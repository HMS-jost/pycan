# TLV-UDP Protokollspezifikation

Dieses Dokument beschreibt das TLV-basierte UDP-Protokoll zur Kommunikation
mit CAN@net Basic Geräten. Es richtet sich an Entwickler, die das Protokoll
in einer anderen Programmiersprache oder auf einer anderen Plattform
implementieren möchten.

## Übersicht

Das Protokoll verwendet UDP-Datagramme mit einer einfachen TLV-Struktur
(Type-Length-Value). Der PC sendet Kommandos an das Gerät, das Gerät
antwortet mit dem gleichen Kommando-Typ. CAN-Empfangsnachrichten werden vom
Gerät unaufgefordert (unsolicited) an den PC gesendet.

**Standard-Port:** 19236 (UDP, konfigurierbar im Gerät)

## TLV-Rahmenformat

Jedes Datagramm besteht aus einem oder mehreren TLV-Frames:

| Offset | Länge | Beschreibung              |
|--------|-------|---------------------------|
| 0      | 1     | Type — Kommando-Code (0–8)|
| 1      | 2     | Length — Länge des Value-Felds in Bytes (Little-Endian) |
| 3      | n     | Value — Nutzdaten (abhängig vom Kommando) |

**Byte-Reihenfolge:** Alle Mehrbyte-Werte sind Little-Endian.

## Kommandos

### 0 — Open

Registriert die Absender-IP und den Port des PCs beim Gerät. Das Gerät
sendet danach CAN-Empfangsnachrichten (Cmd 6) an diese Adresse.

**Muss als erstes Kommando gesendet werden.**

| Richtung | Value (Request) | Value (Response)          |
|----------|-----------------|---------------------------|
| PC → Gerät | (leer, Length=0) | Null-terminierter ASCII-String mit Geräte-ID |

**Beispiel-Response:** `CAN@net Basic NT\x00`

Nach dem Open sollte einmalig ein Status-Kommando (Cmd 1) gesendet werden,
um die TX-Kapazität (`tx_free`) für die Flusskontrolle zu ermitteln.

---

### 1 — Status

Fragt den aktuellen Gerätestatus ab.

| Richtung | Value (Request) | Value (Response)           |
|----------|-----------------|----------------------------|
| PC → Gerät | (leer, Length=0) | 6 Bytes: `status(2) tx_free(2) error(2)` |

**Response-Felder (je uint16 LE):**

| Feld     | Beschreibung |
|----------|--------------|
| status   | CAN-Controller-Status (siehe Statuscodes) |
| tx_free  | Anzahl freier Plätze im TX-Puffer |
| error    | Letzter Fehlercode |

**Statuscodes:**

| Wert | Bedeutung       |
|------|-----------------|
| 0    | Init (nicht gestartet) |
| 1    | Normal (Bus aktiv) |
| 2    | Error Passive   |
| 3    | Overrun         |
| 4    | Bus Off         |

---

### 2 — Stop CAN

Stoppt den CAN-Controller auf dem angegebenen Port.

| Richtung | Value (Request) | Value (Response) |
|----------|-----------------|------------------|
| PC → Gerät | `port(1)` | `result(2)` — uint16, 0 = OK |

**Hinweis:** Muss vor `Init CAN` gesendet werden, falls der Controller
bereits läuft (andernfalls lehnt die Firmware die Neukonfiguration ab).

---

### 3 — Init CAN

Initialisiert den CAN-Controller. Setzt Betriebsmodus und Baudraten.
Löscht alle zuvor registrierten Empfangsfilter.

| Richtung | Value (Request) | Value (Response) |
|----------|-----------------|------------------|
| PC → Gerät | 7 Bytes (siehe unten) | `result(2)` — uint16, 0 = OK |

**Request-Value:**

| Offset | Länge | Feld      | Beschreibung |
|--------|-------|-----------|--------------|
| 0      | 1     | port      | CAN-Port (1) |
| 1      | 2     | mode      | Betriebsmodus-Bitmask (uint16 LE) |
| 3      | 2     | baud_a    | Arbitrations-Bitrate in kBit/s (uint16 LE) |
| 5      | 2     | baud_d    | Daten-Bitrate in kBit/s (uint16 LE, 0 bei Classic CAN) |

**Mode-Bits:**

