"""Comprehensive test suite for the zhsunyco_esl protocol module.

Tests cover CRC-16, RLE compression, encryption, packet structures,
uncompressed encoding, encoding selection, query packets, config packets,
and notification decryption -- all validated against hand-computed values
derived from the V2 protocol specification (PROTOCOL-V2.md).
"""
import sys
import os
import pytest

# Ensure the source tree is importable regardless of working directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from zhsunyco_esl.protocol import (
    crc16,
    compress_rle,
    _derive_key,
    _encrypt_header,
    _encrypt_data_packet,
    _build_header,
    _build_data_packets,
    _pack_pixels_uncompressed,
    _build_rle_hex,
    _build_uncompressed_hex,
    build_packets,
    build_query_packets,
    build_config_packets,
    decrypt_notification,
)
from zhsunyco_esl.models import LabelConfig


# ---------------------------------------------------------------------------
#  Shared fixtures / constants
# ---------------------------------------------------------------------------

# Canonical test MAC from the V2 spec example (Section 4.1).
MAC_BYTES = bytes([0x3D, 0x00, 0x00, 0xE5, 0x7D, 0x76])
# MacXor = 0x3D ^ 0x00 ^ 0x00 ^ 0xE5 ^ 0x7D ^ 0x76 = 0xD3
MAC_XOR = 0xD3


# ===================================================================
#  1. CRC-16 Tests
# ===================================================================

class TestCRC16:
    """Verify CRC-16/ARC (polynomial 0x8005, init 0xFFFF, nibble LUT)."""

    def test_empty_data_returns_init_value(self):
        """Empty input must return the initial CRC value 0xFFFF."""
        assert crc16(b"") == 0xFFFF

    def test_single_zero_byte(self):
        """CRC of a single 0x00 byte."""
        assert crc16(b"\x00") == 0xFD02

    def test_single_0x01_byte(self):
        """CRC of a single 0x01 byte."""
        assert crc16(b"\x01") == 0x7D07

    def test_single_0xff_byte(self):
        """CRC of a single 0xFF byte."""
        assert crc16(b"\xff") == 0xFF00

    def test_two_bytes_0x00_0x01(self):
        """CRC of 0x00 0x01."""
        assert crc16(b"\x00\x01") == 0x0008

    def test_ascii_123(self):
        """CRC of ASCII '123' (0x31 0x32 0x33)."""
        assert crc16(b"123") == 0x217D

    def test_ascii_hello(self):
        """CRC of ASCII 'hello'."""
        assert crc16(b"hello") == 0x1CC5

    def test_ascii_abc(self):
        """CRC of ASCII 'abc'."""
        assert crc16(b"abc") == 0x44D8

    def test_two_bytes_0xde_0xad(self):
        """CRC of 0xDE 0xAD."""
        assert crc16(b"\xde\xad") == 0x47EF

    def test_polynomial_is_0x8005(self):
        """The lookup table's second entry is the polynomial itself."""
        from zhsunyco_esl.protocol import _CRC_TABLE
        assert _CRC_TABLE[1] == 0x8005
        # 0x1021 (CCITT) must NOT be present as the second entry.
        assert _CRC_TABLE[1] != 0x1021

    def test_crc_result_is_16bit(self):
        """CRC output must always fit in 16 bits."""
        for data in [b"\x00", b"\xff", b"easyTag", b"\xde\xad\xbe\xef"]:
            assert 0 <= crc16(data) <= 0xFFFF


# ===================================================================
#  2. RLE Compression Tests
# ===================================================================

