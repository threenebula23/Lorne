import json
import os
import base64
from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode

load_dotenv()

YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET_COLOR = "\u001b[0m"


def resolve_abs_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


@tool
def read_file(filename: str) -> Dict[str, Any]:
    """Gets the full content of a file provided by the user."""
    full_path = resolve_abs_path(filename)
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    return {
        "file_path": str(full_path),
        "content": content,
    }


@tool
def list_files(path: str) -> Dict[str, Any]:
    """Lists the files in a directory provided by the user."""
    full_path = resolve_abs_path(path)
    all_files = []
    for item in full_path.iterdir():
        all_files.append(
            {
                "filename": item.name,
                "type": "file" if item.is_file() else "dir",
            }
        )
    return {
        "path": str(full_path),
        "files": all_files,
    }


@tool
def write_file_b64(path: str, content_b64: str) -> Dict[str, Any]:
    """
    Writes decoded base64 content to a file.
    Creates or fully overwrites the file.
    Use ONLY for initial file creation.
    """
    full_path = resolve_abs_path(path)
    content = base64.b64decode(content_b64).decode("utf-8")
    full_path.write_text(content, encoding="utf-8")
    return {
        "path": str(full_path),
        "action": "written_b64",
    }


@tool
def append_file_b64(path: str, content_b64: str) -> Dict[str, Any]:
    """
    Appends decoded base64 content to the end of an existing file.
    Safe for multi-step code generation and any content with quotes.
    """
    full_path = resolve_abs_path(path)
    content = base64.b64decode(content_b64).decode("utf-8")
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(content)
    return {
        "path": str(full_path),
        "action": "appended_b64",
    }


tools = [
    read_file,
    list_files,
    write_file_b64,
    append_file_b64,
]


SYSTEM_PROMPT = """
Ты помощник в кодинге, цель которого — помогать в решении задач кодинга.

У тебя есть доступ к набору инструментов для работы с файлами:

- read_file(filename: str) -> Dict
  Получает полное содержимое файла.

- list_files(path: str) -> Dict
  Листинг файлов в директории.

- write_file_b64(path: str, content_b64: str) -> Dict
  Создает или ПОЛНОСТЬЮ перезаписывает файл.
  content_b64 — base64-кодированное содержимое файла.
  Используй ТОЛЬКО для первоначального создания файла.

- append_file_b64(path: str, content_b64: str) -> Dict
  Дописывает base64-декодированный текст в КОНЕЦ существующего файла.
  Безопасен для многошаговой генерации и любого кода.

ВАЖНЫЕ ПРАВИЛА:
- ВСЕГДА кодируй содержимое файлов в base64 перед вызовом write_file_b64 или append_file_b64
- НИКОГДА не передавай сырой код напрямую в аргументы инструментов
- write_file_b64 можно использовать ТОЛЬКО один раз на файл
- append_file_b64 можно использовать неограниченно

Когда пользователь просит написать код или создать файл:
1) сгенерируй код
2) закодируй его в base64
3) создай файл через write_file_b64
4) если код большой — используй append_file_b64

Base64 обязателен для любого кода, содержащего кавычки, JSON, SQL, regex, bash, Python.

Используй инструменты, когда нужно взаимодействовать с файловой системой.

После выполнения инструмента сообщи пользователю результат
(например: "Файл создан", "Код дописан").

Всегда предоставляй финальный ответ пользователю после завершения задачи.
"""


llm = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    model="meta-llama/llama-3.1-8b-instruct",
)

llm_with_tools = llm.bind_tools(tools)


def call_model(state: MessagesState) -> Dict[str, List[AIMessage]]:
    messages = state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


tool_node = ToolNode(tools)


def should_continue(state: MessagesState) -> str:
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END


workflow = StateGraph(state_schema=MessagesState)

workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        END: END,
    },
)
workflow.add_edge("tools", "agent")

app = workflow.compile()


def run_coding_agent_loop():
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    while True:
        try:
            user_input = input(f"{YOU_COLOR}You:{RESET_COLOR} ")
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input.strip():
            continue

        messages.append(HumanMessage(content=user_input))
        old_len = len(messages)

        final_state = app.invoke({"messages": messages})
        messages = final_state["messages"]

        for msg in messages[old_len:]:
            if isinstance(msg, AIMessage):
                if msg.tool_calls:
                    print(
                        f"{ASSISTANT_COLOR}Assistant tool calls:{RESET_COLOR} "
                        f"{json.dumps(msg.tool_calls, indent=2)}"
                    )
                if msg.content:
                    print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {msg.content}")
            elif isinstance(msg, ToolMessage):
                print(f"{ASSISTANT_COLOR}Tool result:{RESET_COLOR} {msg.content}")


if __name__ == "__main__":
    run_coding_agent_loop()
