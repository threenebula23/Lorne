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
INSTALL_T0=$(date +%s)

_elapsed_s() {
    echo $(($(date +%s) - INSTALL_T0))
}

# Прогресс: [████░░░░] step/total  Ns  сообщение
_tca_progress() {
    local step="$1"
    local total="$2"
    local msg="$3"
    local width=18
    local filled=$((step * width / total))
    [ "$filled" -gt "$width" ] && filled=$width
    local empty=$((width - filled))
    local bar_f=""
    local bar_e=""
    local i
    for ((i = 0; i < filled; i++)); do bar_f+="█"; done
    for ((i = 0; i < empty; i++)); do bar_e+="░"; done
    printf "  [%b%s%b%s] %d/%d  %ds  %s\n" \
        "$CYAN" "$bar_f" "$DIM" "$bar_e" "$step" "$total" "$(_elapsed_s)" "$msg"
}

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║  TCA — Установка Terminal Coding Assistant   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""

TOTAL_STEPS=6

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

_tca_progress 1 "$TOTAL_STEPS" "Проверка Python: $($PYTHON --version 2>&1)"

# ─── Virtual environment ────────────────────────────
VENV_DIR="$TCA_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    _tca_progress 2 "$TOTAL_STEPS" "Создание виртуального окружения…"
    $PYTHON -m venv "$VENV_DIR"
else
    _tca_progress 2 "$TOTAL_STEPS" "Виртуальное окружение уже есть"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# ─── Dependencies ───────────────────────────────────
_tca_progress 3 "$TOTAL_STEPS" "Обновление pip…"
pip install --quiet --upgrade pip

_tca_progress 4 "$TOTAL_STEPS" "Установка зависимостей (requirements.txt)…"
echo -e "  ${DIM}(ниже — прогресс pip: загрузка и установка пакетов)${RESET}"
pip install -r "$TCA_DIR/requirements.txt"
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
_tca_progress 5 "$TOTAL_STEPS" "Создание команды tca и ссылка в PATH…"

TCA_BIN="$VENV_DIR/bin/tca"
cat > "$TCA_BIN" << SCRIPT
#!/bin/bash
# TCA wrapper — all argument handling (directory, env=KEY) is in tca.py
exec "$VENV_DIR/bin/python" "$TCA_DIR/tca.py" "\$@"
SCRIPT
chmod +x "$TCA_BIN"

INSTALL_DIR=""
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

if [ -L "$SYMLINK" ] || [ -f "$SYMLINK" ]; then
    rm -f "$SYMLINK"
fi

ln -s "$TCA_BIN" "$SYMLINK" 2>/dev/null || {
    cp "$TCA_BIN" "$SYMLINK" 2>/dev/null || {
        echo -e "  ${YELLOW}⚠ Не удалось создать команду в $INSTALL_DIR${RESET}"
        echo -e "  ${DIM}Добавьте вручную: export PATH=\"$VENV_DIR/bin:\$PATH\"${RESET}"
        SYMLINK=""
    }
}

# ─── Done ───────────────────────────────────────────
_tca_progress "$TOTAL_STEPS" "$TOTAL_STEPS" "Готово"

ELAPSED=$(_elapsed_s)
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  ✓ TCA установлен успешно!                  ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${DIM}Время установки: ${BOLD}${ELAPSED}${RESET}${DIM} с${RESET}"
echo ""

if [ -n "$SYMLINK" ]; then
    echo -e "  Команда ${BOLD}tca${RESET} доступна!"
    echo ""
    echo -e "  ${CYAN}Использование:${RESET}"
    echo -e "    ${BOLD}tca${RESET}                          — запуск в текущей папке"
    echo -e "    ${BOLD}tca /path/to/project${RESET}         — запуск в указанном проекте"
    echo -e "    ${BOLD}tca env=sk-or-v1-...${RESET}         — запуск с API ключом"
    echo ""

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
