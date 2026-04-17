"""
Точка входа: тот же выбор режима, что и у `tca.py` (TUI по умолчанию, classic по флагу).

Использование:
    python -m Terminal                       — TUI в текущей директории (как `tca`)
    python -m Terminal /path/to/project      — проект
    python -m Terminal env=<API_KEY>         — ключ OpenRouter (сохраняется в Agent/.env)
    python -m Terminal /path env=<KEY>       — оба аргумента
    python -m Terminal --classic             — только чат в терминале (Rich)
    python -m Terminal --tui                 — явно TUI
"""
import os
import sys
from pathlib import Path

_CLI_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _CLI_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_env_key = ""
_filtered_argv = [sys.argv[0]]
for _arg in sys.argv[1:]:
    if _arg.startswith("env="):
        _env_key = _arg[4:]
    else:
        _filtered_argv.append(_arg)
sys.argv = _filtered_argv

_env_agent = _PROJECT_ROOT / "Agent" / ".env"
if _env_key:
    os.environ["OPENROUTER_API_KEY"] = _env_key
    _env_agent.parent.mkdir(parents=True, exist_ok=True)
    _env_agent.write_text(f"OPENROUTER_API_KEY={_env_key}\n", encoding="utf-8")
    print("\n  Ключ сохранён в Agent/.env — в следующий раз достаточно: python -m Terminal\n")

_env_root = _PROJECT_ROOT / ".env"
if _env_agent.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_agent)
elif _env_root.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_root)


def main() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("\n  \033[31m✗ OPENROUTER_API_KEY не найден!\033[0m\n")
        print("  Укажите ключ одним из способов:\n")
        print("    1. Аргумент запуска:")
        print("       python -m Terminal env=sk-or-v1-ваш_ключ\n")
        print("    2. Файл Agent/.env:")
        print("       echo 'OPENROUTER_API_KEY=sk-or-v1-ваш_ключ' > Agent/.env\n")
        print("    3. Переменная окружения:")
        print("       export OPENROUTER_API_KEY=sk-or-v1-ваш_ключ\n")
        sys.exit(1)

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        target = Path(sys.argv[1]).resolve()
        if target.is_dir():
            os.chdir(target)
        else:
            print(f"Директория не найдена: {target}")
            sys.exit(1)

    mode = os.getenv("TCA_MODE", "tui").lower()

    if "--classic" in sys.argv:
        sys.argv.remove("--classic")
        mode = "classic"
    if "--tui" in sys.argv:
        sys.argv.remove("--tui")
        mode = "tui"

    if mode == "classic":
        from Agent.agent import run_coding_agent_loop
        run_coding_agent_loop()
    else:
        from Agent.agent import run_tui_mode
        run_tui_mode()


if __name__ == "__main__":
    main()
    sys.exit(0)
