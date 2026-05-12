#!/bin/bash
# ═══════════════════════════════════════════════════════
#  Lorne v0.98 — терминальный ассистент для кода — установка
# ═══════════════════════════════════════════════════════
#
#  Этот скрипт:
#  1. Создаёт виртуальное окружение (если его нет)
#  2. Устанавливает зависимости
#  3. Создаёт команды ``lorne`` и ``tca`` (алиас) в PATH
#
#  Использование:
#    chmod +x install.sh && ./install.sh
#
#  После установки:
#    lorne                        — запуск в текущей директории
#    lorne /path/to/project       — запуск в указанном проекте
#    lorne env=sk-or-v1-ваш_ключ  — запуск с API ключом OpenRouter
#    tca …                        — то же (совместимость со старыми инструкциями)
# ═══════════════════════════════════════════════════════

set -e

CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
INSTALL_T0=$(date +%s)

_elapsed_s() {
    echo $(($(date +%s) - INSTALL_T0))
}

# Прогресс: [████░░░░] step/total  Ns  сообщение
_install_progress() {
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
echo -e "${BOLD}║  Lorne v0.98 — установка                      ║${RESET}"
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

_install_progress 1 "$TOTAL_STEPS" "Проверка Python: $($PYTHON --version 2>&1)"

# ─── Virtual environment ────────────────────────────
VENV_DIR="$REPO_ROOT/.venv"

if [ ! -d "$VENV_DIR" ]; then
    _install_progress 2 "$TOTAL_STEPS" "Создание виртуального окружения…"
    $PYTHON -m venv "$VENV_DIR"
else
    _install_progress 2 "$TOTAL_STEPS" "Виртуальное окружение уже есть"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# ─── Dependencies ───────────────────────────────────
_install_progress 3 "$TOTAL_STEPS" "Обновление pip…"
pip install --quiet --upgrade pip

_install_progress 4 "$TOTAL_STEPS" "Установка зависимостей (requirements.txt)…"
echo -e "  ${DIM}(ниже — прогресс pip: загрузка и установка пакетов)${RESET}"
pip install -r "$REPO_ROOT/requirements.txt"
echo -e "  ${GREEN}✓${RESET} Зависимости установлены"

# ─── .env check ─────────────────────────────────────
ENV_FILE="$REPO_ROOT/Agent/.env"
if [ ! -f "$ENV_FILE" ]; then
    ENV_ROOT="$REPO_ROOT/.env"
    if [ ! -f "$ENV_ROOT" ]; then
        echo ""
        echo -e "  ${YELLOW}⚠ Файл .env не найден!${RESET}"
        echo -e "  ${DIM}Создайте Agent/.env с вашим API ключом:${RESET}"
        echo -e "  ${DIM}  echo 'OPENROUTER_API_KEY=ваш_ключ' > $ENV_FILE${RESET}"
        echo ""
    fi
fi

# ─── Команды ``lorne`` и ``tca`` (алиас в venv) ──────
_install_progress 5 "$TOTAL_STEPS" "Создание команд lorne / tca и ссылки в PATH…"

LORNE_BIN="$VENV_DIR/bin/lorne"
cat > "$LORNE_BIN" << SCRIPT
#!/bin/bash
# Lorne — обёртка; аргументы (каталог, env=KEY) обрабатывает tca.py
exec "$VENV_DIR/bin/python" "$REPO_ROOT/tca.py" "\$@"
SCRIPT
chmod +x "$LORNE_BIN"
if [ -e "$VENV_DIR/bin/tca" ] || [ -L "$VENV_DIR/bin/tca" ]; then
    rm -f "$VENV_DIR/bin/tca"
fi
ln -sf "lorne" "$VENV_DIR/bin/tca"

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

SYMLINK_LORNE="$INSTALL_DIR/lorne"
SYMLINK_TCA="$INSTALL_DIR/tca"

for s in "$SYMLINK_LORNE" "$SYMLINK_TCA"; do
    if [ -L "$s" ] || [ -f "$s" ]; then
        rm -f "$s"
    fi
done

ln -s "$LORNE_BIN" "$SYMLINK_LORNE" 2>/dev/null && ln -s "$LORNE_BIN" "$SYMLINK_TCA" 2>/dev/null || {
    cp "$LORNE_BIN" "$SYMLINK_LORNE" 2>/dev/null && cp "$LORNE_BIN" "$SYMLINK_TCA" 2>/dev/null || {
        echo -e "  ${YELLOW}⚠ Не удалось создать команды в $INSTALL_DIR${RESET}"
        echo -e "  ${DIM}Добавьте вручную: export PATH=\"$VENV_DIR/bin:\$PATH\"${RESET}"
        SYMLINK_LORNE=""
        SYMLINK_TCA=""
    }
}

# ─── Done ───────────────────────────────────────────
_install_progress "$TOTAL_STEPS" "$TOTAL_STEPS" "Готово"

ELAPSED=$(_elapsed_s)
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  ✓ Lorne установлен успешно!                ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${DIM}Время установки: ${BOLD}${ELAPSED}${RESET}${DIM} с${RESET}"
echo ""

if [ -n "$SYMLINK_LORNE" ]; then
    echo -e "  Команды ${BOLD}lorne${RESET} и ${BOLD}tca${RESET} (алиас) доступны!"
    echo ""
    echo -e "  ${CYAN}Использование:${RESET}"
    echo -e "    ${BOLD}lorne${RESET}                        — запуск в текущей папке"
    echo -e "    ${BOLD}lorne /path/to/project${RESET}       — запуск в указанном проекте"
    echo -e "    ${BOLD}lorne env=sk-or-v1-...${RESET}       — запуск с API ключом"
    echo -e "    ${DIM}(команда tca — то же самое)${RESET}"
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
    echo -e "    ${BOLD}$LORNE_BIN${RESET}"
    echo ""
fi
