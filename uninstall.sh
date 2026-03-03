#!/bin/bash
# ═══════════════════════════════════════════════════════
#  TCA — Terminal Coding Assistant — Деинсталляция
# ═══════════════════════════════════════════════════════
#
#  Этот скрипт:
#  1. Удаляет симлинк/копию команды `tca` из PATH
#  2. Удаляет виртуальное окружение (.venv)
#  3. Опционально удаляет данные сессий, версий и конфиг
#
#  Использование:
#    chmod +x uninstall.sh && ./uninstall.sh
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
echo -e "${BOLD}║  TCA — Деинсталляция                        ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ─── Remove tca command from PATH directories ───────
for dir in "$HOME/.local/bin" "$HOME/bin" "/usr/local/bin"; do
    SYMLINK="$dir/tca"
    if [ -L "$SYMLINK" ] || [ -f "$SYMLINK" ]; then
        rm -f "$SYMLINK" 2>/dev/null \
            && echo -e "  ${GREEN}✓${RESET} Удалена команда: $SYMLINK" \
            || echo -e "  ${YELLOW}⚠ Не удалось удалить $SYMLINK (попробуйте sudo rm $SYMLINK)${RESET}"
    fi
done

# ─── Remove virtual environment ─────────────────────
VENV_DIR="$TCA_DIR/.venv"

if [ -d "$VENV_DIR" ]; then
    echo -e "  ${CYAN}⏳${RESET} Удаляю виртуальное окружение..."
    rm -rf "$VENV_DIR"
    echo -e "  ${GREEN}✓${RESET} Виртуальное окружение удалено"
else
    echo -e "  ${DIM}Виртуальное окружение не найдено${RESET}"
fi

# ─── Remove TCA data files (optional) ───────────────
echo ""
echo -ne "  Удалить данные сессий, версий и конфиг? [y/N] > "
read -r answer

if [[ "$answer" =~ ^[yYдД] ]]; then
    rm -f "$TCA_DIR/.tca_checkpoints.sqlite" 2>/dev/null
    rm -f "$TCA_DIR/.tca_versions.sqlite" 2>/dev/null
    rm -f "$TCA_DIR/.tca_plan.json" 2>/dev/null
    rm -f "$HOME/.tca_config.json" 2>/dev/null
    echo -e "  ${GREEN}✓${RESET} Данные удалены"
else
    echo -e "  ${DIM}Данные сохранены${RESET}"
fi

# ─── Remove __pycache__ ─────────────────────────────
find "$TCA_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo -e "  ${GREEN}✓${RESET} Кэш Python очищен"

# ─── Done ────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  ✓ TCA деинсталлирован                      ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${DIM}Исходный код остался в: $TCA_DIR${RESET}"
echo -e "  ${DIM}Для полного удаления: rm -rf \"$TCA_DIR\"${RESET}"
echo ""
