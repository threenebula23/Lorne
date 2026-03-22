"""Animated spinner for long LLM operations."""
import sys
import time
import threading

try:
    from Interface.visualization import console, HAS_RICH
except ImportError:
    console = None
    HAS_RICH = False

_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class LiveSpinner:
    """Animated spinner that runs in a background thread during long operations."""

    def __init__(self, message: str = "Модель думает"):
        self._message = message
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_time = 0.0
        self._tui_mode = False

    def start(self):
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            self._tui_mode = True
            self._start_time = time.time()
            bridge.on_info(f"⏳ {self._message}…")
            return

        self._tui_mode = False
        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        if self._tui_mode:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        elapsed = time.time() - self._start_time
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        if HAS_RICH and console:
            console.print(f"  [dim]✓ {self._message} ({elapsed:.1f}с)[/dim]")
        else:
            print(f"  ✓ {self._message} ({elapsed:.1f}с)")

    def _spin(self):
        idx = 0
        while self._running:
            elapsed = time.time() - self._start_time
            frame = _FRAMES[idx % len(_FRAMES)]
            if HAS_RICH:
                line = (
                    f"\r  \033[36m{frame}\033[0m "
                    f"\033[1m{self._message}\033[0m "
                    f"\033[2m({elapsed:.0f}с)\033[0m  "
                )
            else:
                line = f"\r  {frame} {self._message} ({elapsed:.0f}с)  "
            sys.stdout.write(line)
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)
