"""File logger used during generation."""

import datetime
import tempfile
from pathlib import Path

from . import __version__


class Logger:
    def __init__(self, output_srt: str = ""):
        if output_srt:
            self.log_path = Path(output_srt).with_suffix(".log")
        else:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_path = Path(tempfile.gettempdir()) / f"subtitle_generator_v{__version__}_{ts}.log"
        self._file = open(self.log_path, "w", encoding="utf-8")

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        self._file.write(line + "\n")
        self._file.flush()

    def close(self):
        self._file.close()
