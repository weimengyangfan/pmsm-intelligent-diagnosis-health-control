"""Version 1 nibble transport over existing SPI1 diagnostic registers.

16-byte packet: A5 5A 01 flags seq:u16le B:fp32le C:fp32le CRC16:u16le.
CRC16/CCITT-FALSE over first 14 bytes; high nibble then low nibble per byte.
flags=1: already standardized, flags=0: raw mean currents in amperes.
"""
import math
import struct

MEAN = (8.817522565349967e-06, -1.1766226041269304e-05)
STD = (0.391256791915678, 0.39125679176324335)

def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc

def decode_packet(data):
    if len(data) != 16 or data[:3] != b'\xa5\x5a\x01' or data[3] not in (0, 1):
        raise ValueError('Invalid header/version/flags')
    if crc16(data[:14]) != struct.unpack_from('<H', data, 14)[0]:
        raise ValueError('CRC mismatch')
    seq, b, c = struct.unpack_from('<Hff', data, 4)
    if not all(math.isfinite(v) for v in (b, c)):
        raise ValueError('Non-finite feature')
    standardized = (b, c) if data[3] == 1 else tuple((v-m)/s for v,m,s in zip((b,c),MEAN,STD))
    return {'seq': seq, 'format': 'standardized' if data[3] else 'raw_ampere',
            'received': [b,c], 'standardized': list(standardized), 'packet_hex': data.hex()}

class Decoder:
    def __init__(self):
        self.nibbles = []
        self.rejected = 0

    def clear(self):
        self.nibbles.clear()

    def feed(self, value):
        if not 0 <= value < 16:
            self.clear()
            raise ValueError('Not a nibble')
        self.nibbles.append(value)
        # Resynchronize at any nibble boundary; never infer a missing nibble.
        while len(self.nibbles) >= 4:
            if self.nibbles[:4] != [10,5,5,10]:
                del self.nibbles[0]
                continue
            if len(self.nibbles) < 32:
                return None
            data = bytes((self.nibbles[i]<<4)|self.nibbles[i+1] for i in range(0,32,2))
            try:
                packet = decode_packet(data)
            except ValueError:
                self.rejected += 1
                del self.nibbles[0]
                continue
            del self.nibbles[:32]
            return packet
        return None
