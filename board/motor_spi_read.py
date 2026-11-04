#!/usr/bin/env python3
"""Read-only User_Reg SPI diagnostics on FMQL30TAI. Run as root."""
import argparse
import mmap
import os
import struct
import time

BASE = 0x400C0000
SIGNATURE = 0x53504931

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--expect', type=int, choices=range(16))
    args = parser.parse_args()
    fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
    try:
        with mmap.mmap(fd, 4096, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ, offset=BASE) as mem:
            def read(offset):
                return struct.unpack_from('<I', mem, offset)[0]
            sig = read(0x88)
            print('SPI signature: 0x%08X; register decoder version: 0x%08X' % (sig, read(0xC0)), flush=True)
            if sig != SIGNATURE:
                raise SystemExit('SPI signature mismatch. Check loaded BOOT.bin; no registers were written.')
            while True:
                status = read(0x84)
                print('status=%d frames=%d writes=%d errors=%d last_frame=0x%08X' %
                      (status, read(0x8C), read(0x90), read(0x94), read(0x98)), flush=True)
                if args.expect is not None and status != args.expect:
                    raise SystemExit('STATUS_MISMATCH expected=%d actual=%d' % (args.expect, status))
                if not args.watch:
                    break
                time.sleep(0.2)
    finally:
        os.close(fd)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
