#!/usr/bin/env python3
"""Construye la traducción al español de Castlevania: Circle of the Moon (ROMs US y EU de la colección).

Uso: python construir.py ROM_ORIGINAL.bin [salida.ips] [rom_traducido.gba]

El ROM original es el que trae Castlevania Advance Collection
(system/roms/01_Circle_US.patch_210614m.bin o 01_Circle_EU...). Las dos versiones
traen los mismos textos; en la europea las tablas están 76 bytes antes.

Cómo guarda el texto este juego:
  - Una tabla de punteros a cadenas; cada carácter es un byte y 0x00 termina.
  - El código del carácter menos 0x26 es el número de glifo; 0 y 1 son espacios
    (0x26 espacio normal, 0x27 espacio "duro" para rellenar). Los glifos son
    mosaicos de 8x8 a 1 bit y se buscan en otra tabla de punteros.
  - Los bytes 0x0D y 0x0E son prefijos: junto al byte siguiente dan glifos 256+ y 512+.
  - Los nombres de objetos del menú no son texto: son 10 mosaicos por nombre
    con las letras ya dibujadas en una fuente estrecha.
Para el español se copia la tabla de glifos a una zona vacía, se le añaden
á é í ó ú ñ ü ¿ ¡ (y mayúsculas, cifras y signos que faltaban) y se vuelven a
dibujar los nombres de objetos con una fuente estrecha propia.
"""
import math
import os
import re
import struct
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
import gba  # noqa: E402

# Direcciones por versión (código del cartucho):
#   tabla   punteros a cadenas (índice * 4)      glifos   punteros a glifos (glifo 2 en adelante)
VERSIONES = {
    b"AAME": {"nombre": "americana", "tabla": 0x6707D8, "glifos": 0x6711E8,
              "sha1": "9483aa48b384ff3142c47fe81c13ca874a608eb0"},
    b"AAMP": {"nombre": "europea", "tabla": 0x67078C, "glifos": 0x67119C,
              "sha1": "30a2fd3fe95a8a84b02da7ddbc8b2a90e0553d9b"},
}
TABLA_TEXTOS = TABLA_GLIFOS = None    # se fijan en configurar()
LIT_GLIFOS = 0x60AC4           # literal con la dirección de la tabla de glifos (glifo 2)
N_GLIFOS = 626                 # glifos 2..627 en la tabla original
LIBRE = (0x690000, 0x7F0000)

CON_DATO = {0x01, 0x0D, 0x0E, 0x1D, 0x1E, 0x1F, 0x20}   # comandos con un byte de dato
SALTO_PAGINA = "{02}\n{01 0A}"

# Caracteres de la fuente original, en orden desde el código 0x28.
ORIGINALES = "eatorinslhdcu.mwpgfybkAvHSMICDRT?W!P,BEG+'NY()Fx-[]→←↑↓LUqj20zKO%51J3XVZ/48&"
# Caracteres nuevos (glifos 628 en adelante -> prefijo 0x0E, byte 0x9A...).
NUEVOS = "áéíóúñü¿¡ÁÉÍÓÚÑ679:\"Q"


def tabla_de_codigos():
    cod = {" ": bytes([0x26]), "·": bytes([0x27])}
    for i, ch in enumerate(ORIGINALES):
        cod[ch] = bytes([0x28 + i])
    for i, ch in enumerate(NUEVOS):
        n = N_GLIFOS + 2 + i + 0x26          # código de 16 bits
        cod[ch] = bytes([0x0C + (n >> 8), n & 0xFF])
    return cod


def configurar(rom):
    global TABLA_TEXTOS, TABLA_GLIFOS
    v = gba.elegir_version(rom, VERSIONES)
    TABLA_TEXTOS, TABLA_GLIFOS = v["tabla"], v["glifos"]
    return v


CODIGOS = tabla_de_codigos()
DESCODIGOS = {v[0]: k for k, v in CODIGOS.items() if len(v) == 1}


# ----------------------------------------------------------------- texto ---

def puntero(rom, idx):
    return struct.unpack_from("<I", rom, TABLA_TEXTOS + 4 * idx)[0] - gba.GBA


