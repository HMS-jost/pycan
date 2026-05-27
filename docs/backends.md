# pycan Backend Overview

Overview of the supported CAN device backends, their capabilities, and
protocol-level constraints.

---

## Backend Summary

| Property              | TLV-UDP (CAN@net Basic)         | ASCII-TCP (CAN@net NT)          | ASCII-UDP (CAN@net Basic)       | CANM-UDP (Multicast Bridge)     | VCI (IXXAT)                     |
|-----------------------|---------------------------------|---------------------------------|---------------------------------|---------------------------------|---------------------------------|
| **Status**            | Preliminary                     | Stable                          | Stable                          | Stable                          | Stable                          |
| **Python class**      | `CanUdp`                        | `AsciiCan`                      | `AsciiCan`                      | `CanmUdp`                       | `VciCan`                        |
| **Transport**         | UDP                             | TCP                             | UDP                             | UDP Multicast                   | Native DLL (vcinpl2.dll)        |
| **Default port**      | 19236                           | 19228                           | 19228                           | 50009                           | —                               |
| **Device family**     | `basic`                         | `nt`                            | `basic`                         | `basic` (multicast)             | —                               |
| **CAN ports**         | 1                               | 1–4 (device dependent)          | 1                               | 1 (logical)                     | 1–4 (interface dependent)       |
| **CAN FD**            | Yes (port 1)                    | Device dependent (see below)    | Yes (port 1)                    | Yes                             | Interface dependent             |
| **Timestamps**        | Hardware (µs resolution)        | Client-side (`time.time()`)     | Client-side (`time.time()`)     | Client-side (`time.time()`)     | Hardware (VCI timer ticks)      |
| **Burst capability**  | `send_many()` with TX queue     | `send_many()` with TX queue     | `send_many()` with TX queue     | `send_many()` sequential        | `send_many()` direct send       |
| **Platform**          | Windows, Linux                  | Windows, Linux                  | Windows, Linux                  | Windows, Linux                  | Windows only                    |

---

## CAN@net Basic (TLV-UDP and ASCII-UDP)

- **Hardware:** CAN@net Basic (1 CAN port, MCAN controller)
- **CAN FD:** Yes, ISO CAN FD with BRS
- **TLV-UDP protocol:** Binary TLV format, port 19236. Hardware timestamps in µs.
- **ASCII-UDP protocol:** Text-based, port 19228. No hardware timestamps; client-side timestamping.
- **TLV-UDP status:** Preliminary — protocol may still change.
- **ASCII-UDP status:** Stable, identical to the NT ASCII protocol.

### Bitrates (Arbitration, Classic CAN)

50, 100, 125, 250, 500, 800, 1000 kbit/s

### Bitrates (Arbitration, CAN FD mode)

250, 500, 800, 1000 kbit/s

### Bitrates (Data Phase, CAN FD)

500, 1000, 2000, 4000, 5000, 8000 kbit/s

Additionally: User-defined via register values (`CanTiming.use_register_values = True`).

---

## CAN@net NT (ASCII-TCP)

- **Hardware:** CAN@net NT 100, NT 200, NT 420
- **Protocol:** Text-based (ASCII), TCP port 19228
- **Timestamps:** No hardware timestamps. The client adds `time.time()` in µs when parsing the received message line.
- **Status:** Stable.

### Device Variants

| Device           | CAN Ports | CAN FD Ports       | Notes                        |
|------------------|-----------|--------------------|------------------------------|
| CAN@net NT 100   | 1         | —                  | No CAN FD                    |
| CAN@net NT 200   | 2         | —                  | No CAN FD                    |
| CAN@net NT 420   | 4         | Port 3, Port 4     | Ports 1+2 Classic CAN only   |

### Bitrates (Arbitration, Classic CAN)

5, 10, 20, 50, 62.5, 83.3, 100, 125, 250, 500, 800, 1000 kbit/s

Additionally: Automatic baud-rate detection, no baud-rate (port disabled).

### Bitrates (Arbitration, CAN FD mode)

50, 125, 250, 500, 800, 1000 kbit/s

### Bitrates (Data Phase, CAN FD)

500, 1000, 2000, 4000, 5000, 8000 kbit/s

Additionally: User-defined via register values.

---

## IXXAT VCI (Windows)

- **Hardware:** Any IXXAT CAN interface supported by VCI V4 (USB, Ethernet, PCIe)
- **DLL:** `vcinpl2.dll` (installed with the IXXAT VCI V4 driver package)
- **CAN FD:** Depends on the connected interface hardware
- **CAN ports:** Depends on the connected interface (typically 1–4)
- **Timestamps:** Hardware timer ticks from the VCI driver
- **Platform:** Windows only

The number of CAN ports and CAN FD capability depend entirely on the physical
IXXAT interface connected.  For example, a CAN@net NT 420 accessed via VCI
provides 4 ports with CAN FD on ports 3 and 4, while a USB-to-CAN V2 provides
2 Classic-CAN-only ports.

