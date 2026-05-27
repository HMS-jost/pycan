# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""CAN@net CANM multicast bridge backend for the generic CanApi.

The CANM protocol exchanges CAN frames between up to 64 CAN@net Basic devices
via UDP multicast. Each UDP datagram may contain multiple CAN frames. The PC
joins the multicast group and acts as a virtual participant on the shared
CAN-over-UDP backbone.

This backend does NOT control CAN hardware — init_can(), start_can(), and
stop_can() are no-ops that return errors. Filtering is done in software.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections import deque
from typing import Optional, Sequence

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

# ---------------------------------------------------------------------------
# CANM protocol constants
# ---------------------------------------------------------------------------
_CANM_MAGIC = b"CANM"
_CANM_BGI_TYPE_CAN = 0x06  # Classic CAN frame
_CANM_BGI_TYPE_FD = 0x08   # CAN-FD frame
_CANM_BGI_TYPES = {_CANM_BGI_TYPE_CAN, _CANM_BGI_TYPE_FD}
_CANM_SOURCE_PC = 0x10
_CANM_HDR_SIZE = 16
_CANM_CAN_HDR_SIZE = 12
_CANM_EXTRA_SIZE = 52
_CANM_FMT_EXT = 0x01
_CANM_FMT_RTR = 0x02
_CANM_FMT_FDF = 0x10
_CANM_FMT_BRS = 0x20

CANM_DEFAULT_ADDRESS = "225.0.0.250"
CANM_DEFAULT_PORT = 50009
_RX_BUFFER_MAX = 4096


