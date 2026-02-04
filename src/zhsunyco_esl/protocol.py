from typing import List, Tuple
from .models import LabelConfig

def crc16_ccitt(data: bytes) -> int:
    crc_table = [
        0x0000, 0x8005, 0x800F, 0x000A, 0x801B, 0x001E, 0x0014, 0x8011,
        0x8033, 0x0036, 0x003C, 0x8039, 0x0028, 0x802D, 0x8027, 0x0022
    ]
    crc = 0xFFFF
    for byte in data:
        for _ in range(2):
            v5 = (crc << 4) & 0xFFFF
            temp = (crc >> 8) ^ byte
            temp = (temp >> 4) & 0xF
            crc = v5 ^ crc_table[temp]
            byte = (byte << 4) & 0xFF
    return crc

def compress_rle(data: List[int]) -> List[int]:
    out = []
    length = len(data)
    i = 0
    while i < length:
        run_len = 0
        current_val = data[i]
        j = i
        while j < length and data[j] == current_val:
            run_len += 1
            j += 1
            if run_len >= 0xFFFF: break
        
        if run_len < 7:
            byte_val = 0x80
            if i < length: byte_val |= (data[i] << 6)
            accum = 0
            consumed = 0
            for k in range(7):
                if i + k < length:
                    consumed += 1
                    if k > 0: accum |= (data[i+k] << (6 - k))
            byte_val |= accum
            out.append(byte_val)
            i += consumed
        else:
            if run_len <= 31:
                out.append((current_val << 6) | run_len)
            elif run_len <= 255:
                out.append((current_val << 6) | 0x01)
                out.append(run_len)
            else:
                out.append((current_val << 6) | 0x00)
                out.append(run_len & 0xFF)
                out.append((run_len >> 8) & 0xFF)
            i += run_len
    return out

def build_packets(plane_bw: List[int], plane_red: List[int], mac_bytes: bytes, config: LabelConfig) -> Tuple[List[bytes], int]:
    comp_bw = compress_rle(plane_bw)
    comp_red = compress_rle(plane_red)
    hex_bw = "".join([f"{b:02X}" for b in comp_bw])
    hex_red = "".join([f"{b:02X}" for b in comp_red])
    
    # Original script hardcoded 296x128 related values in the command string:
    # 0x80 (128) - 1 = 0x7F (127) -> 007F
    # 0x128 (296) - 1 = 0x127 (295) -> 0127
    
    # From reversed engineering:
    # Command 0: BW data info
    # Command 1: Red data info
    
    h_minus_1 = config.height - 1
    w_minus_1 = config.width - 1
    
    # The format seems to be: 
    # cmd (FC/FC8) | Xstart (2B) | Ystart (2B) | Xend (2B) | Yend (2B) | DataLen (4B) | Data
    # But strictly following the original script's pattern logic for now.
    
    # NOTE: The original script had:
    # s = f"FC{0:04X}{0:04X}{HEIGHT-1:04X}{WIDTH-1:04X}{len(comp_bw):08X}{hex_bw}"
    # s += f"FC8{0:03X}{0:04X}8{HEIGHT-1:03X}{WIDTH-1:04X}{len(comp_red):08X}{hex_red}"
    
    # The "FC8" part looks like FC (cmd) then 8...? 
    # Original: f"FC8{0:03X}..." -> FC8000...
    # Wait, 0:03X means 3 hex digits. 
    # Let's reproduce the string construction EXACTLY but with variables.

    # Packet 1 (BW)
    s = f"FC{0:04X}{0:04X}{h_minus_1:04X}{w_minus_1:04X}{len(comp_bw):08X}{hex_bw}"
    
    # Packet 2 (Red) - appending to same string 's' which becomes 'payload'
    # The original script had a weird formatting for the second part:
    # f"FC8{0:03X}{0:04X}8{HEIGHT-1:03X}{WIDTH-1:04X}{len(comp_red):08X}{hex_red}"
    # If 0 is 000, then FC8000.
    # It looks like the '8' might be part of the coordinates or flags?
    # Actually, looking at the decompilation/original script carefully:
    # FC is likely the command.
    # FC + ...
    # FC8... 
    # Let's assume the previous script worked and just copy the logic identically.
    
    # X_start=0, Y_start=0
    # The '8's might be specific indicators for Red plane?
    s += f"FC8{0:03X}{0:04X}8{h_minus_1:03X}{w_minus_1:04X}{len(comp_red):08X}{hex_red}"
    
    payload = bytes.fromhex(s)
    
    mac_xor = 0
    for b in mac_bytes: mac_xor ^= b
    key = mac_xor ^ 0x31 

    count = (len(payload) + 199) // 200
    header = bytearray(20)
    header[0], header[1] = 0xFF, 0xFC
    header[2:9] = b"easyTag"
    header[9] = 0x62
    header[10:14] = len(payload).to_bytes(4, 'big')
    header[14:16] = count.to_bytes(2, 'big')
    header[16], header[17] = 0x42, 0x54 # 'BT'
    header[18:20] = crc16_ccitt(header[:18]).to_bytes(2, 'big')

    packets = [bytes([b ^ key if i != 9 else b for i, b in enumerate(header)])]

    for i in range(count):
        chunk = payload[i*200 : (i+1)*200]
        pkt = bytearray(204)
        seq = i + 1 
        pkt[0:2] = seq.to_bytes(2, 'big')
        pkt[2:2+len(chunk)] = chunk
        pkt[202:204] = crc16_ccitt(pkt[:202]).to_bytes(2, 'big')
        packets.append(bytes([b ^ key for b in pkt]))
        
    return packets, key
