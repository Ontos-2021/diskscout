import heapq
import os
import time
from collections import Counter
from pathlib import Path


DEFAULT_IGNORE_PATHS = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "venv",
})

class DiskScanner:
    def __init__(
        self,
        min_size=0,
        include_ext=None,
        exclude_ext=None,
        ignore_paths=None,
        max_depth=None,
        follow_symlinks=False,
        use_default_ignores=True,
    ):
        self.min_size = min_size
        self.include_ext = set(include_ext) if include_ext else None
        self.exclude_ext = set(exclude_ext) if exclude_ext else None
        configured_ignores = set(ignore_paths) if ignore_paths else set()
        if use_default_ignores:
            configured_ignores.update(DEFAULT_IGNORE_PATHS)
        self.ignore_paths = {
            str(path).replace("\\", "/").strip("/").lower()
            for path in configured_ignores
            if str(path).strip()
        }
        self.max_depth = max_depth
        self.follow_symlinks = follow_symlinks
        self.use_default_ignores = use_default_ignores

    def scan(self, root_path, progress_callback=None, top_n=20):
        root_path = Path(root_path).resolve()
        if not root_path.exists():
            raise ValueError(f"Path does not exist: {root_path}")

        total_size = 0
        file_count = 0
        dir_count = 0
        errors = []
        ext_sizes = Counter()
        top_files = []
        immediate_children = {}
        start_time = time.time()
        processed = 0

        def get_relative_parts(path_obj):
            try:
                resolved_path = path_obj.resolve()
            except (OSError, PermissionError, RuntimeError):
                resolved_path = path_obj
            try:
                return [
                    part.lower()
                    for part in resolved_path.relative_to(root_path).parts
                ]
            except ValueError:
                return [part.lower() for part in path_obj.parts]

        def should_ignore(path):
            path_obj = Path(path)
            relative_parts = get_relative_parts(path_obj)
            relative_path = "/".join(relative_parts)
            for ignore in self.ignore_paths:
                ignore_parts = [part for part in ignore.split("/") if part]
                if not ignore_parts:
                    continue
                if len(ignore_parts) == 1:
                    if ignore_parts[0] in relative_parts:
                        return True
                    continue
                candidate = "/".join(ignore_parts)
                if relative_path == candidate:
                    return True
                if relative_path.startswith(f"{candidate}/"):
                    return True
            return False

        def get_size(path_stat):
            return path_stat.st_size

        for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=self.follow_symlinks):
            current_dir = Path(dirpath)
            if current_dir != root_path and should_ignore(current_dir):
                dirnames[:] = []
                continue

            current_depth = len(current_dir.relative_to(root_path).parts) if current_dir != root_path else 0

            filtered_dirnames = []
            for dirname in dirnames:
                child_dir = current_dir / dirname
                if should_ignore(child_dir):
                    continue
                filtered_dirnames.append(dirname)
                if current_dir == root_path:
                    immediate_children.setdefault(
                        dirname,
                        {"path": child_dir, "size": 0, "is_dir": True},
                    )
            dirnames[:] = filtered_dirnames

            if self.max_depth is not None and current_depth >= self.max_depth:
                dirnames[:] = []

            dir_count += 1

            for filename in filenames:
                filepath = current_dir / filename
                if should_ignore(filepath):
                    continue

                try:
                    stat_info = filepath.stat()
                    size = get_size(stat_info)
                    if size < self.min_size:
                        continue

                    ext = filepath.suffix.lower()
                    if self.include_ext and ext not in self.include_ext:
                        continue
                    if self.exclude_ext and ext in self.exclude_ext:
                        continue

                    file_count += 1
                    total_size += size
                    ext_sizes[ext] += size

                    relative_path = filepath.relative_to(root_path)
                    if len(relative_path.parts) == 1:
                        immediate_children[filename] = {
                            "path": filepath,
                            "size": size,
                            "is_dir": False,
                        }
                    else:
                        top_child = relative_path.parts[0]
                        immediate_children.setdefault(
                            top_child,
                            {
                                "path": root_path / top_child,
                                "size": 0,
                                "is_dir": True,
                            },
                        )
                        immediate_children[top_child]["size"] += size

                    # Keep top files
                    if top_n is None:
                        top_files.append((size, str(filepath)))
                    elif top_n > 0:
                        if len(top_files) < top_n:
                            heapq.heappush(top_files, (size, str(filepath)))
                        else:
                            heapq.heappushpop(top_files, (size, str(filepath)))

                    processed += 1
                    if progress_callback and processed % 100 == 0:
                        elapsed = time.time() - start_time
                        eta = (elapsed / processed) * (processed + 1000) if processed > 0 else 0  # rough estimate
                        progress_callback(processed, eta)

                except (OSError, PermissionError) as e:
                    errors.append(f"Error accessing {filepath}: {e}")

        # Convert heap to list sorted by size desc
        top_files = sorted(top_files, reverse=True)
        top_children = {
            name: int(data["size"])
            for name, data in immediate_children.items()
            if data["is_dir"]
        }

        elapsed = time.time() - start_time
        return {
            'total_size': total_size,
            'file_count': file_count,
            'dir_count': dir_count,
            'top_files': top_files,
            'top_children': top_children,
            'immediate_children': {
                name: {
                    'path': str(data['path']),
                    'size': int(data['size']),
                    'is_dir': bool(data['is_dir']),
                }
                for name, data in immediate_children.items()
            },
            'ext_sizes': dict(ext_sizes),
            'scan_time': elapsed,
            'errors': errors
        }
