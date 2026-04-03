import argparse
import csv
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scanner import DiskScanner
from core.utils import (
    format_size,
    format_time,
    get_config_path,
    load_app_config,
    reset_app_config,
    save_app_config,
)
from core.snapshot import save_snapshot, load_snapshot, compare_snapshots


def add_scan_filters(parser):
    parser.add_argument(
        '--ignore-path',
        action='append',
        default=[],
        help='Relative path segment or path to ignore. Repeat for multiple values.',
    )
    parser.add_argument(
        '--no-default-ignores',
        action='store_true',
        help='Include common development artifacts such as .git, venv and __pycache__.',
    )


def add_config_arguments(parser):
    parser.add_argument(
        '--ignore-path',
        action='append',
        default=None,
        help='Persist additional ignore paths. Repeat for multiple values.',
    )
    parser.add_argument(
        '--use-default-ignores',
        choices=['true', 'false'],
        help='Persist whether common development artifacts should be ignored by default.',
    )


def resolve_scan_options(args):
    config = load_app_config()
    ignore_paths = list(config.get('ignore_paths', []))
    if getattr(args, 'ignore_path', None):
        ignore_paths.extend(args.ignore_path)

    use_default_ignores = bool(config.get('use_default_ignores', True))
    if getattr(args, 'no_default_ignores', False):
        use_default_ignores = False

    # Preserve order while removing duplicates.
    seen = set()
    unique_ignore_paths = []
    for path in ignore_paths:
        normalized = str(path).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_ignore_paths.append(normalized)

    return {
        'ignore_paths': unique_ignore_paths,
        'use_default_ignores': use_default_ignores,
    }


def build_scanner(args):
    options = resolve_scan_options(args)
    return DiskScanner(
        min_size=getattr(args, 'min_size', 0),
        ignore_paths=options['ignore_paths'],
        use_default_ignores=options['use_default_ignores'],
    )


def handle_config_command(args):
    if args.config_action == 'show':
        config = load_app_config()
        config['config_path'] = str(get_config_path())
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return

    if args.config_action == 'set':
        config = load_app_config()
        if args.ignore_path is not None:
            config['ignore_paths'] = [
                str(path) for path in args.ignore_path if str(path).strip()
            ]
        if args.use_default_ignores is not None:
            config['use_default_ignores'] = args.use_default_ignores == 'true'
        path = save_app_config(config)
        print(f"Saved config to {path}")
        return

    if args.config_action == 'reset':
        removed = reset_app_config()
        if removed:
            print(f"Removed config at {get_config_path()}")
        else:
            print("No config file to remove")
        return

def main():
    parser = argparse.ArgumentParser(description="Disk Scout CLI")
    subparsers = parser.add_subparsers(dest='command')

    # scan
    scan_parser = subparsers.add_parser('scan', help='Scan directory')
    scan_parser.add_argument('path', help='Directory to scan')
    scan_parser.add_argument('--min-size', type=int, default=0, help='Minimum file size in bytes')
    scan_parser.add_argument('--json', action='store_true', help='Output as JSON')
    scan_parser.add_argument('--save', type=str, help='Save snapshot to file')
    add_scan_filters(scan_parser)

    # top
    top_parser = subparsers.add_parser('top', help='Show top files')
    top_parser.add_argument('path', help='Directory to scan')
    top_parser.add_argument('--top', type=int, default=20, help='Number of top files')
    top_parser.add_argument('--min-size', type=int, default=0)
    add_scan_filters(top_parser)

    # export
    export_parser = subparsers.add_parser('export', help='Export scan results')
    export_parser.add_argument('path', help='Directory')
    export_parser.add_argument('--format', choices=['json', 'csv'], default='json')
    export_parser.add_argument('--output', type=str, help='Output file')
    add_scan_filters(export_parser)

    # diff
    diff_parser = subparsers.add_parser('diff', help='Compare snapshots')
    diff_parser.add_argument('snap1', help='First snapshot')
    diff_parser.add_argument('snap2', help='Second snapshot')

    # config
    config_parser = subparsers.add_parser('config', help='Manage persistent user configuration')
    config_subparsers = config_parser.add_subparsers(dest='config_action')
    config_subparsers.required = True

    config_subparsers.add_parser('show', help='Show the current persisted configuration')
    config_set_parser = config_subparsers.add_parser('set', help='Persist scan defaults for future runs')
    add_config_arguments(config_set_parser)
    config_subparsers.add_parser('reset', help='Remove the persisted configuration file')

    # tui
    tui_parser = subparsers.add_parser('tui', help='Launch TUI')
    tui_parser.add_argument('path', help='Directory to scan')
    tui_parser.add_argument('--lang', default='es-AR', help='Language code (e.g. es-AR, en-US)')
    add_scan_filters(tui_parser)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == 'scan':
        scanner = build_scanner(args)
        results = scanner.scan(args.path)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Total size: {format_size(results['total_size'])}")
            print(f"Files: {results['file_count']}")
            print(f"Scan time: {format_time(results['scan_time'])}")
            print("Top files:")
            for size, path in results['top_files'][:10]:
                print(f"  {format_size(size)} {path}")
        if args.save:
            save_snapshot(results, args.path, args.save)

    elif args.command == 'top':
        scanner = build_scanner(args)
        results = scanner.scan(args.path, top_n=args.top)
        for size, path in results['top_files'][:args.top]:
            print(f"{format_size(size)} {path}")

    elif args.command == 'export':
        scanner = build_scanner(args)
        results = scanner.scan(args.path, top_n=None)
        if args.format == 'json':
            data = json.dumps(results, indent=2, ensure_ascii=False)
        elif args.format == 'csv':
            from io import StringIO

            buffer = StringIO(newline='')
            writer = csv.writer(buffer)
            writer.writerow(["Size", "Path"])
            for size, path in results['top_files']:
                writer.writerow([size, path])
            data = buffer.getvalue()
        if args.output:
            newline = '' if args.format == 'csv' else None
            with open(args.output, 'w', encoding='utf-8', newline=newline) as f:
                f.write(data)
        else:
            print(data)

    elif args.command == 'diff':
        snap1 = load_snapshot(args.snap1)
        snap2 = load_snapshot(args.snap2)
        comp = compare_snapshots(snap1, snap2)
        print(f"Size difference: {comp['size_diff_formatted']}")
        print(f"Snap1 total: {comp['snap1_total']}")
        print(f"Snap2 total: {comp['snap2_total']}")

    elif args.command == 'config':
        handle_config_command(args)

    elif args.command == 'tui':
        from tui.app import DiskScoutApp
        options = resolve_scan_options(args)
        app = DiskScoutApp(
            args.path,
            lang=args.lang,
            ignore_paths=options['ignore_paths'],
            use_default_ignores=options['use_default_ignores'],
        )
        app.run()

if __name__ == '__main__':
    main()
