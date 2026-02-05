# eTag / eLabel BLE Protocol — Definitive Reference (V2)

**Primary Target:** ET0290 (2.9-inch E-Ink, 296 x 128, Black/White/Red)

---

## 1. Bluetooth LE Specifications

| UUID | Purpose |
|------|---------|
| `00001523-1212-efde-1523-785feabcd123` | Service |
| `00001525-1212-efde-1523-785feabcd123` | Write Characteristic |
| `00001526-1212-efde-1523-785feabcd123` | Notify Characteristic |
| `00002902-0000-1000-8000-00805f9b34fb` | CCCD Descriptor (standard BLE) |

No other custom services or characteristics are used.

---

## 2. Connection Flow

| Step | Action | Timing |
|------|--------|--------|
| 1 | **Connect** to BLE device (`connectGatt` with `TRANSPORT_LE`) | Connection timeout: **20 s** |
| 2 | **Discover services** (automatic on connect) | — |
| 3 | **Enable notifications** on 0x1526 (write `ENABLE_NOTIFICATION_VALUE` to CCCD 0x2902) | **300 ms** sleep after descriptor write |
| 4 | **Send Header Packet** (Write With Response to 0x1525) | — |
| 5 | **Wait** | **500 ms** before first data packet |
| 6 | **Send Data Packets** sequentially (Write With Response) | **20 ms** between packets; extra **3 ms** every 5th packet |
| 7 | **Wait for tag notification** (battery/temperature response) | Feedback timeout: **30 s** |

On failure, retry the entire transfer up to **2 times** (3 total attempts).

---

## 3. Command Types

There are **three** distinct commands. Each uses the same 20-byte header / 204-byte data packet structure but with different field values.

| Field | Image Update | Query/Ping | Text/Config |
|-------|-------------|------------|-------------|
| Command (byte 1) | `0xFC` | `0xF0` | `0xF2` |
| Identifier (bytes 2–8) | `easyTag` | `easyTag` | `eTag-CO` |
| Type ID (byte 9) | `0x62` | `0x5C` | `0x5C` |
| Marker (bytes 16–17) | `B` `T` (0x42, 0x54) | `B` `T` (0x42, 0x54) | `D` `E` (0x44, 0x45) |
| Magic Byte | `0x31` | `0x63` | `0x63` |
| Payload | RLE-compressed image | Single `0x01` byte | 256-char hex key string |
| Task Type Code | 0 | 10 (0x0A) | 1 |

**Task Type 2** also exists: sends a pre-built list of raw hex packets directly (no encoding).

---

## 4. Encryption (XOR)

### 4.1 Key Derivation

```
MacXor = MAC[0] ^ MAC[1] ^ MAC[2] ^ MAC[3] ^ MAC[4] ^ MAC[5]
Key    = MacXor ^ MagicByte
```

The Magic Byte is derived from the table and is context dependent:


| Context | Char | Magic Byte |
|---------|------|------------|
| Image Update | `'1'` | `0x31` |
| Query/Ping |  `'c'` | `0x63` |
| Text/Config | `'c'` | `0x63` |
| Notification Decryption | `'b'` | `0x62` |

**Example (Image Update):**
MAC `3D:00:00:E5:7D:76` → MacXor = `0x3D ^ 0x00 ^ 0x00 ^ 0xE5 ^ 0x7D ^ 0x76` = `0xD3`
Key = `0xD3 ^ 0x31` = **`0xE2`**

### 4.2 Encryption Scope

The implementation applies two sequential XOR passes (`byte ^= MacXor; byte ^= MagicByte`), which is mathematically equivalent to a single `byte ^= Key`.

**Header Packets (all commands):** Bytes 0–19 are XORed, **except byte 9 (Type ID) which is NEVER encrypted**.

**Data Packets (all commands):** All 204 bytes are XORed.

**Notification Responses:** All 20 bytes are XORed (no byte-9 skip). Uses magic byte `0x62`.

---

## 5. CRC-16

