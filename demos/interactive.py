# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Interactive demo for the common CAN API implementations.

Run after installing the package, for example:

    pycan-demo --backend tlv-udp --address 10.41.18.123
    pycan-demo --backend ascii-tcp --address 10.41.18.10
    pycan-demo --backend ascii-udp --address 10.41.18.11
    pycan-demo --backend virtual --device vcan0

For compatibility with the original TLV demo, ``pycan-demo 10.41.18.123``
still selects the TLV UDP backend.
"""

from __future__ import annotations

import argparse
import sys
import time

if sys.platform == "win32":
    import msvcrt

    def _kbhit() -> bool:
        return msvcrt.kbhit()

    def _getch() -> bytes:
        return msvcrt.getch()
else:
    import select
    import termios
    import tty

    def _kbhit() -> bool:
        return select.select([sys.stdin], [], [], 0)[0] != []

    def _getch() -> bytes:
        return sys.stdin.read(1).encode()

from pycan.ascii_can import ASCII_PORT, AsciiCan
from pycan.can_api import (
    CanApi,
    CanFilter,
    CanMessage,
    CanStatus,
    CanTiming,
    ControllerConfig,
    DeviceInfo,
    FrameFormat,
    IdentifierFormat,
    OpenConfig,
    Transport,
)
from pycan.canudp import CanUdp
from pycan.virtual import Virtual

DEFAULT_TLV_ADDRESS = "10.41.18.123"
DEFAULT_TLV_PORT = 19236
CAN_PORT = 1

TEST_ID = 0x200
TEST_DATA = bytes([0x11, 0x22, 0x33, 0x44])
EXT_ID = 0x1234567
EXT_DATA = b"EXT!"
FD_ID = 0x200
FD_DATA = bytes(range(64))
LOAD_ID = 0x123
DEFAULT_LOAD_COUNT = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive demo for the common CAN API backends.")
    parser.add_argument("legacy_address", nargs="?", help="Backward-compatible TLV UDP address argument")
    parser.add_argument(
        "--backend",
        choices=("tlv-udp", "ascii-tcp", "ascii-udp", "virtual"),
        default="tlv-udp",
        help="CAN API backend to use",
    )
    parser.add_argument("--address", default="", help="Device IP address for network backends")
    parser.add_argument("--port", type=int, default=0, help="Network service port")
    parser.add_argument("--device", default="vcan0", help="Virtual device id")
    parser.add_argument("--bitrate", type=int, default=500, help="Arbitration bitrate in kbit/s")
    parser.add_argument("--data-bitrate", type=int, default=2000, help="CAN FD data bitrate in kbit/s")
    parser.add_argument("--fd", action="store_true", help="Enable CAN FD mode (default is Classic CAN)")
    parser.add_argument("--load-count", type=int, default=DEFAULT_LOAD_COUNT, help="Messages sent by the load test")
    parser.add_argument("--open-timeout", type=float, default=3.0, help="TLV UDP open timeout in seconds")
    return parser.parse_args()


def make_backend(args: argparse.Namespace) -> tuple[CanApi, OpenConfig, str]:
    address = args.address or args.legacy_address or DEFAULT_TLV_ADDRESS
    if args.backend == "tlv-udp":
        port = args.port or DEFAULT_TLV_PORT
        return (
            CanUdp(host=address, port=port),
            OpenConfig(transport=Transport.UDP, address=address, port=port),
            f"TLV UDP {address}:{port}",
        )
    if args.backend == "ascii-tcp":
        port = args.port or ASCII_PORT
        return (
            AsciiCan(host=address, port=port, transport=Transport.TCP, device_family="nt"),
            OpenConfig(transport=Transport.TCP, address=address, port=port, options={"device_family": "nt"}),
            f"ASCII TCP {address}:{port}",
        )
    if args.backend == "ascii-udp":
        port = args.port or ASCII_PORT
        return (
            AsciiCan(host=address, port=port, transport=Transport.UDP, device_family="basic"),
            OpenConfig(transport=Transport.UDP, address=address, port=port, options={"device_family": "basic"}),
            f"ASCII UDP {address}:{port}",
        )
    return (
        Virtual(),
        OpenConfig(transport=Transport.VIRTUAL, device_id=args.device),
        f"Virtual {args.device}",
    )


def open_backend(can: CanApi, config: OpenConfig, args: argparse.Namespace) -> DeviceInfo:
    if isinstance(can, CanUdp):
        return can.open(config, timeout=args.open_timeout)
    return can.open(config)


def controller_config(args: argparse.Namespace) -> ControllerConfig:
    return ControllerConfig(
        can_fd=args.fd,
        bitrate_switch=args.fd,
        arbitration=CanTiming(bitrate_kbit=args.bitrate),
        data=CanTiming(bitrate_kbit=args.data_bitrate if args.fd else 0),
    )


def read_status(can: CanApi) -> CanStatus:
    if isinstance(can, CanUdp):
        return can.status(timeout=1.0)
    return can.get_status(CAN_PORT)


def configure_can(can: CanApi, args: argparse.Namespace) -> None:
    can.init_can(CAN_PORT, controller_config(args))
    can.add_filter(CAN_PORT, CanFilter(IdentifierFormat.STANDARD, mask=0, value=0))
    can.add_filter(CAN_PORT, CanFilter(IdentifierFormat.EXTENDED, mask=0, value=0))
    can.start_can(CAN_PORT)


def print_status(can: CanApi, prefix: str = "Status") -> None:
    sts = read_status(can)
    print(f"  [{prefix}] {sts.status_text}  tx_free={sts.tx_free}  err={sts.error_code}")


def drain_receive(can: CanApi, rx_count: int) -> int:
    last_msg = None
    while True:
        msg = can.receive(CAN_PORT, timeout=0.05 if last_msg is None else 0)
        if msg is None:
            break
        rx_count += 1
        last_msg = msg
    if last_msg is not None:
        print(f"  RX[{rx_count}] {last_msg}  ts={last_msg.timestamp_us}us")
    return rx_count


def run_load_test(can: CanApi, count: int) -> int:
    print(f"  LOAD TEST: sending {count} messages (ID 0x{LOAD_ID:03X}) ...")
    messages = [
        CanMessage(
            LOAD_ID,
            bytes([index & 0xFF, (index >> 8) & 0xFF, 0, 0, 0, 0, 0, 0]),
        )
        for index in range(count)
    ]
    start = time.perf_counter()
    sent = can.send_many(CAN_PORT, messages, overall_timeout=max(10.0, count * 0.02))
    elapsed = time.perf_counter() - start
    rate = sent / elapsed if elapsed > 0 else 0
    print(f"  LOAD TEST done: {sent} sent in {elapsed:.3f}s ({rate:.0f} msg/s)")
    return sent


def main() -> int:
    args = parse_args()
    can, open_config, label = make_backend(args)
    print(f"Connecting to {label} ...")

    try:
        info = open_backend(can, open_config, args)
        print(f"  Device: {info.name or info.device_id}")
        configure_can(can, args)
        print_status(can, "STATUS")

        tx_count = 0
        rx_count = 0
        next_status = time.monotonic() + 5.0
        print("\nReady. Press 't' STD, 'e' EXT, 'f' CAN-FD, 'l' load, 'q' quit.")

        if sys.platform != "win32":
            _old_term = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

        try:
            while True:
                if _kbhit():
                    key = _getch().lower()
                    if key == b"q":
                        break
                    if key == b"t":
                        tx_count += 1
                        msg = CanMessage(TEST_ID, TEST_DATA)
                        print(f"  TX[{tx_count}] {msg}")
                        can.send(CAN_PORT, msg)
                    elif key == b"e":
                        tx_count += 1
                        msg = CanMessage(EXT_ID, EXT_DATA, id_format=IdentifierFormat.EXTENDED)
                        print(f"  TX[{tx_count}] {msg}")
                        can.send(CAN_PORT, msg)
                    elif key == b"f":
                        tx_count += 1
                        msg = CanMessage(FD_ID, FD_DATA, frame_format=FrameFormat.FD_BRS)
                        print(f"  TX[{tx_count}] {msg}")
                        can.send(CAN_PORT, msg)
                    elif key == b"l":
                        try:
                            tx_count += run_load_test(can, args.load_count)
                        except TimeoutError:
                            print("  LOAD TEST aborted: timeout waiting for TX space")

                rx_count = drain_receive(can, rx_count)

                if time.monotonic() >= next_status:
                    next_status = time.monotonic() + 5.0
                    try:
                        print_status(can, "STATUS")
                    except Exception as exc:
                        print(f"  [STATUS] {exc}")
        finally:
            if sys.platform != "win32":
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _old_term)

        print(f"\n--- Summary: {tx_count} sent, {rx_count} received ---")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        can.close()


if __name__ == "__main__":
    sys.exit(main())
