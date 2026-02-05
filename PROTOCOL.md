'DEPRECATED: See PROTOCOL-V2.md`

---

# eTag / eLabel BLE Protocol Documentation

**Target Device:** ET0290 (2.9-inch E-Ink Tag)  
**Resolution:** 296 x 128 pixels (Landscape)  

## 1. Bluetooth LE Specifications

*   **Service UUID:** `00001523-1212-efde-1523-785feabcd123`
*   **Write Characteristic:** `00001525-1212-efde-1523-785feabcd123`
*   **Notify Characteristic:** `00001526-1212-efde-1523-785feabcd123`

## 2. Connection Flow

1.  **Connect** to the BLE device.
2.  **Enable Notifications** on the Notify Characteristic (0x1526).
3.  **Wait** ~1 second for the connection to stabilize.
4.  **Send Header Packet** (Write with Response).
5.  **Wait** ~500ms.
6.  **Send Data Packets** sequentially (Write with Response recommended, or 20ms delays).
7.  **Wait** for display refresh (~15s).

## 3. Encryption & Checksum

### Encryption (XOR)
All packets (Header and Data) are encrypted using a single-byte XOR key, calculated derived from the device's MAC address.

1.  **MacXor:** XOR all 6 bytes of the MAC address together.
    *   Example MAC: `3D:00:00:E5:7D:76`
    *   Logic: `0x3D ^ 0x00 ^ 0x00 ^ 0xE5 ^ 0x7D ^ 0x76` = `0xD3`
2.  **Magic Byte:** Depends on the command type.
    *   **Image Update:** `0x31` (ASCII '1')
    *   *Text/Config:* `0x63` (ASCII 'c') - *Not verified in this test, but present in code.*
3.  **Final Key:** `Key = MacXor ^ MagicByte`
    *   Example Key: `0xD3 ^ 0x31` = **`0xE2`**

**Encryption Scope:**
*   **Header Packet:** Bytes 0-8 and 10-19 are XORed. **Byte 9 (Type ID) is NOT encrypted.**
*   **Data Packets:** All 204 bytes are XORed.

### Checksum (CRC-16)
Standard CRC-16-CCITT.
*   **Polynomial:** `0x1021`
*   **Initial Value:** `0xFFFF`

## 4. Packet Structure

### A. Header Packet (20 Bytes)
Describes the upcoming data transfer.

| Offset | Value | Description |
| :--- | :--- | :--- |
| 0 | `0xFF` | Packet Start |
| 1 | `0xFC` | Command (Image Update) |
| 2-8 | `easyTag` | ASCII String Identifier |
| 9 | `0x62` | **Type ID (Unencrypted)** |
| 10-13 | `Length` | Total Payload Length (Big Endian) |
| 14-15 | `Count` | Total number of data packets (Big Endian) |
| 16 | `0x42` | Marker 'B' |
| 17 | `0x54` | Marker 'T' |
| 18-19 | `CRC16` | Checksum of bytes 0-17 |

*Note: `Count` is calculated as (PayloadLength / 200) rounded up to the nearest whole number`.*

### B. Data Packet (204 Bytes)
Carries the payload in 200-byte chunks.

| Offset | Value | Description |
| :--- | :--- | :--- |
| 0-1 | `Seq` | Sequence Number (Big Endian). **Starts at 1.** |
| 2-201 | `Data` | 200 bytes of payload chunk (Padded with 0x00 if last) |
| 202-203| `CRC16` | Checksum of bytes 0-201 (Seq + Data) |

## 5. Image Payload Format

The payload consists of two concatenated hexadecimal ASCII strings representing the Black/White bitplane and the Red bitplane.

**Full Payload String:** `[BW_Header][BW_Data][Red_Header][Red_Data]` -> Convert to Bytes.

### Bitplane Mapping (296 x 128 Landscape)
*   **Plane 1 (Black/White):** `0` = White, `1` = Black.
*   **Plane 2 (Red):** `0` = No Ink, `1` = Red.

### Payload Headers
The headers are ASCII Hex strings defining the update area. Coordinates are Big Endian Hex.

**1. Black/White Header (`FC`)**
Format: `FC` + `X0` + `Y0` + `Y1` + `X1` + `Length`
*   `X0`: 4 chars (e.g., "0000")
*   `Y0`: 4 chars (e.g., "0000")
*   `Y1`: 4 chars (e.g., "007F" for 127)
*   `X1`: 4 chars (e.g., "0127" for 295)
*   `Length`: 8 chars (Length of the following compressed data in bytes)

**2. Red Header (`FC8`)**
Format: `FC8` + `X0` + `Y0` + `8` + `Y1` + `X1` + `Length`
*   `X0`: **3 chars** (e.g., "000")
*   `Y0`: 4 chars (e.g., "0000")
*   `8`: Literal '8' char.
*   `Y1`: **3 chars** (e.g., "07F")
*   `X1`: 4 chars (e.g., "0127")
*   `Length`: 8 chars

### RLE Compression
The image data is compressed using a custom Run-Length Encoding scheme. Processing is done pixel-by-pixel (row-major).

| Run Length | Format | Byte Structure |
| :--- | :--- | :--- |
| **Literal (Mixed)** | < 7 pixels | `1` `P0` `P1` `P2` `P3` `P4` `P5` `P6` <br> `0x80 | (P0<<6) | Packed(P1..P6)` |
| **Short Repeat** | 7 - 31 | `0` `C` `L` `L` `L` `L` `L` <br> `(Color<<6) \| Length` |
| **Medium Repeat** | 32 - 255 | **Byte 1:** `0` `C` `0` `0` `0` `0` `0` `1` (`(Color<<6) \| 0x01`) <br> **Byte 2:** `Length` |
| **Long Repeat** | > 255 | **Byte 1:** `0` `C` `0` `0` `0` `0` `0` `0` (`(Color<<6) \| 0x00`) <br> **Byte 2:** `Length Low` <br> **Byte 3:** `Length High` |

## 6. Implementation Notes
1.  **Resolution:** The ET0290 must be addressed as 296 (W) x 128 (H). Addressing it as 128x296 results in garbled/striped output.
2.  **Notification:** The tag sends a notification (usually status/firmware info) during transfer. This is encrypted with the same key. A successful handshake/header write often triggers a notification starting with `00` (decrypted) or firmware strings.
3.  **Timing:** Use `Write With Response` to prevent buffer overflows on the tag. If using `Write Without Response`, strict delays (20ms+) are required.
