@echo off
REM Lorne v0.98 — деинсталляция (Windows)
chcp 65001 >nul
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0"
set "REPO_ROOT=%REPO_ROOT:~0,-1%"

for /f %%t in ('powershell -NoProfile -Command "[int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"') do set "T0=%%t"
set "TOTAL_STEPS=5"
set "USTEP=0"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  Lorne — деинсталляция                      ║
echo ╚══════════════════════════════════════════════╝
echo.

goto :after_u_prog
:u_progress
set /a USTEP+=1
set "UMSG=%~1"
set /a UF=!USTEP! * 14 / !TOTAL_STEPS!
if !UF! gtr 14 set UF=14
set /a UE=14-UF
set "UBF="
set "UBE="
for /l %%i in (1,1,!UF!) do set "UBF=!UBF!#"
for /l %%i in (1,1,!UE!) do set "UBE=!UBE!-"
for /f %%e in ('powershell -NoProfile -Command "([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - !T0!"') do set "UEL=%%e"
echo   [!UBF!!UBE!] !USTEP!/!TOTAL_STEPS!  !UEL!s  !UMSG!
exit /b 0
:after_u_prog

call :u_progress "Udalyayu globalnye zapuskachi lorne / tca..."
if exist "%LOCALAPPDATA%\Lorne\lorne.cmd" del /q "%LOCALAPPDATA%\Lorne\lorne.cmd" 2>nul
if exist "%LOCALAPPDATA%\Lorne\tca.cmd" del /q "%LOCALAPPDATA%\Lorne\tca.cmd" 2>nul
if exist "%LOCALAPPDATA%\Lorne" dir /b "%LOCALAPPDATA%\Lorne" 2>nul | findstr /r "." >nul || rmdir "%LOCALAPPDATA%\Lorne" 2>nul
if exist "%LOCALAPPDATA%\TCA\tca.cmd" (
    del /q "%LOCALAPPDATA%\TCA\tca.cmd" 2>nul
    if exist "%LOCALAPPDATA%\TCA" dir /b "%LOCALAPPDATA%\TCA" 2>nul | findstr /r "." >nul || rmdir "%LOCALAPPDATA%\TCA" 2>nul
)

call :u_progress "Udalyayu virtualnoe okruzhenie..."
set "VENV_DIR=%REPO_ROOT%\.venv"
if exist "%VENV_DIR%" (
    if exist "%VENV_DIR%\Scripts\lorne.bat" del /q "%VENV_DIR%\Scripts\lorne.bat" 2>nul
    if exist "%VENV_DIR%\Scripts\tca.bat" del /q "%VENV_DIR%\Scripts\tca.bat" 2>nul
    rmdir /s /q "%VENV_DIR%"
    echo   OK: .venv udalen
) else (
    echo   .venv ne nayden
)

call :u_progress "Opcionalno: dannye..."
echo.
set /p "answer=  Udalit dannye sessiy, versiy i konfig? [y/N] > "
if /i "!answer!" == "y" (
    if exist "%REPO_ROOT%\.tca" rmdir /s /q "%REPO_ROOT%\.tca"
    if exist "%REPO_ROOT%\.tca_checkpoints.sqlite" del /q "%REPO_ROOT%\.tca_checkpoints.sqlite"
    if exist "%REPO_ROOT%\.tca_versions.sqlite" del /q "%REPO_ROOT%\.tca_versions.sqlite"
    if exist "%REPO_ROOT%\.tca_plan.json" del /q "%REPO_ROOT%\.tca_plan.json"
    if exist "%USERPROFILE%\.tca_config.json" del /q "%USERPROFILE%\.tca_config.json"
    echo   OK: dannye udaleny
) else (
    echo   dannye sokhraneny
)

call :u_progress "Chistka __pycache__..."
for /d /r "%REPO_ROOT%" %%D in (__pycache__) do (
    if exist "%%D" rmdir /s /q "%%D"
)
echo   OK: kesh ochischen

call :u_progress "Gotovo"

for /f %%e in ('powershell -NoProfile -Command "([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - !T0!"') do set "USEC=%%e"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  OK Lorne deinstallyirovan                  ║
echo ╚══════════════════════════════════════════════╝
echo.
echo   Vremya: !USEC! s
echo.
echo   Ishodnyy kod ostalsya v: %REPO_ROOT%
echo   Udalite papku vruchnuyu dlya polnogo udaleniya.
echo.

endlocal