class TestRLECompression:
    """Validate custom RLE per V2 spec Section 7.4."""

    # -- Literal mode ---------------------------------------------------

    def test_literal_six_pixels(self):
        """Run of alternating pixels (< 7 each), packed into one literal byte.

        [0,1,0,1,0,1] -> run of 1 each, so literal mode.
        Consumes all 6 pixels, zero-pads 7th position.
        byte = 0x80 | (0<<6)|(1<<5)|(0<<4)|(1<<3)|(0<<2)|(1<<1)|(0<<0)
             = 0x80 | 0x2A = 0xAA = 170
        """
        assert compress_rle([0, 1, 0, 1, 0, 1]) == [0xAA]

    def test_literal_packing_formula(self):
        """Verify byte = 0x80 | (P0<<6) | (P1<<5) | ... | (P6<<0).

        [1,1,0,0,1,1,0] -> all runs < 7, literal.
        byte = 0x80 | 0x40 | 0x20 | 0x00 | 0x00 | 0x04 | 0x02 | 0x00
             = 0x80 | 0x66 = 0xE6 = 230
        """
        assert compress_rle([1, 1, 0, 0, 1, 1, 0]) == [0xE6]

    def test_literal_fewer_than_seven_remaining_zero_padded(self):
        """Only 3 pixels remain: [1,0,1] -> zero-padded to 7 slots.

        Effective slots: [1,0,1,0,0,0,0]
        byte = 0x80 | (1<<6)|(0<<5)|(1<<4) = 0x80 | 0x50 = 0xD0 = 208
        """
        assert compress_rle([1, 0, 1]) == [0xD0]

    def test_literal_single_pixel(self):
        """Single pixel [1] -> padded to [1,0,0,0,0,0,0].

        byte = 0x80 | (1<<6) = 0x80 | 0x40 = 0xC0
        """
        assert compress_rle([1]) == [0xC0]

    def test_literal_all_ones_six(self):
        """[1,1,1,1,1,1] -> all runs still < 7, literal mode.

        byte = 0x80 | 0x7E = 0xFE
        """
        assert compress_rle([1, 1, 1, 1, 1, 1]) == [0xFE]

    # -- Short repeat ---------------------------------------------------

    def test_short_repeat_7_zeros(self):
        """Exactly 7 identical zeros: (0<<6)|7 = 7."""
        assert compress_rle([0] * 7) == [7]

    def test_short_repeat_7_ones(self):
        """Exactly 7 identical ones: (1<<6)|7 = 71 = 0x47."""
        assert compress_rle([1] * 7) == [0x47]

    def test_short_repeat_15_ones(self):
        """15 ones: (1<<6)|15 = 0x4F = 79."""
        assert compress_rle([1] * 15) == [0x4F]

    def test_short_repeat_31_zeros(self):
        """31 zeros: (0<<6)|31 = 31 = 0x1F."""
        assert compress_rle([0] * 31) == [31]

    def test_short_repeat_31_ones(self):
        """31 ones: (1<<6)|31 = 95 = 0x5F."""
        assert compress_rle([1] * 31) == [0x5F]

    # -- Medium repeat --------------------------------------------------

    def test_medium_repeat_32_zeros(self):
        """32 zeros: (0<<6)|0x01=0x01, then 32.

        Two bytes: [0x01, 32].
        """
        assert compress_rle([0] * 32) == [0x01, 32]

    def test_medium_repeat_100_ones(self):
        """100 ones: (1<<6)|0x01=0x41=65, then 100.

        Two bytes: [65, 100].
        """
        assert compress_rle([1] * 100) == [0x41, 100]

    def test_medium_repeat_255_zeros(self):
        """255 zeros: [0x01, 255]."""
        assert compress_rle([0] * 255) == [0x01, 255]

    def test_medium_repeat_255_ones(self):
        """255 ones: [0x41, 255]."""
        assert compress_rle([1] * 255) == [0x41, 255]

    def test_medium_repeat_50_ones(self):
        """50 ones: [0x41, 50]."""
        assert compress_rle([1] * 50) == [0x41, 50]

    # -- Long repeat ----------------------------------------------------

    def test_long_repeat_256_zeros(self):
        """256 zeros: (0<<6)|0x00=0x00, 256&0xFF=0, 256>>8=1.

        Three bytes: [0x00, 0x00, 0x01].
        """
        assert compress_rle([0] * 256) == [0x00, 0x00, 0x01]

    def test_long_repeat_256_ones(self):
        """256 ones: (1<<6)|0x00=0x40, 0x00, 0x01."""
        assert compress_rle([1] * 256) == [0x40, 0x00, 0x01]

    def test_long_repeat_1000_ones(self):
        """1000 ones: 0x40, 1000&0xFF=0xE8=232, 1000>>8=3.

        Three bytes: [0x40, 232, 3].
        """
        assert compress_rle([1] * 1000) == [0x40, 232, 3]

    def test_long_repeat_65535_zeros(self):
        """Maximum run (65535) zeros: [0x00, 0xFF, 0xFF]."""
        assert compress_rle([0] * 65535) == [0x00, 0xFF, 0xFF]

    def test_long_repeat_65535_ones(self):
        """Maximum run (65535) ones: [0x40, 0xFF, 0xFF]."""
        assert compress_rle([1] * 65535) == [0x40, 0xFF, 0xFF]

    # -- Mixed / transitions --------------------------------------------

    def test_mixed_runs_transitions(self):
        """[0]*10 + [1]*5 + [0]*20 -> three segments.

        10 zeros:  short repeat (0<<6)|10 = 10
        5 ones + next 2 zeros: run of ones is 5 < 7 -> literal of 7 pixels
            pixels = [1,1,1,1,1, 0,0]
            byte = 0x80 | (1<<6)|(1<<5)|(1<<4)|(1<<3)|(1<<2)|(0<<1)|(0<<0)
                 = 0x80 | 0x7C = 0xFC = 252
        18 zeros remaining: short repeat (0<<6)|18 = 18
        """
        data = [0] * 10 + [1] * 5 + [0] * 20
        assert compress_rle(data) == [10, 0xFC, 18]

    def test_alternating_pattern_20_pixels(self):
        """[0,1]*10 = 20 pixels -> three literal bytes.

        Pixels 0-6:  [0,1,0,1,0,1,0] -> 0xAA = 170
        Pixels 7-13: [1,0,1,0,1,0,1] -> 0xD5 = 213
        Pixels 14-19 (+pad): [0,1,0,1,0,1,0] -> 0xAA = 170
        """
        assert compress_rle([0, 1] * 10) == [0xAA, 0xD5, 0xAA]

    def test_all_zeros_large(self):
        """1000 zeros -> single long repeat: [0x00, 0xE8, 0x03]."""
        assert compress_rle([0] * 1000) == [0x00, 0xE8, 0x03]

    def test_all_ones_large(self):
        """500 ones -> long repeat: [0x40, 0xF4, 0x01].

        500 & 0xFF = 0xF4 = 244, 500 >> 8 = 1.
        """
        assert compress_rle([1] * 500) == [0x40, 0xF4, 0x01]

    def test_empty_input(self):
        """Empty list produces empty output."""
        assert compress_rle([]) == []


