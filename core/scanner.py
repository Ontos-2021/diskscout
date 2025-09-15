import os
import heapq
import time
import stat
from pathlib import Path
from collections import Counter, defaultdict

class DiskScanner:
    def __init__(self, min_size=0, include_ext=None, exclude_ext=None, ignore_paths=None, max_depth=None, follow_symlinks=False):
        self.min_size = min_size
        self.include_ext = set(include_ext) if include_ext else None
        self.exclude_ext = set(exclude_ext) if exclude_ext else None
        self.ignore_paths = set(ignore_paths) if ignore_paths else set()
        self.max_depth = max_depth
        self.follow_symlinks = follow_symlinks

    def scan(self, root_path, progress_callback=None):
        root_path = Path(root_path).resolve()
        if not root_path.exists():
            raise ValueError(f"Path does not exist: {root_path}")

        total_size = 0
        file_count = 0
        dir_count = 0
        errors = []
        ext_sizes = Counter()
        top_files = []  # min-heap for top N files
        top_children = {}  # for immediate children of root
        start_time = time.time()
        processed = 0

        def should_ignore(path):
            for ignore in self.ignore_paths:
                if ignore in str(path):
                    return True
            return False

        def get_size(path_stat):
            return path_stat.st_size

        for dirpath, dirnames, filenames in os.walk(root_path, topdown=False, followlinks=self.follow_symlinks):
            current_depth = len(Path(dirpath).relative_to(root_path).parts) if dirpath != str(root_path) else 0
            if self.max_depth is not None and current_depth > self.max_depth:
                dirnames[:] = []  # don't recurse deeper
                continue

            if should_ignore(dirpath):
                dirnames[:] = []
                continue

            dir_count += 1
            dir_size = 0

            for filename in filenames:
                filepath = Path(dirpath) / filename
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
                    dir_size += size
                    ext_sizes[ext] += size

                    # Keep top files
                    if len(top_files) < 20:  # top 20
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

            # For top children, if this is immediate child of root
            if Path(dirpath).parent == root_path:
                top_children[str(Path(dirpath).name)] = dir_size

        # Convert heap to list sorted by size desc
        top_files = sorted(top_files, reverse=True)

        elapsed = time.time() - start_time
        return {
            'total_size': total_size,
            'file_count': file_count,
            'dir_count': dir_count,
            'top_files': top_files,
            'top_children': top_children,
            'ext_sizes': dict(ext_sizes),
            'scan_time': elapsed,
            'errors': errors
        }
