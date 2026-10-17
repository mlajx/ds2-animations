#!/usr/bin/env python3
"""Retarget an animation (from blender_export.py) onto the DS2 c0001 Morpheme rig and encode it.

Usage:
  retarget.py SOURCE.json OUT.nsa [--profile mixamo|unreal] [--ref REF.nsa] [--flver c0001.flv]

Source rigs are described by PROFILES: canonical bone names (Mixamo's, without "mixamorig:") map to
the rig's bones; end points a rig lacks (head top, fingertips, toe tip) are synthesised as a rest-pose
offset carried by the bone's rotation. The profile is auto-detected from the bone names.

Method:
  - DS2 reference pose = frame 0 of REF (default: the player Idle), in Morpheme space.
  - Axis map M: Blender world -> Morpheme world, from each skeleton's forward/left/up.
  - Rest alignment, top-down: each mapped DS2 bone is rotated so its aim direction (and, for
    "frame" bones, a secondary side direction) matches the source rest pose; twist otherwise
    comes from the DS2 reference pose.
  - Per frame: world_ds2 = M (R_src(t) R_src_rest^T) M^T aligned_ds2, then to local rotations.
    Root translation follows the source hips, scaled by leg length, then ground-fitted.
    Near the face, two-bone arm IK keeps hand-to-head contacts (face_contact_ik).
    Unmapped bones keep the reference local transform.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nsa  # noqa: E402
import rig  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REF = os.path.join(HERE, "..", "extracted", "c0001-anibnd", "a00_00_0000_Idle_untitled_9d2ebb5e.nsa")
DEFAULT_FLVER = os.path.join(HERE, "..", "extracted", "c0001-model", "c0001.flv")

# DS2 bone -> (canonical source bone, DS2 aim child, source aim child, side vector or None)
# side vectors: (DS2 from, DS2 to, source from, source to), positions of bone heads
HEAD_UP = np.array([1.0, 0.0, 0.0])        # DS2 Head bone axes, Morpheme bone space
HEAD_FORWARD = np.array([0.0, 1.0, 0.0])
MOUTH = np.array([0.010, 0.092, 0.0])      # FLVER dummy 255 on Head (face point), Morpheme bone space
SIDE_HIPS = ("R_Thigh", "L_Thigh", "RightUpLeg", "LeftUpLeg")
SIDE_CHEST = ("R_Clavicle", "L_Clavicle", "RightShoulder", "LeftShoulder")


def _hand(s, x):
    return (f"{s}_Finger1", f"{s}_Finger4", f"{x}HandIndex1", f"{x}HandPinky1")


MAPPING = {
    "Pelvis": ("Hips", "Spine", "Spine", SIDE_HIPS),
    "Spine": ("Spine1", "Spine1", "Spine2", SIDE_CHEST),
    "Spine1": ("Spine2", "Neck", "Neck", SIDE_CHEST),
    "Neck": ("Neck", "Head", "Head", SIDE_CHEST),
    "Head": ("Head", None, None, None),
}
for s, x in (("L", "Left"), ("R", "Right")):
    MAPPING.update({
        f"{s}_Clavicle": (f"{x}Shoulder", f"{s}_UpperArm", f"{x}Arm", None),
        f"{s}_UpperArm": (f"{x}Arm", f"{s}_Forearm", f"{x}ForeArm", None),
        f"{s}_Forearm": (f"{x}ForeArm", f"{s}_Hand", f"{x}Hand", None),
        f"{s}_Hand": (f"{x}Hand", f"{s}_Finger2", f"{x}HandMiddle1", _hand(s, x)),
        f"{s}_Thigh": (f"{x}UpLeg", f"{s}_Calf", f"{x}Leg", None),
        f"{s}_Calf": (f"{x}Leg", f"{s}_Foot", f"{x}Foot", None),
        f"{s}_Foot": (f"{x}Foot", f"{s}_Toe0", f"{x}ToeBase", None),
        f"{s}_Toe0": (f"{x}ToeBase", f"{s}_Toe0Nub", f"{x}Toe_End", None),
    })
    for i, finger in enumerate(("Thumb", "Index", "Middle", "Ring", "Pinky")):
        MAPPING.update({
            f"{s}_Finger{i}": (f"{x}Hand{finger}1", f"{s}_Finger{i}1", f"{x}Hand{finger}2", None),
            f"{s}_Finger{i}1": (f"{x}Hand{finger}2", f"{s}_Finger{i}2", f"{x}Hand{finger}3", None),
            f"{s}_Finger{i}2": (f"{x}Hand{finger}3", None, None, None),
        })
# Thumb in DS2 is Finger0/Finger01/Finger02 (Mixamo Thumb1..3), others FingerN/FingerN1/FingerN2.
for s, x in (("L", "Left"), ("R", "Right")):
    MAPPING[f"{s}_Finger0"] = (f"{x}HandThumb1", f"{s}_Finger01", f"{x}HandThumb2", None)
    MAPPING[f"{s}_Finger01"] = (f"{x}HandThumb2", f"{s}_Finger02", f"{x}HandThumb3", None)
    MAPPING[f"{s}_Finger02"] = (f"{x}HandThumb3", None, None, None)
    MAPPING.pop(f"{s}_Finger00", None)
    MAPPING.pop(f"{s}_Finger01" + "x", None)


# ---------------------------------------------------------------- source rigs
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")


def _unreal_names():
    names = {"Hips": "pelvis", "Spine": "spine_01", "Spine1": "spine_03", "Spine2": "spine_05",
             "Neck": "neck_02", "Head": "head"}  # DS2 has one neck bone: use the one next to the head
    for x, s in (("Left", "l"), ("Right", "r")):
        names.update({f"{x}Shoulder": f"clavicle_{s}", f"{x}Arm": f"upperarm_{s}", f"{x}ForeArm": f"lowerarm_{s}",
                      f"{x}Hand": f"hand_{s}", f"{x}UpLeg": f"thigh_{s}", f"{x}Leg": f"calf_{s}",
                      f"{x}Foot": f"foot_{s}", f"{x}ToeBase": f"ball_{s}"})
        for f in FINGERS:
            for i in (1, 2, 3):
                names[f"{x}Hand{f}{i}"] = f"{f.lower()}_0{i}_{s}"
    return names


def _unreal_synth():
    # canonical end point: (bone it moves with, kind, helper bone)
    synth = {"HeadTop_End": ("Head", "up", "Hips")}
    for x in ("Left", "Right"):
        synth[f"{x}Toe_End"] = (f"{x}ToeBase", "extend_flat", f"{x}Foot")
        for f in FINGERS:
            synth[f"{x}Hand{f}4"] = (f"{x}Hand{f}3", "extend", f"{x}Hand{f}2")
    return synth


PROFILES = {
    # Mixamo FBX: every canonical bone exists as "mixamorig:<name>"
    "mixamo": {"prefix": "mixamorig:", "names": {}, "synth": {}},
    # Unreal / Epic-style skeleton (pelvis, spine_01..05, clavicle_l, upperarm_l, index_01_l, ball_l, ...)
    "unreal": {"prefix": "", "names": _unreal_names(), "synth": _unreal_synth()},
}


def detect_profile(bone_names):
    if "mixamorig:Hips" in bone_names:
        return "mixamo"
    if {"pelvis", "spine_01", "upperarm_l", "thigh_l"} <= set(bone_names):
        return "unreal"
    raise SystemExit("unknown source rig: add a profile to PROFILES in retarget.py")


class Source:
    """Source animation with canonical bone names. Positions/rotations are Blender world space."""

    def __init__(self, data, profile=None):
        self.profile = profile or detect_profile(data["bones"])
        p = PROFILES[self.profile]
        self.prefix, self.names, self.synth = p["prefix"], p["names"], p["synth"]
        self.rate = float(data["rate"])
        self.rest = data["rest"]
        self.samples = data["samples"]
        self._synth_rest = {}
        for name, (bone, kind, helper) in self.synth.items():
            head = self._rest_head(bone)
            if kind == "up":
                v = np.array([0.0, 0.0, 1.0]) * 0.3 * np.linalg.norm(head - self._rest_head(helper))
            elif kind == "extend":
                v = head - self._rest_head(helper)
            elif kind == "extend_flat":
                v = head - self._rest_head(helper)
                v = np.array([v[0], v[1], 0.0])
            self._synth_rest[name] = v

    def bone(self, name):
        return self.prefix + self.names.get(name, name)

    def _rest_head(self, name):
        return np.array(self.rest[self.bone(name)]["head"])

    def frames(self):
        return len(self.samples)

    def rot(self, f, name):
        """f = None for the rest pose."""
        pose = self.rest if f is None else self.samples[f]
        return np.array(pose[self.bone(name)]["rot"])

    def pos(self, f, name):
        pose = self.rest if f is None else self.samples[f]
        if name in self._synth_rest:
            bone = self.synth[name][0]
            carried = self.rot(f, bone) @ self.rot(None, bone).T @ self._synth_rest[name]
            return np.array(pose[self.bone(bone)]["head"]) + carried
        return np.array(pose[self.bone(name)]["head"])


# ---------------------------------------------------------------- math helpers
def quat_to_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def mat_to_quat(m):
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def unit(v):
    return v / np.linalg.norm(v)


def rotation_between(a, b):
    a, b = unit(a), unit(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -0.999999:
        axis = unit(np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0]))
        return 2 * np.outer(axis, axis) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


def basis(primary, secondary):
    x = unit(primary)
    z = unit(np.cross(x, secondary))
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


def orthonormalise(m):
    u, _, vt = np.linalg.svd(m)
    r = u @ vt
    return r


# ---------------------------------------------------------------- skeleton helpers
class Ds2Skeleton:
    def __init__(self, ref_path, flver_path, frame=0):
        anim = nsa.parse(open(ref_path, "rb").read())
        pos, rot = nsa.decode(anim)
        self.names = rig.RIG_NAMES
        self.index = {n: i for i, n in enumerate(self.names)}
        self.parents = rig.rig_parents(open(flver_path, "rb").read())
        self.local_pos = [np.array(p) for p in pos[frame]]
        self.local_rot = [quat_to_mat(q) for q in rot[frame]]

    def fk(self, world_rot_override=None, local_pos=None):
        """World rotations and head positions. world_rot_override: {index: world 3x3}."""
        local_pos = local_pos or self.local_pos
        wr, wp = [None] * len(self.names), [None] * len(self.names)
        for i in range(len(self.names)):
            p = self.parents[i]
            if p < 0:
                wr[i], wp[i] = self.local_rot[i], local_pos[i]
            else:
                wr[i] = wr[p] @ self.local_rot[i]
                wp[i] = wp[p] + wr[p] @ local_pos[i]
            if world_rot_override and i in world_rot_override:
                wr[i] = world_rot_override[i]
        return wr, wp


def _frame(fwd, left, up):
    up = unit(up)
    left = unit(left - np.dot(left, up) * up)
    fwd = unit(fwd - np.dot(fwd, up) * up - np.dot(fwd, left) * left)
    return np.column_stack([fwd, left, up])


def axis_map(ds2, src):
    """3x3 M mapping Blender world vectors to Morpheme world vectors (may be a reflection)."""
    _, wp = ds2.fk()
    g = lambda n: wp[ds2.index[n]]
    ds2_frame = _frame(g("L_Toe0Nub") - g("L_Foot"), g("L_Thigh") - g("R_Thigh"), np.array([0.0, 0.0, 1.0]))
    m = lambda n: src.pos(None, n)
    src_frame = _frame(m("LeftToe_End") - m("LeftFoot"), m("LeftUpLeg") - m("RightUpLeg"), np.array([0.0, 0.0, 1.0]))
    return ds2_frame @ src_frame.T


def character_forward(ds2):
    """DS2 character forward (Morpheme world, horizontal)."""
    _, wp = ds2.fk()
    g = lambda n: wp[ds2.index[n]]
    return _frame(g("L_Toe0Nub") - g("L_Foot"), g("L_Thigh") - g("R_Thigh"), np.array([0.0, 0.0, 1.0]))[:, 0]


def retarget(src, ds2):
    M = axis_map(ds2, src)
    mpos = lambda f, n: M @ src.pos(f, n)
    mrot = lambda f, n: src.rot(f, n)

    # rest alignment, top-down (rig order is parent-before-child)
    aligned = {}
    for i, name in enumerate(ds2.names):
        if name not in MAPPING:
            continue
        mix_bone, aim_d, aim_m, side = MAPPING[name]
        wr, wp = ds2.fk(aligned)
        current = wr[i]
        if name == "Head":
            # the DS2 head has no child joint: use its own axes. In Morpheme bone space the head's
            # +X runs up through the crown and +Y out of the face (FLVER dummy 255, the face point,
            # sits at local (0.010, 0.092, 0)). Source: Head -> HeadTop_End, facing the character's front.
            p_m = mpos(None, "HeadTop_End") - mpos(None, "Head")
            s_m = character_forward(ds2)
            correction = basis(p_m, s_m) @ basis(current @ HEAD_UP, current @ HEAD_FORWARD).T
            aligned[i] = correction @ current
            continue
        if aim_d is None:
            aligned[i] = current
            continue
        p_d = wp[ds2.index[aim_d]] - wp[i]
        p_m = mpos(None, aim_m) - mpos(None, mix_bone)
        if side:
            s_d = wp[ds2.index[side[1]]] - wp[ds2.index[side[0]]]
            s_m = mpos(None, side[3]) - mpos(None, side[2])
            correction = basis(p_m, s_m) @ basis(p_d, s_d).T
        else:
            correction = rotation_between(p_d, p_m)
        aligned[i] = correction @ current

    # leg-length scale for the root translation
    _, wp = ds2.fk()
    g = lambda n: wp[ds2.index[n]]
    leg_d = np.linalg.norm(g("L_Calf") - g("L_Thigh")) + np.linalg.norm(g("L_Foot") - g("L_Calf"))
    leg_m = (np.linalg.norm(mpos(None, "LeftLeg") - mpos(None, "LeftUpLeg")) +
             np.linalg.norm(mpos(None, "LeftFoot") - mpos(None, "LeftLeg")))
    scale = leg_d / leg_m
    root = ds2.index["Root"]
    pelvis_offset = g("Pelvis") - g("Root")  # zero for c0001, kept for safety

    ref_ankle = min(g("L_Foot")[2], g("R_Foot")[2])
    body_scale = g("Head")[2] / mpos(None, "Head")[2]
    positions, rotations = [], []
    for f in range(src.frames()):
        world = {}
        for i, name in enumerate(ds2.names):
            if name not in MAPPING:
                continue
            mb = MAPPING[name][0]
            delta = M @ (mrot(f, mb) @ mrot(None, mb).T) @ M.T
            world[i] = orthonormalise(delta @ aligned[i])
        # world rotations: unmapped bones keep their reference local rotation
        wr = [None] * len(ds2.names)
        for i in range(len(ds2.names)):
            p = ds2.parents[i]
            parent = wr[p] if p >= 0 else np.eye(3)
            wr[i] = world[i] if i in world else parent @ ds2.local_rot[i]
        local_pos = [np.array(p) for p in ds2.local_pos]
        local_pos[root] = mpos(f, "Hips") * scale - pelvis_offset
        face_contact_ik(ds2, wr, local_pos, f, mpos, body_scale)
        local_rot = []
        for i in range(len(ds2.names)):
            p = ds2.parents[i]
            parent = wr[p] if p >= 0 else np.eye(3)
            local_rot.append(mat_to_quat(parent.T @ wr[i]))
        local_pos = [tuple(p) for p in local_pos]
        positions.append(local_pos)
        rotations.append(local_rot)

    # ground fit: a source hip bone may sit above its thigh joints (Mixamo), DS2's Root does not, so
    # move the root vertically until the lowest ankle over the clip matches the reference pose
    lowest = min(min(wp[ds2.index["L_Foot"]][2], wp[ds2.index["R_Foot"]][2])
                 for wp in (pose_positions(ds2, p, r) for p, r in zip(positions, rotations)))
    dz = ref_ankle - lowest
    for local_pos in positions:
        x, y, z = local_pos[root]
        local_pos[root] = (x, y, z + dz)
    print(f"ground fit: root moved {dz * 100:+.1f} cm")
    return positions, rotations, M, scale


CONTACT_NEAR = 0.15   # source fingertip-to-head distance (DS2 metres) at which the face IK is fully on
CONTACT_FAR = 0.30    # ... and fully off


def world_positions(ds2, wr, local_pos):
    wp = [None] * len(ds2.names)
    for i in range(len(ds2.names)):
        p = ds2.parents[i]
        wp[i] = local_pos[i] if p < 0 else wp[p] + wr[p] @ local_pos[i]
    return wp


def face_contact_ik(ds2, wr, local_pos, f, mpos, body_scale):
    """Near the face, put each DS2 fingertip where the source's is relative to the head (scaled), so hand
    contacts survive the different arm/neck proportions. Two-bone IK on upper arm + forearm keeps the
    elbow on its side; the hand keeps its world rotation. Fades out with distance from the head."""
    head = ds2.index["Head"]
    for s, x in (("R", "Right"), ("L", "Left")):
        tip_m = mpos(f, f"{x}HandIndex3")
        dist = np.linalg.norm(tip_m - mpos(f, "Head")) * body_scale
        w = min(1.0, max(0.0, (CONTACT_FAR - dist) / (CONTACT_FAR - CONTACT_NEAR)))
        w = w * w * (3 - 2 * w)
        if w <= 0:
            continue
        wp = world_positions(ds2, wr, local_pos)
        sh, el, wr_i, tip = (ds2.index[n] for n in (f"{s}_UpperArm", f"{s}_Forearm", f"{s}_Hand", f"{s}_Finger12"))
        # source fingertip in its head frame == DS2 fingertip in the DS2 head frame (head rotations match)
        target_tip = wp[head] + (tip_m - mpos(f, "Head")) * body_scale
        target_tip = (1 - w) * wp[tip] + w * target_tip
        target_wrist = target_tip - (wp[tip] - wp[wr_i])

        S, E, W = wp[sh], wp[el], wp[wr_i]
        a, b = np.linalg.norm(E - S), np.linalg.norm(W - E)
        to_t = target_wrist - S
        L = min(max(np.linalg.norm(to_t), abs(a - b) + 1e-4), a + b - 1e-4)
        d = unit(to_t)
        bend = (E - S) - ((E - S) @ d) * d               # keep the elbow on its current side
        if np.linalg.norm(bend) < 1e-6:
            bend = np.cross(d, [0.0, 0.0, 1.0])
        bend = unit(bend)
        cos_a = (a * a + L * L - b * b) / (2 * a * L)
        E2 = S + a * (cos_a * d + math.sqrt(max(0.0, 1 - cos_a * cos_a)) * bend)
        W2 = S + L * d

        hand_world = wr[wr_i]
        r_upper = rotation_between(E - S, E2 - S)
        wr[sh] = r_upper @ wr[sh]
        fore = r_upper @ wr[el]
        wr[el] = rotation_between(r_upper @ (W - E), W2 - E2) @ fore
        wr[wr_i] = hand_world
        # fingers and weapon bone keep their world rotation through the hand


def pose_positions(ds2, positions, rotations):
    """World bone head positions for one frame of local channels."""
    wr, wp = [None] * len(ds2.names), [None] * len(ds2.names)
    for i in range(len(ds2.names)):
        p = ds2.parents[i]
        rot = quat_to_mat(rotations[i])
        pos = np.array(positions[i])
        if p < 0:
            wr[i], wp[i] = rot, pos
        else:
            wr[i] = wr[p] @ rot
            wp[i] = wp[p] + wr[p] @ pos
    return wp


def report(src, ds2, positions, rotations, M):
    """Per-frame direction error of mapped segments + a few sanity distances."""
    errors = []
    lowest_ankle, hand_head = [], []
    for f in range(src.frames()):
        local_pos = [np.array(p) for p in positions[f]]
        ds2_rot = [quat_to_mat(q) for q in rotations[f]]
        wr, wp = [None] * len(ds2.names), [None] * len(ds2.names)
        for i in range(len(ds2.names)):
            p = ds2.parents[i]
            if p < 0:
                wr[i], wp[i] = ds2_rot[i], local_pos[i]
            else:
                wr[i] = wr[p] @ ds2_rot[i]
                wp[i] = wp[p] + wr[p] @ local_pos[i]
        for name, (mb, aim_d, aim_m, _side) in MAPPING.items():
            if aim_d is None:
                continue
            d = unit(wp[ds2.index[aim_d]] - wp[ds2.index[name]])
            m = unit(M @ (src.pos(f, aim_m) - src.pos(f, mb)))
            errors.append((math.degrees(math.acos(max(-1, min(1, float(d @ m))))), name, f))
        lowest_ankle.append(min(wp[ds2.index["L_Foot"]][2], wp[ds2.index["R_Foot"]][2]))
        hand_head.append(min(np.linalg.norm(wp[ds2.index[h]] - wp[ds2.index["Head"]]) for h in ("L_Finger11", "R_Finger11")))
    errors.sort(reverse=True)
    mean = sum(e[0] for e in errors) / len(errors)
    print(f"segment direction error vs source: mean {mean:.2f} deg, max {errors[0][0]:.2f} deg ({errors[0][1]} frame {errors[0][2]})")
    worst = {}
    for e, n, _f in errors:
        worst[n] = max(worst.get(n, 0), e)
    print("  worst bones:", ", ".join(f"{n} {e:.1f}" for n, e in sorted(worst.items(), key=lambda kv: -kv[1])[:6]))
    print(f"ankle height: min {min(lowest_ankle):.3f} m, max of per-frame lowest {max(lowest_ankle):.3f} m")
    print(f"closest index finger to head: {min(hand_head):.3f} m")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source_json")
    ap.add_argument("out_nsa")
    ap.add_argument("--profile", choices=sorted(PROFILES))
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--flver", default=DEFAULT_FLVER)
    args = ap.parse_args()

    src = Source(json.load(open(args.source_json)), args.profile)
    ds2 = Ds2Skeleton(args.ref, args.flver)
    positions, rotations, M, scale = retarget(src, ds2)
    print(f"profile {src.profile}, axis map det {np.linalg.det(M):+.0f}, root scale {scale:.3f}, "
          f"{len(positions)} frames @ {src.rate} Hz")
    report(src, ds2, positions, rotations, M)
    data = nsa.write(positions, rotations, src.rate)
    open(args.out_nsa, "wb").write(data)
    back = nsa.parse(data)
    print(f"wrote {args.out_nsa}: {len(data)} bytes, {back.sections[0].num_frames} frames, {back.duration:.2f} s, "
          f"{len(back.sampled_quat_map)} animated rotation channels")


if __name__ == "__main__":
    main()
