import json
import os
from pathlib import Path


DEFAULT_APP_CONFIG = {
    "ignore_paths": [],
    "use_default_ignores": True,
}

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


def get_config_dir():
    """Return the per-user configuration directory for DiskScout."""
    if os.name == 'nt':
        appdata = os.environ.get('APPDATA')
        if appdata:
            return Path(appdata) / 'DiskScout'
    return get_home_dir() / '.diskscout'


def get_config_path():
    """Return the per-user configuration file path for DiskScout."""
    return get_config_dir() / 'config.json'


def load_app_config():
    """Load persistent user configuration, falling back to defaults."""
    config_path = get_config_path()
    if not config_path.exists():
        return dict(DEFAULT_APP_CONFIG)
    with open(config_path, 'r', encoding='utf-8') as f:
        loaded = json.load(f)

    config = dict(DEFAULT_APP_CONFIG)
    if isinstance(loaded, dict):
        ignore_paths = loaded.get('ignore_paths', DEFAULT_APP_CONFIG['ignore_paths'])
        if isinstance(ignore_paths, list):
            config['ignore_paths'] = [str(path) for path in ignore_paths if str(path).strip()]
        use_default_ignores = loaded.get(
            'use_default_ignores',
            DEFAULT_APP_CONFIG['use_default_ignores'],
        )
        config['use_default_ignores'] = bool(use_default_ignores)
    return config


def save_app_config(config):
    """Persist user configuration to disk."""
    merged = dict(DEFAULT_APP_CONFIG)
    merged.update(config)
    merged['ignore_paths'] = [
        str(path) for path in merged.get('ignore_paths', []) if str(path).strip()
    ]
    merged['use_default_ignores'] = bool(
        merged.get('use_default_ignores', DEFAULT_APP_CONFIG['use_default_ignores'])
    )

    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    return config_path


def reset_app_config():
    """Delete the persistent user configuration file if present."""
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()
        return True
    return False

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
