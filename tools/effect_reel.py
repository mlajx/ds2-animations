#!/usr/bin/env python3
"""Build a test TAE where Prostration (74010130) shows candidate effects one after another.

Embers spawn at the right hand (dummy 1) and smoke at the face (dummy 255), each in its own time
slot, so a single in-game run shows every candidate. Writes OUT_TAE and OUT_TAE minus extension + "_reel.txt" (slot sheet).

Usage: effect_reel.py IN_TAE OUT_TAE
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tae  # noqa: E402

ANIM = 74010130
LENGTH_FRAMES = 537           # 17.9 s at 30 fps
DUMMY_HAND, DUMMY_FACE = 1, 255
# shortlisted from build/sfx_catalog by texture: ember = single small-glow texture, smoke = wisp textures
EMBERS = [1601, 1700, 3320, 3783, 3907, 3962]
SMOKE = [107, 23, 193, 238, 301, 651, 654, 923, 1656, 3010, 3697, 3800, 105, 176]


def main(src, dst):
    events, sheet = [], ["Prostration effect reel (times from the start of the gesture)", ""]
    sheet.append("EMBER candidates at the right hand (each shown 2.5 s):")
    for k, fx in enumerate(EMBERS):
        start = 0.5 + 2.8 * k
        events.append(tae.sfx_event(start, start + 2.5, fx, DUMMY_HAND))
        sheet.append(f"  E{k + 1}  {start:5.1f}-{start + 2.5:4.1f} s   effect {fx}")
    sheet += ["", "SMOKE candidates at the face (each spawned for 0.6 s, may linger):"]
    for k, fx in enumerate(SMOKE):
        start = 0.5 + 1.2 * k
        events.append(tae.sfx_event(start, start + 0.6, fx, DUMMY_FACE))
        sheet.append(f"  S{k + 1:<2} {start:5.1f} s        effect {fx}")
    d = open(src, "rb").read()
    d = bytearray(d)
    import struct
    struct.pack_into("<I", d, tae.length_field(d, ANIM), LENGTH_FRAMES)
    d = tae.add_events(bytes(d), ANIM, events, tae.SFX_GROUP)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(d)
    sheet_path = os.path.splitext(dst)[0] + "_reel.txt"
    open(sheet_path, "w").write("\n".join(sheet) + "\n")
    print("\n".join(sheet))
    print(f"\nwrote {dst} ({len(events)} events) and {os.path.normpath(sheet_path)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
