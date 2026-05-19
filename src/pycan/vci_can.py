# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""VCI backend for the generic CanApi.

This backend uses the IXXAT VCI V4 DLL (``vcinpl2.dll``) via ctypes and
supports Classic CAN and CAN FD on Windows.  The device is identified by its
serial number (e.g. ``HW426714``), passed via ``OpenConfig.device_id``.

Typical usage::

    from pycan import VciCan, OpenConfig, Transport, ControllerConfig, CanTiming

    can = VciCan()
    can.open(OpenConfig(transport=Transport.VCI, device_id="HW426714"))
    can.init_can(1, ControllerConfig(arbitration=CanTiming(bitrate_kbit=500)))
    can.start_can(1)
    can.send(1, CanMessage(0x200, b"\\x11\\x22\\x33\\x44"))
    can.close()
"""

from __future__ import annotations

import time
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

try:
    from ._vci2 import (
        VCI,
        CanMsg,
        MsgInfo,
        VciError,
        CAN_STATUS_BUSOFF,
        CAN_STATUS_ERRLIM,
        CAN_STATUS_ININIT,
        CAN_STATUS_OVRRUN,
        CAN_STATUS_TXPEND,
        bytes_to_dlc,
        dlc_to_bytes,
    )
    from ctypes import c_uint8
except (ImportError, OSError) as exc:
    raise ImportError(
        "VCI backend requires Windows and the IXXAT VCI V4 runtime (vcinpl2.dll)"
    ) from exc

MAX_PORTS = 4


class VciCan(CanApi):
    """IXXAT VCI V4 implementation of the common CAN API."""

    #: Maximum number of acceptance filters per port.
    MAX_FILTERS = 5

    def __init__(self):
        self._vci: Optional[VCI] = None
        self._device_info: Optional[DeviceInfo] = None
        self._configs: dict[int, ControllerConfig] = {}
        self._filters: dict[int, list[CanFilter]] = {}
        self._receive_callbacks: dict[int, ReceiveCallback] = {}
        self._last_error: tuple[int, str] = (0, "")

    def _set_error(self, code: int, text: str) -> None:
        self._last_error = (code, text)

    def _require_open(self) -> None:
        if self._vci is None:
            raise CanApiError("device is not open")

    def _validate_port(self, port: int) -> None:
        if not 1 <= port <= MAX_PORTS:
            raise CanApiError(f"invalid CAN port {port} (must be 1..{MAX_PORTS})")

    @staticmethod
    def _channel(port: int) -> int:
        """Convert 1-based port to 0-based VCI channel number."""
        return port - 1

    # ------------------------------------------------------------------
    # CanApi implementation
    # ------------------------------------------------------------------

    def get_device_list(self, transport: Transport = Transport.ANY) -> list[DeviceInfo]:
        if transport not in (Transport.ANY, Transport.VCI):
            return []
        try:
            vci = VCI(no_rx_thread=True)
            devices = vci.get_device_list()
            vci.closeDevice() if vci.hDevice else None
        except (OSError, VciError):
            return []
        result = []
        for _obj_id, serial, description in devices:
            result.append(DeviceInfo(
                device_id=serial.decode(errors="replace"),
                name=description.decode(errors="replace"),
                transport=Transport.VCI,
                channel_count=MAX_PORTS,
                supports_can_fd=True,
                supports_listen_only=True,
            ))
        return result

    def open(self, config: OpenConfig | str | None = None) -> DeviceInfo:
        serial_num: Optional[str] = None
        if isinstance(config, OpenConfig):
            serial_num = config.device_id or None
        elif isinstance(config, str):
            serial_num = config
        if not serial_num:
            raise CanApiError("open(): device_id (serial number) required for VCI")

        try:
            self._vci = VCI(no_rx_thread=False)
            self._vci.openDevice(serialNum=serial_num)
        except VciError as exc:
            self._vci = None
            raise CanApiError(str(exc)) from exc

        self._device_info = DeviceInfo(
            device_id=serial_num,
            name=f"IXXAT VCI ({serial_num})",
            transport=Transport.VCI,
            channel_count=MAX_PORTS,
            supports_can_fd=True,
            supports_listen_only=True,
        )
        return self._device_info

    def close(self) -> None:
        if self._vci is not None:
            for ch in range(MAX_PORTS):
                if self._vci.lCanStarted[ch]:
                    self._vci.closeCanChannel(ch)
                    self._vci.closeCanControl(ch)
            self._vci.closeDevice()
            self._vci = None
        self._device_info = None
        self._configs.clear()
        self._filters.clear()

    def identify(self) -> DeviceInfo:
        self._require_open()
        return self._device_info  # type: ignore[return-value]

    def init_can(self, port: int, config: ControllerConfig) -> None:
        self._require_open()
        self._validate_port(port)
        ch = self._channel(port)

        # Stop if already running
        if self._vci.lCanStarted[ch]:
            self._vci.closeCanChannel(ch)
            self._vci.closeCanControl(ch)

        self._configs[port] = config
        self._filters[port] = []

    def add_filter(self, port: int, can_filter: CanFilter) -> None:
        self._require_open()
        self._validate_port(port)
        if port not in self._filters:
            self._filters[port] = []
        if len(self._filters[port]) >= self.MAX_FILTERS:
            raise CanApiError(
                f"add_filter({port}): max {self.MAX_FILTERS} filters per port"
            )
        self._filters[port].append(can_filter)

    def start_can(self, port: int) -> None:
        self._require_open()
        self._validate_port(port)
        ch = self._channel(port)

        config = self._configs.get(port)
        if config is None:
            raise CanApiError(f"start_can({port}): init_can not called")

        baudrateA = config.arbitration.bitrate_kbit
        baudrateD = config.data.bitrate_kbit if config.can_fd else None

        try:
            # Close if previously opened (e.g. restart)
            if self._vci.lCanStarted[ch]:
                self._vci.closeCanChannel(ch)
                self._vci.closeCanControl(ch)

            self._vci.openCanChannel(ch)
            self._vci.openCanControl(
                ch,
                baudrateA=baudrateA,
                baudrateD=baudrateD,
                listen_only=config.listen_only,
                nonISO=not config.iso_mode if config.can_fd else False,
            )
        except VciError as exc:
            raise CanApiError(f"start_can({port}): {exc}") from exc

    def stop_can(self, port: int) -> None:
        self._require_open()
        self._validate_port(port)
        ch = self._channel(port)
        if self._vci.lCanStarted[ch]:
            self._vci.closeCanChannel(ch)
            self._vci.closeCanControl(ch)

    def _accepts(self, port: int, can_id: int, id_format: IdentifierFormat) -> bool:
        """Return True if *can_id* passes the software acceptance filter."""
        filters = self._filters.get(port)
        if not filters:
            return True  # no filters configured → accept all
        for f in filters:
            if f.id_format != id_format:
                continue
            if (can_id & f.mask) == (f.value & f.mask):
                return True
        # Filters exist but none matched
        return False

    def send(self, port: int, message: CanMessage) -> None:
        self._require_open()
        self._validate_port(port)
        ch = self._channel(port)
        msg = self._to_vci_msg(message)
        if not self._vci.sendMsg(ch, msg):
            raise CanApiError(f"send({port}): transmit failed (timeout)")

    def send_many(
        self,
        port: int,
        messages: Sequence[CanMessage],
        poll_interval: float = 0.001,
        overall_timeout: Optional[float] = None,
    ) -> int:
        self._require_open()
        self._validate_port(port)
        ch = self._channel(port)
        sent = 0
        deadline = None if overall_timeout is None else time.monotonic() + overall_timeout
        for message in messages:
            if deadline is not None and time.monotonic() >= deadline:
                break
            msg = self._to_vci_msg(message)
            if self._vci.sendMsg(ch, msg):
                sent += 1
            else:
                break
        return sent

    def receive(self, port: int, timeout: Optional[float] = 1.0) -> Optional[CanMessage]:
        self._require_open()
        self._validate_port(port)
        ch = self._channel(port)
        wait = timeout if timeout is not None else 1e9
        deadline = time.monotonic() + wait

        while True:
            raw = self._vci.readMsg(ch)
            if raw is not None:
                id_fmt = IdentifierFormat.EXTENDED if raw.MsgInfo.ext else IdentifierFormat.STANDARD
                if self._accepts(port, raw.MsgId, id_fmt):
                    return self._from_vci_msg(raw, port)
                continue  # filtered out, keep reading until timeout
            if wait == 0 or time.monotonic() >= deadline:
                return None
            time.sleep(0.001)

    def set_receive_callback(self, port: int, callback: Optional[ReceiveCallback]) -> None:
        self._require_open()
        self._validate_port(port)
        if callback is None:
            self._receive_callbacks.pop(port, None)
        else:
            self._receive_callbacks[port] = callback

    def process_cycle(self) -> None:
        if self._vci is None:
            return
        for port in range(1, MAX_PORTS + 1):
            ch = self._channel(port)
            callback = self._receive_callbacks.get(port)
            if callback is None:
                continue
            while True:
                raw = self._vci.readMsg(ch)
                if raw is None:
                    break
                id_fmt = IdentifierFormat.EXTENDED if raw.MsgInfo.ext else IdentifierFormat.STANDARD
                if self._accepts(port, raw.MsgId, id_fmt):
                    callback(port, self._from_vci_msg(raw, port))

    def get_status(self, port: int) -> CanStatus:
        self._require_open()
        self._validate_port(port)
        ch = self._channel(port)
        try:
            sts = self._vci.getStatus(ch)
        except (VciError, OSError):
            return CanStatus(state=BusState.UNKNOWN)

        if sts.Status & CAN_STATUS_BUSOFF:
            state = BusState.BUS_OFF
        elif sts.Status & CAN_STATUS_ERRLIM:
            state = BusState.ERROR_WARNING
        elif sts.Status & CAN_STATUS_OVRRUN:
            state = BusState.OVERRUN
        elif sts.Status & CAN_STATUS_ININIT:
            state = BusState.INIT
        else:
            state = BusState.RUNNING

        tx_pending = 1 if (sts.Status & CAN_STATUS_TXPEND) else 0
        return CanStatus(
            state=state,
            tx_free=QUEUE_SIZE - tx_pending,
            rx_pending=self._vci.rxPending(ch),
            flags=sts.Status,
        )

    def get_last_error(self) -> tuple[int, str]:
        return self._last_error

    # ------------------------------------------------------------------
    # Message conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_vci_msg(message: CanMessage) -> CanMsg:
        """Convert a pycan CanMessage to a VCI CanMsg."""
        is_fd = message.frame_format in (FrameFormat.FD_NO_BRS, FrameFormat.FD_BRS)
        is_brs = message.frame_format == FrameFormat.FD_BRS

        if is_fd:
            dlc = bytes_to_dlc(len(message.data))
        elif message.frame_type == FrameType.REMOTE:
            dlc = message.dlc
        else:
            dlc = len(message.data)

        info = MsgInfo(
            rtr=1 if message.frame_type == FrameType.REMOTE else 0,
            ext=1 if message.id_format == IdentifierFormat.EXTENDED else 0,
            edl=1 if is_fd else 0,
            fdr=1 if is_brs else 0,
            dlc=dlc,
            ssm=0,
            hpm=0,
        )
        data = (c_uint8 * 64)()
        for i, b in enumerate(message.data[:64]):
            data[i] = b

        return CanMsg(MsgId=message.can_id, Time=0, MsgInfo=info, Data=data)

    @staticmethod
    def _from_vci_msg(raw: CanMsg, port: int) -> CanMessage:
        """Convert a VCI CanMsg to a pycan CanMessage."""
        id_format = IdentifierFormat.EXTENDED if raw.MsgInfo.ext else IdentifierFormat.STANDARD
        if raw.MsgInfo.rtr:
            frame_type = FrameType.REMOTE
        else:
            frame_type = FrameType.DATA

        if raw.MsgInfo.fdr:
            frame_format = FrameFormat.FD_BRS
        elif raw.MsgInfo.edl:
            frame_format = FrameFormat.FD_NO_BRS
        else:
            frame_format = FrameFormat.CLASSIC

        if frame_format in (FrameFormat.FD_NO_BRS, FrameFormat.FD_BRS):
            num_bytes = dlc_to_bytes(raw.MsgInfo.dlc)
        else:
            num_bytes = raw.MsgInfo.dlc

        if frame_type == FrameType.REMOTE:
            data = bytes(num_bytes)
        else:
            data = bytes(raw.Data[:num_bytes])

        return CanMessage(
            can_id=raw.MsgId,
            data=data,
            id_format=id_format,
            frame_format=frame_format,
            frame_type=frame_type,
            timestamp_us=raw.Time,
            port=port,
        )


# Convenience alias
CanVci = VciCan

# Re-export QUEUE_SIZE for status calculations
QUEUE_SIZE = 10000
