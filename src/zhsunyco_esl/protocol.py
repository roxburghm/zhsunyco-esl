from typing import List, Tuple, Dict
from .models import LabelConfig

# CRC-16/ARC lookup table (polynomial 0x8005, nibble-at-a-time)
_CRC_TABLE = [
    0x0000, 0x8005, 0x800F, 0x000A, 0x801B, 0x001E, 0x0014, 0x8011,
    0x8033, 0x0036, 0x003C, 0x8039, 0x0028, 0x802D, 0x8027, 0x0022
]


def crc16(data: bytes) -> int:
    """CRC-16/ARC (polynomial 0x8005) with nibble-at-a-time lookup."""
    crc = 0xFFFF
    for byte in data:
        for _ in range(2):
            shifted = (crc << 4) & 0xFFFF
            index = (((crc >> 8) ^ byte) >> 4) & 0x0F
            crc = shifted ^ _CRC_TABLE[index]
            byte = (byte << 4) & 0xFF
    return crc


def compress_rle(data: List[int]) -> List[int]:
    """Custom RLE compression for pixel data per V2 spec Section 7.4."""
    out = []
    length = len(data)
    i = 0
    while i < length:
        # Count run of identical values
        run_len = 0
        current_val = data[i]
        j = i
        while j < length and data[j] == current_val:
            run_len += 1
            j += 1
            if run_len >= 0xFFFF:
                break

        if run_len < 7:
            # Literal mode: pack up to 7 pixels into 1 byte (zero-padded)
            byte_val = 0x80
            consumed = min(7, length - i)
            for k in range(consumed):
                byte_val |= (data[i + k] << (6 - k))
            out.append(byte_val)
            i += consumed
        elif run_len <= 31:
            # Short repeat: single byte (Color << 6) | RunLength
            out.append((current_val << 6) | run_len)
            i += run_len
        elif run_len <= 255:
            # Medium repeat: 2 bytes
            out.append((current_val << 6) | 0x01)
            out.append(run_len)
            i += run_len
        else:
            # Long repeat: 3 bytes (little-endian length)
            out.append((current_val << 6) | 0x00)
            out.append(run_len & 0xFF)
            out.append((run_len >> 8) & 0xFF)
            i += run_len
    return out


def _pack_pixels_uncompressed(plane: List[int], width: int, height: int) -> str:
    """Pack pixels 8-per-byte MSB first, return hex string (FE/03 format)."""
    w8 = (width + 7) & ~7
    h8 = (height + 7) & ~7
    hex_chars = []
    for y in range(h8):
        for x_start in range(0, w8, 8):
            byte_val = 0
            for bit in range(8):
                px = x_start + bit
                if y < height and px < width:
                    byte_val |= (plane[y * width + px] << (7 - bit))
            hex_chars.append(f"{byte_val:02X}")
    return "".join(hex_chars)


def _build_rle_hex(plane_bw: List[int], plane_red: List[int],
                   config: LabelConfig) -> str:
    """Build FC/FC8 RLE-compressed hex payload string."""
    comp_bw = compress_rle(plane_bw)
    comp_red = compress_rle(plane_red)
    hex_bw = "".join(f"{b:02X}" for b in comp_bw)
    hex_red = "".join(f"{b:02X}" for b in comp_red)

    h_end = config.height - 1
    w_end = config.width - 1

    # BW header (26 hex chars): FC X0 Y0 Y1 X1 Length
    s = f"FC{0:04X}{0:04X}{h_end:04X}{w_end:04X}{len(comp_bw):08X}{hex_bw}"
    # Red header (26 hex chars): FC8 X0 Y0 8 Y1 X1 Length
    s += f"FC8{0:03X}{0:04X}8{h_end:03X}{w_end:04X}{len(comp_red):08X}{hex_red}"

    return s


def _build_uncompressed_hex(plane_bw: List[int], plane_red: List[int],
                            config: LabelConfig) -> str:
    """Build FE/03 uncompressed hex payload string."""
    h_end = config.height - 1
    w_end = config.width - 1

    bw_hex = _pack_pixels_uncompressed(plane_bw, config.width, config.height)
    red_hex = _pack_pixels_uncompressed(plane_red, config.width, config.height)

    # BW: FE X0 Y0 Y1 X1 [data]
    s = f"FE{0:04X}{0:04X}{h_end:04X}{w_end:04X}{bw_hex}"
    # Red: 03 X0 Y0 Y1 X1 [data]
    s += f"03{0:04X}{0:04X}{h_end:04X}{w_end:04X}{red_hex}"

    return s


def _derive_key(mac_bytes: bytes, magic_byte: int) -> int:
    """Derive XOR encryption key: MacXor ^ MagicByte."""
    mac_xor = 0
    for b in mac_bytes:
        mac_xor ^= b
    return mac_xor ^ magic_byte


