# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (C) 2015-2017 IXXAT Automation GmbH, all rights reserved
# Copyright (c) 2025-2026 HMS Technology Center GmbH (minor cleanups)

"""VCI V4 low-level wrapper for IXXAT CAN interfaces (Windows only).

This is a private helper module used by :mod:`pycan.vci_can`.  It wraps the
native ``vcinpl2.dll`` via ctypes and exposes a simplified Python API for
device enumeration, channel/control lifecycle, and message send/receive.
"""

from __future__ import annotations

import copy
import ctypes
import re
import struct
import sys
import threading
import time
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_uint,
    c_uint8,
    c_uint16,
    c_uint32,
    c_void_p,
    create_string_buffer,
    windll,
)
from ctypes.util import find_library
from typing import Optional

__revision__ = "2.00.00"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VCI_OK = 0x0
VCI_MAX_BUSCTRL = 32
QUEUE_SIZE = 10000

# Bus Type
VCI_BUS_CAN = 1
VCI_BUS_LIN = 2

# Controller operating modes
CAN_OPMODE_UNDEFINED = 0x00
CAN_OPMODE_STANDARD = 0x01
CAN_OPMODE_EXTENDED = 0x02
CAN_OPMODE_ERRFRAME = 0x04
CAN_OPMODE_LISTONLY = 0x08
CAN_OPMODE_LOWSPEED = 0x10
CAN_OPMODE_AUTOBAUD = 0x20

# Extended operating modes
CAN_EXMODE_DISABLED = 0x00
CAN_EXMODE_EXTDATA = 0x01
CAN_EXMODE_FASTDATA = 0x02
CAN_EXMODE_NONISO = 0x04

# Filter modes
CAN_FILTER_LOCK = 0x01
CAN_FILTER_PASS = 0x02
CAN_FILTER_INCL = 0x03
CAN_FILTER_EXCL = 0x04

# Message types
CAN_MSGTYPE_DATA = 0
CAN_MSGTYPE_INFO = 1
CAN_MSGTYPE_ERROR = 2
CAN_MSGTYPE_STATUS = 3
CAN_MSGTYPE_WAKEUP = 4
CAN_MSGTYPE_TIMEOVR = 5
CAN_MSGTYPE_TIMERST = 6

# Controller status flags
CAN_STATUS_TXPEND = 0x01
CAN_STATUS_OVRRUN = 0x02
CAN_STATUS_ERRLIM = 0x04
CAN_STATUS_BUSOFF = 0x08
CAN_STATUS_ININIT = 0x10

# Bit timing mode
CAN_BTMODE_RAW = 0x00000001
CAN_BTMODE_TSM = 0x00000002

# Standard bit timing tables (brp, tseg1, tseg2, sjw, tdo)
BITRATE_TABLE_A = {
    125: (8, 63, 16, 16, 0),
    250: (4, 63, 16, 16, 0),
    500: (2, 63, 16, 16, 0),
    1000: (2, 31, 8, 8, 0),
}

BITRATE_TABLE_D = {
    500: (8, 15, 4, 4, 80),
    1000: (4, 15, 4, 4, 40),
    2000: (2, 15, 4, 4, 20),
    4000: (2, 7, 2, 2, 10),
    5000: (2, 5, 2, 2, 8),
    8000: (2, 3, 1, 1, 5),
}


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------


class _Struct(Structure):
    """ctypes Structure with keyword-argument init."""

    def __init__(self, **kwargs):
        for field_name, *_ in self._fields_:
            if field_name in kwargs:
                setattr(self, field_name, kwargs[field_name])


class CANBTP(_Struct):
    _fields_ = [
        ("dwMode", c_uint32),
        ("dwBPS", c_uint32),
        ("wTS1", c_uint16),
        ("wTS2", c_uint16),
        ("wSJW", c_uint16),
        ("wTDO", c_uint16),
    ]


class CanLineStatus(_Struct):
    _fields_ = [
        ("OpMode", c_uint8),
        ("ExMode", c_uint8),
        ("BusLoad", c_uint8),
        ("Rsrvd", c_uint8),
        ("sBtpSdr", CANBTP),
        ("sBtpFdr", CANBTP),
        ("Status", c_uint32),
    ]


