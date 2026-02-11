import json
import os
from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List
from json_repair import repair_json

from langchain_core.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
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
    print(full_path)
    with open(str(full_path), "r") as f:
        content = f.read()
    return {
        "file_path": str(full_path),
        "content": content
    }

@tool
def list_files(path: str) -> Dict[str, Any]:
    """Lists the files in a directory provided by the user."""
    full_path = resolve_abs_path(path)
    all_files = []
    for item in full_path.iterdir():
        all_files.append({
            "filename": item.name,
            "type": "file" if item.is_file() else "dir"
        })
    return {
        "path": str(full_path),
        "files": all_files
    }

@tool
def edit_file(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """Replaces first occurrence of old_str with new_str in file. If old_str is empty, create/overwrite file with new_str."""
    full_path = resolve_abs_path(path)
    if old_str == "":
        full_path.write_text(new_str, encoding="utf-8")
        return {
            "path": str(full_path),
            "action": "created_file"
        }
    original = full_path.read_text(encoding="utf-8")
    if original.find(old_str) == -1:
        return {
            "path": str(full_path),
            "action": "old_str not found"
        }
    edited = original.replace(old_str, new_str, 1)
    full_path.write_text(edited, encoding="utf-8")
    return {
        "path": str(full_path),
        "action": "edited"
    }

tools = [read_file, list_files, edit_file]

SYSTEM_PROMPT = """
Ты помощник в кодинге, цель которого - помогать в решении задач кодинга.

У тебя есть доступ к набору инструментов для работы с файлами:
- read_file(filename: str) -> Dict: Получает полное содержимое файла.
- list_files(path: str) -> Dict: Листинг файлов в директории.
- edit_file(path: str, old_str: str, new_str: str) -> Dict: Заменяет первое вхождение old_str на new_str в файле. Если old_str пустой, создает или перезаписывает файл содержимым new_str.

Если пользователь просит написать код или создать файл, сгенерируй содержимое и используй edit_file с old_str="" для создания файла.

При генерации аргументов вызова инструмента убедитесь, что все строки являются допустимыми JSON-данными, экранируя внутренние двойные кавычки символом \". Например, используйте \"print(\\\"Hello, World!\\\")\" вместо \"print(\"Hello, World!\")\". Поместите ПОЛНОЕ содержимое в new_str без дополнительного текста.

Используй инструменты когда нужно взаимодействовать с файловой системой.

Когда тебе нужно использовать инструмент, используй вызовы инструментов в формате, предоставленном моделью.

После получения результатов инструмента, проанализируй их и сообщи пользователю о результате (например, "Файл создан").

Если инструмент не требуется, отвечай обычным образом.

Всегда предоставляй финальный ответ пользователю после завершения задачи.

To call tools, output ONLY a JSON array of objects like:
[{"id": "call_id", "type": "function", "function": {"name": "tool_name", "arguments": {"arg": "value"}}}]
For multiple tools, use an array. Escape inner quotes in arguments with \".
For normal responses, output plain text without JSON.
"""

llm = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    model="meta-llama/llama-3.1-8b-instruct"
)

def call_model(state: MessagesState) -> Dict[str, List[AIMessage]]:
    messages = state["messages"]
    raw_response = llm.invoke(messages)
    fixed_content = repair_json(raw_response.content)
    if fixed_content.strip():
        try:
            parsed_tools = json.loads(fixed_content)
            if not isinstance(parsed_tools, list):
                parsed_tools = [parsed_tools]
            tool_calls = []
            for tool in parsed_tools:
                if "function" in tool:
                    func = tool["function"]
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    elif not isinstance(args, dict):
                        args = {}
                    tool_calls.append({
                        "name": func["name"],
                        "args": args,
                        "id": str(tool.get("id", "call_" + str(hash(func["name"])))),
                        "type": "tool_call"
                    })
            response = AIMessage(content="", tool_calls=tool_calls)
        except json.JSONDecodeError:
            response = AIMessage(content=fixed_content)
    else:
        response = AIMessage(content="")
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
        # Run the graph
        final_state = app.invoke({"messages": messages})
        messages = final_state["messages"]
        # Print the new messages from this invocation
        for msg in messages[old_len:]:
            if isinstance(msg, AIMessage):
                if msg.tool_calls:
                    print(f"{ASSISTANT_COLOR}Assistant tool calls:{RESET_COLOR} {json.dumps(msg.tool_calls, indent=2)}")
                if msg.content:
                    print(f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {msg.content}")
            elif isinstance(msg, ToolMessage):
                print(f"{ASSISTANT_COLOR}Tool result:{RESET_COLOR} {msg.content}")

if __name__ == "__main__":
    run_coding_agent_loop()