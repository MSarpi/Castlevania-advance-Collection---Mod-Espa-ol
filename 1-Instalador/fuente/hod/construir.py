#!/usr/bin/env python3
"""Construye la traducción al español de Castlevania: Harmony of Dissonance (ROMs US y EU de la colección).

Uso: python construir.py ROM_ORIGINAL.bin [salida.ips] [rom_traducido.gba]

El ROM original es el que trae Castlevania Advance Collection
(system/roms/02_Byakuya_US.patch_210520m.bin o 02_Byakuya_EU...). La versión
europea solo se diferencia de la americana en 267 bytes y usa las mismas direcciones.

Cómo guarda el texto este juego:
  - Cada carácter son 16 bits. Las mayúsculas, cifras y símbolos usan su código
    Shift-JIS de ancho completo y se dibujan con 6 píxeles de avance.
  - Los códigos desde 0x8540 son "proporcionales": indexan una tabla de 4 bytes
    [código del glifo (2), desplazamiento, ancho]. Hay una tabla para la fuente
    grande (diálogos) y otra para la pequeña (nombres), cada una con 0x26 entradas.
  - Los comandos son 0xF0xx.
Para el español se mueven las dos tablas a una zona vacía del ROM y se amplían
con á é í ó ú ñ ü ¿ ¡ Í, cuyos glifos se dibujan sobre caracteres japoneses que
la versión americana no usa.
"""
import os
import re
import struct
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
import gba  # noqa: E402

TABLA_TEXTOS = 0x495500
N_TEXTOS = 0x2AB
FUENTE_GRANDE = 0x496316       # 14 bytes por glifo: código (2) + 12 filas; este es el primer bitmap
FUENTE_PEQUENA = 0x495FAB      # 10 bytes por glifo: 3 de datos + 7 filas
PROP_GRANDE = 0xC5470          # tabla proporcional de la fuente grande
PROP_PEQUENA = 0xC5508         # tabla proporcional de la fuente pequeña
N_PROP = 0x26
LIT_PROP_GRANDE = 0x14D14      # dónde guarda el código la dirección de cada tabla
LIT_PROP_PEQUENA = 0x14F54
CMP_MAYUSCULAS = 0x143DC       # "cmp r0, #0x19": rango de mayúsculas de la fuente pequeña
CMP_MINUSCULAS = 0x14404       # ídem para minúsculas
LIBRE = (0x6B0000, 0x7F0000)
VERSIONES = {
    b"ACHE": {"nombre": "americana", "sha1": "58a562662f416846b7e3575da2844f2fda72f6c1"},
    b"ACHP": {"nombre": "europea", "sha1": "3997c7a3bd3b47165f78fe96e1d20e8037fea555"},
}

MULTI = {1, 2, 3, 7, 8}        # comandos con un dato de 16 bits

# Caracteres proporcionales originales, en el orden de la tabla (índice = código - 0x8540).
PROP_ORIGINAL = " ,.・:;!Iabcdefghijklmnopqrstuvwxyz'()$"

# Caracteres nuevos: (carácter, código del glifo, (despl., ancho) grande, (despl., ancho) pequeña)
# Los códigos 0x829C-0x82A0 y 0x827A-0x827E caen en los huecos de la fuente pequeña
# una vez ampliados sus rangos; 0x8194 ('#') ya tenía hueco propio (índice 0x50).
NUEVOS = [
    ("á", 0x829C, (0, 6), (0, 5)),
    ("é", 0x829D, (0, 6), (0, 5)),
    ("í", 0x829E, (2, 3), (2, 3)),
    ("ó", 0x829F, (0, 6), (0, 5)),
    ("ú", 0x82A0, (0, 6), (0, 5)),
    ("ñ", 0x8194, (0, 6), (0, 5)),
    ("ü", 0x82A1, (0, 6), (0, 5)),      # solo en la fuente grande
    ("¿", 0x82A2, (0, 6), (0, 6)),      # solo en la fuente grande
    ("¡", 0x82A3, (1, 4), (1, 4)),      # solo en la fuente grande
    ("Í", 0x827C, (1, 4), (2, 3)),
]
# Mayúsculas acentuadas de ancho fijo (código directo).
DIRECTOS = {"Á": 0x827A, "É": 0x827B, "Ó": 0x827D, "Ú": 0x827E, "Ñ": 0x82A4}
INDICE_PEQUENA = {0x827A: 0x1A, 0x827B: 0x1B, 0x827C: 0x1C, 0x827D: 0x1D, 0x827E: 0x1E,
                  0x829C: 0x3B, 0x829D: 0x3C, 0x829E: 0x3D, 0x829F: 0x3E, 0x82A0: 0x3F, 0x8194: 0x50}

