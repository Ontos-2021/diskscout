from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Static
from textual.worker import Worker
import asyncio
import json
import os
import sys
from functools import partial
from pathlib import Path
import logging
from typing import Optional

logger = logging.getLogger("DiskScoutTUI")
if not logger.handlers:
    handler = logging.FileHandler("tui.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scanner import DiskScanner
from core.utils import format_size, draw_bar, load_strings

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None


class ConfirmDeletionModal(ModalScreen[bool]):
    """Modal sencillo para confirmar el envío a la Papelera."""

    BINDINGS = [
        Binding("y", "confirm", "", show=False),
        Binding("s", "confirm", "", show=False),
        Binding("n", "cancel", "", show=False),
        Binding("escape", "cancel", "", show=False),
    ]

    def __init__(self, message: str, strings: dict):
        super().__init__()
        self.message = message
        self.strings = strings

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.message, id="confirm_message"),
            Static(
                self.strings.get(
                    "confirm_shortcuts",
                    "Teclas: S o Y para Sí · N para No · Esc para cancelar",
                ),
                id="confirm_shortcuts",
            ),
            Horizontal(
                Button(self.strings["yes"], id="confirm_yes", variant="success"),
                Button(self.strings["no"], id="confirm_no", variant="primary"),
                id="confirm_buttons",
            ),
            id="confirm_container",
        )

    def on_mount(self) -> None:
        self.query_one("#confirm_yes", Button).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        logger.info("Modal button pressed: %s", event.button.id)
        if event.button.id == "confirm_yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        logger.info("Modal confirm action triggered")
        self.dismiss(True)

    def action_cancel(self) -> None:
        logger.info("Modal cancel action triggered")
        self.dismiss(False)


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

