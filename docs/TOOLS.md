# TCA Tools Reference

Reference for tools available to the TCA agent. The **exact count** depends on build: base tools from `Agent/tool_registry.py`, optional Git/Context7/browser bundles, user **custom tools** (`/custom`), and **agent mode** may add Playwright browser tools — see [ARCHITECTURE.md](./ARCHITECTURE.md) § `tool_registry`.

## File Operations

### `read_file(filename, encoding, offset, limit)`
Read file contents with optional pagination for large files.
- `filename` (str): Path to file (relative or absolute)
- `encoding` (str, default="utf-8"): File encoding
- `offset` (int, default=0): Start line (0-based)
- `limit` (int, default=0): Number of lines to read (0 = entire file)

### `list_files(path, recursive, pattern)`
List files in a directory.
- `path` (str): Directory path
- `recursive` (bool): Traverse subdirectories
- `pattern` (str): Glob pattern (e.g. `*.py`)

### `search_in_files(directory, query, file_pattern, max_files)`
Full-text search across files.
- `directory` (str): Root directory
- `query` (str): Text to search
- `file_pattern` (str, default="*.py"): Glob filter
- `max_files` (int, default=50): Max files to scan

### `edit_file(path, old_str, new_str)`
Replace first occurrence of `old_str` with `new_str`. If `old_str` is empty, creates/overwrites the file. Automatically creates a version snapshot before editing.

### `write_file(path, content)`
Create or overwrite a file. Auto-creates parent directories. Creates a snapshot and Git auto-commit.

### `create_code_file(filepath, language, code)`
Create a code file with language-appropriate extension.

### `append_code_snippet(filepath, snippet, language)`
Append code to the end of a file.

### `get_file_line_count(path)`
Return the number of lines in a file.

## Terminal

### `run_command(command, cwd, timeout_seconds)`
Execute a shell command with user confirmation.
- `command` (str): Command to execute
- `cwd` (str): Working directory (empty = project root)
- `timeout_seconds` (int, default=30): Timeout

Safety: blocks dangerous commands (`rm -rf`, etc.), deduplicates rapid repeated runs.

### `code_interpreter(code, timeout)`
Execute Python code in a subprocess. Useful for calculations and algorithm verification.

## Planning

### `save_plan(title, steps)`
Save a task plan. Steps is a list of strings.

### `load_plan()`
Load the current plan from `.tca_plan.json`.

### `update_plan(step_index, status, note)`
Update step status: `pending` | `in_progress` | `completed` | `blocked`.

### `clear_plan()`
Delete the current plan.

## Git Integration

### `git_log(path, limit)`
Show commit history.
- `path` (str): Filter by file (empty = all commits)
- `limit` (int, default=15): Max commits

### `git_diff(commit)`
Show diff.
- `commit` (str): Commit hash (empty = current unstaged changes)

### `git_rollback_file(path, commit)`
Restore a file from a specific commit.

### `git_status()`
Get current Git status: branch, changed/staged/untracked files.

## Versioning (SQLite)

### `list_file_versions(path, limit)`
List version snapshots for a file (most recent first).

### `rollback_file(path, version_id)`
Rollback a file to a specific version snapshot or the latest one.

## Web & Documentation

### `web_search(query, max_results)`
Search the web via DuckDuckGo.

### `web_fetch(url, max_length)`
Fetch a web page as text.

### `get_documentation(query, library)`
Search documentation for libraries and APIs.

## RAG Search

### `rag_search(query, top_k)`
Search indexed project documents.
- Uses semantic chunking (800 chars with 200 char overlap)
- Python-aware: breaks at function/class boundaries
- Word-level scoring with phrase bonus
- Returns chunks with file path, line numbers, and relevance score

## Other

### `ask_user(question)`
Ask the user a question via terminal input.

### `create_pdf(filepath, title, body)`
Create a PDF document (falls back to .txt if ReportLab is not installed).
