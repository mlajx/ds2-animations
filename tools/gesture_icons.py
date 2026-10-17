#!/usr/bin/env python3
"""Make gesture menu icons from existing ones (same character render, painted details).

Icons: /menu/tex/icon/IC_00<gestureId>.tpf in GameDataEbl, a TPF with one 64x128 DXT5 DDS named
GE_IC_00<gestureId>. A new icon keeps the target's TPF (header, texture name) and only swaps pixels.
Gesture ids: 63001000 I won't bite, 63004000 Welcome, 63015000 Have mercy!, 63016000 Prostration, ...

Usage: gesture_icons.py EXTRACTED_ICON_DIR OUT_DIR      (writes OUT_DIR/IC_00NNNNNNNN.tpf + a preview)
"""
import io
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageOps

SS = 8  # supersampling for painted details


def load(icon_dir, gesture_id):
    raw = open(os.path.join(icon_dir, f"IC_{gesture_id:010d}.tpf"), "rb").read()
    return raw, Image.open(io.BytesIO(raw[raw.find(b"DDS "):])).convert("RGBA")


def store(tpf, image):
    """Replace the DDS in a single-texture TPF with image (same size, DXT5)."""
    start = tpf.find(b"DDS ")
    buf = io.BytesIO()
    image.save(buf, "DDS", pixel_format="DXT5")
    dds = buf.getvalue()
    if len(dds) != len(tpf) - start:
        raise ValueError("encoded texture size differs from the original")
    return tpf[:start] + dds


def paint(base, draw_fn, blur=0.6):
    """draw_fn(draw, s) draws on a SS-times larger transparent layer (s = scale helper)."""
    layer = Image.new("RGBA", (base.width * SS, base.height * SS), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer), lambda *xy: tuple(v * SS for v in xy))
    layer = layer.filter(ImageFilter.GaussianBlur(blur * SS)).resize(base.size, Image.LANCZOS)
    return Image.alpha_composite(base, layer)


def smoking(base):
    """'I won't bite' pose (hand raised beside the face) + cigarette, ember and a smoke curl.

    DXT5 keeps two colour endpoints per 4x4 block, so white, orange and the dark armour must not share
    a block (they blend into yellow-green): the cigarette stays in the hand's blocks (x < 40), the ember
    alone in the empty block x 40-43 / y 28-31, the smoke starts in the block above."""
    def details(d, s):
        smoke = [(41.6, 27.4), (42.6, 24.6), (41.4, 21.6), (43.0, 18.4), (41.8, 15.2), (43.4, 12.0)]
        for k in range(len(smoke) - 1):
            alpha = int(150 * (1 - k / len(smoke)))
            d.line(s(*smoke[k]) + s(*smoke[k + 1]), fill=(205, 205, 205, alpha), width=int(1.3 * SS))
        d.line(s(35.6, 33.6) + s(39.5, 31.2), fill=(238, 232, 214, 255), width=int(1.1 * SS))   # cigarette
        d.ellipse(s(40.2, 29.0) + s(42.2, 31.2), fill=(255, 150, 50, 150))                       # glow
        d.ellipse(s(40.5, 29.5) + s(41.7, 30.7), fill=(255, 95, 30, 255))                        # ember
    return paint(base, details, blur=0.25)


def dancing(base):
    """'Fist pump' jump mirrored (so it differs from Fist pump in the menu) + faint motion arcs."""
    mirrored = ImageOps.mirror(base)

    def details(d, s):
        for box, start, end in (((12, 28, 30, 46), 150, 250), ((10, 26, 32, 48), 160, 240),
                                ((34, 74, 54, 94), -20, 70), ((32, 72, 56, 96), -10, 60)):
            d.arc(s(*box), start, end, fill=(220, 220, 220, 110), width=int(0.9 * SS))
    return paint(mirrored, details, blur=0.3)


ICONS = {
    # target gesture id: (base gesture id, painter, label)
    63015000: (63001000, smoking, "Smoking (replaces Have mercy!)"),
    63004000: (63018000, dancing, "Dancing (replaces Welcome)"),
}


def main(icon_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    previews = []
    for target, (base_id, painter, label) in ICONS.items():
        tpf, _ = load(icon_dir, target)
        _, base = load(icon_dir, base_id)
        image = painter(base)
        path = os.path.join(out_dir, f"IC_{target:010d}.tpf")
        open(path, "wb").write(store(tpf, image))
        check = Image.open(io.BytesIO(open(path, "rb").read()[tpf.find(b"DDS "):])).convert("RGBA")
        previews.append(check)
        print(f"wrote {path}: {label}, based on {base_id}")
    sheet = Image.new("RGBA", (64 * 4 * len(previews), 128 * 4), (45, 45, 45, 255))
    for k, im in enumerate(previews):
        big = im.resize((256, 512), Image.NEAREST)
        sheet.alpha_composite(big, (256 * k, 0))
    preview = os.path.join(out_dir, "..", "..", "..", "..", "gesture_icons_preview.png")
    sheet.save(preview)
    print("preview:", os.path.normpath(preview))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
