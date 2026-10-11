#!/usr/bin/env python3
"""Construye la traducción al español de Castlevania: Aria of Sorrow (ROMs US y EU de la colección).

Uso: python construir.py ROM_ORIGINAL.bin [salida.ips] [rom_traducido.gba]

El ROM original es el que trae Castlevania Advance Collection
(system/roms/03_Akatsuki_US.patch_210623m.bin o 03_Akatsuki_EU...). Las dos
versiones traen los mismos textos en inglés, francés y alemán; solo cambian las
direcciones, que se eligen por el código del cartucho. El parche resultante solo
contiene los textos traducidos y los glifos nuevos de la fuente.
"""
import os
import re
import struct
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
import gba  # noqa: E402

# Direcciones por versión (código del cartucho):
#   tabla           punteros a cadenas (id * 4); se traduce la parte inglesa
#   fuente/pequena  glifos a 1 bit desde el carácter 0x20 (14 y 10 bytes por carácter)
#   anchos*         4 bytes por carácter desde 0x20: [desplaz., ancho, 0, 0]
VERSIONES = {
    b"A2CE": {"nombre": "americana", "tabla": 0x506B38, "fuente": 0x50A136, "pequena": 0x509876,
              "anchos": 0xE2B4C, "anchos_pequena": 0xE2EC0,
              "sha1": "f2869a861f1be637a1d1b57009cb42cc06b82e09"},
    b"A2CP": {"nombre": "europea", "tabla": 0x506B70, "fuente": 0x50A16E, "pequena": 0x5098AE,
              "anchos": 0xE2B60, "anchos_pequena": 0xE2ED4,
              "sha1": "02dc76fdfe464877202b3d59cd102d626d194fe6"},
}
N_INGLES = 0x3C4               # ids 0x000-0x3C3: inglés (después vienen francés y alemán)
LIBRE = (0x680000, 0x6FFFF0)   # zona vacía del ROM donde van las cadenas nuevas
TABLA_TEXTOS = GRANDE = PEQUENA = None    # se fijan en configurar()

MULTI = {1: 2, 2: 1, 3: 1, 7: 1, 8: 1}   # comandos de texto con bytes de datos

# (primer id, último id, modo, ancho en px, líneas)
REGIONES = [
    (0x000, 0x00A, "nombre", 73, 1),     # personajes
    (0x00B, 0x00B, "dialogo", 205, 7),   # introducción
    (0x00C, 0x05A, "dialogo", 174, 3),   # escenas
    (0x05B, 0x15B, "nombre", 80, 1),     # objetos y almas
    (0x15C, 0x1E3, "desc", 189, 2),      # descripciones de objetos
    (0x1E4, 0x25C, "desc", 176, 2),      # descripciones de almas
    (0x25D, 0x2CD, "nombre", 80, 1),     # enemigos
    (0x2CE, 0x33E, "desc", 200, 2),      # descripciones de enemigos
    (0x33F, 0x349, "desc", 214, 2),      # precios
    (0x34A, 0x34F, "desc", 80, 2),       # preguntas (guardar)
    (0x350, 0x351, "desc", 106, 2),      # menú de equipo
    (0x352, 0x353, "desc", 127, 2),      # configuración
    (0x354, 0x35E, "desc", 214, 2),      # selección de partida
    (0x35F, 0x361, "desc", 139, 2),      # avisos
    (0x362, 0x369, "desc", 135, 2),      # menú de pausa
    (0x36A, 0x36B, "desc", 85, 2),       # pausa / guardado
    (0x36C, 0x371, "nombre", 80, 1),     # tipos de alma
    (0x372, 0x376, "desc", 172, 2),      # intercambio de almas
    (0x377, 0x37C, "desc", 214, 2),      # selección de partida
    (0x37D, 0x37F, "desc", 176, 2),      # ayuda de almas
    (0x380, 0x392, "desc", 214, 2),      # selección de partida y sonido
    (0x393, 0x3AF, "nombre", 124, 1),    # música
    (0x3B0, 0x3B6, "desc", 172, 2),      # tienda y varios
    (0x3B7, 0x3C3, "nombre", 118, 1),    # zonas
]


# ----------------------------------------------------------------- texto ---

def decodificar(b):
    out, i = [], 0
    while i < len(b):
        c = b[i]
        if c == 6:
            out.append("\n")
            i += 1
        elif c < 0x20:
            n = MULTI.get(c, 0)
            out.append("{" + " ".join("%02X" % x for x in b[i:i + 1 + n]) + "}")
            i += 1 + n
        else:
            out.append(bytes([c]).decode("latin-1"))
            i += 1
    return "".join(out)