**Polynomial:** `0x8005` (CRC-16/ARC/IBM)
**Initial Value:** `0xFFFF`
**Algorithm:** Nibble-at-a-time (4-bit) lookup, two passes per byte.

### Lookup Table (16 entries)

```
[0x0000, 0x8005, 0x800F, 0x000A, 0x801B, 0x001E, 0x0014, 0x8011,
 0x8033, 0x0036, 0x003C, 0x8039, 0x0028, 0x802D, 0x8027, 0x0022]
```

### Pseudocode

```
function crc16(data, length):
    crc = 0xFFFF
    for each byte in data:
        for 2 iterations:
            shifted = (crc << 4) & 0xFFFF
            index   = ((crc >> 8) ^ byte) >> 4) & 0x0F
            crc     = shifted ^ TABLE[index]
            byte    = (byte << 4) & 0xFF
    return crc
```

---

## 6. Packet Structures

### 6A. Header Packet (20 Bytes)

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0 | 1 | `0xFF` | Packet Start |
| 1 | 1 | *varies* | Command Byte (`0xFC` / `0xF0` / `0xF2`) |
| 2–8 | 7 | *varies* | ASCII Identifier (`easyTag` or `eTag-CO`) |
| 9 | 1 | *varies* | Type ID — **NOT encrypted** (`0x62` or `0x5C`) |
| 10–13 | 4 | Length | Total payload byte count (Big Endian) |
| 14–15 | 2 | Count | Number of data packets: `ceil(Length / 200)` (Big Endian) |
| 16 | 1 | *varies* | Marker 1 (`0x42` 'B' or `0x44` 'D') |
| 17 | 1 | *varies* | Marker 2 (`0x54` 'T' or `0x45` 'E') |
| 18–19 | 2 | CRC-16 | Checksum of bytes 0–17 (Big Endian) |

After CRC computation, the entire header is XOR-encrypted (skipping byte 9).

### 6B. Data Packet (204 Bytes)

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0–1 | 2 | Seq | Sequence number (Big Endian). **Starts at 1.** |
| 2–201 | 200 | Data | Payload chunk (zero-padded if final packet is short) |
| 202–203 | 2 | CRC-16 | Checksum of bytes 0–201 (Big Endian) |

After CRC computation, all 204 bytes are XOR-encrypted.

---

## 7. Image Payload Format

The payload is a hex-ASCII string converted to bytes. It consists of one or two bitplane sections depending on display mode.

### 7.1 Bitplane Color Mapping

| Plane | Value 0 | Value 1 |
|-------|---------|---------|
| **Black/White** | White (no ink) | Black (ink) |
| **Red** | No red ink | Red ink |

Pixels are processed **row-major** (for each Y from 0, for each X from 0). Both width and height are rounded up to multiples of 8 internally.

### 7.2 Encoding Selection

The implements multiple encoding methods and pick whichever produces a shorter payload:

1. **`FC` / `FC8` format** — RLE-compressed (Section 7.3 + 7.4)
2. **`FE` / `03` format** — Uncompressed, raw 8-pixel-per-byte hex encoding (Section 7.5)

### 7.3 RLE Payload Headers

Both headers are exactly **26 hex characters** (13 bytes) before the data.

**Black/White Header (`FC`)**

```
FC  XXXX  YYYY  yyyy  xxxx  LLLLLLLL  [compressed data]
```

| Field | Width | Description |
|-------|-------|-------------|
| `FC` | 2 chars | BW command prefix |
| X0 | 4 chars | Start X pixel (e.g. `0000`) |
| Y0 | 4 chars | Start Y pixel (e.g. `0000`) |
| Y1 | 4 chars | End Y pixel (e.g. `007F` for 127) |
| X1 | 4 chars | End X pixel (e.g. `0127` for 295) |
| Length | 8 chars | Byte count of following compressed data |

**Red Header (`FC8`)**

```
FC8  XXX  YYYY  8  yyy  xxxx  LLLLLLLL  [compressed data]
```

