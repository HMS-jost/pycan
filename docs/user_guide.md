# Common CAN API User Guide

The Python API defines a common surface for Classic CAN, CAN FD, TCP, UDP, and
virtual test backends. Install the package with `python -m pip install .` or
`python -m pip install -e .` from the repository root.

## Core Types

```python
from pycan import (
    CanFilter,
    CanMessage,
    CanTiming,
    ControllerConfig,
    FrameFormat,
    IdentifierFormat,
    OpenConfig,
    Transport,
)
```

Important data classes:

- `OpenConfig` selects the backend endpoint.
- `ControllerConfig` describes bitrate, CAN FD, listen-only, and receive modes.
- `CanFilter` describes one receive filter.
- `CanMessage` is used for transmit and receive frames.
- `CanStatus` reports controller state, TX queue space, RX queue space, and errors.

`CanMessage.dlc` is always the payload length in bytes. It is not the encoded
CAN FD DLC value. Valid payload lengths are 0..8 bytes for Classic CAN and
0..64 bytes for CAN FD.

## Backend Initialization

### CAN@net Basic TLV UDP

```python
from pycan import CanUdp, OpenConfig, Transport

can = CanUdp()
can.open(OpenConfig(transport=Transport.UDP, address="10.41.18.123", port=19236))
```

### CAN@net NT ASCII TCP

```python
from pycan import AsciiCan, OpenConfig, Transport

can = AsciiCan(transport=Transport.TCP, device_family="nt")
can.open(OpenConfig(
    transport=Transport.TCP,
    address="10.41.18.10",
    port=19228,
    options={"device_family": "nt"},
))
```

### CAN@net Basic ASCII UDP

```python
from pycan import AsciiCan, OpenConfig, Transport

can = AsciiCan(transport=Transport.UDP, device_family="basic")
can.open(OpenConfig(
    transport=Transport.UDP,
    address="10.41.18.11",
    port=19228,
    options={"device_family": "basic"},
))
```

### Virtual Backend

```python
from pycan import OpenConfig, Transport, Virtual

can = Virtual()
can.open(OpenConfig(transport=Transport.VIRTUAL, device_id="vcan0"))
```

### IXXAT VCI Backend (Windows)

```python
from pycan import VciCan, OpenConfig, Transport

can = VciCan()
can.open(OpenConfig(transport=Transport.VCI, device_id="HW426714"))
```

The `device_id` is the IXXAT serial number printed on the interface (e.g.
`HW426714`).  CAN port count and CAN FD capability depend on the connected
hardware.

## CAN Initialization

Classic CAN at 500 kbit/s:

```python
config = ControllerConfig(arbitration=CanTiming(bitrate_kbit=500))
can.init_can(1, config)
```

CAN FD with bitrate switching:

```python
config = ControllerConfig(
    can_fd=True,
    bitrate_switch=True,
    arbitration=CanTiming(bitrate_kbit=500),
    data=CanTiming(bitrate_kbit=2000),
)
can.init_can(1, config)
```

Add accept-all filters and start CAN:

```python
can.add_filter(1, CanFilter(IdentifierFormat.STANDARD, mask=0, value=0))
can.add_filter(1, CanFilter(IdentifierFormat.EXTENDED, mask=0, value=0))
can.start_can(1)
```

## Sending

Send one standard Classic CAN frame:

```python
can.send(1, CanMessage(0x200, b"\x11\x22\x33\x44"))
```

Send one extended frame:

```python
can.send(1, CanMessage(
    0x1234567,
    b"\x11\x22\x33\x44\x55\x66\x77\x88",
    id_format=IdentifierFormat.EXTENDED,
))
```

Send one CAN FD frame:

```python
can.send(1, CanMessage(
    0x200,
    bytes(range(64)),
    frame_format=FrameFormat.FD_BRS,
))
```

Send a burst with backpressure:

```python
messages = [
    CanMessage(0x300, bytes([index & 0xFF]))
    for index in range(1000)
]
sent = can.send_many(1, messages, overall_timeout=10.0)
```

`send_many()` is the preferred API for sustained transmission. It uses reported
TX queue space and waits until the backend can accept more frames or the timeout
expires.

## Receiving

Poll once:

```python
message = can.receive(1, timeout=0)
```

Wait up to one second:

```python
message = can.receive(1, timeout=1.0)
if message is not None:
    print(message.can_id, message.data, message.timestamp_us)
```

The ASCII protocol does not transport hardware timestamps. The ASCII backend
therefore adds a client-side timestamp when a received message line is parsed.

## Callbacks And Processing

Backends are cooperative. Call `process_cycle()` periodically when using receive
callbacks:

```python
received = []
can.set_receive_callback(1, lambda port, msg: received.append((port, msg)))

while True:
    can.process_cycle()
```

Use callbacks and direct `receive()` polling as alternative receive models per
port. They consume the same receive stream, so mixing both on the same port makes
message ownership depend on whether `process_cycle()` or `receive()` reads the
next frame first.

## Status And Errors

```python
status = can.get_status(1)
print(status.status_text, status.tx_free, status.error_code)
```

Some current backends actively query the device in `get_status()`, while others
return cached state. The intended long-term split is cached `get_status()` plus a
separate active refresh operation.

Backend-specific diagnostic information is available through:

```python
code, text = can.get_last_error()
```

## Cleanup

```python
try:
    can.stop_can(1)
finally:
    can.close()
```