class MsgInfo(_Struct):
    _fields_ = [
        ("type", c_uint, 8),
        ("ssm", c_uint, 1),
        ("hpm", c_uint, 1),
        ("edl", c_uint, 1),
        ("fdr", c_uint, 1),
        ("esi", c_uint, 1),
        ("res", c_uint, 3),
        ("dlc", c_uint, 4),
        ("ovr", c_uint, 1),
        ("srr", c_uint, 1),
        ("rtr", c_uint, 1),
        ("ext", c_uint, 1),
        ("afc", c_uint, 8),
    ]


class CanMsg(_Struct):
    _fields_ = [
        ("Time", c_uint32),
        ("_rsvd_", c_uint32),
        ("MsgId", c_uint32),
        ("MsgInfo", MsgInfo),
        ("Data", c_uint8 * 64),
    ]


# ---------------------------------------------------------------------------
# DLC <-> byte count helpers
# ---------------------------------------------------------------------------

_DLC_TO_BYTES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64]


def dlc_to_bytes(dlc: int) -> int:
    """Convert CAN FD DLC code (0..15) to payload byte count."""
    if 0 <= dlc <= 15:
        return _DLC_TO_BYTES[dlc]
    return 0


def bytes_to_dlc(num_bytes: int) -> int:
    """Convert payload byte count to smallest matching CAN FD DLC code."""
    for dlc, length in enumerate(_DLC_TO_BYTES):
        if length >= num_bytes:
            return dlc
    return 15


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class VciError(Exception):
    """Raised on VCI DLL errors."""


# ---------------------------------------------------------------------------
# VCI class
# ---------------------------------------------------------------------------


