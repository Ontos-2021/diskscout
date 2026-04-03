from pathlib import Path
from types import SimpleNamespace

import tui.app as app_module


def test_collect_items_uses_a_single_scan_result(monkeypatch, tmp_path):
    class FakeScanner:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def scan(self, path, progress_callback=None, top_n=20):
            FakeScanner.calls += 1
            assert Path(path) == tmp_path
            assert top_n == 0
            return {
                "total_size": 15,
                "immediate_children": {
                    "folder": {
                        "path": str(tmp_path / "folder"),
                        "size": 10,
                        "is_dir": True,
                    },
                    "file.txt": {
                        "path": str(tmp_path / "file.txt"),
                        "size": 5,
                        "is_dir": False,
                    },
                },
            }

    monkeypatch.setattr(app_module, "DiskScanner", FakeScanner)

    app = app_module.DiskScoutApp(str(tmp_path))
    items, total_size, error_count = app._collect_items(tmp_path)

    assert FakeScanner.calls == 1
    assert total_size == 15
    assert error_count == 0
    assert {(item["path"].name, item["size"], item["is_dir"]) for item in items} == {
        ("folder", 10, True),
        ("file.txt", 5, False),
    }


def test_collect_items_returns_partial_error_count(monkeypatch, tmp_path):
    class FakeScanner:
        def __init__(self, *args, **kwargs):
            pass

        def scan(self, path, progress_callback=None, top_n=20):
            return {
                "total_size": 15,
                "immediate_children": {
                    "folder": {
                        "path": str(tmp_path / "folder"),
                        "size": 10,
                        "is_dir": True,
                    },
                },
                "errors": ["permission denied"],
            }

    monkeypatch.setattr(app_module, "DiskScanner", FakeScanner)

    app = app_module.DiskScoutApp(str(tmp_path))
    items, total_size, error_count = app._collect_items(tmp_path)

    assert total_size == 15
    assert error_count == 1
    assert items[0]["path"].name == "folder"


def test_apply_scan_results_shows_partial_permissions_warning(monkeypatch, tmp_path):
    app = app_module.DiskScoutApp(str(tmp_path))

    headers = []
    monkeypatch.setattr(app, "refresh_list", lambda: None)
    monkeypatch.setattr(app, "_update_header", lambda message: headers.append(message))

    app._apply_scan_results(
        tmp_path,
        [{"path": tmp_path / "folder", "size": 10, "is_dir": True}],
        10,
        error_count=2,
    )

    assert app.strings["partial_permissions_warning"] in headers[-1]


def test_scan_worker_forwards_partial_error_count(monkeypatch, tmp_path):
    app = app_module.DiskScoutApp(str(tmp_path))

    calls = []
    monkeypatch.setattr(
        app,
        "_collect_items",
        lambda path: ([{"path": tmp_path / "folder", "size": 10, "is_dir": True}], 10, 2),
    )
    monkeypatch.setattr(
        app,
        "call_from_thread",
        lambda callback, *args: calls.append((callback, args)),
    )

    app._scan_worker(tmp_path)

    assert len(calls) == 1
    callback, args = calls[0]
    assert callback == app._apply_scan_results
    assert args == (
        tmp_path,
        [{"path": tmp_path / "folder", "size": 10, "is_dir": True}],
        10,
        2,
    )


def test_action_show_actions_schedules_confirmation_in_background(monkeypatch, tmp_path):
    created_coroutines = []

    class DummyTask:
        def done(self):
            return False

        def cancel(self):
            return None

    def fake_create_task(coro):
        created_coroutines.append(coro)
        return DummyTask()

    app = app_module.DiskScoutApp(str(tmp_path))
    app.current_items = [
        {"path": tmp_path / "folder", "size": 10, "is_dir": True},
    ]
    app.selected_indices = {0}

    pushed = []
    headers = []
    monkeypatch.setattr(app_module, "send2trash", object())
    monkeypatch.setattr(app_module.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(app, "push_screen", lambda *args, **kwargs: pushed.append((args, kwargs)))
    monkeypatch.setattr(app, "_update_header", lambda message: headers.append(message))

    app.action_show_actions()

    assert app.preparing_delete_confirmation is True
    assert len(created_coroutines) == 1
    assert not pushed
    assert headers[-1] == app.strings["preparing_delete_confirmation"]

    created_coroutines[0].close()


def test_action_show_actions_without_selection_shows_feedback(monkeypatch, tmp_path):
    app = app_module.DiskScoutApp(str(tmp_path))

    headers = []
    notifications = []
    monkeypatch.setattr(app, "_update_header", lambda message: headers.append(message))
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, severity="information", timeout=0: notifications.append(
            (message, severity, timeout)
        ),
    )

    app.action_show_actions()

    assert headers[-1] == app.strings["select_items_first"]
    assert notifications[-1] == (app.strings["select_items_first"], "warning", 4)