# ===================================================================
#  3. Encryption Tests
# ===================================================================

class TestEncryption:
    """Validate key derivation and XOR encryption."""

    # -- Key derivation -------------------------------------------------

    def test_key_derivation_magic_0x31(self):
        """V2 spec example: MAC 3D:00:00:E5:7D:76 with magic 0x31 -> 0xE2."""
        assert _derive_key(MAC_BYTES, 0x31) == 0xE2

    def test_key_derivation_magic_0x63(self):
        """MacXor 0xD3 ^ 0x63 = 0xB0."""
        assert _derive_key(MAC_BYTES, 0x63) == 0xB0

    def test_key_derivation_magic_0x62(self):
        """MacXor 0xD3 ^ 0x62 = 0xB1 (notification key)."""
        assert _derive_key(MAC_BYTES, 0x62) == 0xB1

    def test_key_derivation_all_zeros_mac(self):
        """All-zeros MAC: MacXor=0x00, key = 0x00 ^ magic."""
        mac_zeros = bytes(6)
        assert _derive_key(mac_zeros, 0x31) == 0x31
        assert _derive_key(mac_zeros, 0x63) == 0x63

    def test_key_derivation_all_ff_mac(self):
        """All-0xFF MAC: 0xFF XORed 6 times = 0x00, key = magic."""
        mac_ff = bytes([0xFF] * 6)
        assert _derive_key(mac_ff, 0x31) == 0x31

    # -- Header encryption (byte 9 skip) --------------------------------

    def test_header_byte9_never_modified(self):
        """Byte 9 (Type ID) must remain unchanged after encryption."""
        header = _build_header(0xFC, b"easyTag", 0x62, 100, 1, 0x42, 0x54)
        original_byte9 = header[9]
        key = _derive_key(MAC_BYTES, 0x31)
        encrypted = _encrypt_header(header, key)
        assert encrypted[9] == original_byte9

    def test_header_other_bytes_xored(self):
        """All header bytes except byte 9 are XORed with the key."""
        header = _build_header(0xFC, b"easyTag", 0x62, 100, 1, 0x42, 0x54)
        key = _derive_key(MAC_BYTES, 0x31)  # 0xE2
        encrypted = _encrypt_header(header, key)
        for i in range(20):
            if i == 9:
                assert encrypted[i] == header[i], "Byte 9 must NOT be XORed"
            else:
                assert encrypted[i] == (header[i] ^ key), (
                    f"Byte {i}: expected {header[i]^key:#04x}, got {encrypted[i]:#04x}"
                )

    def test_header_encryption_roundtrip(self):
        """Encrypting twice with the same key recovers the original
        (except byte 9 which is never touched)."""
        header = _build_header(0xF0, b"easyTag", 0x5C, 1, 1, 0x42, 0x54)
        key = 0xB0
        encrypted = _encrypt_header(bytearray(header), key)
        # Build bytearray from encrypted for second pass
        decrypted = _encrypt_header(bytearray(encrypted), key)
        assert decrypted == bytes(header)

    # -- Data packet encryption -----------------------------------------

    def test_data_packet_all_bytes_xored(self):
        """Every byte in a 204-byte data packet is XORed."""
        pkt = bytearray(range(204))
        key = 0xAB
        encrypted = _encrypt_data_packet(pkt, key)
        assert len(encrypted) == 204
        for i in range(204):
            assert encrypted[i] == (pkt[i] ^ key)

    def test_data_packet_encryption_roundtrip(self):
        """XOR is its own inverse: encrypt(encrypt(x)) = x."""
        pkt = bytearray(b"\xDE\xAD" * 102)
        key = 0x42
        encrypted = _encrypt_data_packet(pkt, key)
        decrypted = _encrypt_data_packet(bytearray(encrypted), key)
        assert decrypted == bytes(pkt)


