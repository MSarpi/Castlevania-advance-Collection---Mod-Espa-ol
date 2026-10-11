#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crea la versión MANUAL (arrastrar y soltar) de la traducción a partir de TU
copia de Castlevania Advance Collection. No modifica el juego.

Uso:
    python crear_manual.py                       detecta el juego
    python crear_manual.py "<juego>" "<salida>"  indica el juego y dónde crearla

Resultado (unos 370 MB), en la carpeta "Manual" junto a este archivo:
    Paso-1_Datos/windata/alldata.bin             los datos del juego + todas las traducciones
    Paso-2_Americana/windata/...                 índice: español en la versión americana
    Paso-2_Europea/windata/...                   índice: español en la versión europea
    Paso-2_Americana-y-europea/windata/...       índice: español en las dos
    Volver-al-original/windata/alldata.psb.m     índice original

OJO: esa carpeta contiene el juego completo. Es para uso propio: no la
compartas ni la subas a ningún sitio. Solo vale para la versión del juego
con la que se creó; si el juego se actualiza, hay que crearla de nuevo.
"""
import datetime
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import instalar as I  # noqa: E402
import marchive  # noqa: E402

OPCIONES = (("Paso-2_Americana", ["us"]),
            ("Paso-2_Europea", ["eu"]),
            ("Paso-2_Americana-y-europea", ["us", "eu"]))

LEEME = """
VERSIÓN MANUAL (arrastrar y soltar)
===================================

Carpeta del juego:
   C:\\Program Files (x86)\\Steam\\steamapps\\common\\Castlevania Advance Collection
   (en Steam: clic derecho en el juego > Administrar > Ver archivos locales)

Cierra el juego antes de empezar. Son dos arrastres: en los dos se arrastra
la carpeta "windata" que hay DENTRO de la carpeta indicada hasta la carpeta
del juego, y se acepta reemplazar los archivos (y el permiso de
administrador, si Windows lo pide).

PASO 1 - una sola vez
   Carpeta "Paso-1_Datos".
   Lleva los datos del juego con todas las traducciones dentro.

PASO 2 - elige UNA
   "Paso-2_Americana"             español en la versión americana (US)
   "Paso-2_Europea"               español en la versión europea (EU)
   "Paso-2_Americana-y-europea"   español en las dos

Luego abre el juego y, en el menú de la colección, elige esa versión de
cada título. Las versiones que no elijas siguen en su idioma original.
En Aria of Sorrow europeo el español sustituye al inglés: si pusiste el
juego en francés o alemán, vuelve a English.

Para cambiar de opción basta repetir el paso 2 con otra carpeta.

VOLVER AL ORIGINAL
   Arrastra la "windata" de la carpeta "Volver-al-original".
   Si algo no quedara bien, Steam lo arregla siempre: clic derecho en el
   juego > Propiedades > Archivos instalados > Verificar integridad.

CUÁNDO HAY QUE REPETIRLO
   Si Steam verifica o repara los archivos, el juego vuelve a su idioma
   original: repite los pasos 1 y 2. Lo mismo si entre medias usaste el
   instalador (Instalar.bat o Desinstalar.bat).

IMPORTANTE
 - Estos archivos salieron de tu copia del juego el %(fecha)s. Si el juego
   recibe una actualización de verdad, NO uses esta carpeta (lo dejarías
   con datos antiguos): usa el instalador, o crea de nuevo esta carpeta
   con crear_manual.py.
   Cómo saberlo: antes del paso 1, mira cuánto ocupa windata\\alldata.bin
   en la carpeta del juego (clic derecho > Propiedades > Tamaño):
       %(tam_original)s bytes  = juego original
       %(tam_manual)s bytes  = con estos datos ya puestos
   Si sale otro número y no has usado el instalador, el juego cambió.
 - No compartas ni subas esta carpeta a GitHub ni a ningún sitio:
   alldata.bin es el juego entero. Para compartir está el instalador.
 - Solo se reemplazan archivos de datos del juego; tus partidas no cambian.
 - Es compatible con el instalador: después de arrastrar, Desinstalar.bat
   también funciona.
