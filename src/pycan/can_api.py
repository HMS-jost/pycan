# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Generic CAN API proposal.

This module defines a small transport-independent Python interface for Classic
CAN and CAN FD devices. It is intended as a common surface for USB, TCP, UDP,
VCI-style, and embedded gateway implementations.

Open points are marked with "tbd".
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from typing import Callable, Optional, Sequence


class CanApiError(Exception):
    """Base exception raised by CAN API implementations.

    The exact mapping between backend error codes and Python exceptions is tbd.
    """


class Transport(Enum):
    """Connection transport used to reach a CAN device."""

    ANY = auto()
    VIRTUAL = auto()
    USB = auto()
    SERIAL = auto()
    TCP = auto()
    UDP = auto()
    VCI = auto()
    TBD = auto()


class BusState(IntEnum):
    """Common CAN controller states."""

    UNKNOWN = 0
    INIT = 1
    RUNNING = 2
    ERROR_WARNING = 3
    ERROR_PASSIVE = 4
    OVERRUN = 5
    BUS_OFF = 6
    TBD = 32767


class FrameFormat(Enum):
    """Physical CAN frame family."""

    CLASSIC = auto()
    FD_NO_BRS = auto()
    FD_BRS = auto()
    TBD = auto()


class IdentifierFormat(Enum):
    """CAN identifier width."""

    STANDARD = auto()
    EXTENDED = auto()
    TBD = auto()


class FrameType(Enum):
    """CAN frame content type."""

    DATA = auto()
    REMOTE = auto()
    ERROR = auto()
    TBD = auto()


@dataclass(slots=True)
class DeviceInfo:
    """Information used to select or describe a CAN device.

    Attributes:
        device_id: Stable identifier that can be passed to open().
        name: Human-readable product or device name.
        transport: Transport used by this device.
        channel_count: Number of CAN ports reported by the device.
        supports_can_fd: True if the device supports CAN FD.
        supports_listen_only: True if listen-only mode is available.
        firmware_version: Firmware version string, if known.
        hardware_version: Hardware version string, if known.

    Unknown values should be empty strings, zero, or False. Additional fields
    such as serial number or IP metadata are tbd.
    """

    device_id: str = ""
    name: str = ""
    transport: Transport = Transport.ANY
    channel_count: int = 0
    supports_can_fd: bool = False
    supports_listen_only: bool = False
    firmware_version: str = ""
    hardware_version: str = ""


@dataclass(slots=True)
class OpenConfig:
    """Connection parameters for open().

    Attributes:
        transport: Preferred transport or Transport.ANY.
        device_id: Device identifier returned by get_device_list().
        address: Transport-specific address such as an IP address or COM port.
        port: Transport-specific network or service port.
        options: Backend-specific options. Supported keys are tbd.
    """

    transport: Transport = Transport.ANY
    device_id: str = ""
    address: str = ""
    port: int = 0
    options: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CanTiming:
    """CAN bitrate or explicit timing-register configuration.

    Set bitrate_kbit for normal preset-based initialization. Set
    use_register_values to True when brp, sjw, tseg1, tseg2, and tdo should be
    used directly. Validation rules for timing values are tbd.
    """

    bitrate_kbit: int = 500
    brp: int = 0
    sjw: int = 0
    tseg1: int = 0
    tseg2: int = 0
    tdo: int = 0
    use_register_values: bool = False


