# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
from pycan.virtual import Virtual


class VirtualCanApiTest(unittest.TestCase):
    def setUp(self):
        Virtual.reset_bus()

    def test_virtual_is_can_api_and_lists_devices(self):
        can = Virtual()
        self.assertIsInstance(can, CanApi)
        devices = can.get_device_list(Transport.VIRTUAL)
        self.assertEqual([item.device_id for item in devices], ["vcan0", "vcan1"])

    def test_send_receive_between_virtual_devices(self):
        tx = Virtual()
        rx = Virtual()
        tx.open(OpenConfig(transport=Transport.VIRTUAL, device_id="vcan0"))
        rx.open(OpenConfig(transport=Transport.VIRTUAL, device_id="vcan1"))
        tx.init_can(1, ControllerConfig())
        rx.init_can(1, ControllerConfig())
        tx.start_can(1)
        rx.start_can(1)

        tx.send(1, CanMessage(0x123, b"abc"))
        message = rx.receive(1, timeout=0)

        self.assertIsNotNone(message)
        self.assertEqual(message.can_id, 0x123)
        self.assertEqual(message.data, b"abc")
        self.assertEqual(message.port, 1)
        self.assertGreater(message.timestamp_us, 0)

    def test_filters_limit_received_messages(self):
        tx = Virtual()
        rx = Virtual()
        tx.open("vcan0")
        rx.open("vcan1")
        tx.init_can(1, ControllerConfig())
        rx.init_can(1, ControllerConfig())
        rx.add_filter(1, CanFilter(IdentifierFormat.STANDARD, mask=0x700, value=0x200))
        tx.start_can(1)
        rx.start_can(1)

        tx.send(1, CanMessage(0x123, b"blocked"))
        tx.send(1, CanMessage(0x234, b"pass"))

        message = rx.receive(1, timeout=0)
        self.assertIsNotNone(message)
        self.assertEqual(message.can_id, 0x234)
        self.assertIsNone(rx.receive(1, timeout=0))

    def test_send_many_status_and_callback(self):
        tx = Virtual()
        rx = Virtual()
        tx.open("vcan0")
        rx.open("vcan1")
        tx.init_can(2, ControllerConfig(can_fd=True))
        rx.init_can(2, ControllerConfig(can_fd=True))
        tx.start_can(2)
        rx.start_can(2)

        received = []
        rx.set_receive_callback(2, lambda port, msg: received.append((port, msg)))
        sent = tx.send_many(
            2,
            [
                CanMessage(0x100, bytes(range(8))),
                CanMessage(0x101, bytes(range(12)), frame_format=FrameFormat.FD_BRS),
            ],
        )
        rx.process_cycle()
        status = rx.get_status(2)

        self.assertEqual(sent, 2)
        self.assertEqual([msg.can_id for _, msg in received], [0x100, 0x101])
        self.assertEqual(status.state, BusState.RUNNING)
        self.assertEqual(status.rx_pending, 0)


if __name__ == "__main__":
    unittest.main()