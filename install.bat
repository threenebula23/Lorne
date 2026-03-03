@echo off
REM ═══════════════════════════════════════════════════════
REM  TCA — Terminal Coding Assistant — Установка (Windows)
REM ═══════════════════════════════════════════════════════
REM
REM  Этот скрипт:
REM  1. Создаёт виртуальное окружение (если его нет)
REM  2. Устанавливает зависимости
REM  3. Создаёт команду `tca` доступную из любой директории
REM
REM  Использование:
REM    install.bat
REM
REM  После установки:
REM    tca                          — запуск в текущей директории
REM    tca C:\path\to\project       — запуск в указанном проекте
REM    tca env=sk-or-v1-ваш_ключ   — запуск с API ключом OpenRouter
REM ═══════════════════════════════════════════════════════

setlocal enabledelayedexpansion

set "TCA_DIR=%~dp0"
set "TCA_DIR=%TCA_DIR:~0,-1%"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  TCA — Установка Terminal Coding Assistant   ║
echo ╚══════════════════════════════════════════════╝
echo.

REM ─── Python ─────────────────────────────────────────
set "PYTHON="
for %%P in (python3 python py) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=%%P"
        goto :found_python
    )
)

echo   X Python не найден. Установите Python 3.10+ и попробуйте снова.
exit /b 1

:found_python
for /f "tokens=2 delims= " %%V in ('%PYTHON% --version 2^>^&1') do set "PYVER=%%V"
for /f "tokens=1,2 delims=." %%A in ("%PYVER%") do (
    set "PY_MAJOR=%%A"
    set "PY_MINOR=%%B"
)
if !PY_MAJOR! lss 3 (
    echo   X Требуется Python 3.10+. Найден: %PYVER%
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 10 (
    echo   X Требуется Python 3.10+. Найден: %PYVER%
    exit /b 1
)
echo   √ Python: %PYVER%

REM ─── Virtual environment ────────────────────────────
set "VENV_DIR=%TCA_DIR%\.venv"

if not exist "%VENV_DIR%" (
    echo   ... Создаю виртуальное окружение...
    %PYTHON% -m venv "%VENV_DIR%"
    echo   √ Виртуальное окружение создано
) else (
    echo   √ Виртуальное окружение найдено
)

REM Activate venv
call "%VENV_DIR%\Scripts\activate.bat"

REM ─── Dependencies ───────────────────────────────────
echo   ... Устанавливаю зависимости...
pip install --quiet --upgrade pip
pip install --quiet -r "%TCA_DIR%\requirements.txt"
echo   √ Зависимости установлены

REM ─── .env check ─────────────────────────────────────
if not exist "%TCA_DIR%\Agent\.env" (
    if not exist "%TCA_DIR%\.env" (
        echo.
        echo   ! Файл .env не найден!
        echo     Создайте Agent\.env с вашим API ключом:
        echo     echo OPENROUTER_API_KEY=ваш_ключ ^> "%TCA_DIR%\Agent\.env"
        echo.
    )
)

REM ─── Create tca.bat command ─────────────────────────
set "TCA_BAT=%VENV_DIR%\Scripts\tca.bat"
(
    echo @echo off
    echo set "TCA_ROOT=%TCA_DIR%"
    echo set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
    echo if "%%1" neq "" if exist "%%1\" (
    echo     cd /d "%%1"
    echo     shift
    echo ^)
    echo "%%VENV_PYTHON%%" "%%TCA_ROOT%%\tca.py" %%*
) > "%TCA_BAT%"

REM ─── Add to PATH ────────────────────────────────────
set "SCRIPTS_DIR=%VENV_DIR%\Scripts"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  √ TCA установлен успешно!                  ║
echo ╚══════════════════════════════════════════════╝
echo.
echo   Использование:
echo     tca                          — запуск в текущей папке
echo     tca C:\path\to\project       — запуск в указанном проекте
echo     tca env=sk-or-v1-...         — запуск с API ключом
echo.
echo   Если команда tca не найдена, добавьте в PATH:
echo     set PATH=%SCRIPTS_DIR%;%%PATH%%
echo.
echo   Или запускайте напрямую:
echo     "%TCA_BAT%"
echo.

endlocal
