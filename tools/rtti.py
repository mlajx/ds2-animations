#!/usr/bin/env python3
"""Find vtables of MSVC x64 classes by RTTI name in a PE file.

Usage: rtti.py EXE SUBSTRING
Prints, for each matching type: TypeDescriptor VA, vtable VA and the first virtual function VAs.
"""
import re
import struct
import sys

exe, needle = sys.argv[1:3]
d = open(exe, "rb").read()
pe = struct.unpack_from("<I", d, 0x3C)[0]
opt = struct.unpack_from("<H", d, pe + 20)[0]
ib = struct.unpack_from("<Q", d, pe + 24 + 24)[0]
ns = struct.unpack_from("<H", d, pe + 6)[0]
secs = []
for i in range(ns):
    o = pe + 24 + opt + i * 40
    vs, va, rs, ro = struct.unpack_from("<IIII", d, o + 8)
    secs.append((va, max(vs, rs), ro, rs))


def off2rva(off):
    for va, vs, ro, rs in secs:
        if ro <= off < ro + rs:
            return va + off - ro


def rva2off(rva):
    for va, vs, ro, rs in secs:
        if va <= rva < va + rs:
            return ro + rva - va


for m in re.finditer(rb"\.\?AV[^\0]*" + re.escape(needle.encode()) + rb"[^\0]*@@\0", d):
    td_rva = off2rva(m.start() - 0x10)
    name = m.group().rstrip(b"\0").decode()
    # Complete Object Locator: signature 1, offset, cdOffset, pTypeDescriptor (rva), pClassHierarchy, pSelf
    pat = struct.pack("<I", td_rva)
    for c in re.finditer(re.escape(pat), d):
        col_off = c.start() - 12
        sig, off_, cd = struct.unpack_from("<III", d, col_off)
        if sig != 1:
            continue
        col_rva = off2rva(col_off)
        if struct.unpack_from("<I", d, col_off + 20)[0] != col_rva:
            continue
        for v in re.finditer(re.escape(struct.pack("<Q", ib + col_rva)), d):
            vt_rva = off2rva(v.start() + 8)
            fns = []
            for k in range(40):
                (fp,) = struct.unpack_from("<Q", d, v.start() + 8 + 8 * k)
                if not (ib + 0x1000 <= fp < ib + 0x10A6000):
                    break
                fns.append(hex(fp))
            print(f"{name} td={ib + td_rva:#x} offset={off_} vtable={ib + vt_rva:#x} ({len(fns)} fns)")
            print("   ", " ".join(fns))
