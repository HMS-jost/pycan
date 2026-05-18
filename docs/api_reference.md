# pycan API Reference

Complete reference for all public classes, enums, and methods defined in
`pycan.can_api`.

---

## Enums

### `Transport`

Connection transport used to reach a CAN device.

| Value      | Description                        |
|------------|------------------------------------|
| `ANY`      | No preference; let backend decide  |
| `VIRTUAL`  | In-memory (test/demo)              |
| `USB`      | USB connection                     |
| `SERIAL`   | Serial / COM port                  |
| `TCP`      | TCP socket                         |
| `UDP`      | UDP socket                         |
| `VCI`      | VCI-style driver (Windows)         |

### `BusState`

CAN controller states (IntEnum).

| Value           | Int | Description                              |
|-----------------|-----|------------------------------------------|
| `UNKNOWN`       | 0   | State not (yet) known                    |
| `INIT`          | 1   | Controller initialized, not started      |
| `RUNNING`       | 2   | Bus active, no errors                    |
| `ERROR_WARNING` | 3   | Error warning level reached              |
| `ERROR_PASSIVE` | 4   | Error passive state                      |
| `OVERRUN`       | 5   | Data overrun (frame lost)                |
| `BUS_OFF`       | 6   | Bus-off state                            |

### `FrameFormat`

Physical CAN frame family.

| Value        | Description                      |
|--------------|----------------------------------|
| `CLASSIC`    | Classic CAN (up to 8 bytes)      |
| `FD_NO_BRS`  | CAN FD without bit rate switch   |
| `FD_BRS`     | CAN FD with bit rate switch      |

### `IdentifierFormat`

CAN identifier width.

| Value      | Description              |
|------------|--------------------------|
| `STANDARD` | 11-bit identifier        |
| `EXTENDED` | 29-bit identifier        |

### `FrameType`

CAN frame content type.

| Value    | Description                    |
|----------|--------------------------------|
| `DATA`   | Data frame                     |
| `REMOTE` | Remote transmission request    |
| `ERROR`  | Error frame                    |

---

## Data Classes

### `DeviceInfo`

Information used to select or describe a CAN device.

| Field                  | Type        | Default          | Description                          |
|------------------------|-------------|------------------|--------------------------------------|
| `device_id`            | `str`       | `""`             | Stable ID for `open()`               |
| `name`                 | `str`       | `""`             | Human-readable product name          |
| `transport`            | `Transport` | `Transport.ANY`  | Transport used by this device        |
| `channel_count`        | `int`       | `0`              | Number of CAN ports                  |
| `supports_can_fd`      | `bool`      | `False`          | CAN FD capable                       |
| `supports_listen_only` | `bool`      | `False`          | Listen-only mode available           |
| `firmware_version`     | `str`       | `""`             | Firmware version string              |
| `hardware_version`     | `str`       | `""`             | Hardware version string              |

### `OpenConfig`

Connection parameters for `open()`.

| Field        | Type                   | Default         | Description                              |
|--------------|------------------------|-----------------|------------------------------------------|
| `transport`  | `Transport`            | `Transport.ANY` | Preferred transport                      |
| `device_id`  | `str`                  | `""`            | Device identifier from `get_device_list` |
| `address`    | `str`                  | `""`            | IP address, COM port, etc.               |
| `port`       | `int`                  | `0`             | Network or service port                  |
| `options`    | `dict[str, object]`    | `{}`            | Backend-specific options                 |

### `CanTiming`

CAN bitrate or explicit timing-register configuration.

| Field                | Type   | Default | Description                               |
|----------------------|--------|---------|-------------------------------------------|
| `bitrate_kbit`       | `int`  | `500`   | Bitrate in kbit/s (preset mode)           |
| `brp`                | `int`  | `0`     | Baud rate prescaler (register mode)       |
| `sjw`                | `int`  | `0`     | Synchronization jump width                |
| `tseg1`              | `int`  | `0`     | Time segment 1                            |
| `tseg2`              | `int`  | `0`     | Time segment 2                            |
| `tdo`                | `int`  | `0`     | Transmitter delay offset                  |
| `use_register_values`| `bool` | `False` | Use register values instead of preset     |

### `ControllerConfig`

CAN controller configuration for `init_can()`.

| Field              | Type                | Default                          | Description                         |
|--------------------|---------------------|----------------------------------|-------------------------------------|
| `can_fd`           | `bool`              | `False`                          | Enable CAN FD mode                  |
| `bitrate_switch`   | `bool`              | `False`                          | Enable CAN FD bitrate switching     |
| `listen_only`      | `bool`              | `False`                          | Passive mode (no ACK, no TX)        |
| `iso_mode`         | `bool`              | `True`                           | ISO CAN FD                          |
| `receive_standard` | `bool`              | `True`                           | Accept 11-bit IDs                   |
| `receive_extended` | `bool`              | `True`                           | Accept 29-bit IDs                   |
| `receive_remote`   | `bool`              | `True`                           | Accept remote frames                |
| `arbitration`      | `CanTiming`         | `CanTiming()`                    | Arbitration phase timing            |
| `data`             | `CanTiming`         | `CanTiming(bitrate_kbit=0)`      | Data phase timing (FD)              |
| `options`          | `dict[str, object]` | `{}`                             | Backend-specific options            |

### `CanFilter`

Receive filter definition. A message is accepted when
`(message_id & mask) == value` and the identifier format matches.

| Field       | Type               | Default                        | Description                   |
|-------------|--------------------|--------------------------------|-------------------------------|
| `id_format` | `IdentifierFormat`  | `IdentifierFormat.STANDARD`   | Filter applies to this format |
| `frame_type`| `FrameType`         | `FrameType.DATA`              | Filter applies to this type   |
| `mask`      | `int`               | `0`                           | Bit mask (0 = accept all)     |
| `value`     | `int`               | `0`                           | Match value                   |
| `options`   | `dict[str, object]` | `{}`                          | Backend-specific options      |

