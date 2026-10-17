#!/usr/bin/env python3
"""Decoder for Morpheme 4 NSA animations (.nsa) as shipped in DS2 SotFS c0001.anibnd.

Layout (all offsets are file-relative, pointers stored as 64-bit offsets):
  0x08 u64  header size (= offset of first section)
  0x18 u32  anim type (2 = NSA)
  0x28 f32  duration (s)          0x2C f32 sample frequency (Hz)
  0x30 u32  channel count         0x34 u32 frame sections   0x38 u32 channel sections
  0x3C u32  max compressed channels per section
  0x40 ptr  unchanging pos  CompToAnimMap  (u16 n, u16 animChannel[n], 0xFFFF pad)
  0x48 ptr  unchanging quat CompToAnimMap
  0x50 ptr  -> ptr[channelSections] sampled pos  CompToAnimMaps
  0x58 ptr  -> ptr[channelSections] sampled quat CompToAnimMaps
  0x60 6xf32 pos-means quantisation (offset xyz, scale xyz), applied to u8 means
  0x78 u32  sampled pos quantisation set count   0x7C u32 sampled quat set count
  0x80 ptr  pos sets  (offset xyz, scale xyz) x count
  0x88 ptr  quat sets (offset xyz, scale xyz) x count
  0x90 ptr  unchanging data: u32 nPos, u32 nQuat, posQuant[6f], quatQuant[6f],
            u64 posDataOff, u64 quatDataOff (relative to this block); data = u16x3 per channel
  0x98 u64  max section byte size
  0xA0 ptr  u32 sectionStartFrames[frameSections + 1]
  0xA8 ptr  u32 sectionByteSizes[frameSections * channelSections]
  0xB0 ptr  u64 sectionOffsets[...]
  0xB8 ptr  trajectory source
  0xC0 ptr  channel name table (0 here)

Section: u32 numFrames, u32 nPos, u32 nQuat, u32 pad, then four u64 offsets (relative to
section start): posData (u32 per frame per channel, x:11 bits 21..31, y:11 bits 10..20,
z:10 bits 0..9), posMeanSet (u8 mean xyz + u8 set xyz per channel, channels padded to 4),
quatData (u16x3 per frame per channel), quatMeanSet (same 6-byte layout).

Values:
  unchanging pos/quat:  v = offset + scale * u16
  sampled pos:          mean(u8 via pos-means quant) + set.offset + set.scale * q
  sampled quat:         TQA mean (u8 * 2/255 - 1) combined with TQA delta (set.offset + set.scale * u16)
Rotations are tan-quarter-angle vectors; see tqa_to_quat.

Usage:
  nsa.py dump FILE.nsa [FRAME]
  nsa.py reencode IN.nsa OUT.nsa     decode and re-encode through this encoder (in-place trajectory)
"""
import math
import struct
import sys
from dataclasses import dataclass, field


def tqa_to_quat(v):
    """Tan-quarter-angle rotation vector -> quaternion (x, y, z, w)."""
    t2 = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
    k = 2.0 / (1.0 + t2)
    return (v[0] * k, v[1] * k, v[2] * k, (1.0 - t2) / (1.0 + t2))


def quat_to_tqa(q):
    x, y, z, w = q
    if w < 0:
        x, y, z, w = -x, -y, -z, -w
    k = 1.0 / (1.0 + w)
    return (x * k, y * k, z * k)


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


@dataclass
class QuantSet:
    offset: tuple
    scale: tuple


@dataclass
class Section:
    num_frames: int
    pos_means: list           # per sampled pos channel: (u8 mean xyz, u8 set xyz)
    quat_means: list
    pos_data: list            # [frame][channel] -> u32
    quat_data: list           # [frame][channel] -> (u16, u16, u16)


@dataclass
class NSA:
    duration: float
    sample_rate: float
    num_channels: int
    unchanging_pos_map: list
    unchanging_quat_map: list
    sampled_pos_map: list
    sampled_quat_map: list
    pos_means_quant: QuantSet
    pos_sets: list
    quat_sets: list
    unchanging_pos_quant: QuantSet
    unchanging_quat_quant: QuantSet
    unchanging_pos: list      # u16x3
    unchanging_quat: list     # u16x3
    section_start_frames: list
    sections: list
    raw: bytes = field(repr=False, default=b"")

    @property
    def num_frames(self):
        return self.section_start_frames[-1] + 1


