@echo off
REM TCA - Terminal Coding Assistant - Ustanovka (Windows)
REM  1. Sozdaet virtualnoe okruzhenie (esli net)
REM  2. Ustanavlivaet zavisimosti
REM  3. Sozdaet komandu tca v .venv\Scripts (dolzhen byt v PATH)

chcp 65001 >nul
setlocal enabledelayedexpansion

set "TCA_DIR=%~dp0"
set "TCA_DIR=%TCA_DIR:~0,-1%"

echo.
echo [========================================]
echo   TCA - Ustanovka Terminal Coding Assistant
echo [========================================]
echo.

REM Python: py launcher ili python/python3 (NELZYa stavit "py -3" v odnu peremennuyu!)
set "PYTHON="
set "PYTHON_EXTRA="

REM 1. Python Launcher (py.exe)
where py >nul 2>&1
if !errorlevel! equ 0 (
    py -3 --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=py"
        set "PYTHON_EXTRA=-3"
        goto :found_python
    )
    py --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=py"
        set "PYTHON_EXTRA="
        goto :found_python
    )
)

REM 2. python, python3
for %%P in (python python3) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=%%P"
        set "PYTHON_EXTRA="
        goto :found_python
    )
)

echo   [X] Python ne nayden. Ustanovite Python 3.10+ s python.org
echo       i otmette "Add Python to PATH" ili Python Launcher.
exit /b 1

:found_python
for /f "tokens=2 delims= " %%V in ('"%PYTHON%" %PYTHON_EXTRA% --version 2^>^&1') do set "PYVER=%%V"
for /f "tokens=1,2 delims=." %%A in ("%PYVER%") do (
    set "PY_MAJOR=%%A"
    set "PY_MINOR=%%B"
)
if !PY_MAJOR! lss 3 (
    echo   [X] Trebuetsya Python 3.10+. Nayden: %PYVER%
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 10 (
    echo   [X] Trebuetsya Python 3.10+. Nayden: %PYVER%
    exit /b 1
)
echo   [OK] Python: %PYVER%

REM Virtual environment
set "VENV_DIR=%TCA_DIR%\.venv"

if not exist "%VENV_DIR%" (
    echo   Sozdayu virtualnoe okruzhenie...
    "%PYTHON%" %PYTHON_EXTRA% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo   [X] Oshibka sozdaniya venv. Proverte: "%PYTHON%" %PYTHON_EXTRA% -m venv
        exit /b 1
    )
    echo   [OK] Virtualnoe okruzhenie sozdano
) else (
    echo   [OK] Virtualnoe okruzhenie naydeno
)

REM Activate venv
call "%VENV_DIR%\Scripts\activate.bat"

REM Dependencies
echo   Ustanavlivayu zavisimosti...
pip install --quiet --upgrade pip
pip install --quiet -r "%TCA_DIR%\requirements.txt"
echo   [OK] Zavisimosti ustanovleny

REM .env check
if not exist "%TCA_DIR%\Agent\.env" (
    if not exist "%TCA_DIR%\.env" (
        echo.
        echo   [!] Fail .env ne nayden!
        echo       Sozdayte Agent\.env s API klyuchom:
        echo       echo OPENROUTER_API_KEY=vash_klyuch ^> "%TCA_DIR%\Agent\.env"
        echo.
    )
)

REM Create tca.bat in .venv\Scripts
set "TCA_BAT=%VENV_DIR%\Scripts\tca.bat"
set "SCRIPTS_DIR=%VENV_DIR%\Scripts"
if not exist "%SCRIPTS_DIR%" (
    echo   [X] Papka ne naydena: %SCRIPTS_DIR%
    exit /b 1
)
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%TCA_DIR%\tca.py" %%*
) > "%TCA_BAT%"

REM tca.cmd v korne proekta (dlya zapuska iz papki proekta)
set "TCA_CMD=%TCA_DIR%\tca.cmd"
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%TCA_DIR%\tca.py" %%*
) > "%TCA_CMD%"

REM Globalnaya komanda: papka v profile usera, dobavlyaem v PATH (rabotaet iz lyuboy direktori)
set "TCA_GLOBAL=%LOCALAPPDATA%\TCA"
if not exist "%TCA_GLOBAL%" mkdir "%TCA_GLOBAL%"
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%TCA_DIR%\tca.py" %%*
) > "%TCA_GLOBAL%\tca.cmd"

REM Dobavit TCA_GLOBAL v polzovatelskiy PATH (bez obrezki - cherez PowerShell)
set "ADD_PATH=%TCA_GLOBAL%"
powershell -NoProfile -Command "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($p -notlike '*%ADD_PATH%*') { [Environment]::SetEnvironmentVariable('Path', $p + ';' + '%ADD_PATH%', 'User'); Write-Host '  [OK] Komanda tca dobavlena v PATH (globalno)' } else { Write-Host '  [OK] tca uzhe v PATH' }"
if errorlevel 1 (
    echo   [!] Ne udalos dobavit v PATH. Dobavte vruchnuyu: set "PATH=%%PATH%%;%TCA_GLOBAL%"
)

echo.
echo [========================================]
echo   [OK] TCA ustanovlen uspeshno!
echo [========================================]
echo.
echo   Komanda tca dostupna GLOBALNO (iz lyuboy papki).
echo   Otkroyte novoe okno konsoli esli tca esche ne nakhoditsya.
echo.
echo   Ispolzovanie:
echo     tca                          - zapusk v tekushchey papke
echo     tca C:\path\to\project        - zapusk v ukazannom proekte
echo     tca env=sk-or-v1-...         - zapusk s API klyuchom
echo.

endlocal
