"""Image Viewer panel — display images in the terminal (fallback to metadata if no renderer)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Center, Middle, VerticalScroll
from textual.widgets import Label, Static
from rich.panel import Panel
from rich.text import Text

class ImageViewerPanel(Vertical):
    """Panel for displaying images or their metadata."""

    DEFAULT_CSS = """
    ImageViewerPanel {
        height: 1fr;
        background: #0D0D15;
    }
    #image-container-scroll {
        align: center top;
        height: 1fr;
    }
    #image-info {
        margin: 1 2;
        color: #6B7280;
        text-align: center;
    }
    #image-placeholder {
        margin: 1;
        padding: 0;
        background: #0D0D15;
    }
    """

    BINDINGS = [
        Binding("plus,=", "zoom_in", "Zoom In (+)", show=True),
        Binding("minus,-", "zoom_out", "Zoom Out (-)", show=True),
        Binding("0", "reset_zoom", "Reset Zoom (100%)", show=True),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_path: Optional[Path] = None
        self._zoom: float = 1.0

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="image-container-scroll"):
            yield Static("Select an image to view", id="image-placeholder")
            yield Label("", id="image-info")

    def show_image(self, path: Path) -> None:
        """Load and display image info."""
        self._current_path = path
        try:
            from PIL import Image as PILImage
            from rich.text import Text
            from rich.style import Style
            from rich.panel import Panel
            
            # Check if we can open it
            with PILImage.open(path) as img:
                orig_w, orig_h = img.size
                
                # Base size constraints for 100% zoom
                base_w = 60
                base_h = 30
                
                # Resizing logic:
                # We want to fit within (base_w * zoom) horizontal characters.
                # Terminal cells are typically 2x taller than wide (aspect ~0.5).
                # To compensate for stretching, we use an adjustment factor (0.85).
                
                target_w = int(base_w * self._zoom)
                target_h = int(base_h * self._zoom)
                
                ratio = min(target_w / orig_w, target_h / orig_h)
                new_w = max(1, int(orig_w * ratio))
                # Adjustment factor (0.85) to fix terminal cell stretching
                new_h = max(1, int(orig_h * ratio * 0.85))
                
                # Scale image to (new_w) x (new_h * 2) pixels
                # Since each char is 2 vertical pixels (half-blocks)
                img = img.resize((new_w, new_h * 2), PILImage.Resampling.LANCZOS)
                
                if img.mode != "RGB":
                    img = img.convert("RGB")
                
                pixels = img.load()
                w, h = img.size # h is vertical pixels
                
                rendered_text = Text()
                # Use half-blocks (▄) to get 2 vertical pixels per line
                for py in range(0, h - 1, 2):
                    for px in range(w):
                        r1, g1, b1 = pixels[px, py]
                        r2, g2, b2 = pixels[px, py + 1]
                        # ▄ uses Foreground for the bottom half, Background for the top half
                        s = Style(color=f"rgb({r2},{g2},{b2})", bgcolor=f"rgb({r1},{g1},{b1})")
                        rendered_text.append("▄", style=s)
                    rendered_text.append("\n")
                
                info = (f"File: {path.name} | Original: {orig_w}x{orig_h} | Zoom: {int(self._zoom*100)}%\n"
                        f"Shortcuts: [+] Zoom In | [-] Zoom Out | [0] Reset")
                
                self.query_one("#image-placeholder", Static).update(Panel(
                    rendered_text,
                    title=f"[bold #8B5CF6]{path.name}[/]",
                    border_style="#8B5CF6",
                    padding=0,
                    expand=False
                ))
                self.query_one("#image-info", Label).update(info)
                
        except Exception as ex:
            self.query_one("#image-info", Label).update(f"Error rendering image: {ex}")

    def action_zoom_in(self) -> None:
        if self._zoom < 8.0:
            self._zoom *= 1.25
            if self._current_path:
                self.show_image(self._current_path)

    def action_zoom_out(self) -> None:
        if self._zoom > 0.1:
            self._zoom /= 1.25
            if self._current_path:
                self.show_image(self._current_path)

    def action_reset_zoom(self) -> None:
        self._zoom = 1.0
        if self._current_path:
            self.show_image(self._current_path)

    def clear(self) -> None:
        self.query_one("#image-placeholder", Static).update("No image selected")
        self.query_one("#image-info", Label).update("")
