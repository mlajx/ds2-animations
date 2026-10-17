#!/usr/bin/env python3
"""Minimal Dark Souls II: SotFS archive reader (BHD5 header + BDT data).

The .bhd header is RSA-encrypted with the public key in the matching
*KeyCode.pem. Each file entry carries an AES-128-ECB key plus the byte
ranges of the file that are encrypted with it.

Usage:
  ds2unpack.py GAME_DIR ARCHIVE list
  ds2unpack.py GAME_DIR ARCHIVE find PATH [PATH...]
  ds2unpack.py GAME_DIR ARCHIVE extract OUT_DIR PATH [PATH...]
  ds2unpack.py GAME_DIR ARCHIVE extract-hash OUT_DIR HASH [HASH...]

ARCHIVE is the base name, e.g. GameData, LqChr (Ebl.bhd/.bdt/KeyCode.pem added).
"""
import base64
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def read_pem_public_key(path):
    der = base64.b64decode("".join(
        l for l in Path(path).read_text().splitlines() if not l.startswith("-----")))

    # PKCS#1 RSAPublicKey ::= SEQUENCE { modulus INTEGER, publicExponent INTEGER }
    def read_tlv(buf, pos):
        tag = buf[pos]
        length = buf[pos + 1]
        pos += 2
        if length & 0x80:
            n = length & 0x7F
            length = int.from_bytes(buf[pos:pos + n], "big")
            pos += n
        return tag, buf[pos:pos + length], pos + length

    _, seq, _ = read_tlv(der, 0)
    _, n_bytes, pos = read_tlv(seq, 0)
    _, e_bytes, _ = read_tlv(seq, pos)
    return int.from_bytes(n_bytes, "big"), int.from_bytes(e_bytes, "big")


def rsa_decrypt_bhd(data, n, e):
    # Raw RSA with the public key, block by block; each plaintext block is key_size - 1 bytes.
    key_size = (n.bit_length() + 7) // 8
    out = bytearray()
    for off in range(0, len(data), key_size):
        c = int.from_bytes(data[off:off + key_size], "big")
        out += pow(c, e, n).to_bytes(key_size - 1, "big")
    return bytes(out)


def path_hash(path):
    h = 0
    for ch in path.lower().replace("\\", "/"):
        h = (h * 37 + ord(ch)) & 0xFFFFFFFF
    return h


class Entry:
    __slots__ = ("hash", "padded_size", "offset", "aes_key", "aes_ranges")


def parse_bhd5(bhd):
    if bhd[:4] != b"BHD5":
        raise ValueError("decrypted header is not BHD5: %r" % bhd[:16])
    _flags, _one, _size, bucket_count, buckets_off, salt_len = struct.unpack_from("<iiiiii", bhd, 4)
    salt = bhd[28:28 + salt_len].decode("ascii", "replace")
    entries = {}
    for b in range(bucket_count):
        count, headers_off = struct.unpack_from("<ii", bhd, buckets_off + b * 8)
        for i in range(count):
            e = Entry()
            h_off = headers_off + i * 32
            e.hash, e.padded_size, e.offset, _salted_hash_off, aes_off = struct.unpack_from("<IiqqQ", bhd, h_off)
            e.aes_key, e.aes_ranges = None, []
            if aes_off:
                e.aes_key = bhd[aes_off:aes_off + 16]
                (range_count,) = struct.unpack_from("<i", bhd, aes_off + 16)
                for r in range(range_count):
                    e.aes_ranges.append(struct.unpack_from("<qq", bhd, aes_off + 20 + r * 16))
            entries[e.hash] = e
    return salt, entries


class Archive:
    def __init__(self, game_dir, name):
        game_dir = Path(game_dir)
        n, e = read_pem_public_key(game_dir / f"{name}KeyCode.pem")
        bhd = rsa_decrypt_bhd((game_dir / f"{name}Ebl.bhd").read_bytes(), n, e)
        self.salt, self.entries = parse_bhd5(bhd)
        self.bdt_path = game_dir / f"{name}Ebl.bdt"

    def read(self, entry):
        with open(self.bdt_path, "rb") as f:
            f.seek(entry.offset)
            data = bytearray(f.read(entry.padded_size))
        if entry.aes_key:
            dec = Cipher(algorithms.AES(entry.aes_key), modes.ECB()).decryptor()
            for start, end in entry.aes_ranges:
                if start == -1 or end <= start:
                    continue
                data[start:end] = dec.update(bytes(data[start:end]))
        return bytes(data)


def main(argv):
    if len(argv) < 4:
        sys.exit(__doc__)
    game_dir, name, cmd, *args = argv[1:]
    arc = Archive(game_dir, name)
    if cmd == "list":
        print(f"salt={arc.salt!r} entries={len(arc.entries)}")
        for h, e in sorted(arc.entries.items(), key=lambda kv: kv[1].offset):
            print(f"{h:08x} off={e.offset:#x} size={e.padded_size} enc_ranges={len(e.aes_ranges)}")
    elif cmd == "find":
        for p in args:
            h = path_hash(p)
            print(f"{'FOUND ' if h in arc.entries else 'missing'} {h:08x} {p}")
    elif cmd in ("extract", "extract-hash"):
        out_dir = Path(args[0])
        for p in args[1:]:
            h = int(p, 16) if cmd == "extract-hash" else path_hash(p)
            e = arc.entries.get(h)
            if not e:
                print(f"missing {p}")
                continue
            dest = out_dir / (f"{h:08x}.bin" if cmd == "extract-hash" else p.lstrip("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(arc.read(e))
            print(f"wrote {dest} ({e.padded_size} bytes)")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
