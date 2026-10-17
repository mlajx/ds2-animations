#!/usr/bin/env python3
"""Build the mod payload (the files that go in Game\\DS2AnimMod) from the slot list below.

Every slot replaces one shipped animation. Shared files are always rebuilt from the untouched
originals in extracted/, so slots never undo each other:
  morpheme4/chr/c0001.anibnd.dcx   all replaced .nsa files + Morpheme network durations (anibnd.py)
  timeact/chr/c000100_pl.tae       each slot's length (30 fps frames) + its effect events (tae.py)
  sfx/sfx9999.ffxbnd.dcx           custom effects (ffx_edit.py)          - only if a slot uses effects
  model/chr/c0001.bnd              extra dummy polys (flver_dummies.py)  - only if a slot uses effects
  menu/text/<lang>/*.fmg           renamed gestures, all languages (gesture_text.py RENAMES)
  menu/tex/icon/IC_00<id>.tpf      gesture menu icons (gesture_icons.py ICONS)

Usage: build_mod.py GAME_DIR OUT_DIR        then: make -C mod package PAYLOAD=../OUT_DIR
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import anibnd  # noqa: E402
import bnd4  # noqa: E402
import cigarette_timeline  # noqa: E402
import ffx_edit  # noqa: E402
import ds2unpack  # noqa: E402
import flver_dummies  # noqa: E402
import gesture_icons  # noqa: E402
import gesture_text  # noqa: E402
import tae  # noqa: E402

ROOT = os.path.join(HERE, "..")
EXTRACTED = os.path.join(ROOT, "extracted")

# name: substring of the shipped .nsa to replace; tae: its TimeAct id (aXX_YY_ZZZZ -> XXYYZZZZ);
# nsa: the retargeted animation; events: optional [(start frame @30fps, end frame, effect, dummy, note)]
SLOTS = [
    {"name": "a74_01_0130_Pray", "tae": 74010130, "label": "Prostration -> smoking",
     "nsa": "build/smoking/a74_01_0130_Smoking.nsa", "events": cigarette_timeline.TIMELINE},
    {"name": "a74_01_0040_Welcome", "tae": 74010040, "label": "Welcome -> Master Chief dance",
     "nsa": "build/chief/a74_01_0040_Chief.nsa"},
]


def main(game, out):
    anim_src = open(os.path.join(EXTRACTED, "morpheme4/chr/c0001.anibnd.dcx"), "rb").read()
    tae_data = bytearray(open(os.path.join(EXTRACTED, "timeact/chr/c000100_pl.tae"), "rb").read())
    anim = anim_src
    for slot in SLOTS:
        nsa_data = open(os.path.join(ROOT, slot["nsa"]), "rb").read()
        print(f"[{slot['label']}]")
        anim = anibnd.replace(anim, slot["name"], nsa_data)
        (duration,) = struct.unpack_from("<f", nsa_data, 0x28)
        frames = round(duration * 30)
        struct.pack_into("<I", tae_data, tae.length_field(tae_data, slot["tae"]), frames)
        print(f"  TAE {slot['tae']}: length {frames} frames ({duration:.2f} s)")
        if slot.get("events"):
            events = [tae.sfx_event(a / 30, b / 30, fx, dummy) for a, b, fx, dummy, _ in slot["events"]]
            tae_data = bytearray(tae.add_events(bytes(tae_data), slot["tae"], events, tae.SFX_GROUP))
            print(f"  TAE {slot['tae']}: {len(events)} effect events")

    def write(rel, data):
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(data)
        print(f"wrote {path} ({len(data)} bytes)")

    write("morpheme4/chr/c0001.anibnd.dcx", bnd4.dcx(anim))
    write("timeact/chr/c000100_pl.tae", bytes(tae_data))
    if any(slot.get("events") for slot in SLOTS):
        for sub in ("sfx", "model/chr"):
            os.makedirs(os.path.join(out, sub), exist_ok=True)
        ffx_edit.main(game, os.path.join(out, "sfx", "sfx9999.ffxbnd.dcx"))
        flver_dummies.main(os.path.join(EXTRACTED, "model/chr/c0001.bnd"), os.path.join(out, "model/chr/c0001.bnd"))

    print("[gesture names]")
    gesture_text.build(game, out)
    print("[gesture icons]")
    icon_dir = os.path.join(EXTRACTED, "menu", "tex", "icon")
    os.makedirs(icon_dir, exist_ok=True)
    archive = ds2unpack.Archive(game, "GameData")
    for target, (base, _painter, _label) in gesture_icons.ICONS.items():
        for gid in (target, base):
            entry = archive.entries[ds2unpack.path_hash(f"/menu/tex/icon/IC_{gid:010d}.tpf")]
            open(os.path.join(icon_dir, f"IC_{gid:010d}.tpf"), "wb").write(archive.read(entry))
    gesture_icons.main(icon_dir, os.path.join(out, "menu", "tex", "icon"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