@dataclass(slots=True)
class ControllerConfig:
    """CAN controller configuration for init_can().

    Attributes:
        can_fd: Enable CAN FD mode.
        bitrate_switch: Enable CAN FD bitrate switching.
        listen_only: Keep the controller passive on the CAN bus.
        iso_mode: Use ISO CAN FD when True. Non-ISO behavior is tbd.
        receive_standard: Accept standard 11-bit identifiers.
        receive_extended: Accept extended 29-bit identifiers.
        receive_remote: Accept remote frames.
        arbitration: Arbitration phase timing.
        data: Data phase timing for CAN FD.
        options: Backend-specific options. Supported keys are tbd.
    """

    can_fd: bool = False
    bitrate_switch: bool = False
    listen_only: bool = False
    iso_mode: bool = True
    receive_standard: bool = True
    receive_extended: bool = True
    receive_remote: bool = True
    arbitration: CanTiming = field(default_factory=CanTiming)
    data: CanTiming = field(default_factory=lambda: CanTiming(bitrate_kbit=0))
    options: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CanFilter:
    """Receive filter definition.

    A message is accepted when (message_id & mask) == value and the identifier
    format matches. Whether clearing all filters means "accept none" or
    "accept all" is tbd per backend.
    """

    id_format: IdentifierFormat = IdentifierFormat.STANDARD
    frame_type: FrameType = FrameType.DATA
    mask: int = 0
    value: int = 0
    options: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CanMessage:
    """CAN message used for sending and receiving.

    Attributes:
        can_id: 11-bit or 29-bit CAN identifier.
        data: Payload bytes. Classic CAN allows 0..8 bytes, CAN FD allows
            up to 64 bytes.
        id_format: Standard or extended identifier format.
        frame_format: Classic CAN, CAN FD without BRS, or CAN FD with BRS.
        frame_type: Data, remote, or error frame.
        timestamp_us: Receive timestamp in microseconds. The time base is tbd.
        port: CAN port number. The explicit method port argument wins when both
            are present.
        flags: Backend-specific flags. Supported bits are tbd.
    """

    can_id: int
    data: bytes = b""
    id_format: IdentifierFormat = IdentifierFormat.STANDARD
    frame_format: FrameFormat = FrameFormat.CLASSIC
    frame_type: FrameType = FrameType.DATA
    timestamp_us: int = 0
    port: int = 1
    flags: int = 0

    @property
    def dlc(self) -> int:
        """Return the payload length in bytes.

        This API uses byte counts, not the encoded CAN FD DLC value. Valid
        lengths are 0..8 for Classic CAN and 0..64 for CAN FD.
        """

        return len(self.data)

    @property
    def is_extended(self) -> bool:
        """Return True when this message uses a 29-bit CAN identifier."""

        return self.id_format == IdentifierFormat.EXTENDED

    @property
    def is_rtr(self) -> bool:
        """Return True when this message is a remote transmission request."""

        return self.frame_type == FrameType.REMOTE

    @property
    def is_fd(self) -> bool:
        """Return True when this message is a CAN FD frame."""

        return self.frame_format in (FrameFormat.FD_NO_BRS, FrameFormat.FD_BRS)

    @property
    def format_str(self) -> str:
        """Return the common three-letter format string such as CSD or FED."""

        if self.frame_format == FrameFormat.FD_BRS:
            can_type = "F"
        elif self.frame_format == FrameFormat.FD_NO_BRS:
            can_type = "N"
        else:
            can_type = "C"
        id_type = "E" if self.is_extended else "S"
        frame_type = "R" if self.is_rtr else "D"
        return can_type + id_type + frame_type

    def __str__(self) -> str:
        id_str = f"{self.can_id:08x}" if self.is_extended else f"     {self.can_id:03x}"
        data_str = f"dlc={self.dlc}" if self.is_rtr else self.data.hex(" ")
        return f"{id_str}    {self.format_str}    {data_str}"


@dataclass(slots=True)
class CanStatus:
    """CAN controller status returned by get_status().

    Attributes:
        state: Current bus state.
        tx_free: Number of free transmit queue entries, if known.
        rx_pending: Number of queued receive messages, if known.
        error_code: Backend-specific diagnostic code.
        text: Human-readable status text.
        flags: Backend-specific status flags. Supported bits are tbd.
    """

    state: BusState = BusState.UNKNOWN
    tx_free: int = 0
    rx_pending: int = 0
    error_code: int = 0
    text: str = ""
    flags: int = 0

    @property
    def status_text(self) -> str:
        """Return a human-readable status text."""

        if self.text:
            return self.text
        return self.state.name.lower().replace("_", " ")

    @property
    def is_ok(self) -> bool:
        """Return True when the CAN controller is running normally."""

        return self.state == BusState.RUNNING


ReceiveCallback = Callable[[int, CanMessage], None]


