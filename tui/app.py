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
from pathlib import Path
import logging
from typing import Optional, Tuple

logger = logging.getLogger("DiskScoutTUI")
if not logger.handlers:
    handler = logging.FileHandler("tui.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

if os.name == "nt":
    import ctypes
    import winreg

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("i64Size", ctypes.c_longlong),
            ("i64NumItems", ctypes.c_longlong),
        ]
else:  # pragma: no cover - non-Windows fallback
    ctypes = None  # type: ignore[assignment]
    winreg = None  # type: ignore[assignment]
    SHQUERYRBINFO = None

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


class MixedDeletionModal(ModalScreen[str]):
    """Modal con tres opciones para casos mixtos: borrar todo, sólo lo que entra o cancelar."""

    BINDINGS = [
        Binding("y", "choose_all", "", show=False),
        Binding("s", "choose_all", "", show=False),
        Binding("f", "choose_fit", "", show=False),
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
                    "mixed_shortcuts",
                    "Teclas: S/Y = Todo · F = Sólo los que entran · N = No · Esc = Cancelar",
                ),
                id="confirm_shortcuts",
            ),
            Horizontal(
                Button(self.strings.get("yes", "Sí"), id="confirm_all", variant="success"),
                Button(self.strings.get("only_fit", "Sólo los que entran"), id="confirm_fit", variant="warning"),
                Button(self.strings.get("no", "No"), id="confirm_no", variant="primary"),
                id="confirm_buttons",
            ),
            id="confirm_container",
        )

    def on_mount(self) -> None:
        self.query_one("#confirm_all", Button).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        logger.info("Mixed modal button pressed: %s", event.button.id)
        if event.button.id == "confirm_all":
            self.dismiss("all")
        elif event.button.id == "confirm_fit":
            self.dismiss("fit")
        else:
            self.dismiss("cancel")

    def action_choose_all(self) -> None:
        logger.info("Mixed modal choose_all action")
        self.dismiss("all")

    def action_choose_fit(self) -> None:
        logger.info("Mixed modal choose_fit action")
        self.dismiss("fit")

    def action_cancel(self) -> None:
        logger.info("Mixed modal cancel action")
        self.dismiss("cancel")


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
        self.awaiting_overflow_confirmation: bool = False

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

    def _query_recycle_bin(self, target: Optional[Path] = None) -> Optional[Tuple[int, int]]:
        """Return (item_count, total_size) for the system Recycle Bin or a drive."""
        if os.name != "nt" or SHQUERYRBINFO is None or ctypes is None:
            return None
        try:
            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            query_path = None
            if target:
                drive = target.drive or os.path.splitdrive(str(target))[0]
                if drive:
                    query_path = f"{drive.rstrip(':')}:\\"
            result = ctypes.windll.shell32.SHQueryRecycleBinW(
                query_path,
                ctypes.byref(info),
            )
            if result != 0:
                raise ctypes.WinError(result)
            return (int(info.i64NumItems), int(info.i64Size))
        except Exception as error:  # pragma: no cover - Windows-specific guard
            logger.warning("Recycle bin query failed: %s", error)
            return None

    def _query_recycle_bin_multi(self, paths: list[Path]) -> Optional[Tuple[int, int]]:
        """Return aggregated (item_count, total_size) across all drives involved in paths."""
        if not paths:
            return self._query_recycle_bin()
        drives = []
        for p in paths:
            drive = p.drive or os.path.splitdrive(str(p))[0]
            if drive and drive not in drives:
                drives.append(drive)
        total_items = 0
        total_size = 0
        for d in drives:
            try:
                info = SHQUERYRBINFO()
                info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
                query_path = f"{d.rstrip(':')}:\\"
                result = ctypes.windll.shell32.SHQueryRecycleBinW(
                    query_path,
                    ctypes.byref(info),
                )
                if result == 0:
                    total_items += int(info.i64NumItems)
                    total_size += int(info.i64Size)
            except Exception:
                continue
        return (total_items, total_size)

    def _get_drive_total_bytes(self, path: Path) -> Optional[int]:
        if os.name != "nt" or ctypes is None:
            return None
        drive = path.drive or os.path.splitdrive(str(path))[0]
        if not drive:
            return None
        root = f"{drive.rstrip(':')}:\\"
        free_bytes_available = ctypes.c_ulonglong()
        total_number_of_bytes = ctypes.c_ulonglong()
        total_number_of_free_bytes = ctypes.c_ulonglong()
        success = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(root),
            ctypes.byref(free_bytes_available),
            ctypes.byref(total_number_of_bytes),
            ctypes.byref(total_number_of_free_bytes),
        )
        if success:
            return int(total_number_of_bytes.value)
        return None

    def _get_volume_guid_for_path(self, path: Path) -> Optional[str]:
        """Return the volume GUID path for the drive of 'path', e.g. \\?\Volume{GUID}\\.

        Uses GetVolumeNameForVolumeMountPointW on the drive root (C:\\).
        """
        if os.name != "nt" or ctypes is None:
            return None
        drive = path.drive or os.path.splitdrive(str(path))[0]
        if not drive:
            return None
        root = f"{drive.rstrip(':')}:\\"
        buf_len = 128
        buffer = ctypes.create_unicode_buffer(buf_len)
        success = ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(
            ctypes.c_wchar_p(root), buffer, buf_len
        )
        if success:
            guid = buffer.value
            # Normalize: ensure trailing backslash removed for comparison uniformity
            return guid.rstrip("\\").lower()
        return None

    def _get_recycle_bin_limit_bytes(self, path: Path, current_usage: int) -> Optional[int]:
        if os.name != "nt" or winreg is None:
            return None
        drive = path.drive or os.path.splitdrive(str(path))[0]
        if not drive:
            return None
        drive_root = f"{drive.rstrip(':')}:\\"
        volume_guid = self._get_volume_guid_for_path(path)
        found_limit = None

        # Helper available across all branches in this method
        def _decode_reg_value(val: object) -> str:
            if isinstance(val, (bytes, bytearray)):
                try:
                    s = val.decode("utf-16-le", errors="ignore")
                except Exception:
                    try:
                        s = val.decode(errors="ignore")  # type: ignore[arg-type]
                    except Exception:
                        s = ""
                return s.split("\x00", 1)[0]
            return str(val)

        def _try_read_limit_from_key(key_handle, source_label: str) -> Optional[int]:
            """Attempt to read NukeOnDelete/MaxCapacity or Percent from a given key.
            Returns limit in bytes or 0 if NukeOnDelete, or None if not present.
            """
            # NukeOnDelete overrides everything
            try:
                nuke_on_delete, _ = winreg.QueryValueEx(key_handle, "NukeOnDelete")
                if int(nuke_on_delete) == 1:
                    logger.info("Recycle Bin (%s) configured to delete immediately for %s", source_label, drive_root)
                    return 0
            except FileNotFoundError:
                pass

            # Primary: MaxCapacity (MB)
            max_capacity = None
            try:
                max_capacity, _ = winreg.QueryValueEx(key_handle, "MaxCapacity")
            except FileNotFoundError:
                max_capacity = None
            if max_capacity is not None:
                try:
                    mc = int(max_capacity)
                except Exception:
                    mc = 0
                if mc <= 0:
                    return 0
                limit_bytes = mc * 1024 * 1024
                total_bytes = self._get_drive_total_bytes(path)
                if total_bytes and limit_bytes > total_bytes:
                    limit_bytes = total_bytes
                logger.info(
                    "Recycle Bin limit (MB) read from %s for %s: %s MB (~%s bytes)",
                    source_label,
                    drive_root,
                    mc,
                    limit_bytes,
                )
                return limit_bytes

            # Fallback: Percent (0-100) if present on some systems
            try:
                percent, _ = winreg.QueryValueEx(key_handle, "Percent")
                pct = int(percent)
                if pct < 0:
                    pct = 0
                if pct > 100:
                    pct = 100
                total_bytes = self._get_drive_total_bytes(path)
                if total_bytes:
                    limit_bytes = (total_bytes * pct) // 100
                    logger.info(
                        "Recycle Bin limit (Percent=%s%%) read from %s for %s: ~%s bytes",
                        pct,
                        source_label,
                        drive_root,
                        limit_bytes,
                    )
                    return limit_bytes
            except FileNotFoundError:
                pass
            return None
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume",
            ) as volumes_key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(volumes_key, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(volumes_key, subkey_name) as volume_key:
                            # Try matching via Volume GUID first (most reliable)
                            volume_value = None
                            try:
                                volume_value, _ = winreg.QueryValueEx(volume_key, "Volume")
                            except FileNotFoundError:
                                volume_value = None
                            matched = False
                            if volume_guid and volume_value:
                                vol_str = _decode_reg_value(volume_value).rstrip("\\").lower()
                                if vol_str and vol_str == volume_guid:
                                    matched = True

                            # Fallback: match by MountPoint (e.g., C:\)
                            if not matched:
                                mount_point = None
                                try:
                                    mount_point, _ = winreg.QueryValueEx(volume_key, "MountPoint")
                                except FileNotFoundError:
                                    mount_point = None
                                if mount_point:
                                    mp_str = _decode_reg_value(mount_point)
                                    if mp_str.lower().startswith(drive_root.lower()):
                                        matched = True

                            if not matched:
                                continue
                            limit = _try_read_limit_from_key(volume_key, "Volume")
                            if limit is None:
                                continue
                            found_limit = limit
                            raise StopIteration
                    except OSError:
                        continue
        except FileNotFoundError:
            pass
        except StopIteration:
            # Found via Volume
            return found_limit

        # Try BitBucket\Bins as a fallback (some systems store per-volume settings here)
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Bins",
            ) as bins_key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(bins_key, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(bins_key, subkey_name) as bin_key:
                            # The Bins structure sometimes nests user SIDs -> Volume GUIDs
                            # Try the current key first, then any child keys.

                            def _match_and_read_from(handle) -> Optional[int]:
                                # Prefer matching Volume GUID, fallback to MountPoint
                                volume_value = None
                                try:
                                    volume_value, _ = winreg.QueryValueEx(handle, "Volume")
                                except FileNotFoundError:
                                    volume_value = None

                                matched = False
                                if volume_guid and volume_value:
                                    vol_str = _decode_reg_value(volume_value).rstrip("\\").lower()
                                    if vol_str and vol_str == volume_guid:
                                        matched = True
                                if not matched:
                                    try:
                                        mount_point, _ = winreg.QueryValueEx(handle, "MountPoint")
                                        mp_str = _decode_reg_value(mount_point)
                                        if mp_str.lower().startswith(drive_root.lower()):
                                            matched = True
                                    except FileNotFoundError:
                                        pass
                                if not matched:
                                    return None
                                return _try_read_limit_from_key(handle, "Bins")

                            # Try current key
                            limit = _match_and_read_from(bin_key)
                            if limit is not None:
                                return limit

                            # Enumerate child keys (e.g., SID -> Volume GUID)
                            try:
                                child_index = 0
                                while True:
                                    try:
                                        child_name = winreg.EnumKey(bin_key, child_index)
                                        child_index += 1
                                    except OSError:
                                        break
                                    try:
                                        with winreg.OpenKey(bin_key, child_name) as child_key:
                                            limit = _match_and_read_from(child_key)
                                            if limit is not None:
                                                return limit
                                    except OSError:
                                        continue
                            except OSError:
                                pass
                    except OSError:
                        continue
        except FileNotFoundError:
            pass
        total_bytes = self._get_drive_total_bytes(path)
        if total_bytes is None:
            return None
        # Assume default Windows behavior (~5% of drive) if configuration not found.
        approximate_limit = int(total_bytes * 0.05)
        if approximate_limit <= 0:
            return None
        logger.info(
            "Recycle Bin limit fallback (~5%% of drive) for %s: ~%s bytes (could not read Volume/Bins keys)",
            drive_root,
            approximate_limit,
        )
        return approximate_limit

    def _evaluate_recycle_bin_risk(
        self,
        paths: list[Path],
        total_size: int,
    ) -> Optional[str]:
        if os.name != "nt" or not paths:
            return None
        bin_stats = self._query_recycle_bin(paths[0])
        if bin_stats is None:
            return self.strings.get("recycle_bin_overflow_prompt_unknown")
        _, current_usage = bin_stats
        limit_bytes = self._get_recycle_bin_limit_bytes(paths[0], current_usage)
        if limit_bytes is None:
            return self.strings.get("recycle_bin_overflow_prompt_unknown")
        if limit_bytes <= 0:
            return self.strings.get("recycle_bin_overflow_prompt_unknown")
        available = max(limit_bytes - current_usage, 0)
        if total_size > available:
            return self.strings.get(
                "recycle_bin_overflow_prompt",
                "Warning: the Recycle Bin may not have enough space.",
            ).format(
                available=format_size(available),
                size=format_size(total_size),
            )
        return None

    def _predict_recycle_bin_fit(
        self,
        paths: list[Path],
    ) -> Optional[Tuple[list[Path], list[Path], int]]:
        """Predict which of the given paths would fit in the Recycle Bin quota.

        Returns (will_fit, overflow, available_bytes) or None if unknown.
        """
        if os.name != "nt" or not paths:
            return None
        bin_stats = self._query_recycle_bin(paths[0])
        if bin_stats is None:
            return None
        _, current_usage = bin_stats
        limit_bytes = self._get_recycle_bin_limit_bytes(paths[0], current_usage)
        if limit_bytes is None or limit_bytes <= 0:
            return None
        available = max(limit_bytes - current_usage, 0)
        logger.info(
            "Recycle bin fit prediction: current_usage=%s limit=%s available=%s for %s items",
            current_usage,
            limit_bytes,
            available,
            len(paths),
        )

        # Build a size map from current listing, fallback to stat/scan
        size_map: dict[Path, int] = {}
        for item in self.current_items:
            size_map[item['path'].resolve()] = int(item['size'])

        def get_size(p: Path) -> int:
            rp = p.resolve()
            if rp in size_map:
                return size_map[rp]
            try:
                if rp.is_dir():
                    return int(DiskScanner().scan(str(rp))['total_size'])
                return int(rp.stat().st_size)
            except Exception:
                return 0

        ordered = sorted(paths, key=lambda p: get_size(p))  # small first to maximize fit
        will_fit: list[Path] = []
        overflow: list[Path] = []
        remaining = available
        for p in ordered:
            sz = get_size(p)
            if sz <= remaining:
                will_fit.append(p)
                remaining -= sz
            else:
                overflow.append(p)
        return (will_fit, overflow, available)

    def _get_path_size_cached(self, p: Path) -> int:
        """Return size for a path using current_items cache, falling back to stat/scan."""
        rp = p.resolve()
        for item in self.current_items:
            if item['path'].resolve() == rp:
                return int(item['size'])
        try:
            if rp.is_dir():
                return int(DiskScanner().scan(str(rp))['total_size'])
            return int(rp.stat().st_size)
        except Exception:
            return 0

    def _start_deletion(self, items_to_delete: list[Path], total_size: int) -> None:
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
        # Build an informed confirmation message BEFORE asking the user
        # so the user sees mixed/overflow/marginal risks up front.
        confirm_message: str
        prediction = self._predict_recycle_bin_fit(items_to_delete)
        if prediction is not None:
            will_fit, overflow, available = prediction
            if will_fit and overflow:
                preview_names = ", ".join(p.name for p in overflow[:3])
                if len(overflow) > 3:
                    preview_names += f" +{len(overflow) - 3}"
                # Compute total sizes for each group for display
                fit_size_total = sum(self._get_path_size_cached(p) for p in will_fit)
                overflow_size_total = sum(self._get_path_size_cached(p) for p in overflow)
                confirm_message = self.strings.get(
                    "recycle_bin_mixed_prompt",
                    "Heads up: {fit} of {total} items would fit; {overflow} may be deleted.",
                ).format(
                    fit=len(will_fit),
                    total=len(items_to_delete),
                    overflow=len(overflow),
                    preview=preview_names,
                    fit_size=format_size(fit_size_total),
                    overflow_size=format_size(overflow_size_total),
                )
                # Push the mixed modal with three options and return early.
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
                    elif choice == "all":
                        self._start_deletion(items_to_delete, total_size)
                        return
                    else:
                        self._update_header(self.strings.get("delete_cancelled", "Acción cancelada"))
                        return

                self.push_screen(
                    MixedDeletionModal(confirm_message, self.strings),
                    handle_mixed,
                )
                return
            elif overflow and not will_fit:
                # None would fit: treat as overflow warn
                confirm_message = self.strings.get(
                    "recycle_bin_overflow_prompt",
                    "Warning: the Recycle Bin may not have enough space.",
                ).format(
                    available=format_size(max(available, 0)),
                    size=format_size(total_size),
                )
            elif will_fit and not overflow:
                # All fit, but maybe with a very small margin
                margin = max(available - total_size, 0)
                margin_threshold = 64 * 1024 * 1024  # 64 MiB safety margin
                logger.info(
                    "Recycle bin margin check (pre-confirm): available=%s total_size=%s margin=%s threshold=%s",
                    available,
                    total_size,
                    margin,
                    margin_threshold,
                )
                if margin <= margin_threshold:
                    confirm_message = self.strings.get(
                        "recycle_bin_marginal_prompt",
                        "Heads up: the Recycle Bin would have very little free space left ({margin}). Continue?",
                    ).format(margin=format_size(margin))
                else:
                    confirm_message = (
                        f"{self.strings['confirm_delete']}\n"
                        f"{len(items_to_delete)} · {format_size(total_size)}"
                    )
            else:
                confirm_message = (
                    f"{self.strings['confirm_delete']}\n"
                    f"{len(items_to_delete)} · {format_size(total_size)}"
                )
        else:
            # Fallback to coarse check (unknown space or API not available)
            overflow_warning = self._evaluate_recycle_bin_risk(items_to_delete, total_size)
            if overflow_warning:
                confirm_message = overflow_warning
            else:
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
            self._start_deletion(items_to_delete, total_size)
        
        self.push_screen(
            ConfirmDeletionModal(confirm_message, self.strings),
            handle_confirmation
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
        self.awaiting_overflow_confirmation = False
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

        if processed:
            # If we suspect some items were permanently deleted, try to infer which ones
            suspect_preview = ""
            if potential_bin_issue and suspected_count:
                # Heuristic: the largest N are more likely to have been skipped by the bin
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

if __name__ == "__main__":
    if len(sys.argv) > 1:
        lang_arg = sys.argv[2] if len(sys.argv) > 2 else "es-AR"
        app = DiskScoutApp(sys.argv[1], lang=lang_arg)
    else:
        app = DiskScoutApp(".")
    app.run()
