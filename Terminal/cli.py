"""
Точка входа: запуск агента в терминале.
Запуск из корня проекта: python -m Terminal
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

if _env_key:
    os.environ["OPENROUTER_API_KEY"] = _env_key

_env_agent = _PROJECT_ROOT / "Agent" / ".env"
_env_root = _PROJECT_ROOT / ".env"
if _env_agent.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_agent)
elif _env_root.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_root)

# Agent expects cwd to be the project root
os.chdir(_PROJECT_ROOT)


def main():
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

    from Agent.agent import run_coding_agent_loop
    run_coding_agent_loop()


if __name__ == "__main__":
    main()
    sys.exit(0)
