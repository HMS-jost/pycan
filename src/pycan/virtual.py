# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Virtual in-memory CAN implementation for the generic CanApi.

The implementation exposes two virtual devices, ``vcan0`` and ``vcan1``. Each
device has two CAN ports. Ports with the same number are connected to the same
in-memory bus, so a message sent on port 1 can be received by other open and
started virtual devices on port 1.
"""

from __future__ import annotations

import copy
import time
from collections import deque
from dataclasses import replace
from threading import RLock
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
        FrameType,
        IdentifierFormat,
        OpenConfig,
        ReceiveCallback,
        Transport,
    )


MAX_NUM_MSG = 100
DEVICE_IDS = ("vcan0", "vcan1")
PORTS = (1, 2)


class Virtual(CanApi):
    """In-memory CAN device used for tests and demos without hardware."""

    _lock = RLock()
    _instances: list["Virtual"] = []

    def __init__(self, max_queue_size: int = MAX_NUM_MSG):
        self._max_queue_size = max_queue_size
        self._device_info: Optional[DeviceInfo] = None
        self._started = {port: False for port in PORTS}
        self._configs = {port: ControllerConfig() for port in PORTS}
        self._filters: dict[int, list[CanFilter]] = {port: [] for port in PORTS}
        self._rx_queues: dict[int, deque[CanMessage]] = {
            port: deque(maxlen=max_queue_size) for port in PORTS
        }
        self._receive_callbacks: dict[int, ReceiveCallback] = {}
        self._last_error: tuple[int, str] = (0, "")

    @classmethod
    def reset_bus(cls) -> None:
        """Remove all virtual devices from the shared bus.

        This helper is intended for tests, so each test can start from a clean
        in-memory bus state.
        """

        with cls._lock:
            cls._instances.clear()

    def _set_error(self, code: int, text: str) -> None:
        self._last_error = (code, text)

    def _require_open(self) -> None:
        if self._device_info is None:
            self._set_error(1, "device is not open")
            raise CanApiError("device is not open")

    @staticmethod
    def _validate_port(port: int) -> None:
        if port not in PORTS:
            raise CanApiError(f"invalid CAN port {port}")

    @staticmethod
    def _matches_filter(message: CanMessage, can_filter: CanFilter) -> bool:
        if can_filter.id_format != message.id_format:
            return False
        if can_filter.frame_type != message.frame_type:
            return False
        return (message.can_id & can_filter.mask) == can_filter.value

    def _accepts(self, port: int, message: CanMessage) -> bool:
        filters = self._filters[port]
        if not filters:
            return True
        return any(self._matches_filter(message, can_filter) for can_filter in filters)

    def _enqueue(self, port: int, message: CanMessage) -> None:
        queue = self._rx_queues[port]
        queue.append(copy.deepcopy(message))

    @staticmethod
    def _make_device_info(device_id: str) -> DeviceInfo:
        return DeviceInfo(
            device_id=device_id,
            name=f"Virtual CAN {device_id}",
            transport=Transport.VIRTUAL,
            channel_count=len(PORTS),
            supports_can_fd=True,
            supports_listen_only=True,
            firmware_version="virtual",
            hardware_version="virtual",
        )

    def get_device_list(self, transport: Transport = Transport.ANY) -> list[DeviceInfo]:
        """Return the available virtual CAN devices."""

        if transport not in (Transport.ANY, Transport.VIRTUAL):
            return []
        return [self._make_device_info(device_id) for device_id in DEVICE_IDS]

    def open(self, config: OpenConfig | str | None = None) -> DeviceInfo:
        """Open one virtual CAN device.

        config may be an OpenConfig, a device id string such as ``vcan0``, or
        None to open the first virtual device.
        """

        if isinstance(config, OpenConfig):
            device_id = config.device_id or config.address or DEVICE_IDS[0]
        elif isinstance(config, str):
            device_id = config or DEVICE_IDS[0]
        else:
            device_id = DEVICE_IDS[0]
        if device_id not in DEVICE_IDS:
            self._set_error(2, f"unknown virtual device {device_id}")
            raise CanApiError(f"unknown virtual device {device_id}")
        self._device_info = self._make_device_info(device_id)
        with self._lock:
            if self not in self._instances:
                self._instances.append(self)
        self._set_error(0, "")
        return self._device_info

    def close(self) -> None:
        """Close the virtual device and remove it from the shared bus."""

        with self._lock:
            if self in self._instances:
                self._instances.remove(self)
        self._device_info = None
        self._started = {port: False for port in PORTS}
        self._receive_callbacks.clear()
        for queue in self._rx_queues.values():
            queue.clear()

    def identify(self) -> DeviceInfo:
        """Return identification information for the open virtual device."""

        self._require_open()
        return self._device_info

    def init_can(self, port: int, config: ControllerConfig) -> None:
        """Initialize one virtual CAN port and clear its receive filters."""

        self._require_open()
        self._validate_port(port)
        self._configs[port] = config
        self._filters[port].clear()
        self._rx_queues[port].clear()
        self._set_error(0, "")

    def add_filter(self, port: int, can_filter: CanFilter) -> None:
        """Add one receive filter to a virtual CAN port."""

        self._require_open()
        self._validate_port(port)
        self._filters[port].append(can_filter)
        self._set_error(0, "")

    def start_can(self, port: int) -> None:
        """Start one virtual CAN port."""

        self._require_open()
        self._validate_port(port)
        self._started[port] = True
        self._set_error(0, "")

    def stop_can(self, port: int) -> None:
        """Stop one virtual CAN port."""

        self._require_open()
        self._validate_port(port)
        self._started[port] = False
        self._set_error(0, "")

    def send(self, port: int, message: CanMessage) -> None:
        """Send one message to all matching virtual devices on the same port."""

        self._require_open()
        self._validate_port(port)
        if not self._started[port]:
            self._set_error(3, f"CAN port {port} is not started")
            raise CanApiError(f"CAN port {port} is not started")
        if message.frame_type == FrameType.DATA:
            max_len = 64 if message.is_fd else 8
            if len(message.data) > max_len:
                raise ValueError(f"CAN data max {max_len} bytes, got {len(message.data)}")
        limit = 0x1FFFFFFF if message.id_format == IdentifierFormat.EXTENDED else 0x7FF
        if not 0 <= message.can_id <= limit:
            raise ValueError(f"CAN-ID 0x{message.can_id:X} out of range (max 0x{limit:X})")
        timestamp_us = int(time.time() * 1_000_000)
        bus_message = replace(message, port=port, timestamp_us=timestamp_us)
        with self._lock:
            for endpoint in list(self._instances):
                if endpoint._device_info is None or not endpoint._started[port]:
                    continue
                if endpoint._accepts(port, bus_message):
                    endpoint._enqueue(port, bus_message)
        self._set_error(0, "")

    def send_many(
        self,
        port: int,
        messages: Sequence[CanMessage],
        poll_interval: float = 0.001,
        overall_timeout: Optional[float] = None,
    ) -> int:
        """Send all messages and return the number accepted by the virtual bus."""

        sent = 0
        for message in messages:
            self.send(port, message)
            sent += 1
        return sent

    def receive(self, port: int, timeout: Optional[float] = 1.0) -> Optional[CanMessage]:
        """Receive one message from the virtual receive queue."""

        self._require_open()
        self._validate_port(port)
        wait = timeout if timeout is not None else 1e9
        deadline = time.monotonic() + wait
        while True:
            queue = self._rx_queues[port]
            if queue:
                self._set_error(0, "")
                return queue.popleft()
            if wait == 0 or time.monotonic() >= deadline:
                return None
            time.sleep(min(0.001, deadline - time.monotonic()))

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
        self._set_error(0, "")

    def process_cycle(self) -> None:
        """Dispatch all currently queued messages to registered callbacks."""

        for port, callback in list(self._receive_callbacks.items()):
            while True:
                message = self.receive(port, timeout=0)
                if message is None:
                    break
                callback(port, message)

    def get_status(self, port: int) -> CanStatus:
        """Return status for one virtual CAN port."""

        self._require_open()
        self._validate_port(port)
        rx_pending = len(self._rx_queues[port])
        if self._started[port]:
            return CanStatus(
                state=BusState.RUNNING,
                tx_free=self._max_queue_size,
                rx_pending=rx_pending,
                text="running",
            )
        return CanStatus(
            state=BusState.INIT,
            tx_free=self._max_queue_size,
            rx_pending=rx_pending,
            text="init",
        )

    def get_last_error(self) -> tuple[int, str]:
        """Return the last virtual backend error code and text."""

        return self._last_error


CanVirtual = Virtual