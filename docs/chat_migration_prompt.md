# Chat Migration Prompt

Use this file to continue the CAN API work in a fresh chat. Paste the prompt
below into the new chat.

## Prompt To Paste

```text
We are working on the `pycan` repository: a small installable Python/C CAN API
project that grew out of a CAN@net Basic TLV UDP test interface. Please continue
from the existing code instead of redesigning it from scratch.

Current goals:
- Maintain a small transport-independent CAN API for Classic CAN and CAN FD.
- Keep the API usable for CAN@net Basic TLV UDP, CAN@net ASCII UDP, CAN@net NT
  ASCII TCP, and a virtual in-memory backend.
- Keep the public send surface simple: send() and send_many(); send_many() is
  the backpressure-aware burst API.
- Keep unit tests hardware-free and keep hardware tests manual/explicit.
- Prefer small, focused changes that match the existing style.

Current layout:
- pyproject.toml: setuptools package metadata.
- src/pycan/can_api.py: common Python API, dataclasses, enums, ABC.
- src/pycan/can_api.h: C API sketch matching the same concepts.
- src/pycan/canudp.py: CAN@net Basic TLV UDP backend.
- src/pycan/ascii_can.py: CAN@net ASCII backend. CAN@net NT uses TCP, CAN@net Basic
  uses UDP. ASCII receive timestamps are added client-side.
- src/pycan/virtual.py: in-memory virtual backend for local tests.
- src/pycan/demo.py: interactive CLI demo exposed as `pycan-demo`.
- tests/test_virtual.py: unit tests for the virtual backend.
- tests/test_ascii_can.py: unit tests for the ASCII backend using a fake transport.
- tests/can_matrix_test.py: manual hardware integration suite for three physical
  interfaces connected on CAN1.
- README.md: API project overview.
- docs/user_guide.md: user-facing API documentation and snippets.
- docs/chat_migration_prompt.md: this handoff file.

Important API decisions:
- send_many_flow_controlled() was intentionally removed from the public API.
- send_many() is the central backpressure-aware burst method.
- send() sends exactly one message. Backend behavior should be safe, but the TLV
  protocol has no per-frame bus-delivery acknowledgement.
- process_cycle() is for cooperative background processing and callback dispatch.
- get_status() is currently inconsistent: virtual returns local/cached state;
  UDP and ASCII currently perform active status queries. The intended long-term
  design is cached get_status() plus a separate explicit refresh/request method.
- Hardware bus delivery must be verified by receiving the message on another
  interface. Do not compare timestamps across all backends because ASCII adds
  timestamps client-side.

Validation commands from the repository root:

python -m py_compile src\pycan\can_api.py src\pycan\canudp.py src\pycan\ascii_can.py src\pycan\virtual.py src\pycan\demo.py tests\test_virtual.py tests\test_ascii_can.py tests\can_matrix_test.py
python -m unittest discover -s tests -p "test_*.py"
python -m pip install -e .
python -c "import pycan; print(pycan.CanMessage(0x123, b'abc'))"

Demo examples:

pycan-demo --backend tlv-udp --address 10.41.18.123 --bitrate 500
pycan-demo --backend ascii-tcp --address 10.41.18.10 --bitrate 500
pycan-demo --backend ascii-udp --address 10.41.18.11 --bitrate 500
pycan-demo --backend virtual --device vcan0

The old TLV shortcut still works:

pycan-demo 10.41.18.123

Manual hardware integration suite examples:

python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests all
python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests bitrates --bitrates 125,250,500,1000
python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests types --include-fd --bitrate 500 --data-bitrate 2000
python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests burst --burst-count 128

Known follow-up topics:
- Replace placeholder package metadata once repository URLs are known.
- Clarify status semantics: cached get_status() plus active refresh_status() or
  request_status().
- Review send() backpressure semantics per backend. send_many() is clear, but
  send() may still need backend-local TX credit handling if it should always wait
  instead of sending immediately.
- Keep hardware-specific CAN@net TLV/NanoBasic notes separate from common API docs.

When editing:
- Preserve the package install workflow and the lightweight test commands.
- Keep hardware tests out of normal unittest discovery unless explicitly mocked.
- Run py_compile and unittest discovery after code changes.
```

## Short Version

```text
Continue this `pycan` repository from the current files. It has a common API in
src/pycan/can_api.py, implementations for TLV UDP, ASCII TCP/UDP, and virtual
CAN in src/pycan/, unit tests in tests/, a manual hardware suite in
tests/can_matrix_test.py, and user docs in docs/. Keep send() and send_many() as
the only public send APIs; send_many() is backpressure-aware. Preserve the
installable package workflow and validate with py_compile plus unittest
discovery.
```
