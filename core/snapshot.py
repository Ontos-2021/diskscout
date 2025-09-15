import json
import datetime
from pathlib import Path
from .utils import format_size

def save_snapshot(scan_results, root_path, output_path):
    """Save scan results to JSON snapshot."""
    now = datetime.datetime.now().isoformat()

    items = []
    # Add top children as dirs
    for name, size in scan_results['top_children'].items():
        path = str(Path(root_path) / name)
        items.append({"path": path, "type": "dir", "size": size, "mtime_ns": 0})  # mtime not collected yet

    # Add top files
    for size, path in scan_results['top_files']:
        items.append({"path": path, "type": "file", "size": size, "mtime_ns": 0})

    data = {
        "version": 1,
        "scanned_at": now,
        "root": str(root_path),
        "total_size": scan_results['total_size'],
        "items": items,
        "ext_sizes": scan_results['ext_sizes']
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def load_snapshot(path):
    """Load snapshot from JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def compare_snapshots(snap1, snap2):
    """Compare two snapshots."""
    diff_size = snap2['total_size'] - snap1['total_size']
    return {
        'size_diff': diff_size,
        'size_diff_formatted': format_size(diff_size),
        'snap1_total': format_size(snap1['total_size']),
        'snap2_total': format_size(snap2['total_size'])
    }