def _get_local_ip() -> str:
    """Return the local IP used for outgoing traffic."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    except Exception:
        return "0.0.0.0"


def _build_canm_packet(
    can_id: int,
    data: bytes,
    is_extended: bool = False,
    is_fd: bool = False,
    bitrate_switch: bool = False,
    port: int = 1,
) -> bytes:
    """Build a single CANM frame packet."""
    dlc = len(data)
    fmt_byte = 0
    if is_extended:
        fmt_byte |= _CANM_FMT_EXT
    if is_fd:
        fmt_byte |= _CANM_FMT_FDF
    if bitrate_switch:
        fmt_byte |= _CANM_FMT_BRS
    extra = bytes(_CANM_EXTRA_SIZE)
    total_size = _CANM_HDR_SIZE + _CANM_CAN_HDR_SIZE + dlc + len(extra)
    timestamp = int(time.time() * 1000) & 0xFFFF
    mtype = _CANM_BGI_TYPE_FD if is_fd else _CANM_BGI_TYPE_CAN
    bgi_header = struct.pack(
        "<4sIHHHBB",
        _CANM_MAGIC, 0, total_size, 0, timestamp, _CANM_SOURCE_PC, mtype,
    )
    can_header = struct.pack("<IBBBBI", can_id, dlc, fmt_byte, port, 0, 0)
    return bgi_header + can_header + data + extra


def _parse_canm_frames(data: bytes) -> list[CanMessage]:
    """Parse one UDP datagram that may contain multiple CANM frames."""
    messages: list[CanMessage] = []
    offset = 0
    while offset + _CANM_HDR_SIZE + _CANM_CAN_HDR_SIZE <= len(data):
        # Validate magic
        if data[offset:offset + 4] != _CANM_MAGIC:
            break
        try:
            _magic, _res, total_size, _topic, ts, _src, mtype = struct.unpack_from(
                "<4sIHHHBB", data, offset
            )
        except struct.error:
            break
        if mtype not in _CANM_BGI_TYPES:
            break
        if offset + total_size > len(data):
            break
        # Parse CAN header
        can_offset = offset + _CANM_HDR_SIZE
        try:
            can_id, dlc, fmt, port, _tbd, _res2 = struct.unpack_from(
                "<IBBBBI", data, can_offset
            )
        except struct.error:
            break
        payload_start = can_offset + _CANM_CAN_HDR_SIZE
        payload = data[payload_start:payload_start + dlc]

        # Determine formats
        is_ext = bool(fmt & _CANM_FMT_EXT)
        is_rtr = bool(fmt & _CANM_FMT_RTR)
        is_fd = bool(fmt & _CANM_FMT_FDF)
        is_brs = bool(fmt & _CANM_FMT_BRS)

        if is_fd and is_brs:
            frame_format = FrameFormat.FD_BRS
        elif is_fd:
            frame_format = FrameFormat.FD_NO_BRS
        else:
            frame_format = FrameFormat.CLASSIC

        id_format = IdentifierFormat.EXTENDED if is_ext else IdentifierFormat.STANDARD
        frame_type = FrameType.REMOTE if is_rtr else FrameType.DATA

        msg = CanMessage(
            can_id=can_id,
            data=payload,
            id_format=id_format,
            frame_format=frame_format,
            frame_type=frame_type,
            timestamp_us=int(time.time() * 1_000_000),
            port=port,
        )
        messages.append(msg)
        offset += total_size

    return messages


class CanmUdp(CanApi):
    """CAN@net CANM multicast bridge backend.

    Joins a UDP multicast group to send and receive CAN frames exchanged
    between CAN@net Basic devices on the same backbone.
    """

    def __init__(
        self,
        address: str = CANM_DEFAULT_ADDRESS,
        port: int = CANM_DEFAULT_PORT,
        interface: str = "",
    ):
        self._mcast_address = address
        self._mcast_port = port
        self._interface = interface
        self._sock: Optional[socket.socket] = None
        self._send_sock: Optional[socket.socket] = None
        self._local_ip = ""
        self._device_info: Optional[DeviceInfo] = None
        self._rx_queue: deque[CanMessage] = deque(maxlen=_RX_BUFFER_MAX)
        self._filters: list[CanFilter] = []
        self._receive_callbacks: dict[int, ReceiveCallback] = {}
        self._last_error: tuple[int, str] = (0, "")
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_error(self, code: int, text: str) -> None:
        self._last_error = (code, text)

    def _require_open(self) -> None:
        if self._sock is None or self._device_info is None:
            self._set_error(1, "device is not open")
            raise CanApiError("device is not open")

    def _accepts(self, msg: CanMessage) -> bool:
        """Software filter: accept if no filters set or any filter matches."""
        if not self._filters:
            return True
        for f in self._filters:
            if f.id_format != msg.id_format:
                continue
            if (msg.can_id & f.mask) == (f.value & f.mask):
                return True
        return False

    def _listener_loop(self) -> None:
        """Background thread: receive multicast datagrams and parse frames."""
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            frames = _parse_canm_frames(data)
            for msg in frames:
                if self._accepts(msg):
                    self._rx_queue.append(msg)
                    # Fire callbacks
                    cb = self._receive_callbacks.get(msg.port)
                    if cb:
                        cb(msg.port, msg)

    # ------------------------------------------------------------------
    # CanApi interface
    # ------------------------------------------------------------------

    def get_device_list(self, transport: Transport = Transport.ANY) -> list[DeviceInfo]:
        """Return the multicast endpoint as a device."""
        if transport not in (Transport.ANY, Transport.UDP):
            return []
        return [
            DeviceInfo(
                device_id=self._mcast_address,
                name="CAN@net CANM Multicast",
                transport=Transport.UDP,
                channel_count=1,
                supports_can_fd=True,
            )
        ]

    def open(self, config: Optional[OpenConfig] = None) -> DeviceInfo:
        """Join the multicast group and start the listener thread."""
        if config is not None:
            if config.address:
                self._mcast_address = config.address
            if config.port:
                self._mcast_port = config.port

        self._local_ip = self._interface or _get_local_ip()

        # Receive socket — join multicast group
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", self._mcast_port))
        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(self._mcast_address),
            socket.inet_aton(self._local_ip),
        )
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._sock.settimeout(0.5)

        # Send socket
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        self._send_sock.bind((self._local_ip, 0))

        self._device_info = DeviceInfo(
            device_id=self._mcast_address,
            name="CAN@net CANM Multicast",
            transport=Transport.UDP,
            channel_count=1,
            supports_can_fd=True,
        )

        # Start listener thread
        self._running = True
        self._listener_thread = threading.Thread(target=self._listener_loop, daemon=True)
        self._listener_thread.start()

        return self._device_info

    def close(self) -> None:
        """Leave multicast group and close sockets."""
        self._running = False
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=2.0)
            self._listener_thread = None
        if self._sock is not None:
            try:
                mreq = struct.pack(
                    "4s4s",
                    socket.inet_aton(self._mcast_address),
                    socket.inet_aton(self._local_ip),
                )
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            except Exception:
                pass
            self._sock.close()
            self._sock = None
        if self._send_sock is not None:
            self._send_sock.close()
            self._send_sock = None
        self._device_info = None

    def identify(self) -> DeviceInfo:
        """Return cached device information."""
        self._require_open()
        return self._device_info

    def init_can(self, port: int, config: ControllerConfig) -> None:
        """No-op — CANM multicast has no CAN controller to initialize."""
        self._require_open()
        self._set_error(99, "init_can not supported on CANM multicast backend")
        raise CanApiError("init_can not supported on CANM multicast backend")

    def start_can(self, port: int) -> None:
        """No-op — CANM multicast has no CAN controller to start."""
        self._require_open()
        self._set_error(99, "start_can not supported on CANM multicast backend")
        raise CanApiError("start_can not supported on CANM multicast backend")

    def stop_can(self, port: int) -> None:
        """No-op — CANM multicast has no CAN controller to stop."""
        self._require_open()
        self._set_error(99, "stop_can not supported on CANM multicast backend")
        raise CanApiError("stop_can not supported on CANM multicast backend")

    def add_filter(self, port: int, can_filter: CanFilter) -> None:
        """Add a software receive filter."""
        self._require_open()
        self._filters.append(can_filter)

    def clear_filters(self, port: int) -> None:
        """Clear all software receive filters."""
        self._require_open()
        self._filters.clear()

    def send(self, port: int, message: CanMessage) -> None:
        """Send one CAN message via CANM multicast."""
        self._require_open()
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
        packet = _build_canm_packet(
            can_id=message.can_id,
            data=message.data,
            is_extended=is_ext,
            is_fd=message.frame_format != FrameFormat.CLASSIC,
            bitrate_switch=message.frame_format == FrameFormat.FD_BRS,
            port=port,
        )
        self._send_sock.sendto(packet, (self._mcast_address, self._mcast_port))

    def send_many(
        self,
        port: int,
        messages: Sequence[CanMessage],
        poll_interval: float = 0.001,
        overall_timeout: Optional[float] = None,
    ) -> int:
        """Send multiple messages sequentially."""
        sent = 0
        for msg in messages:
            self.send(port, msg)
            sent += 1
        return sent

    def receive(self, port: int, timeout: Optional[float] = 1.0) -> Optional[CanMessage]:
        """Receive one CAN message from the multicast queue."""
        self._require_open()
        wait = timeout if timeout is not None else 1e9
        deadline = time.monotonic() + wait
        while True:
            if self._rx_queue:
                return self._rx_queue.popleft()
            if wait == 0 or time.monotonic() >= deadline:
                return None
            time.sleep(0.005)

    def set_receive_callback(
        self,
        port: int,
        callback: Optional[ReceiveCallback],
    ) -> None:
        """Register or remove a receive callback."""
        self._require_open()
        if callback is None:
            self._receive_callbacks.pop(port, None)
        else:
            self._receive_callbacks[port] = callback

    def get_status(self, port: int) -> CanStatus:
        """Return status — RUNNING if multicast group is joined."""
        self._require_open()
        return CanStatus(
            state=BusState.RUNNING,
            tx_free=100,
            text="multicast active",
            flags=0,
            rx_pending=len(self._rx_queue),
        )

    def get_last_error(self) -> tuple[int, str]:
        """Return the last error code and text."""
        return self._last_error