| Field | Width | Description |
|-------|-------|-------------|
| `FC8` | 3 chars | Red command prefix |
| X0 | 3 chars | Start X pixel (e.g. `000`) |
| Y0 | 4 chars | Start Y pixel (e.g. `0000`) |
| `8` | 1 char | Literal separator |
| Y1 | 3 chars | End Y pixel (e.g. `07F` for 127) |
| X1 | 4 chars | End X pixel (e.g. `0127` for 295) |
| Length | 8 chars | Byte count of following compressed data |

The different field widths in the Red header (`FC8` = 3 chars, X0 = 3 chars, Y1 = 3 chars, separator `8` = 1 char) are designed so both headers total exactly 26 hex characters.

**Full RLE Payload (Black/White/Red mode):**

```
[BW Header + BW Data][Red Header + Red Data] → convert hex string to bytes
```

### 7.4 RLE Compression

A custom Run-Length Encoding scheme. Input is a flat 1D pixel array (row-major). Runs cross row boundaries freely. Maximum run length: 65,535.

#### Encoding Rules

| Mode | Condition | Bytes | Format |
|------|-----------|-------|--------|
| **Literal** | run < 7 | 1 | `1 P0 P1 P2 P3 P4 P5 P6` |
| **Short Repeat** | 7 ≤ run ≤ 31 | 1 | `0 C LLLLL` |
| **Medium Repeat** | 32 ≤ run ≤ 255 | 2 | Byte 1: `0 C 000001`, Byte 2: `Length` |
| **Long Repeat** | 256 ≤ run ≤ 65535 | 3 | Byte 1: `0 C 000000`, Byte 2: `Length Low`, Byte 3: `Length High` |

Where `C` = color bit (0 or 1), `P0`–`P6` = individual pixel values, `L` = length bits.

#### Literal Mode Detail

Packs exactly **7 pixel positions** into a single byte. If fewer than 7 pixels remain, trailing positions are zero-padded.

```
Bit 7: 1 (literal marker — distinguishes from repeat modes)
Bit 6: pixel[0]
Bit 5: pixel[1]
Bit 4: pixel[2]
Bit 3: pixel[3]
Bit 2: pixel[4]
Bit 1: pixel[5]
Bit 0: pixel[6]
```

`byte = 0x80 | (P0 << 6) | (P1 << 5) | (P2 << 4) | (P3 << 3) | (P4 << 2) | (P5 << 1) | P6`

#### Short Repeat Detail

Single byte: `(Color << 6) | RunLength`

Since RunLength is 7–31, the lower 6 bits are always ≥ 2, distinguishing this from medium/long repeat.

#### Medium Repeat Detail

```
Byte 1: (Color << 6) | 0x01    ← lower 6 bits = exactly 1
Byte 2: RunLength (8-bit)
```

#### Long Repeat Detail

```
Byte 1: (Color << 6) | 0x00    ← lower 6 bits = exactly 0
Byte 2: RunLength & 0xFF       ← low byte (little-endian)
Byte 3: (RunLength >> 8) & 0xFF ← high byte
```

#### Decoding Decision Tree

```
Read byte B:
  If B & 0x80:
    LITERAL → 7 pixels from bits 6..0 (MSB = pixel[0])
  Else:
    color = (B >> 6) & 1
    field = B & 0x3F
    If field >= 2:  SHORT REPEAT  → emit field pixels of color
    If field == 1:  MEDIUM REPEAT → read 1 byte as length
    If field == 0:  LONG REPEAT   → read 2 bytes as length (little-endian)
```

### 7.5 Uncompressed Format (`FE` / `03`)

An alternative encoding where 8 pixels are packed per byte (MSB first), rendered as 2-char hex.

**Black/White Only:**

```
FE  XXXX  YYYY  yyyy  xxxx  [raw hex data]
```

**Black/White/Red:**

```
FE  XXXX  YYYY  yyyy  xxxx  [BW hex data]  03  XXXX  YYYY  yyyy  xxxx  [Red hex data]
```

All coordinate fields are 4 hex chars. Compare the total length of RLE (`FC`/`FC8`) vs uncompressed (`FE`/`03`) and **use whichever is shorter**.

---

## 8. Command Details

