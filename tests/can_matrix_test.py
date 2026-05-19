# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Manual hardware integration suite for the common CAN API.

Connect the CAN-FD-capable port of each interface to the same terminated CAN
bus, then run this script.  The CAN@net NT 420 uses CAN3 (the only FD-capable
port); CAN@net Basic and TLV-UDP devices use CAN1; VCI interfaces use the
port given via --vci-port (default 1).  The suite opens up to four endpoints
and exercises bitrate configuration, frame formats, filters, single
send/receive, and burst sending across all backend combinations.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pycan.ascii_can import ASCII_PORT, AsciiCan
from pycan.can_api import (
    CanApi,
    CanFilter,
    CanMessage,
    CanTiming,
    ControllerConfig,
    FrameFormat,
    FrameType,
    IdentifierFormat,
    OpenConfig,
    Transport,
)
from pycan.canudp import CanUdp
from pycan.vci_can import VciCan

TLV_PORT = 19236
# CAN@net NT 420: only CAN3 supports CAN FD
NT_CAN_PORT = 3
BASIC_CAN_PORT = 1


@dataclass(slots=True)
class Node:
    name: str
    api: CanApi
    can_port: int = 1


@dataclass(slots=True)
class ScenarioResult:
    name: str
    passed: bool
    message: str = ""


def _split_endpoint(value: str, default_port: int) -> tuple[str, int]:
    if ":" not in value:
        return value, default_port
    host, port_text = value.rsplit(":", 1)
    return host, int(port_text)


def _make_ascii_tcp(endpoint: str) -> Node:
    host, port = _split_endpoint(endpoint, ASCII_PORT)
    api = AsciiCan(host=host, port=port, transport=Transport.TCP, device_family="nt")
    api.open(OpenConfig(transport=Transport.TCP, address=host, port=port, options={"device_family": "nt"}))
    return Node("ascii-tcp", api, can_port=NT_CAN_PORT)


def _make_ascii_udp(endpoint: str) -> Node:
    host, port = _split_endpoint(endpoint, ASCII_PORT)
    api = AsciiCan(host=host, port=port, transport=Transport.UDP, device_family="basic")
    api.open(OpenConfig(transport=Transport.UDP, address=host, port=port, options={"device_family": "basic"}))
    return Node("ascii-udp", api, can_port=BASIC_CAN_PORT)


def _make_tlv_udp(endpoint: str) -> Node:
    host, port = _split_endpoint(endpoint, TLV_PORT)
    api = CanUdp(host=host, port=port)
    api.open(OpenConfig(transport=Transport.UDP, address=host, port=port))
    return Node("tlv-udp", api, can_port=BASIC_CAN_PORT)


def _make_vci(serial_num: str, can_port: int) -> Node:
    api = VciCan()
    api.open(OpenConfig(transport=Transport.VCI, device_id=serial_num))
    return Node("vci", api, can_port=can_port)


