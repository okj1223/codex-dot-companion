from __future__ import annotations

import json
import time
from pathlib import Path


DOT_MARKERS = (
    "dot-companion/codex-dot hook-start",
    "dot-companion/codex-dot hook-stop",
    "codex_dot_companion.codex_dot hook-start",
    "codex_dot_companion.codex_dot hook-stop",
    "codex-dot hook-start",
    "codex-dot hook-stop",
)


def is_dot_hook(command: object) -> bool:
    text = str(command or "")
    return any(marker in text for marker in DOT_MARKERS)


def read_hooks(path: Path) -> dict:
    if not path.exists():
        return {"hooks": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"failed to parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        return {"hooks": {}}
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        payload["hooks"] = {}
    return payload


def strip_existing_dot_hooks(groups: object) -> list[dict]:
    if not isinstance(groups, list):
        return []
    cleaned = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        hook_items = group.get("hooks")
        if not isinstance(hook_items, list):
            continue
        next_hooks = [
            hook
            for hook in hook_items
            if not (isinstance(hook, dict) and is_dot_hook(hook.get("command")))
        ]
        if next_hooks:
            next_group = dict(group)
            next_group["hooks"] = next_hooks
            cleaned.append(next_group)
    return cleaned


def hook_group(command: str, status_message: str) -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 5,
                "statusMessage": status_message,
            }
        ]
    }


def install_hooks(codex_home: Path, command_prefix: str) -> Path:
    codex_home.mkdir(parents=True, exist_ok=True)
    hooks_path = codex_home / "hooks.json"
    payload = read_hooks(hooks_path)
    hooks = payload.setdefault("hooks", {})

    hooks["UserPromptSubmit"] = strip_existing_dot_hooks(hooks.get("UserPromptSubmit"))
    hooks["Stop"] = strip_existing_dot_hooks(hooks.get("Stop"))
    hooks["UserPromptSubmit"].append(
        hook_group(f"{command_prefix} hook-start", "도리 작업 시작")
    )
    hooks["Stop"].append(
        hook_group(f"{command_prefix} hook-stop", "도리 작업 완료")
    )

    if hooks_path.exists():
        backup = hooks_path.with_suffix(f".json.bak.{int(time.time())}")
        backup.write_text(hooks_path.read_text(encoding="utf-8"), encoding="utf-8")

    tmp = hooks_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(hooks_path)
    return hooks_path

