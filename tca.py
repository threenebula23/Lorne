#!/usr/bin/env python3
"""
TCA — Terminal Coding Assistant.
Entry point: can be run directly or via `tca` command after installation.

Usage:
    tca                            — run in current directory
    tca /path/to/project           — run in specific directory
    tca env=<OPENROUTER_API_KEY>   — run with API key
    tca /path env=<KEY>            — combine both
"""
import os
import sys
from pathlib import Path

_TCA_ROOT = Path(__file__).resolve().parent
if str(_TCA_ROOT) not in sys.path:
    sys.path.insert(0, str(_TCA_ROOT))

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

_env_agent = _TCA_ROOT / "Agent" / ".env"
_env_root = _TCA_ROOT / ".env"
if _env_agent.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_agent)
elif _env_root.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_root)


def main():
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("\n  \033[31m✗ OPENROUTER_API_KEY не найден!\033[0m\n")
        print("  Укажите ключ одним из способов:\n")
        print("    1. Аргумент запуска:")
        print("       tca env=sk-or-v1-ваш_ключ\n")
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

    from Agent.agent import run_coding_agent_loop
    run_coding_agent_loop()


if __name__ == "__main__":
    main()
