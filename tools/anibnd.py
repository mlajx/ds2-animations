#!/usr/bin/env python3
"""Replace an animation inside c0001.anibnd(.dcx) and keep the Morpheme network in sync.

The network (c0001.nmb) caches every animation's clip duration per node, as
  u32 animFileId, u32 hash, u8 2, pad[3], f32 clipStart (0.0), f32 clipEnd (1.0), f32 duration
(3238 records, all equal to their .nsa duration in the shipped files). Playback stops at that
cached duration, so after swapping in a longer .nsa the records must be updated too.

Usage: anibnd.py replace IN.anibnd[.dcx] OUT.anibnd[.dcx] NAME_SUBSTRING NEW.nsa
"""
import re
import struct
import sys

import bnd4

RECORD = re.compile(rb"(?s)(....)....\x02\x00\x00\xcd\x00\x00\x00\x00\x00\x00\x80\x3f(....)")


def duration_records(nmb, anim_id):
    """Offsets of the duration floats for anim_id."""
    out = []
    for m in RECORD.finditer(nmb):
        if struct.unpack("<I", m.group(1))[0] == anim_id:
            out.append(m.start(2))
    return out


def replace(src, needle, new_nsa):
    files = bnd4.read_bnd4(src)
    hits = [i for i, f in enumerate(files) if needle.lower() in f.name.lower() and f.name.endswith(".nsa")]
    if len(hits) != 1:
        sys.exit(f"'{needle}' matches {len(hits)} animations, need exactly 1")
    anim = files[hits[0]]
    nmb_index = next(i for i, f in enumerate(files) if f.name.endswith(".nmb"))
    nmb = bytearray(files[nmb_index].data)
    (old,) = struct.unpack_from("<f", anim.data, 0x28)
    (new,) = struct.unpack_from("<f", new_nsa, 0x28)
    offsets = duration_records(nmb, anim.id)
    for off in offsets:
        struct.pack_into("<f", nmb, off, new)
    print(f"{anim.name.lstrip(chr(92))} (id {anim.id}): {old:.3f} s -> {new:.3f} s, "
          f"{len(offsets)} network duration record(s) updated")
    return bnd4.replace_files(src, {hits[0]: new_nsa, nmb_index: bytes(nmb)})


def main(argv):
    if len(argv) != 6 or argv[1] != "replace":
        sys.exit(__doc__)
    _, _, src, dst, needle, nsa_path = argv
    out = replace(open(src, "rb").read(), needle, open(nsa_path, "rb").read())
    open(dst, "wb").write(bnd4.dcx(out) if dst.endswith(".dcx") else out)
    print("wrote", dst)


if __name__ == "__main__":
    main(sys.argv)