def _f6(d, o):
    v = struct.unpack_from("<6f", d, o)
    return QuantSet(v[:3], v[3:])


def _cmap(d, o):
    (n,) = struct.unpack_from("<H", d, o)
    return list(struct.unpack_from(f"<{n}H", d, o + 2))


def parse(d):
    (anim_type,) = struct.unpack_from("<I", d, 0x18)
    if anim_type != 2:
        raise ValueError(f"not an NSA animation (type {anim_type})")
    duration, rate = struct.unpack_from("<ff", d, 0x28)
    nch, nfs, ncs, _maxc = struct.unpack_from("<4I", d, 0x30)
    if ncs != 1:
        raise NotImplementedError("multiple channel sections")
    up_off, uq_off, sp_pp, sq_pp = struct.unpack_from("<4Q", d, 0x40)
    (sp_off,) = struct.unpack_from("<Q", d, sp_pp)
    (sq_off,) = struct.unpack_from("<Q", d, sq_pp)
    nps, nqs = struct.unpack_from("<II", d, 0x78)
    ps_off, qs_off, ud_off, _maxsz, ssf_off, _ssz_off, so_off, _traj = struct.unpack_from("<8Q", d, 0x80)
    pos_sets = [_f6(d, ps_off + 24 * i) for i in range(nps)]
    quat_sets = [_f6(d, qs_off + 24 * i) for i in range(nqs)]

    nup, nuq = struct.unpack_from("<II", d, ud_off)
    upq, uqq = _f6(d, ud_off + 8), _f6(d, ud_off + 0x20)
    upd, uqd = struct.unpack_from("<QQ", d, ud_off + 0x38)
    upos = [struct.unpack_from("<3H", d, ud_off + upd + 6 * i) for i in range(nup)]
    uquat = [struct.unpack_from("<3H", d, ud_off + uqd + 6 * i) for i in range(nuq)]

    ssf = list(struct.unpack_from(f"<{nfs + 1}I", d, ssf_off))
    sections = []
    for s in range(nfs):
        (so,) = struct.unpack_from("<Q", d, so_off + 8 * s)
        nf, np_, nq, _ = struct.unpack_from("<4I", d, so)
        pd, pm, qd, qm = struct.unpack_from("<4Q", d, so + 16)
        pos_means = [(tuple(d[so + pm + 6 * i:so + pm + 6 * i + 3]), tuple(d[so + pm + 6 * i + 3:so + pm + 6 * i + 6]))
                     for i in range(np_)]
        quat_means = [(tuple(d[so + qm + 6 * i:so + qm + 6 * i + 3]), tuple(d[so + qm + 6 * i + 3:so + qm + 6 * i + 6]))
                      for i in range(nq)]
        pos_data = [list(struct.unpack_from(f"<{np_}I", d, so + pd + 4 * np_ * f)) for f in range(nf)]
        stride = _quat_frame_stride(nq)
        quat_data = [[struct.unpack_from("<3H", d, so + qd + stride * f + 6 * c) for c in range(nq)] for f in range(nf)]
        sections.append(Section(nf, pos_means, quat_means, pos_data, quat_data))

    return NSA(duration, rate, nch, _cmap(d, up_off), _cmap(d, uq_off), _cmap(d, sp_off), _cmap(d, sq_off),
               _f6(d, 0x60), pos_sets, quat_sets, upq, uqq, upos, uquat, ssf, sections, d)


def _quat_frame_stride(num_quat):
    # each frame's u16x3 samples are padded to a 4-byte boundary
    return (6 * num_quat + 3) & ~3


def unpack_pos(word):
    return (word >> 21) & 0x7FF, (word >> 10) & 0x7FF, word & 0x3FF


