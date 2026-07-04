from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widgets import Header, ListView, Static
from textual.worker import Worker
import asyncio
import sys
from pathlib import Path
from typing import Optional, Tuple

from core.scanner import DiskScanner
from core.utils import format_size, load_strings
from tui.list_items import DirectoryItem
from tui.logging_config import configure_logging, logger
from tui.modals import ConfirmDeletionModal, MixedDeletionModal
from tui.recycle_bin import RecycleBinMixin

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None


class DiskScoutApp(RecycleBinMixin, App):
    """Main TUI app for Disk Scout."""

    BINDINGS = [
        Binding("q", "quit", "Salir", key_display="Q"),
        Binding("enter", "open_selected", "Abrir", key_display="Enter", priority=True),
        Binding("backspace", "go_back", "Volver", key_display="Backspace", priority=True),
        Binding("space", "toggle_selection", "Marcar", key_display="Space"),
        Binding("a", "show_actions", "Papelera", key_display="A"),
    ]

    CSS = """
    #shortcuts_bar {
        color: $text;
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $accent;
        text-style: bold;
    }

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

    def __init__(
        self,
        root_path: str,
        lang: str = "es-AR",
        ignore_paths: Optional[list[str]] = None,
        include_ext: Optional[list[str]] = None,
        exclude_ext: Optional[list[str]] = None,
        max_depth: Optional[int] = None,
        follow_symlinks: bool = False,
        use_default_ignores: bool = True,
    ):
        super().__init__()
        self.root_path = Path(root_path).resolve()
        self.current_path = self.root_path
        self.path_history: list[Path] = []
        self.current_items: list[dict] = []
        self.scan_cache: dict[Path, tuple[list[dict], int, int]] = {}
        self.selected_indices: set[int] = set()
        self.lang = lang
        self.strings = load_strings(lang)
        self.scan_worker: Optional[Worker] = None
        self.deleting: bool = False
        self.current_total_size: int = 0
        self.current_max_size: int = 0
        self.deletion_task: Optional[asyncio.Task] = None
        self.confirmation_task: Optional[asyncio.Task] = None
        self.last_deleted: list[Path] = []
        self.awaiting_overflow_confirmation: bool = False
        self.preparing_delete_confirmation: bool = False
        self.ignore_paths = ignore_paths or []
        self.include_ext = include_ext or []
        self.exclude_ext = exclude_ext or []
        self.max_depth = max_depth
        self.follow_symlinks = follow_symlinks
        self.use_default_ignores = use_default_ignores
        configure_logging()

        logger.info(
            "DiskScoutApp initialized root=%s lang=%s default_ignores=%s ignore_paths=%s",
            self.root_path,
            self.lang,
            self.use_default_ignores,
            self.ignore_paths,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"{self.strings['root']}: {self.current_path}", id="current_path_header")
        yield ListView(id="file_list")
        yield Static(
            self.strings.get(
                "shortcuts",
                "Atajos: Enter abrir · Backspace volver · Espacio marcar · A Papelera · Q salir",
            ),
            id="shortcuts_bar",
        )

    def on_mount(self):
        """Scan the initial directory when the app starts."""
        self.scan_directory(self.current_path)

    def scan_directory(self, path: Path) -> None:
        """Launch an asynchronous scan for the given path."""
        if self.scan_worker and not self.scan_worker.is_finished:
            self.scan_worker.cancel()
        self.selected_indices.clear()
        cached = self.scan_cache.get(path)
        if cached:
            items, total_size, error_count = cached
            self._display_scan_results(path, items, total_size, error_count, refreshing=True)
        else:
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
            items, total_size, error_count = self._collect_items(path)
        except PermissionError:
            self.call_from_thread(
                self._update_header,
                f"{self.strings['permissions_error']} ({path})",
            )
            return

        self.call_from_thread(self._apply_scan_results, path, items, total_size, error_count)

    def _collect_items(self, path: Path) -> tuple[list[dict], int, int]:
        scanner = DiskScanner(
            include_ext=self.include_ext,
            exclude_ext=self.exclude_ext,
            ignore_paths=self.ignore_paths,
            max_depth=self.max_depth,
            follow_symlinks=self.follow_symlinks,
            use_default_ignores=self.use_default_ignores,
        )
        results = scanner.scan(path, top_n=0)
        items: list[dict] = []
        for child in results.get("immediate_children", {}).values():
            try:
                items.append(
                    {
                        "path": Path(child["path"]),
                        "size": int(child["size"]),
                        "is_dir": bool(child["is_dir"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return items, int(results["total_size"]), len(results.get("errors", []))

    def _display_scan_results(
        self,
        path: Path,
        items: list[dict],
        total_size: int,
        error_count: int = 0,
        refreshing: bool = False,
    ) -> None:
        self.current_items = sorted(items, key=lambda x: x['size'], reverse=True)
        self.current_total_size = total_size
        self.current_max_size = self.current_items[0]['size'] if self.current_items else 0
        self.refresh_list()
        message = (
            f"{self.strings['current_folder']}: {path} ({format_size(total_size)})"
            if self.current_items
            else f"{self.strings['empty_folder']} ({path})"
        )
        if error_count:
            message = f"{message} · {self.strings.get('partial_permissions_warning', 'Algunas rutas se omitieron por permisos.')}"
        if refreshing:
            message = f"{message} · {self.strings['scanning']}..."
        self._update_header(message)
        self.last_deleted = []

    def _apply_scan_results(self, path: Path, items: list[dict], total_size: int, error_count: int = 0) -> None:
        self.scan_cache[path] = (items, total_size, error_count)
        if path != self.current_path:
            return
        self._display_scan_results(path, items, total_size, error_count)

    def _update_header(self, message: str) -> None:
        try:
            header = self.query_one("#current_path_header", Static)
        except NoMatches:
            return
        header.update(message)

    def _start_deletion(self, items_to_delete: list[Path], total_size: int) -> None:
        self.deleting = True
        self.preparing_delete_confirmation = False
        self.confirmation_task = None
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
            self._perform_deletion(items_to_delete, total_size)
        )

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

    def _get_highlighted_index(self) -> Optional[int]:
        list_view = self.query_one("#file_list", ListView)
        idx = list_view.index
        if idx is None or idx < 0 or idx >= len(self.current_items):
            return None
        return idx

    def _open_directory_at_index(self, idx: Optional[int]) -> bool:
        if idx is None:
            message = self.strings.get(
                "select_folder_first",
                "Selecciona una carpeta para entrar.",
            )
            self._update_header(message)
            self.notify(message, severity="warning", timeout=4)
            return False

        item = self.current_items[idx]
        if not item['is_dir']:
            message = self.strings.get(
                "selected_item_not_folder",
                "El elemento seleccionado no es una carpeta.",
            )
            self._update_header(message)
            self.notify(message, severity="warning", timeout=4)
            return False

        self.selected_indices.clear()
        self.path_history.append(self.current_path)
        self.current_path = item['path']
        self.scan_directory(self.current_path)
        return True

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle item selection in the list."""
        self._open_directory_at_index(event.list_view.index)

    def action_open_selected(self) -> None:
        """Open the highlighted directory using Enter."""
        self._open_directory_at_index(self._get_highlighted_index())

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
            self.refresh_list()

    def action_show_actions(self) -> None:
        """Muestra acciones disponibles para los elementos seleccionados."""
        logger.info(
            "action_show_actions triggered with indices=%s",
            sorted(self.selected_indices),
        )
        if not self.selected_indices:
            logger.info("No items selected; action aborted")
            message = self.strings.get(
                "select_items_first",
                "Selecciona uno o más elementos con Espacio antes de usar Acciones.",
            )
            self._update_header(message)
            self.notify(message, severity="warning", timeout=4)
            return
        if self.preparing_delete_confirmation:
            logger.warning("Delete confirmation preparation already in progress")
            self._update_header(
                self.strings.get(
                    "preparing_delete_confirmation",
                    "Preparando confirmación de borrado...",
                )
            )
            return
        if self.deleting or self.awaiting_overflow_confirmation:
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
        self.preparing_delete_confirmation = True
        self._update_header(
            self.strings.get(
                "preparing_delete_confirmation",
                "Preparando confirmación de borrado...",
            )
        )
        if self.confirmation_task and not self.confirmation_task.done():
            self.confirmation_task.cancel()
        self.confirmation_task = asyncio.create_task(
            self._prepare_delete_confirmation(items_to_delete, total_size)
        )

    def _build_delete_confirmation_plan(
        self,
        items_to_delete: list[Path],
        total_size: int,
    ) -> dict[str, object]:
        """Build the confirmation plan outside the UI thread."""
        default_message = (
            f"{self.strings['confirm_delete']}\n"
            f"{len(items_to_delete)} · {format_size(total_size)}"
        )

        prediction = self._predict_recycle_bin_fit(items_to_delete)
        if prediction is not None:
            will_fit = list(prediction["will_fit"])
            overflow = list(prediction["overflow"])
            available = int(prediction["available_total"])
            min_margin = int(prediction["min_margin"])
            if will_fit and overflow:
                preview_names = ", ".join(p.name for p in overflow[:3])
                if len(overflow) > 3:
                    preview_names += f" +{len(overflow) - 3}"
                fit_size_total = sum(self._get_path_size_cached(p) for p in will_fit)
                overflow_size_total = sum(self._get_path_size_cached(p) for p in overflow)
                return {
                    "modal": "mixed",
                    "message": self.strings.get(
                        "recycle_bin_mixed_prompt",
                        "Heads up: {fit} of {total} items would fit; {overflow} may be deleted.",
                    ).format(
                        fit=len(will_fit),
                        total=len(items_to_delete),
                        overflow=len(overflow),
                        preview=preview_names,
                        fit_size=format_size(fit_size_total),
                        overflow_size=format_size(overflow_size_total),
                    ),
                    "will_fit": will_fit,
                    "overflow": overflow,
                }
            if overflow and not will_fit:
                return {
                    "modal": "confirm",
                    "message": self.strings.get(
                        "recycle_bin_overflow_prompt",
                        "Warning: the Recycle Bin may not have enough space.",
                    ).format(
                        available=format_size(max(available, 0)),
                        size=format_size(total_size),
                    ),
                }
            if will_fit and not overflow:
                margin = max(min_margin, 0)
                margin_threshold = 64 * 1024 * 1024
                logger.info(
                    "Recycle bin margin check (pre-confirm): available=%s total_size=%s margin=%s threshold=%s",
                    available,
                    total_size,
                    margin,
                    margin_threshold,
                )
                if margin <= margin_threshold:
                    return {
                        "modal": "confirm",
                        "message": self.strings.get(
                            "recycle_bin_marginal_prompt",
                            "Heads up: the Recycle Bin would have very little free space left ({margin}). Continue?",
                        ).format(margin=format_size(margin)),
                    }
            return {"modal": "confirm", "message": default_message}

        overflow_warning = self._evaluate_recycle_bin_risk(items_to_delete, total_size)
        if overflow_warning:
            return {"modal": "confirm", "message": overflow_warning}
        return {"modal": "confirm", "message": default_message}

    async def _prepare_delete_confirmation(
        self,
        items_to_delete: list[Path],
        total_size: int,
    ) -> None:
        try:
            plan = await asyncio.to_thread(
                self._build_delete_confirmation_plan,
                items_to_delete,
                total_size,
            )
        except asyncio.CancelledError:
            self.preparing_delete_confirmation = False
            self.confirmation_task = None
            raise
        except Exception:
            logger.exception("Error preparing delete confirmation")
            plan = {
                "modal": "confirm",
                "message": (
                    f"{self.strings['confirm_delete']}\n"
                    f"{len(items_to_delete)} · {format_size(total_size)}"
                ),
            }

        self.preparing_delete_confirmation = False
        self.confirmation_task = None

        if plan.get("modal") == "mixed":
            will_fit = list(plan.get("will_fit", []))

            def handle_mixed(choice: Optional[str]) -> None:
                logger.info("Mixed choice result=%s", choice)
                if choice == "fit":
                    paths_fit = will_fit
                    size_fit = sum(self._get_path_size_cached(p) for p in paths_fit)
                    if not paths_fit:
                        self._update_header(self.strings.get("delete_cancelled", "Acción cancelada"))
                        return
                    self._start_deletion(paths_fit, size_fit)
                    return
                if choice == "all":
                    self._start_deletion(items_to_delete, total_size)
                    return
                self._update_header(self.strings.get("delete_cancelled", "Acción cancelada"))

            self.push_screen(
                MixedDeletionModal(str(plan["message"]), self.strings),
                handle_mixed,
            )
            return

        def handle_confirmation(confirmed: Optional[bool]) -> None:
            logger.info("Deletion confirmation result=%s", confirmed)
            if confirmed is not True:
                logger.info("Deletion cancelled by user")
                self._update_header(
                    self.strings.get("delete_cancelled", "Acción cancelada")
                )
                return
            self._start_deletion(items_to_delete, total_size)

        self.push_screen(
            ConfirmDeletionModal(str(plan["message"]), self.strings),
            handle_confirmation,
        )

    async def _perform_deletion(self, paths: list[Path], expected_total_size: int) -> None:
        before_stats = self._query_recycle_bin_multi(paths)
        try:
            successes, failures = await asyncio.to_thread(self._send_to_trash, paths)
        except Exception as error:  # pragma: no cover - defensive safeguard
            logger.exception("Unexpected error during deletion task")
            self._handle_deletion_complete(
                [],
                [(Path("?"), str(error))],
                len(paths),
                0,
                before_stats,
                self._query_recycle_bin_multi(paths),
            )
            return

        after_stats = self._query_recycle_bin_multi(paths)
        self._handle_deletion_complete(
            successes,
            failures,
            len(paths),
            expected_total_size,
            before_stats,
            after_stats,
        )

    def _handle_deletion_complete(
        self,
        successes: list[Path],
        failures: list[tuple[Path, str]],
        total: int,
        expected_total_size: int,
        before_stats: Optional[Tuple[int, int]],
        after_stats: Optional[Tuple[int, int]],
        all_paths: Optional[list[Path]] = None,
    ) -> None:
        self.deleting = False
        self.deletion_task = None
        self.confirmation_task = None
        self.awaiting_overflow_confirmation = False
        self.preparing_delete_confirmation = False
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

        potential_bin_issue = False
        suspected_count = 0
        if (
            processed
            and expected_total_size > 0
            and before_stats
            and after_stats
        ):
            before_items, before_size = before_stats
            after_items, after_size = after_stats
            size_delta = after_size - before_size
            items_delta = after_items - before_items
            threshold = max(int(expected_total_size * 0.1), 1)
            if size_delta < threshold or items_delta < processed:
                potential_bin_issue = True
                suspected_count = max(processed - max(items_delta, 0), 1)
                logger.warning(
                    "Recycle bin delta smaller than expected (expected=%s, delta=%s, items_delta=%s)",
                    expected_total_size,
                    size_delta,
                    items_delta,
                )

        if potential_bin_issue:
            if suspected_count and suspected_count < processed:
                warning_message = self.strings.get(
                    "recycle_bin_space_warning_some",
                    "Warning: {suspected} of {processed} items may have been permanently deleted.",
                ).format(suspected=suspected_count, processed=processed)
                warning_short = self.strings.get(
                    "recycle_bin_space_warning_some_short",
                    "Warning: possible permanent deletion of {suspected} of {processed}.",
                ).format(suspected=suspected_count, processed=processed)
            else:
                warning_message = self.strings.get(
                    "recycle_bin_space_warning",
                    "Warning: Recycle Bin may have skipped some items.",
                )
                warning_short = self.strings.get(
                    "recycle_bin_space_warning_short",
                    "Warning: Windows may have deleted items permanently.",
                )
            message = f"{message} · {warning_short}"

        self._update_header(message)

        if processed:
            suspect_preview = ""
            if potential_bin_issue and suspected_count:
                sized_successes = [
                    (p, self._get_path_size_cached(p)) for p in successes
                ]
                sized_successes.sort(key=lambda t: t[1], reverse=True)
                suspect_paths = [p for p, _ in sized_successes[:suspected_count]]
                suspect_preview = ", ".join(p.name for p in suspect_paths[:3])
                if len(suspect_paths) > 3:
                    suspect_preview += f" +{len(suspect_paths) - 3}"

            names_preview = ", ".join(path.name for path in successes[:3])
            if len(successes) > 3:
                names_preview += f" +{len(successes) - 3}"
            severity = "warning" if failures or potential_bin_issue else "information"
            if suspect_preview:
                self.notify(
                    f"{message}\n{self.strings.get('suspected_permanent', 'Sospechoso permanente')}: {suspect_preview}",
                    severity=severity,
                    timeout=8,
                )
            else:
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
        if potential_bin_issue:
            self.notify(warning_message, severity="warning", timeout=8)

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
            return
        message = self.strings.get(
            "already_at_root",
            "Ya estás en la carpeta inicial.",
        )
        self._update_header(message)
        self.notify(message, severity="information", timeout=4)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        lang_arg = sys.argv[2] if len(sys.argv) > 2 else "es-AR"
        app = DiskScoutApp(sys.argv[1], lang=lang_arg)
    else:
        app = DiskScoutApp(".")
    app.run()
