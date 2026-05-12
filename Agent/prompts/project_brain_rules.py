"""Project Brain + RAG rules (workspace brain, not the IDE package)."""

PROJECT_BRAIN_SYSTEM_SECTION = """
=== PROJECT BRAIN (внешняя память) ===
Каталог ``project_brain/`` — Markdown (и ``rag_manifest.json``): часть файлов **пересобирается**
сканером (``project_brain_tool`` ``refresh`` / ``scan``), часть — **только модель**.

Правила ответа:
1. По архитектуре, модулям и связям — **сначала** ``rag_search`` (brain выше кода), при необходимости ``read_file`` по ``project_brain/*.md``, затем исходники.
2. Не выдумывай модули и потоки без опоры на brain или проверенный код.
3. **Запись моделью (Markdown в brain):**
   - Общий случай — ``action=write_brain``, ``brain_rel_path`` (относительно ``project_brain/``, только ``.md``) и ``content``. Режим ``write_mode=append`` (по умолчанию) добавляет секцию с датой; ``replace`` — перезаписывает файл полем ``content`` (для нового файла при ``append`` подставляется короткий заголовок).
   - Разрешённые пути: ``agent/…/*.md`` (подкаталог ``agent/`` не пересобирается refresh), корень brain: ``*_notes.md`` / ``*_supplement.md``, либо устаревший совместимый ``action=write_architecture`` → только ``agent_architecture.md``.
   - **Не писать** в корневые ``overview.md``, ``architecture.md``, ``glossary.md``, ``tools.md``, ``flows.md``, ``rag_manifest.json`` и в деревья ``modules/``, ``machine/``, ``services/``, ``agents/`` — их даёт сканер; дополняй смысл в ``agent/overview_notes.md``, ``agent/glossary_supplement.md`` и т.п.
4. Пересборка сканом — ``refresh`` / ``reindex`` / ``scan``, когда структура репозитория сильно изменилась.
5. После финального ответа в графе LangGraph brain **переиндексируется в RAG с диска текущего workspace** (корень проекта в UI, не каталог установки IDE): новые/изменённые ``project_brain/*.md`` попадают в поиск без ручного ``reindex``. В режиме **Brainer** после каждого раунда с тулами RAG тоже обновляется с диска; после завершения хода дополнительно выполняется полный **refresh** сканера (пересборка обзорных файлов brain из кода), чтобы ``rag_search`` видел актуальную структуру репозитория.

Формат ответа про модуль (если уместно):
## Module / Purpose / Responsibilities / Public API / Dependencies / Side effects / Used by / Risks
(заполняй только поля, подтверждённые brain или файлами).
"""