SIMBOLOS = {"?": 0x8148, "-": 0x817C, "/": 0x815E, "+": 0x817B, '"': 0x8168, "%": 0x8193,
            "&": 0x8195, "*": 0x8196, "@": 0x8197, "=": 0x8181, "<": 0x8183, ">": 0x8184,
            "`": 0x8165, "~": 0x8160, "★": 0x819A}

# (primer id, último id, modo, ancho en px, líneas)
REGIONES = [
    (0x000, 0x009, "nombre", 84, 1),     # personajes
    (0x00A, 0x00A, "dialogo", 186, 5),   # introducción
    (0x00B, 0x021, "dialogo", 156, 3),   # escenas
    (0x022, 0x0F6, "nombre", 80, 1),     # objetos
    (0x0F7, 0x1CB, "desc", 206, 2),      # descripciones
    (0x1CC, 0x248, "nombre", 84, 1),     # enemigos
    (0x249, 0x280, "desc", 202, 2),      # menús
    (0x281, 0x283, "dialogo", 156, 3),   # mercader
    (0x284, 0x286, "desc", 186, 2),
    (0x287, 0x288, "dialogo", 156, 3),
    (0x289, 0x289, "desc", 202, 2),
    (0x28A, 0x28B, "dialogo", 156, 3),
    (0x28C, 0x2AA, "desc", 132, 2),      # música
]


# ----------------------------------------------------------------- texto ---

def _ancho_completo(ch):
    """Código Shift-JIS de ancho completo de un carácter ASCII."""
    o = ord(ch)
    if "0" <= ch <= "9":
        return 0x824F + o - 0x30
    if "A" <= ch <= "Z":
        return 0x8260 + o - 0x41
    if "a" <= ch <= "z":
        return 0x8281 + o - 0x61
    return None


def tabla_de_codigos():
    cod = {}
    for i, ch in enumerate(PROP_ORIGINAL):
        cod[ch] = 0x8540 + i
    for i, (ch, _, _, _) in enumerate(NUEVOS):
        cod[ch] = 0x8540 + N_PROP + i
    cod.update(DIRECTOS)
    cod.update(SIMBOLOS)
    for o in range(0x30, 0x7B):
        ch = chr(o)
        if ch not in cod and _ancho_completo(ch):
            cod[ch] = _ancho_completo(ch)
    return cod


CODIGOS = tabla_de_codigos()
DESCODIGOS = {v: k for k, v in CODIGOS.items()}
DESCODIGOS[0x8166] = "'"
DESCODIGOS[0x8167] = '"'


def leer_cadena(rom, tid):
    p = struct.unpack_from("<I", rom, TABLA_TEXTOS + 4 * tid)[0] - gba.GBA
    i, out = p + 2, []
    while True:
        h = struct.unpack_from("<H", rom, i)[0]
        i += 2
        if h == 0xF00A:
            break
        if h & 0xFF00 == 0xF000:
            c = h & 0xFF
            if c == 6:
                out.append("\n")
            elif c in MULTI:
                out.append("{%02X %04X}" % (c, struct.unpack_from("<H", rom, i)[0]))
                i += 2
            else:
                out.append("{%02X}" % c)
        elif h >= 0x8540 and h < 0x8540 + N_PROP:
            out.append(PROP_ORIGINAL[h - 0x8540].replace("・", "·"))
        else:
            out.append(DESCODIGOS.get(h, "{RAW %04X}" % h))
    return "".join(out)