def decode(anim, quat_mode="mean*delta"):
    """Return (positions, rotations): lists [frame][channel] of xyz tuples and xyzw quats."""
    nch = anim.num_channels
    base_pos = [None] * nch
    base_rot = [None] * nch
    for ch, q in zip(anim.unchanging_pos_map, anim.unchanging_pos):
        base_pos[ch] = tuple(anim.unchanging_pos_quant.offset[k] + anim.unchanging_pos_quant.scale[k] * q[k] for k in range(3))
    for ch, q in zip(anim.unchanging_quat_map, anim.unchanging_quat):
        v = tuple(anim.unchanging_quat_quant.offset[k] + anim.unchanging_quat_quant.scale[k] * q[k] for k in range(3))
        base_rot[ch] = tqa_to_quat(v)

    positions, rotations = [], []
    for sec in anim.sections:
        pm = anim.pos_means_quant
        pos_mean = [tuple(pm.offset[k] + pm.scale[k] * m[k] for k in range(3)) for m, _ in sec.pos_means]
        quat_mean = [tuple(m[k] * (2.0 / 255.0) - 1.0 for k in range(3)) for m, _ in sec.quat_means]
        for f in range(sec.num_frames):
            if positions and f == 0:
                continue  # sections share their boundary frame
            pos = list(base_pos)
            rot = list(base_rot)
            for c, ch in enumerate(anim.sampled_pos_map):
                q = unpack_pos(sec.pos_data[f][c])
                sets = sec.pos_means[c][1]
                pos[ch] = tuple(pos_mean[c][k] + anim.pos_sets[sets[k]].offset[k] + anim.pos_sets[sets[k]].scale[k] * q[k]
                                for k in range(3))
            for c, ch in enumerate(anim.sampled_quat_map):
                q = sec.quat_data[f][c]
                sets = sec.quat_means[c][1]
                delta = tuple(anim.quat_sets[sets[k]].offset[k] + anim.quat_sets[sets[k]].scale[k] * q[k] for k in range(3))
                if quat_mode == "mean*delta":
                    rot[ch] = qmul(tqa_to_quat(quat_mean[c]), tqa_to_quat(delta))
                elif quat_mode == "delta*mean":
                    rot[ch] = qmul(tqa_to_quat(delta), tqa_to_quat(quat_mean[c]))
                elif quat_mode == "mean+delta":
                    rot[ch] = tqa_to_quat(tuple(quat_mean[c][k] + delta[k] for k in range(3)))
                else:
                    raise ValueError(quat_mode)
            positions.append(pos)
            rotations.append(rot)
    return positions, rotations


def main(argv):
    if len(argv) == 4 and argv[1] == "reencode":
        anim = parse(open(argv[2], "rb").read())
        pos, rot = decode(anim)
        open(argv[3], "wb").write(write(pos, rot, anim.sample_rate))
        print(f"wrote {argv[3]} ({len(pos)} frames @ {anim.sample_rate} Hz)")
        return
    if len(argv) < 3 or argv[1] != "dump":
        sys.exit(__doc__)
    anim = parse(open(argv[2], "rb").read())
    frame = int(argv[3]) if len(argv) > 3 else 0
    pos, rot = decode(anim)
    print(f"duration={anim.duration} rate={anim.sample_rate} channels={anim.num_channels} frames={len(pos)}")
    for ch in range(anim.num_channels):
        p, r = pos[frame][ch], rot[frame][ch]
        print(f"ch{ch:2} pos=({p[0]:+.4f},{p[1]:+.4f},{p[2]:+.4f}) rot=({r[0]:+.4f},{r[1]:+.4f},{r[2]:+.4f},{r[3]:+.4f})")



# ---------------------------------------------------------------------------
# Writer

class _Buf:
    def __init__(self):
        self.b = bytearray()

    def tell(self):
        return len(self.b)

    def align(self, n, fill=b"\0"):
        while len(self.b) % n:
            self.b += fill

    def put(self, fmt, *v):
        o = len(self.b)
        self.b += struct.pack("<" + fmt, *v)
        return o

    def patch(self, off, fmt, *v):
        struct.pack_into("<" + fmt, self.b, off, *v)


