#!/bin/bash
# ═══════════════════════════════════════════════════════
#  Lorne v0.98 — деинсталляция
# ═══════════════════════════════════════════════════════
#
#  Этот скрипт:
#  1. Удаляет симлинки/копии команд ``lorne`` и ``tca`` из PATH
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

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
U0=$(date +%s)

_elapsed_s() {
    echo $(($(date +%s) - U0))
}

_tca_u_progress() {
    local step="$1"
    local total="$2"
    local msg="$3"
    local width=14
    local filled=$((step * width / total))
    [ "$filled" -gt "$width" ] && filled=$width
    local empty=$((width - filled))
    local bar_f=""
    local i
    for ((i = 0; i < filled; i++)); do bar_f+="█"; done
    local bar_e=""
    for ((i = 0; i < empty; i++)); do bar_e+="░"; done
    printf "  [%b%s%b%s] %d/%d  %ds  %s\n" \
        "$CYAN" "$bar_f" "$DIM" "$bar_e" "$step" "$total" "$(_elapsed_s)" "$msg"
}

TOTAL=5

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║  Lorne — деинсталляция                      ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""

_tca_u_progress 1 "$TOTAL" "Удаление команд lorne / tca из известных каталогов PATH…"

for dir in "$HOME/.local/bin" "$HOME/bin" "/usr/local/bin"; do
    for name in lorne tca; do
        SYMLINK="$dir/$name"
        if [ -L "$SYMLINK" ] || [ -f "$SYMLINK" ]; then
            rm -f "$SYMLINK" 2>/dev/null \
                && echo -e "  ${GREEN}✓${RESET} Удалена команда: $SYMLINK" \
                || echo -e "  ${YELLOW}⚠ Не удалось удалить $SYMLINK (попробуйте sudo rm $SYMLINK)${RESET}"
        fi
    done
done

_tca_u_progress 2 "$TOTAL" "Удаление виртуального окружения .venv…"

VENV_DIR="$REPO_ROOT/.venv"

if [ -d "$VENV_DIR" ]; then
    rm -f "$VENV_DIR/bin/lorne" "$VENV_DIR/bin/tca" 2>/dev/null || true
    rm -rf "$VENV_DIR"
    echo -e "  ${GREEN}✓${RESET} Виртуальное окружение удалено"
else
    echo -e "  ${DIM}Виртуальное окружение не найдено${RESET}"
fi

_tca_u_progress 3 "$TOTAL" "Опционально: данные сессий и версий…"

echo ""
echo -ne "  Удалить данные сессий, версий и конфиг? [y/N] > "
read -r answer

if [[ "$answer" =~ ^[yYдД] ]]; then
    rm -rf "$REPO_ROOT/.lorne" "$REPO_ROOT/.tca" 2>/dev/null || true
    rm -f "$REPO_ROOT/.tca_checkpoints.sqlite" "$REPO_ROOT/.tca_versions.sqlite" 2>/dev/null || true
    rm -f "$REPO_ROOT/.tca_plan.json" 2>/dev/null || true
    rm -f "$HOME/.lorne_config.json" "$HOME/.tca_config.json" 2>/dev/null || true
    rm -rf "$HOME/.lorne_custom_tools" "$HOME/.tca_custom_tools" 2>/dev/null || true
    rm -f "$HOME/.lorne_recent_projects.json" "$HOME/.tca_recent_projects.json" 2>/dev/null || true
    echo -e "  ${GREEN}✓${RESET} Данные удалены"
else
    echo -e "  ${DIM}Данные сохранены${RESET}"
fi

_tca_u_progress 4 "$TOTAL" "Очистка __pycache__…"

find "$REPO_ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo -e "  ${GREEN}✓${RESET} Кэш Python очищен"

_tca_u_progress "$TOTAL" "$TOTAL" "Готово"

ELAPSED=$(_elapsed_s)
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  ✓ Lorne деинсталлирован                    ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${DIM}Время выполнения: ${BOLD}${ELAPSED}${RESET}${DIM} с${RESET}"
echo ""
echo -e "  ${DIM}Исходный код остался в: $REPO_ROOT${RESET}"
echo -e "  ${DIM}Для полного удаления: rm -rf \"$REPO_ROOT\"${RESET}"
echo ""
