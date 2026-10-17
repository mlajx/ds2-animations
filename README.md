# DS2 custom animations (Dark Souls II: Scholar of the First Sin)

Tools and a drop-in mod (`DS2AnimMod`, a `dinput8.dll`) to replace player animations in DS2 SotFS
with animations from Blender/Mixamo/game rigs, plus particle effects (embers, smoke) driven by the
animation's TimeAct events. Everything was reverse-engineered from the game files and
`DarkSoulsII.exe`; the format notes below are what the tools rely on.

Current mod content:

| Original gesture | Shown in game as | Internal slot | TAE id | Replaced with |
|---|---|---|---|---|
| Have mercy! | Smoking (pt: Fumar) | `a74_01_0130_Pray` | 74010130 | Mixamo "Smoking" (17.9 s) + cigarette ember/smoke effects |
| Welcome | Dancing (pt: Dançar) | `a74_01_0040_Welcome` | 74010040 | Master Chief dance (`animations/default-chief`, action `succ`, 6.8 s) |

---

## 1. Setup

Requirements: Python 3 with `cryptography`, `numpy`, `matplotlib`, `Pillow`; Blender (headless is enough);
`x86_64-w64-mingw32-g++` for the DLL; Wine only for the optional loader self-test.

Game folder used below:

```sh
G="$HOME/games/SteamLibrary/steamapps/common/Dark Souls II Scholar of the First Sin/Game"
```

`extracted/` and `build/` are git-ignored. Recreate the extracted originals once (read-only on the game):

```sh
python3 tools/ds2unpack.py "$G" GameData extract extracted \
    /morpheme4/chr/c0001.anibnd.dcx /model/chr/c0001.bnd \
    /timeact/chr/c000100_pl.tae /timeact/chr/c000100_sfx.tae /timeact/chr/c000100_snd.tae
python3 -c "import sys,zlib; d=open('extracted/morpheme4/chr/c0001.anibnd.dcx','rb').read(); open('extracted/morpheme4/chr/c0001.anibnd','wb').write(zlib.decompress(d[0x4c:]))"
python3 tools/bnd4.py extract extracted/morpheme4/chr/c0001.anibnd extracted/c0001-anibnd
python3 tools/bnd4.py extract extracted/model/chr/c0001.bnd extracted/c0001-model
```

## 2. Import a new animation (the recipe)

1. **Pick the slot.** Gestures are `a74_01_XXXX_*.nsa` in `extracted/c0001-anibnd/` (list below).
   The TAE id is the name digits: `a74_01_0040` -> `74010040`. Optionally rename it / give it an icon
   (section 4).
2. **Export the source animation** (FBX or .blend) to JSON with Blender. For downloaded `.blend`
   files keep `--disable-autoexec` (stops embedded scripts). List actions first if unsure
   (open the file in Blender, or run the exporter and read the `EXPORT OK` line).

   ```sh
   blender -b --factory-startup --disable-autoexec --python tools/blender_export.py -- \
       animations/Smoking.fbx build/smoking/smoking_mixamo.json            # active action, 20 Hz
   blender -b --factory-startup --disable-autoexec --python tools/blender_export.py -- \
       animations/default-chief/source/mc.blend build/chief/chief_source.json --action succ
   ```

3. **Retarget + encode** onto the DS2 rig. The source rig profile (`mixamo`, `unreal`) is auto-detected;
   a new rig needs a profile in `PROFILES` in `tools/retarget.py` (canonical Mixamo names -> rig bones,
   plus synthesised end points for missing head-top/fingertip/toe-tip bones).

   ```sh
   python3 tools/retarget.py build/chief/chief_source.json build/chief/a74_01_0040_Chief.nsa
   ```

   Read the report: segment direction error (mean should be < 1 deg; large values only on arms near
   the face = contact IK at work), ankle height (lowest ~0.095-0.10 m = feet on the ground).
4. **Check it visually** (grey = source, colour = DS2 decoded back from the .nsa):

   ```sh
   python3 tools/preview.py build/chief/chief_source.json build/chief/a74_01_0040_Chief.nsa build/chief/preview.png 0 28 56 84
   ```

5. **Add the slot** to `SLOTS` in `tools/build_mod.py` (shipped .nsa name substring, TAE id, your .nsa,
   optional effect events), then build and package everything:

   ```sh
   python3 tools/build_mod.py "$G" build/payload
   make -C mod package PAYLOAD=../build/payload      # -> mod/dist/DS2AnimMod/
   ```

