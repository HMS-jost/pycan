# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""
CAN@net Basic — TLV UDP API

Implements the TLV CAN-UDP protocol: 1B Type + 2B Length (LE) + Value.

Commands:
  0  Open       PC→Dev   (no value)                    → null-term ID string
  1  Status     PC→Dev   (no value)                    → 3x uint16 (sts, tx_free, err)
  2  StopCAN    PC→Dev   port(1B)                      → uint16 status (0=ok)
  3  InitCAN    PC→Dev   port mode(2B) baudA(2B) baudD(2B) → uint16 status
  4  StartCAN   PC→Dev   port(1B)                      → uint16 status
  5  Filter     PC→Dev   port fmt mask(4B) value(4B)   → uint16 status
  6  CANrecv    Dev→PC   port ts_us(4B) fmt id(4B) data (unsolicited)
  7  CANsend    PC→Dev   port fmt id(4B) data           (no response)
  8  Close      PC→Dev   (no value)                    (no response)

Format bitmask (fmt):
  FMT_EXT=0x01  FMT_RTR=0x02  FMT_FDF=0x10  FMT_BRS=0x20

Usage:
    with CanUdp("10.41.18.123") as can:
    can.init_can(1, ControllerConfig(arbitration=CanTiming(bitrate_kbit=500)))
    can.add_filter(1, CanFilter(IdentifierFormat.STANDARD))
        can.start_can(1)
    can.send(1, CanMessage(0x200, b"\x01\x02\x03"))
    msg = can.receive(1, timeout=1.0)
        print(msg)
