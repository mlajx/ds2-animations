#!/usr/bin/env python3
"""Catalog DS2 effects: which textures/models each FFX uses, and contact sheets of the textures.

In the DLsE effect tree an inline FXSerializableParam of type 40 holds a texture id
(sNNNNNN.tpf in sfx9999res.ffxbnd) and type 41 a model id (sNNNNNN.flv).

Usage: sfx_catalog.py GAME_DIR OUT_DIR
Writes OUT_DIR/ffx_refs.json ({ffx id: {"textures": [...], "models": [...]}}) and
OUT_DIR/sheet_NN.png (each texture labelled with its id and the effects using it).
"""
import io
import json
import os
import re
import struct
import sys
import zlib

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bnd4  # noqa: E402
import dlse  # noqa: E402

PARAM_TEXTURE = 40
PARAM_MODEL = 41


def references(ffx):
    textures, models = set(), set()
    for node, _ in dlse.walk(dlse.load(ffx)):
        if node.cls == "FXSerializableParam" and len(node.fields) >= 2 and not node.children:
            if node.fields[0] == PARAM_TEXTURE:
                textures.add(node.fields[1])
            elif node.fields[0] == PARAM_MODEL:
                models.add(node.fields[1])
    return sorted(textures - {0, -1}), sorted(models - {0, -1})


def main(game, out):
    os.makedirs(out, exist_ok=True)
    ffx = bnd4.read_bnd4(open(os.path.join(game, "sfx", "sfx9999.ffxbnd.dcx"), "rb").read())
    res = bnd4.read_bnd4(open(os.path.join(game, "sfx", "sfx9999res.ffxbnd"), "rb").read())
    uses = {}
    unparsed = 0
    for f in ffx:
        m = re.search(r"f(\d+)\.ffx$", f.name)
        if not m:
            continue
        textures, models = references(zlib.decompress(f.data))
        uses[int(m.group(1))] = {"textures": textures, "models": models}
    json.dump(uses, open(os.path.join(out, "ffx_refs.json"), "w"))

    by_texture = {}
    for eid, refs in uses.items():
        for t in refs["textures"]:
            by_texture.setdefault(t, []).append(eid)
    tiles = []
    for f in res:
        m = re.search(r"s(\d+)\.tpf$", f.name)
        if not m:
            continue
        tid = int(m.group(1))
        data = zlib.decompress(f.data)
        dds = data.find(b"DDS ")
        try:
            img = Image.open(io.BytesIO(data[dds:])).convert("RGBA")
        except Exception:
            continue
        img.thumbnail((128, 128))
        tile = Image.new("RGB", (136, 170), (40, 40, 40))
        bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        tile.paste(Image.alpha_composite(bg, img).convert("RGB"), (4, 4))
        users = sorted(by_texture.get(tid, []))
        draw = ImageDraw.Draw(tile)
        draw.text((4, 134), f"t{tid} ({len(users)} fx)", fill=(255, 255, 0))
        draw.text((4, 150), ",".join(map(str, users[:4])), fill=(180, 220, 255))
        tiles.append(tile)
    per = 40
    for s in range(0, len(tiles), per):
        sheet = Image.new("RGB", (136 * 8, 170 * 5), (20, 20, 20))
        for k, tile in enumerate(tiles[s:s + per]):
            sheet.paste(tile, ((k % 8) * 136, (k // 8) * 170))
        sheet.save(os.path.join(out, f"sheet_{s // per:02d}.png"))
    print(f"{len(uses)} effects parsed, {len(by_texture)} textures referenced, "
          f"{len(tiles)} textures rendered into {(len(tiles) + per - 1) // per} sheets")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
