# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Transport-independent CAN API and CAN@net backend implementations."""

__version__ = "1.1.0"

from .can_api import (
	BusState,
	CanApi,
	CanApiError,
	CanFilter,
	CanMessage,
	CanStatus,
	CanTiming,
	ControllerConfig,
	DeviceInfo,
	FrameFormat,
	FrameType,
	IdentifierFormat,
	OpenConfig,
	ReceiveCallback,
	Transport,
)
from .ascii_can import AsciiCan, CanAscii
from .canudp import CanUdp
from .virtual import CanVirtual, Virtual

import sys as _sys
if _sys.platform == "win32":
	try:
		from .vci_can import VciCan, CanVci
	except ImportError:
		pass

__all__ = [
	"__version__",
	"AsciiCan",
	"BusState",
	"CanApi",
	"CanApiError",
	"CanAscii",
	"CanFilter",
	"CanMessage",
	"CanStatus",
	"CanTiming",
	"CanUdp",
	"CanVci",
	"CanVirtual",
	"ControllerConfig",
	"DeviceInfo",
	"FrameFormat",
	"FrameType",
	"IdentifierFormat",
	"OpenConfig",
	"ReceiveCallback",
	"Transport",
	"VciCan",
	"Virtual",
]