def codificar(s):
    out, i = bytearray(), 0
    while i < len(s):
        ch = s[i]
        if ch == "{":
            j = s.index("}", i)
            partes = s[i + 1:j].split()
            if partes[0] == "RAW":
                out += struct.pack("<H", int(partes[1], 16))
            else:
                out += struct.pack("<H", 0xF000 | int(partes[0], 16))
                for p in partes[1:]:
                    out += struct.pack("<H", int(p, 16))
            i = j + 1
        elif ch == "\n":
            out += struct.pack("<H", 0xF006)
            i += 1
        else:
            if ch not in CODIGOS:
                raise ValueError("carácter sin código en HoD: %r" % ch)
            out += struct.pack("<H", CODIGOS[ch])
            i += 1
    return bytes(out)


# --------------------------------------------------------------- fuentes ---

def pos_grande(codigo):
    alto, bajo = codigo >> 8, codigo & 0xFF
    if bajo > 0x7E:
        bajo -= 1
    return FUENTE_GRANDE + (alto - 0x81) * 0xA48 + (bajo - 0x40) * 14


def glifo_grande(rom, ch):
    codigo = _ancho_completo(ch) or {"!": 0x8149}.get(ch) or SIMBOLOS[ch]
    p = pos_grande(codigo)
    return ["".join("#" if rom[p + r] & (0x80 >> x) else "." for x in range(8)) for r in range(12)]


def poner_grande(rom, codigo, filas):
    assert len(filas) == 12 and all(len(f) == 8 for f in filas), hex(codigo)
    p = pos_grande(codigo)
    assert struct.unpack_from(">H", rom, p - 2)[0] == codigo, "la fuente grande no tiene %04X" % codigo
    for r, fila in enumerate(filas):
        rom[p + r] = sum(0x80 >> x for x in range(8) if fila[x] == "#")


IDX_PEQ = {"?": 0x4E, "!": 0x4F}


def glifo_pequeno(rom, ch):
    if "A" <= ch <= "Z":
        idx = ord(ch) - 0x41
    elif "a" <= ch <= "z":
        idx = 0x20 + ord(ch) - 0x61
    else:
        idx = IDX_PEQ[ch]
    p = FUENTE_PEQUENA + idx * 10 + 3
    return ["".join("#" if rom[p + r] & (0x80 >> x) else "." for x in range(8)) for r in range(7)]


def poner_pequeno(rom, idx, filas):
    assert len(filas) == 7 and all(len(f) == 8 for f in filas), hex(idx)
    p = FUENTE_PEQUENA + idx * 10 + 3
    for r, fila in enumerate(filas):
        rom[p + r] = sum(0x80 >> x for x in range(8) if fila[x] == "#")


AGUDO = ["....#...", "...#...."]
TILDE = ["..##.#..", ".#..#..."]
DIERESIS = [".#...#..", "........"]
VACIO = "........"


def girar(filas):
    return [f[6::-1] + "." for f in reversed(filas)]


def sin(filas, *quitar):
    return [f for i, f in enumerate(filas) if i not in quitar]


