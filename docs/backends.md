# pycan Backend Overview

Overview of the supported CAN device backends, their capabilities, and
protocol-level constraints.

---

## Backend Summary

| Property              | TLV-UDP (CAN@net Basic)         | ASCII-TCP (CAN@net NT)          | ASCII-UDP (CAN@net Basic)       |
|-----------------------|---------------------------------|---------------------------------|---------------------------------|
| **Status**            | Preliminary                     | Stable                          | Stable                          |
| **Python class**      | `CanUdp`                        | `AsciiCan`                      | `AsciiCan`                      |
| **Transport**         | UDP                             | TCP                             | UDP                             |
| **Default port**      | 19236                           | 19228                           | 19228                           |
| **Device family**     | `basic`                         | `nt`                            | `basic`                         |
| **CAN ports**         | 1                               | 1–4 (device dependent)          | 1                               |
| **CAN FD**            | Yes (port 1)                    | Device dependent (see below)    | Yes (port 1)                    |
| **Timestamps**        | Hardware (µs resolution)        | Client-side (`time.time()`)     | Client-side (`time.time()`)     |
| **Burst capability**  | `send_many()` with TX queue     | `send_many()` with TX queue     | `send_many()` with TX queue     |

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

## Timestamp Behavior

| Backend      | Source          | Resolution   | Reference                     |
|--------------|-----------------|--------------|-------------------------------|
| TLV-UDP      | Hardware        | ~1 µs        | Device-internal clock         |
| ASCII-TCP    | Client-side     | ~1 ms        | `time.time()` on receive      |
| ASCII-UDP    | Client-side     | ~1 ms        | `time.time()` on receive      |

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
