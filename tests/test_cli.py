import csv
import json
import os
import sys

from cli.main import main


def test_export_csv_quotes_paths_and_includes_all_files(tmp_path, monkeypatch):
    for index in range(25):
        (tmp_path / f"file_{index}.txt").write_text("x", encoding="utf-8")
    (tmp_path / "comma,name.txt").write_text("x", encoding="utf-8")

    output_path = tmp_path / "export.csv"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diskscout",
            "export",
            str(tmp_path),
            "--format",
            "csv",
            "--output",
            str(output_path),
        ],
    )

    main()

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == ["Size", "Path"]
    exported_paths = {row[1] for row in rows[1:]}
    assert len(exported_paths) == 26
    assert str(tmp_path / "comma,name.txt") in exported_paths


def test_config_set_show_and_reset_persists_user_preferences(tmp_path, monkeypatch, capsys):
    appdata_dir = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata_dir))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diskscout",
            "config",
            "set",
            "--ignore-path",
            "build",
            "--ignore-path",
            "dist",
            "--use-default-ignores",
            "false",
        ],
    )
    main()
    capsys.readouterr()

    config_path = appdata_dir / "DiskScout" / "config.json"
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored == {
        "ignore_paths": ["build", "dist"],
        "use_default_ignores": False,
    }

    monkeypatch.setattr(sys, "argv", ["diskscout", "config", "show"])
    main()
    output = capsys.readouterr().out
    shown = json.loads(output)
    assert shown["ignore_paths"] == ["build", "dist"]
    assert shown["use_default_ignores"] is False
    assert shown["config_path"].endswith(os.path.join("DiskScout", "config.json"))

    monkeypatch.setattr(sys, "argv", ["diskscout", "config", "reset"])
    main()
    assert not config_path.exists()


def test_scan_uses_persisted_config_and_cli_overrides(tmp_path, monkeypatch, capsys):
    appdata_dir = tmp_path / "Profile" / "AppData" / "Roaming"
    scan_root = tmp_path / "scan-root"
    scan_root.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata_dir))
    config_path = appdata_dir / "DiskScout" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"ignore_paths": ["build"], "use_default_ignores": True}),
        encoding="utf-8",
    )

    (scan_root / "kept.txt").write_text("x", encoding="utf-8")
    (scan_root / "build" / "ignored.txt").parent.mkdir(parents=True, exist_ok=True)
    (scan_root / "build" / "ignored.txt").write_text("x", encoding="utf-8")
    (scan_root / "dist" / "also_ignored.txt").parent.mkdir(parents=True, exist_ok=True)
    (scan_root / "dist" / "also_ignored.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diskscout",
            "scan",
            str(scan_root),
            "--json",
            "--ignore-path",
            "dist",
        ],
    )
    main()

    result = json.loads(capsys.readouterr().out)
    assert result["file_count"] == 1
    assert "build" not in result["immediate_children"]
    assert "dist" not in result["immediate_children"]