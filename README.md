# pycan

`pycan` is a small transport-independent CAN API for Classic CAN and CAN FD.
It currently provides backends for CAN@net Basic via TLV UDP and ASCII UDP,
CAN@net NT ASCII TCP, and an in-memory virtual bus.

## Install

From a local checkout:

```powershell
python -m pip install .
```

For development:

```powershell
python -m pip install -e .
```

After installation, import the API from the `pycan` package:

```python
from pycan import CanMessage, ControllerConfig, CanTiming, OpenConfig, Transport
from pycan import CanUdp

can = CanUdp()
can.open(OpenConfig(transport=Transport.UDP, address="10.41.18.123", port=19236))
can.init_can(1, ControllerConfig(arbitration=CanTiming(bitrate_kbit=500)))
can.start_can(1)
can.send(1, CanMessage(0x200, b"\x11\x22\x33\x44"))
can.close()
```

## Layout

- `src/pycan/` - Package source code and backend implementations.
- `tests/` - Unit tests and the manual hardware integration suite.
- `docs/` - User documentation and chat handoff notes.
- `pyproject.toml` - Build and packaging metadata.

## Backends

- `pycan.CanUdp` - CAN@net Basic TLV UDP backend.
- `pycan.AsciiCan` - CAN@net ASCII backend for NT/TCP and Basic/UDP.
- `pycan.Virtual` - In-memory virtual backend for local tests.

## Demo

The package installs a `pycan-demo` console script:

```powershell
pycan-demo --backend tlv-udp --address 10.41.18.123 --bitrate 500
pycan-demo --backend ascii-tcp --address 10.41.18.10 --bitrate 500
pycan-demo --backend ascii-udp --address 10.41.18.11 --bitrate 500
pycan-demo --backend virtual --device vcan0
```

You can also run the demo module directly:

```powershell
python -m pycan.demo --backend virtual --device vcan0
```

## Documentation

See `docs/user_guide.md` for API concepts, initialization snippets,
send/receive examples, and backend-specific notes.

## BusMonitor

The package includes a graphical CAN BusMonitor (Tkinter GUI) that supports all
pycan backends. After installation, start it from the command line:

```powershell
pcbm
```

Features:
- Backend selection: TLV-UDP, ASCII-TCP, ASCII-UDP
- IP address and CAN port configuration (1–4)
- Configurable bitrate
- Live receive display with timestamps, hex data, and ASCII decode
- Transmit command line with history
- CAN FD support (flags `F` for FD no BRS, `B` for FD+BRS, up to 64 bytes)
- Trace file logging

Transmit syntax:

```
<id> [E][R][F][B] [<data bytes> ...]
```

Examples:

```
100 11 22 33 44                Standard CAN, ID 0x100, 4 bytes
1ABCDEF0 E 01 02 03            Extended 29-bit ID
200 B 00 01 02 ... (64 bytes)   CAN FD with BRS
```

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for
details.