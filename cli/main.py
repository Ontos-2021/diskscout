import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scanner import DiskScanner
from core.utils import format_size, format_time
from core.snapshot import save_snapshot, load_snapshot, compare_snapshots

def main():
    parser = argparse.ArgumentParser(description="Disk Scout CLI")
    subparsers = parser.add_subparsers(dest='command')

    # scan
    scan_parser = subparsers.add_parser('scan', help='Scan directory')
    scan_parser.add_argument('path', help='Directory to scan')
    scan_parser.add_argument('--min-size', type=int, default=0, help='Minimum file size in bytes')
    scan_parser.add_argument('--json', action='store_true', help='Output as JSON')
    scan_parser.add_argument('--save', type=str, help='Save snapshot to file')

    # top
    top_parser = subparsers.add_parser('top', help='Show top files')
    top_parser.add_argument('path', help='Directory to scan')
    top_parser.add_argument('--top', type=int, default=20, help='Number of top files')
    top_parser.add_argument('--min-size', type=int, default=0)

    # export
    export_parser = subparsers.add_parser('export', help='Export scan results')
    export_parser.add_argument('path', help='Directory')
    export_parser.add_argument('--format', choices=['json', 'csv'], default='json')
    export_parser.add_argument('--output', type=str, help='Output file')

    # diff
    diff_parser = subparsers.add_parser('diff', help='Compare snapshots')
    diff_parser.add_argument('snap1', help='First snapshot')
    diff_parser.add_argument('snap2', help='Second snapshot')

    # tui
    tui_parser = subparsers.add_parser('tui', help='Launch TUI')
    tui_parser.add_argument('path', help='Directory to scan')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == 'scan':
        scanner = DiskScanner(min_size=args.min_size)
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
        scanner = DiskScanner(min_size=args.min_size)
        results = scanner.scan(args.path)
        for size, path in results['top_files'][:args.top]:
            print(f"{format_size(size)} {path}")

    elif args.command == 'export':
        scanner = DiskScanner()
        results = scanner.scan(args.path)
        if args.format == 'json':
            data = json.dumps(results, indent=2)
        elif args.format == 'csv':
            data = "Size,Path\n"
            for size, path in results['top_files']:
                data += f"{size},{path}\n"
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
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

    elif args.command == 'tui':
        from tui.app import DiskScoutApp
        app = DiskScoutApp(args.path)
        app.run()

if __name__ == '__main__':
    main()