### 8A. Image Update (Command `0xFC`)

Sends a bitmap image to the display.

**Header:** `0xFF 0xFC "easyTag" 0x62 [len:4] [count:2] 0x42 0x54 [crc:2]`
**Encryption Key:** `MacXor ^ 0x31`
**Payload:** RLE or uncompressed image bitplanes (Section 7)

### 8B. Query/Ping (Command `0xF0`)

Requests device status. Sends a minimal 1-byte payload and expects a notification response.

**Header:** `0xFF 0xF0 "easyTag" 0x5C 0x00000001 0x0001 0x42 0x54 [crc:2]`
**Encryption Key:** `MacXor ^ 0x63`
**Payload:** Single byte `0x01`, zero-padded to 200 bytes in one data packet.

### 8C. Text/Config Key (Command `0xF2`)

Uploads a 256-character hex configuration key to the device.

**Header:** `0xFF 0xF2 "eTag-CO" 0x5C [len:4] [count:2] 0x44 0x45 [crc:2]`
**Encryption Key:** `MacXor ^ 0x63`
**Payload:** Raw characters of the 256-char hex string, split into 200-byte data packet chunks.
**Input Validation:** String must be exactly 256 characters (`0x100`).

---

## 9. Notification Response

The tag sends a 20-byte encrypted notification after a successful transfer or ping.

### Decryption

```
Key = MacXor ^ 0x62
```

All 20 bytes are XORed with this key (no byte-9 skip).

**Important:** The notification key (`MacXor ^ 0x62`) is **different** from the image update key (`MacXor ^ 0x31`) and the query/config key (`MacXor ^ 0x63`).

### Parsed Fields

| Byte | Field | Notes |
|------|-------|-------|
| 2 | Battery | Raw value / 10.0 = voltage (e.g. `33` → 3.3V) |
| 3 | Temperature | Signed: if value > 127, result = `-(256 - value)` |

---

## 10. Timing Summary

| Constant | Value | Purpose |
|----------|-------|---------|
| Connection timeout | 20,000 ms | Max wait for BLE connection |
| Feedback timeout | 30,000 ms | Max wait for tag notification response |
| Post-CCCD write | 300 ms | Sleep after enabling notifications |
| Pre-data delay | 500 ms | Sleep before sending first data packet |
| Inter-packet delay | 20 ms | Default delay between each write |
| 5th-packet bonus | 3 ms | Additional delay every 5 packets |
| Retry attempts | 2 | Re-enqueue on failure (3 total attempts) |
| BLE scan wait | 20,000 ms | Duration of device scan |
| Queue poll | 5,000 ms | Send queue dispatcher loop interval |

---

## Appendix A: Differences from V1 Protocol Document

| Item | V1 (PROTOCOL.md) | V2 (Corrected) |
|------|-------------------|-----------------|
| Command types | Only image (`0xFC`) | Three: `0xFC`, `0xF0`, `0xF2` |
| CRC polynomial | 0x1021 (CCITT) | **0x8005** (ARC/IBM) |
| BW plane polarity | 0=White, 1=Black | **Confirmed: 0=White, 1=Black** (same as V1) |
| Identifier string | Always `easyTag` | `eTag-CO` for Text/Config |
| Marker bytes | Always `B` `T` | `D` `E` for Text/Config |
| Type ID | Only `0x62` | `0x5C` for Query and Text/Config |
| Post-connect delay | ~1 second | **300 ms** (post-CCCD descriptor write) |
| Notification magic byte | Not documented | `0x62` (different from all command keys) |
| Notification byte-9 skip | Not documented | **No skip** — all 20 bytes XORed |
| FE uncompressed fallback | Not documented | Pick shorter of FC (RLE) vs FE (raw) |
| Long repeat endianness | Not specified | **Little-endian** (low byte first) |
| Literal pixel count | "< 7 pixels" | Always packs **7 slots** (zero-padded) |
| Retry logic | Not mentioned | Up to 2 retries (3 total) |
| 5th-packet extra delay | Not mentioned | 3 ms additional every 5 packets |