| Bit(s) | Wert | Bedeutung |
|--------|------|-----------|
| 0      | 1    | Standard-Frames (11-Bit-ID) empfangen |
| 1      | 2    | Extended-Frames (29-Bit-ID) empfangen |
| 2      | 4    | Error-Frames empfangen |
| 3      | 8    | Listen-Only (kein Senden) |
| 5      | 32   | Automatische Baudratenerkennung |
| 6      | 64   | Remote-Frames (RTR) empfangen |
| 8–9    | 768  | ISO CAN-FD Modus aktivieren |

**Typische Kombinationen:**

| Mode-Wert | Beschreibung |
|-----------|--------------|
| 67        | Classic CAN (STD + EXT + RTR) |
| 835       | CAN FD (Classic + FD) |

**Typische Ablaufsequenz:**
1. Stop CAN (Cmd 2)
2. Init CAN (Cmd 3)
3. Filter setzen (Cmd 5) — mindestens einen
4. Start CAN (Cmd 4)

---

### 4 — Start CAN

Startet den CAN-Controller. Ab jetzt werden CAN-Nachrichten empfangen und
gesendet.

| Richtung | Value (Request) | Value (Response) |
|----------|-----------------|------------------|
| PC → Gerät | `port(1)` | `result(2)` — uint16, 0 = OK |

---

### 5 — Filter

Registriert einen Empfangsfilter. Ein Frame wird akzeptiert, wenn:

```
(frame_id & mask) == value
```

Für einen "Accept All"-Filter: `mask=0`, `value=0`.

| Richtung | Value (Request) | Value (Response) |
|----------|-----------------|------------------|
| PC → Gerät | 10 Bytes (siehe unten) | `result(2)` — uint16, 0 = OK |

**Request-Value:**

| Offset | Länge | Feld   | Beschreibung |
|--------|-------|--------|--------------|
| 0      | 1     | port   | CAN-Port |
| 1      | 1     | fmt    | Frame-Format (siehe Format-Bitmask) |
| 2      | 4     | mask   | ID-Maske (uint32 LE) |
| 6      | 4     | value  | ID-Wert (uint32 LE) |

**Beispiele:**

| Ziel | fmt | mask | value |
|------|-----|------|-------|
| Alle Standard-Frames | 0x00 | 0x00000000 | 0x00000000 |
| Alle Extended-Frames | 0x01 | 0x00000000 | 0x00000000 |
| Nur ID 0x200 (Std) | 0x00 | 0x000007FF | 0x00000200 |
| IDs 0x100–0x1FF (Std) | 0x00 | 0x00000700 | 0x00000100 |

---

### 6 — CAN Receive (Gerät → PC)

Unsolicited-Nachricht: Das Gerät sendet empfangene CAN-Frames an den
registrierten PC (nach Open). Es gibt keine Antwort vom PC.

| Richtung | Value |
|----------|-------|
| Gerät → PC | Variable Länge (mind. 10 Bytes + Daten) |

**Value-Aufbau:**

| Offset | Länge | Feld      | Beschreibung |
|--------|-------|-----------|--------------|
| 0      | 1     | port      | CAN-Port, auf dem empfangen |
| 1      | 4     | timestamp | Zeitstempel in Mikrosekunden (uint32 LE) |
| 5      | 1     | fmt       | Frame-Format-Bitmask |
| 6      | 4     | can_id    | CAN-ID (uint32 LE) |
| 10     | 0–64  | data      | Nutzdaten (0–8 Bytes Classic, 0–64 Bytes FD) |

---

### 7 — CAN Send (PC → Gerät)

Sendet eine CAN-Nachricht. **Keine Antwort vom Gerät.**

| Richtung | Value |
|----------|-------|
| PC → Gerät | Variable Länge (mind. 6 Bytes + Daten) |

**Value-Aufbau:**

| Offset | Länge | Feld   | Beschreibung |
|--------|-------|--------|--------------|
| 0      | 1     | port   | CAN-Port |
| 1      | 1     | fmt    | Frame-Format-Bitmask |
| 2      | 4     | can_id | CAN-ID (uint32 LE) |
| 6      | 0–64  | data   | Nutzdaten |

