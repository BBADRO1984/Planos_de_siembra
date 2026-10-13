@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Planos de siembra v5

python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Se necesita Python 3.10 o mas nuevo ^(marcando "Add Python to PATH" al instalarlo^).
    echo Descargalo en https://www.python.org/downloads/
    pause
    exit /b
)

echo Verificando librerias ^(la primera vez puede tardar unos minutos^)...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo No se pudieron instalar las librerias. Revisa la conexion a internet.
    pause
    exit /b
)

echo.
echo Abriendo la app en el navegador. Para cerrarla, cerra esta ventana.
python -m streamlit run app.py
pause