def _put_cmap(buf, channels):
    o = buf.put("H", len(channels))
    padded = list(channels) + [0xFFFF] * (-len(channels) % 4)
    buf.put(f"{len(padded)}H", *padded)
    buf.align(4, b"\xff")
    return o


def _put_q6(buf, q):
    buf.put("6f", *q.offset, *q.scale)


def _mean_set_bytes(entries):
    entries = list(entries)
    if entries:
        entries += [entries[-1]] * (-len(entries) % 4)
    return b"".join(bytes(m) + bytes(s) for m, s in entries)


def identity_trajectory(num_frames, sample_rate):
    """Trajectory block with no root motion (layout copied from a00_00_0000_Idle)."""
    t = bytearray(0x70)
    struct.pack_into("<IIQQQfI", t, 0, 2, 0, 0, 0x70, 0x10, sample_rate, num_frames)
    struct.pack_into("<f", t, 0x4C, 1.0)  # constant delta rotation = identity quaternion
    return bytes(t)


def serialize(anim, trajectory):
    """Build .nsa bytes from an NSA (single frame section, single channel section)."""
    if len(anim.sections) != 1:
        raise NotImplementedError("multiple frame sections")
    sec = anim.sections[0]
    buf = _Buf()
    buf.put("QQII", 0, 0, 16, 2046)          # header size patched below
    buf.put("IIQ", 2, 0, 0)
    buf.put("ff", anim.duration, anim.sample_rate)
    max_comp = max(len(anim.unchanging_pos_map), len(anim.unchanging_quat_map),
                   len(anim.sampled_pos_map), len(anim.sampled_quat_map))
    buf.put("4I", anim.num_channels, 1, 1, max_comp)
    ptrs = buf.put("4Q", 0, 0, 0, 0)
    _put_q6(buf, anim.pos_means_quant)
    buf.put("II", len(anim.pos_sets), len(anim.quat_sets))
    ptrs2 = buf.put("9Q", *([0] * 9))

    up = _put_cmap(buf, anim.unchanging_pos_map)
    uq = _put_cmap(buf, anim.unchanging_quat_map)
    buf.align(8)
    sp_arr = buf.put("Q", 0)
    sq_arr = buf.put("Q", 0)
    sp = _put_cmap(buf, anim.sampled_pos_map)
    sq = _put_cmap(buf, anim.sampled_quat_map)
    buf.patch(ptrs, "4Q", up, uq, sp_arr, sq_arr)
    buf.patch(sp_arr, "Q", sp)
    buf.patch(sq_arr, "Q", sq)

    ps = buf.tell()
    for q in anim.pos_sets:
        _put_q6(buf, q)
    qs = buf.tell()
    for q in anim.quat_sets:
        _put_q6(buf, q)
    ssf = buf.put(f"{len(anim.section_start_frames)}I", *anim.section_start_frames)
    ssz = buf.put("I", 0)
    soff = buf.put("Q", 0)

    ud = buf.put("II", len(anim.unchanging_pos), len(anim.unchanging_quat))
    _put_q6(buf, anim.unchanging_pos_quant)
    _put_q6(buf, anim.unchanging_quat_quant)
    ud_ptrs = buf.put("QQ", 0, 0)
    upd = buf.tell() - ud
    for q in anim.unchanging_pos:
        buf.put("3H", *q)
    buf.align(4)
    uqd = buf.tell() - ud
    for q in anim.unchanging_quat:
        buf.put("3H", *q)
    buf.patch(ud_ptrs, "QQ", upd, uqd)
    buf.align(16)

    # section
    so = buf.tell()
    sec_hdr = buf.put("4I", sec.num_frames, len(anim.sampled_pos_map), len(anim.sampled_quat_map), 0)
    sec_ptrs = buf.put("4Q", 0, 0, 0, 0)
    pd = buf.tell() - so
    for frame in sec.pos_data:
        buf.put(f"{len(frame)}I", *frame)
    pm = buf.tell() - so
    buf.b += _mean_set_bytes(sec.pos_means)
    qd = buf.tell() - so
    for frame in sec.quat_data:
        for q in frame:
            buf.put("3H", *q)
        buf.align(4)
    qm = buf.tell() - so
    buf.b += _mean_set_bytes(sec.quat_means)
    buf.align(16)
    size = buf.tell() - so
    if not anim.sampled_pos_map:
        pd = pm = 0
    buf.patch(sec_ptrs, "4Q", pd, pm, qd, qm)
    buf.patch(ssz, "I", size)
    buf.patch(soff, "Q", so)

    traj = buf.tell() if trajectory else 0
    if trajectory:
        buf.b += trajectory
    buf.patch(8, "Q", so)
    buf.patch(ptrs2, "9Q", ps if anim.pos_sets else 0, qs if anim.quat_sets else 0,
              ud, size, ssf, ssz, soff, traj, 0)
    return bytes(buf.b)