def leer_bytes(rom, idx):
    p, out = puntero(rom, idx), bytearray()
    while rom[p]:
        out.append(rom[p])
        if rom[p] in CON_DATO:
            out.append(rom[p + 1])
            p += 1
        p += 1
    return bytes(out)


def decodificar(b):
    out, k = [], 0
    while k < len(b):
        x = b[k]
        if x == 9:
            out.append("\n")
        elif x in CON_DATO:
            out.append("{%02X %02X}" % (x, b[k + 1]))
            k += 1
        elif x < 0x26:
            out.append("{%02X}" % x)
        else:
            out.append(DESCODIGOS.get(x, "{%02X}" % x))
        k += 1
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
            out.append(9)
            i += 1
        else:
            if ch not in CODIGOS:
                raise ValueError("carácter sin glifo en CotM: %r" % ch)
            out += CODIGOS[ch]
            i += 1
    return bytes(out)


def visible(s):
    """Texto sin comandos (cada carácter ocupa un mosaico)."""
    return gba.CMD.sub("", s)


# --------------------------------------------------------------- glifos ---

def a_bytes(filas):
    """8 filas de '#'/'.' -> 8 bytes en el formato del juego (pares de bits intercambiados)."""
    out = bytearray()
    for fila in filas:
        b = sum(0x80 >> x for x in range(8) if fila[x] == "#")
        out.append(((b & 0xAA) >> 1) | ((b & 0x55) << 1))
    return bytes(out)


def de_bytes(datos):
    filas = []
    for b in datos:
        b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1)
        filas.append("".join("#" if b & (0x80 >> x) else "." for x in range(8)))
    return filas


def glifo(rom, ch):
    n = CODIGOS[ch][0] - 0x26
    p = struct.unpack_from("<I", rom, TABLA_GLIFOS + 4 * (n - 2))[0] - gba.GBA
    return de_bytes(rom[p:p + 8])


V = "........"
AGUDO = ["....#...", "...#...."]


def girar(filas):
    return [f[6::-1] + "." for f in reversed(filas)]


def glifos_nuevos(rom):
    """Dibujos de los caracteres de NUEVOS, compuestos a partir de la fuente del juego."""
    g = lambda ch: glifo(rom, ch)

    def minuscula(base, quitar, marca):
        cuerpo = g(base)[2:]                      # 6 filas (2-7)
        del cuerpo[quitar]                        # se comprime a 5 para dejar sitio al acento
        return marca + [V] + cuerpo

    def mayuscula(base, marca):
        return [marca] + g(base)[1:]

    d = {}
    d["á"] = minuscula("a", 3, AGUDO)
    d["é"] = minuscula("e", 4, AGUDO)
    d["í"] = AGUDO + [V] + g("i")[3:]
    d["ó"] = minuscula("o", 2, AGUDO)
    d["ú"] = minuscula("u", 1, AGUDO)
    d["ñ"] = minuscula("n", 3, ["..##.#..", ".#..#..."])
    d["ü"] = minuscula("u", 1, [V, ".#...#.."])
    d["¿"] = [V] + girar(g("?")[1:])
    d["¡"] = [V] + g("!")[:0:-1]
    for ch, base in (("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U")):
        d[ch] = mayuscula(base, "....#...")
    d["Ñ"] = mayuscula("N", "..##.#..")
    d["6"] = [V, "..###...", ".#......", ".####...", ".#...#..", ".#...#..", ".#...#..", "..###..."]
    d["7"] = [V, ".#####..", ".....#..", "....#...", "...#....", "...#....", "...#....", "...#...."]
    d["9"] = [V, "..###...", ".#...#..", ".#...#..", "..####..", ".....#..", ".....#..", "..###..."]
    d[":"] = [V, V, V, "...#....", V, V, "...#....", V]
    d['"'] = [V, "..#.#...", "..#.#...", V, V, V, V, V]
    d["Q"] = [V, "..###...", ".#...#..", ".#...#..", ".#...#..", ".#.#.#..", ".#..#...", "..##.#.."]
    return d


