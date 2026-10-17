#!/usr/bin/env python3
"""Face-direction error vs the source and fingertip-to-mouth distance for retargeted .nsa files.

Usage: check_head.py SOURCE.json ANIM.nsa [ANIM.nsa ...]
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nsa  # noqa: E402
import retarget as rt  # noqa: E402

src = rt.Source(json.load(open(sys.argv[1])))
ds2 = rt.Ds2Skeleton(rt.DEFAULT_REF, rt.DEFAULT_FLVER)
M = rt.axis_map(ds2, src)
H = ds2.index["Head"]
forward = rt.character_forward(ds2)
tips = [ds2.index[n] for n in ("R_Finger12", "R_Finger22", "L_Finger12", "L_Finger22")]


def ang(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, a @ b / np.linalg.norm(a) / np.linalg.norm(b)))))


for path in sys.argv[2:]:
    pos, rot = nsa.decode(nsa.parse(open(path, "rb").read()))
    face_err, mouth = [], []
    for f in range(len(pos)):
        wr, wp = [None] * 58, [None] * 58
        for i in range(58):
            p = ds2.parents[i]
            r = rt.quat_to_mat(rot[f][i])
            if p < 0:
                wr[i], wp[i] = r, np.array(pos[f][i])
            else:
                wr[i], wp[i] = wr[p] @ r, wp[p] + wr[p] @ np.array(pos[f][i])
        d = M @ (src.rot(f, "Head") @ src.rot(None, "Head").T) @ M.T
        face_err.append(ang(wr[H] @ rt.HEAD_FORWARD, d @ forward))
        m = wp[H] + wr[H] @ rt.MOUTH
        mouth.append(min(np.linalg.norm(wp[t] - m) for t in tips))
    best = int(np.argmin(mouth))
    print(f"{os.path.basename(path)}: face error {np.mean(face_err):.1f} deg (max {np.max(face_err):.1f}); "
          f"closest fingertip-to-mouth {mouth[best] * 100:.1f} cm at {best / src.rate:.2f} s")