### `CanMessage`

CAN message used for sending and receiving.

| Field          | Type               | Default                       | Description                          |
|----------------|--------------------|-------------------------------|--------------------------------------|
| `can_id`       | `int`              | *(required)*                  | 11-bit or 29-bit CAN identifier      |
| `data`         | `bytes`            | `b""`                         | Payload (0–8 Classic, 0–64 FD)       |
| `id_format`    | `IdentifierFormat` | `IdentifierFormat.STANDARD`   | Standard or extended                 |
| `frame_format` | `FrameFormat`      | `FrameFormat.CLASSIC`         | Classic / FD_NO_BRS / FD_BRS         |
| `frame_type`   | `FrameType`        | `FrameType.DATA`              | Data / Remote / Error                |
| `timestamp_us` | `int`              | `0`                           | Receive timestamp in µs              |
| `port`         | `int`              | `1`                           | CAN port number                      |
| `flags`        | `int`              | `0`                           | Backend-specific flags               |

**Properties:**

| Property     | Returns | Description                              |
|--------------|---------|------------------------------------------|
| `dlc`        | `int`   | Payload length in bytes                  |
| `is_extended`| `bool`  | True if 29-bit identifier                |
| `is_rtr`     | `bool`  | True if remote transmission request      |
| `is_fd`      | `bool`  | True if CAN FD frame                     |
| `format_str` | `str`   | Three-letter format (e.g. `CSD`, `FED`)  |

### `CanStatus`

CAN controller status returned by `get_status()`.

| Field        | Type       | Default            | Description                        |
|--------------|------------|--------------------|------------------------------------|
| `state`      | `BusState` | `BusState.UNKNOWN` | Current bus state                  |
| `tx_free`    | `int`      | `0`                | Free TX queue entries              |
| `rx_pending` | `int`      | `0`                | Queued receive messages            |
| `error_code` | `int`      | `0`                | Backend-specific error code        |
| `text`       | `str`      | `""`               | Human-readable status text         |
| `flags`      | `int`      | `0`                | Backend-specific status flags      |

**Properties:**

| Property      | Returns | Description                              |
|---------------|---------|------------------------------------------|
| `status_text` | `str`   | Readable status (text or state name)     |
| `is_ok`       | `bool`  | True when state is `RUNNING`             |

---

## Abstract Base Class: `CanApi`

All backend implementations inherit from `CanApi`. The table below lists
all abstract methods that each backend must implement.

### `get_device_list(transport=Transport.ANY) → list[DeviceInfo]`

Return available CAN devices. The returned `device_id` values can be passed
to `open()`.

### `open(config=None) → DeviceInfo`

Open a CAN device or network endpoint.

- `config`: `OpenConfig`, a `device_id` string, or `None` for default.
- Returns: `DeviceInfo` for the opened device.
- Raises: `CanApiError` on failure.

### `close() → None`

Close the connection and release all resources.

### `identify() → DeviceInfo`

Read identification and capability information from the open device.

### `init_can(port, config) → None`

Initialize a CAN controller without starting bus traffic. Implicitly clears all
receive filters for the given port — add new filters with `add_filter()` before
calling `start_can()`.

- `port`: CAN port number (1-based).
- `config`: `ControllerConfig` with bitrate, FD mode, filters, etc.

### `add_filter(port, can_filter) → None`

Add one receive filter to a CAN controller.

- `port`: CAN port number.
- `can_filter`: `CanFilter` instance.

### `start_can(port) → None`

Start a previously initialized CAN controller. After this call, TX and RX
operations are enabled.

### `stop_can(port) → None`

Stop a CAN controller. Check `get_status().tx_free` before stopping if
pending transmissions must complete.

### `send(port, message) → None`

Send one CAN message.

- `port`: CAN port number.
- `message`: `CanMessage` instance.

### `send_many(port, messages, poll_interval=0.001, overall_timeout=None) → int`

Send multiple messages respecting TX queue backpressure. This is a default
implementation that polls `get_status().tx_free`; backends may override it.

- `port`: CAN port number.
- `messages`: Sequence of `CanMessage`.
- `poll_interval`: Sleep interval when TX queue is full (seconds).
- `overall_timeout`: Maximum total time (seconds), or `None` for unlimited.
- Returns: Number of messages sent.
- Raises: `TimeoutError` if timeout expires before all messages are sent.

### `receive(port, timeout=1.0) → CanMessage | None`

Receive one CAN message.

- `port`: CAN port number.
- `timeout`: Seconds to wait. `0` = poll once. `None` = wait forever.
- Returns: `CanMessage` or `None` if no message available within timeout.

### `set_receive_callback(port, callback) → None`

Register or remove a receive callback.

- `port`: CAN port number.
- `callback`: `Callable[[int, CanMessage], None]` or `None` to disable.

Do not mix callbacks and `receive()` on the same port — both consume the
same stream.

### `process_cycle() → None`

Run backend-specific background processing once (parse packets, dispatch
callbacks, send heartbeats). Implementations with worker threads may do
nothing.

### `get_status(port) → CanStatus`

Return CAN controller status including bus state, TX/RX queue counts, and
error information.

### `get_last_error() → tuple[int, str]`

Return backend-specific diagnostic information as `(error_code, text)`.

---

## Exceptions

### `CanApiError`

Base exception raised by all CAN API implementations on operational errors.

---

## Context Manager

`CanApi` supports the `with` statement:

```python
with CanUdp() as can:
    can.open(OpenConfig(...))
    # ... use can ...
# can.close() is called automatically
```
