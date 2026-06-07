#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_dot_companion.hook_installer import install_hooks


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Codex dot companion hooks.")
    parser.add_argument("command_prefix", help="Absolute command prefix, without hook-start/hook-stop.")
    args = parser.parse_args()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    path = install_hooks(codex_home, args.command_prefix)
    print(f"updated hooks at {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