class CanHardwareSuite:
    def __init__(self, nodes: list[Node], timeout: float):
        self.nodes = nodes
        self.timeout = timeout

    def close(self) -> None:
        for node in self.nodes:
            try:
                node.api.stop_can(node.can_port)
            except Exception:
                pass
            node.api.close()

    def configure_all(
        self,
        config: ControllerConfig,
        filters: Optional[Iterable[CanFilter]] = None,
    ) -> None:
        filter_list = list(filters) if filters is not None else self._accept_all_filters()
        for node in self.nodes:
            self._configure_node(node, config, filter_list)
        self.drain_all()

    def _configure_node(self, node: Node, config: ControllerConfig, filters: list[CanFilter]) -> None:
        print(f"  configuring {node.name} (CAN{node.can_port})")
        try:
            node.api.stop_can(node.can_port)
        except Exception:
            pass
        node.api.init_can(node.can_port, config)
        for can_filter in filters:
            node.api.add_filter(node.can_port, can_filter)
        node.api.start_can(node.can_port)

    @staticmethod
    def _accept_all_filters() -> list[CanFilter]:
        return [
            CanFilter(IdentifierFormat.STANDARD, mask=0, value=0),
            CanFilter(IdentifierFormat.EXTENDED, mask=0, value=0),
        ]

    def drain_all(self) -> None:
        for node in self.nodes:
            while node.api.receive(node.can_port, timeout=0) is not None:
                pass

    def receivers_for(self, sender: Node) -> list[Node]:
        return [node for node in self.nodes if node is not sender]

    def test_smoke(self, bitrate: int) -> None:
        self.configure_all(self.classic_config(bitrate))
        for sequence, sender in enumerate(self.nodes, start=1):
            message = CanMessage(
                can_id=0x240 + sequence,
                data=bytes([sequence, 0x55, 0xAA, len(sender.name)]),
                id_format=IdentifierFormat.STANDARD,
                frame_format=FrameFormat.CLASSIC,
            )
            self.send_and_expect(sender, message)

    def test_bitrates(self, bitrates: list[int]) -> None:
        for bitrate in bitrates:
            print(f"  bitrate {bitrate} kbit/s")
            self.configure_all(self.classic_config(bitrate))
            sender = self.nodes[0]
            message = CanMessage(0x280 + bitrate % 0x40, bytes([bitrate & 0xFF]))
            self.send_and_expect(sender, message)

    def test_message_types(self, bitrate: int, data_bitrate: int, include_fd: bool) -> None:
        self.configure_all(self.classic_config(bitrate))
        classic_messages = [
            CanMessage(0x301, b"std", IdentifierFormat.STANDARD, FrameFormat.CLASSIC),
            CanMessage(0x1234567, b"ext", IdentifierFormat.EXTENDED, FrameFormat.CLASSIC),
            CanMessage(0x302, bytes(4), IdentifierFormat.STANDARD, FrameFormat.CLASSIC, FrameType.REMOTE),
        ]
        self._send_message_set(classic_messages)

        if include_fd:
            self.configure_all(self.fd_config(bitrate, data_bitrate))
            fd_messages = [
                CanMessage(0x351, bytes(range(12)), IdentifierFormat.STANDARD, FrameFormat.FD_NO_BRS),
                CanMessage(0x1234568, bytes(range(32)), IdentifierFormat.EXTENDED, FrameFormat.FD_BRS),
            ]
            self._send_message_set(fd_messages)

    def test_filters(self, bitrate: int) -> None:
        filters = [CanFilter(IdentifierFormat.STANDARD, mask=0x700, value=0x300)]
        self.configure_all(self.classic_config(bitrate), filters)
        for sender in self.nodes:
            blocked = CanMessage(0x221, b"blocked")
            allowed = CanMessage(0x321, b"allowed")
            self.drain_all()
            print(f"  {sender.name} sends blocked 0x{blocked.can_id:X} and allowed 0x{allowed.can_id:X}")
            sender.api.send(sender.can_port, blocked)
            sender.api.send(sender.can_port, allowed)
            for receiver in self.receivers_for(sender):
                self.expect_allowed_without_forbidden(receiver, allowed, blocked.can_id)

    def test_burst(self, bitrate: int, count: int) -> None:
        self.configure_all(self.classic_config(bitrate))
        for sender_index, sender in enumerate(self.nodes, start=1):
            base_id = 0x400 + sender_index * 0x40
            messages = [
                CanMessage(base_id + index, bytes([sender_index, index & 0xFF, 0x5A]))
                for index in range(count)
            ]
            self.drain_all()
            print(f"  {sender.name} sends burst of {count} frames")
            sent = sender.api.send_many(sender.can_port, messages, overall_timeout=max(self.timeout, count * 0.02))
            if sent != count:
                raise AssertionError(f"{sender.name} sent {sent}/{count} burst frames")
            for receiver in self.receivers_for(sender):
                self.expect_burst(receiver, messages)

    def _send_message_set(self, messages: list[CanMessage]) -> None:
        sequence = 1
        for message in messages:
            for sender in self.nodes:
                tagged = self._tag_message(message, sequence)
                sequence += 1
                self.send_and_expect(sender, tagged)

    @staticmethod
    def _tag_message(message: CanMessage, sequence: int) -> CanMessage:
        if message.frame_type == FrameType.REMOTE:
            return CanMessage(
                message.can_id + sequence,
                message.data,
                message.id_format,
                message.frame_format,
                message.frame_type,
            )
        return CanMessage(
            message.can_id + sequence,
            bytes([sequence & 0xFF]) + message.data,
            message.id_format,
            message.frame_format,
            message.frame_type,
        )

    def send_and_expect(self, sender: Node, message: CanMessage) -> None:
        self.drain_all()
        print(f"  {sender.name} sends {self.describe(message)}")
        sender.api.send_many(sender.can_port, [message], overall_timeout=self.timeout)
        for receiver in self.receivers_for(sender):
            received = self.receive_expected(receiver, message)
            print(f"    {receiver.name} received timestamp_us={received.timestamp_us}")

    def receive_expected(self, receiver: Node, expected: CanMessage) -> CanMessage:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            message = receiver.api.receive(receiver.can_port, timeout=min(0.05, max(0.0, deadline - time.monotonic())))
            if message is None:
                continue
            if self.message_matches(message, expected):
                return message
            raise AssertionError(
                f"{receiver.name} received unexpected {self.describe(message)}, expected {self.describe(expected)}"
            )
        raise AssertionError(f"{receiver.name} did not receive {self.describe(expected)}")

    def expect_allowed_without_forbidden(self, receiver: Node, allowed: CanMessage, forbidden_id: int) -> None:
        deadline = time.monotonic() + self.timeout
        saw_allowed = False
        while time.monotonic() < deadline:
            message = receiver.api.receive(receiver.can_port, timeout=min(0.05, max(0.0, deadline - time.monotonic())))
            if message is None:
                continue
            if message.can_id == forbidden_id:
                raise AssertionError(f"{receiver.name} received filtered frame 0x{forbidden_id:X}")
            if self.message_matches(message, allowed):
                saw_allowed = True
                break
        if not saw_allowed:
            raise AssertionError(f"{receiver.name} did not receive allowed filtered frame")

    def expect_burst(self, receiver: Node, expected_messages: list[CanMessage]) -> None:
        expected_by_id = {message.can_id: message for message in expected_messages}
        received_ids: set[int] = set()
        deadline = time.monotonic() + max(self.timeout, len(expected_messages) * 0.02)
        while time.monotonic() < deadline and len(received_ids) < len(expected_by_id):
            message = receiver.api.receive(receiver.can_port, timeout=min(0.05, max(0.0, deadline - time.monotonic())))
            if message is None:
                continue
            expected = expected_by_id.get(message.can_id)
            if expected is None:
                raise AssertionError(f"{receiver.name} received unexpected burst frame {self.describe(message)}")
            if not self.message_matches(message, expected):
                raise AssertionError(f"{receiver.name} received malformed burst frame {self.describe(message)}")
            received_ids.add(message.can_id)
        missing = sorted(set(expected_by_id) - received_ids)
        if missing:
            formatted = ", ".join(f"0x{can_id:X}" for can_id in missing[:8])
            raise AssertionError(f"{receiver.name} missed {len(missing)} burst frames: {formatted}")

    @staticmethod
    def message_matches(actual: CanMessage, expected: CanMessage) -> bool:
        if actual.can_id != expected.can_id:
            return False
        if actual.id_format != expected.id_format:
            return False
        if actual.frame_format != expected.frame_format:
            return False
        if actual.frame_type != expected.frame_type:
            return False
        if expected.frame_type == FrameType.REMOTE:
            return actual.dlc == expected.dlc
        return actual.data == expected.data

    @staticmethod
    def describe(message: CanMessage) -> str:
        if message.frame_type == FrameType.REMOTE:
            payload = f"dlc={message.dlc}"
        else:
            payload = message.data.hex(" ")
        return f"0x{message.can_id:X} {message.format_str} {payload}"

    @staticmethod
    def classic_config(bitrate: int) -> ControllerConfig:
        return ControllerConfig(arbitration=CanTiming(bitrate_kbit=bitrate))

    @staticmethod
    def fd_config(bitrate: int, data_bitrate: int) -> ControllerConfig:
        return ControllerConfig(
            can_fd=True,
            bitrate_switch=True,
            arbitration=CanTiming(bitrate_kbit=bitrate),
            data=CanTiming(bitrate_kbit=data_bitrate),
        )


