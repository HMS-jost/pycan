# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Quick hardware test: two CAN@net Basic devices against each other.

TLV-UDP on 10.41.18.101  <-->  ASCII-UDP on 10.41.18.102
Both connected on CAN1, CAN FD at 1000/4000 kbit/s.
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

CAN_PORT = 1
BITRATE = 1000
DATA_BITRATE = 4000
TIMEOUT = 2.0
BURST_COUNT = 16


def main() -> int:
    # --- Open backends ---
    print("Opening TLV-UDP on 10.41.18.101 ...")
    tlv = CanUdp(host="10.41.18.101", port=19236)
    tlv.open(OpenConfig(transport=Transport.UDP, address="10.41.18.101", port=19236))

    print("Opening ASCII-UDP on 10.41.18.102 ...")
    asc = AsciiCan(host="10.41.18.102", port=19228, transport=Transport.UDP, device_family="basic")
    asc.open(OpenConfig(transport=Transport.UDP, address="10.41.18.102", port=19228, options={"device_family": "basic"}))

    apis = [("tlv", tlv), ("ascii", asc)]

    # --- Configure both for CAN FD (no BRS) ---
    cfg = ControllerConfig(
        can_fd=True,
        bitrate_switch=False,
        arbitration=CanTiming(bitrate_kbit=BITRATE),
        data=CanTiming(bitrate_kbit=DATA_BITRATE),
    )
    accept_all = [
        CanFilter(IdentifierFormat.STANDARD, mask=0, value=0),
        CanFilter(IdentifierFormat.EXTENDED, mask=0, value=0),
    ]

    for name, api in apis:
        print(f"  Configuring {name} @ {BITRATE} kbit/s")
        try:
            api.stop_can(CAN_PORT)
        except Exception:
            pass
        api.init_can(CAN_PORT, cfg)
        try:
            api.clear_filters(CAN_PORT)
        except Exception:
            pass
        for f in accept_all:
            api.add_filter(CAN_PORT, f)
        api.start_can(CAN_PORT)

    # Drain any stale frames
    for _, api in apis:
        while api.receive(CAN_PORT, timeout=0) is not None:
            pass
    time.sleep(0.2)

    results = []

    # --- Test 1: TLV -> ASCII (64 bytes) ---
    msg1 = CanMessage(0x101, bytes(range(64)), IdentifierFormat.EXTENDED, FrameFormat.FD_NO_BRS)
    print(f"\nTest 1: TLV sends 0x{msg1.can_id:03X} FD 64B -> ASCII receives")
    tlv.send(CAN_PORT, msg1)
    rx = _receive_expected(asc, msg1)
    if rx:
        print(f"  PASS  received 0x{rx.can_id:03X} data={rx.data.hex(' ')}")
        results.append(True)
    else:
        print("  FAIL  no matching frame received")
        results.append(False)

    _drain(apis)
    time.sleep(0.2)

    # --- Test 2: ASCII -> TLV (64 bytes) ---
    msg2 = CanMessage(0x202, bytes(range(64)), IdentifierFormat.EXTENDED, FrameFormat.FD_NO_BRS)
    print(f"\nTest 2: ASCII sends 0x{msg2.can_id:03X} FD 64B -> TLV receives")
    asc.send(CAN_PORT, msg2)
    rx = _receive_expected(tlv, msg2)
    if rx:
        print(f"  PASS  received 0x{rx.can_id:03X} data={rx.data.hex(' ')}")
        results.append(True)
    else:
        print("  FAIL  no matching frame received")
        results.append(False)

    _drain(apis)
    time.sleep(0.1)

    # --- Test 3: Burst TLV -> ASCII (64 bytes each) ---
    msgs3 = [
        CanMessage(0x300 + i, bytes([i] + [0xAA] * 63), IdentifierFormat.EXTENDED, FrameFormat.FD_NO_BRS)
        for i in range(BURST_COUNT)
    ]
    print(f"\nTest 3: TLV burst {BURST_COUNT} FD frames -> ASCII receives")
    sent = tlv.send_many(CAN_PORT, msgs3, overall_timeout=TIMEOUT)
    print(f"  sent={sent}/{BURST_COUNT}")
    received_ids = _receive_burst(asc, BURST_COUNT)
    print(f"  received={len(received_ids)}/{BURST_COUNT}")
    if len(received_ids) >= BURST_COUNT:
        print("  PASS")
        results.append(True)
    else:
        missing = sorted(set(m.can_id for m in msgs3) - received_ids)
        print(f"  FAIL  missing: {', '.join(f'0x{x:X}' for x in missing[:8])}")
        results.append(False)

    _drain(apis)
    time.sleep(0.1)

    # --- Test 4: Burst ASCII -> TLV (64 bytes each) ---
    msgs4 = [
        CanMessage(0x400 + i, bytes([i] + [0xBB] * 63), IdentifierFormat.EXTENDED, FrameFormat.FD_NO_BRS)
        for i in range(BURST_COUNT)
    ]
    print(f"\nTest 4: ASCII burst {BURST_COUNT} FD frames -> TLV receives")
    sent = asc.send_many(CAN_PORT, msgs4, overall_timeout=TIMEOUT)
    print(f"  sent={sent}/{BURST_COUNT}")
    received_ids = _receive_burst(tlv, BURST_COUNT)
    print(f"  received={len(received_ids)}/{BURST_COUNT}")
    if len(received_ids) >= BURST_COUNT:
        print("  PASS")
        results.append(True)
    else:
        missing = sorted(set(m.can_id for m in msgs4) - received_ids)
        print(f"  FAIL  missing: {', '.join(f'0x{x:X}' for x in missing[:8])}")
        results.append(False)

    # --- Cleanup ---
    print("\nCleaning up...")
    for _, api in apis:
        try:
            api.stop_can(CAN_PORT)
        except Exception:
            pass
        api.close()

    passed = sum(results)
    total = len(results)
    print(f"\nResult: {passed}/{total} tests passed")
    return 0 if all(results) else 1


def _receive_expected(api, expected: CanMessage):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        rx = api.receive(CAN_PORT, timeout=0.05)
        if rx is not None and rx.can_id == expected.can_id and rx.data == expected.data:
            return rx
    return None


def _receive_burst(api, count: int) -> set:
    received_ids: set[int] = set()
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline and len(received_ids) < count:
        rx = api.receive(CAN_PORT, timeout=0.05)
        if rx is not None:
            received_ids.add(rx.can_id)
    return received_ids


def _drain(apis):
    for _, api in apis:
        while api.receive(CAN_PORT, timeout=0) is not None:
            pass


if __name__ == "__main__":
    sys.exit(main())