**Flusskontrolle:** Vor dem Senden vieler Nachrichten sollte der PC per
Status-Kommando (Cmd 1) das Feld `tx_free` abfragen und nicht mehr
Nachrichten senden, als Plätze im TX-Puffer frei sind. Typischerweise hat
der Puffer 50 Einträge.

---

### 8 — Close

Beendet die Verbindung. Das Gerät sendet danach keine CAN-Empfangsnachrichten
mehr an den PC. **Keine Antwort vom Gerät.**

| Richtung | Value (Request) |
|----------|-----------------|
| PC → Gerät | (leer, Length=0) |

---

## Frame-Format-Bitmask (fmt)

Die `fmt`-Flags beschreiben den Typ eines CAN-Frames:

| Bit | Wert | Bedeutung |
|-----|------|-----------|
| 0   | 0x01 | Extended Frame (29-Bit-ID) |
| 1   | 0x02 | Remote Transmission Request (RTR) |
| 4   | 0x10 | CAN FD Frame |
| 5   | 0x20 | CAN FD Bit Rate Switch (BRS) |
| 6   | 0x40 | CAN FD Error State Indicator (ESI) |

Wenn kein Bit gesetzt ist (0x00), handelt es sich um einen Standard-Frame
(11-Bit-ID, Classic CAN, Daten-Frame).

**Typische Kombinationen:**

| fmt  | Beschreibung |
|------|--------------|
| 0x00 | Standard CAN, Data Frame |
| 0x01 | Extended CAN, Data Frame |
| 0x02 | Standard CAN, Remote Frame |
| 0x10 | CAN FD, Standard-ID, ohne BRS |
| 0x30 | CAN FD, Standard-ID, mit BRS |
| 0x11 | CAN FD, Extended-ID, ohne BRS |
| 0x31 | CAN FD, Extended-ID, mit BRS |

## Typischer Ablauf

```text
PC                              Gerät
 |                                |
 |--- Open (Cmd 0) ------------->|
 |<-- Response: "CAN@net..." ----|
 |                                |
 |--- Status (Cmd 1) ----------->|
 |<-- Response: sts/tx_free/err -|
 |                                |
 |--- Stop CAN (Cmd 2, port=1) ->|
 |<-- Response: 0 (OK) ----------|
 |                                |
 |--- Init CAN (Cmd 3) --------->|
 |    port=1, mode=67, 500kBit   |
 |<-- Response: 0 (OK) ----------|
 |                                |
 |--- Filter (Cmd 5) ----------->|
 |    port=1, fmt=0, mask=0, v=0 |
 |<-- Response: 0 (OK) ----------|
 |                                |
 |--- Start CAN (Cmd 4, port=1)->|
 |<-- Response: 0 (OK) ----------|
 |                                |
 |--- CAN Send (Cmd 7) --------->|
 |    (keine Antwort)            |
 |                                |
 |<-- CAN Recv (Cmd 6) ----------|  (unsolicited)
 |<-- CAN Recv (Cmd 6) ----------|
 |                                |
 |--- Close (Cmd 8) ------------>|
 |    (keine Antwort)            |
```

## Hinweise zur Implementierung

1. **UDP ist verbindungslos** — es gibt keine Session im klassischen Sinn.
   Das Open-Kommando registriert lediglich IP:Port beim Gerät.

2. **Empfang während Kommandos** — Zwischen dem Senden eines Kommandos und
   dem Empfang der Antwort können CAN-Recv-Frames (Cmd 6) eintreffen. Diese
   müssen gepuffert werden, bis die Antwort auf das gesendete Kommando
   ankommt (gleicher Kommando-Typ in der Response).

3. **Timeout** — Antworten kommen typischerweise innerhalb von 50 ms. Ein
   Timeout von 2 Sekunden ist ein sicherer Standardwert.

4. **Keine Fragmentierung** — Jedes UDP-Datagramm enthält genau ein
   TLV-Frame. Die maximale Paketgröße beträgt ca. 80 Bytes (CAN FD mit 64
   Datenbytes + Header).

5. **Fehlercodes** — Alle Kommandos mit Response liefern ein uint16-Result.
   Der Wert 0 bedeutet Erfolg, jeder andere Wert ist ein Fehler.

6. **Reihenfolge** — Die Kommandos müssen in der Reihenfolge Open → Stop →
   Init → Filter → Start ausgeführt werden. Send/Receive ist erst nach
   Start möglich.