6. **Install/test**: copy the contents of `mod/dist/DS2AnimMod/` next to `DarkSoulsII.exe` (replace the
   whole `DS2AnimMod` folder). On Proton: launch option `WINEDLLOVERRIDES="dinput8=n,b" %command%`.
   Test offline. `DS2AnimMod.log` must show `serving <file> from the mod folder` for each replaced file.

Length: the game ships animations up to 244 frames (~12 s); 359 frames (17.9 s at 20 Hz) works fine.
`build_mod.py` sets the slot's TAE length and the Morpheme network durations from the .nsa automatically.

## 3. Effects (embers, smoke) on an animation

- Events: `tae.sfx_event(start_s, end_s, effect_id, dummy_id)` = TAE event type 2104
  (params `-1, effectId, dummyPoly, 1, 0`), grouped under group type 2100; the effect lives from
  start to end. In `build_mod.py` a slot's `events` are `(start frame @30 fps, end frame, effect, dummy, note)`;
  the cigarette timeline is `tools/cigarette_timeline.py`.
- Attachment points (dummy polys of `c0001.flv`): 1 = right hand grip, 2 = left hand, 255 = face/mouth,
  150 = crown, 249 = pelvis. Added by `tools/flver_dummies.py`: 900 = cigarette tip past the right index
  fingertip, 901 = cigarette tip 7 cm in front of the mouth. Add more in its `DUMMIES` table.
- Finding effects: `python3 tools/sfx_catalog.py "$G" build/sfx_catalog` renders every effect texture
  labelled with the effect ids that use it (effects/textures only have numbers). Shortlist by texture,
  then test in-game with a reel (`tools/effect_reel.py`: candidates in timed slots).
- Tuning effects: `tools/ffx_edit.py` `RECIPES` clones an effect under a new id with in-place edits
  (`scale` floats in a parameter block slot, `alpha` of colour keys). Extract an effect (bank entries
  are zlib-compressed one by one) and inspect its parameter blocks:

  ```sh
  mkdir -p extracted/sfx && python3 -c "import sys,zlib; sys.path.insert(0,'tools'); import bnd4; \
  [open('extracted/sfx/'+f.name.split(chr(92))[-1],'wb').write(zlib.decompress(f.data)) \
   for f in bnd4.read_bnd4(open(sys.argv[1],'rb').read()) if f.name.endswith('f0001601.ffx')]" "$G/sfx/sfx9999.ffxbnd.dcx"
  python3 tools/dlse.py extracted/sfx/f0001601.ffx
  ```

   Current: 9101 steady ember (from 1601, whose colour
  curve blinked), 9102 drag/exhale and 9103 wisp (from 193, smaller/fainter).
- Learned the hard way: effect 107 is an area-sized fog (huge white cloud), 301/3907/3962 are red-tinted.

## 4. Gesture names and menu icons

Both are built by `build_mod.py` from two tables:

- **Names** - `RENAMES` in `tools/gesture_text.py`: `{gestureId: {"default": name, "<language>": name}}`.
  For each of the 11 language folders (`chinese english french germany italian korean neutralspanish
  polish portuguese russian spanish` under `/menu/text/`) it sets the gesture menu name
  (`ingamemenu.fmg`) and swaps that language's old name inside the gesture item name (`ItemName.fmg`,
  e.g. `"Welcome" Gesture`) and its description (`DetailedExplanation.fmg`). Languages that decline the
  name instead of quoting it get a sentence rule (`SENTENCE_RULES`, Polish); texts that call the gesture
  something else than its menu name (English "Have mercy!" is described as "Beg for life") are rebuilt
  from the Point gesture's wording (`REFERENCE_GESTURE`). Inspect any text with
  `python3 tools/fmg.py dump extracted/menu/text/english/ingamemenu.fmg Welcome`.
- **Icons** - `ICONS` in `tools/gesture_icons.py`: `{targetGestureId: (baseGestureId, painter, label)}`.
  Icons are `/menu/tex/icon/IC_00<gestureId>.tpf` (one 64x128 DXT5 texture). A new icon starts from an
  existing gesture's render and paints details on it; it is stored in the target's own TPF. DXT5 keeps two
  colours per 4x4 block, so keep contrasting colours (white vs orange vs dark armour) in separate blocks
  or they blend (that is why the ember sits alone in its block). Preview: `build/gesture_icons_preview.png`.