class CanApi(ABC):
    """Abstract base class for a generic CAN interface.

    Implementations should keep method names and data classes stable across
    transports. Blocking behavior, thread-safety, and callback interaction are
    tbd unless an implementation documents them explicitly.
    """

    @abstractmethod
    def get_device_list(self, transport: Transport = Transport.ANY) -> list[DeviceInfo]:
        """Return available CAN devices.

        The returned DeviceInfo.device_id values should be accepted by open().
        Discovery behavior for remote/network devices is tbd.
        """

    @abstractmethod
    def open(self, config: OpenConfig | str | None = None) -> DeviceInfo:
        """Open a CAN device or network endpoint.

        config may be an OpenConfig, a device_id string, or None to select a
        default device. The method returns identification information for the
        opened device and raises CanApiError on failure.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the connection and release resources.

        Applications should stop active CAN controllers before closing when bus
        state matters. Whether close() implicitly stops controllers is tbd.
        """

    @abstractmethod
    def identify(self) -> DeviceInfo:
        """Read identification and capability information from the open device.

        Unknown fields should be returned as empty strings, zero, or False.
        """

    @abstractmethod
    def init_can(self, port: int, config: ControllerConfig) -> None:
        """Initialize a CAN controller without starting bus traffic.

        The configuration selects Classic CAN or CAN FD, nominal/data bitrate,
        listen-only mode, and accepted frame classes. Valid bitrate ranges are
        tbd.
        """

    @abstractmethod
    def add_filter(self, port: int, can_filter: CanFilter) -> None:
        """Add one receive filter to a CAN controller.

        A message is accepted when (message_id & mask) == value and the
        identifier format matches. Filter capacity is tbd per backend.
        """

    @abstractmethod
    def clear_filters(self, port: int) -> None:
        """Remove all receive filters from a CAN controller.

        The default receive behavior after clearing filters is tbd.
        """

    @abstractmethod
    def start_can(self, port: int) -> None:
        """Start a previously initialized CAN controller.

        After this call, transmit and receive operations are enabled for the
        selected port.
        """

    @abstractmethod
    def stop_can(self, port: int) -> None:
        """Stop a CAN controller.

        Applications should normally check get_status().tx_free before stopping
        if pending transmissions must be completed. Blocking behavior is tbd.
        """

    @abstractmethod
    def send(self, port: int, message: CanMessage) -> None:
        """Send one CAN message.

        Implementations should validate identifier range and payload length for
        the selected frame format. Payload length is expressed as bytes, not as
        the encoded CAN FD DLC value.
        """

    def send_many(
        self,
        port: int,
        messages: Sequence[CanMessage],
        poll_interval: float = 0.001,
        overall_timeout: Optional[float] = None,
    ) -> int:
        """Send multiple messages while respecting reported TX queue space.

        This generic helper repeatedly reads get_status(port).tx_free and sends
        no more messages than the backend reports as currently available. It is
        intentionally conservative and portable; backends may override it when
        they have a cheaper local TX-free cache or protocol-specific batching.

        Args:
            port: CAN port number.
            messages: Sequence of messages to send.
            poll_interval: Sleep interval used while tx_free is zero.
            overall_timeout: Optional maximum total time in seconds.

        Returns:
            Number of messages sent.

        Raises:
            TimeoutError: If overall_timeout expires before all messages are sent.
        """

        sent = 0
        total = len(messages)
        deadline = None if overall_timeout is None else time.monotonic() + overall_timeout
        while sent < total:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("send_many(): timeout waiting for TX space")
            self.process_cycle()
            tx_free = self.get_status(port).tx_free
            chunk = min(tx_free, total - sent)
            if chunk <= 0:
                time.sleep(poll_interval)
                continue
            for message in messages[sent:sent + chunk]:
                self.send(port, message)
            sent += chunk
        return sent

    @abstractmethod
    def receive(self, port: int, timeout: Optional[float] = 1.0) -> Optional[CanMessage]:
        """Receive one CAN message.

        timeout is given in seconds. A value of 0 should poll once. A value of
        None should wait indefinitely unless the backend documents otherwise.
        The timestamp time base is tbd.
        """

    @abstractmethod
    def set_receive_callback(
        self,
        port: int,
        callback: Optional[ReceiveCallback],
    ) -> None:
        """Register or remove a receive callback.

        Passing None disables callbacks for the selected port. A port should use
        either callbacks or receive() polling as its active receive model. Both
        consume the same receive stream; mixing them makes message ownership
        depend on whichever path reads first.
        """

    @abstractmethod
    def process_cycle(self) -> None:
        """Run backend-specific background processing once.

        Cooperative implementations can use this method to process incoming
        packets, dispatch callbacks, or send heartbeat messages. Implementations
        with worker threads may do nothing. Required call frequency is tbd.
        """

    @abstractmethod
    def get_status(self, port: int) -> CanStatus:
        """Return CAN controller status.

        The status includes bus state, transmit queue capacity, receive queue
        count, and backend-specific error information. Exact flag semantics are
        tbd.
        """

    @abstractmethod
    def get_last_error(self) -> tuple[int, str]:
        """Return backend-specific diagnostic information.

        The tuple contains an implementation-specific error code and English
        text. Whether reading this value clears it is tbd.
        """

    def __enter__(self) -> CanApi:
        """Return this object for context-manager use.

        Automatic opening is intentionally not defined here; whether a concrete
        implementation opens in __enter__ is tbd.
        """

        return self

    def __exit__(self, *exc: object) -> None:
        """Close the API object when leaving a context manager."""

        self.close()