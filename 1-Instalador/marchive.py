#!/usr/bin/env python3
"""Lectura/escritura minima del formato MArchive de M2 (alldata.psb.m + alldata.bin).

Implementacion propia en Python puro (solo libreria estandar):
  - "mdf": zlib + XOR con un flujo de claves Mersenne Twister sembrado con MD5(clave + nombre)
  - PSB: arbol binario de objetos con el indice de archivos (file_info)
"""
import hashlib
import struct
import zlib

# ---------------------------------------------------------------- MT19937 ---


class MT19937:
    def __init__(self):
        self.mt = [0] * 624
        self.idx = 625

    def init_genrand(self, s):
        mt = self.mt
        mt[0] = s & 0xFFFFFFFF
        for i in range(1, 624):
            mt[i] = (1812433253 * (mt[i - 1] ^ (mt[i - 1] >> 30)) + i) & 0xFFFFFFFF
        self.idx = 624

    def init_by_array(self, key):
        self.init_genrand(19650218)
        mt = self.mt
        i, j = 1, 0
        n = len(key)
        for _ in range(max(624, n)):
            mt[i] = ((mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1664525)) + key[j] + j) & 0xFFFFFFFF
            i += 1
            j += 1
            if i >= 624:
                mt[0] = mt[623]
                i = 1
            if j >= n:
                j = 0
        for _ in range(623):
            mt[i] = ((mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1566083941)) - i) & 0xFFFFFFFF
            i += 1
            if i >= 624:
                mt[0] = mt[623]
                i = 1
        mt[0] = 0x80000000

    def genrand(self):
        mt = self.mt
        if self.idx >= 624:
            for k in range(624):
                y = (mt[k] & 0x80000000) | (mt[(k + 1) % 624] & 0x7FFFFFFF)
                mt[k] = mt[(k + 397) % 624] ^ (y >> 1) ^ (0x9908B0DF if y & 1 else 0)
            self.idx = 0
        y = mt[self.idx]
        self.idx += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        return y & 0xFFFFFFFF


# -------------------------------------------------------------------- MDF ---

def keystream(seed, name, key_length):
    """Flujo de claves para el archivo `name` (solo el nombre base, en minusculas)."""
    digest = hashlib.md5((seed + name.lower()).encode("utf-8")).digest()
    mt = MT19937()
    mt.init_by_array(list(struct.unpack("<4I", digest)))
    out = bytearray()
    while len(out) < key_length:
        out += struct.pack("<I", mt.genrand())
    return bytes(out[:key_length])


