@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 --version >nul 2>nul
if not errorlevel 1 (
  py -3 instalar.py %*
  goto :eof
)
python --version >nul 2>nul
if not errorlevel 1 (
  python instalar.py %*
  goto :eof
)
echo No encuentro Python 3 en este equipo.
echo Instalalo gratis desde https://www.python.org/downloads/ ^(marca "Add python.exe to PATH"^)
echo o desde la Microsoft Store, y vuelve a abrir este archivo.
pause
