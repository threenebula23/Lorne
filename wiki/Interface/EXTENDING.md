# Руководство: Как расширять интерфейс (EXTENDING)

Индекс документации: [wiki/README.md](../README.md) · настройки UI: [SETTINGS.md](SETTINGS.md) · тулы: [../developer/ADDING_TOOLS.md](../developer/ADDING_TOOLS.md).

Если вы хотите добавить новую панель, кнопку или функционал в TCA, следуйте этой инструкции.

## 1. Добавление новой панели (Виджета)
1. Создайте файл в `Interface/panels/` (например, `my_panel.py`).
2. Наследуйтесь от `Vertical` или `Static`:
```python
from textual.app import ComposeResult
from textual.widgets import Static, Label

class MyNewPanel(Static):
    def compose(self) -> ComposeResult:
        yield Label("Это моя новая панель!")
```
3. Зарегистрируйте её в `Interface/tui_app.py`:
   - Импортируйте класс.
   - Добавьте в метод `compose()` внутри нужного контейнера.

## 2. Связь через события (Messages)
В Textual лучше не вызывать методы панелей напрямую из главного приложения. Используйте систему событий:
1. В панели: `self.post_message(MyEvent(data))`
2. В `LorneApp`:
```python
@on(MyEvent)
def handle_my_event(self, event: MyEvent):
    # Логика обработки
```

## 3. Добавление команд в Мост
Если вам нужно, чтобы агент мог управлять вашей новой панелью:
1. Откройте `Interface/tui_bridge.py`.
2. Добавьте метод:
```python
def update_my_data(self, value):
    self._call(self.app.my_panel.update_info, value)
```
3. Теперь в коде любого инструмента (`Agent/tools/`) вы можете вызвать:
```python
bridge = get_bridge()
if bridge:
    bridge.update_my_data("Новый текст")
```

## 4. Создание диалоговых окон (Screens)
Для всплывающих окон (как запрос ввода или подтверждение):
1. Наследуйтесь от `ModalScreen`.
2. Используйте `app.push_screen(MyScreen())` для отображения.
3. Окно перекрывает весь интерфейс и блокирует взаимодействие с фоном.

---

## Советы для разработчика
- Используйте команду `textual console` в отдельном терминале и запускайте TCA с флагом `--dev`, чтобы видеть лог ошибок интерфейса и живую перезагрузку стилей.
- Если панель должна быть скрываемой, используйте свойство `display = False` (а не `visible = False`), чтобы она не забирала место в макете.
