"""User configuration: defaults, file location, and load/save helpers."""

import os
from pathlib import Path

DEFAULT_CONFIG = {
    "whisper_path": "",
    "model_path": "",
    "ffmpeg_path": "ffmpeg",
    "language": "en",
    "translate": "no",
    "mode": "full",
    "chunk_size": "30",
    "segment_size": "120",
    "output_dir": "",
}


def get_config_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "subtitle_generator" / "config.txt"
    return Path.home() / ".config" / "subtitle_generator" / "config.txt"


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    path = get_config_path()
    if not path.exists():
        return config
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                if key in config:
                    config[key] = value.strip()
    except Exception:
        pass
    return config


def save_config(args) -> None:
    """Persist current settings to config file for future sessions."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"whisper_path={args.whisper_path}",
        f"model_path={args.model_path}",
        f"ffmpeg_path={args.ffmpeg_path}",
        f"language={args.language}",
        f"translate={'yes' if args.translate else 'no'}",
        f"segment_size={args.segment_size}",
    ]
    if hasattr(args, "output_dir") and args.output_dir:
        lines.append(f"output_dir={args.output_dir}")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
