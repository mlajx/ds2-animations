#!/usr/bin/env python3
"""Write the cigarette effect events into Prostration's TAE entry (74010130).

Frame numbers are the Mixamo clip's 30 fps frames. Dummies 900/901 come from flver_dummies.py,
effects 9101-9103 from ffx_edit.py, 255 is the shipped face dummy.

Usage: cigarette_timeline.py IN_TAE OUT_TAE
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tae  # noqa: E402

ANIM = 74010130
LENGTH_FRAMES = 537
EMBER, DRAG_SMOKE, WISP = 9101, 9102, 9103
HAND_TIP, MOUTH_TIP, FACE = 900, 901, 255


def s(frame):
    return frame / 30.0


# (start frame, end frame, effect, dummy, what)
TIMELINE = [
    (72, 115, EMBER, HAND_TIP, "lit cigarette in the right hand"),
    (115, 270, EMBER, MOUTH_TIP, "cigarette in the mouth"),
    (234, 252, DRAG_SMOKE, MOUTH_TIP, "drag: smoke from the cigarette tip"),
    (270, 294, DRAG_SMOKE, FACE, "exhale after taking it out"),
    (270, 355, EMBER, HAND_TIP, "back in the hand"),
    (270, 355, WISP, HAND_TIP, "smoke rising from the held cigarette"),
]


def main(src, dst):
    d = bytearray(open(src, "rb").read())
    struct.pack_into("<I", d, tae.length_field(d, ANIM), LENGTH_FRAMES)
    events = [tae.sfx_event(s(a), s(b), fx, dummy) for a, b, fx, dummy, _ in TIMELINE]
    out = tae.add_events(bytes(d), ANIM, events, tae.SFX_GROUP)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(out)
    for a, b, fx, dummy, what in TIMELINE:
        print(f"  frames {a:3}-{b:3} ({s(a):5.2f}-{s(b):5.2f} s)  effect {fx} @ dummy {dummy}: {what}")
    print("wrote", dst)


if __name__ == "__main__":
    main(*sys.argv[1:3])
