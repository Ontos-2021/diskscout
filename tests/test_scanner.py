import json
from pathlib import Path

import core.scanner as scanner_module
from core.scanner import DiskScanner
from core.snapshot import save_snapshot


def write_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_scan_applies_max_depth_and_aggregates_immediate_children(tmp_path):
    write_file(tmp_path / "root.txt", 3)
    write_file(tmp_path / "a" / "direct.txt", 5)
    write_file(tmp_path / "a" / "b" / "deep.txt", 10)

    result_depth_0 = DiskScanner(max_depth=0).scan(tmp_path, top_n=None)
    assert result_depth_0["file_count"] == 1
    assert result_depth_0["top_children"]["a"] == 0
    assert result_depth_0["immediate_children"]["root.txt"]["size"] == 3

    result_depth_1 = DiskScanner(max_depth=1).scan(tmp_path, top_n=None)
    assert result_depth_1["file_count"] == 2
    assert result_depth_1["top_children"]["a"] == 5

    result_depth_2 = DiskScanner(max_depth=2).scan(tmp_path, top_n=None)
    assert result_depth_2["file_count"] == 3
    assert result_depth_2["top_children"]["a"] == 15


def test_scan_prunes_ignored_paths(tmp_path):
    write_file(tmp_path / "keep.txt", 4)
    write_file(tmp_path / "skip" / "nested.txt", 8)

    result = DiskScanner(ignore_paths={"skip"}).scan(tmp_path, top_n=None)

    assert result["file_count"] == 1
    assert result["total_size"] == 4
    assert "skip" not in result["immediate_children"]


def test_scan_ignores_common_dev_artifacts_by_default(tmp_path):
    write_file(tmp_path / "visible.txt", 3)
    write_file(tmp_path / "venv" / "ignored.txt", 10)
    write_file(tmp_path / ".git" / "config", 7)

    result = DiskScanner().scan(tmp_path, top_n=None)

    assert result["file_count"] == 1
    assert result["total_size"] == 3
    assert "venv" not in result["immediate_children"]
    assert ".git" not in result["immediate_children"]


def test_scan_can_disable_default_ignores(tmp_path):
    write_file(tmp_path / "visible.txt", 3)
    write_file(tmp_path / "venv" / "included.txt", 10)

    result = DiskScanner(use_default_ignores=False).scan(tmp_path, top_n=None)

    assert result["file_count"] == 2
    assert result["total_size"] == 13
    assert result["top_children"]["venv"] == 10


def test_snapshot_uses_recursive_immediate_child_sizes(tmp_path):
    write_file(tmp_path / "dir" / "nested" / "deep.txt", 12)
    scan_results = DiskScanner().scan(tmp_path, top_n=None)
    output_path = tmp_path / "snapshot.json"

    save_snapshot(scan_results, tmp_path, output_path)

    snapshot = json.loads(output_path.read_text(encoding="utf-8"))
    dir_item = next(item for item in snapshot["items"] if item["type"] == "dir")
    assert dir_item["path"].endswith("dir")
    assert dir_item["size"] == 12


def test_scan_tolerates_paths_that_fail_to_resolve(monkeypatch, tmp_path):
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    write_file(restricted / "data.txt", 5)

    original_resolve = Path.resolve

    def fake_resolve(self, *args, **kwargs):
        if self.name == "restricted":
            raise PermissionError("denied")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(scanner_module.Path, "resolve", fake_resolve)

    result = DiskScanner().scan(tmp_path, top_n=None)

    assert result["file_count"] == 1
    assert result["total_size"] == 5