# ===================================================================
#  4. Packet Structure Tests
# ===================================================================

class TestPacketStructure:
    """Validate header and data packet byte layout per V2 spec Section 6."""

    # -- Image header (0xFC) --------------------------------------------

    def test_image_header_size(self):
        """Image header must be exactly 20 bytes."""
        header = _build_header(0xFC, b"easyTag", 0x62, 100, 1, 0x42, 0x54)
        assert len(header) == 20

    def test_image_header_layout(self):
        """Byte-by-byte verification of the image header."""
        payload_len = 100
        packet_count = 1
        header = _build_header(0xFC, b"easyTag", 0x62,
                               payload_len, packet_count, 0x42, 0x54)

        assert header[0] == 0xFF, "Byte 0: Packet Start"
        assert header[1] == 0xFC, "Byte 1: Command"
        assert header[2:9] == b"easyTag", "Bytes 2-8: Identifier"
        assert header[9] == 0x62, "Byte 9: Type ID"
        assert int.from_bytes(header[10:14], "big") == payload_len, "Bytes 10-13: Length"
        assert int.from_bytes(header[14:16], "big") == packet_count, "Bytes 14-15: Count"
        assert header[16] == 0x42, "Byte 16: Marker 1 ('B')"
        assert header[17] == 0x54, "Byte 17: Marker 2 ('T')"
        # CRC covers bytes 0-17
        expected_crc = crc16(bytes(header[:18]))
        assert int.from_bytes(header[18:20], "big") == expected_crc

    # -- Query header (0xF0) --------------------------------------------

    def test_query_header_layout(self):
        """V2 spec 8B: 0xFF 0xF0 'easyTag' 0x5C 0x00000001 0x0001 'B' 'T' CRC."""
        header = _build_header(0xF0, b"easyTag", 0x5C, 1, 1, 0x42, 0x54)

        assert header[0] == 0xFF
        assert header[1] == 0xF0
        assert header[2:9] == b"easyTag"
        assert header[9] == 0x5C
        assert int.from_bytes(header[10:14], "big") == 1
        assert int.from_bytes(header[14:16], "big") == 1
        assert header[16] == 0x42
        assert header[17] == 0x54
        # Known CRC of this exact header (hand-computed)
        assert int.from_bytes(header[18:20], "big") == 0x0F68

    # -- Config header (0xF2) -------------------------------------------

    def test_config_header_layout(self):
        """V2 spec 8C: 0xFF 0xF2 'eTag-CO' 0x5C len count 'D' 'E' CRC."""
        header = _build_header(0xF2, b"eTag-CO", 0x5C, 256, 2, 0x44, 0x45)

        assert header[0] == 0xFF
        assert header[1] == 0xF2
        assert header[2:9] == b"eTag-CO"
        assert header[9] == 0x5C
        assert int.from_bytes(header[10:14], "big") == 256
        assert int.from_bytes(header[14:16], "big") == 2
        assert header[16] == 0x44  # 'D'
        assert header[17] == 0x45  # 'E'
        assert int.from_bytes(header[18:20], "big") == 0x9934

    def test_header_size_is_always_20(self):
        """All header types must produce exactly 20 bytes."""
        for cmd, ident, tid, m1, m2 in [
            (0xFC, b"easyTag", 0x62, 0x42, 0x54),
            (0xF0, b"easyTag", 0x5C, 0x42, 0x54),
            (0xF2, b"eTag-CO", 0x5C, 0x44, 0x45),
        ]:
            h = _build_header(cmd, ident, tid, 1, 1, m1, m2)
            assert len(h) == 20, f"Header for cmd {cmd:#04x} is {len(h)} bytes"

    # -- Data packets ---------------------------------------------------

    def test_data_packet_size_is_always_204(self):
        """Every data packet must be exactly 204 bytes."""
        key = 0xE2
        payload = bytes(range(200))
        packets = _build_data_packets(payload, key)
        for pkt in packets:
            assert len(pkt) == 204

    def test_data_packet_sequence_starts_at_one(self):
        """Sequence numbers start at 1 (not 0). Verify after decryption."""
        key = 0x00  # Use key=0 so encryption is a no-op.
        payload = b"\xAB" * 200
        packets = _build_data_packets(payload, key)
        assert len(packets) == 1
        seq = int.from_bytes(packets[0][0:2], "big")
        assert seq == 1

    def test_data_packet_sequence_increments(self):
        """Multiple packets have seq 1, 2, 3, ..."""
        key = 0x00
        payload = b"\x00" * 600  # 3 packets
        packets = _build_data_packets(payload, key)
        assert len(packets) == 3
        for idx, pkt in enumerate(packets, start=1):
            seq = int.from_bytes(pkt[0:2], "big")
            assert seq == idx

    def test_header_crc_covers_bytes_0_to_17(self):
        """CRC in bytes 18-19 must equal crc16(header[0:18])."""
        header = _build_header(0xFC, b"easyTag", 0x62, 500, 3, 0x42, 0x54)
        expected_crc = crc16(bytes(header[:18]))
        actual_crc = int.from_bytes(header[18:20], "big")
        assert actual_crc == expected_crc

    def test_data_crc_covers_bytes_0_to_201(self):
        """CRC in bytes 202-203 must equal crc16(pkt[0:202]) (before encryption)."""
        key = 0x00  # No encryption, so we can inspect directly.
        payload = bytes(range(200))
        packets = _build_data_packets(payload, key)
        pkt = packets[0]
        expected_crc = crc16(bytes(pkt[:202]))
        actual_crc = int.from_bytes(pkt[202:204], "big")
        assert actual_crc == expected_crc