def xor(data, ks):
    n = len(data)
    reps = ks * (n // len(ks) + 1)
    return (int.from_bytes(data, "little") ^ int.from_bytes(reps[:n], "little")).to_bytes(n, "little")


def mdf_unpack(blob, seed, name, key_length):
    if blob[:4] != b"mdf\0":
        raise ValueError("no es un archivo mdf: %r" % blob[:4])
    size = struct.unpack_from("<I", blob, 4)[0]
    raw = zlib.decompress(xor(blob[8:], keystream(seed, name, key_length)))
    if len(raw) != size:
        raise ValueError("tamano inesperado en %s: %d != %d" % (name, len(raw), size))
    return raw


def mdf_pack(raw, seed, name, key_length, level=9):
    comp = zlib.compress(raw, level)
    return b"mdf\0" + struct.pack("<I", len(raw)) + xor(comp, keystream(seed, name, key_length))


# -------------------------------------------------------------------- PSB ---

class Res:
    """Referencia a un recurso (chunk) del PSB; se conserva tal cual."""

    def __init__(self, index, extra=False):
        self.index, self.extra = index, extra

    def __repr__(self):
        return "Res(%d%s)" % (self.index, ",extra" if self.extra else "")


class F32(float):
    pass


def _uint(b):
    return int.from_bytes(b, "little")


def _min_unsigned(v):
    n = 1
    while v >= (1 << (8 * n)):
        n += 1
    return n


def _enc_array(vals):
    cnt = len(vals)
    cn = _min_unsigned(cnt)
    en = _min_unsigned(max(vals)) if vals else 1
    out = bytearray([0x0C + cn]) + cnt.to_bytes(cn, "little") + bytes([0x0C + en])
    for v in vals:
        out += v.to_bytes(en, "little")
    return bytes(out)


class PSB:
    def __init__(self, data):
        self.data = data
        if data[:4] != b"PSB\0":
            raise ValueError("no es un PSB")
        self.version, self.encrypt = struct.unpack_from("<HH", data, 4)
        if self.encrypt:
            raise ValueError("cabecera PSB cifrada: no soportado")
        (self.header_len, self.off_names, self.off_strings, self.off_strdata,
         self.off_chunk_off, self.off_chunk_len, self.off_chunk_data,
         self.off_entries) = struct.unpack_from("<8I", data, 8)
        self.names = self._read_names()
        self.str_offsets, _ = self._read_array(self.off_strings)
        self.root = self._read_value(self.off_entries)[0]

    # -- lectura
    def _read_array(self, pos):
        d = self.data
        cn = d[pos] - 0x0C
        if not 1 <= cn <= 8:
            raise ValueError("array PSB invalido en 0x%x" % pos)
        cnt = _uint(d[pos + 1:pos + 1 + cn])
        pos += 1 + cn
        en = d[pos] - 0x0C
        pos += 1
        vals = [_uint(d[pos + i * en:pos + (i + 1) * en]) for i in range(cnt)]
        return vals, pos + cnt * en

    def _read_names(self):
        charset, p = self._read_array(self.off_names)
        tree, p = self._read_array(p)
        indexes, p = self._read_array(p)
        names = []
        for idx in indexes:
            chars = bytearray()
            c = tree[idx]
            while c != 0:
                code = tree[c]
                chars.append(c - charset[code])
                c = code
            names.append(bytes(reversed(chars)).decode("utf-8"))
        return names

    def _string(self, i):
        start = self.off_strdata + self.str_offsets[i]
        end = self.data.index(b"\0", start)
        return self.data[start:end].decode("utf-8")

    def _read_value(self, pos):
        d = self.data
        t = d[pos]
        pos += 1
        if t == 0x01:
            return None, pos
        if t == 0x02:
            return False, pos
        if t == 0x03:
            return True, pos
        if 0x04 <= t <= 0x0C:
            n = t - 0x04
            return int.from_bytes(d[pos:pos + n], "little", signed=True), pos + n
        if 0x0D <= t <= 0x14:
            vals, end = self._read_array(pos - 1)
            return tuple(vals), end
        if 0x15 <= t <= 0x18:
            n = t - 0x14
            return self._string(_uint(d[pos:pos + n])), pos + n
        if 0x19 <= t <= 0x1C:
            n = t - 0x18
            return Res(_uint(d[pos:pos + n])), pos + n
        if t == 0x1D:
            return F32(0.0), pos
        if t == 0x1E:
            return F32(struct.unpack_from("<f", d, pos)[0]), pos + 4
        if t == 0x1F:
            return struct.unpack_from("<d", d, pos)[0], pos + 8
        if t == 0x20:
            offs, base = self._read_array(pos)
            return [self._read_value(base + o)[0] for o in offs], None
        if t == 0x21:
            nidx, p = self._read_array(pos)
            offs, base = self._read_array(p)
            return {self.names[n]: self._read_value(base + o)[0] for n, o in zip(nidx, offs)}, None
        if 0x22 <= t <= 0x25:
            n = t - 0x21
            return Res(_uint(d[pos:pos + n]), True), pos + n
        raise ValueError("tipo PSB desconocido 0x%02x en 0x%x" % (t, pos - 1))

    # -- escritura (se conservan nombres y cadenas; solo se reescribe el arbol)
    def _enc_value(self, v, strings):
        if v is None:
            return b"\x01"
        if v is False:
            return b"\x02"
        if v is True:
            return b"\x03"
        if isinstance(v, F32):
            return b"\x1d" if v == 0 else b"\x1e" + struct.pack("<f", v)
        if isinstance(v, float):
            return b"\x1f" + struct.pack("<d", v)
        if isinstance(v, int):
            if v == 0:
                return b"\x04"
            n = 1
            while not -(1 << (8 * n - 1)) <= v < (1 << (8 * n - 1)):
                n += 1
            return bytes([0x04 + n]) + v.to_bytes(n, "little", signed=True)
        if isinstance(v, tuple):
            return _enc_array(list(v))
        if isinstance(v, str):
            i = strings[v]
            n = _min_unsigned(i)
            return bytes([0x14 + n]) + i.to_bytes(n, "little")
        if isinstance(v, Res):
            n = _min_unsigned(v.index)
            return bytes([(0x21 if v.extra else 0x18) + n]) + v.index.to_bytes(n, "little")
        if isinstance(v, list):
            offs, body = [], bytearray()
            for item in v:
                offs.append(len(body))
                body += self._enc_value(item, strings)
            return b"\x20" + _enc_array(offs) + bytes(body)
        if isinstance(v, dict):
            nidx = {n: i for i, n in enumerate(self.names)}
            items = sorted(v.items(), key=lambda kv: nidx[kv[0]])
            offs, body = [], bytearray()
            for _, item in items:
                offs.append(len(body))
                body += self._enc_value(item, strings)
            return b"\x21" + _enc_array([nidx[k] for k, _ in items]) + _enc_array(offs) + bytes(body)
        raise TypeError(type(v))

    def serialize(self):
        """Reconstruye el PSB conservando todas las secciones salvo el arbol de entradas."""
        d = self.data
        strings = {self._string(i): i for i in range(len(self.str_offsets))}
        entries = self._enc_value(self.root, strings)
        # Secciones originales, ordenadas por su posicion en el archivo.
        fields = ["off_names", "off_strings", "off_strdata", "off_chunk_off",
                  "off_chunk_len", "off_chunk_data", "off_entries"]
        hdr_fmt_extra = []
        if self.version >= 4:
            hdr_fmt_extra = list(struct.unpack_from("<3I", d, 0x2C))
        bounds = sorted(set([getattr(self, f) for f in fields] + hdr_fmt_extra + [len(d)]))
        first = bounds[0]
        out = bytearray(d[:first])
        new_off = {}
        for start, end in zip(bounds, bounds[1:]):
            new_off[start] = len(out)
            out += entries if start == self.off_entries else d[start:end]
        new_off[len(d)] = len(out)
        for i, f in enumerate(fields):
            struct.pack_into("<I", out, 12 + 4 * i, new_off[getattr(self, f)])
        if self.version >= 4:
            for i, o in enumerate(hdr_fmt_extra):
                struct.pack_into("<I", out, 0x2C + 4 * i, new_off[o])
        if self.version >= 3:
            # Adler-32 de los desplazamientos de la cabecera (bytes 8..0x28)
            struct.pack_into("<I", out, 0x28, zlib.adler32(bytes(out[8:0x28])) & 0xFFFFFFFF)
        return bytes(out)