def test_action_open_selected_enters_highlighted_directory(monkeypatch, tmp_path):
    app = app_module.DiskScoutApp(str(tmp_path))
    folder = tmp_path / "folder"
    app.current_items = [
        {"path": folder, "size": 10, "is_dir": True},
    ]

    class FakeListView:
        index = 0

    scanned = []
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: FakeListView())
    monkeypatch.setattr(app, "scan_directory", lambda path: scanned.append(path))

    app.action_open_selected()

    assert app.current_path == folder
    assert app.path_history == [tmp_path]
    assert scanned == [folder]


def test_scan_directory_cancels_previous_worker_using_is_finished(monkeypatch, tmp_path):
    app = app_module.DiskScoutApp(str(tmp_path))

    class FakeWorker:
        is_finished = False

        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    class FakeListView:
        def __init__(self):
            self.cleared = False

        def clear(self):
            self.cleared = True

    fake_worker = FakeWorker()
    fake_list = FakeListView()
    created = []

    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: fake_list)
    monkeypatch.setattr(app, "_update_header", lambda message: None)
    monkeypatch.setattr(
        app,
        "run_worker",
        lambda *args, **kwargs: created.append((args, kwargs)) or "new-worker",
    )

    app.scan_worker = fake_worker
    app.scan_directory(tmp_path / "child")

    assert fake_worker.cancelled is True
    assert fake_list.cleared is True
    assert app.scan_worker == "new-worker"
    assert len(created) == 1


def test_action_open_selected_on_file_shows_feedback(monkeypatch, tmp_path):
    app = app_module.DiskScoutApp(str(tmp_path))
    app.current_items = [
        {"path": tmp_path / "file.txt", "size": 5, "is_dir": False},
    ]

    class FakeListView:
        index = 0

    headers = []
    notifications = []
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: FakeListView())
    monkeypatch.setattr(app, "_update_header", lambda message: headers.append(message))
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, severity="information", timeout=0: notifications.append(
            (message, severity, timeout)
        ),
    )

    app.action_open_selected()

    assert headers[-1] == app.strings["selected_item_not_folder"]
    assert notifications[-1] == (app.strings["selected_item_not_folder"], "warning", 4)


def test_action_go_back_without_history_shows_feedback(monkeypatch, tmp_path):
    app = app_module.DiskScoutApp(str(tmp_path))

    headers = []
    notifications = []
    monkeypatch.setattr(app, "_update_header", lambda message: headers.append(message))
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, severity="information", timeout=0: notifications.append(
            (message, severity, timeout)
        ),
    )

    app.action_go_back()

    assert headers[-1] == app.strings["already_at_root"]
    assert notifications[-1] == (app.strings["already_at_root"], "information", 4)


