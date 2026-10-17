#!/usr/bin/env python3
"""Print IAT slot VA -> DLL!function for a PE file. Usage: imports.py EXE"""
import struct
import sys

d = open(sys.argv[1], "rb").read()
pe = struct.unpack_from("<I", d, 0x3C)[0]
opt = struct.unpack_from("<H", d, pe + 20)[0]
ib = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
imp_rva = struct.unpack_from("<I", d, pe + 24 + 112 + 8)[0]
ns = struct.unpack_from("<H", d, pe + 6)[0]
secs = [struct.unpack_from("<IIII", d, pe + 24 + opt + i * 40 + 8) for i in range(ns)]


def r2o(rva):
    for vs, va, rs, ro in secs:
        if va <= rva < va + max(vs, rs):
            return ro + rva - va


def cstr(o):
    return d[o:d.index(b"\0", o)].decode()


o = r2o(imp_rva)
while True:
    oft, _, _, name, ft = struct.unpack_from("<IIIII", d, o)
    if not name:
        break
    dll = cstr(r2o(name))
    i = 0
    while True:
        (thunk,) = struct.unpack_from("<Q", d, r2o(oft or ft) + 8 * i)
        if not thunk:
            break
        fn = f"#{thunk & 0xFFFF}" if thunk >> 63 else cstr(r2o(thunk & 0x7FFFFFFF) + 2)
        print(f"{ib + ft + 8 * i:#x} {dll}!{fn}")
        i += 1
    o += 20
