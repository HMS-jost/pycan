# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

import unittest
from collections import deque
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pycan.ascii_can import AsciiCan
from pycan.can_api import (
    BusState,
    CanApi,
    CanFilter,
    CanMessage,
    ControllerConfig,
    FrameFormat,
    IdentifierFormat,
    OpenConfig,
    Transport,
)


class FakeTransport:
    def __init__(self, responses=()):
        self.sent = []
        self.responses = deque(responses)

    def send_line(self, line: bytes) -> None:
        self.sent.append(line.rstrip(b"\n"))

    def read_line(self, timeout: float = 0.0):
        if self.responses:
            return self.responses.popleft()
        return None

    def close(self) -> None:
        pass


class AsciiCanTest(unittest.TestCase):
    def test_open_queries_identification_and_is_can_api(self):
        transport = FakeTransport([b"R V1.2.3", b"R V2", b"R CAN CAN CAN CAN"])
        can = AsciiCan(_transport=transport)

        info = can.open(OpenConfig(transport=Transport.TCP, address="10.0.0.1"))

        self.assertIsInstance(can, CanApi)
        self.assertEqual(info.channel_count, 4)
        self.assertEqual(info.transport, Transport.TCP)
        self.assertEqual(info.firmware_version, "V1.2.3")
        self.assertEqual(
            transport.sent,
            [b"DEV VERSION", b"DEV PROTOCOL", b"DEV INTERFACES"],
        )

    def test_basic_requires_udp_and_has_one_port(self):
        can = AsciiCan(_transport=FakeTransport([b"R V1", b"R V2", b"R CAN"]))
        with self.assertRaisesRegex(Exception, "UDP only"):
            can.open(OpenConfig(transport=Transport.TCP, address="10.0.0.1", options={"device_family": "basic"}))

        can = AsciiCan(_transport=FakeTransport([b"R V1", b"R V2", b"R CAN"]))
        info = can.open(OpenConfig(transport=Transport.UDP, address="10.0.0.1", options={"device_family": "basic"}))
        self.assertEqual(info.channel_count, 1)
        with self.assertRaisesRegex(Exception, "invalid CAN port"):
            can.start_can(2)

    def test_init_filter_start_send_and_status_commands(self):
        transport = FakeTransport([
            b"R V1", b"R V2", b"R CAN CAN CAN CAN",
            b"R ok", b"R ok", b"R ok", b"R ok",
            b"R CAN 1 ----- 42",
        ])
        can = AsciiCan(_transport=transport)
        can.open(OpenConfig(transport=Transport.TCP, address="10.0.0.1"))
        can.init_can(1, ControllerConfig(can_fd=True))
        can.add_filter(1, CanFilter(IdentifierFormat.EXTENDED, mask=0, value=0))
        can.start_can(1)
        can.send(1, CanMessage(0x123, b"abc"))
        status = can.get_status(1)

        self.assertIn(b"CAN 1 INIT mode=STD baudA=500 baudD=0 iso=ISO", transport.sent)
        self.assertIn(b"CAN 1 FILTER CLEAR", transport.sent)
        self.assertIn(b"CAN 1 FILTER ADD type=EXT id=0 mask=0", transport.sent)
        self.assertIn(b"CAN 1 START", transport.sent)
        self.assertIn(b"M 1 CSD 123 61 62 63", transport.sent)
        self.assertEqual(status.state, BusState.RUNNING)
        self.assertEqual(status.tx_free, 42)

    def test_receive_parses_message_and_adds_client_timestamp(self):
        transport = FakeTransport([
            b"R V1", b"R V2", b"R CAN CAN CAN CAN",
            b"M 1 FED 1234567 00 01 02 03",
        ])
        can = AsciiCan(_transport=transport)
        can.open(OpenConfig(transport=Transport.TCP, address="10.0.0.1"))

        msg = can.receive(1, timeout=0)

        self.assertIsNotNone(msg)
        self.assertEqual(msg.can_id, 0x1234567)
        self.assertEqual(msg.id_format, IdentifierFormat.EXTENDED)
        self.assertEqual(msg.frame_format, FrameFormat.FD_BRS)
        self.assertEqual(msg.data, b"\x00\x01\x02\x03")
        self.assertGreater(msg.timestamp_us, 0)

    def test_callback_process_cycle(self):
        transport = FakeTransport([
            b"R V1", b"R V2", b"R CAN CAN CAN CAN",
            b"M 1 CSD 123 AA",
        ])
        can = AsciiCan(_transport=transport)
        can.open(OpenConfig(transport=Transport.TCP, address="10.0.0.1"))
        received = []
        can.set_receive_callback(1, lambda port, msg: received.append((port, msg.can_id)))

        can.process_cycle()

        self.assertEqual(received, [(1, 0x123)])

    def test_generic_backpressure_send_many(self):
        transport = FakeTransport([
            b"R V1", b"R V2", b"R CAN CAN CAN CAN",
            b"R CAN 1 ----- 2",
        ])
        can = AsciiCan(_transport=transport)
        can.open(OpenConfig(transport=Transport.TCP, address="10.0.0.1"))

        sent = can.send_many(
            1,
            [CanMessage(0x100, b"a"), CanMessage(0x101, b"b")],
            overall_timeout=0.1,
        )

        self.assertEqual(sent, 2)
        self.assertIn(b"CAN 1 STATUS", transport.sent)
        self.assertIn(b"M 1 CSD 100 61", transport.sent)
        self.assertIn(b"M 1 CSD 101 62", transport.sent)


if __name__ == "__main__":
    unittest.main()