#!/usr/bin/env python3
"""Disassemble the function(s) containing given VAs in DarkSoulsII.exe using .pdata bounds.

Usage: disfn.py EXE VA [VA...]
"""
import bisect
import struct
import subprocess
import sys

exe, *vas = sys.argv[1:]
d = open(exe, "rb").read()
pe = struct.unpack_from("<I", d, 0x3C)[0]
opt = struct.unpack_from("<H", d, pe + 20)[0]
ib = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
pdata_rva, pdata_size = struct.unpack_from("<II", d, pe + 24 + 112 + 3 * 8)
ns = struct.unpack_from("<H", d, pe + 6)[0]
secs = []
for i in range(ns):
    o = pe + 24 + opt + i * 40
    vs, va, rs, ro = struct.unpack_from("<IIII", d, o + 8)
    secs.append((va, vs, ro))


def rva2off(rva):
    for va, vs, ro in secs:
        if va <= rva < va + vs:
            return ro + rva - va


p = rva2off(pdata_rva)
funcs = sorted(struct.unpack_from("<II", d, p + i * 12) for i in range(pdata_size // 12))
starts = [f[0] for f in funcs]
for a in vas:
    rva = int(a, 16) - ib
    i = bisect.bisect_right(starts, rva) - 1
    b, e = funcs[i]
    print(f"; function {ib + b:#x}-{ib + e:#x} contains {a}", flush=True)
    subprocess.run(["objdump", "-d", "-M", "intel", "--no-show-raw-insn",
                    f"--start-address={ib + b:#x}", f"--stop-address={ib + e:#x}", exe])
