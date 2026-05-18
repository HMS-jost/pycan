# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Simple CAN@net NT demo: send 4 messages, receive for 60 seconds.

Usage:
    python demos/nt_send_receive.py --address 10.41.18.10
"""

from __future__ import annotations

import argparse
import time

from pycan.ascii_can import ASCII_PORT, AsciiCan
from pycan.can_api import (
    CanFilter,
    CanMessage,
    CanTiming,
    ControllerConfig,
    IdentifierFormat,
    OpenConfig,
    Transport,
)

CAN_PORT = 1
BITRATE = 500
DURATION = 60


def main() -> int:
    parser = argparse.ArgumentParser(description="CAN@net NT send/receive demo")
    parser.add_argument("--address", required=True, help="CAN@net NT IP address")
    parser.add_argument("--port", type=int, default=ASCII_PORT, help="TCP port")
    args = parser.parse_args()

    can = AsciiCan(host=args.address, port=args.port, transport=Transport.TCP, device_family="nt")
    config = OpenConfig(transport=Transport.TCP, address=args.address, port=args.port,
                        options={"device_family": "nt"})

    print(f"Connecting to CAN@net NT at {args.address}:{args.port} ...")
    try:
        info = can.open(config)
        print(f"  Device: {info.name or info.device_id}")

        # Configure CAN1: 500 kBit, classic CAN
        can.init_can(CAN_PORT, ControllerConfig(
            arbitration=CanTiming(bitrate_kbit=BITRATE),
        ))

        # Filter: accept all standard (11-bit) IDs
        can.clear_filters(CAN_PORT)
        can.add_filter(CAN_PORT, CanFilter(IdentifierFormat.STANDARD, mask=0, value=0))

        can.start_can(CAN_PORT)
        print(f"  CAN1 started at {BITRATE} kBit/s, filter: all standard IDs\n")

        # Send 4 messages with IDs 0x100..0x103
        for i in range(4):
            msg = CanMessage(0x100 + i, bytes([i, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77]))
            can.send(CAN_PORT, msg)
            print(f"  TX: {msg}")

        print(f"\nReceiving for {DURATION}s (status every second) ...\n")

        rx_count = 0
        start = time.monotonic()
        next_status = start + 1.0

        while time.monotonic() - start < DURATION:
            msg = can.receive(CAN_PORT, timeout=0.1)
            if msg is not None:
                rx_count += 1
                print(f"  RX[{rx_count}]: {msg}")

            if time.monotonic() >= next_status:
                status = can.get_status(CAN_PORT)
                elapsed = time.monotonic() - start
                print(f"  [{elapsed:.0f}s] {status.status_text}  rx={rx_count}")
                next_status += 1.0

        print(f"\n--- Done: {rx_count} messages received in {DURATION}s ---")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        can.close()


if __name__ == "__main__":
    raise SystemExit(main())