def _encrypt_header(header: bytearray, key: int) -> bytes:
    """XOR-encrypt header, skipping byte 9 (Type ID)."""
    return bytes([b ^ key if i != 9 else b for i, b in enumerate(header)])


def _encrypt_data_packet(pkt: bytearray, key: int) -> bytes:
    """XOR-encrypt all bytes of a data packet."""
    return bytes([b ^ key for b in pkt])


def _build_header(command: int, identifier: bytes, type_id: int,
                  payload_len: int, packet_count: int,
                  marker1: int, marker2: int) -> bytearray:
    """Build a 20-byte header packet (before encryption)."""
    header = bytearray(20)
    header[0] = 0xFF
    header[1] = command
    header[2:9] = identifier
    header[9] = type_id
    header[10:14] = payload_len.to_bytes(4, 'big')
    header[14:16] = packet_count.to_bytes(2, 'big')
    header[16] = marker1
    header[17] = marker2
    header[18:20] = crc16(bytes(header[:18])).to_bytes(2, 'big')
    return header


def _build_data_packets(payload: bytes, key: int) -> List[bytes]:
    """Build encrypted data packets from payload."""
    count = (len(payload) + 199) // 200
    packets = []
    for i in range(count):
        chunk = payload[i * 200:(i + 1) * 200]
        pkt = bytearray(204)
        pkt[0:2] = (i + 1).to_bytes(2, 'big')
        pkt[2:2 + len(chunk)] = chunk
        pkt[202:204] = crc16(bytes(pkt[:202])).to_bytes(2, 'big')
        packets.append(_encrypt_data_packet(pkt, key))
    return packets


def build_packets(plane_bw: List[int], plane_red: List[int],
                  mac_bytes: bytes, config: LabelConfig) -> Tuple[List[bytes], int]:
    """Build Image Update (0xFC) packets. Picks shorter of RLE vs uncompressed."""
    key = _derive_key(mac_bytes, 0x31)

    # Try both encodings, pick shorter payload
    rle_hex = _build_rle_hex(plane_bw, plane_red, config)
    uncompressed_hex = _build_uncompressed_hex(plane_bw, plane_red, config)

    if len(rle_hex) <= len(uncompressed_hex):
        payload = bytes.fromhex(rle_hex)
    else:
        payload = bytes.fromhex(uncompressed_hex)

    count = (len(payload) + 199) // 200
    header = _build_header(0xFC, b"easyTag", 0x62,
                           len(payload), count, 0x42, 0x54)

    packets = [_encrypt_header(header, key)]
    packets.extend(_build_data_packets(payload, key))

    return packets, key


def build_query_packets(mac_bytes: bytes) -> Tuple[List[bytes], int]:
    """Build Query/Ping (0xF0) packets."""
    key = _derive_key(mac_bytes, 0x63)

    header = _build_header(0xF0, b"easyTag", 0x5C, 1, 1, 0x42, 0x54)

    # Single data packet: seq=1, payload=0x01, zero-padded
    pkt = bytearray(204)
    pkt[0:2] = (1).to_bytes(2, 'big')
    pkt[2] = 0x01
    pkt[202:204] = crc16(bytes(pkt[:202])).to_bytes(2, 'big')

    packets = [_encrypt_header(header, key), _encrypt_data_packet(pkt, key)]
    return packets, key


def build_config_packets(hex_key: str, mac_bytes: bytes) -> Tuple[List[bytes], int]:
    """Build Text/Config (0xF2) packets."""
    if len(hex_key) != 256:
        raise ValueError(
            f"Config key must be exactly 256 characters, got {len(hex_key)}")

    key = _derive_key(mac_bytes, 0x63)
    payload = hex_key.encode('ascii')
    count = (len(payload) + 199) // 200

    header = _build_header(0xF2, b"eTag-CO", 0x5C,
                           len(payload), count, 0x44, 0x45)

    packets = [_encrypt_header(header, key)]
    packets.extend(_build_data_packets(payload, key))

    return packets, key


def decrypt_notification(data: bytes, mac_bytes: bytes) -> Dict:
    """Decrypt and parse a 20-byte notification response.

    Uses magic byte 0x62 (different from all command keys).
    All 20 bytes XORed — no byte-9 skip.
    """
    key = _derive_key(mac_bytes, 0x62)
    decrypted = bytes([b ^ key for b in data])

    battery_raw = decrypted[2]
    battery_voltage = battery_raw / 10.0

    temp_raw = decrypted[3]
    temperature = temp_raw if temp_raw <= 127 else -(256 - temp_raw)

    return {
        'raw': decrypted,
        'battery_voltage': battery_voltage,
        'temperature': temperature,
    }
