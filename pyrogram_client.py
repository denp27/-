import logging
import sys


def _setup() -> logging.Logger:
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)

    root = logging.getLogger("mycodershop")
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    return root


logger = _setup()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"mycodershop.{name}")
