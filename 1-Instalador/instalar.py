#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Castlevania Advance Collection (Steam) - instalador de traducciones al español.

Aplica parches de traducción (.ips) a los ROMs que trae TU copia del juego y
los vuelve a empaquetar. No contiene ni descarga ROMs ni nada de internet:
trabaja siempre sobre los archivos que ya tienes instalados.

Uso:
    python instalar.py                  detecta el juego, pregunta la versión e instala
    python instalar.py --us | --eu | --ambas   instala sin preguntar en la versión
                                        americana, la europea o las dos
    python instalar.py "<carpeta>"      indica la carpeta del juego (o windata)
    python instalar.py --desinstalar    deja el juego como estaba
    python instalar.py --estado         muestra que hay instalado
    python instalar.py --extraer        saca los ROMs originales a roms/ (para
                                        reconstruir los parches desde fuente/)

Solo necesita Python 3.8 o superior (sin dependencias).
"""
import hashlib
import json
import os
import re
import shutil
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import marchive  # noqa: E402

SEMILLA = "25G/xpvTbsb+6"   # clave del archivo MArchive de esta coleccion
LARGO_CLAVE = 64
ALINEACION = 0x800           # el motor de M2 exige entradas alineadas a 2048 bytes
DATOS = "alldata.bin"
INDICE = "alldata.psb.m"
RESPALDO = "alldata.psb.m.original"
ESTADO = "mod_es.json"
CARPETA_PARCHES = os.path.join(AQUI, "parches")
SUBRUTA_JUEGO = os.path.join("steamapps", "common", "Castlevania Advance Collection")
BLOQUE = 1 << 22


for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def log(msg=""):
    print(msg, flush=True)


class Fallo(Exception):
    pass


# ------------------------------------------------------------ utilidades ---

def sha1(datos):
    return hashlib.sha1(datos).hexdigest()


def alinear(n):
    return (n + ALINEACION - 1) // ALINEACION * ALINEACION


def leer(ruta):
    with open(ruta, "rb") as f:
        return f.read()


def escribir(ruta, datos):
    with open(ruta, "wb") as f:
        f.write(datos)


def borrar(ruta):
    try:
        os.remove(ruta)
    except OSError:
        pass


# ------------------------------------------------------- parches (.ips) ---

def aplicar_ips(rom, parche, nombre="parche"):
    """Aplica un parche IPS (con registros RLE y la extension de truncado)."""
    if parche[:5] != b"PATCH":
        raise Fallo("%s no es un parche IPS válido." % nombre)
    rom = bytearray(rom)
    i = 5
    registros = 0
    while True:
        if i + 3 > len(parche):
            raise Fallo("%s está incompleto o dañado." % nombre)
        if parche[i:i + 3] == b"EOF":
            i += 3
            break
        pos = int.from_bytes(parche[i:i + 3], "big")
        tam = int.from_bytes(parche[i + 3:i + 5], "big")
        i += 5
        if tam:
            trozo = parche[i:i + tam]
            i += tam
        else:
            veces = int.from_bytes(parche[i:i + 2], "big")
            trozo = parche[i + 2:i + 3] * veces
            i += 3
        if pos + len(trozo) > len(rom):
            rom.extend(b"\xff" * (pos + len(trozo) - len(rom)))
        rom[pos:pos + len(trozo)] = trozo
        registros += 1
    if len(parche) - i == 3:
        del rom[int.from_bytes(parche[i:i + 3], "big"):]
    if not registros:
        raise Fallo("%s no contiene cambios." % nombre)
    return bytes(rom)


# -------------------------------------------------- localizar el juego ---

def bibliotecas_steam():
    raices = []
    if os.name == "nt":
        try:
            import winreg
            for raiz, clave in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
                for valor in ("SteamPath", "InstallPath"):
                    try:
                        with winreg.OpenKey(raiz, clave) as k:
                            raices.append(os.path.normpath(winreg.QueryValueEx(k, valor)[0]))
                    except OSError:
                        pass
        except ImportError:
            pass
    casa = os.path.expanduser("~")
    raices += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam",
               os.path.join(casa, ".local", "share", "Steam"),
               os.path.join(casa, ".steam", "steam"),
               os.path.join(casa, ".var", "app", "com.valvesoftware.Steam", "data", "Steam")]
    todas = []
    for r in raices:
        if not os.path.isdir(r):
            continue
        todas.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="ignore") as f:
                for m in re.finditer(r'"path"\s*"([^"]+)"', f.read()):
                    todas.append(m.group(1).replace("\\\\", "\\"))
        except OSError:
            pass
    vistas, unicas = set(), []
    for r in todas:
        clave = os.path.normcase(os.path.normpath(r))
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(r)
    return unicas


def buscar_windata(indicada=None):
    def probar(carpeta):
        for c in (carpeta, os.path.join(carpeta, "windata")):
            if os.path.isfile(os.path.join(c, DATOS)) and os.path.isfile(os.path.join(c, INDICE)):
                return c
        return None

    if indicada:
        w = probar(os.path.abspath(indicada.strip().strip('"')))
        if not w:
            raise Fallo("No encuentro %s dentro de: %s" % (DATOS, indicada))
        return w
    # 1) Si esta carpeta se copio dentro de la del juego, se usa esa.
    carpeta = AQUI
    for _ in range(4):
        w = probar(carpeta)
        if w:
            return w
        carpeta = os.path.dirname(carpeta)
    # 2) Bibliotecas de Steam.
    for raiz in bibliotecas_steam():
        w = probar(os.path.join(raiz, SUBRUTA_JUEGO))
        if w:
            return w
    return None


# ---------------------------------------------------------- los parches ---

def cargar_catalogo():
    ruta = os.path.join(CARPETA_PARCHES, "parches.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)["juegos"]
    except (OSError, ValueError, KeyError) as e:
        raise Fallo("No puedo leer %s (%s)." % (ruta, e))


def parches_de(juego):
    """Devuelve [(nombre, bytes)] con los parches del juego, en orden de aplicación."""
    carpeta = os.path.join(CARPETA_PARCHES, juego["carpeta"])
    if not os.path.isdir(carpeta):
        return []
    nombres = sorted(n for n in os.listdir(carpeta) if n.lower().endswith(".ips"))
    return [(n, leer(os.path.join(carpeta, n))) for n in nombres]


# --------------------------------------------------------- el archivo ---

class Archivo:
    """Par alldata.psb.m + alldata.bin de una instalacion del juego."""

    def __init__(self, windata):
        self.windata = windata
        self.r_datos = os.path.join(windata, DATOS)
        self.r_indice = os.path.join(windata, INDICE)
        self.r_respaldo = os.path.join(windata, RESPALDO)
        self.r_estado = os.path.join(windata, ESTADO)

    def abrir_indice(self, blob):
        return marchive.PSB(marchive.mdf_unpack(blob, SEMILLA, INDICE, LARGO_CLAVE))

    def cerrar_indice(self, psb):
        return marchive.mdf_pack(psb.serialize(), SEMILLA, INDICE, LARGO_CLAVE)

    def estado(self):
        try:
            with open(self.r_estado, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def original(self):
        """Devuelve (blob del indice original, instalado?) y deja el respaldo listo."""
        actual = leer(self.r_indice)
        est = self.estado()
        if os.path.isfile(self.r_respaldo):
            resp = leer(self.r_respaldo)
            if est and est.get("indice_mod_sha1") == sha1(actual):
                return resp, True               # el mod esta instalado
            if sha1(resp) == sha1(actual):
                return resp, False              # juego original, respaldo vigente
            log("Los archivos del juego cambiaron (actualización o verificación de Steam);")
            log("se toman los actuales como originales.")
        escribir(self.r_respaldo, actual)
        borrar(self.r_estado)
        return actual, False

    @staticmethod
    def tam_original(info):
        return alinear(max(pos + tam for pos, tam in info.values()))

    def extraer(self, f, info, entrada):
        pos, tam = info[entrada]
        f.seek(pos)
        return marchive.mdf_unpack(f.read(tam), SEMILLA, os.path.basename(entrada), LARGO_CLAVE)


OPCIONES = {"1": ["us"], "2": ["eu"], "3": ["us", "eu"]}


def elegir_regiones(opciones, windata):
    """Devuelve las versiones del juego ('us', 'eu') donde poner el español."""
    if "--ambas" in opciones or ("--us" in opciones and "--eu" in opciones):
        return ["us", "eu"]
    if "--us" in opciones:
        return ["us"]
    if "--eu" in opciones:
        return ["eu"]
    previas = (Archivo(windata).estado() or {}).get("regiones")
    defecto = next((k for k, v in OPCIONES.items() if v == previas), "3")
    if "--sin-pausa" in opciones or not sys.stdin or not sys.stdin.isatty():
        return OPCIONES[defecto]
    log("¿En qué versión de los juegos quieres el español?")
    log("  1) Americana (US)")
    log("  2) Europea (EU)")
    log("  3) Americana y europea")
    while True:
        r = input("Escribe 1, 2 o 3 y pulsa ENTER [%s]: " % defecto).strip() or defecto
        if r in OPCIONES:
            log()
            return OPCIONES[r]


def instalar(windata, regiones):
    arch = Archivo(windata)
    catalogo = [j for j in cargar_catalogo() if j.get("region", "us") in regiones]

    # Se reunen los parches antes de tocar nada.
    plan = []
    for juego in catalogo:
        log("- %s, versión %s" % (juego["nombre"], juego["version"]))
        parches = parches_de(juego)
        if parches:
            log("   Parches: %s" % ", ".join(n for n, _ in parches))
            plan.append((juego, parches))
        else:
            log("   Sin parche en parches/%s/ -> se deja como está." % juego["carpeta"])
            if juego.get("ayuda"):
                log("   (%s)" % juego["ayuda"])
    if not plan:
        raise Fallo("No hay ningún parche que aplicar.")

    blob_original, _ = arch.original()
    psb = arch.abrir_indice(blob_original)
    info = psb.root["file_info"]
    tam_orig = arch.tam_original(info)
    if os.path.getsize(arch.r_datos) < tam_orig:
        raise Fallo("%s está incompleto. Usa en Steam 'Verificar integridad de los archivos "
                    "del juego' y vuelve a intentarlo." % DATOS)

    log()
    log("Aplicando en: %s" % windata)
    hechos = []
    with open(arch.r_datos, "r+b") as f:
        nuevos = []
        for juego, parches in plan:
            entrada = juego["entrada"]
            if entrada not in info:
                log("   Aviso: esta versión del juego no tiene %s; se omite." % entrada)
                continue
            rom = arch.extraer(f, info, entrada)
            if juego.get("sha1_rom") and sha1(rom) != juego["sha1_rom"]:
                log("   Aviso: el ROM de %s difiere del probado; se intenta igualmente." % juego["nombre"])
            for nombre, datos in parches:
                rom = aplicar_ips(rom, datos, nombre)
            nuevos.append((juego, parches, rom,
                           marchive.mdf_pack(rom, SEMILLA, os.path.basename(entrada), LARGO_CLAVE)))
        if not nuevos:
            raise Fallo("No se pudo aplicar ningún parche.")
        # Los ROMs nuevos se anaden al final; los datos originales no se tocan.
        f.truncate(tam_orig)
        pos = tam_orig
        for juego, parches, rom, blob in nuevos:
            f.seek(pos)
            f.write(blob)
            info[juego["entrada"]] = [pos, len(blob)]
            hechos.append({"id": juego["id"], "nombre": juego["nombre"], "entrada": juego["entrada"],
                           "region": juego.get("region", "us"),
                           "version": juego["version"], "parches": [n for n, _ in parches],
                           "sha1_rom_es": sha1(rom)})
            pos = alinear(pos + len(blob))
            f.truncate(pos)
        f.flush()
        os.fsync(f.fileno())
    indice_nuevo = arch.cerrar_indice(psb)
    # Primero el estado y luego el índice: si algo se corta a medias, el respaldo
    # del índice original nunca se confunde con uno ya modificado.
    with open(arch.r_estado, "w", encoding="utf-8") as f:
        json.dump(estado_nuevo(indice_nuevo, tam_orig, hechos), f, ensure_ascii=False, indent=1)
    escribir(arch.r_indice, indice_nuevo)

    verificar(arch, blob_original, hechos)
    log()
    log("*** LISTO. Juegos en español: ***")
    for juego, _, _, _ in nuevos:
        log("  - %s, versión %s" % (juego["nombre"], juego["version"]))
        if juego.get("nota"):
            log("    %s" % juego["nota"])
    log()
    log("En el menú de la colección elige esa versión de cada juego;")
    log("las demás versiones siguen en su idioma original.")
    log()
    log("Para volver al original: Desinstalar.bat (o 'python instalar.py --desinstalar').")
    log("Si Steam actualiza o verifica el juego, vuelve a ejecutar el instalador.")


def estado_nuevo(indice_nuevo, tam_orig, hechos):
    """Contenido de mod_es.json: lo que hay instalado y con qué índice."""
    return {"indice_mod_sha1": sha1(indice_nuevo), "tam_original": tam_orig,
            "regiones": sorted({h["region"] for h in hechos}, reverse=True), "juegos": hechos}


def verificar(arch, blob_original, hechos):
    """Relee lo escrito y comprueba que el archivo quedo coherente."""
    antes = arch.abrir_indice(blob_original).root["file_info"]
    ahora = arch.abrir_indice(leer(arch.r_indice)).root["file_info"]
    cambiadas = {h["entrada"]: h for h in hechos}
    if set(antes) != set(ahora):
        raise Fallo("Verificación: la lista de archivos cambió.")
    tam = os.path.getsize(arch.r_datos)
    with open(arch.r_datos, "rb") as f:
        for entrada, (pos, largo) in ahora.items():
            if pos % ALINEACION or pos + largo > tam:
                raise Fallo("Verificación: %s quedó mal colocado." % entrada)
            if entrada in cambiadas:
                rom = arch.extraer(f, ahora, entrada)
                if sha1(rom) != cambiadas[entrada]["sha1_rom_es"]:
                    raise Fallo("Verificación: %s no se lee bien." % entrada)
            elif list(antes[entrada]) != [pos, largo]:
                raise Fallo("Verificación: %s cambió sin querer." % entrada)
    log("Verificación correcta (%d archivos, %d ROMs traducidos)." % (len(ahora), len(hechos)))


def desinstalar(windata):
    arch = Archivo(windata)
    if not os.path.isfile(arch.r_respaldo):
        log("No hay nada que desinstalar (no existe %s)." % RESPALDO)
        return
    actual, resp = leer(arch.r_indice), leer(arch.r_respaldo)
    est = arch.estado()
    if sha1(actual) != sha1(resp):
        if not est or est.get("indice_mod_sha1") != sha1(actual):
            raise Fallo("Los archivos del juego no son los que dejó este instalador. Usa en Steam "
                        "'Verificar integridad de los archivos del juego'.")
        tam_orig = arch.tam_original(arch.abrir_indice(resp).root["file_info"])
        with open(arch.r_datos, "r+b") as f:
            f.truncate(tam_orig)
        escribir(arch.r_indice, resp)
    borrar(arch.r_estado)
    borrar(arch.r_respaldo)
    log("*** Juego restaurado al ORIGINAL. ***")


def mostrar_estado(windata):
    arch = Archivo(windata)
    est = arch.estado()
    if est and os.path.isfile(arch.r_respaldo) and est.get("indice_mod_sha1") == sha1(leer(arch.r_indice)):
        log("Traducciones instaladas:")
        for j in est["juegos"]:
            log("  - %s, versión %s" % (j["nombre"], j["version"]))
    else:
        log("El juego está en su estado original (sin traducciones instaladas).")


def extraer_roms(windata):
    """Saca a roms/ los ROMs originales de los juegos del catálogo."""
    arch = Archivo(windata)
    est = arch.estado()
    instalado = bool(est and os.path.isfile(arch.r_respaldo)
                     and est.get("indice_mod_sha1") == sha1(leer(arch.r_indice)))
    info = arch.abrir_indice(leer(arch.r_respaldo if instalado else arch.r_indice)).root["file_info"]
    destino = os.path.join(AQUI, "roms")
    os.makedirs(destino, exist_ok=True)
    with open(arch.r_datos, "rb") as f:
        for juego in cargar_catalogo():
            rom = arch.extraer(f, info, juego["entrada"])
            ruta = os.path.join(destino, juego["id"] + ".gba")
            escribir(ruta, rom)
            aviso = "" if sha1(rom) == juego.get("sha1_rom") else "  (¡no es la versión esperada!)"
            log("  %s -> %s%s" % (juego["nombre"], ruta, aviso))
    log()
    log("Son tus ROMs: no los compartas ni los subas a ningún sitio.")


def main(argv):
    log("=" * 62)
    log(" Castlevania Advance Collection - traducciones al español")
    log("=" * 62)
    opciones = [a for a in argv if a.startswith("--")]
    rutas = [a for a in argv if not a.startswith("--")]
    windata = buscar_windata(rutas[0] if rutas else None)
    if not windata:
        log("No encuentro el juego automáticamente.")
        log("Arrastra aquí la carpeta del juego (o escribe su ruta) y pulsa ENTER:")
        windata = buscar_windata(input("> "))
    log("Juego: %s" % os.path.dirname(windata))
    log()
    if "--desinstalar" in opciones:
        desinstalar(windata)
    elif "--estado" in opciones:
        mostrar_estado(windata)
    elif "--extraer" in opciones:
        extraer_roms(windata)
    else:
        instalar(windata, elegir_regiones(opciones, windata))


if __name__ == "__main__":
    codigo = 0
    try:
        main(sys.argv[1:])
    except Fallo as e:
        log()
        log("!! " + str(e))
        codigo = 1
    except PermissionError as e:
        log()
        log("!! Sin permiso para escribir (%s)." % e)
        log("   Cierra el juego y, si hace falta, ejecuta el instalador como administrador.")
        codigo = 1
    except (EOFError, KeyboardInterrupt):
        log("Cancelado.")
        codigo = 1
    if os.name == "nt" and "--sin-pausa" not in sys.argv:
        try:
            input("\nPulsa ENTER para salir...")
        except EOFError:
            pass
    sys.exit(codigo)