def ampliar_fuente(rom, libre):
    """Copia la tabla de glifos a espacio libre y le añade los caracteres nuevos."""
    origen = struct.unpack_from("<I", rom, LIT_GLIFOS)[0] - gba.GBA
    assert origen == TABLA_GLIFOS
    tabla = bytearray(rom[origen:origen + 4 * N_GLIFOS])
    nuevos = glifos_nuevos(rom)
    for ch in NUEVOS:
        datos = a_bytes(nuevos[ch])
        p = libre.reservar(8)
        rom[p:p + 8] = datos
        tabla += struct.pack("<I", p + gba.GBA)
    p = libre.reservar(len(tabla))
    rom[p:p + len(tabla)] = tabla
    struct.pack_into("<I", rom, LIT_GLIFOS, p + gba.GBA)


# ------------------------------------------------- fuente estrecha (nombres) ---

def leer_fuente_estrecha():
    """Fuente de 6 filas y ancho variable definida en fuente_estrecha.txt."""
    fuente, actual = {}, None
    with open(os.path.join(AQUI, "fuente_estrecha.txt"), encoding="utf-8") as f:
        for linea in f:
            linea = linea.rstrip("\n")
            if linea.startswith("= "):
                actual = linea[2:]
                fuente[actual] = []
            elif re.fullmatch(r"[#.]+", linea):
                fuente[actual].append(linea)      # fila de píxeles
            # cualquier otra línea es comentario o separación
    for ch, filas in fuente.items():
        if len(filas) != 8 or len(set(map(len, filas))) != 1:
            raise ValueError("glifo estrecho mal definido: %r" % ch)
    return fuente


def dibujar_estrecho(texto, fuente, espacio=3):
    """Devuelve las 8 filas (cadenas de '#'/'.') del texto dibujado con la fuente estrecha."""
    filas = [""] * 8
    for i, ch in enumerate(texto):
        if ch == " ":
            trozo = ["." * espacio] * 8
        else:
            if ch not in fuente:
                raise ValueError("la fuente estrecha no tiene %r (en %r)" % (ch, texto))
            trozo = fuente[ch]
            if i + 1 < len(texto) and texto[i + 1] != " ":
                trozo = [f + "." for f in trozo]
        filas = [a + b for a, b in zip(filas, trozo)]
    return filas


def poner_mosaicos(rom, idx, texto, fuente, avisos):
    """Redibuja los 10 mosaicos de la cadena `idx` con `texto`."""
    filas = dibujar_estrecho(texto, fuente)
    ancho = len(filas[0])
    if ancho > 80:
        avisos.append("%d nombre dibujado demasiado ancho (%d px): %s" % (idx, ancho, texto))
        filas = [f[:80] for f in filas]
    filas = [f.ljust(80, ".") for f in filas]
    b = leer_bytes(rom, idx)
    numeros, k = [], 0
    while k < len(b):
        if b[k] in (0x0D, 0x0E):
            numeros.append(((b[k] - 0x0C) << 8) + b[k + 1] - 0x26)
            k += 2
        else:
            numeros.append(b[k] - 0x26)
            k += 1
    assert len(numeros) == 10, hex(idx)
    for t, n in enumerate(numeros):
        p = struct.unpack_from("<I", rom, TABLA_GLIFOS + 4 * (n - 2))[0] - gba.GBA
        rom[p:p + 8] = a_bytes([f[t * 8:t * 8 + 8] for f in filas])


# ------------------------------------------------------------ composición ---

