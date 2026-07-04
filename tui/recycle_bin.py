import os
from pathlib import Path
from typing import Optional, Tuple

from core.scanner import DiskScanner
from core.utils import format_size
from tui.logging_config import logger

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


class RecycleBinMixin:
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

    def _group_paths_by_drive(self, paths: list[Path]) -> dict[str, list[Path]]:
        grouped: dict[str, list[Path]] = {}
        for path in paths:
            drive = path.drive or os.path.splitdrive(str(path))[0]
            drive_key = drive.upper()
            grouped.setdefault(drive_key, []).append(path)
        return grouped

    def _query_recycle_bin_multi(self, paths: list[Path]) -> Optional[Tuple[int, int]]:
        """Return aggregated (item_count, total_size) across all drives involved in paths."""
        if os.name != "nt" or SHQUERYRBINFO is None or ctypes is None:
            return None
        if not paths:
            return self._query_recycle_bin()
        total_items = 0
        total_size = 0
        for drive_paths in self._group_paths_by_drive(paths).values():
            try:
                info = SHQUERYRBINFO()
                info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
                drive = drive_paths[0].drive or os.path.splitdrive(str(drive_paths[0]))[0]
                query_path = f"{drive.rstrip(':')}:\\"
                result = ctypes.windll.shell32.SHQueryRecycleBinW(
                    query_path,
                    ctypes.byref(info),
                )
                if result != 0:
                    return None
                total_items += int(info.i64NumItems)
                total_size += int(info.i64Size)
            except Exception:
                return None
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
        r"""Return the volume GUID path for the drive of 'path', e.g. \?\Volume{GUID}\."""
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
            return buffer.value.rstrip("\\").lower()
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
            try:
                nuke_on_delete, _ = winreg.QueryValueEx(key_handle, "NukeOnDelete")
                if int(nuke_on_delete) == 1:
                    logger.info("Recycle Bin (%s) configured to delete immediately for %s", source_label, drive_root)
                    return 0
            except FileNotFoundError:
                pass

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
            return found_limit

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
                            def _match_and_read_from(handle) -> Optional[int]:
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

                            limit = _match_and_read_from(bin_key)
                            if limit is not None:
                                return limit

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
        available_total = 0
        for drive_paths in self._group_paths_by_drive(paths).values():
            bin_stats = self._query_recycle_bin(drive_paths[0])
            if bin_stats is None:
                return self.strings.get("recycle_bin_overflow_prompt_unknown")
            _, current_usage = bin_stats
            limit_bytes = self._get_recycle_bin_limit_bytes(drive_paths[0], current_usage)
            if limit_bytes is None:
                return self.strings.get("recycle_bin_overflow_prompt_unknown")
            available_total += max(limit_bytes - current_usage, 0)
        if total_size > available_total:
            return self.strings.get(
                "recycle_bin_overflow_prompt",
                "Warning: the Recycle Bin may not have enough space.",
            ).format(
                available=format_size(available_total),
                size=format_size(total_size),
            )
        return None

    def _predict_recycle_bin_fit(
        self,
        paths: list[Path],
    ) -> Optional[dict[str, object]]:
        """Predict which paths would fit in the Recycle Bin quota across all drives."""
        if os.name != "nt" or not paths:
            return None
        size_map: dict[Path, int] = {}
        for item in self.current_items:
            size_map[item['path'].resolve()] = int(item['size'])

        def get_size(p: Path) -> int:
            rp = p.resolve()
            if rp in size_map:
                return size_map[rp]
            try:
                if rp.is_dir():
                    return int(
                        DiskScanner(
                            include_ext=self.include_ext,
                            exclude_ext=self.exclude_ext,
                            ignore_paths=self.ignore_paths,
                            max_depth=self.max_depth,
                            follow_symlinks=self.follow_symlinks,
                            use_default_ignores=self.use_default_ignores,
                        ).scan(str(rp), top_n=0)['total_size']
                    )
                return int(rp.stat().st_size)
            except Exception:
                return 0

        will_fit: list[Path] = []
        overflow: list[Path] = []
        available_total = 0
        min_margin: Optional[int] = None

        for drive_paths in self._group_paths_by_drive(paths).values():
            bin_stats = self._query_recycle_bin(drive_paths[0])
            if bin_stats is None:
                return None
            _, current_usage = bin_stats
            limit_bytes = self._get_recycle_bin_limit_bytes(drive_paths[0], current_usage)
            if limit_bytes is None:
                return None
            available = max(limit_bytes - current_usage, 0)
            available_total += available
            logger.info(
                "Recycle bin fit prediction: drive=%s current_usage=%s limit=%s available=%s items=%s",
                drive_paths[0].drive,
                current_usage,
                limit_bytes,
                available,
                len(drive_paths),
            )

            remaining = available
            for path in sorted(drive_paths, key=get_size):
                size = get_size(path)
                if size <= remaining:
                    will_fit.append(path)
                    remaining -= size
                else:
                    overflow.append(path)

            if min_margin is None or remaining < min_margin:
                min_margin = remaining

        return {
            "will_fit": will_fit,
            "overflow": overflow,
            "available_total": available_total,
            "min_margin": 0 if min_margin is None else min_margin,
        }

    def _get_path_size_cached(self, p: Path) -> int:
        """Return size for a path using current_items cache, falling back to stat/scan."""
        rp = p.resolve()
        for item in self.current_items:
            if item['path'].resolve() == rp:
                return int(item['size'])
        try:
            if rp.is_dir():
                return int(
                    DiskScanner(
                        include_ext=self.include_ext,
                        exclude_ext=self.exclude_ext,
                        ignore_paths=self.ignore_paths,
                        max_depth=self.max_depth,
                        follow_symlinks=self.follow_symlinks,
                        use_default_ignores=self.use_default_ignores,
                    ).scan(str(rp), top_n=0)['total_size']
                )
            return int(rp.stat().st_size)
        except Exception:
            return 0