class DiskScoutApp(App):
    """Main TUI app for Disk Scout."""

    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("backspace", "go_back", "Volver"),
        Binding("space", "toggle_selection", "Marcar"),
        Binding("a", "show_actions", "Acciones"),
    ]

    CSS = """
    #confirm_container {
        align: center middle;
        width: 60%;
        border: round #666;
        background: $background 30%;
        padding: 1 2;
    }

    #confirm_message {
        padding-bottom: 1;
        text-align: center;
    }

    #confirm_shortcuts {
        color: $text-muted;
        padding-bottom: 1;
        text-align: center;
    }

    #confirm_buttons {
        width: 100%;
        align: center middle;
    }
    """

    def __init__(self, root_path: str, lang: str = "es-AR"):
        super().__init__()
        self.root_path = Path(root_path).resolve()
        self.current_path = self.root_path
        self.path_history: list[Path] = []
        self.current_items: list[dict] = []
        self.selected_indices: set[int] = set()
        self.lang = lang
        self.strings = load_strings(lang)
        self.scan_worker: Optional[Worker] = None
        self.deleting: bool = False
        self.current_total_size: int = 0
        self.current_max_size: int = 0
        self.deletion_task: Optional[asyncio.Task] = None
        self.last_deleted: list[Path] = []

        logger.info("DiskScoutApp initialized root=%s lang=%s", self.root_path, self.lang)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"{self.strings['root']}: {self.current_path}", id="current_path_header")
        yield ListView(id="file_list")
        yield Footer()

    def on_mount(self):
        """Scan the initial directory when the app starts."""
        self.scan_directory(self.current_path)

    def scan_directory(self, path: Path) -> None:
        """Launch an asynchronous scan for the given path."""
        if self.scan_worker and not self.scan_worker.finished:
            self.scan_worker.cancel()
        self.selected_indices.clear()
        self.query_one("#file_list", ListView).clear()
        self._update_header(f"{self.strings['scanning']}: {path}...")
        self.scan_worker = self.run_worker(
            lambda: self._scan_worker(path),
            exclusive=True,
            thread=True,
            name="scan",
        )

    def _scan_worker(self, path: Path) -> None:
        try:
            items, total_size = self._collect_items(path)
        except PermissionError:
            self.call_from_thread(
                self._update_header,
                f"{self.strings['permissions_error']} ({path})",
            )
            return

        self.call_from_thread(self._apply_scan_results, path, items, total_size)

    def _collect_items(self, path: Path) -> tuple[list[dict], int]:
        scanner = DiskScanner()
        items: list[dict] = []
        total_size = 0
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    is_dir = entry.is_dir()
                    if is_dir:
                        dir_results = scanner.scan(entry.path)
                        size = dir_results['total_size']
                    else:
                        size = entry.stat().st_size
                    items.append({"path": Path(entry.path), "size": size, "is_dir": is_dir})
                    total_size += size
                except (PermissionError, FileNotFoundError):
                    continue
        return items, total_size

    def _apply_scan_results(self, path: Path, items: list[dict], total_size: int) -> None:
        if path != self.current_path:
            return
        self.current_items = sorted(items, key=lambda x: x['size'], reverse=True)
        self.current_total_size = total_size
        self.current_max_size = self.current_items[0]['size'] if self.current_items else 0
        self.refresh_list()
        message = (
            f"{self.strings['current_folder']}: {path} ({format_size(total_size)})"
            if self.current_items
            else f"{self.strings['empty_folder']} ({path})"
        )
        self._update_header(message)
        self.last_deleted = []

    def _update_header(self, message: str) -> None:
        try:
            header = self.query_one("#current_path_header", Static)
        except NoMatches:
            return
        header.update(message)

    def _prune_deleted_items(self, deleted_paths: list[Path]) -> None:
        """Remove deleted entries from the current list so the UI reflects the change."""
        if not deleted_paths:
            return
        deleted_set = {path.resolve() for path in deleted_paths}
        if not deleted_set:
            return
        self.current_items = [
            item
            for item in self.current_items
            if item['path'].resolve() not in deleted_set
        ]

    def refresh_list(self) -> None:
        """Refresca la lista para reflejar la selección actual."""
        list_view = self.query_one("#file_list", ListView)
        list_view.clear()
        max_size = self.current_max_size
        deleted_lookup = {path.resolve() for path in self.last_deleted}
        for idx, item in enumerate(self.current_items):
            selected = idx in self.selected_indices
            list_item = DirectoryItem(
                name=item['path'].name,
                path=item['path'],
                size=item['size'],
                total_size=max_size,
                is_dir=item['is_dir'],
                selected=selected,
                recently_deleted=item['path'].resolve() in deleted_lookup,
            )
            list_view.append(list_item)


    def on_list_view_selected(self, event: ListView.Selected):
        """Handle item selection in the list."""
        item = event.item
        idx = event.list_view.index
        if item.is_dir:
            self.path_history.append(self.current_path)
            self.current_path = item.item_path
            self.scan_directory(self.current_path)

    def action_toggle_selection(self):
        """Toggle selection of the highlighted item."""
        list_view = self.query_one("#file_list", ListView)
        idx = list_view.index
        if idx is not None:
            if idx in self.selected_indices:
                self.selected_indices.remove(idx)
                logger.info("Selection removed for index %s", idx)
            else:
                self.selected_indices.add(idx)
                logger.info("Selection added for index %s", idx)
            # Refresh the list to show selection
            self.refresh_list()

    def action_show_actions(self) -> None:
        """Muestra acciones disponibles para los elementos seleccionados."""
        logger.info(
            "action_show_actions triggered with indices=%s",
            sorted(self.selected_indices),
        )
        if not self.selected_indices:
            logger.info("No items selected; action aborted")
            return
        if self.deleting:
            logger.warning("Deletion already in progress")
            self._update_header(
                self.strings.get(
                    "delete_in_progress",
                    "Envío a la Papelera en curso, espera...",
                )
            )
            return
        if send2trash is None:
            logger.error("send2trash module not available")
            self._update_header(
                self.strings.get("send2trash_missing", "Error: send2trash no instalado")
            )
            return

        indices = sorted(self.selected_indices)
        items_to_delete = [self.current_items[i]['path'] for i in indices]
        total_size = sum(self.current_items[i]['size'] for i in indices)
        logger.info(
            "Prepared %s items for deletion (total size %s)",
            len(items_to_delete),
            format_size(total_size),
        )
        confirm_message = (
            f"{self.strings['confirm_delete']}\n"
            f"{len(items_to_delete)} · {format_size(total_size)}"
        )
        
        def handle_confirmation(confirmed: Optional[bool]) -> None:
            logger.info("Deletion confirmation result=%s", confirmed)
            if confirmed is not True:
                logger.info("Deletion cancelled by user")
                self._update_header(
                    self.strings.get("delete_cancelled", "Acción cancelada")
                )
                return

            self.deleting = True
            self._update_header(
                self.strings.get(
                    "sending_to_trash",
                    "Enviando a la Papelera...",
                )
            )
            logger.info("Starting deletion for %s files", len(items_to_delete))
            if self.deletion_task and not self.deletion_task.done():
                self.deletion_task.cancel()
            self.deletion_task = asyncio.create_task(
                self._perform_deletion(items_to_delete)
            )
        
        self.push_screen(
            ConfirmDeletionModal(confirm_message, self.strings),
            handle_confirmation
        )
    
    async def _perform_deletion(self, paths: list[Path]) -> None:
        try:
            successes, failures = await asyncio.to_thread(self._send_to_trash, paths)
        except Exception as error:  # pragma: no cover - defensive safeguard
            logger.exception("Unexpected error during deletion task")
            self._handle_deletion_complete([], [(Path("?"), str(error))], len(paths))
            return
        self._handle_deletion_complete(successes, failures, len(paths))

    def _handle_deletion_complete(
        self,
        successes: list[Path],
        failures: list[tuple[Path, str]],
        total: int,
    ) -> None:
        self.deleting = False
        self.deletion_task = None
        processed = len(successes)
        logger.info(
            "Deletion worker finished: processed=%s failures=%s",
            processed,
            len(failures),
        )

        if total == 0:
            self.last_deleted = []
            self._update_header(self.strings.get("delete_cancelled", "Acción cancelada"))
            return

        self.last_deleted = successes
        if successes:
            self._prune_deleted_items(successes)
            self.selected_indices.clear()
            self.refresh_list()

        if processed == total:
            message = self.strings.get(
                "delete_result_success",
                "Enviados {total} elementos a la Papelera",
            ).format(total=total)
        else:
            message = self.strings.get(
                "delete_result_partial",
                "Se enviaron {processed} de {total} elementos a la Papelera",
            ).format(processed=processed, total=total)

        if failures:
            detail_template = self.strings.get(
                "delete_error_detail",
                "Error en {path}: {error}",
            )
            failed_path, error_message = failures[0]
            logger.warning("Deletion failures encountered: %s", failures)
            message = f"{message} · {detail_template.format(path=str(failed_path), error=error_message)}"

        self._update_header(message)

        if processed:
            names_preview = ", ".join(path.name for path in successes[:3])
            if len(successes) > 3:
                names_preview += f" +{len(successes) - 3}"
            severity = "warning" if failures else "information"
            self.notify(
                f"{message}\n{names_preview}",
                severity=severity,
                timeout=6,
            )
        elif failures:
            failed_preview = ", ".join(path.name for path, _ in failures[:3])
            self.notify(
                f"{message}\n{failed_preview}",
                severity="error",
                timeout=6,
            )

        if not successes:
            self.selected_indices.clear()

        self.scan_directory(self.current_path)

    def _send_to_trash(self, paths: list[Path]) -> tuple[list[Path], list[tuple[Path, str]]]:
        logger.info("Attempting to delete paths: %s", paths)
        successes: list[Path] = []
        failures: list[tuple[Path, str]] = []
        for path in paths:
            try:
                if path.exists():
                    logger.info("Sending %s to trash", path)
                    send2trash(str(path))
                    successes.append(path)
                else:
                    logger.warning("Path does not exist, skipping: %s", path)
                    failures.append((path, "Path does not exist"))
            except Exception as error:
                logger.exception("Failed to delete %s", path)
                failures.append((path, str(error)))
        return successes, failures

    def action_go_back(self):
        """Go back to the previous directory."""
        self.selected_indices.clear()
        if self.path_history:
            self.current_path = self.path_history.pop()
            self.scan_directory(self.current_path)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        lang_arg = sys.argv[2] if len(sys.argv) > 2 else "es-AR"
        app = DiskScoutApp(sys.argv[1], lang=lang_arg)
    else:
        app = DiskScoutApp(".")
    app.run()