# ===================================================================
#  5. Uncompressed Encoding (FE/03) Tests
# ===================================================================

class TestUncompressedEncoding:
    """Validate FE/03 raw pixel packing per V2 spec Section 7.5."""

    def test_8x8_all_zeros(self):
        """8x8 plane of all zeros -> 8 bytes of 0x00."""
        result = _pack_pixels_uncompressed([0] * 64, 8, 8)
        assert result == "00" * 8

    def test_8x8_all_ones(self):
        """8x8 plane of all ones -> 8 bytes of 0xFF."""
        result = _pack_pixels_uncompressed([1] * 64, 8, 8)
        assert result == "FF" * 8

    def test_msb_first_packing(self):
        """Verify MSB-first order: pixel 0 in bit 7, pixel 7 in bit 0.

        Row of 8 pixels [1,0,0,0,0,0,0,0] -> 0x80.
        Row of 8 pixels [0,0,0,0,0,0,0,1] -> 0x01.
        """
        # 8x1 image with MSB pixel set
        plane_msb = [1, 0, 0, 0, 0, 0, 0, 0]
        result = _pack_pixels_uncompressed(plane_msb, 8, 1)
        # height rounds to 8, so 8 rows: first row = 0x80, rest = 0x00
        assert result[:2] == "80"
        # Remaining 7 rows are zero-padded
        assert result[2:] == "00" * 7

    def test_non_multiple_of_8_dimensions(self):
        """5x3 image rounds up to 8x8 internally.

        Row 0: [0,1,0,1,0]+pad -> [0,1,0,1,0,0,0,0] -> 0x50
        Row 1: [1,0,1,0,1]+pad -> [1,0,1,0,1,0,0,0] -> 0xA8
        Row 2: [0,0,1,1,0]+pad -> [0,0,1,1,0,0,0,0] -> 0x30
        Rows 3-7: all zeros -> 0x00 each
        """
        plane = [0, 1, 0, 1, 0,
                 1, 0, 1, 0, 1,
                 0, 0, 1, 1, 0]
        result = _pack_pixels_uncompressed(plane, 5, 3)
        assert result == "50A8300000000000"

    def test_fe_header_format(self):
        """FE header: 'FE' + X0(4) + Y0(4) + Y1(4) + X1(4) + data."""
        config = LabelConfig(width=8, height=8)
        plane_bw = [0] * 64
        plane_red = [0] * 64
        hex_str = _build_uncompressed_hex(plane_bw, plane_red, config)

        # BW section: FE + 0000 + 0000 + 0007 + 0007 + data
        assert hex_str.startswith("FE00000000000700")
        # Check the full BW header (18 hex chars: 2+4+4+4+4)
        bw_header = hex_str[:18]
        assert bw_header == "FE0000000000070007"

    def test_03_header_format_for_red_plane(self):
        """Red plane header starts with '03' + coordinates."""
        config = LabelConfig(width=8, height=8)
        plane_bw = [0] * 64
        plane_red = [0] * 64
        hex_str = _build_uncompressed_hex(plane_bw, plane_red, config)

        # BW data: 8 bytes = 16 hex chars
        # BW section total: 18 (header) + 16 (data) = 34 chars
        # Red section starts at offset 34
        red_section = hex_str[34:]
        assert red_section.startswith("030000000000070007")

    def test_dimensions_round_up_to_multiples_of_8(self):
        """A 5x3 image produces 8*8/8 = 8 bytes per plane."""
        result = _pack_pixels_uncompressed([0] * 15, 5, 3)
        # 8 wide x 8 tall / 8 pixels per byte = 8 bytes = 16 hex chars
        assert len(result) == 16

    def test_known_small_pixel_array(self):
        """Verify complete hex output for a small known image."""
        # 8x8 image: first row all-1, rest all-0
        plane = [1] * 8 + [0] * 56
        result = _pack_pixels_uncompressed(plane, 8, 8)
        assert result == "FF" + "00" * 7


