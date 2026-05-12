# Добавление и обновление инструмента (tool)

Чеклист по репозиторию. Обновление существующего тула — те же шаги, что относятся к изменению.

## 1. Реализация

- Новый модуль или функция в **`Agent/tools/`** с декоратором **`@tool`** (LangChain).
- Экспорт в **`Agent/tools/__init__.py`**, если принято для импорта из пакета.

## 2. Реестр

- **`Agent/tool_registry.py`**: добавить объект в **`_base_tools`** или в условный список (браузер, git).
- Для Ask-режима: при необходимости добавить имя в **`_ASK_EXCLUDED_TOOL_NAMES`** или оставить доступным.
- Для переключателя Custom tools: при необходимости **`_CUSTOM_TOOL_NAMES`**.

## 3. Схемы и coerce

- **`Agent/tool_schemas.py`**: класс `*Args(BaseModel)`, зарегистрировать в **`TOOL_ARG_MODELS`**.
- При типичных ошибках модели с аргументами — расширить **`_coerce_common_arg_mistakes`**.

## 4. Компактный диспетчер

- Если тул объединяется с другими под одним именем — ветка в **`Agent/tools/compact_tools.py`**.
- Обновить **[COMPACT_TOOLS.md](../COMPACT_TOOLS.md)** и секцию в **[tool/REFERENCE.md](../tool/REFERENCE.md)**.

## 5. Поведение модели

- При необходимости: **`Agent/system_promt.py`** или **`Agent/prompts/`** (режимные дополнения).

## 6. UI

- Карточка результата: **`Interface/panels/tool_card.py`** (ветка по `tool_name`).

## 7. Тесты

- Добавить smoke в **`tests/`** по аналогии с `test_project_brain_tool.py` или существующими тул-тестами.

## 8. Документация

- Секция в **[wiki/tool/REFERENCE.md](../tool/REFERENCE.md)** (или отдельная страница, если тул очень большой).
- Строка в **[wiki/TOOLS.md](../TOOLS.md)**.
- Обновить **[wiki/README.md](../README.md)** при новом разделе.

## 9. PR

- Код + документация wiki в **одном** PR (или сразу следующий коммит в ту же ветку), см. [CONTRIBUTING.md](../../CONTRIBUTING.md).
