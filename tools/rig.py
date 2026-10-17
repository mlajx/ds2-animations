"""DS2 player (c0001) Morpheme rig: channel order from c0001.nmb, parents from c0001.flv."""
import re
import struct

RIG_NAMES = (
    "Character Master Root Pelvis Spine Spine1 Neck Head "
    "L_Clavicle L_UpperArm L_Forearm L_Hand L_Finger0 L_Finger01 L_Finger02 L_Finger1 L_Finger11 L_Finger12 "
    "L_Finger2 L_Finger21 L_Finger22 L_Finger3 L_Finger31 L_Finger32 L_Finger4 L_Finger41 L_Finger42 L_Weapon "
    "R_Clavicle R_UpperArm R_Forearm R_Hand R_Finger0 R_Finger01 R_Finger02 R_Finger1 R_Finger11 R_Finger12 "
    "R_Finger2 R_Finger21 R_Finger22 R_Finger3 R_Finger31 R_Finger32 R_Finger4 R_Finger41 R_Finger42 R_Weapon "
    "L_Thigh L_Calf L_Foot L_Toe0 L_Toe0Nub R_Thigh R_Calf R_Foot R_Toe0 R_Toe0Nub"
).split()

_EXTRA_PARENTS = {"Character": None, "L_Toe0Nub": "L_Toe0", "R_Toe0Nub": "R_Toe0"}


def flver_bones(data):
    ndummy, nmat, nbone = struct.unpack_from("<3i", data, 0x14)
    off = 0x80 + ndummy * 0x40 + nmat * 0x20
    bones = []
    for i in range(nbone):
        o = off + i * 0x80
        (name_off,) = struct.unpack_from("<i", data, o + 12)
        (parent,) = struct.unpack_from("<h", data, o + 28)
        end = name_off
        while data[end:end + 2] != b"\0\0":
            end += 2
        bones.append((data[name_off:end].decode("utf-16-le"), parent))
    return bones


def rig_parents(flver_data):
    bones = flver_bones(flver_data)
    by_name = {n: (bones[p][0] if p >= 0 else None) for n, p in bones}
    parents = []
    for name in RIG_NAMES:
        pname = _EXTRA_PARENTS[name] if name in _EXTRA_PARENTS else by_name[name]
        parents.append(RIG_NAMES.index(pname) if pname else -1)
    return parents
