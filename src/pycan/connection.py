# SPDX-License-Identifier: MIT
# Copyright (c) 2025-2026 HMS Technology Center GmbH

"""Convenience helpers for opening pycan backends from connection strings."""

from __future__ import annotations

import sys

from .ascii_can import ASCII_PORT, AsciiCan
from .can_api import CanApi, CanApiError, OpenConfig, Transport
from .canm_udp import CANM_DEFAULT_PORT, CanmUdp
from .canudp import CanUdp
from .virtual import Virtual

if sys.platform == "win32":
    try:
        from .vci_can import VciCan
    except ImportError:
        VciCan = None  # type: ignore[misc,assignment]
else:
    VciCan = None  # type: ignore[misc,assignment]

TLV_UDP_PORT = 19236


def connect(target: str, *, open_timeout: float = 2.0) -> CanApi:
    """Open a CAN backend from a compact connection string.

    Supported forms are::

        tlv-udp/<address>[/<port>]
        ascii-tcp/<address>[/<port>]
        ascii-udp/<address>[/<port>]
        canm-udp/<multicast_address>[/<port>]
        vci/<serial_number>
        virtual/<device_id>

    Network ports are optional. TLV UDP defaults to 19236, ASCII TCP/UDP to
    19228, CANM-UDP to 50009. The returned backend instance is already opened.
    """

    backend, endpoint, port = _parse_target(target)

    if backend == "tlv-udp":
        can = CanUdp(host=endpoint, port=port or TLV_UDP_PORT)
        try:
            can.open(
                OpenConfig(
                    transport=Transport.UDP,
                    address=endpoint,
                    port=port or TLV_UDP_PORT,
                ),
                timeout=open_timeout,
            )
        except Exception:
            can.close()
            raise
        return can

    if backend == "ascii-tcp":
        can = AsciiCan(
            host=endpoint,
            port=port or ASCII_PORT,
            transport=Transport.TCP,
            device_family="nt",
        )
        try:
            can.open(
                OpenConfig(
                    transport=Transport.TCP,
                    address=endpoint,
                    port=port or ASCII_PORT,
                    options={"device_family": "nt"},
                )
            )
        except Exception:
            can.close()
            raise
        return can

    if backend == "ascii-udp":
        can = AsciiCan(
            host=endpoint,
            port=port or ASCII_PORT,
            transport=Transport.UDP,
            device_family="basic",
        )
        try:
            can.open(
                OpenConfig(
                    transport=Transport.UDP,
                    address=endpoint,
                    port=port or ASCII_PORT,
                    options={"device_family": "basic"},
                )
            )
        except Exception:
            can.close()
            raise
        return can

    if backend == "vci":
        if port:
            raise CanApiError("vci connection strings do not accept a port")
        if VciCan is None:
            raise CanApiError("VCI backend is not available on this platform")
        can = VciCan()
        try:
            can.open(OpenConfig(transport=Transport.VCI, device_id=endpoint))
        except Exception:
            can.close()
            raise
        return can

    if backend == "canm-udp":
        can = CanmUdp(address=endpoint, port=port or CANM_DEFAULT_PORT)
        try:
            can.open(
                OpenConfig(
                    transport=Transport.CANM_UDP,
                    address=endpoint,
                    port=port or CANM_DEFAULT_PORT,
                )
            )
        except Exception:
            can.close()
            raise
        return can

    if backend == "virtual":
        if port:
            raise CanApiError("virtual connection strings do not accept a port")
        can = Virtual()
        try:
            can.open(OpenConfig(transport=Transport.VIRTUAL, device_id=endpoint))
        except Exception:
            can.close()
            raise
        return can

    raise CanApiError(f"unsupported backend {backend!r}")


def _parse_target(target: str) -> tuple[str, str, int]:
    parts = target.strip().split("/")
    if len(parts) not in (2, 3) or not parts[0] or not parts[1]:
        raise CanApiError(
            "connection string must use backend/endpoint or backend/endpoint/port"
        )

    backend = parts[0].lower()
    endpoint = parts[1]
    port = 0
    if len(parts) == 3:
        if not parts[2]:
            raise CanApiError("port must not be empty")
        try:
            port = int(parts[2])
        except ValueError as exc:
            raise CanApiError(f"invalid port {parts[2]!r}") from exc
        if not 1 <= port <= 65535:
            raise CanApiError(f"invalid port {port} (must be 1..65535)")

    return backend, endpoint, port