### Bitrates (Arbitration)

Preset table: 125, 250, 500, 1000 kbit/s (raw register values).
Other bitrates: passed directly to the VCI driver as `dwBPS` in bit/s.

### Bitrates (Data Phase, CAN FD)

Preset table: 500, 1000, 2000, 4000, 5000, 8000 kbit/s (raw register values).

### Receive Filtering

VCI hardware acceptance filters are not supported reliably on all IXXAT
interfaces.  The `VciCan` backend therefore implements **software filtering**:
the controller always accepts all frames (`CAN_FILTER_PASS`) and incoming
messages are matched against the configured filters in `receive()` and
`process_cycle()`.

Up to **5 filters per port** can be configured via `add_filter()`.  A frame is
accepted if it matches at least one filter:

```
accepted = (can_id & mask) == (value & mask)  and  id_format matches
```

If no filters are configured, all frames pass through (accept-all).

---

## CAN@net CANM Multicast Bridge (CANM-UDP)

- **Protocol:** CANM binary format over UDP multicast
- **Default multicast group:** 225.0.0.250
- **Default port:** 50009
- **CAN FD:** Yes (Classic CAN and CAN FD frames)
- **Timestamps:** Client-side (`time.time()`) when parsing received datagrams
- **Status:** Stable

The CANM protocol is used by CAN@net Basic devices to exchange CAN frames over
a UDP multicast backbone. Up to 64 devices can participate in the same multicast
group. The PC joins the group and acts as a virtual participant — sending and
receiving CAN frames alongside the embedded devices.

### Key Differences from Other Backends

- **No CAN controller management:** `init_can()`, `start_can()`, and `stop_can()`
  are not supported (raise `CanApiError`). The multicast bus is always active.
- **Multiple frames per datagram:** A single UDP packet may contain multiple
  CAN frames, each with a 16-byte CANM header + 12-byte CAN header.
- **Software filtering:** Receive filters are applied in software, identical to
  the VCI backend pattern.
- **Background listener thread:** Incoming multicast packets are received and
  parsed in a daemon thread; `receive()` reads from an internal queue.

### Connection String

```
canm-udp/225.0.0.250        (default port 50009)
canm-udp/225.0.0.250/50009  (explicit port)
```

### Usage Example

```python
from pycan import connect, CanFilter, IdentifierFormat, CanMessage

can = connect("canm-udp/225.0.0.250")
can.add_filter(1, CanFilter(IdentifierFormat.STANDARD, mask=0, value=0))
can.send(1, CanMessage(0x123, b"\x01\x02\x03\x04"))
msg = can.receive(1, timeout=1.0)
can.close()
```

---

## Timestamp Behavior

| Backend      | Source          | Resolution   | Reference                     |
|--------------|-----------------|--------------|-------------------------------|
| TLV-UDP      | Hardware        | ~1 µs        | Device-internal clock         |
| ASCII-TCP    | Client-side     | ~1 ms        | `time.time()` on receive      |
| ASCII-UDP    | Client-side     | ~1 ms        | `time.time()` on receive      |
| CANM-UDP     | Client-side     | ~1 ms        | `time.time()` on receive      |
| VCI          | Hardware        | VCI ticks    | Interface-internal timer      |

**Note:** The BusMonitor displays relative timestamps (from the first received
frame). For ASCII backends, accuracy is limited by network latency and Python
scheduling (~1–5 ms).

---

## Register-based Bitrate Configuration

All backends support user-defined timing parameters via
`CanTiming(use_register_values=True, brp=..., sjw=..., tseg1=..., tseg2=..., tdo=...)`.

**CAN@net Basic (MCAN controller, 80 MHz clock):**

| Parameter | Classic CAN     | CAN FD Data Phase |
|-----------|-----------------|-------------------|
| BRP       | 1–512           | 1–32              |
| TSEG1     | 1–256           | 1–16              |
| TSEG2     | 1–128           | 1–16              |
| SJW       | 1–128           | 1–16              |
| TDO       | —               | 0–127             |

**CAN@net NT (LPC 36 MHz / IFI 80 MHz):**

| Parameter | Classic CAN (Port 1,2) | CAN FD (Port 3,4) Arbitration | CAN FD Data Phase |
|-----------|------------------------|-------------------------------|-------------------|
| BRP       | 1–1024                 | 1–512                         | 1–32              |
| TSEG1     | 1–256                  | 1–256                         | 1–16              |
| TSEG2     | 1–128                  | 1–128                         | 1–16              |
| SJW       | 1–128                  | 1–128                         | 1–16              |
| TDO       | —                      | —                             | 0–127             |

Bitrate formula: `bitrate = clock / ((TSEG1 + TSEG2 + 1) × BRP)`
