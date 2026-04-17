@echo off
REM TCA - Terminal Coding Assistant - Ustanovka (Windows)
REM  1. Virtualnoe okruzhenie
REM  2. Zavisimosti (pip pokazhet sobstvennyy progress)
REM  3. Komanda tca v %%LOCALAPPDATA%%\TCA + PATH

chcp 65001 >nul
setlocal enabledelayedexpansion

set "TCA_DIR=%~dp0"
set "TCA_DIR=%TCA_DIR:~0,-1%"

for /f %%t in ('powershell -NoProfile -Command "[int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"') do set "T_BUILD_START=%%t"
set "TOTAL_STEPS=6"
set "CUR_STEP=0"

echo.
echo [========================================]
echo   TCA - Ustanovka Terminal Coding Assistant
echo [========================================]
echo.

goto :after_sub_show_progress
:show_progress
set /a CUR_STEP+=1
set "PMSG=%~1"
set /a FILLED=!CUR_STEP! * 18 / !TOTAL_STEPS!
if !FILLED! gtr 18 set FILLED=18
set /a EMPTY=18 - FILLED
set "BARF="
set "BARE="
for /l %%i in (1,1,!FILLED!) do set "BARF=!BARF!#"
for /l %%i in (1,1,!EMPTY!) do set "BARE=!BARE!-"
for /f %%e in ('powershell -NoProfile -Command "([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - !T_BUILD_START!"') do set "ELAPSED=%%e"
echo   [!BARF!!BARE!] !CUR_STEP!/!TOTAL_STEPS!  !ELAPSED!s  !PMSG!
exit /b 0
:after_sub_show_progress

set "PYTHON="
set "PYTHON_EXTRA="

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

for %%P in (python python3) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=%%P"
        set "PYTHON_EXTRA="
        goto :found_python
    )
)

echo   [X] Python ne nayden. Ustanovite Python 3.10+ s python.org
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
call :show_progress "Proverka Python: %PYVER%"

set "VENV_DIR=%TCA_DIR%\.venv"
if not exist "%VENV_DIR%" (
    call :show_progress "Sozdanie virtualnogo okruzheniya..."
    "%PYTHON%" %PYTHON_EXTRA% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo   [X] Oshibka sozdaniya venv.
        exit /b 1
    )
) else (
    call :show_progress "Virtualnoe okruzhenie uzhe est"
)

call "%VENV_DIR%\Scripts\activate.bat"

call :show_progress "Obnovlenie pip..."
pip install --quiet --upgrade pip
if errorlevel 1 (
    echo   [X] Oshibka pip upgrade
    exit /b 1
)

call :show_progress "Ustanovka zavisimostey (requirements.txt)..."
echo   (nizhe — progress pip)
pip install -r "%TCA_DIR%\requirements.txt"
if errorlevel 1 (
    echo   [X] Oshibka pip install
    exit /b 1
)
echo   [OK] Zavisimosti ustanovleny

if not exist "%TCA_DIR%\Agent\.env" (
    if not exist "%TCA_DIR%\.env" (
        echo.
        echo   [!] Fail .env ne nayden!
        echo       Sozdayte Agent\.env s API klyuchom.
        echo.
    )
)

call :show_progress "Sozdanie komandy tca i PATH..."

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

set "TCA_CMD=%TCA_DIR%\tca.cmd"
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%TCA_DIR%\tca.py" %%*
) > "%TCA_CMD%"

set "TCA_GLOBAL=%LOCALAPPDATA%\TCA"
if not exist "%TCA_GLOBAL%" mkdir "%TCA_GLOBAL%"
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%TCA_DIR%\tca.py" %%*
) > "%TCA_GLOBAL%\tca.cmd"

set "ADD_PATH=%TCA_GLOBAL%"
powershell -NoProfile -Command "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($p -notlike '*%ADD_PATH%*') { [Environment]::SetEnvironmentVariable('Path', $p + ';' + '%ADD_PATH%', 'User'); Write-Host '  [OK] tca dobavlena v PATH (globalno)' } else { Write-Host '  [OK] tca uzhe v PATH' }"
if errorlevel 1 (
    echo   [!] Ne udalos dobavit v PATH.
)

call :show_progress "Gotovo"

for /f %%e in ('powershell -NoProfile -Command "([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - !T_BUILD_START!"') do set "BUILD_SEC=%%e"

echo.
echo [========================================]
echo   [OK] TCA ustanovlen uspeshno!
echo [========================================]
echo.
echo   Vremya ustanovki: !BUILD_SEC! s
echo.
echo   Komanda tca dostupna GLOBALNO.
echo   Otkroyte novoe okno konsoli esli tca esche ne nakhoditsya.
echo.
echo   Ispolzovanie:
echo     tca                          - zapusk v tekushchey papke
echo     tca C:\path\to\project        - zapusk v ukazannom proekte
echo     tca env=sk-or-v1-...         - zapusk s API klyuchom
echo.

endlocal