def codificar(s):
    out, i = bytearray(), 0
    while i < len(s):
        ch = s[i]
        if ch == "{":
            j = s.index("}", i)
            out += bytes(int(x, 16) for x in s[i + 1:j].split())
            i = j + 1
        elif ch == "\n":
            out.append(6)
            i += 1
        else:
            out += ch.encode("latin-1")
            i += 1
    return bytes(out)


def leer_cadena(rom, tid):
    p = struct.unpack_from("<I", rom, TABLA_TEXTOS + 4 * tid)[0] - gba.GBA
    i = p + 2
    while rom[i] != 0x0A:
        c = rom[i]
        i += 1 + (MULTI.get(c, 0) if c < 0x20 else 0)
    return decodificar(rom[p + 2:i])


# ---------------------------------------------------------------- fuente ---

class Fuente:
    """Fuente de 1 bit por píxel: `paso` bytes por carácter desde 0x20, `filas` filas útiles."""

    def __init__(self, base, paso, filas, anchos, marca):
        self.base, self.paso, self.filas, self.anchos, self.marca = base, paso, filas, anchos, marca

    def glifo(self, rom, ch):
        p = self.base + (ord(ch.encode("latin-1")) - 0x20) * self.paso
        return ["".join("#" if rom[p + r] & (0x80 >> x) else "." for x in range(7)) + "."
                for r in range(self.filas)]

    def poner(self, rom, ch, filas, ancho):
        c = ord(ch.encode("latin-1"))
        assert len(filas) == self.filas and all(len(f) == 8 for f in filas), ch
        p = self.base + (c - 0x20) * self.paso
        for r, fila in enumerate(filas):
            rom[p + r] = sum(0x80 >> x for x in range(7) if fila[x] == "#") | self.marca
        rom[self.anchos + (c - 0x20) * 4] = 0
        rom[self.anchos + (c - 0x20) * 4 + 1] = ancho

    def ancho(self, rom, ch):
        return rom[self.anchos + (ord(ch.encode("latin-1")) - 0x20) * 4 + 1]


# Fuente grande (diálogos y descripciones) y pequeña (nombres).
def configurar(rom):
    global TABLA_TEXTOS, GRANDE, PEQUENA
    v = gba.elegir_version(rom, VERSIONES)
    TABLA_TEXTOS = v["tabla"]
    GRANDE = Fuente(v["fuente"], 14, 12, v["anchos"], marca=1)
    PEQUENA = Fuente(v["pequena"], 10, 8, v["anchos_pequena"], marca=0)
    return v


AGUDO = ["....#...", "...#...."]
AGUDO_I = ["...#....", "..#....."]
TILDE = ["..##.#..", ".#..#..."]
VACIO = "........"


def girar(filas):
    """Gira un glifo 180 grados (para sacar ¿ de ?)."""
    return [f[6::-1] + "." for f in reversed(filas)]


def ampliar_fuentes(rom):
    """Añade á í ó ú ñ Ñ Í Ó Ú ¿ ¡ a las dos fuentes.

    El juego ya trae é É Á ü Ü (las usa en francés y alemán), así que los glifos
    nuevos se componen a partir de los que existen: la vocal con otro acento
    y el acento agudo de la é.
    """
    f = GRANDE
    g = lambda ch: f.glifo(rom, ch)
    f.poner(rom, "á", AGUDO + g("à")[2:], 6)
    f.poner(rom, "ó", AGUDO + g("ô")[2:], 6)
    f.poner(rom, "ú", AGUDO + g("ù")[2:], 6)
    f.poner(rom, "í", AGUDO_I + g("ï")[2:], 4)
    f.poner(rom, "ñ", TILDE + g("n")[2:], 6)
    N, I, U = g("N"), g("I"), g("Ü")
    # Mayúsculas: el cuerpo se comprime a 8 filas (2-9), como hace el juego con É.
    f.poner(rom, "Ñ", TILDE + [N[0], N[2], N[3], N[4], N[5], N[6], N[7], N[9]] + N[10:], 6)
    f.poner(rom, "Ó", AGUDO + g("Ö")[2:], 6)
    f.poner(rom, "Ú", AGUDO + [U[3]] + U[3:], 6)
    f.poner(rom, "Í", AGUDO_I + [I[0]] + I[1:7] + [I[9]] + I[10:], 4)
    f.poner(rom, "¿", [VACIO, VACIO] + girar(g("?")[:10]), 6)        # baja de la línea base
    f.poner(rom, "¡", [VACIO, VACIO] + g("!")[9::-1], 4)

    f = PEQUENA
    g = lambda ch: f.glifo(rom, ch)
    f.poner(rom, "á", AGUDO + g("à")[2:], 6)
    f.poner(rom, "ó", AGUDO + g("ô")[2:], 6)
    f.poner(rom, "ú", AGUDO + g("ù")[2:], 6)
    f.poner(rom, "í", AGUDO_I + g("î")[2:], 4)
    f.poner(rom, "ñ", [".##.#...", "#..#...."] + g("n")[2:], 5)
    N, I, U = g("N"), g("I"), g("Û")
    f.poner(rom, "Ñ", TILDE + [N[0], N[1], N[2], N[3], N[6], N[7]], 6)
    f.poner(rom, "Ó", AGUDO + g("Ö")[2:], 6)
    f.poner(rom, "Ú", AGUDO + [U[3]] + U[3:], 6)
    f.poner(rom, "Í", AGUDO_I + [I[0], I[1], I[2], I[3], I[6], I[7]], 4)
    f.poner(rom, "¿", girar(g("?")[:7]) + [VACIO], 6)
    f.poner(rom, "¡", g("!")[6::-1] + [VACIO], 2)


