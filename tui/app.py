from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Static
from textual.containers import Horizontal, Vertical
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scanner import DiskScanner
from core.utils import format_size

class DiskScoutApp(App):
    """Main TUI app for Disk Scout."""

    CSS = """
    #file_list {
        width: 60%;
        height: 100%;
    }
    #details {
        width: 40%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }
    """

    def __init__(self, root_path):
        super().__init__()
        self.root_path = Path(root_path)
        self.scan_results = None
        self.current_items = []  # list of (name, size, is_dir)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ListView(id="file_list")
            yield Static("Scanning...", id="details")
        yield Footer()

    def on_mount(self):
        """Scan directory on mount."""
        self.scan_directory()

    def scan_directory(self):
        """Perform the scan."""
        scanner = DiskScanner()
        self.scan_results = scanner.scan(str(self.root_path))

        # Populate current_items with top_children
        self.current_items = [(name, size, True) for name, size in self.scan_results['top_children'].items()]
        self.current_items.extend([(Path(path).name, size, False) for size, path in self.scan_results['top_files']])

        self.update_list()

    def update_list(self):
        """Update the list view."""
        list_view = self.query_one("#file_list", ListView)
        list_view.clear()

        for name, size, is_dir in self.current_items:
            icon = "📁" if is_dir else "📄"
            list_view.append(ListItem(Static(f"{icon} {name} - {format_size(size)}")))

    def update_details(self, selected_item):
        """Update details panel."""
        if not selected_item:
            return
        name, size, is_dir = selected_item
        details = self.query_one("#details", Static)
        details.update(f"Selected: {name}\nSize: {format_size(size)}\nType: {'Folder' if is_dir else 'File'}")

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle list selection."""
        index = event.list_view.index
        if 0 <= index < len(self.current_items):
            self.update_details(self.current_items[index])

if __name__ == "__main__":
    # For testing
    app = DiskScoutApp("C:\\Users\\Kotelo\\Desktop")
    app.run()