"""


def miles(n):
    return "{:,}".format(n).replace(",", ".")


def crear(windata, salida):
    arch = I.Archivo(windata)
    est = arch.estado()
    instalado = bool(est and os.path.isfile(arch.r_respaldo)
                     and est.get("indice_mod_sha1") == I.sha1(I.leer(arch.r_indice)))
    blob_original = I.leer(arch.r_respaldo if instalado else arch.r_indice)
    info = arch.abrir_indice(blob_original).root["file_info"]
    tam_orig = arch.tam_original(info)
    if os.path.getsize(arch.r_datos) < tam_orig:
        raise I.Fallo("%s está incompleto." % I.DATOS)

    def carpeta(nombre):
        ruta = os.path.join(salida, nombre, "windata")
        os.makedirs(ruta, exist_ok=True)
        return ruta

    # Paso 1: los datos originales y, detrás, todos los ROMs traducidos.
    hechos = []
    destino = os.path.join(carpeta("Paso-1_Datos"), I.DATOS)
    I.log("Creando %s ..." % destino)
    with open(arch.r_datos, "rb") as f, open(destino, "wb") as out:
        falta = tam_orig
        while falta:
            trozo = f.read(min(I.BLOQUE, falta))
            if not trozo:
                raise I.Fallo("No se pudo leer %s entero." % I.DATOS)
            out.write(trozo)
            falta -= len(trozo)
        pos = tam_orig
        for juego in I.cargar_catalogo():
            parches = I.parches_de(juego)
            if not parches or juego["entrada"] not in info:
                I.log("   Se omite %s (%s)." % (juego["nombre"], juego["version"]))
                continue
            rom = arch.extraer(f, info, juego["entrada"])
            if I.sha1(rom) != juego.get("sha1_rom"):
                I.log("   Aviso: el ROM de %s (%s) difiere del probado." % (juego["nombre"], juego["version"]))
            for nombre, datos in parches:
                rom = I.aplicar_ips(rom, datos, nombre)
            blob = marchive.mdf_pack(rom, I.SEMILLA, os.path.basename(juego["entrada"]), I.LARGO_CLAVE)
            out.seek(pos)
            out.write(blob)
            hechos.append(({"id": juego["id"], "nombre": juego["nombre"], "entrada": juego["entrada"],
                            "region": juego.get("region", "us"), "version": juego["version"],
                            "parches": [n for n, _ in parches], "sha1_rom_es": I.sha1(rom)},
                           [pos, len(blob)]))
            pos = I.alinear(pos + len(blob))
            out.truncate(pos)
            I.log("   + %s, versión %s" % (juego["nombre"], juego["version"]))
        tam_manual = pos
    if not hechos:
        raise I.Fallo("No hay ningún parche que aplicar.")

    # Paso 2: un índice por opción (y lo necesario para que el instalador lo reconozca).
    for nombre, regiones in OPCIONES:
        psb = arch.abrir_indice(blob_original)
        elegidos = [(h, donde) for h, donde in hechos if h["region"] in regiones]
        for h, donde in elegidos:
            psb.root["file_info"][h["entrada"]] = list(donde)
        indice = arch.cerrar_indice(psb)
        ruta = carpeta(nombre)
        I.escribir(os.path.join(ruta, I.INDICE), indice)
        I.escribir(os.path.join(ruta, I.RESPALDO), blob_original)
        with open(os.path.join(ruta, I.ESTADO), "w", encoding="utf-8") as f:
            json.dump(I.estado_nuevo(indice, tam_orig, [h for h, _ in elegidos]), f,
                      ensure_ascii=False, indent=1)
    I.escribir(os.path.join(carpeta("Volver-al-original"), I.INDICE), blob_original)

    texto = LEEME.strip("\n") % {"fecha": datetime.date.today().strftime("%d/%m/%Y"),
                                 "tam_original": miles(tam_orig), "tam_manual": miles(tam_manual)}
    I.escribir(os.path.join(salida, "LEEME.txt"), ("\ufeff" + texto + "\n").replace("\n", "\r\n").encode("utf-8"))
    I.log()
    I.log("*** Versión manual creada en: %s ***" % salida)
    I.log("Contiene el juego completo: es para ti, no la compartas.")


def main(argv):
    rutas = [a for a in argv if not a.startswith("--")]
    windata = I.buscar_windata(rutas[0] if rutas else None)
    if not windata:
        raise I.Fallo("No encuentro el juego. Indica su carpeta: python crear_manual.py \"<carpeta del juego>\"")
    crear(windata, rutas[1] if len(rutas) > 1 else os.path.join(AQUI, "Manual"))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except I.Fallo as e:
        I.log("!! " + str(e))
        sys.exit(1)