# ===================================================================
#  6. Encoding Selection Tests
# ===================================================================

class TestEncodingSelection:
    """Verify that build_packets picks the shorter encoding."""

    def test_uniform_plane_prefers_rle(self):
        """All-same-color plane: RLE is shorter and should be picked.

        For a 16x8 all-zero image, RLE produces 2 bytes per plane
        while uncompressed produces 16 bytes per plane.
        """
        config = LabelConfig(width=16, height=8)
        plane = [0] * 128

        rle_hex = _build_rle_hex(plane, plane, config)
        uncomp_hex = _build_uncompressed_hex(plane, plane, config)
        assert len(rle_hex) < len(uncomp_hex), "RLE should be shorter for uniform data"

    def test_random_plane_may_prefer_uncompressed(self):
        """A pseudo-random plane can cause RLE to be longer.

        We use seed=42 for reproducibility; the alternating/random
        patterns force many literal bytes in RLE.
        """
        import random
        rng = random.Random(42)
        config = LabelConfig(width=16, height=8)
        plane = [rng.randint(0, 1) for _ in range(128)]

        rle_hex = _build_rle_hex(plane, plane, config)
        uncomp_hex = _build_uncompressed_hex(plane, plane, config)
        assert len(uncomp_hex) < len(rle_hex), "Uncompressed should be shorter for noisy data"

    def test_build_packets_uses_shorter_encoding(self):
        """build_packets returns packets using the shorter payload."""
        # Uniform image -> RLE wins
        config = LabelConfig(width=16, height=8)
        plane = [0] * 128
        mac = MAC_BYTES
        packets, key = build_packets(plane, plane, mac, config)

        # Decrypt header to inspect payload length
        decrypted_header = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        payload_len = int.from_bytes(decrypted_header[10:14], "big")

        # RLE payload for uniform data is very small; uncompressed would be bigger
        rle_hex = _build_rle_hex(plane, plane, config)
        uncomp_hex = _build_uncompressed_hex(plane, plane, config)
        expected_payload_len = len(bytes.fromhex(
            rle_hex if len(rle_hex) <= len(uncomp_hex) else uncomp_hex
        ))
        assert payload_len == expected_payload_len


# ===================================================================
#  7. Query Packet Tests
# ===================================================================