Gesture ids are the menu ids: `630NN000` with NN = the gesture number (Have mercy! 15, Prostration 16, Welcome 4); the
same id keys the name, item, description and icon. Current: Have mercy! (15) -> "Smoking" (pt: "Fumar"),
icon from "I won't bite" + cigarette; Welcome -> "Dancing" (pt: "Dançar"), icon = mirrored "Fist pump"
+ motion arcs.

## 5. The mod DLL (`mod/`)

`dinput8.dll` proxy, settings in `DS2AnimMod.ini`, log `DS2AnimMod.log` (both next to the exe).

- **SteamFix** (on by default): the stutter fix from `../SteamFixAlternative` (skips re-storing unlocked
  achievements, throttles stats requests, deduplicates leaked Steam callbacks).
- **AnimLoader**: every file under `Game\DS2AnimMod\` replaces the game file with the same path:
  - archived files (`GameDataEbl.bdt` etc.): on the first `open()` through each
    `DLEBL::DLEncryptedBinderLightFileDevice` (vtable found via RTTI at runtime, slot 1), the in-memory
    BHD5 entry (`[dev+C0]` base, `[dev+C8]` bucket count, `[dev+D0]` buckets) is pointed at a virtual
    offset (256 GiB + n x 4 GiB) with the new size, unencrypted, no hash. Exe IAT hooks:
    `GetFileInformationByHandle` inflates the `.bdt` size (the disk layer clamps seeks to it),
    `ReadFile` (sync + OVERLAPPED) serves the virtual range, `CreateFileW`/`CloseHandle` track handles.
  - loose files (`Game\sfx\...`, read through the `title:` root): `CreateFileW` opens the mod copy.
- Build: `make -C mod`; offline check of the exe lookups under Wine: `make -C mod test`.

## 6. File formats (what the tools rely on)

- **Archives** `*Ebl.bhd/.bdt` (`ds2unpack.py`): BHD is RSA-encrypted with the public key in
  `*KeyCode.pem` (raw RSA, 256-byte blocks -> 255-byte plaintext) -> BHD5 (salt, buckets, 0x20-byte
  entries: u32 hash, i32 size, i64 offset, i64 saltedHash, i64 aesKey). Path hash: `h = h*37 + c`
  over the lower-case path with `/`, e.g. `/morpheme4/chr/c0001.anibnd.dcx`. Some entries have
  AES-128-ECB ranges (TAE files do; the anibnd doesn't).
- **DCX** = `DCX` header + zlib (DFLT). **BND4** (`bnd4.py`): `write_bnd4` rebuilds byte-identically;
  effect bank entries are zlib-compressed (flags 0xC0, separate compressed/uncompressed sizes).
- **Animations: NaturalMotion Morpheme 4, not Havok** (Havok in the exe is physics). `c0001.anibnd`
  = 897 `.nsa` + `c0001.nmb` (network). `.nsa` (`nsa.py`, byte-identical rebuild of 874/876 files):
  58 channels in `rig.RIG_NAMES` order (Character, Master, Root, Pelvis, Spine, Spine1, Neck, Head,
  arms+fingers, legs+toe nubs); rotations are tan-quarter-angle vectors; sampled rotation =
  mean(u8) * delta(u16 per component via quantisation sets); sampled position u32 packed 11:11:10;
  Morpheme space = FLVER with Y and Z swapped. One frame section, <=14 rotation quantisation sets.
- **Network durations**: `c0001.nmb` caches each animation's length per node
  (`u32 animFileId, u32 hash, 02 00 00 cd, f32 0, f32 1, f32 duration`; 3238 records). Playback stops at
  that value -> `anibnd.py replace` updates it (cause of the first "stops at 9 s" bug).
- **TimeAct** `c000100_pl.tae` (`tae.py`; the player's TAE id is 100, not 1): animation length in 30 fps
  frames in the animFile record (second "stops at 9 s" cause), events/groups/times appended by `add_events`.
- **Effects** `Game\sfx\sfx9999.ffxbnd.dcx`: `fNNNNNNN.ffx` are DLsE object trees (`dlse.py`; param type
  40 = texture id, 41 = model id) + `sfxParameter.sfxparam` (0x40-byte records sorted by id) and
  `sfxDebugParameter.sfxparam` (8-byte records); new effects need records in both (`ffx_edit.py`).
- **FLVER dummies** (`flver_dummies.py`): 0x40-byte records after the 0x80 header; adding some shifts
  the header data offset and bone name offsets.

## 7. Retarget details and pitfalls

- Rest alignment per bone (aim + optional side vector), then world-space deltas; twist comes from the
  DS2 Idle frame 0. The DS2 head has no child: aligned on its own axes (+X up, +Y face).
- **Proportions break hand-to-face contact** (the hand landed on the cheek): `face_contact_ik` solves
  the arm so the fingertip sits where the source puts it relative to the head (within 0.15-0.30 m).
- Ground fit moves the root so the lowest ankle matches the DS2 idle (Mixamo hips sit above the thighs).
- Rigs with more spine/neck bones: map DS2 bones to the source bone nearest the next joint
  (Unreal: Spine1 = spine_03, Spine2 = spine_05, Neck = neck_02).
- Imported game rigs often have meaningless bone tails: profiles synthesise end points instead.

## 8. Gesture slots (internal name -> in-game)

Verified in game: `0130_Pray` = **Have mercy!** (gesture 15; it ends bowed to the floor, which first
looked like Prostration), `0040_Welcome` = Welcome (gesture 4). Probably `0250_IAmSorryJP` = Prostration
(16, a Japanese apology bow). Confirm a slot in game before renaming it: replace the animation, play
every gesture card, and note which one plays it. Probable from names: `0010_Foreword` Point, `0020_ComeOn` I won't bite,
`0030_MakeaBow` Bow, `0060_Bye` Wave, `0080_Yes` Righty-ho!, `0090_No` No way, `0150_Cutthroat` Decapitate,
`0270_WarmingUp` Warmup, `0280_Roar` Warcry, `0300_PrayingToTheSun` Praise the Sun, `0050_Saluez` Duel bow?,
`0070_DelightMale` Joy?, `0310_HardDelight` Fist Pump?, `0100_LeaveItToMe` This one's me?, `0240_Rouse` Hurrah!?,
`0120_Rise` Pumped Up?, `0220_IDontKnowJP` Mock?, `0290_WarmingUp2` ?.

## 9. Tool index

| Tool | Purpose |
|---|---|
| `tools/ds2unpack.py` | list/find/extract files from the encrypted archives |
| `tools/bnd4.py` | DCX/BND4 read, extract, replace, `write_bnd4`, `dcx` |
| `tools/nsa.py` | Morpheme NSA decode/encode (`dump`, `reencode`) |
| `tools/rig.py` | DS2 player rig (channel names, parents) |
| `tools/blender_export.py` | Blender: FBX/.blend animation -> JSON (world transforms) |
| `tools/retarget.py` | JSON -> DS2 .nsa (profiles, alignment, contact IK, ground fit) |
| `tools/preview.py` | stick-figure comparison PNG |
| `tools/anibnd.py` | replace an animation + Morpheme network durations |
| `tools/tae.py` | TAE show / set-length / add events |
| `tools/build_mod.py` | build the full payload from `SLOTS` |
| `tools/cigarette_timeline.py` | cigarette effect timeline ("Have mercy!" slot) |
| `tools/dlse.py`, `tools/sfx_catalog.py`, `tools/ffx_edit.py`, `tools/effect_reel.py` | effects: parse, catalog, tune, test reel |
| `tools/flver_dummies.py` | add effect attachment points |
| `tools/fmg.py`, `tools/gesture_text.py` | game text (FMG) read/write, gesture renames in all languages |
| `tools/gesture_icons.py` | gesture menu icons (TPF/DXT5) |
| `tools/disfn.py`, `tools/rtti.py`, `tools/imports.py` | exe RE helpers (objdump by function, RTTI vtables, IAT) |

Reverse-engineering note: REA/Ghidra times out (~5.5 min) on the 28 MB exe on every call; objdump plus
`disfn.py`/`rtti.py`/`imports.py` was enough for everything above.

## 10. Credits

Source animations in `animations/` belong to their authors and keep their original licenses:

- `animations/default-chief/` (model, textures and the `succ` dance used for "Dancing"):
  "Default Chief" on Sketchfab - https://sketchfab.com/3d-models/default-chief-b11ec17a3a9e431eb38ac1ab2b8acf4c
- `animations/Smoking.fbx` (used for "Smoking"): Mixamo - https://www.mixamo.com/#/?page=1&query=smoke

Dark Souls II and its assets belong to FromSoftware / Bandai Namco; this repository contains no game files
(everything under `extracted/` and `build/` is generated locally from your own installation).