def trajectory_bytes(data):
    (t,) = struct.unpack_from("<Q", data, 0xB8)
    return data[t:] if t else None


# ---------------------------------------------------------------------------
# Encoder

MAX_QUAT_SETS = 14        # largest count found in the shipped c0001 animations
POS_EPS = 1e-5            # metres: below this a position channel is stored as unchanging
ROT_EPS = 1e-5            # TQA units (~0.003 deg)


def _qconj(q):
    return (-q[0], -q[1], -q[2], q[3])


def _range_quant(values, levels):
    """QuantSet covering per-component [min, max] of a list of xyz tuples."""
    lo = [min(v[k] for v in values) for k in range(3)]
    hi = [max(v[k] for v in values) for k in range(3)]
    scale = [max(hi[k] - lo[k], 1e-12) / levels[k] for k in range(3)]
    return QuantSet(tuple(lo), tuple(scale))


def _quantise(v, q, levels):
    return tuple(min(levels[k], max(0, round((v[k] - q.offset[k]) / q.scale[k]))) for k in range(3))


def _cluster_ranges(ranges, n):
    """Group per-channel (lo, hi) ranges into <= n sets. Returns (set_ranges, assignment)."""
    order = sorted(range(len(ranges)), key=lambda i: ranges[i][1] - ranges[i][0])
    groups = [order[i * len(order) // n:(i + 1) * len(order) // n] for i in range(n)]
    groups = [g for g in groups if g]
    assign = [0] * len(ranges)
    out = []
    for gi, g in enumerate(groups):
        out.append((min(ranges[i][0] for i in g), max(ranges[i][1] for i in g)))
        for i in g:
            assign[i] = gi
    return out, assign


def _average_quat(qs):
    ref = qs[0]
    acc = [0.0, 0.0, 0.0, 0.0]
    for q in qs:
        s = 1.0 if sum(q[k] * ref[k] for k in range(4)) >= 0 else -1.0
        for k in range(4):
            acc[k] += s * q[k]
    n = math.sqrt(sum(a * a for a in acc)) or 1.0
    return tuple(a / n for a in acc)


def encode(positions, rotations, sample_rate):
    """Build an NSA from local channel transforms: positions[frame][ch] = xyz,
    rotations[frame][ch] = quaternion xyzw (Morpheme rig space)."""
    nf = len(positions)
    nch = len(positions[0])
    lv16 = (65535, 65535, 65535)
    lvpos = (2047, 2047, 1023)

    up_map, sp_map, uq_map, sq_map = [], [], [], []
    for ch in range(nch):
        p0 = positions[0][ch]
        if all(max(abs(positions[f][ch][k] - p0[k]) for k in range(3)) < POS_EPS for f in range(nf)):
            up_map.append(ch)
        else:
            sp_map.append(ch)
        t0 = quat_to_tqa(rotations[0][ch])
        if all(max(abs(a - b) for a, b in zip(quat_to_tqa(rotations[f][ch]), t0)) < ROT_EPS for f in range(nf)):
            uq_map.append(ch)
        else:
            sq_map.append(ch)

    # unchanging channels
    up_vals = [positions[0][ch] for ch in up_map] or [(0.0, 0.0, 0.0)]
    upq = _range_quant(up_vals, lv16)
    upos = [_quantise(positions[0][ch], upq, lv16) for ch in up_map]
    uq_vals = [quat_to_tqa(rotations[0][ch]) for ch in uq_map] or [(0.0, 0.0, 0.0)]
    uqq = _range_quant(uq_vals, lv16)
    uquat = [_quantise(quat_to_tqa(rotations[0][ch]), uqq, lv16) for ch in uq_map]

    # sampled positions: u8 mean per channel + one shared residual set
    means = [tuple((min(positions[f][ch][k] for f in range(nf)) + max(positions[f][ch][k] for f in range(nf))) / 2
                   for k in range(3)) for ch in sp_map]
    pmq = _range_quant(means or [(0.0, 0.0, 0.0)], (255, 255, 255))
    qmeans = [_quantise(m, pmq, (255, 255, 255)) for m in means]
    dmeans = [tuple(pmq.offset[k] + pmq.scale[k] * qm[k] for k in range(3)) for qm in qmeans]
    residuals = [[tuple(positions[f][ch][k] - dmeans[c][k] for k in range(3)) for f in range(nf)]
                 for c, ch in enumerate(sp_map)]
    pos_sets = [_range_quant([r for rs in residuals for r in rs], lvpos)] if sp_map else []
    pos_data = [[0] * len(sp_map) for _ in range(nf)]
    for c in range(len(sp_map)):
        for f in range(nf):
            x, y, z = _quantise(residuals[c][f], pos_sets[0], lvpos)
            pos_data[f][c] = (x << 21) | (y << 10) | z
    pos_means = [(qm, (0, 0, 0)) for qm in qmeans]

    # sampled rotations: u8 TQA mean per channel + TQA delta quantised in clustered sets
    quat_means, deltas = [], []
    for ch in sq_map:
        mean_t = quat_to_tqa(_average_quat([rotations[f][ch] for f in range(nf)]))
        qm = tuple(min(255, max(0, round((mean_t[k] + 1.0) * 255.0 / 2.0))) for k in range(3))
        mq = tqa_to_quat(tuple(qm[k] * (2.0 / 255.0) - 1.0 for k in range(3)))
        quat_means.append(qm)
        deltas.append([quat_to_tqa(qmul(_qconj(mq), rotations[f][ch])) for f in range(nf)])
    nsets = min(MAX_QUAT_SETS, max(1, len(sq_map)))
    set_lo = [[0.0] * 3 for _ in range(nsets)]
    set_hi = [[0.0] * 3 for _ in range(nsets)]
    assign = [[0] * 3 for _ in sq_map]
    for k in range(3):
        ranges = [(min(d[k] for d in ds), max(d[k] for d in ds)) for ds in deltas] or [(0.0, 0.0)]
        set_ranges, a = _cluster_ranges(ranges, nsets)
        for j, (lo, hi) in enumerate(set_ranges):
            set_lo[j][k], set_hi[j][k] = lo, hi
        for c in range(len(sq_map)):
            assign[c][k] = a[c]
    quat_sets = [QuantSet(tuple(set_lo[j]), tuple(max(set_hi[j][k] - set_lo[j][k], 1e-12) / 65535 for k in range(3)))
                 for j in range(nsets)]
    quat_data = [[None] * len(sq_map) for _ in range(nf)]
    for c in range(len(sq_map)):
        for f in range(nf):
            quat_data[f][c] = tuple(
                min(65535, max(0, round((deltas[c][f][k] - quat_sets[assign[c][k]].offset[k]) /
                                        quat_sets[assign[c][k]].scale[k]))) for k in range(3))
    quat_means = [(quat_means[c], tuple(assign[c])) for c in range(len(sq_map))]

    sec = Section(nf, pos_means, quat_means, pos_data, quat_data)
    return NSA((nf - 1) / sample_rate, sample_rate, nch, up_map, uq_map, sp_map, sq_map, pmq, pos_sets, quat_sets,
               upq, uqq, upos, uquat, [0, nf - 1], [sec])


def write(positions, rotations, sample_rate):
    anim = encode(positions, rotations, sample_rate)
    return serialize(anim, identity_trajectory(len(positions), sample_rate))


if __name__ == "__main__":
    main(sys.argv)
