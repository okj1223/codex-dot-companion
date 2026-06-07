from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

from .hook_installer import install_hooks

DEFAULT_NAMES = ["Blink", "Pip", "Nib", "Glyph", "Bit", "Nod", "Loop", "Echo"]


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def copy_preview(app_dir: Path) -> None:
    source = resources.files("codex_dot_companion").joinpath("agent_mascot_preview.html")
    app_dir.mkdir(parents=True, exist_ok=True)
    target = app_dir / "agent_mascot_preview.html"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def ensure_config(app_dir: Path) -> None:
    config = app_dir / "config.json"
    if config.exists():
        return
    config.write_text(json.dumps({"names": DEFAULT_NAMES}, indent=2) + "\n", encoding="utf-8")


def command_prefix() -> str:
    command = shutil.which("codex-dot")
    if command:
        return command
    return f"{sys.executable} -m codex_dot_companion.codex_dot"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Codex dot companion hooks.")
    parser.add_argument("--no-start", action="store_true", help="Install files and hooks without starting the overlay.")
    args = parser.parse_args(argv)

    home = codex_home()
    app_dir = home / "dot-companion"
    copy_preview(app_dir)
    ensure_config(app_dir)
    hooks_path = install_hooks(home, command_prefix())

    if not args.no_start:
        subprocess.run(f"{command_prefix()} start", shell=True, check=False)

    print(f"installed Codex dot companion under {app_dir}")
    print(f"updated hooks at {hooks_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
