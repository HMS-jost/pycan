# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pycan import connect
from pycan.ascii_can import ASCII_PORT, AsciiCan
from pycan.can_api import CanApiError, DeviceInfo, Transport
from pycan.canudp import CanUdp
from pycan.connection import TLV_UDP_PORT
from pycan.virtual import Virtual


class ConnectTest(unittest.TestCase):
    def setUp(self):
        Virtual.reset_bus()

    def test_virtual_returns_open_backend(self):
        can = connect("virtual/vcan0")
        try:
            self.assertIsInstance(can, Virtual)
            self.assertEqual(can.identify().device_id, "vcan0")
        finally:
            can.close()

    def test_tlv_udp_uses_default_port_and_timeout(self):
        with patch.object(CanUdp, "open", return_value=DeviceInfo()) as open_mock:
            can = connect("tlv-udp/10.41.18.101", open_timeout=3.5)
        try:
            self.assertIsInstance(can, CanUdp)
            self.assertEqual(can._host, "10.41.18.101")
            self.assertEqual(can._port, TLV_UDP_PORT)
            config = open_mock.call_args.args[0]
            self.assertEqual(config.transport, Transport.UDP)
            self.assertEqual(config.address, "10.41.18.101")
            self.assertEqual(config.port, TLV_UDP_PORT)
            self.assertEqual(open_mock.call_args.kwargs["timeout"], 3.5)
        finally:
            can.close()

    def test_tlv_udp_accepts_explicit_port(self):
        with patch.object(CanUdp, "open", return_value=DeviceInfo()):
            can = connect("tlv-udp/10.41.18.101/20000")
        try:
            self.assertEqual(can._port, 20000)
        finally:
            can.close()

    def test_ascii_tcp_uses_nt_family_and_default_port(self):
        with patch.object(AsciiCan, "open", return_value=DeviceInfo()) as open_mock:
            can = connect("ascii-tcp/10.41.18.10")

        self.assertIsInstance(can, AsciiCan)
        self.assertEqual(can._host, "10.41.18.10")
        self.assertEqual(can._port, ASCII_PORT)
        self.assertEqual(can._transport_kind, Transport.TCP)
        self.assertEqual(can._device_family, "nt")
        config = open_mock.call_args.args[0]
        self.assertEqual(config.options["device_family"], "nt")

    def test_ascii_udp_uses_basic_family_and_explicit_port(self):
        with patch.object(AsciiCan, "open", return_value=DeviceInfo()) as open_mock:
            can = connect("ascii-udp/10.41.18.11/20001")

        self.assertEqual(can._host, "10.41.18.11")
        self.assertEqual(can._port, 20001)
        self.assertEqual(can._transport_kind, Transport.UDP)
        self.assertEqual(can._device_family, "basic")
        config = open_mock.call_args.args[0]
        self.assertEqual(config.options["device_family"], "basic")

    def test_invalid_connection_strings_raise_can_api_error(self):
        invalid_targets = [
            "",
            "tlv-udp",
            "tlv-udp/10.41.18.101/",
            "tlv-udp/10.41.18.101/not-a-port",
            "tlv-udp/10.41.18.101/70000",
            "virtual/vcan0/1",
            "unknown/device",
        ]

        for target in invalid_targets:
            with self.subTest(target=target):
                with self.assertRaises(CanApiError):
                    connect(target)


if __name__ == "__main__":
    unittest.main()
