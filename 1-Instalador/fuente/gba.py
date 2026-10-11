#!/usr/bin/env python3
"""Utilidades comunes para construir los parches de traducción (ROMs de GBA)."""
import re
import struct

GBA = 0x08000000
CMD = re.compile(r"(\{[^}]*\})")


# ------------------------------------------------------------- versiones ---

def elegir_version(rom, versiones):
    """Devuelve los datos de la versión (americana o europea) según el código del cartucho."""
    codigo = bytes(rom[0xAC:0xB0])
    if codigo not in versiones:
        raise ValueError("ROM no reconocido (código %r); valen: %s"
                         % (codigo, ", ".join(c.decode() for c in versiones)))
    return versiones[codigo]


def avisar_sha1(rom, version):
    import hashlib
    if hashlib.sha1(rom).hexdigest() != version["sha1"]:
        print("Aviso: el ROM no es exactamente el probado (se intenta igualmente).")


# ------------------------------------------------------------------ IPS ---

def crear_ips(original, nuevo):
    """Genera un parche IPS con las diferencias entre dos ROMs del mismo tamaño."""
    if len(original) != len(nuevo):
        raise ValueError("los ROMs deben medir lo mismo")
    if len(nuevo) > 0x1000000:
        raise ValueError("IPS no admite más de 16 MB")
    tramos = []
    i, n = 0, len(nuevo)
    while i < n:
        if original[i] == nuevo[i]:
            i += 1
            continue
        j = i + 1
        hueco = 0
        fin = j
        while j < n and hueco <= 8:
            if original[j] != nuevo[j]:
                fin = j + 1
                hueco = 0
            else:
                hueco += 1
            j += 1
        tramos.append((i, fin))
        i = fin
    out = bytearray(b"PATCH")
    for a, b in tramos:
        while a < b:
            if a == 0x454F46:          # "EOF": no puede ser el inicio de un registro
                a -= 1
            t = min(b - a, 0xFFFF)
            out += a.to_bytes(3, "big") + t.to_bytes(2, "big") + nuevo[a:a + t]
            a += t
    out += b"EOF"
    return bytes(out)


# ---------------------------------------------------------- traducciones ---

def leer_glosario(ruta):
    """Archivo 'inglés = español' -> dict."""
    g = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.rstrip("\n")
            if not linea.strip() or linea.lstrip().startswith("#"):
                continue
            k, _, v = linea.partition(" = ")
            g[k.strip()] = v.strip()
    return g


def leer_entradas(ruta, base=16):
    """Archivo de entradas '@ID texto' -> {id: (literal?, texto)}.

    '@ID texto'            una línea (se ajusta sola)
    '@ID' + líneas         varias líneas que se unen con espacios (se ajusta sola)
    '@ID= texto' / '@ID='  texto literal: se respetan espacios y saltos de línea
                           ({sp} es un espacio explícito, útil al principio o al final)
    """
    entradas = {}
    actual = None
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.rstrip("\n")
            if linea.startswith("@"):
                m = re.match(r"@([0-9A-Fa-f]+)(=?)(?: (.*))?$", linea)
                if not m:
                    raise ValueError("entrada mal escrita: %r" % linea)
                actual = int(m.group(1), base)
                if actual in entradas:
                    raise ValueError("entrada repetida: %03X" % actual)
                entradas[actual] = [bool(m.group(2)), [m.group(3)] if m.group(3) is not None else []]
            elif actual is not None and entradas[actual][0]:
                entradas[actual][1].append(linea)
            elif linea.startswith("#") or not linea.strip():
                continue
            elif actual is None:
                raise ValueError("texto fuera de una entrada: %r" % linea)
            else:
                entradas[actual][1].append(linea.strip())
    res = {}
    for k, (literal, lineas) in entradas.items():
        if literal:
            while lineas and not lineas[-1].strip():
                lineas.pop()
            res[k] = (True, "\n".join(lineas).replace("{sp}", " "))   # {sp} = espacio explícito
        else:
            res[k] = (False, " ".join(lineas))
    return res


class Medidor:
    """Mide texto en píxeles con la tabla de anchos de la fuente."""

    def __init__(self, ancho_de, ancho_cmd=10):
        self.ancho_de = ancho_de
        self.ancho_cmd = ancho_cmd

    def px(self, texto):
        total = 0
        for trozo in CMD.split(texto):
            if trozo.startswith("{"):
                total += self.ancho_cmd
            else:
                total += sum(self.ancho_de(c) for c in trozo)
        return total

    def ajustar(self, texto, ancho):
        """Parte `texto` en líneas de como mucho `ancho` píxeles."""
        lineas, actual = [], ""
        for palabra in texto.split():
            prueba = palabra if not actual else actual + " " + palabra
            if actual and self.px(prueba) > ancho:
                lineas.append(actual)
                actual = palabra
            else:
                actual = prueba
        if actual:
            lineas.append(actual)
        return lineas


def componer_dialogo(texto, medidor, ancho, max_lineas, salto="\n", pausa="{05}{09}"):
    """Texto con comandos -> cadena final con saltos de línea y cuadros extra si hacen falta."""
    out = []
    for trozo in CMD.split(texto):
        if trozo.startswith("{"):
            out.append(trozo)
            continue
        trozo = trozo.strip()
        if not trozo:
            continue
        lineas = medidor.ajustar(trozo, ancho)
        paginas = [lineas[i:i + max_lineas] for i in range(0, len(lineas), max_lineas)]
        out.append(pausa.join(salto.join(p) + salto for p in paginas))
    return "".join(out)


# ------------------------------------------------------------- inyección ---

class EspacioLibre:
    def __init__(self, inicio, fin, alineacion=4):
        self.pos, self.fin, self.alineacion = inicio, fin, alineacion
        self.inicio = inicio

    def reservar(self, n):
        a = self.alineacion
        self.pos = (self.pos + a - 1) // a * a
        if self.pos + n > self.fin:
            raise ValueError("no queda espacio libre en el ROM")
        p = self.pos
        self.pos += n
        return p


def reapuntar(rom, tabla, nuevas, libre, cabecera, final):
    """Escribe `nuevas` {id: bytes} en espacio libre y actualiza la tabla de punteros."""
    hechas = {}
    for tid in sorted(nuevas):
        datos = cabecera + nuevas[tid] + final
        if datos not in hechas:
            p = libre.reservar(len(datos))
            rom[p:p + len(datos)] = datos
            hechas[datos] = p
        struct.pack_into("<I", rom, tabla + 4 * tid, hechas[datos] + GBA)
