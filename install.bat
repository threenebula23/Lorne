@echo off
REM Lorne v0.98 — установка (Windows)
REM  1. Виртуальное окружение
REM  2. Зависимости (pip покажет собственный прогресс)
REM  3. Команды lorne и tca (алиас) в %%LOCALAPPDATA%%\Lorne + PATH

chcp 65001 >nul
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0"
set "REPO_ROOT=%REPO_ROOT:~0,-1%"

for /f %%t in ('powershell -NoProfile -Command "[int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"') do set "T_BUILD_START=%%t"
set "TOTAL_STEPS=6"
set "CUR_STEP=0"

echo.
echo [========================================]
echo   Lorne v0.98 — установка
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

set "VENV_DIR=%REPO_ROOT%\.venv"
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
pip install -r "%REPO_ROOT%\requirements.txt"
if errorlevel 1 (
    echo   [X] Oshibka pip install
    exit /b 1
)
echo   [OK] Zavisimosti ustanovleny

if not exist "%REPO_ROOT%\Agent\.env" (
    if not exist "%REPO_ROOT%\.env" (
        echo.
        echo   [!] Fail .env ne nayden!
        echo       Sozdayte Agent\.env s API klyuchom.
        echo.
    )
)

call :show_progress "Sozdanie komand lorne / tca i PATH..."

set "SCRIPTS_DIR=%VENV_DIR%\Scripts"
if not exist "%SCRIPTS_DIR%" (
    echo   [X] Papka ne naydena: %SCRIPTS_DIR%
    exit /b 1
)

set "LORNE_BAT=%SCRIPTS_DIR%\lorne.bat"
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%REPO_ROOT%\tca.py" %%*
) > "%LORNE_BAT%"

set "LORNE_CMD=%REPO_ROOT%\lorne.cmd"
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%REPO_ROOT%\tca.py" %%*
) > "%LORNE_CMD%"

set "TCA_BAT=%SCRIPTS_DIR%\tca.bat"
copy /Y "%LORNE_BAT%" "%TCA_BAT%" >nul

set "TCA_CMD=%REPO_ROOT%\tca.cmd"
copy /Y "%LORNE_CMD%" "%TCA_CMD%" >nul

set "LORNE_GLOBAL=%LOCALAPPDATA%\Lorne"
if not exist "%LORNE_GLOBAL%" mkdir "%LORNE_GLOBAL%"
(
    echo @echo off
    echo "%SCRIPTS_DIR%\python.exe" "%REPO_ROOT%\tca.py" %%*
) > "%LORNE_GLOBAL%\lorne.cmd"
copy /Y "%LORNE_GLOBAL%\lorne.cmd" "%LORNE_GLOBAL%\tca.cmd" >nul

set "ADD_PATH=%LORNE_GLOBAL%"
powershell -NoProfile -Command "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($p -notlike '*%ADD_PATH%*') { [Environment]::SetEnvironmentVariable('Path', $p + ';' + '%ADD_PATH%', 'User'); Write-Host '  [OK] lorne i tca dobavleny v PATH (globalno)' } else { Write-Host '  [OK] Lorne uzhe v PATH' }"
if errorlevel 1 (
    echo   [!] Ne udalos dobavit v PATH.
)

call :show_progress "Gotovo"

for /f %%e in ('powershell -NoProfile -Command "([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - !T_BUILD_START!"') do set "BUILD_SEC=%%e"

echo.
echo [========================================]
echo   [OK] Lorne ustanovlen uspeshno!
echo [========================================]
echo.
echo   Vremya ustanovki: !BUILD_SEC! s
echo.
echo   Komandy lorne i tca (alias) dostupny GLOBALNO.
echo   Otkroyte novoe okno konsoli esli komanda esche ne nakhoditsya.
echo.
echo   Ispolzovanie:
echo     lorne                        - zapusk v tekushchey papke
echo     lorne C:\path\to\project      - zapusk v ukazannom proekte
echo     lorne env=sk-or-v1-...       - zapusk s API klyuchom
echo     tca …                        - to zhe (sovmestimost)
echo.

endlocal