def componer(texto, ancho, lineas, salto_pagina=SALTO_PAGINA):
    """Ajusta texto con comandos a `ancho` caracteres y `lineas` líneas por cuadro.

    {P} fuerza un cuadro nuevo y {N} un salto de línea; el resto de comandos no ocupa sitio.
    """
    out, col, lin, espacio = [], 0, 0, False
    centrado = None
    for trozo in gba.CMD.split(texto):
        if trozo == "{C}":                        # línea centrada a mano, como en el original
            centrado = []
            continue
        if trozo == "{/C}":
            linea = centrar("".join(centrado))
            out.append(linea.replace(" ", "\x01"))   # \x01: espacio de una línea centrada
            col, espacio, centrado = len(visible(linea)), False, None
            continue
        if centrado is not None:
            centrado.append(trozo)
            continue
        if trozo.startswith("{"):
            if trozo == "{P}":
                out.append(salto_pagina)
                col, lin, espacio = 0, 0, False
            elif trozo == "{N}":
                if lin + 1 >= lineas:             # no cabe otra línea: cuadro nuevo
                    out.append(salto_pagina)
                    col, lin, espacio = 0, 0, False
                else:
                    out.append("\n")
                    col, lin, espacio = 0, lin + 1, False
            else:
                out.append(trozo)
                if trozo.upper() == "{01 0A}":    # el juego limpia el cuadro
                    col, lin, espacio = 0, 0, False
            continue
        for parte in re.findall(r"\S+|\s+", trozo):
            if parte.isspace():
                espacio = True
                continue
            hueco = 1 if (col > 0 and espacio) else 0
            if col > 0 and col + hueco + len(parte) > ancho:
                if lin + 1 >= lineas:
                    out.append(salto_pagina)
                    lin = 0
                else:
                    out.append("\n")
                    lin += 1
                col, hueco = 0, 0
            out.append(" " * hueco + parte)
            col += hueco + len(parte)
            espacio = False
    return "".join(out)


def ajustar(texto, ancho):
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = palabra if not actual else actual + " " + palabra
        if actual and len(visible(prueba)) > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = prueba
    if actual:
        lineas.append(actual)
    return lineas


# Regiones de la tabla: (primer índice, último, modo, parámetros)
REGIONES = [
    (29, 35, "fijo", 14),            # nombres de quien habla
    (36, 179, "nombre", 18),         # enemigos
    (180, 180, "nombre", 10),        # "Quitar"
    (183, 236, "nombre", 17),        # objetos (texto)
    (291, 315, "zona", 24),          # zonas
    (317, 325, "fijo", 10),          # objetos mágicos
    (327, 332, "linea", 28),         # introducción (una línea por cadena)
    (333, 367, "dialogo", 21, 3),    # escenas
    (368, 368, "dialogo", 23, 4),    # aviso de la arena
    (369, 379, "dialogo", 21, 3),    # mensajes al recoger objetos
    (381, 388, "dialogo", 21, 3),    # objetos mágicos (menú)
    (390, 490, "lineas", 21, 3),     # combinaciones DSS
    (491, 505, "fijo", 24),          # selección de partida
    (506, 507, "fijo", 12),
    (508, 514, "lineas", 21, 2),     # ayuda del menú
    (515, 568, "objeto", 27, 2),     # descripciones de objetos
    (569, 569, "dialogo", 21, 3),    # tutorial DSS
    (570, 589, "dialogo", 27, 1),    # cartas recibidas
    (591, 610, "dialogo", 21, 3),    # descripciones de cartas
]
MOSAICOS = [(181, 180)] + [(237 + k, 183 + k) for k in range(54)]   # (cadena de mosaicos, nombre)


def centrar(texto, ancho=27):
    """Antepone los espacios necesarios para centrar una línea (como hace el original)."""
    return " " * max(0, math.ceil((ancho - len(visible(texto))) / 2)) + texto


