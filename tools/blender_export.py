"""Dump an armature animation (FBX or .blend) as world-space bone transforms (run inside Blender).

Usage:
  blender -b --factory-startup --disable-autoexec --python tools/blender_export.py -- IN.fbx|IN.blend OUT.json
          [--rate HZ] [--action NAME] [--armature NAME]

Defaults: 20 Hz, the armature's active action, the first armature in the file.
--disable-autoexec matters for downloaded .blend files: it stops scripts embedded in them from running.

Output JSON:
  rate, duration, frames (sample count), bones: [names],
  rest:    {name: {"head": xyz, "tail": xyz, "rot": 3x3}}   armature rest pose, world space
  samples: [ {name: {"head": xyz, "tail": xyz, "rot": 3x3}} ... ]  posed, world space, one per 1/RATE s
World space is Blender's with object transforms applied; rotations are orthonormalised
(object scale removed). Tails give end points for rigs without end bones (head top, fingertips).
"""
import json
import sys

import bpy


def parse_args(argv):
    args = {"rate": 20.0, "action": None, "armature": None}
    positional = []
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            args[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    return positional[0], positional[1], float(args["rate"]), args["action"], args["armature"]


def main():
    src, dst, rate, action_name, armature_name = parse_args(sys.argv[sys.argv.index("--") + 1:])

    if src.lower().endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=src, load_ui=False)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=src, automatic_bone_orientation=False)
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    arm = next(o for o in armatures if o.name == armature_name) if armature_name else armatures[0]
    if action_name:
        arm.animation_data_create()
        arm.animation_data.action = bpy.data.actions[action_name]
        for track in arm.animation_data.nla_tracks:
            track.mute = True
    action = arm.animation_data.action if arm.animation_data else None
    if action is None:
        sys.exit("no animation on the armature")
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    first, last = action.frame_range
    duration = (last - first) / fps
    count = int(duration * rate + 1e-6) + 1

    def xform(matrix, tail):
        loc, rot, _scale = matrix.decompose()
        return {"head": list(loc), "tail": list(tail), "rot": [list(row) for row in rot.to_matrix()]}

    names = [b.name for b in arm.data.bones]
    rest = {b.name: xform(arm.matrix_world @ b.matrix_local, arm.matrix_world @ b.tail_local) for b in arm.data.bones}
    samples = []
    for i in range(count):
        frame = first + i * fps / rate
        whole = int(frame)
        scene.frame_set(whole, subframe=frame - whole)
        samples.append({pb.name: xform(arm.matrix_world @ pb.matrix, arm.matrix_world @ pb.tail)
                        for pb in arm.pose.bones})

    with open(dst, "w") as f:
        json.dump({"source": src, "armature": arm.name, "action": action.name, "fps": fps, "rate": rate,
                   "duration": duration, "frames": count, "bones": names, "rest": rest, "samples": samples}, f)
    print(f"EXPORT OK: {arm.name}/{action.name}: {len(names)} bones, {count} samples @ {rate} Hz "
          f"({duration:.3f} s, source {fps} fps, frames {first:g}-{last:g})")


main()
