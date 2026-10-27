from pathlib import Path


class ConvertError(Exception):
    """An asset/data problem the author must fix. str() is the message shown by the build."""

    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
