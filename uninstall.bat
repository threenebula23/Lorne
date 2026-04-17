@echo off
REM TCA — Deinstallyatsiya (Windows)
chcp 65001 >nul
setlocal enabledelayedexpansion

set "TCA_DIR=%~dp0"
set "TCA_DIR=%TCA_DIR:~0,-1%"

for /f %%t in ('powershell -NoProfile -Command "[int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"') do set "T0=%%t"
set "TOTAL_STEPS=5"
set "USTEP=0"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  TCA — Деинсталляция                        ║
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

call :u_progress "Udalyayu globalnyy zapuskach tca..."
if exist "%LOCALAPPDATA%\TCA\tca.cmd" (
    del /q "%LOCALAPPDATA%\TCA\tca.cmd" 2>nul
    if exist "%LOCALAPPDATA%\TCA" dir /b "%LOCALAPPDATA%\TCA" 2>nul | findstr /r "." >nul || rmdir "%LOCALAPPDATA%\TCA" 2>nul
)

call :u_progress "Udalyayu virtualnoe okruzhenie..."
set "VENV_DIR=%TCA_DIR%\.venv"
if exist "%VENV_DIR%" (
    rmdir /s /q "%VENV_DIR%"
    echo   OK: .venv udalen
) else (
    echo   .venv ne nayden
)

call :u_progress "Opcionalno: dannye..."
echo.
set /p "answer=  Udalit dannye sessiy, versiy i konfig? [y/N] > "
if /i "!answer!" == "y" (
    if exist "%TCA_DIR%\.tca" rmdir /s /q "%TCA_DIR%\.tca"
    if exist "%TCA_DIR%\.tca_checkpoints.sqlite" del /q "%TCA_DIR%\.tca_checkpoints.sqlite"
    if exist "%TCA_DIR%\.tca_versions.sqlite" del /q "%TCA_DIR%\.tca_versions.sqlite"
    if exist "%TCA_DIR%\.tca_plan.json" del /q "%TCA_DIR%\.tca_plan.json"
    if exist "%USERPROFILE%\.tca_config.json" del /q "%USERPROFILE%\.tca_config.json"
    echo   OK: dannye udaleny
) else (
    echo   dannye sokhraneny
)

call :u_progress "Chistka __pycache__..."
for /d /r "%TCA_DIR%" %%D in (__pycache__) do (
    if exist "%%D" rmdir /s /q "%%D"
)
echo   OK: kesh ochischen

call :u_progress "Gotovo"

for /f %%e in ('powershell -NoProfile -Command "([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - !T0!"') do set "USEC=%%e"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  OK TCA deinstallyirovan                    ║
echo ╚══════════════════════════════════════════════╝
echo.
echo   Vremya: !USEC! s
echo.
echo   Ishodnyy kod ostalsya v: %TCA_DIR%
echo   Udalite papku vruchnuyu dlya polnogo udaleniya.
echo   Primenenie PATH: otkroyte novyy CMD posle udaleniya tca iz PATH vruchnuyu esli nuzhno.
echo.

endlocal
