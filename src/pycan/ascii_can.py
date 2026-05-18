# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""CAN@net ASCII protocol implementation for the generic CanApi.

CAN@net NT devices use the ASCII protocol over TCP. CAN@net Basic uses the
ASCII protocol over UDP. The ASCII protocol does not provide receive timestamps,
so this client adds a timestamp when a message line is parsed.
"""

from __future__ import annotations

import socket
import time
from collections import deque
from dataclasses import replace
from typing import Optional, Protocol, Sequence

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


ASCII_PORT = 19228
BUFFER_SIZE = 4096
MAX_NT_PORTS = 4
MAX_BASIC_PORTS = 1


class _Transport(Protocol):
    def send_line(self, line: bytes) -> None:
        ...

    def read_line(self, timeout: float = 0.0) -> Optional[bytes]:
        ...

    def close(self) -> None:
        ...


class _SocketTransport:
    def __init__(self, host: str, port: int, transport: Transport, src_port: int = 0):
        self._host = host
        self._port = port
        self._transport = transport
        self._stream = b""
        if transport == Transport.TCP:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(2.0)
            self._sock.connect((host, port))
        elif transport == Transport.UDP:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.bind(("", src_port))
        else:
            raise CanApiError("ASCII transport must be TCP or UDP")
        self._sock.settimeout(0.0)

    def send_line(self, line: bytes) -> None:
        if not line.endswith(b"\n"):
            line += b"\n"
        self._sock.settimeout(1.0)
        try:
            if self._transport == Transport.TCP:
                self._sock.sendall(line)
            else:
                self._sock.sendto(line, (self._host, self._port))
        finally:
            self._sock.settimeout(0.0)

    def read_line(self, timeout: float = 0.0) -> Optional[bytes]:
        deadline = time.monotonic() + timeout
        while True:
            line = self._pop_line()
            if line is not None:
                return line
            try:
                if self._transport == Transport.TCP:
                    data = self._sock.recv(BUFFER_SIZE)
                else:
                    data, _ = self._sock.recvfrom(BUFFER_SIZE)
                if not data:
                    return None
                self._stream += data
            except (BlockingIOError, socket.timeout):
                if timeout == 0 or time.monotonic() >= deadline:
                    return None
                time.sleep(0.001)

    def _pop_line(self) -> Optional[bytes]:
        self._stream = self._stream.replace(b"\r", b"\n")
        if b"\n" not in self._stream:
            return None
        line, self._stream = self._stream.split(b"\n", 1)
        line = line.strip()
        return line or None

    def close(self) -> None:
        self._sock.close()


class AsciiCan(CanApi):
    """CAN@net ASCII implementation of the common CAN API."""

    def __init__(
        self,
        host: str = "",
        port: int = ASCII_PORT,
        transport: Transport = Transport.TCP,
        device_family: str = "",
        timeout: float = 0.5,
        src_port: int = 0,
        _transport: Optional[_Transport] = None,
    ):
        self._host = host
        self._port = port
        self._transport_kind = transport
        self._device_family = device_family.lower()
        self._timeout = timeout
        self._src_port = src_port
        self._transport = _transport
        self._device_info: Optional[DeviceInfo] = None
        self._rx_queues: dict[int, deque[CanMessage]] = {
            port_no: deque() for port_no in range(1, MAX_NT_PORTS + 1)
        }
        self._response_queue: deque[str] = deque()
        self._status: dict[int, CanStatus] = {}
        self._receive_callbacks: dict[int, ReceiveCallback] = {}
        self._last_error: tuple[int, str] = (0, "")

    def _set_error(self, code: int, text: str) -> None:
        self._last_error = (code, text)

    @property
    def _max_ports(self) -> int:
        return MAX_BASIC_PORTS if self._device_family == "basic" else MAX_NT_PORTS

    def _require_open(self) -> None:
        if self._transport is None or self._device_info is None:
            self._set_error(1, "device is not open")
            raise CanApiError("device is not open")

    def _validate_port(self, port: int) -> None:
        if not 1 <= port <= self._max_ports:
            raise CanApiError(f"invalid CAN port {port} for {self._device_family or 'ascii'} device")

    def _send_command(self, command: str | bytes) -> None:
        self._require_open()
        line = command.encode("ascii") if isinstance(command, str) else command
        self._transport.send_line(line)

    def _read_response(self, timeout: Optional[float] = None) -> Optional[str]:
        deadline = time.monotonic() + (self._timeout if timeout is None else timeout)
        while True:
            self._read_available(timeout=0)
            if self._response_queue:
                return self._response_queue.popleft()
            if time.monotonic() >= deadline:
                return None
            line_timeout = min(0.01, max(0.0, deadline - time.monotonic()))
            self._read_available(timeout=line_timeout)

    def _expect_ok(self, operation: str) -> None:
        response = self._read_response()
        if response == "ok":
            self._set_error(0, "")
            return
        text = response or f"{operation}: target timeout"
        self._set_error(2, text)
        raise CanApiError(text)

    def _read_available(self, timeout: float = 0.0) -> None:
        if self._transport is None:
            return
        first = True
        while True:
            line = self._transport.read_line(timeout if first else 0.0)
            first = False
            if line is None:
                break
            self._dispatch_line(line)

    def _dispatch_line(self, line: bytes) -> None:
        words = line.split()
        if not words:
            return
        if words[0] == b"M":
            message = self._parse_message(words)
            self._rx_queues[message.port].append(message)
        elif words[0] == b"R":
            if len(words) >= 5 and words[1].upper() == b"CAN" and words[2].isdigit():
                port = int(words[2])
                status_text = words[3].decode("ascii", errors="replace")
                tx_free = int(words[4])
                self._status[port] = self._status_from_ascii(status_text, tx_free)
            else:
                self._response_queue.append(b" ".join(words[1:]).decode("ascii", errors="replace"))
        elif words[0] == b"E":
            self._set_error(3, line.decode("ascii", errors="replace"))

    @staticmethod
    def _parse_message(words: list[bytes]) -> CanMessage:
        port = int(words[1])
        fmt = words[2].decode("ascii", errors="replace")
        can_id = int(words[3], 16)
        frame_format = AsciiCan._frame_format_from_ascii(fmt)
        id_format = IdentifierFormat.EXTENDED if fmt[1] == "E" else IdentifierFormat.STANDARD
        frame_type = FrameType.REMOTE if fmt[2] == "R" else FrameType.DATA
        if frame_type == FrameType.REMOTE:
            dlc_word = words[4].decode("ascii", errors="replace") if len(words) > 4 else "dlc=0"
            dlc = int(dlc_word.split("=", 1)[1]) if "=" in dlc_word else int(dlc_word, 16)
            data = bytes(dlc)
        else:
            data = bytes(int(item, 16) for item in words[4:])
        return CanMessage(
            can_id=can_id,
            data=data,
            id_format=id_format,
            frame_format=frame_format,
            frame_type=frame_type,
            timestamp_us=int(time.time() * 1_000_000),
            port=port,
        )

    @staticmethod
    def _frame_format_from_ascii(fmt: str) -> FrameFormat:
        if fmt[0] == "F":
            return FrameFormat.FD_BRS
        if fmt[0] == "N":
            return FrameFormat.FD_NO_BRS
        return FrameFormat.CLASSIC

    @staticmethod
    def _ascii_from_message(message: CanMessage) -> str:
        return message.format_str

    @staticmethod
    def _filter_type(can_filter: CanFilter) -> str:
        return "EXT" if can_filter.id_format == IdentifierFormat.EXTENDED else "STD"

    @staticmethod
    def _status_from_ascii(status_text: str, tx_free: int) -> CanStatus:
        if "B" in status_text:
            state = BusState.BUS_OFF
        elif "E" in status_text:
            state = BusState.ERROR_WARNING
        elif "O" in status_text:
            state = BusState.OVERRUN
        elif "I" in status_text:
            state = BusState.INIT
        else:
            state = BusState.RUNNING
        return CanStatus(state=state, tx_free=tx_free, text=status_text, flags=0)

    def get_device_list(self, transport: Transport = Transport.ANY) -> list[DeviceInfo]:
        """Return the configured ASCII endpoint as a device, if known."""

        if transport not in (Transport.ANY, Transport.TCP, Transport.UDP):
            return []
        if self._host == "":
            return []
        family = self._device_family or ("basic" if self._transport_kind == Transport.UDP else "nt")
        return [
            DeviceInfo(
                device_id=self._host,
                name=f"CAN@net {family.upper()} ASCII",
                transport=self._transport_kind,
                channel_count=MAX_BASIC_PORTS if family == "basic" else MAX_NT_PORTS,
                supports_can_fd=True,
                supports_listen_only=True,
            )
        ]

    def open(self, config: OpenConfig | str | None = None) -> DeviceInfo:
        """Open the ASCII connection and read device identification."""

        if isinstance(config, OpenConfig):
            self._host = config.address or config.device_id or self._host
            self._port = config.port or self._port or ASCII_PORT
            self._transport_kind = config.transport if config.transport != Transport.ANY else self._transport_kind
            self._device_family = str(config.options.get("device_family", self._device_family)).lower()
            self._src_port = int(config.options.get("src_port", self._src_port))
        elif isinstance(config, str):
            self._host = config
        if self._transport_kind == Transport.UDP and not self._device_family:
            self._device_family = "basic"
        if self._transport_kind == Transport.TCP and not self._device_family:
            self._device_family = "nt"
        if self._device_family == "basic" and self._transport_kind != Transport.UDP:
            raise CanApiError("CAN@net Basic ASCII is supported over UDP only")
        if self._device_family == "nt" and self._transport_kind != Transport.TCP:
            raise CanApiError("CAN@net NT ASCII is supported over TCP only")
        if self._transport is None:
            if not self._host:
                raise CanApiError("open(): no host configured")
            self._transport = _SocketTransport(self._host, self._port, self._transport_kind, self._src_port)
        self._device_info = DeviceInfo(
            device_id=self._host or "ascii-test",
            name=f"CAN@net {self._device_family.upper()} ASCII",
            transport=self._transport_kind,
            channel_count=self._max_ports,
            supports_can_fd=True,
            supports_listen_only=True,
        )
        try:
            firmware = self._query_text("DEV VERSION") or ""
            protocol = self._query_text("DEV PROTOCOL") or ""
            interfaces = self._query_text("DEV INTERFACES") or ""
            channel_count = min(self._max_ports, max(1, interfaces.upper().split().count("CAN"))) if interfaces else self._max_ports
            self._device_info = replace(
                self._device_info,
                channel_count=channel_count,
                firmware_version=firmware,
                hardware_version=protocol,
            )
        except CanApiError:
            if self._transport is not None:
                raise
        return self._device_info

    def _query_text(self, command: str) -> Optional[str]:
        self._send_command(command)
        return self._read_response()

    def close(self) -> None:
        """Close the ASCII connection."""

        if self._transport is not None:
            self._transport.close()
        self._transport = None
        self._device_info = None

    def identify(self) -> DeviceInfo:
        """Return cached identification information for the ASCII endpoint."""

        self._require_open()
        return self._device_info

    def init_can(self, port: int, config: ControllerConfig) -> None:
        """Initialize one CAN controller via ASCII command.

        Implicitly clears all receive filters for the given port.
        """

        self._require_open()
        self._validate_port(port)
        mode = "LISTEN" if config.listen_only else "STD"
        baud_a = config.arbitration.bitrate_kbit
        baud_d = config.data.bitrate_kbit if config.can_fd else 0
        if config.can_fd:
            iso = "ISO" if config.iso_mode else "nonISO"
            command = f"CAN {port} INIT mode={mode} baudA={baud_a} baudD={baud_d} iso={iso}"
        else:
            command = f"CAN {port} INIT mode={mode} baudA={baud_a}"
        self._send_command(command)
        self._expect_ok("init_can")
        self._send_command(f"CAN {port} FILTER CLEAR")
        self._expect_ok("init_can/filter_clear")

    def add_filter(self, port: int, can_filter: CanFilter) -> None:
        """Add one ASCII receive filter."""

        self._require_open()
        self._validate_port(port)
        command = (
            f"CAN {port} FILTER ADD type={self._filter_type(can_filter)} "
            f"id={can_filter.value:X} mask={can_filter.mask:X}"
        )
        self._send_command(command)
        self._expect_ok("add_filter")

    def start_can(self, port: int) -> None:
        """Start one CAN controller."""

        self._require_open()
        self._validate_port(port)
        self._rx_queues[port].clear()
        self._send_command(f"CAN {port} START")
        self._expect_ok("start_can")

    def stop_can(self, port: int) -> None:
        """Stop one CAN controller."""

        self._require_open()
        self._validate_port(port)
        self._send_command(f"CAN {port} STOP")
        self._expect_ok("stop_can")

    def send(self, port: int, message: CanMessage) -> None:
        """Send one CAN message using an ASCII ``M`` line."""

        self._require_open()
        self._validate_port(port)
        fmt = self._ascii_from_message(message)
        parts = [f"M {port} {fmt} {message.can_id:X}"]
        if message.frame_type == FrameType.REMOTE:
            parts.append(f"dlc={message.dlc}")
        else:
            parts.extend(f"{item:02X}" for item in message.data)
        self._send_command(" ".join(parts))

    def send_many(
        self,
        port: int,
        messages: Sequence[CanMessage],
        poll_interval: float = 0.001,
        overall_timeout: Optional[float] = None,
    ) -> int:
        """Send multiple ASCII messages using reported TX queue space."""

        return super().send_many(port, messages, poll_interval, overall_timeout)

    def receive(self, port: int, timeout: Optional[float] = 1.0) -> Optional[CanMessage]:
        """Receive one message and add a client-side timestamp."""

        self._require_open()
        self._validate_port(port)
        wait = timeout if timeout is not None else 1e9
        deadline = time.monotonic() + wait
        while True:
            self._read_available(timeout=0)
            if self._rx_queues[port]:
                return self._rx_queues[port].popleft()
            if wait == 0 or time.monotonic() >= deadline:
                return None
            self._read_available(timeout=min(0.01, max(0.0, deadline - time.monotonic())))

    def set_receive_callback(
        self,
        port: int,
        callback: Optional[ReceiveCallback],
    ) -> None:
        """Register or remove a cooperative receive callback."""

        self._require_open()
        self._validate_port(port)
        if callback is None:
            self._receive_callbacks.pop(port, None)
        else:
            self._receive_callbacks[port] = callback

    def process_cycle(self) -> None:
        """Read pending ASCII lines and dispatch queued receive callbacks."""

        self._read_available(timeout=0)
        for port, callback in list(self._receive_callbacks.items()):
            while self._rx_queues[port]:
                callback(port, self._rx_queues[port].popleft())

    def get_status(self, port: int) -> CanStatus:
        """Query and return CAN controller status."""

        self._require_open()
        self._validate_port(port)
        self._send_command(f"CAN {port} STATUS")
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            self._read_available(timeout=min(0.01, max(0.0, deadline - time.monotonic())))
            if port in self._status:
                status = self._status.pop(port)
                status.rx_pending = len(self._rx_queues[port])
                return status
        raise CanApiError("get_status(): target timeout")

    def get_last_error(self) -> tuple[int, str]:
        """Return the last ASCII backend error code and text."""

        return self._last_error

    def ascii_send(self, command: str | bytes) -> None:
        """Send a raw ASCII command."""

        self._send_command(command)

    def ascii_receive(self, timeout: Optional[float] = None) -> Optional[str]:
        """Read one raw ASCII response."""

        return self._read_response(timeout)


CanAscii = AsciiCan