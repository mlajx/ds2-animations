#!/usr/bin/env python3
"""Rename gestures in every game language.

For each language folder /menu/text/<lang>/ (GameDataEbl):
  ingamemenu.fmg           gesture menu name (id = gesture id)        -> set to the new name
  ItemName.fmg             the gesture's item, e.g. '"Welcome" Gesture' -> old name replaced inside
  DetailedExplanation.fmg  its description ('Teaches the "Welcome" gesture.') -> same
The old name is that language's own ingamemenu text, so translated sentences stay intact.

Usage: gesture_text.py GAME_DIR OUT_DIR  (names from RENAMES; writes OUT_DIR/menu/text/<lang>/*.fmg)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ds2unpack  # noqa: E402
import fmg  # noqa: E402

LANGUAGES = ["chinese", "english", "french", "germany", "italian", "korean", "neutralspanish", "polish",
             "portuguese", "russian", "spanish"]
FILES = ["ingamemenu", "ItemName", "DetailedExplanation"]

# languages whose sentences decline the name instead of quoting it: (file, regex, replacement)
SENTENCE_RULES = {
    "polish": [("DetailedExplanation", r"Uczy gestu [^.\n]*\.", 'Uczy gestu "{new}".')],
}

# gesture whose item/description wording is reused when a text calls the gesture something else
# than its menu name (e.g. English "Have mercy!" is described as teaching "Beg for life")
REFERENCE_GESTURE = 63000000  # Point

# gesture id: {language: name}, "default" for every language not listed
RENAMES = {
    63015000: {"default": "Smoking", "portuguese": "Fumar"},     # was Have mercy! (anim a74_01_0130_Pray)
    63004000: {"default": "Dancing", "portuguese": "Dançar"},    # was Welcome
}


def build(game, out, renames=RENAMES):
    archive = ds2unpack.Archive(game, "GameData")
    for lang in LANGUAGES:
        tables = {}
        for name in FILES:
            entry = archive.entries[ds2unpack.path_hash(f"/menu/text/{lang}/{name}.fmg")]
            tables[name] = fmg.read(archive.read(entry)[:entry.padded_size])
        report = []
        reference = {name: tables[name][2].get(REFERENCE_GESTURE) for name in FILES}
        for gesture, names in renames.items():
            new = names.get(lang, names["default"])
            old = tables["ingamemenu"][2][gesture]
            tables["ingamemenu"][2][gesture] = new
            for name in ("ItemName", "DetailedExplanation"):
                text = tables[name][2].get(gesture)
                if not text:
                    continue
                updated = re.sub(re.escape(old), lambda _m: new, text, flags=re.IGNORECASE)
                for file, pattern, replacement in SENTENCE_RULES.get(lang, []):
                    if file == name and updated == text:
                        updated = re.sub(pattern, lambda _m: replacement.format(new=new), text)
                if updated == text:  # differently worded: rebuild from the reference gesture's text
                    ref_name, ref_text = reference["ingamemenu"], reference[name]
                    candidate = re.sub(re.escape(ref_name), lambda _m: new, ref_text, flags=re.IGNORECASE)
                    for file, pattern, replacement in SENTENCE_RULES.get(lang, []):
                        if file == name and candidate == ref_text:
                            candidate = re.sub(pattern, lambda _m: replacement.format(new=new), ref_text)
                    if candidate != ref_text:
                        updated = candidate
                        report.append(f"{name} {gesture}: reworded from gesture {REFERENCE_GESTURE}")
                    else:
                        report.append(f"{name} {gesture}: old name not found, left unchanged")
                tables[name][2][gesture] = updated
            report.append(f"{old} -> {new}")
        for name in FILES:
            path = os.path.join(out, "menu", "text", lang, f"{name}.fmg")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(fmg.write(*tables[name]))
        print(f"  {lang:14} " + "; ".join(report))


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
