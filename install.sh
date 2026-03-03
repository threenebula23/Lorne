#!/bin/bash
# ═══════════════════════════════════════════════════════
#  TCA — Terminal Coding Assistant — Установка
# ═══════════════════════════════════════════════════════
#
#  Этот скрипт:
#  1. Создаёт виртуальное окружение (если его нет)
#  2. Устанавливает зависимости
#  3. Создаёт команду `tca` доступную из любой директории
#
#  Использование:
#    chmod +x install.sh && ./install.sh
#
#  После установки:
#    tca                          — запуск в текущей директории
#    tca /path/to/project         — запуск в указанном проекте
#    tca env=sk-or-v1-ваш_ключ   — запуск с API ключом OpenRouter
# ═══════════════════════════════════════════════════════

set -e

CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

TCA_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║  TCA — Установка Terminal Coding Assistant   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ─── Python ─────────────────────────────────────────
PYTHON=""
for candidate in python3.11 python3.12 python3.13 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}✗ Python 3.10+ не найден. Установите Python и попробуйте снова.${RESET}"
    exit 1
fi

echo -e "  ${GREEN}✓${RESET} Python: $($PYTHON --version)"

# ─── Virtual environment ────────────────────────────
VENV_DIR="$TCA_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo -e "  ${CYAN}⏳${RESET} Создаю виртуальное окружение..."
    $PYTHON -m venv "$VENV_DIR"
    echo -e "  ${GREEN}✓${RESET} Виртуальное окружение создано: $VENV_DIR"
else
    echo -e "  ${GREEN}✓${RESET} Виртуальное окружение найдено: $VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# ─── Dependencies ───────────────────────────────────
echo -e "  ${CYAN}⏳${RESET} Устанавливаю зависимости..."
pip install --quiet --upgrade pip
pip install --quiet -r "$TCA_DIR/requirements.txt"
echo -e "  ${GREEN}✓${RESET} Зависимости установлены"

# ─── .env check ─────────────────────────────────────
ENV_FILE="$TCA_DIR/Agent/.env"
if [ ! -f "$ENV_FILE" ]; then
    ENV_ROOT="$TCA_DIR/.env"
    if [ ! -f "$ENV_ROOT" ]; then
        echo ""
        echo -e "  ${YELLOW}⚠ Файл .env не найден!${RESET}"
        echo -e "  ${DIM}Создайте Agent/.env с вашим API ключом:${RESET}"
        echo -e "  ${DIM}  echo 'OPENROUTER_API_KEY=ваш_ключ' > $ENV_FILE${RESET}"
        echo ""
    fi
fi

# ─── Create `tca` command ───────────────────────────
TCA_BIN="$VENV_DIR/bin/tca"
cat > "$TCA_BIN" << SCRIPT
#!/bin/bash
TCA_ROOT="$TCA_DIR"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ -n "\$1" ] && [ -d "\$1" ]; then
    cd "\$1"
    shift
fi

exec "\$VENV_PYTHON" "\$TCA_ROOT/tca.py" "\$@"
SCRIPT
chmod +x "$TCA_BIN"

# ─── Symlink to PATH ───────────────────────────────
INSTALL_DIR=""

# Try common user bin locations
for dir in "$HOME/.local/bin" "$HOME/bin" "/usr/local/bin"; do
    if [ -d "$dir" ]; then
        INSTALL_DIR="$dir"
        break
    fi
done

if [ -z "$INSTALL_DIR" ]; then
    INSTALL_DIR="$HOME/.local/bin"
    mkdir -p "$INSTALL_DIR"
fi

SYMLINK="$INSTALL_DIR/tca"

# Remove old symlink if exists
if [ -L "$SYMLINK" ] || [ -f "$SYMLINK" ]; then
    rm -f "$SYMLINK"
fi

ln -s "$TCA_BIN" "$SYMLINK" 2>/dev/null || {
    # If symlink fails (e.g. /usr/local/bin needs sudo), copy instead
    cp "$TCA_BIN" "$SYMLINK" 2>/dev/null || {
        echo -e "  ${YELLOW}⚠ Не удалось создать команду в $INSTALL_DIR${RESET}"
        echo -e "  ${DIM}Добавьте вручную: export PATH=\"$VENV_DIR/bin:\$PATH\"${RESET}"
        SYMLINK=""
    }
}

# ─── Done ───────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  ✓ TCA установлен успешно!                  ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${RESET}"
echo ""

if [ -n "$SYMLINK" ]; then
    echo -e "  Команда ${BOLD}tca${RESET} доступна!"
    echo ""
    echo -e "  ${CYAN}Использование:${RESET}"
    echo -e "    ${BOLD}tca${RESET}                          — запуск в текущей папке"
    echo -e "    ${BOLD}tca /path/to/project${RESET}         — запуск в указанном проекте"
    echo -e "    ${BOLD}tca env=sk-or-v1-...${RESET}         — запуск с API ключом"
    echo ""

    # Check if INSTALL_DIR is in PATH
    case ":$PATH:" in
        *":$INSTALL_DIR:"*) ;;
        *)
            echo -e "  ${YELLOW}⚠ Добавьте в PATH (в ~/.zshrc или ~/.bashrc):${RESET}"
            echo -e "    ${DIM}export PATH=\"$INSTALL_DIR:\$PATH\"${RESET}"
            echo ""
            ;;
    esac
else
    echo -e "  Запуск через venv:"
    echo -e "    ${BOLD}$TCA_BIN${RESET}"
    echo ""
fi