"""

import socket
import struct
import time
from collections import deque
from typing import Optional, Sequence

try:
    from .can_api import (
        BusState,
        CanApi,
        CanApiError,
        CanFilter,
        CanMessage,
        CanStatus,
        ControllerConfig,
        DeviceInfo,
        FrameFormat,
        FrameType,
        IdentifierFormat,
        OpenConfig,
        ReceiveCallback,
        Transport,
    )
except ImportError:
    from can_api import (
        BusState,
        CanApi,
        CanApiError,
        CanFilter,
        CanMessage,
        CanStatus,
        ControllerConfig,
        DeviceInfo,
        FrameFormat,
        FrameType,
        IdentifierFormat,
        OpenConfig,
        ReceiveCallback,
        Transport,
    )

# ---------------------------------------------------------------------------
# TLV command codes
# ---------------------------------------------------------------------------
CMD_OPEN      = 0
CMD_STATUS    = 1
CMD_STOP_CAN  = 2
CMD_INIT_CAN  = 3
CMD_START_CAN = 4
CMD_FILTER    = 5
CMD_CAN_RECV  = 6
CMD_CAN_SEND  = 7
CMD_CLOSE     = 8

# CAN status codes returned by the device
CAN_STATUS_INIT          = 0
CAN_STATUS_NORMAL        = 1
CAN_STATUS_ERROR_PASSIVE = 2
CAN_STATUS_OVERRUN       = 3
CAN_STATUS_BUS_OFF       = 4

CAN_STATUS_TEXT = {
    0: "init",
    1: "normal",
    2: "error passive",
    3: "overrun",
    4: "bus off",
}

# Frame format bitmask flags
FMT_STD = 0x00   # Standard CAN frame (11-bit ID)
FMT_EXT = 0x01   # Extended frame (29-bit ID)
FMT_RTR = 0x02   # Remote Transmission Request
FMT_FDF = 0x10   # CAN FD frame
FMT_BRS = 0x20   # CAN FD Bit Rate Switch
FMT_ESI = 0x40   # CAN FD Error State Indicator

# Legacy aliases
FMT_STANDARD = FMT_STD
FMT_EXTENDED = FMT_EXT

# CAN init mode bits
MODE_STD     = 1    # enable standard frame reception
MODE_EXT     = 2    # enable extended frame reception
MODE_ERR     = 4    # enable error frame reception
MODE_LISTEN  = 8    # listen-only (TX passive)
MODE_ABD     = 32   # automatic baud rate detection
MODE_RTR     = 64   # enable RTR frame reception
MODE_FD      = 768  # ISO CAN-FD mode

MODE_CLASSIC = MODE_STD | MODE_EXT | MODE_RTR   # = 67,  default Classic CAN
MODE_CANFD   = MODE_CLASSIC | MODE_FD            # = 835, default CAN-FD


class CanUdp(CanApi):
    """TLV CAN-over-UDP client for CAN@net Basic (NanoBasic UDP Server).

    Args:
        host:     Device IP address. May also be supplied later via open().
        port:     UDP server port (must match server_port in device config).
        src_port: Local UDP port to bind (0 = OS-assigned). The device sends
                  CAN receive frames back to the address/port of the Open command.
    """

    def __init__(self, host: str = "", port: int = 19236, src_port: int = 0):
        self._host = host
        self._port = port
        self._src_port = src_port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("", src_port))
        self._sock.settimeout(1.0)
        # TX capacity — updated after open() via status()
        self._tx_capacity: int = 50  # default from MSG_MboxSetLimit max_entries=50
        self._device_info = DeviceInfo(
            device_id=host,
            name="CAN@net Basic",
            transport=Transport.UDP,
            channel_count=1,
            supports_can_fd=True,
        )
        self._last_error: tuple[int, str] = (0, "")
        self._receive_callbacks: dict[int, ReceiveCallback] = {}
        self._rx_buffer: deque[CanMessage] = deque()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pack_tlv(self, cmd: int, value: bytes = b"") -> bytes:
        """Build a TLV frame: 1B type + 2B length LE + value bytes."""
        return struct.pack("<BH", cmd, len(value)) + value

    def _send_recv(self, cmd: int, value: bytes = b"",
                   timeout: float = 2.0) -> Optional[bytes]:
        """Send a TLV command and return the matching response value, or None on timeout.

        CMD_CAN_RECV frames (cmd=6) arriving while waiting are buffered.
        """
        self._sock.sendto(self._pack_tlv(cmd, value), (self._host, self._port))
        deadline = time.monotonic() + timeout
        self._sock.settimeout(max(0.05, timeout))
        while time.monotonic() < deadline:
            try:
                pkt, _ = self._sock.recvfrom(512)
            except socket.timeout:
                return None
            if len(pkt) < 3:
                continue
            resp_cmd, length = struct.unpack_from("<BH", pkt, 0)
            resp_value = pkt[3: 3 + length]
            if resp_cmd == cmd:
                return resp_value
            # Buffer CAN receive frames that arrive concurrently
            if resp_cmd == CMD_CAN_RECV:
                self._buffer_rx_packet(pkt[3:])
        return None

    def _buffer_rx_packet(self, val: bytes) -> None:
        """Parse a CMD_CAN_RECV payload and append to the RX buffer."""
        if len(val) < 10:
            return
        recv_port = val[0]
        ts_us = struct.unpack_from("<I", val, 1)[0]
        recv_fmt = val[5]
        recv_id = struct.unpack_from("<I", val, 6)[0]
        payload = bytes(val[10:])
        msg = self._message_from_fmt(recv_id, payload, recv_fmt, recv_port, ts_us)
        self._rx_buffer.append(msg)

    def _set_error(self, code: int, text: str) -> None:
        self._last_error = (code, text)

    def _device_result(self, operation: str, resp: Optional[bytes]) -> int:
        if resp is None or len(resp) < 2:
            self._set_error(CAN_STATUS_BUS_OFF, f"{operation}(): no response")
            raise TimeoutError(f"{operation}(): no response")
        result = struct.unpack_from("<H", resp)[0]
        if result != 0:
            text = f"{operation}() returned status {result}"
            self._set_error(result, text)
            raise CanApiError(text)
        self._set_error(0, "")
        return result

    @staticmethod
    def _status_to_state(status: int) -> BusState:
        if status == CAN_STATUS_INIT:
            return BusState.INIT
        if status == CAN_STATUS_NORMAL:
            return BusState.RUNNING
        if status == CAN_STATUS_ERROR_PASSIVE:
            return BusState.ERROR_PASSIVE
        if status == CAN_STATUS_OVERRUN:
            return BusState.OVERRUN
        if status == CAN_STATUS_BUS_OFF:
            return BusState.BUS_OFF
        return BusState.UNKNOWN

    @staticmethod
    def _message_to_fmt(message: CanMessage) -> int:
        fmt = FMT_STD
        if message.id_format == IdentifierFormat.EXTENDED:
            fmt |= FMT_EXT
        if message.frame_type == FrameType.REMOTE:
            fmt |= FMT_RTR
        if message.frame_format in (FrameFormat.FD_NO_BRS, FrameFormat.FD_BRS):
            fmt |= FMT_FDF
        if message.frame_format == FrameFormat.FD_BRS:
            fmt |= FMT_BRS
        return fmt

    @staticmethod
    def _message_from_fmt(
        can_id: int,
        data: bytes,
        fmt: int,
        port: int,
        timestamp_us: int,
    ) -> CanMessage:
        id_format = IdentifierFormat.EXTENDED if fmt & FMT_EXT else IdentifierFormat.STANDARD
        if fmt & FMT_FDF:
            frame_format = FrameFormat.FD_BRS if fmt & FMT_BRS else FrameFormat.FD_NO_BRS
        else:
            frame_format = FrameFormat.CLASSIC
        frame_type = FrameType.REMOTE if fmt & FMT_RTR else FrameType.DATA
        return CanMessage(
            can_id=can_id,
            data=data,
            id_format=id_format,
            frame_format=frame_format,
            frame_type=frame_type,
            timestamp_us=timestamp_us,
            port=port,
            flags=fmt,
        )

    @staticmethod
    def _config_to_mode(config: ControllerConfig) -> int:
        mode = 0
        if config.receive_standard:
            mode |= MODE_STD
        if config.receive_extended:
            mode |= MODE_EXT
        if config.listen_only:
            mode |= MODE_LISTEN
        if config.receive_remote:
            mode |= MODE_RTR
        if config.can_fd:
            mode |= MODE_FD
        return mode or MODE_CLASSIC

    @staticmethod
    def _filter_to_fmt(can_filter: CanFilter) -> int:
        fmt = FMT_EXT if can_filter.id_format == IdentifierFormat.EXTENDED else FMT_STD
        if can_filter.frame_type == FrameType.REMOTE:
            fmt |= FMT_RTR
        return fmt

    # ------------------------------------------------------------------
    # Protocol commands
    # ------------------------------------------------------------------

    def get_device_list(self, transport: Transport = Transport.ANY) -> list[DeviceInfo]:
        """Return the configured UDP endpoint as a device, if known."""
        if transport not in (Transport.ANY, Transport.UDP):
            return []
        if not self._host:
            return []
        return [self._device_info]

    def open(self, config: OpenConfig | str | None = None, timeout: float = 2.0) -> DeviceInfo:
        """Send Open command. Registers our IP/port for unsolicited CAN receive frames.

        Returns device identification information.
        Raises TimeoutError on no response.
        """
        if isinstance(config, OpenConfig):
            self._host = config.address or config.device_id or self._host
            if config.port:
                self._port = config.port
        elif isinstance(config, str):
            self._host = config
        if not self._host:
            raise CanApiError("open(): no host configured")
        resp = self._send_recv(CMD_OPEN, b"", timeout=timeout)
        if resp is None:
            self._set_error(CAN_STATUS_BUS_OFF, "open(): no response from device")
            raise TimeoutError("open(): no response from device")
        ident = resp.split(b"\x00")[0].decode("ascii", errors="replace")
        self._device_info = DeviceInfo(
            device_id=self._host,
            name=ident,
            transport=Transport.UDP,
            channel_count=1,
            supports_can_fd=True,
            supports_listen_only=True,
        )
        # Cache TX capacity for flow control
        try:
            sts = self.status(timeout=timeout)
            if sts.tx_free > 0:
                self._tx_capacity = sts.tx_free
        except TimeoutError:
            pass
        self._set_error(0, "")
        return self._device_info

    def identify(self) -> DeviceInfo:
        """Return cached identification information for the open UDP endpoint."""
        return self._device_info

    def status(self, timeout: float = 2.0) -> CanStatus:
        """Query device/CAN status.

        Returns CanStatus(state, tx_free, error_code, text).
        Raises TimeoutError on no response.
        """
        resp = self._send_recv(CMD_STATUS, b"", timeout=timeout)
        if resp is None or len(resp) < 6:
            self._set_error(CAN_STATUS_BUS_OFF, "status(): no response from device")
            raise TimeoutError("status(): no response from device")
        sts, tx_free, error = struct.unpack_from("<HHH", resp, 0)
        self._set_error(error, CAN_STATUS_TEXT.get(sts, f"unknown({sts})"))
        return CanStatus(
            state=self._status_to_state(sts),
            tx_free=tx_free,
            error_code=error,
            text=CAN_STATUS_TEXT.get(sts, f"unknown({sts})"),
            flags=sts,
        )

    def get_status(self, port: int = 1) -> CanStatus:
        """Return CAN controller status for the selected port."""
        return self.status()

    def stop_can(self, port: int = 1, timeout: float = 2.0) -> None:
        """Stop CAN controller."""
        resp = self._send_recv(CMD_STOP_CAN, bytes([port]), timeout=timeout)
        self._device_result("stop_can", resp)

    def init_can(self, port: int = 1, config: ControllerConfig | None = None,
                 timeout: float = 2.0) -> None:
        """Initialize CAN controller. Clears all receive filters.

        Sends STOP first to ensure the controller can be re-initialized.

        Args:
            port:   CAN channel (currently only 1 supported).
            config: Common CAN controller configuration.
        """
        self.stop_can(port, timeout=timeout)
        config = config or ControllerConfig()
        mode = self._config_to_mode(config)
        baud_a = config.arbitration.bitrate_kbit
        baud_d = config.data.bitrate_kbit if config.can_fd else 0
        value = struct.pack("<BHHH", port, mode, baud_a, baud_d)
        resp = self._send_recv(CMD_INIT_CAN, value, timeout=timeout)
        self._device_result("init_can", resp)

    def start_can(self, port: int = 1, timeout: float = 2.0) -> None:
        """Start CAN controller."""
        resp = self._send_recv(CMD_START_CAN, bytes([port]), timeout=timeout)
        self._device_result("start_can", resp)

    def add_filter(self, port: int = 1, can_filter: CanFilter | None = None,
                   timeout: float = 2.0) -> None:
        """Register a CAN receive filter (mask/value).

        A frame is accepted when (frame_id & mask) == value.
        mask=0, value=0 accepts all frames of the given identifier format.
        """
        can_filter = can_filter or CanFilter()
        payload = struct.pack(
            "<BBII",
            port,
            self._filter_to_fmt(can_filter),
            can_filter.mask,
            can_filter.value,
        )
        resp = self._send_recv(CMD_FILTER, payload, timeout=timeout)
        self._device_result("add_filter", resp)

    def send(self, port: int, message: CanMessage) -> None:
        """Send a CAN message. No response from device.

        Raises:
            ValueError: If data length or CAN-ID is out of range.
        """
        fmt = self._message_to_fmt(message)
        max_len = 64 if message.is_fd else 8
        if len(message.data) > max_len:
            raise ValueError(f"CAN data max {max_len} bytes, got {len(message.data)}")
        is_ext = message.id_format == IdentifierFormat.EXTENDED
        limit = 0x1FFFFFFF if is_ext else 0x7FF
        if not (0 <= message.can_id <= limit):
            raise ValueError(
                f"CAN-ID 0x{message.can_id:X} out of range for "
                f"{'Extended' if is_ext else 'Standard'} (max 0x{limit:X})"
            )
        tlv_value = struct.pack("<BBI", port, fmt, message.can_id) + message.data
        self._sock.sendto(self._pack_tlv(CMD_CAN_SEND, tlv_value), (self._host, self._port))

    def send_many(
        self,
        port: int,
        messages: Sequence[CanMessage],
        poll_interval: float = 0.001,
        overall_timeout: Optional[float] = None,
    ) -> int:
        """Send multiple CAN messages using device TX-free flow control."""
        return super().send_many(port, messages, poll_interval, overall_timeout)

    def receive(self, port: int = 1, timeout: Optional[float] = 1.0) -> Optional[CanMessage]:
        """Wait for a CAN receive frame (CMD 6) from the device.

        Checks the internal buffer first (filled by _send_recv during
        command/response exchanges), then reads from the socket.

        Args:
            timeout: Seconds to wait; None = wait indefinitely.

        Returns CanMessage or None on timeout.
        """
        # Check buffer first
        for i, msg in enumerate(self._rx_buffer):
            if msg.port == port:
                del self._rx_buffer[i]
                return msg

        wait = timeout if timeout is not None else 1e9
        if wait == 0:
            self._sock.settimeout(0)
            try:
                pkt, _ = self._sock.recvfrom(512)
            except (BlockingIOError, socket.timeout):
                return None
            if len(pkt) < 3:
                return None
            cmd, length = struct.unpack_from("<BH", pkt, 0)
            if cmd != CMD_CAN_RECV:
                return None
            val = pkt[3:]
            if len(val) < 10:
                return None
            recv_port = val[0]
            if recv_port != port:
                self._buffer_rx_packet(val)
                return None
            ts_us = struct.unpack_from("<I", val, 1)[0]
            recv_fmt = val[5]
            recv_id = struct.unpack_from("<I", val, 6)[0]
            payload = bytes(val[10:])
            return self._message_from_fmt(recv_id, payload, recv_fmt, recv_port, ts_us)
        deadline = time.monotonic() + wait
        self._sock.settimeout(max(0.05, wait))
        while time.monotonic() < deadline:
            try:
                pkt, _ = self._sock.recvfrom(512)
            except socket.timeout:
                return None
            if len(pkt) < 3:
                continue
            cmd, length = struct.unpack_from("<BH", pkt, 0)
            if cmd != CMD_CAN_RECV:
                continue
            val = pkt[3:]
            if len(val) < 10:
                continue
            recv_port = val[0]
            if recv_port != port:
                self._buffer_rx_packet(val)
                continue
            ts_us     = struct.unpack_from("<I", val, 1)[0]
            recv_fmt  = val[5]
            recv_id   = struct.unpack_from("<I", val, 6)[0]
            payload   = bytes(val[10:])
            return self._message_from_fmt(recv_id, payload, recv_fmt, recv_port, ts_us)
        return None

    def set_receive_callback(
        self,
        port: int,
        callback: Optional[ReceiveCallback],
    ) -> None:
        """Register or remove a cooperative receive callback."""
        if callback is None:
            self._receive_callbacks.pop(port, None)
        else:
            self._receive_callbacks[port] = callback

    def process_cycle(self) -> None:
        """Dispatch all currently queued receive messages to callbacks."""
        for port, callback in list(self._receive_callbacks.items()):
            while True:
                msg = self.receive(port, timeout=0)
                if msg is None:
                    break
                callback(port, msg)

    def get_last_error(self) -> tuple[int, str]:
        """Return the last backend-specific error code and text."""
        return self._last_error

    def close(self) -> None:
        """Send Close command (device stops sending CAN frames to us) and close socket."""
        try:
            self._sock.sendto(self._pack_tlv(CMD_CLOSE), (self._host, self._port))
        except Exception:
            pass
        self._sock.close()

    # ------------------------------------------------------------------
    # Legacy compatibility
    # ------------------------------------------------------------------

    def can_status(self, timeout: float = 2.0) -> CanStatus:
        """Alias for status() — backward compatibility."""
        return self.status(timeout=timeout)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "CanUdp":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
