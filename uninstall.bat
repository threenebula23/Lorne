@echo off
REM ═══════════════════════════════════════════════════════
REM  TCA — Terminal Coding Assistant — Деинсталляция (Windows)
REM ═══════════════════════════════════════════════════════
REM
REM  Этот скрипт:
REM  1. Удаляет виртуальное окружение (.venv)
REM  2. Опционально удаляет данные сессий, версий и конфиг
REM
REM  Использование:
REM    uninstall.bat
REM ═══════════════════════════════════════════════════════

setlocal enabledelayedexpansion

set "TCA_DIR=%~dp0"
set "TCA_DIR=%TCA_DIR:~0,-1%"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  TCA — Деинсталляция                        ║
echo ╚══════════════════════════════════════════════╝
echo.

REM ─── Remove virtual environment ────────────────────
set "VENV_DIR=%TCA_DIR%\.venv"

if exist "%VENV_DIR%" (
    echo   ... Удаляю виртуальное окружение...
    rmdir /s /q "%VENV_DIR%"
    echo   √ Виртуальное окружение удалено
) else (
    echo   Виртуальное окружение не найдено
)

REM ─── Remove tca.bat from Scripts if exists ─────────
set "TCA_BAT=%VENV_DIR%\Scripts\tca.bat"
if exist "%TCA_BAT%" (
    del /q "%TCA_BAT%"
    echo   √ Лаунчер tca.bat удалён
)

REM ─── Remove TCA data files (optional) ─────────────
echo.
set /p "answer=  Удалить данные сессий, версий и конфиг? [y/N] > "
if /i "!answer!" == "y" (
    if exist "%TCA_DIR%\.tca_checkpoints.sqlite" del /q "%TCA_DIR%\.tca_checkpoints.sqlite"
    if exist "%TCA_DIR%\.tca_versions.sqlite" del /q "%TCA_DIR%\.tca_versions.sqlite"
    if exist "%TCA_DIR%\.tca_plan.json" del /q "%TCA_DIR%\.tca_plan.json"
    if exist "%USERPROFILE%\.tca_config.json" del /q "%USERPROFILE%\.tca_config.json"
    echo   √ Данные удалены
) else (
    echo   Данные сохранены
)

REM ─── Remove __pycache__ ────────────────────────────
for /d /r "%TCA_DIR%" %%D in (__pycache__) do (
    if exist "%%D" rmdir /s /q "%%D"
)
echo   √ Кэш Python очищен

REM ─── Done ──────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════════╗
echo ║  √ TCA деинсталлирован                      ║
echo ╚══════════════════════════════════════════════╝
echo.
echo   Исходный код остался в: %TCA_DIR%
echo   Для полного удаления удалите папку вручную.
echo.

endlocal