def test_query_recycle_bin_multi_aggregates_per_drive(monkeypatch, tmp_path):
    class FakeInfo:
        def __init__(self):
            self.cbSize = 0
            self.i64NumItems = 0
            self.i64Size = 0

    recycle_bin_by_drive = {
        "C:\\": (2, 100),
        "D:\\": (3, 250),
    }

    def fake_query_recycle_bin(query_path, info):
        items, size = recycle_bin_by_drive[query_path]
        info.i64NumItems = items
        info.i64Size = size
        return 0

    fake_ctypes = SimpleNamespace(
        sizeof=lambda _: 1,
        byref=lambda value: value,
        windll=SimpleNamespace(
            shell32=SimpleNamespace(SHQueryRecycleBinW=fake_query_recycle_bin)
        ),
    )

    monkeypatch.setattr(app_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(app_module, "ctypes", fake_ctypes)
    monkeypatch.setattr(app_module, "SHQUERYRBINFO", FakeInfo)

    app = app_module.DiskScoutApp(str(tmp_path))
    result = app._query_recycle_bin_multi([
        Path("C:/tmp/a.txt"),
        Path("D:/tmp/b.txt"),
        Path("C:/tmp/c.txt"),
    ])

    assert result == (5, 350)


def test_get_recycle_bin_limit_reads_nested_bins_registry(monkeypatch, tmp_path):
    class FakeRegistryKey:
        def __init__(self, registry, path):
            self.registry = registry
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeWinReg:
        HKEY_CURRENT_USER = "HKCU"

        def __init__(self):
            self.values = {
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Bins": {},
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Bins\UserSid": {},
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Bins\UserSid\VolumeKey": {
                    "Volume": "\\\\?\\Volume{abc}",
                    "MaxCapacity": 1,
                },
            }
            self.children = {
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Bins": ["UserSid"],
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Bins\UserSid": ["VolumeKey"],
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Bins\UserSid\VolumeKey": [],
            }

        def OpenKey(self, root, subkey):
            if isinstance(root, FakeRegistryKey):
                path = f"{root.path}\\{subkey}"
            else:
                path = subkey
            if path not in self.values:
                raise FileNotFoundError(path)
            return FakeRegistryKey(self, path)

        def EnumKey(self, key, index):
            children = self.children.get(key.path, [])
            if index >= len(children):
                raise OSError("No more keys")
            return children[index]

        def QueryValueEx(self, key, value_name):
            values = self.values.get(key.path, {})
            if value_name not in values:
                raise FileNotFoundError(value_name)
            return values[value_name], None

    monkeypatch.setattr(app_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(app_module, "winreg", FakeWinReg())

    app = app_module.DiskScoutApp(str(tmp_path))
    monkeypatch.setattr(app, "_get_volume_guid_for_path", lambda path: "\\\\?\\volume{abc}")
    monkeypatch.setattr(app, "_get_drive_total_bytes", lambda path: 50 * 1024 * 1024)

    limit_bytes = app._get_recycle_bin_limit_bytes(Path("C:/tmp/file.txt"), current_usage=0)

    assert limit_bytes == 1024 * 1024


def test_get_recycle_bin_limit_respects_nuke_on_delete(monkeypatch, tmp_path):
    class FakeRegistryKey:
        def __init__(self, registry, path):
            self.registry = registry
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeWinReg:
        HKEY_CURRENT_USER = "HKCU"

        def __init__(self):
            self.values = {
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume": {},
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\VolumeKey": {
                    "Volume": "\\\\?\\Volume{abc}",
                    "NukeOnDelete": 1,
                },
            }
            self.children = {
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume": ["VolumeKey"],
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\VolumeKey": [],
            }

        def OpenKey(self, root, subkey):
            if isinstance(root, FakeRegistryKey):
                path = f"{root.path}\\{subkey}"
            else:
                path = subkey
            if path not in self.values:
                raise FileNotFoundError(path)
            return FakeRegistryKey(self, path)

        def EnumKey(self, key, index):
            children = self.children.get(key.path, [])
            if index >= len(children):
                raise OSError("No more keys")
            return children[index]

        def QueryValueEx(self, key, value_name):
            values = self.values.get(key.path, {})
            if value_name not in values:
                raise FileNotFoundError(value_name)
            return values[value_name], None

    monkeypatch.setattr(app_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(app_module, "winreg", FakeWinReg())

    app = app_module.DiskScoutApp(str(tmp_path))
    monkeypatch.setattr(app, "_get_volume_guid_for_path", lambda path: "\\\\?\\volume{abc}")

    assert app._get_recycle_bin_limit_bytes(Path("C:/tmp/file.txt"), current_usage=0) == 0


def test_get_recycle_bin_limit_uses_percent_fallback(monkeypatch, tmp_path):
    class FakeRegistryKey:
        def __init__(self, registry, path):
            self.registry = registry
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeWinReg:
        HKEY_CURRENT_USER = "HKCU"

        def __init__(self):
            self.values = {
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume": {},
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\VolumeKey": {
                    "Volume": "\\\\?\\Volume{abc}",
                    "Percent": 10,
                },
            }
            self.children = {
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume": ["VolumeKey"],
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\VolumeKey": [],
            }

        def OpenKey(self, root, subkey):
            if isinstance(root, FakeRegistryKey):
                path = f"{root.path}\\{subkey}"
            else:
                path = subkey
            if path not in self.values:
                raise FileNotFoundError(path)
            return FakeRegistryKey(self, path)

        def EnumKey(self, key, index):
            children = self.children.get(key.path, [])
            if index >= len(children):
                raise OSError("No more keys")
            return children[index]

        def QueryValueEx(self, key, value_name):
            values = self.values.get(key.path, {})
            if value_name not in values:
                raise FileNotFoundError(value_name)
            return values[value_name], None

    monkeypatch.setattr(app_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(app_module, "winreg", FakeWinReg())

    app = app_module.DiskScoutApp(str(tmp_path))
    monkeypatch.setattr(app, "_get_volume_guid_for_path", lambda path: "\\\\?\\volume{abc}")
    monkeypatch.setattr(app, "_get_drive_total_bytes", lambda path: 200)

    assert app._get_recycle_bin_limit_bytes(Path("C:/tmp/file.txt"), current_usage=0) == 20


def test_predict_recycle_bin_fit_handles_multiple_drives(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module.os, "name", "nt", raising=False)
    app = app_module.DiskScoutApp(str(tmp_path))
    app.current_items = [
        {"path": Path("C:/tmp/big.txt"), "size": 8, "is_dir": False},
        {"path": Path("C:/tmp/small.txt"), "size": 3, "is_dir": False},
        {"path": Path("D:/tmp/other.txt"), "size": 4, "is_dir": False},
    ]

    monkeypatch.setattr(
        app,
        "_query_recycle_bin",
        lambda path: (0, {"C:": 2, "D:": 1}[path.drive]),
    )
    monkeypatch.setattr(
        app,
        "_get_recycle_bin_limit_bytes",
        lambda path, usage: {"C:": 10, "D:": 10}[path.drive],
    )

    prediction = app._predict_recycle_bin_fit([
        Path("C:/tmp/big.txt"),
        Path("C:/tmp/small.txt"),
        Path("D:/tmp/other.txt"),
    ])

    assert prediction is not None
    assert [path.name for path in prediction["will_fit"]] == ["small.txt", "other.txt"]
    assert [path.name for path in prediction["overflow"]] == ["big.txt"]
    assert prediction["available_total"] == 17
    assert prediction["min_margin"] == 5