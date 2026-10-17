#!/usr/bin/env python3
"""Add dummy polys (effect attachment points) to a FLVER2 with no meshes, e.g. c0001.flv.

c0001.flv layout: 0x80 header, dummies (0x40 each), bones (0x80 each), UTF-16 bone names.
Adding dummies shifts the bones and names, so the header data offset (0x0C) and every bone's
name offset (+0x0C) move by 0x40 per dummy. Dummy record (as in the shipped dummy 255):
  f32[3] position (bone space), u8[4] colour, f32[3] forward, i16 reference id, i16 bone,
  f32[3] upward, i16 parent bone (-1), u8 flag, u8 useUpward, 16 zero bytes

Usage: flver_dummies.py IN.bnd OUT.bnd       (adds DUMMIES below to the .flv inside a model .bnd)
"""
import struct
import sys

import bnd4

# reference id: (bone name, position in FLVER bone space, comment)
DUMMIES = {
    900: ("R_Finger12", (0.045, 0.0, 0.0), "cigarette tip held in the right hand (past the index fingertip)"),
    901: ("Head", (-0.005, 0.0, 0.165), "cigarette tip in the mouth (7 cm in front of face dummy 255)"),
}


def bone_names(d):
    nd, nm, nb = struct.unpack_from("<3i", d, 0x14)
    base = 0x80 + nd * 0x40 + nm * 0x20
    names = []
    for i in range(nb):
        (off,) = struct.unpack_from("<i", d, base + i * 0x80 + 12)
        end = off
        while d[end:end + 2] != b"\0\0":
            end += 2
        names.append(d[off:end].decode("utf-16-le"))
    return names


def add_dummies(flver, dummies):
    d = bytearray(flver)
    nd, nm, nb, nmesh = struct.unpack_from("<4i", d, 0x14)
    if nm or nmesh:
        raise ValueError("only skeleton-only FLVERs (no materials/meshes) are supported")
    names = bone_names(d)
    template = bytes(d[0x80:0x80 + 0x40])   # first dummy as layout template
    template = next(bytes(d[0x80 + i * 0x40:0x80 + (i + 1) * 0x40]) for i in range(nd)
                    if struct.unpack_from("<h", d, 0x80 + i * 0x40 + 0x1C)[0] == 255) or template
    records = b""
    for ref_id, (bone, pos, _comment) in sorted(dummies.items()):
        r = bytearray(template)
        struct.pack_into("<3f", r, 0, *pos)
        struct.pack_into("<hh", r, 0x1C, ref_id, names.index(bone))
        records += bytes(r)
    shift = len(records)
    insert_at = 0x80 + nd * 0x40
    d[insert_at:insert_at] = records
    struct.pack_into("<i", d, 0x14, nd + len(dummies))
    struct.pack_into("<i", d, 0x0C, struct.unpack_from("<i", d, 0x0C)[0] + shift)
    bones = insert_at + shift
    for i in range(nb):
        off = bones + i * 0x80 + 12
        struct.pack_into("<i", d, off, struct.unpack_from("<i", d, off)[0] + shift)
    return bytes(d)


def main(src, dst):
    raw = open(src, "rb").read()
    files = bnd4.read_bnd4(raw)
    flv = next(f for f in files if f.name.lower().endswith(".flv"))
    flv.data = add_dummies(flv.data, DUMMIES)
    flv.usize = len(flv.data)
    open(dst, "wb").write(bnd4.write_bnd4(raw, files))
    for ref_id, (bone, pos, comment) in sorted(DUMMIES.items()):
        print(f"dummy {ref_id} on {bone} at {pos}: {comment}")
    print("wrote", dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
