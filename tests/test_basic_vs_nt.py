# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Hardware test: CAN@net Basic (TLV-UDP) vs CAN@net NT 420 (ASCII-TCP).

TLV-UDP on 10.41.18.101 CAN1  <-->  ASCII-TCP on 10.41.18.10 CAN3
Tests: Classic CAN, CAN FD NO_BRS, CAN FD BRS — each with Standard and Extended IDs.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pycan.canudp import CanUdp
from pycan.ascii_can import AsciiCan
from pycan.can_api import (
    CanFilter,
    CanMessage,
    CanTiming,
    ControllerConfig,
    FrameFormat,
    IdentifierFormat,
    OpenConfig,
    Transport,
)

TLV_HOST = "10.41.18.101"
TLV_PORT_NUM = 19236
TLV_CAN = 1

NT_HOST = "10.41.18.20"
NT_PORT_NUM = 19228
NT_CAN = 3

CLASSIC_BITRATE = 500
FD_BITRATE = 1000
FD_DATA_BITRATE = 4000
TIMEOUT = 2.0
BURST_COUNT = 16


def main() -> int:
    print(f"Opening TLV-UDP on {TLV_HOST} (CAN{TLV_CAN}) ...")
    tlv = CanUdp(host=TLV_HOST, port=TLV_PORT_NUM)
    tlv.open(OpenConfig(transport=Transport.UDP, address=TLV_HOST, port=TLV_PORT_NUM))

    print(f"Opening ASCII-TCP on {NT_HOST} (CAN{NT_CAN}) ...")
    nt = AsciiCan(host=NT_HOST, port=NT_PORT_NUM, transport=Transport.TCP, device_family="nt")
    nt.open(OpenConfig(transport=Transport.TCP, address=NT_HOST, port=NT_PORT_NUM, options={"device_family": "nt"}))

    apis = [("tlv", tlv, TLV_CAN), ("nt", nt, NT_CAN)]
    results: list[tuple[str, bool]] = []

    # ---- Classic CAN ----
    print("\n========== Classic CAN @ 500 kbit/s ==========")
    _configure_all(apis, _classic_config(CLASSIC_BITRATE))

    results += _run_pair(apis, "Classic STD", 0x110,
                         IdentifierFormat.STANDARD, FrameFormat.CLASSIC, b"\xDE\xAD\xBE\xEF\x01\x02\x03\x04")
    results += _run_pair(apis, "Classic EXT", 0x1ABCDEF0,
                         IdentifierFormat.EXTENDED, FrameFormat.CLASSIC, b"\xCA\xFE\xBA\xBE\x05\x06\x07\x08")
    results += _run_burst_pair(apis, "Classic Burst STD", 0x500,
                               IdentifierFormat.STANDARD, FrameFormat.CLASSIC, 8)

    # ---- CAN FD NO_BRS ----
    print("\n========== CAN FD NO_BRS @ 1000 kbit/s ==========")
    _configure_all(apis, _fd_config(FD_BITRATE, FD_DATA_BITRATE, brs=False))

    results += _run_pair(apis, "FD NO_BRS STD", 0x210,
                         IdentifierFormat.STANDARD, FrameFormat.FD_NO_BRS, bytes(range(64)))
    results += _run_pair(apis, "FD NO_BRS EXT", 0x1ABCDEF1,
                         IdentifierFormat.EXTENDED, FrameFormat.FD_NO_BRS, bytes(range(64)))
    results += _run_burst_pair(apis, "FD NO_BRS Burst EXT", 0x600,
                               IdentifierFormat.EXTENDED, FrameFormat.FD_NO_BRS, 64)

    # ---- CAN FD BRS ----
    print("\n========== CAN FD BRS @ 1000/4000 kbit/s ==========")
    _configure_all(apis, _fd_config(FD_BITRATE, FD_DATA_BITRATE, brs=True))

    results += _run_pair(apis, "FD BRS STD", 0x310,
                         IdentifierFormat.STANDARD, FrameFormat.FD_BRS, bytes(range(64)))
    results += _run_pair(apis, "FD BRS EXT", 0x1ABCDEF2,
                         IdentifierFormat.EXTENDED, FrameFormat.FD_BRS, bytes(range(64)))
    results += _run_burst_pair(apis, "FD BRS Burst STD", 0x700,
                               IdentifierFormat.STANDARD, FrameFormat.FD_BRS, 64)

    # ---- Cleanup ----
    print("\nCleaning up...")
    for name, api, can_port in apis:
        try:
            api.stop_can(can_port)
        except Exception:
            pass
        api.close()

    # ---- Summary ----
    print("\n========== Summary ==========")
    passed = 0
    for label, ok in results:
        state = "PASS" if ok else "FAIL"
        print(f"  {state}  {label}")
        passed += ok
    total = len(results)
    print(f"\n{passed}/{total} tests passed")
    return 0 if passed == total else 1


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _classic_config(bitrate: int) -> ControllerConfig:
    return ControllerConfig(arbitration=CanTiming(bitrate_kbit=bitrate))