class VCI:
    """High-level wrapper around the VCI V4 native DLL."""

    def __init__(self, no_rx_thread: bool = False):
        dllpath = "C:\\windows\\system32\\vcinpl2.dll"
        self.vcidll = windll.LoadLibrary(dllpath)
        if self.vcidll.vciInitialize() != VCI_OK:
            raise VciError("vciInitialize failed")
        self.lDevices: list = []
        self._enumerate_devices()
        self.hDevice: Optional[c_void_p] = None
        self.canChn: list[Optional[c_void_p]] = [None] * 4
        self.canCtrl: list[Optional[c_void_p]] = [None] * 4
        self.lRxMsg: list[list[CanMsg]] = [[], [], [], []]
        self.lCanStarted: list[bool] = [False, False, False, False]
        self.rxTaskActive = not no_rx_thread
        self._lock = threading.Lock()
        if not no_rx_thread:
            self._rx_thread = threading.Thread(target=self._receive_task, daemon=True)
            self._rx_thread.start()
        else:
            self._rx_thread = None

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------

    def _enumerate_devices(self) -> None:
        hEnum = c_void_p()
        self.lDevices = []
        buf = create_string_buffer(304)
        self.vcidll.vciEnumDeviceOpen(byref(hEnum))
        while self.vcidll.vciEnumDeviceNext(hEnum, buf) == VCI_OK:
            self.lDevices.append(self._parse_device_info(buf))
        self.vcidll.vciEnumDeviceClose(hEnum)

    @staticmethod
    def _parse_device_info(buf) -> tuple[bytes, bytes, bytes]:
        (
            obj_id, _dev_class,
            _drv_major, _drv_minor, _drv_build,
            _hw_branch, _hw_major, _hw_minor, _hw_build,
            unique_id, description, _manufacturer, _drv_release,
        ) = struct.unpack("8s16sBBHBBBB16s128s126sH", buf)
        return obj_id, unique_id.split(b"\0")[0], description.split(b"\0")[0]

    def get_device_list(self) -> list[tuple[bytes, bytes, bytes]]:
        """Return list of (obj_id, serial_number, description) tuples."""
        self._enumerate_devices()
        return self.lDevices

    # ------------------------------------------------------------------
    # Device open/close
    # ------------------------------------------------------------------

    def openDevice(self, devIdx: Optional[int] = None, serialNum: Optional[str] = None) -> bool:
        self.hDevice = c_void_p()
        if devIdx is not None:
            res = self.vcidll.vciDeviceOpen(self.lDevices[devIdx][0], byref(self.hDevice))
            if res != VCI_OK:
                raise VciError(f"vciDeviceOpen failed (index {devIdx})")
        elif serialNum is not None:
            serial_bytes = serialNum.encode() if isinstance(serialNum, str) else serialNum
            matches = [d for d in self.lDevices if d[1] == serial_bytes]
            if len(matches) == 0:
                raise VciError(f"No VCI device with serial {serialNum}")
            if len(matches) > 1:
                # Filter to IP-addressed devices (ETH vs USB duplicates)
                ip_matches = [d for d in matches if re.match(rb"^\d+\.\d+\.\d+\.\d+$", d[2])]
                matches = ip_matches if ip_matches else matches[:1]
            res = self.vcidll.vciDeviceOpen(matches[0][0], byref(self.hDevice))
            if res != VCI_OK:
                raise VciError(f"vciDeviceOpen failed ({serialNum})")
        else:
            raise VciError("No device specified")
        return True

    def closeDevice(self) -> None:
        self.stop_reception()
        if self.hDevice:
            self.vcidll.vciDeviceClose(self.hDevice)
            self.hDevice = None

    # ------------------------------------------------------------------
    # Channel / Control
    # ------------------------------------------------------------------

    def openCanChannel(self, channelNo: int) -> None:
        self.canChn[channelNo] = c_void_p()
        res = self.vcidll.canChannelOpen(self.hDevice, channelNo, False, byref(self.canChn[channelNo]))
        if res != VCI_OK:
            raise VciError(f"canChannelOpen({channelNo}) failed: 0x{res:08X}")
        res = self.vcidll.canChannelInitialize(self.canChn[channelNo], QUEUE_SIZE, 1, QUEUE_SIZE, 1, 0, CAN_FILTER_PASS)
        if res != VCI_OK:
            raise VciError(f"canChannelInitialize({channelNo}) failed: 0x{res:08X}")
        res = self.vcidll.canChannelActivate(self.canChn[channelNo], True)
        if res != VCI_OK:
            raise VciError(f"canChannelActivate({channelNo}) failed: 0x{res:08X}")

    def openCanControl(
        self,
        channelNo: int,
        baudrateA: int,
        baudrateD: Optional[int] = None,
        listen_only: bool = False,
        nonISO: bool = False,
        sfMode: int = CAN_FILTER_PASS,
        efMode: int = CAN_FILTER_PASS,
    ) -> None:
        self.canCtrl[channelNo] = c_void_p()
        res = self.vcidll.canControlOpen(self.hDevice, channelNo, byref(self.canCtrl[channelNo]))
        if res != VCI_OK:
            raise VciError(f"canControlOpen({channelNo}) failed: 0x{res:08X}")

        opMode = CAN_OPMODE_STANDARD | CAN_OPMODE_EXTENDED | CAN_OPMODE_ERRFRAME
        if listen_only:
            opMode |= CAN_OPMODE_LISTONLY

        exMode = CAN_EXMODE_DISABLED
        if baudrateD is not None:
            exMode = CAN_EXMODE_EXTDATA | CAN_EXMODE_FASTDATA
        if nonISO:
            exMode |= CAN_EXMODE_NONISO

        # Arbitration bit timing
        if baudrateD is not None and baudrateA in BITRATE_TABLE_A:
            bps, ts1, ts2, sjw, tdo = BITRATE_TABLE_A[baudrateA]
            abt = CANBTP(dwMode=CAN_BTMODE_RAW, dwBPS=bps, wTS1=ts1, wTS2=ts2, wSJW=sjw, wTDO=tdo)
        else:
            abt = CANBTP(dwMode=0, dwBPS=baudrateA * 1000, wTS1=14, wTS2=2, wSJW=1, wTDO=0)

        # Data bit timing
        if baudrateD is None:
            dbt = CANBTP()
        elif baudrateD in BITRATE_TABLE_D:
            bps, ts1, ts2, sjw, tdo = BITRATE_TABLE_D[baudrateD]
            dbt = CANBTP(dwMode=CAN_BTMODE_RAW, dwBPS=bps, wTS1=ts1, wTS2=ts2, wSJW=sjw, wTDO=tdo)
        else:
            raise VciError(f"Unsupported data bitrate {baudrateD} kbit/s")

        res = self.vcidll.canControlInitialize(
            self.canCtrl[channelNo], opMode, exMode,
            sfMode, efMode,
            0, 0, byref(abt), byref(dbt),
        )
        if res != VCI_OK:
            raise VciError(f"canControlInitialize({channelNo}) failed: 0x{res:08X}")

        self.lRxMsg[channelNo] = []
        self.vcidll.canControlStart(self.canCtrl[channelNo], True)
        self.lCanStarted[channelNo] = True

    def setAccFilter(self, channelNo: int, extended: bool, mask: int, value: int) -> None:
        """Set acceptance filter on a running controller."""
        self.vcidll.canControlSetAccFilter(
            self.canCtrl[channelNo], extended, value << 1, mask << 1,
        )

    def getStatus(self, channelNo: int) -> CanLineStatus:
        sts = CanLineStatus()
        self.vcidll.canControlGetStatus(self.canCtrl[channelNo], byref(sts))
        return sts

    # ------------------------------------------------------------------
    # Send / Receive
    # ------------------------------------------------------------------

    def sendMsg(self, channelNo: int, msg: CanMsg) -> bool:
        deadline = time.monotonic() + 1.0
        res = self.vcidll.canChannelSendMessage(self.canChn[channelNo], -1, byref(msg))
        while res != VCI_OK and time.monotonic() < deadline:
            time.sleep(0.001)
            res = self.vcidll.canChannelSendMessage(self.canChn[channelNo], -1, byref(msg))
        return res == VCI_OK

    def _read_one(self, channelNo: int) -> bool:
        """Read one raw message from the VCI FIFO and sort it."""
        msg = CanMsg()
        res = self.vcidll.canChannelPeekMessage(self.canChn[channelNo], byref(msg))
        if res != VCI_OK:
            return False
        with self._lock:
            if msg.MsgInfo.type == CAN_MSGTYPE_DATA:
                self.lRxMsg[channelNo].append(copy.copy(msg))
        return True

    def _receive_task(self) -> None:
        """Background thread: read messages into per-channel lists."""
        while self.rxTaskActive:
            busy = False
            for ch, started in enumerate(self.lCanStarted):
                if started:
                    busy |= self._read_one(ch)
            if not busy:
                time.sleep(0.001)

    def readMsg(self, channelNo: int) -> Optional[CanMsg]:
        if self._rx_thread is not None:
            with self._lock:
                if self.lRxMsg[channelNo]:
                    return self.lRxMsg[channelNo].pop(0)
            return None
        else:
            # No background thread: drain FIFO inline
            while self._read_one(channelNo):
                pass
            with self._lock:
                if self.lRxMsg[channelNo]:
                    return self.lRxMsg[channelNo].pop(0)
            return None

    def rxPending(self, channelNo: int) -> int:
        """Return the number of buffered receive messages."""
        with self._lock:
            return len(self.lRxMsg[channelNo])

    # ------------------------------------------------------------------
    # Shutdown helpers
    # ------------------------------------------------------------------

    def stop_reception(self) -> None:
        if self.rxTaskActive:
            self.rxTaskActive = False
            if self._rx_thread is not None:
                self._rx_thread.join(timeout=2.0)
                self._rx_thread = None

    def closeCanChannel(self, channelNo: int) -> None:
        self.lCanStarted[channelNo] = False
        if self.canChn[channelNo] is not None:
            self.vcidll.canChannelClose(self.canChn[channelNo])
            self.canChn[channelNo] = None

    def closeCanControl(self, channelNo: int) -> None:
        if self.canCtrl[channelNo] is not None:
            self.vcidll.canControlReset(self.canCtrl[channelNo])
            self.vcidll.canControlClose(self.canCtrl[channelNo])
            self.canCtrl[channelNo] = None
