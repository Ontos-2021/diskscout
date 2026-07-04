from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import ListItem, Static

from core.utils import draw_bar, format_size


class DirectoryItem(ListItem):
    """A ListItem that displays a file or folder."""

    def __init__(
        self,
        name: str,
        path: Path,
        size: int,
        total_size: int,
        is_dir: bool,
        selected: bool = False,
        recently_deleted: bool = False,
    ):
        super().__init__()
        self.item_name = name
        self.item_path = path
        self.item_size = size
        self.total_size = total_size
        self.is_dir = is_dir
        self.selected = selected
        self.recently_deleted = recently_deleted

    def compose(self) -> ComposeResult:
        icon = "📁" if self.is_dir else "📄"
        bar = draw_bar(self.item_size, self.total_size, 20)
        check = "[x]" if self.selected else "[ ]"
        status = "🗑️ " if self.recently_deleted else ""
        label = f"{check} {status}{icon} {bar} {self.item_name}"
        size_str = format_size(self.item_size)

        yield Static(f"{label:<60} {size_str:>12}")
