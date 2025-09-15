import json
import os
from pathlib import Path

def format_size(size_bytes, base=1024):
    """Format size in human readable format."""
    if size_bytes == 0:
        return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    size = float(size_bytes)
    unit_index = 0
    while size >= base and unit_index < len(units) - 1:
        size /= base
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"

def format_time(seconds):
    """Format time in seconds to human readable."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"

def draw_bar(size, max_size, width=20):
    """Draw a progress bar."""
    if max_size == 0:
        return '█' * width
    filled = int((size / max_size) * width)
    return '█' * filled + ' ' * (width - filled)

def get_extension(path):
    """Get file extension."""
    return Path(path).suffix.lower()

def load_strings(lang='es-AR'):
    """Load strings for given language."""
    strings_path = Path(__file__).parent.parent / 'assets' / 'strings' / f'{lang}.json'
    if strings_path.exists():
        with open(strings_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # Fallback to en-US
        fallback_path = Path(__file__).parent.parent / 'assets' / 'strings' / 'en-US.json'
        with open(fallback_path, 'r', encoding='utf-8') as f:
            return json.load(f)

def get_home_dir():
    """Get user's home directory."""
    return Path.home()

def get_desktop_dir():
    """Get desktop directory."""
    return get_home_dir() / 'Desktop'

def get_documents_dir():
    """Get documents directory."""
    return get_home_dir() / 'Documents'

def get_downloads_dir():
    """Get downloads directory."""
    return get_home_dir() / 'Downloads'
