import struct,binascii

def bits(x):return struct.unpack('<I',struct.pack('<f',x))[0]
def unbits(text):return struct.unpack('<f',struct.pack('<I',int(text,16)))[0]
def lines_for_cycle(seq,points):
    lines=[];crc=65535
    for i,point in enumerate(points):
        t,b,c=point[:3];crc=binascii.crc_hqx(struct.pack('<Hfff',i,t,b,c),crc)
        lines.append(f'~D{i:04X}{bits(t):08X}{bits(b):08X}{bits(c):08X}\n')
    return f'~B{seq:04X}{len(points):04X}{crc:04X}\n',lines,f'~E{seq:04X}\n'
