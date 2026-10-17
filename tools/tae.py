#!/usr/bin/env python3
"""DS2 SotFS TimeAct (.tae, 64-bit "TAE " v0x1000C) helpers.

Layout used here:
  0x54 i32 animation count, 0x58 i64 offset of {i64 id, i64 header offset}[count]
  animation header (0x30): i64 eventHeaders, i64 eventGroups, i64 times, i64 animFile,
                           i32 eventCount, i32 groupCount, i32 timeCount, i32 pad
  event header: i64 startTimePtr, i64 endTimePtr, i64 eventDataPtr; data: i32 type, i32 pad, i64 paramsPtr
  animFile: i64 type, i64 dataOffset -> {i64 next, u8 ?, u8 fps(30), u16 ?, u32 lengthFrames}

  group: i64 eventCount, i64 eventIndexListPtr, i64 groupDataPtr, i64 0; groupData: u32 groupType,
         pad, i64 ptr -> 16 zero bytes; index list: i64 eventHeaderPtr per event
  SFX event 2104 (seen in shipped events): params i32[10] = (-1, ffxId, dummyPolyId, 1, 0, ...),
         grouped under group type 2100; the effect lives from start to end time.

Usage:
  tae.py show TAE ANIM_ID
  tae.py set-length TAE OUT ANIM_ID FRAMES      animation length in 30 fps frames
"""
import struct
import sys


def anim_offsets(d):
    count, table = struct.unpack_from("<iq", d, 0x54)
    return dict(struct.unpack_from("<qq", d, table + 16 * i) for i in range(count))


def length_field(d, anim_id):
    header = anim_offsets(d)[anim_id]
    (anim_file,) = struct.unpack_from("<q", d, header + 0x18)
    (data,) = struct.unpack_from("<q", d, anim_file + 8)
    return data + 0xC


def events(d, anim_id):
    header = anim_offsets(d)[anim_id]
    (ev,) = struct.unpack_from("<q", d, header)
    (count,) = struct.unpack_from("<i", d, header + 0x20)
    out = []
    for e in range(count):
        st, en, data = struct.unpack_from("<3q", d, ev + 24 * e)
        (etype,) = struct.unpack_from("<i", d, data)
        (params,) = struct.unpack_from("<q", d, data + 8)
        out.append((struct.unpack_from("<f", d, st)[0], struct.unpack_from("<f", d, en)[0], etype,
                    struct.unpack_from("<8i", d, params) if params else None))
    return out


SFX_EVENT = 2104
SFX_GROUP = 2100


def add_events(d, anim_id, events, group_type):
    """Append events [(start_s, end_s, type, params i32[10])] to anim_id (which must have none),
    all in one group of group_type. Returns the new file bytes."""
    d = bytearray(d)
    header = anim_offsets(d)[anim_id]
    if struct.unpack_from("<i", d, header + 0x20)[0]:
        raise ValueError(f"{anim_id} already has events")

    def align(n):
        while len(d) % n:
            d.append(0)

    align(16)
    times = sorted({t for e in events for t in e[:2]})
    times_off = len(d)
    for t in times:
        d += struct.pack("<f", t)
    align(16)
    headers_off = len(d)
    d += bytes(24 * len(events))
    align(16)
    for i, (start, end, etype, params) in enumerate(events):
        data_off = len(d)
        d += struct.pack("<iiq", etype, 0, data_off + 16)
        d += struct.pack("<10i", *(list(params) + [0] * (10 - len(params))))
        align(16)
        struct.pack_into("<3q", d, headers_off + 24 * i, times_off + 4 * times.index(start),
                         times_off + 4 * times.index(end), data_off)
    group_off = len(d)
    d += bytes(0x20)
    group_data_off = len(d)
    d += struct.pack("<iiq", group_type, 0, group_data_off + 16) + bytes(16)
    index_off = len(d)
    for i in range(len(events)):
        d += struct.pack("<q", headers_off + 24 * i)
    align(16)
    struct.pack_into("<qqqq", d, group_off, len(events), index_off, group_data_off, 0)

    struct.pack_into("<qqq", d, header, headers_off, group_off, times_off)
    struct.pack_into("<iii", d, header + 0x20, len(events), 1, len(times))
    struct.pack_into("<I", d, 0x0C, len(d))  # file size
    return bytes(d)


def sfx_event(start, end, ffx_id, dummy):
    return (start, end, SFX_EVENT, (-1, ffx_id, dummy, 1, 0))


def main(argv):
    if len(argv) >= 4 and argv[1] == "show":
        d = open(argv[2], "rb").read()
        anim = int(argv[3])
        (frames,) = struct.unpack_from("<I", d, length_field(d, anim))
        print(f"{anim}: length {frames} frames ({frames / 30:.2f} s @ 30 fps)")
        for ev in events(d, anim):
            print("  ", ev)
    elif len(argv) == 6 and argv[1] == "set-length":
        d = bytearray(open(argv[2], "rb").read())
        anim, frames = int(argv[4]), int(argv[5])
        off = length_field(d, anim)
        (old,) = struct.unpack_from("<I", d, off)
        struct.pack_into("<I", d, off, frames)
        open(argv[3], "wb").write(d)
        print(f"{anim}: length {old} -> {frames} frames ({frames / 30:.2f} s) -> {argv[3]}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
