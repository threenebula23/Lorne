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

from system_promt import SYSTEM_PROMPT

load_dotenv()

YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET_COLOR = "\u001b[0m"

def resolve_abs_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path

def analyze_project_structure(root_path: Path = None) -> str:
    """Анализирует структуру проекта и создает контекстное описание"""
    if root_path is None:
        root_path = Path.cwd()
    
    project_context = []
    project_context.append(f"=== СТРУКТУРА ПРОЕКТА: {root_path.name} ===\n")
    
    def scan_directory(directory: Path, prefix: str = "", is_last: bool = True):
        if directory.name.startswith('.') or directory.name == '__pycache__':
            return
        
        # Добавляем текущую директорию
        connector = "└── " if is_last else "├── "
        project_context.append(f"{prefix}{connector}{directory.name}/")
        
        # Получаем все элементы в директории
        try:
            items = list(directory.iterdir())
        except PermissionError:
            project_context.append(f"{prefix}{'    ' if is_last else '│   '}[Нет доступа]")
            return
        
        # Сортируем: сначала директории, потом файлы
        dirs = [item for item in items if item.is_dir()]
        files = [item for item in items if item.is_file()]
        
        dirs.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())
        
        all_items = dirs + files
        
        for i, item in enumerate(all_items):
            is_last_item = (i == len(all_items) - 1)
            extension = "    " if is_last else "│   "
            
            if item.is_dir():
                scan_directory(item, prefix + extension, is_last_item)
            else:
                # Для файлов показываем расширение и размер
                file_size = item.stat().st_size if item.exists() else 0
                size_str = f" ({file_size} bytes)" if file_size > 0 else ""
                file_connector = "└── " if is_last_item else "├── "
                project_context.append(f"{prefix}{extension}{file_connector}{item.name}{size_str}")
    
    # Начинаем сканирование с корневой директории
    scan_directory(root_path)
    
    # Добавляем информацию о типах файлов
    file_types = {}
    total_files = 0
    
    for file_path in root_path.rglob('*'):
        if file_path.is_file() and not str(file_path).startswith('.') and '__pycache__' not in str(file_path):
            suffix = file_path.suffix or 'no_extension'
            if suffix not in file_types:
                file_types[suffix] = 0
            file_types[suffix] += 1
            total_files += 1
    
    project_context.append(f"\n=== СТАТИСТИКА ПРОЕКТА ===")
    project_context.append(f"Всего файлов: {total_files}")
    project_context.append("Типы файлов:")
    for ext, count in sorted(file_types.items(), key=lambda x: x[1], reverse=True):
        project_context.append(f"  {ext}: {count}")
    
    # Добавляем информацию о ключевых файлах
    project_context.append(f"\n=== КЛЮЧЕВЫЕ ФАЙЛЫ ПРОЕКТА ===")
    key_files = []
    for file_path in root_path.rglob('*'):
        if file_path.is_file() and file_path.suffix == '.py':
            key_files.append(file_path)
    
    # Сортируем по размеру (сначала самые большие)
    key_files.sort(key=lambda x: x.stat().st_size, reverse=True)
    
    for i, file_path in enumerate(key_files[:5]):  # Показываем 5 самых больших файлов
        rel_path = file_path.relative_to(root_path)
        size = file_path.stat().st_size
        project_context.append(f"{i+1}. {rel_path} ({size} bytes)")
    
    return '\n'.join(project_context)

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



llm = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    model="meta-llama/llama-3.1-8b-instruct"
)

def call_model(state: MessagesState) -> Dict[str, List[AIMessage]]:
    messages = state["messages"]
    raw_response = llm.invoke(messages)
    
    # Clean the content to remove invalid Unicode characters BEFORE processing
    content = raw_response.content
    if isinstance(content, str):
        # Remove surrogate characters that cause encoding issues
        content = content.encode('utf-8', 'ignore').decode('utf-8', 'ignore')
    
    # Create a new AIMessage with the cleaned content
    cleaned_response = AIMessage(content=content, tool_calls=raw_response.tool_calls)
    
    fixed_content = repair_json(content)
    if fixed_content.strip():
        try:
            parsed_tools = json.loads(fixed_content)
            if not isinstance(parsed_tools, list):
                parsed_tools = [parsed_tools]
            tool_calls = []
            for tool in parsed_tools:
                if isinstance(tool, dict) and "function" in tool:
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
    # Автоматически анализируем структуру проекта при запуске
    print(f"{ASSISTANT_COLOR}Анализирую структуру проекта...{RESET_COLOR}")
    project_structure = analyze_project_structure()
    
    # Создаем улучшенный системный промпт с информацией о проекте
    enhanced_system_prompt = f"""{SYSTEM_PROMPT}

=== КОНТЕКСТ ПРОЕКТА ===
{project_structure}

=== ИНСТРУКЦИИ ===
Теперь ты знаешь структуру этого проекта. Используй эту информацию, чтобы:
1. Лучше понимать, о каких файлах идет речь
2. Предлагать более релевантные решения
3. Знать, где находятся ключевые файлы
4. Понимать архитектуру проекта

Помни эту информацию на протяжении всей сессии.
"""
    
    messages = [SystemMessage(content=enhanced_system_prompt)]
    
    print(f"{ASSISTANT_COLOR}Проект проанализирован! Могу помочь с любыми задачами по кодингу.{RESET_COLOR}")
    print(f"{ASSISTANT_COLOR}Доступные команды:{RESET_COLOR}")
    print("  - Просто опиши задачу, которую нужно решить")
    print("  - Спроси о структуре проекта")
    print("  - Попроси показать содержимое конкретного файла")
    print("  - Попроси создать новый файл")
    print("  - Попроси внести изменения в существующий файл")
    print()
    
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