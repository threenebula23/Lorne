# Extending TCA

Guide for adding custom tools, models, and configuring Creator Mode.

**Карта модулей и архитектура репозитория:** [ARCHITECTURE.md](./ARCHITECTURE.md)

## Adding a Custom Tool (via CLI)

The fastest way to add a tool:

```bash
tca
❯ /custom add my_tool
```

This creates a template in `~/.tca_custom_tools/my_tool.py`. Edit it and reload:

```bash
❯ /custom reload
```

## Adding a Custom Tool (via Code)

### 1. Create the tool file

Create `Agent/tools/my_tool.py`:

```python
from typing import Dict, Any
from langchain_core.tools import tool

@tool
def my_awesome_tool(query: str, limit: int = 10) -> Dict[str, Any]:
    """Description visible to the agent. Be specific about parameters and return value."""
    # Your logic here
    results = do_something(query, limit)
    return {"ok": True, "results": results, "count": len(results)}
```

### 2. Export from `__init__.py`

Add to `Agent/tools/__init__.py`:

```python
from .my_tool import my_awesome_tool
```

### 3. Register in tool_registry

Add to `_base_tools` list in `Agent/tool_registry.py`:

```python
_base_tools: List[Any] = [
    # ... existing tools ...
    my_awesome_tool,
]
```

### 4. (Optional) Add to system prompt

Add a description in `Agent/system_promt.py` so the agent knows when to use it:

```
### My Category
- my_awesome_tool(query, limit) → Description of what it does.
```

### 5. (Optional) Add custom display

Add a handler in `Interface/visualization.py` `display_tool_result()`:

```python
if name == "my_awesome_tool" and isinstance(result, dict):
    _display_my_tool_result(result)
    return
```

## Adding a New Model

Add to `AVAILABLE_MODELS` in `Agent/llm_provider.py`:

```python
{"id": "provider/model-name", "name": "Display Name", "ctx": 128_000, "tier": "free"},
```

Tiers: `free`, `cheap`, `paid`, `pro`.

If the provider supports `parallel_tool_calls`, add to `_PROVIDER_CAPS`:

```python
"provider/": {"parallel_tool_calls": True, "native_tools": True},
```

## Configuring Creator Mode

Creator Mode runs multiple agents in parallel for complex tasks.

### Setup

1. Start a local model server (Ollama, LM Studio, vLLM):

```bash
ollama serve
ollama pull qwen3.5:27b
```

2. Configure TCA:

```bash
tca
❯ /creator set local_base_url http://localhost:11434/v1
❯ /creator set local_model qwen3.5:27b
❯ /creator set max_workers 4
```

3. Enable and use:

```bash
❯ /creator on
❯ Create a REST API with auth, tests, and documentation
```

### How it works

1. **Planning**: The task is split into subtasks via LLM planner
2. **Routing**: Each subtask is classified as `simple` or `complex`
   - Simple tasks → local model (fast, free)
   - Complex tasks → heavy model (OpenRouter)
3. **Execution**: Subtasks run in parallel via `ThreadPoolExecutor`
4. **Display**: Live progress visualization with worker status

### Configuration options

| Parameter | Description | Default |
|---|---|---|
| `local_base_url` | URL of local OpenAI-compatible API | `http://192.168.1.20:3000/api` |
| `local_model` | Model name on local server | `qwen3.5:27b` |
| `max_workers` | Max parallel agents | `4` |

## Architecture Overview

```
User Input
    │
    ▼
CommandRouter ──── /slash commands ──── direct response
    │
    │ (regular input)
    ▼
Planner ──── build_plan() ──── save_plan()
    │
    ▼
AgentGraph.stream()
    │
    ├── call_model (LLM invocation with retry)
    │   └── sanitize_messages → llm_with_tools.invoke()
    │
    ├── execute_tools (parallel read-only, sequential write)
    │   ├── read_file, list_files, search_in_files (parallel)
    │   └── edit_file, write_file, run_command (sequential)
    │
    └── should_continue → END if no tool_calls
```
