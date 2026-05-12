# TCA / Lorne — документация (wiki)

Единый индекс. Версия продукта см. корневой [README.md](../README.md).

## Быстрый старт

- [Установка и первый запуск](tutorials/quickstart.md)

## Пользователь

- [TUI: экраны и потоки](TUI.md)
- [Режимы чата](MODES/README.md) — Agent, Ask, Creator, Research, Deep, Brainer
- [Фоновые задачи и Deep (обзор)](BACKGROUND_AND_DEEP.md)

## Архитектура и данные

- [Архитектура репозитория](ARCHITECTURE.md)
- [Project Brain и RAG](PROJECT_BRAIN.md)

## Инструменты (tools)

- [Сводная таблица тулов](TOOLS.md)
- [Компактные мульти-тулы](COMPACT_TOOLS.md)
- [Детальный справочник по тулу (секции)](tool/REFERENCE.md)

## Интерфейс (разработка UI)

- [Обзор компонентов TUI](Interface/OVERVIEW.md)
- [Настройки: `ui_settings.json` и prefs](Interface/SETTINGS.md)
- [Стили и TCSS](Interface/STYLING.md)
- [Расширение панелей](Interface/EXTENDING.md)

## Разработка агента и тулов

- [Расширение TCA (обзор)](EXTENDING.md)
- [Контракты расширений](developer/extension-contracts.md)
- [Добавление и обновление тула](developer/ADDING_TOOLS.md)
- [Участие в проекте (PR, тесты)](../CONTRIBUTING.md)

## Прочее

- [Документация в `docs/`](../docs/README.md) — указатель в wiki

Правило: изменения в поведении тула, режима или prefs → обновить соответствующую страницу здесь в том же изменении, что и код.