def construir(rom_original):
    configurar(rom_original)
    rom = bytearray(rom_original)
    libre = gba.EspacioLibre(*LIBRE)
    ampliar_fuente(rom, libre)
    estrecha = leer_fuente_estrecha()

    glosario = gba.leer_glosario(os.path.join(AQUI, "nombres.txt"))
    entradas = {}
    for archivo in ("textos.txt", "dialogos.txt"):
        for k, v in gba.leer_entradas(os.path.join(AQUI, archivo), base=10).items():
            if k in entradas:
                raise ValueError("entrada repetida entre archivos: %03X" % k)
            entradas[k] = v

    avisos, nuevas, nombres = [], {}, {}
    for reg in REGIONES:
        ini, fin, modo = reg[0], reg[1], reg[2]
        for idx in range(ini, fin + 1):
            original = decodificar(leer_bytes(rom_original, idx))
            limpio = original.replace("·", " ").strip()
            texto = None
            if idx in entradas:
                literal, texto = entradas[idx]
                if literal:
                    nuevas[idx] = codificar(texto)
                    continue
            elif modo in ("nombre", "fijo") and limpio in glosario:
                texto = glosario[limpio]
            elif modo == "zona":
                clave = re.sub(r" {2,}", " ", limpio)
                if clave in glosario:
                    texto = glosario[clave]       # "mitad|mitad" marca dónde se parte el nombre
            if texto is None:
                if re.search(r"[A-Za-z]{3}", visible(original)):
                    avisos.append("%d sin traducir: %r" % (idx, original[:40]))
                continue

            if modo == "fijo":
                n = reg[3]
                if len(texto) > n:
                    avisos.append("%d no cabe en %d: %s" % (idx, n, texto))
                final = texto[:n].ljust(n).replace(" ", "·")
            elif modo == "nombre":
                if len(texto) > reg[3]:
                    avisos.append("%d nombre largo (%d > %d): %s" % (idx, len(texto), reg[3], texto))
                final = texto.replace(" ", "·")
                nombres[idx] = texto
            elif modo == "zona":
                if "|" in texto and re.search(r" {2,}", original):
                    a, b = texto.split("|")
                    hueco = max(1, min(10, reg[3] - len(a) - len(b)))
                    final = a + " " * hueco + b
                else:
                    final = texto.replace("|", " ")
                if len(final) > reg[3]:
                    avisos.append("%d zona larga (%d): %s" % (idx, len(final), final))
            elif modo == "linea":
                final = texto
                if len(visible(final)) > reg[3]:
                    avisos.append("%d línea larga (%d): %s" % (idx, len(visible(final)), final))
            elif modo == "lineas":
                lineas = ajustar(texto, reg[3])
                if len(lineas) > reg[4]:
                    avisos.append("%d ocupa %d líneas: %s" % (idx, len(lineas), texto))
                final = "\n".join(lineas)
            elif modo == "objeto":
                lineas = ajustar(texto, reg[3])
                if len(lineas) > 1:               # la segunda línea va sangrada 6 espacios
                    lineas = lineas[:1] + ajustar(" ".join(lineas[1:]), reg[3] - 3)
                if len(lineas) > reg[4]:
                    avisos.append("%d ocupa %d líneas: %s" % (idx, len(lineas), texto))
                final = "\n      ".join(lineas)
            else:  # dialogo
                final = componer(texto, reg[3], reg[4])
                for pagina in re.split(r"\{01 0A\}", final):
                    ls = visible(pagina).rstrip("\n").split("\n")
                    if len(ls) > reg[4]:
                        avisos.append("%d cuadro con %d líneas" % (idx, len(ls)))
                    for l in ls:
                        if len(l) > (27 if "\x01" in l else reg[3]):
                            avisos.append("%d línea larga (%d): %s" % (idx, len(l), l.replace("\x01", " ")))
                final = final.replace("\x01", " ")
            if final != original:
                nuevas[idx] = codificar(final)

    # Nombres de objetos dibujados en mosaicos.
    for idx_mosaico, idx_nombre in MOSAICOS:
        original = decodificar(leer_bytes(rom_original, idx_nombre)).replace("·", " ").strip()
        texto = nombres.get(idx_nombre) or glosario.get(original)
        if texto:
            poner_mosaicos(rom, idx_mosaico, texto, estrecha, avisos)
        else:
            avisos.append("%d mosaico sin nombre traducido: %s" % (idx_mosaico, original))

    inicio = libre.pos
    gba.reapuntar(rom, TABLA_TEXTOS, nuevas, libre, b"", b"\x00")
    return bytes(rom), avisos, len(nuevas), libre.pos - inicio


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    original = open(argv[0], "rb").read()
    gba.avisar_sha1(original, gba.elegir_version(original, VERSIONES))
    rom, avisos, n, usado = construir(original)
    for a in avisos:
        print("  !", a)
    salida = argv[1] if len(argv) > 1 else os.path.join(AQUI, "cotm-es.ips")
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
