#!/usr/bin/env python3
"""Make tuned copies of DS2 effects (FFX) and add them to the effect bank.

Edits are in-place value changes on the DLsE tree (see dlse.py), so the file layout never changes:
  - the effect id (root FXSerializableEffect field 1)
  - floats / colour alphas inside a parameter block: Param [38, BLOCK] -> ParamList -> slot INDEX

Bank update: sfx9999.ffxbnd(.dcx) gets f%07d.ffx entries (zlib, flags 0xC0 like the originals) and
sfxParameter.sfxparam gets a copy of the source effect's 0x40-byte record under the new id
(header: "sfxp", u32 5, u32 count, u32 0x20; records sorted by u32 id).

Usage: ffx_edit.py GAME_DIR OUT_BANK.ffxbnd.dcx
Builds the cigarette effects defined in RECIPES.
"""
import os
import re
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bnd4  # noqa: E402
import dlse  # noqa: E402


def block_slot(root, block, index):
    for node, _ in dlse.walk(root):
        if node.cls == "FXSerializableParam" and node.fields[:2] == [38, block] and node.children:
            return node.children[0].children[index]
    raise KeyError(f"block {block} not found")


def set_effect_id(d, root, new_id):
    struct.pack_into("<i", d, root.offset + 10 + 4, new_id)


def scale_floats(d, root, block, index, factor):
    """Multiply every dl_float32 value inside a slot (curve keys keep their times)."""
    for node, _ in dlse.walk(block_slot(root, block, index)):
        if node.cls == "FXSerializablePrimitive<dl_float32>":
            off = node.offset + 10
            struct.pack_into("<f", d, off, struct.unpack_from("<f", d, off)[0] * factor)


def color_alpha(d, root, block, index, fn):
    """Apply fn(alpha) to every RGBA key inside a slot."""
    for node, _ in dlse.walk(block_slot(root, block, index)):
        if "ColorRGBA" in node.cls:
            off = node.offset + 10 + 12
            struct.pack_into("<f", d, off, fn(struct.unpack_from("<f", d, off)[0]))


# new id: (source id, [(edit, block, slot, argument)], description)
RECIPES = {
    9101: (1601, [("alpha", 15000, 13, lambda a: 0.75),          # blink curve 0.75/0/0.75/0 -> steady
                  ("scale", 15000, 11, 0.6), ("scale", 15000, 12, 0.6)],
           "cigarette ember: 1601 without the blink, 60% size"),
    9102: (193, [("scale", 15001, 12, 0.7), ("scale", 15001, 16, 0.7),
                 ("alpha", 15001, 21, lambda a: a * 0.6)],
           "drag / exhale smoke: 193 at 70% size, 60% opacity"),
    9103: (193, [("scale", 15001, 12, 0.5), ("scale", 15001, 16, 0.5),
                 ("alpha", 15001, 21, lambda a: a * 0.35)],
           "wisp from the held cigarette: 193 at 50% size, 35% opacity"),
}


def build_effect(source, new_id, edits):
    d = bytearray(source)
    root = dlse.load(bytes(d))
    set_effect_id(d, root, new_id)
    for kind, block, index, arg in edits:
        if kind == "scale":
            scale_floats(d, root, block, index, arg)
        elif kind == "alpha":
            color_alpha(d, root, block, index, arg)
    return bytes(d)


def add_param_records(sfxparam, new_records):
    """new_records: {new_id: source_id}. Copies the source record, sorted insert.
    Works for sfxParameter (0x40-byte records) and sfxDebugParameter (8-byte records)."""
    magic, version, count, start = struct.unpack_from("<4sIII", sfxparam, 0)
    size = (len(sfxparam) - start) // count
    records = [sfxparam[start + size * i:start + size * (i + 1)] for i in range(count)]
    by_id = {struct.unpack_from("<I", r, 0)[0]: r for r in records}
    for new_id, src in new_records.items():
        if new_id in by_id:
            raise ValueError(f"effect id {new_id} already registered")
        r = bytearray(by_id[src])
        struct.pack_into("<I", r, 0, new_id)
        by_id[new_id] = bytes(r)
    ids = sorted(by_id)
    header = bytearray(sfxparam[:start])
    struct.pack_into("<I", header, 8, len(ids))
    return bytes(header) + b"".join(by_id[i] for i in ids)


def main(game, out_path):
    bank_path = os.path.join(game, "sfx", "sfx9999.ffxbnd.dcx")
    raw = open(bank_path, "rb").read()
    files = bnd4.read_bnd4(raw)
    by_id = {int(m.group(1)): f for f in files for m in [re.search(r"f(\d+)\.ffx$", f.name)] if m}
    prefix = next(f.name for f in files if f.name.endswith(".ffx")).rsplit("\\", 1)[0]
    param_files = [f for f in files if f.name.endswith(".sfxparam")]
    next_entry = max(f.id for f in files if f.name.endswith(".ffx")) + 1

    new_files = []
    for new_id, (src, edits, desc) in sorted(RECIPES.items()):
        if new_id in by_id:
            sys.exit(f"effect {new_id} already exists in the bank")
        data = build_effect(zlib.decompress(by_id[src].data), new_id, edits)
        new_files.append(bnd4.new_file(next_entry, f"{prefix}\\f{new_id:07d}.ffx", data, compress=True))
        next_entry += 1
        print(f"f{new_id:07d}.ffx  <- {src}: {desc}")

    for param_file in param_files:
        params = add_param_records(zlib.decompress(param_file.data), {i: r[0] for i, r in RECIPES.items()})
        param_file.data = zlib.compress(params, 9)
        param_file.usize = len(params)

    ffx_files = [f for f in files if f.name.endswith(".ffx")]
    other = [f for f in files if not f.name.endswith(".ffx")]
    out = bnd4.write_bnd4(raw, ffx_files + new_files + other)
    open(out_path, "wb").write(bnd4.dcx(out))
    print(f"wrote {out_path}: {len(ffx_files) + len(new_files)} effects, {len(param_files)} parameter files updated")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
