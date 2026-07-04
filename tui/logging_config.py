import logging


logger = logging.getLogger("DiskScoutTUI")


def configure_logging() -> None:
    """Configure TUI logging when the app starts, not when the module is imported."""
    if logger.handlers:
        return
    handler = logging.FileHandler("tui.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