def ampliar_fuentes(rom):
    g = lambda ch: glifo_grande(rom, ch)
    cod = dict((ch, c) for ch, c, _, _ in NUEVOS)
    cod.update(DIRECTOS)
    # --- fuente grande: minúsculas (cuerpo en filas 3-9, acento en 0-1)
    for ch, base in (("á", "a"), ("é", "e"), ("ó", "o"), ("ú", "u")):
        poner_grande(rom, cod[ch], AGUDO + g(base)[2:])
    poner_grande(rom, cod["í"], AGUDO + [VACIO] + g("i")[3:])
    poner_grande(rom, cod["ñ"], TILDE + g("n")[2:])
    poner_grande(rom, cod["ü"], DIERESIS + g("u")[2:])
    poner_grande(rom, cod["¿"], [VACIO, VACIO] + girar(g("?")[:10]))
    poner_grande(rom, cod["¡"], [VACIO, VACIO] + g("!")[9::-1])
    # --- fuente grande: mayúsculas (el cuerpo de 10 filas se comprime a 8)
    for ch, base in (("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U")):
        poner_grande(rom, cod[ch], AGUDO + sin(g(base)[:10], 1, 5) + [VACIO, VACIO])
    poner_grande(rom, cod["Ñ"], TILDE + sin(g("N")[:10], 1, 5) + [VACIO, VACIO])

    # --- fuente pequeña (7 filas): minúsculas con el cuerpo en filas 2-6
    p = lambda ch: glifo_pequeno(rom, ch)
    agudo_p = ["...#....", "..#....."]
    for ch, base in (("á", "a"), ("é", "e"), ("ó", "o"), ("ú", "u")):
        poner_pequeno(rom, INDICE_PEQUENA[cod[ch]], agudo_p + p(base)[2:])
    poner_pequeno(rom, INDICE_PEQUENA[cod["í"]], ["....#...", "...#....", VACIO] + p("i")[3:])
    poner_pequeno(rom, INDICE_PEQUENA[cod["ñ"]], [".##.#...", "#..#...."] + p("n")[2:])
    # mayúsculas: 7 filas comprimidas a 5
    for ch, base, quitar in (("Á", "A", (2, 5)), ("É", "E", (2, 5)), ("Í", "I", (2, 5)),
                             ("Ó", "O", (2, 5)), ("Ú", "U", (2, 5))):
        poner_pequeno(rom, INDICE_PEQUENA[cod[ch]], agudo_p + sin(p(base), *quitar))
    # La fuente pequeña reconoce ahora 0x827A-0x827E y 0x829B-0x82A0.
    assert rom[CMP_MAYUSCULAS:CMP_MAYUSCULAS + 2] == b"\x19\x28"
    assert rom[CMP_MINUSCULAS:CMP_MINUSCULAS + 2] == b"\x19\x28"
    rom[CMP_MAYUSCULAS] = 0x1E
    rom[CMP_MINUSCULAS] = 0x1F


def ampliar_tablas(rom, libre):
    """Copia las tablas proporcionales a espacio libre y les añade los caracteres nuevos."""
    for origen, literal, columna in ((PROP_GRANDE, LIT_PROP_GRANDE, 2), (PROP_PEQUENA, LIT_PROP_PEQUENA, 3)):
        assert struct.unpack_from("<I", rom, literal)[0] == origen + gba.GBA
        tabla = bytearray(rom[origen:origen + N_PROP * 4])
        for entrada in NUEVOS:
            despl, ancho = entrada[columna]
            tabla += struct.pack("<HBB", entrada[1], despl, ancho)
        pos = libre.reservar(len(tabla))
        rom[pos:pos + len(tabla)] = tabla
        struct.pack_into("<I", rom, literal, pos + gba.GBA)


def anchos(rom, origen, columna):
    """{carácter: avance en píxeles} para una de las dos fuentes."""
    a = {}
    for i, ch in enumerate(PROP_ORIGINAL):
        a[ch] = rom[origen + i * 4 + 3]
    for entrada in NUEVOS:
        a[entrada[0]] = entrada[columna][1]
    return a


# ----------------------------------------------------------- construcción ---

PAGINA = re.compile(r"\{05\}")