class TestQueryPackets:
    """Validate build_query_packets per V2 spec Section 8B."""

    def test_returns_exactly_two_packets(self):
        """Query: 1 header + 1 data packet."""
        packets, _ = build_query_packets(MAC_BYTES)
        assert len(packets) == 2

    def test_query_uses_magic_0x63(self):
        """Query encryption key uses magic byte 0x63."""
        _, key = build_query_packets(MAC_BYTES)
        expected_key = MAC_XOR ^ 0x63  # 0xD3 ^ 0x63 = 0xB0
        assert key == expected_key

    def test_query_header_command_is_0xF0(self):
        """Decrypted header byte 1 must be 0xF0."""
        packets, key = build_query_packets(MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert decrypted[1] == 0xF0

    def test_query_header_identifier_is_easyTag(self):
        """Decrypted header bytes 2-8 must be 'easyTag'."""
        packets, key = build_query_packets(MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert bytes(decrypted[2:9]) == b"easyTag"

    def test_query_header_type_id_is_0x5C(self):
        """Byte 9 (Type ID, unencrypted) must be 0x5C."""
        packets, _ = build_query_packets(MAC_BYTES)
        # Byte 9 is never encrypted.
        assert packets[0][9] == 0x5C

    def test_query_header_payload_len_is_1(self):
        """Decrypted header reports payload length = 1."""
        packets, key = build_query_packets(MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert int.from_bytes(decrypted[10:14], "big") == 1

    def test_query_header_packet_count_is_1(self):
        """Decrypted header reports packet count = 1."""
        packets, key = build_query_packets(MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert int.from_bytes(decrypted[14:16], "big") == 1

    def test_query_data_payload_is_0x01_zero_padded(self):
        """Data packet (decrypted) has seq=1, byte[2]=0x01, rest zeros."""
        packets, key = build_query_packets(MAC_BYTES)
        decrypted_data = bytes(b ^ key for b in packets[1])
        assert int.from_bytes(decrypted_data[0:2], "big") == 1  # seq=1
        assert decrypted_data[2] == 0x01  # payload byte
        # Bytes 3-201 should be zero (padding).
        assert all(b == 0 for b in decrypted_data[3:202])

    def test_query_header_and_data_sizes(self):
        """Header=20 bytes, data=204 bytes."""
        packets, _ = build_query_packets(MAC_BYTES)
        assert len(packets[0]) == 20
        assert len(packets[1]) == 204


# ===================================================================
#  8. Config Packet Tests
# ===================================================================

class TestConfigPackets:
    """Validate build_config_packets per V2 spec Section 8C."""

    def test_valid_256_char_key_accepted(self):
        """A 256-character hex key must not raise."""
        hex_key = "AB" * 128  # 256 characters
        packets, key = build_config_packets(hex_key, MAC_BYTES)
        # Should produce 1 header + 2 data packets (256 bytes / 200 = 2 chunks)
        assert len(packets) == 3

    def test_rejects_non_256_char_input(self):
        """Any length other than 256 must raise ValueError."""
        with pytest.raises(ValueError, match="256 characters"):
            build_config_packets("A" * 255, MAC_BYTES)
        with pytest.raises(ValueError, match="256 characters"):
            build_config_packets("A" * 257, MAC_BYTES)
        with pytest.raises(ValueError, match="256 characters"):
            build_config_packets("", MAC_BYTES)

    def test_config_uses_eTag_CO_identifier(self):
        """Decrypted header bytes 2-8 must be 'eTag-CO'."""
        hex_key = "00" * 128
        packets, key = build_config_packets(hex_key, MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert bytes(decrypted[2:9]) == b"eTag-CO"

    def test_config_uses_markers_D_E(self):
        """Decrypted header bytes 16-17 must be 'D' (0x44) and 'E' (0x45)."""
        hex_key = "FF" * 128
        packets, key = build_config_packets(hex_key, MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert decrypted[16] == 0x44  # 'D'
        assert decrypted[17] == 0x45  # 'E'

    def test_config_uses_magic_0x63(self):
        """Config encryption key = MacXor ^ 0x63."""
        hex_key = "00" * 128
        _, key = build_config_packets(hex_key, MAC_BYTES)
        assert key == MAC_XOR ^ 0x63  # 0xD3 ^ 0x63 = 0xB0

    def test_config_command_is_0xF2(self):
        """Decrypted header byte 1 must be 0xF2."""
        hex_key = "00" * 128
        packets, key = build_config_packets(hex_key, MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert decrypted[1] == 0xF2

    def test_config_type_id_is_0x5C(self):
        """Byte 9 (Type ID, never encrypted) must be 0x5C."""
        hex_key = "00" * 128
        packets, _ = build_config_packets(hex_key, MAC_BYTES)
        assert packets[0][9] == 0x5C

    def test_config_payload_length(self):
        """Payload length in header must equal 256 (the key length as ASCII bytes)."""
        hex_key = "AB" * 128
        packets, key = build_config_packets(hex_key, MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert int.from_bytes(decrypted[10:14], "big") == 256

    def test_config_packet_count_is_2(self):
        """256-byte payload / 200 = ceil = 2 data packets."""
        hex_key = "AB" * 128
        packets, key = build_config_packets(hex_key, MAC_BYTES)
        decrypted = bytearray(
            b ^ key if i != 9 else b for i, b in enumerate(packets[0])
        )
        assert int.from_bytes(decrypted[14:16], "big") == 2

    def test_config_data_reconstructs_payload(self):
        """Decrypting and reassembling data packets recovers the original
        256-byte ASCII payload."""
        hex_key = "AB" * 128  # the key string
        packets, key = build_config_packets(hex_key, MAC_BYTES)

        # Decrypt and reassemble
        payload_bytes = bytearray()
        for pkt in packets[1:]:
            decrypted = bytes(b ^ key for b in pkt)
            # Bytes 2-201 contain the chunk
            payload_bytes.extend(decrypted[2:202])

        # Trim to actual payload length (256 bytes)
        payload_bytes = payload_bytes[:256]
        assert payload_bytes.decode("ascii") == hex_key


# ===================================================================
#  9. Notification Decryption Tests
# ===================================================================

class TestNotificationDecryption:
    """Validate decrypt_notification per V2 spec Section 9."""

    def _make_encrypted_notification(self, decrypted_bytes: bytes) -> bytes:
        """Helper: encrypt a 20-byte notification with the notification key."""
        key = _derive_key(MAC_BYTES, 0x62)  # 0xB1
        return bytes(b ^ key for b in decrypted_bytes)

    def test_notification_uses_magic_0x62(self):
        """Notification key = MacXor ^ 0x62, NOT 0x31 or 0x63."""
        key = _derive_key(MAC_BYTES, 0x62)
        assert key == 0xB1
        # Confirm it differs from image and query/config keys.
        assert key != _derive_key(MAC_BYTES, 0x31)  # 0xE2
        assert key != _derive_key(MAC_BYTES, 0x63)  # 0xB0

    def test_battery_parsing(self):
        """raw=33 at byte 2 -> voltage = 33/10.0 = 3.3V."""
        plain = bytearray(20)
        plain[2] = 33
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["battery_voltage"] == pytest.approx(3.3)

    def test_temperature_parsing_positive(self):
        """raw=23 -> 23°C (room temperature)."""
        plain = bytearray(20)
        plain[3] = 23
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["temperature"] == 23

    def test_temperature_parsing_negative(self):
        """raw=246 -> signed -(256-246) = -10°C."""
        plain = bytearray(20)
        plain[3] = 246
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["temperature"] == -10

    def test_temperature_zero(self):
        """raw=0 -> 0°C."""
        plain = bytearray(20)
        plain[3] = 0
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["temperature"] == 0

    def test_temperature_boundary_127(self):
        """raw=127 -> 127°C (max positive signed byte)."""
        plain = bytearray(20)
        plain[3] = 127
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["temperature"] == 127

    def test_temperature_boundary_128(self):
        """raw=128 -> -(256-128) = -128°C (most negative signed byte)."""
        plain = bytearray(20)
        plain[3] = 128
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["temperature"] == -128

    def test_all_20_bytes_xored_no_byte9_skip(self):
        """All 20 bytes are decrypted -- byte 9 is NOT skipped."""
        plain = bytearray(range(20))
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert list(result["raw"]) == list(range(20))
        # Specifically verify byte 9 was decrypted correctly.
        assert result["raw"][9] == 9

    def test_notification_roundtrip_all_bytes(self):
        """Encrypting then decrypting restores every byte, including byte 9."""
        plain = bytes([0xAA] * 20)
        encrypted = self._make_encrypted_notification(plain)
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["raw"] == plain

    def test_combined_battery_and_temperature(self):
        """Both battery and temperature in the same notification."""
        plain = bytearray(20)
        plain[2] = 33   # 3.3V
        plain[3] = 23   # 23°C
        encrypted = self._make_encrypted_notification(bytes(plain))
        result = decrypt_notification(encrypted, MAC_BYTES)
        assert result["battery_voltage"] == pytest.approx(3.3)
        assert result["temperature"] == 23