# ----------------------------------------------------------- construcción ---

def construir(rom_original):
    configurar(rom_original)
    rom = bytearray(rom_original)
    ampliar_fuentes(rom)
    medidor = gba.Medidor(lambda c: GRANDE.ancho(rom, c))
    medidor_nombres = gba.Medidor(lambda c: PEQUENA.ancho(rom, c))

    glosario = gba.leer_glosario(os.path.join(AQUI, "nombres.txt"))
    entradas = {}
    for archivo in ("textos.txt", "dialogos.txt"):
        for k, v in gba.leer_entradas(os.path.join(AQUI, archivo)).items():
            if k in entradas:
                raise ValueError("entrada repetida entre archivos: %03X" % k)
            entradas[k] = v

    avisos, nuevas = [], {}
    sin_traducir = 0
    for ini, fin, modo, ancho, max_lineas in REGIONES:
        for tid in range(ini, fin + 1):
            original = leer_cadena(rom_original, tid)
            cola = "\n" if original.rstrip(" ").endswith("\n") else ""
            if tid in entradas:
                literal, texto = entradas[tid]
                if literal:
                    final = texto + cola
                elif modo == "dialogo":
                    final = gba.componer_dialogo(texto, medidor, ancho, max_lineas)
                elif modo == "nombre":
                    final = texto + cola
                else:
                    lineas = medidor.ajustar(texto, ancho)
                    if len(lineas) > max_lineas:
                        avisos.append("%03X ocupa %d líneas: %s" % (tid, len(lineas), texto))
                    final = "\n".join(lineas) + cola
            elif original.strip() in glosario:
                final = glosario[original.strip()] + cola
            else:
                if original.strip() and re.search(r"[A-Za-z]{3}", original):
                    sin_traducir += 1
                    avisos.append("%03X sin traducir: %r" % (tid, original[:40]))
                continue
            if modo == "nombre" and medidor_nombres.px(final.strip()) > ancho:
                avisos.append("%03X nombre ancho (%d px > %d): %s"
                              % (tid, medidor_nombres.px(final.strip()), ancho, final.strip()))
            for linea in gba.CMD.sub("", final).split("\n") if modo == "dialogo" else final.split("\n"):
                if modo != "nombre" and not entradas.get(tid, (False,))[0] and medidor.px(linea) > ancho:
                    avisos.append("%03X línea ancha (%d px): %s" % (tid, medidor.px(linea), linea))
            if final != original:
                nuevas[tid] = codificar(final)

    libre = gba.EspacioLibre(*LIBRE)
    gba.reapuntar(rom, TABLA_TEXTOS, nuevas, libre, b"\x01\x00", b"\x0A")
    return bytes(rom), avisos, len(nuevas), libre.pos - libre.inicio


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    original = open(argv[0], "rb").read()
    gba.avisar_sha1(original, gba.elegir_version(original, VERSIONES))
    rom, avisos, n, usado = construir(original)
    for a in avisos:
        print("  !", a)
    salida = argv[1] if len(argv) > 1 else os.path.join(AQUI, "aos-es.ips")
    ips = gba.crear_ips(original, rom)
    with open(salida, "wb") as f:
        f.write(ips)
    if len(argv) > 2:
        with open(argv[2], "wb") as f:
            f.write(rom)
    print("%d cadenas traducidas, %d bytes de texto, parche de %d bytes -> %s (%d avisos)"
          % (n, usado, len(ips), salida, len(avisos)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