def _fd_config(bitrate: int, data_bitrate: int, brs: bool) -> ControllerConfig:
    return ControllerConfig(
        can_fd=True,
        bitrate_switch=brs,
        arbitration=CanTiming(bitrate_kbit=bitrate),
        data=CanTiming(bitrate_kbit=data_bitrate),
    )


def _configure_all(apis, cfg: ControllerConfig) -> None:
    accept_all = [
        CanFilter(IdentifierFormat.STANDARD, mask=0, value=0),
        CanFilter(IdentifierFormat.EXTENDED, mask=0, value=0),
    ]
    for name, api, can_port in apis:
        print(f"  Configuring {name} CAN{can_port}")
        try:
            api.stop_can(can_port)
        except Exception:
            pass
        api.init_can(can_port, cfg)
        try:
            api.clear_filters(can_port)
        except Exception:
            pass
        for f in accept_all:
            api.add_filter(can_port, f)
        api.start_can(can_port)
    _drain(apis)
    time.sleep(0.2)


def _drain(apis) -> None:
    for _, api, can_port in apis:
        while api.receive(can_port, timeout=0) is not None:
            pass


# ---------------------------------------------------------------------------
# Single-frame tests (both directions)
# ---------------------------------------------------------------------------

def _run_pair(apis, label: str, can_id: int,
              id_fmt: IdentifierFormat, frame_fmt: FrameFormat,
              data: bytes) -> list[tuple[str, bool]]:
    results = []
    names = [a[0] for a in apis]
    for sender_idx in range(len(apis)):
        receiver_idx = 1 - sender_idx
        s_name, s_api, s_can = apis[sender_idx]
        r_name, r_api, r_can = apis[receiver_idx]
        tag = f"{label}: {s_name}->{ r_name}"
        msg = CanMessage(can_id + sender_idx, data, id_fmt, frame_fmt)
        _drain(apis)
        print(f"  {tag}  0x{msg.can_id:X} ({len(data)}B)")
        s_api.send(s_can, msg)
        rx = _receive_expected(r_api, r_can, msg)
        if rx:
            print(f"    PASS  data[0..3]={rx.data[:4].hex(' ')}")
            results.append((tag, True))
        else:
            print(f"    FAIL")
            results.append((tag, False))
    return results


# ---------------------------------------------------------------------------
# Burst tests (both directions)
# ---------------------------------------------------------------------------

def _run_burst_pair(apis, label: str, base_id: int,
                    id_fmt: IdentifierFormat, frame_fmt: FrameFormat,
                    payload_len: int) -> list[tuple[str, bool]]:
    results = []
    for sender_idx in range(len(apis)):
        receiver_idx = 1 - sender_idx
        s_name, s_api, s_can = apis[sender_idx]
        r_name, r_api, r_can = apis[receiver_idx]
        tag = f"{label}: {s_name}->{r_name} x{BURST_COUNT}"
        offset = sender_idx * 0x40
        msgs = [
            CanMessage(base_id + offset + i,
                       bytes([i & 0xFF]) + bytes([0xAA + sender_idx] * (payload_len - 1)),
                       id_fmt, frame_fmt)
            for i in range(BURST_COUNT)
        ]
        _drain(apis)
        print(f"  {tag}")
        sent = s_api.send_many(s_can, msgs, overall_timeout=TIMEOUT)
        received_ids = _receive_burst(r_api, r_can, BURST_COUNT)
        ok = len(received_ids) >= BURST_COUNT
        print(f"    sent={sent}/{BURST_COUNT}  received={len(received_ids)}/{BURST_COUNT}  {'PASS' if ok else 'FAIL'}")
        results.append((tag, ok))
    return results


# ---------------------------------------------------------------------------
# Receive helpers
# ---------------------------------------------------------------------------

def _receive_expected(api, can_port: int, expected: CanMessage):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        rx = api.receive(can_port, timeout=0.05)
        if rx is not None and rx.can_id == expected.can_id and rx.data == expected.data:
            return rx
    return None


def _receive_burst(api, can_port: int, count: int) -> set:
    received_ids: set[int] = set()
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and len(received_ids) < count:
        rx = api.receive(can_port, timeout=0.05)
        if rx is not None:
            received_ids.add(rx.can_id)
    return received_ids


if __name__ == "__main__":
    sys.exit(main())
