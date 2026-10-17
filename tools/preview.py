#!/usr/bin/env python3
"""Stick-figure comparison of a source export and an encoded DS2 .nsa (front + side views).

Usage: preview.py SOURCE.json ANIM.nsa OUT.png [FRAME ...]
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nsa  # noqa: E402
import retarget  # noqa: E402

src_path, nsa_path, out = sys.argv[1:4]
src = retarget.Source(json.load(open(src_path)))
ds2 = retarget.Ds2Skeleton(retarget.DEFAULT_REF, retarget.DEFAULT_FLVER)
M = retarget.axis_map(ds2, src)
pos, rot = nsa.decode(nsa.parse(open(nsa_path, "rb").read()))
frames = [int(f) for f in sys.argv[4:]] or list(np.linspace(0, len(pos) - 1, 6).astype(int))

# scale the source to DS2 size (head height) so the overlay is comparable
_, wp0 = ds2.fk()
scale = wp0[ds2.index["Head"]][2] / (M @ src.pos(None, "Head"))[2]

chains = [["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End"]]
for x in ("Left", "Right"):
    chains += [["Spine2", f"{x}Shoulder", f"{x}Arm", f"{x}ForeArm", f"{x}Hand"],
               ["Hips", f"{x}UpLeg", f"{x}Leg", f"{x}Foot", f"{x}ToeBase", f"{x}Toe_End"]]
    chains += [[f"{x}Hand"] + [f"{x}Hand{f}{i}" for i in range(1, 5)] for f in retarget.FINGERS]

fig, axes = plt.subplots(2, len(frames), figsize=(3.2 * len(frames), 7.5), squeeze=False)
for col, f in enumerate(frames):
    wp = retarget.pose_positions(ds2, pos[f], rot[f])
    for row, (ax_h, label) in enumerate(((0, "front"), (1, "side"))):
        ax = axes[row][col]
        for chain in chains:
            pts = np.array([M @ src.pos(f, n) * scale for n in chain])
            ax.plot(pts[:, ax_h], pts[:, 2], color="#bbbbbb", lw=3, zorder=1)
        for i, p in enumerate(ds2.parents):
            if p < 0 or ds2.names[i] == "Root" or ds2.names[p] in ("Character", "Master"):
                continue
            a, b = wp[p], wp[i]
            side = ds2.names[i][:2]
            color = "#d1495b" if side == "L_" else "#2e86ab" if side == "R_" else "#333333"
            ax.plot([a[ax_h], b[ax_h]], [a[2], b[2]], color=color, lw=1.4, zorder=2)
        ax.set_aspect("equal")
        ax.set_xlim(-0.8, 0.8)
        ax.set_ylim(-0.05, 1.9)
        ax.axhline(0, color="#999999", lw=0.5)
        ax.set_title(f"frame {f} ({f / src.rate:.1f}s) {label}", fontsize=8)
        ax.tick_params(labelsize=6)
fig.suptitle("grey = source (axis-mapped, scaled to DS2 height), colour = DS2 decoded from .nsa (red L, blue R)",
             fontsize=9)
fig.tight_layout()
fig.savefig(out, dpi=90)
print("wrote", out)