def _parse_bitrates(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _run(name: str, scenario: Callable[[], None]) -> ScenarioResult:
    print(f"\n[{name}]")
    try:
        scenario()
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return ScenarioResult(name, False, str(exc))
    print(f"PASS {name}")
    return ScenarioResult(name, True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hardware integration suite for ASCII TCP, ASCII UDP, TLV UDP, and VCI CAN APIs.")
    parser.add_argument("--ascii-tcp", required=True, metavar="HOST[:PORT]", help="CAN@net NT ASCII TCP endpoint")
    parser.add_argument("--ascii-udp", required=True, metavar="HOST[:PORT]", help="CAN@net Basic ASCII UDP endpoint")
    parser.add_argument("--tlv-udp", required=True, metavar="HOST[:PORT]", help="CAN@net Basic TLV UDP endpoint")
    parser.add_argument("--vci", metavar="SERIAL", default=None, help="IXXAT VCI serial number (e.g. HW426714)")
    parser.add_argument("--vci-port", type=int, default=1, help="CAN port on the VCI interface (default: 1)")
    parser.add_argument("--bitrate", type=int, default=500, help="Default arbitration bitrate in kbit/s")
    parser.add_argument("--bitrates", default="500", help="Comma-separated classic CAN bitrates for the bitrate scenario")
    parser.add_argument("--data-bitrate", type=int, default=2000, help="CAN FD data bitrate in kbit/s")
    parser.add_argument("--include-fd", action="store_true", help="Also run CAN FD message type checks")
    parser.add_argument("--burst-count", type=int, default=32, help="Frames per sender in the burst scenario")
    parser.add_argument("--timeout", type=float, default=1.0, help="Receive and send timeout in seconds")
    parser.add_argument(
        "--tests",
        default="all",
        help="Comma-separated scenarios: all, smoke, bitrates, types, filters, burst",
    )
    args = parser.parse_args()

    requested = {item.strip().lower() for item in args.tests.split(",") if item.strip()}
    if "all" in requested:
        requested = {"smoke", "bitrates", "types", "filters", "burst"}

    nodes: list[Node] = []
    suite: Optional[CanHardwareSuite] = None
    try:
        nodes = [
            _make_ascii_tcp(args.ascii_tcp),
            _make_ascii_udp(args.ascii_udp),
            _make_tlv_udp(args.tlv_udp),
        ]
        if args.vci:
            nodes.append(_make_vci(args.vci, args.vci_port))
        suite = CanHardwareSuite(nodes, args.timeout)
        scenarios: list[tuple[str, Callable[[], None]]] = []
        if "smoke" in requested:
            scenarios.append(("smoke", lambda: suite.test_smoke(args.bitrate)))
        if "bitrates" in requested:
            scenarios.append(("bitrates", lambda: suite.test_bitrates(_parse_bitrates(args.bitrates))))
        if "types" in requested:
            scenarios.append(("types", lambda: suite.test_message_types(args.bitrate, args.data_bitrate, args.include_fd)))
        if "filters" in requested:
            scenarios.append(("filters", lambda: suite.test_filters(args.bitrate)))
        if "burst" in requested:
            scenarios.append(("burst", lambda: suite.test_burst(args.bitrate, args.burst_count)))
        if not scenarios:
            raise ValueError(f"no valid scenarios selected: {args.tests}")

        results = [_run(name, scenario) for name, scenario in scenarios]
        failed = [result for result in results if not result.passed]
        print("\nSummary")
        for result in results:
            state = "PASS" if result.passed else "FAIL"
            detail = f" - {result.message}" if result.message else ""
            print(f"  {state} {result.name}{detail}")
        return 1 if failed else 0
    finally:
        if suite is not None:
            suite.close()
        else:
            for node in nodes:
                node.api.close()


if __name__ == "__main__":
    sys.exit(main())