def construir(rom_original):
    gba.elegir_version(rom_original, VERSIONES)
    rom = bytearray(rom_original)
    libre = gba.EspacioLibre(*LIBRE)
    ampliar_fuentes(rom)
    ampliar_tablas(rom, libre)
    a_grande = anchos(rom_original, PROP_GRANDE, 2)
    a_pequena = anchos(rom_original, PROP_PEQUENA, 3)
    medidor = gba.Medidor(lambda c: a_grande.get(c, 6), ancho_cmd=0)
    medidor_nombres = gba.Medidor(lambda c: a_pequena.get(c, 6), ancho_cmd=0)

    glosario = gba.leer_glosario(os.path.join(AQUI, "nombres.txt"))
    entradas = {}
    for archivo in ("textos.txt", "dialogos.txt"):
        for k, v in gba.leer_entradas(os.path.join(AQUI, archivo)).items():
            if k in entradas:
                raise ValueError("entrada repetida entre archivos: %03X" % k)
            entradas[k] = v

    avisos, nuevas = [], {}
    for ini, fin, modo, ancho, max_lineas in REGIONES:
        for tid in range(ini, fin + 1):
            original = leer_cadena(rom_original, tid)
            cola = "\n" if original.rstrip(" ").endswith("\n") else ""
            literal = False
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
                if original.strip() not in ("NULL", "O") and re.search(r"[A-Za-z]{3}", gba.CMD.sub("", original)):
                    avisos.append("%03X sin traducir: %r" % (tid, original[:40]))
                continue
            if modo == "nombre":
                if medidor_nombres.px(final.strip()) > ancho:
                    avisos.append("%03X nombre ancho (%d px > %d): %s"
                                  % (tid, medidor_nombres.px(final.strip()), ancho, final.strip()))
                if re.search(r"[.,;üÑ¿¡]", final):
                    avisos.append("%03X usa un carácter que la fuente pequeña no tiene: %s" % (tid, final.strip()))
            elif literal:
                for linea in final.split("\n"):
                    if tid >= 0x28C and medidor.px(linea) > ancho:
                        avisos.append("%03X línea ancha (%d px): %s" % (tid, medidor.px(linea), linea))
            else:
                for pagina in PAGINA.split(final):
                    lineas = [l for l in gba.CMD.sub("", pagina).split("\n") if l.strip()]
                    if modo == "dialogo" and len(lineas) > max_lineas:
                        avisos.append("%03X cuadro con %d líneas: %s" % (tid, len(lineas), " / ".join(lineas)))
                    for linea in lineas:
                        if medidor.px(linea) > ancho:
                            avisos.append("%03X línea ancha (%d px): %s" % (tid, medidor.px(linea), linea))
            if final != original:
                nuevas[tid] = codificar(final)

    inicio = libre.pos
    gba.reapuntar(rom, TABLA_TEXTOS, nuevas, libre, b"\x00\x00", b"\x0A\xF0")
    return bytes(rom), avisos, len(nuevas), libre.pos - inicio


def estadisticas(rom):
    """Muestra el ancho máximo de línea del texto original por región (para calibrar)."""
    a_grande = anchos(rom, PROP_GRANDE, 2)
    a_pequena = anchos(rom, PROP_PEQUENA, 3)
    for ini, fin, modo, ancho, max_lineas in REGIONES:
        med = gba.Medidor((lambda c: a_pequena.get(c, 6)) if modo == "nombre" else (lambda c: a_grande.get(c, 6)), 0)
        peor, n = (0, ""), 0
        for tid in range(ini, fin + 1):
            for pagina in PAGINA.split(leer_cadena(rom, tid)):
                lineas = [l.rstrip() for l in re.sub(r"\{01 [0-9A-F]+\}", "Dracula", pagina).split("\n")]
                lineas = [gba.CMD.sub("", l) for l in lineas if gba.CMD.sub("", l).strip()]
                n = max(n, len(lineas))
                for l in lineas:
                    peor = max(peor, (med.px(l), "%03X %s" % (tid, l)))
        print("%03X-%03X %-8s max %3d px, %d líneas  %s" % (ini, fin, modo, peor[0], n, peor[1]))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    original = open(argv[0], "rb").read()
    gba.avisar_sha1(original, gba.elegir_version(original, VERSIONES))
    if len(argv) > 1 and argv[1] == "--estadisticas":
        estadisticas(original)
        return 0
    rom, avisos, n, usado = construir(original)
    for a in avisos:
        print("  !", a)
    salida = argv[1] if len(argv) > 1 else os.path.join(AQUI, "hod-es.ips")
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
