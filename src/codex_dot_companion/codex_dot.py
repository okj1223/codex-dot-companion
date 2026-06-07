#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import random
import signal
import socket
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
APP_DIR = CODEX_HOME / "dot-companion"
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "state.json"
ASSIGNMENTS_FILE = APP_DIR / "assignments.json"
PID_FILE = APP_DIR / "overlay.pid"
LOG_FILE = APP_DIR / "overlay.log"
MASCOT_SERVER_FILE = APP_DIR / "mascot-server.json"
MASCOT_SERVER_LOG = APP_DIR / "mascot-server.log"
MASCOT_PREVIEW_FILE = APP_DIR / "agent_mascot_preview.html"
SESSIONS_DIR = CODEX_HOME / "sessions"
DEFAULT_NAMES = ["Blink", "Pip", "Nib", "Glyph", "Bit", "Nod", "Loop", "Echo"]
PERSONALITIES = [
    {"mood": "eager", "tempo": 1.18, "idle_period": 18, "blink_period": 54, "work_amp": 1.15, "arm_amp": 1.10, "sleep_delay": 1.15, "sleep_bob": 1, "startle": 1.10, "success": 1.10},
    {"mood": "focused", "tempo": 0.86, "idle_period": 28, "blink_period": 86, "work_amp": 0.62, "arm_amp": 0.72, "sleep_delay": 1.30, "sleep_bob": 0, "startle": 0.72, "success": 0.82},
    {"mood": "fidgety", "tempo": 1.08, "idle_period": 20, "blink_period": 66, "work_amp": 0.96, "arm_amp": 1.28, "sleep_delay": 1.00, "sleep_bob": 1, "startle": 1.00, "success": 0.95},
    {"mood": "reluctant", "tempo": 0.62, "idle_period": 34, "blink_period": 96, "work_amp": 0.42, "arm_amp": 0.46, "sleep_delay": 1.18, "sleep_bob": 0, "startle": 0.58, "success": 0.62},
    {"mood": "snappy", "tempo": 1.28, "idle_period": 16, "blink_period": 58, "work_amp": 1.08, "arm_amp": 0.92, "sleep_delay": 1.08, "sleep_bob": 1, "startle": 1.05, "success": 1.00},
    {"mood": "sleepy", "tempo": 0.78, "idle_period": 24, "blink_period": 72, "work_amp": 0.70, "arm_amp": 0.75, "sleep_delay": 0.58, "sleep_bob": 2, "startle": 0.82, "success": 0.78},
    {"mood": "bouncy", "tempo": 1.02, "idle_period": 19, "blink_period": 64, "work_amp": 1.00, "arm_amp": 0.90, "sleep_delay": 0.95, "sleep_bob": 1, "startle": 1.20, "success": 1.22},
    {"mood": "shy", "tempo": 0.92, "idle_period": 30, "blink_period": 82, "work_amp": 0.78, "arm_amp": 0.82, "sleep_delay": 1.20, "sleep_bob": 0, "startle": 0.92, "success": 0.88},
]
WINDOW_W = 424
WINDOW_H = 146
SLOT_W = 102
SLOT_H = 132
MAX_SLOTS = 8
MASCOT_SERVER_PORT = 8765
ACTIVE_STALE_SECONDS = 6 * 60 * 60
WORKING_MIN_VISIBLE_SECONDS = 0.5
SUCCESS_VISIBLE_SECONDS = 1.5
DONE_VISIBLE_SECONDS = SUCCESS_VISIBLE_SECONDS
MANUAL_VISIBLE_SECONDS = 60
OVERLAY_TICK_MS = 60
SLEEP_DELAY_SECONDS = 7.0
DROWSY_SECONDS = 1.6
STIR_SECONDS = 1.05
ASLEEP_STIR_MIN_SECONDS = 6.0
ASLEEP_STIR_SPREAD_SECONDS = 7.0
AWAKE_AFTER_STIR_MIN_SECONDS = 4.5
AWAKE_AFTER_STIR_SPREAD_SECONDS = 6.5
RAW_WORKING_STATES = {"loading", "streaming", "generating", "editing", "tool_running", "command_running", "working"}
RAW_SUCCESS_STATES = {"completed", "complete", "done", "success"}
RAW_ERROR_STATES = {"failed", "failure", "exception", "error", "attention"}
SESSION_PARSE_CACHE: dict[str, tuple[int, int, dict | None]] = {}


def now() -> float:
    return time.time()


def ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def read_config() -> dict:
    ensure_dir()
    if not CONFIG_FILE.exists():
        write_config({"names": DEFAULT_NAMES})
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"names": DEFAULT_NAMES}
    names = config.get("names")
    if not isinstance(names, list):
        names = DEFAULT_NAMES
    clean_names = []
    for idx, name in enumerate(names):
        fallback = DEFAULT_NAMES[idx] if idx < len(DEFAULT_NAMES) else f"Blink-{idx + 1}"
        clean_names.append(str(name).strip() or fallback)
    return {"names": clean_names or DEFAULT_NAMES}


def write_config(config: dict) -> None:
    ensure_dir()
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def read_assignments() -> dict[str, int]:
    try:
        payload = json.loads(ASSIGNMENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    assignments = payload.get("assignments") if isinstance(payload, dict) else {}
    if not isinstance(assignments, dict):
        return {}
    clean: dict[str, int] = {}
    for key, value in assignments.items():
        try:
            clean[str(key)] = int(value) % len(DEFAULT_NAMES)
        except Exception:
            continue
    return clean


def write_assignments(assignments: dict[str, int]) -> None:
    ensure_dir()
    tmp = ASSIGNMENTS_FILE.with_suffix(".json.tmp")
    payload = {
        "assignments": assignments,
        "updated_at": now(),
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(ASSIGNMENTS_FILE)


def choose_mascot_index(assignments: dict[str, int]) -> int:
    used = set(assignments.values())
    available = [idx for idx in range(len(DEFAULT_NAMES)) if idx not in used]
    if available:
        return random.choice(available)
    return random.randrange(len(DEFAULT_NAMES))


def apply_mascot_assignments(slots: list[dict]) -> list[dict]:
    assignments = read_assignments()
    live_ids = [str(slot.get("assignment_id") or slot.get("id", idx)) for idx, slot in enumerate(slots)]
    live_set = set(live_ids)
    assignments = {
        sid: mascot_idx
        for sid, mascot_idx in assignments.items()
        if sid in live_set and 0 <= mascot_idx < len(DEFAULT_NAMES)
    }

    changed = False
    for sid in live_ids:
        if sid not in assignments:
            assignments[sid] = choose_mascot_index(assignments)
            changed = True
    if changed or set(read_assignments()) != set(assignments):
        write_assignments(assignments)

    for idx, slot in enumerate(slots):
        sid = str(slot.get("assignment_id") or slot.get("id", idx))
        slot["assignment_id"] = sid
        mascot_idx = assignments.get(sid, idx % len(DEFAULT_NAMES))
        slot["mascot_index"] = mascot_idx
        slot["name"] = companion_name(mascot_idx)
    return slots


def companion_names() -> list[str]:
    return read_config()["names"]


def companion_name(index: int) -> str:
    names = companion_names()
    if index < len(names):
        return names[index]
    return DEFAULT_NAMES[index] if index < len(DEFAULT_NAMES) else f"Blink-{index + 1}"


def set_companion_name(index: int, name: str) -> None:
    names = companion_names()
    while len(names) <= index:
        next_index = len(names)
        names.append(DEFAULT_NAMES[next_index] if next_index < len(DEFAULT_NAMES) else f"Blink-{next_index + 1}")
    fallback = DEFAULT_NAMES[index] if index < len(DEFAULT_NAMES) else f"Blink-{index + 1}"
    names[index] = name.strip()[:24] or fallback
    write_config({"names": names})


def write_state(state: str, cwd: str | None = None, source: str = "manual") -> None:
    ensure_dir()
    payload = {
        "state": normalize_state(state),
        "cwd": cwd or os.getcwd(),
        "name": companion_name(0),
        "source": source,
        "updated_at": now(),
    }
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "state": "idle",
            "cwd": os.getcwd(),
            "name": companion_name(0),
            "source": "default",
            "updated_at": 0,
        }


def normalize_state(state: str | None) -> str:
    raw = str(state or "idle").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in RAW_WORKING_STATES:
        return "working"
    if raw in RAW_SUCCESS_STATES:
        return "done"
    if raw in RAW_ERROR_STATES:
        return "attention"
    return "idle"


def mascot_status_for_state(state: str | None) -> str:
    normalized = normalize_state(state)
    if normalized == "attention":
        return "error"
    if normalized == "working":
        return "working"
    if normalized == "done":
        return "success"
    return "idle"


def event_state(event_type: str | None) -> str | None:
    raw = str(event_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return None
    if raw == "task_started" or raw in RAW_WORKING_STATES:
        return "working"
    if raw == "task_complete" or raw in RAW_SUCCESS_STATES:
        return "done"
    if raw == "task_failed" or raw in RAW_ERROR_STATES or "exception" in raw or raw.endswith("_error"):
        return "attention"
    return None


def session_clear_cutoff() -> float:
    current = read_state()
    if normalize_state(current.get("state")) != "idle":
        return 0
    if current.get("source") not in {"manual", "right-click"}:
        return 0
    return float(current.get("updated_at") or 0)


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return pid if is_running(pid) else None


def start_overlay() -> None:
    ensure_dir()
    if read_pid():
        return

    env = os.environ.copy()
    env.setdefault("GDK_BACKEND", "x11")
    with LOG_FILE.open("ab", buffering=0) as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "overlay"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,
            close_fds=True,
        )


def stop_overlay() -> None:
    pid = read_pid()
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def newest_session_file() -> Path | None:
    if not SESSIONS_DIR.exists():
        return None
    try:
        files = SESSIONS_DIR.glob("*/*/*/*.jsonl")
        return max(files, key=lambda path: path.stat().st_mtime)
    except ValueError:
        return None
    except Exception:
        return None


def tail_lines(path: Path, max_bytes: int = 1048576) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            blob = handle.read()
    except Exception:
        return []
    return blob.decode("utf-8", errors="ignore").splitlines()


def parse_iso_timestamp(value: str | None) -> float:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def parse_session_slot(path: Path) -> dict | None:
    latest: dict | None = None
    latest_cwd = ""
    user_preview = ""
    for line in tail_lines(path):
        try:
            record = json.loads(line)
        except Exception:
            continue

        record_type = record.get("type")
        payload = record.get("payload") or {}
        ts = parse_iso_timestamp(record.get("timestamp"))

        if record_type == "turn_context":
            latest_cwd = payload.get("cwd") or latest_cwd
            continue

        if record_type == "response_item":
            message = payload.get("message") if isinstance(payload.get("message"), str) else ""
            if message:
                user_preview = message[:64]

        if record_type != "event_msg":
            continue

        event_type = payload.get("type")
        if event_type == "user_message":
            user_preview = (payload.get("message") or user_preview)[:64]

        state = event_state(event_type)
        if state == "working":
            latest = {
                "id": path.stem,
                "turn_id": payload.get("turn_id") or "",
                "state": "working",
                "cwd": latest_cwd,
                "name": companion_name(0),
                "source": "session-log",
                "updated_at": ts,
                "path": str(path),
                "preview": user_preview,
            }
        elif state in {"done", "attention"}:
            latest = {
                "id": path.stem,
                "turn_id": payload.get("turn_id") or "",
                "state": state,
                "cwd": latest_cwd,
                "name": companion_name(0),
                "source": "session-log",
                "updated_at": ts,
                "path": str(path),
                "preview": user_preview,
            }

    return latest


def cached_parse_session_slot(path: Path) -> dict | None:
    try:
        stat = path.stat()
    except Exception:
        return None
    key = str(path)
    cached = SESSION_PARSE_CACHE.get(key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return dict(cached[2]) if cached[2] else None

    slot = parse_session_slot(path)
    SESSION_PARSE_CACHE[key] = (stat.st_mtime_ns, stat.st_size, dict(slot) if slot else None)
    if len(SESSION_PARSE_CACHE) > 160:
        live_keys = set()
        try:
            live_keys = {str(candidate) for candidate in SESSIONS_DIR.glob("*/*/*/*.jsonl")}
        except Exception:
            pass
        for cached_key in list(SESSION_PARSE_CACHE):
            if live_keys and cached_key not in live_keys:
                SESSION_PARSE_CACHE.pop(cached_key, None)
    return dict(slot) if slot else None


def session_slots() -> list[dict]:
    if not SESSIONS_DIR.exists():
        return []
    cutoff = now() - ACTIVE_STALE_SECONDS
    clear_cutoff = session_clear_cutoff()
    try:
        paths = sorted(
            SESSIONS_DIR.glob("*/*/*/*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:80]
    except Exception:
        return []

    slots: list[dict] = []
    for path in paths:
        slot = cached_parse_session_slot(path)
        if not slot:
            continue
        if clear_cutoff and slot.get("updated_at", 0) <= clear_cutoff:
            continue
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = slot.get("updated_at", 0)

        if slot["state"] == "working" and mtime < cutoff:
            continue
        if slot["state"] == "done" and now() - slot.get("updated_at", 0) > DONE_VISIBLE_SECONDS:
            continue
        slot["mascot_status"] = mascot_status_for_state(slot.get("state"))
        slots.append(slot)

    slots.sort(
        key=lambda item: (
            {"attention": 0, "working": 1, "done": 2}.get(item.get("state"), 3),
            -float(item.get("updated_at", 0)),
        )
    )
    return slots[:MAX_SLOTS]


def codex_process_records() -> list[dict]:
    try:
        output = subprocess.check_output(["ps", "-eo", "pid=,tty=,args="], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []

    records: list[dict] = []
    for line in output.splitlines():
        if "codex_dot.py" in line or "rg " in line:
            continue
        if "vendor/x86_64-unknown-linux-musl/bin/codex" in line:
            parts = line.strip().split(maxsplit=2)
            try:
                pid = int(parts[0])
            except Exception:
                continue
            try:
                cwd = str(Path(f"/proc/{pid}/cwd").resolve())
            except Exception:
                cwd = ""
            records.append(
                {
                    "pid": pid,
                    "tty": parts[1] if len(parts) > 1 else "",
                    "cwd": cwd,
                    "assignment_id": f"codex-process-{pid}",
                }
            )
    return sorted(records, key=lambda item: int(item["pid"]))


def codex_process_ids() -> list[int]:
    return [int(record["pid"]) for record in codex_process_records()]


def codex_process_count() -> int:
    return len(codex_process_ids())


def process_assignment_for_slot(slot: dict, process_records: list[dict]) -> str | None:
    cwd = str(slot.get("cwd") or "")
    if cwd:
        matches = [record for record in process_records if record.get("cwd") == cwd]
        if len(matches) == 1:
            return str(matches[0]["assignment_id"])
    if len(process_records) == 1:
        return str(process_records[0]["assignment_id"])
    return None


def display_slots() -> list[dict]:
    raw_slots = session_slots()
    slots: list[dict] = []
    process_records = codex_process_records()
    current = read_state()
    if (
        not process_records
        and current.get("source") == "manual"
        and now() - current.get("updated_at", 0) < MANUAL_VISIBLE_SECONDS
    ):
        manual_state = normalize_state(current.get("state"))
        raw_slots.insert(
            0,
            {
                "id": "manual",
                "state": manual_state,
                "cwd": current.get("cwd", ""),
                "name": companion_name(0),
                "source": "manual",
                "updated_at": current.get("updated_at", 0),
                "preview": "",
                "mascot_status": mascot_status_for_state(manual_state),
            },
        )

    represented_processes = set()
    if process_records:
        for slot in raw_slots:
            assignment_id = process_assignment_for_slot(slot, process_records)
            if assignment_id and assignment_id not in represented_processes:
                slot["assignment_id"] = assignment_id
                represented_processes.add(assignment_id)
                slots.append(slot)

        for slot in raw_slots:
            if slot.get("assignment_id") or len(slots) >= len(process_records):
                continue
            cwd = str(slot.get("cwd") or "")
            candidates = [
                record
                for record in process_records
                if str(record["assignment_id"]) not in represented_processes
                and cwd
                and record.get("cwd") == cwd
            ]
            if not candidates:
                candidates = [
                    record
                    for record in process_records
                    if str(record["assignment_id"]) not in represented_processes
                ]
            if not candidates:
                continue
            assignment_id = str(candidates[0]["assignment_id"])
            slot["assignment_id"] = assignment_id
            represented_processes.add(assignment_id)
            slots.append(slot)
    else:
        slots = raw_slots

    represented_processes = set()
    for slot in slots:
        assignment_id = str(slot.get("assignment_id") or "")
        if assignment_id:
            represented_processes.add(assignment_id)

    for record in process_records:
        assignment_id = str(record["assignment_id"])
        if assignment_id in represented_processes or len(slots) >= MAX_SLOTS:
            continue
        slots.append(
            {
                "id": assignment_id,
                "assignment_id": assignment_id,
                "state": "idle",
                "cwd": str(record.get("cwd") or ""),
                "name": companion_name(len(slots)),
                "source": "process",
                "updated_at": 0,
                "preview": "",
                "mascot_status": "idle",
            }
        )

    for idx, slot in enumerate(slots[:MAX_SLOTS]):
        slot["state"] = normalize_state(slot.get("state"))
        slot["mascot_status"] = mascot_status_for_state(slot.get("state"))
    return apply_mascot_assignments(slots[:MAX_SLOTS])


def window_size_for_slots(count: int) -> tuple[int, int]:
    count = max(1, min(MAX_SLOTS, count))
    cols = min(4, count)
    rows = math.ceil(count / cols)
    return 16 + cols * SLOT_W, 12 + rows * SLOT_H


def merge_state(current: dict) -> dict:
    fallback = parse_session_slot(newest_session_file()) if newest_session_file() else None
    if fallback and fallback.get("updated_at", 0) > current.get("updated_at", 0):
        return fallback
    return current


def trim_cwd(cwd: str | None) -> str:
    if not cwd:
        return "~"
    home = str(Path.home())
    if cwd == home:
        return "~"
    if cwd.startswith(home + os.sep):
        cwd = "~" + cwd[len(home) :]
    parts = cwd.split(os.sep)
    if len(parts) > 3:
        return os.sep.join(parts[-2:])
    return cwd


def overlay_main() -> int:
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    import cairo
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

    ensure_dir()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    class DotOverlay(Gtk.Window):
        def __init__(self) -> None:
            super().__init__(type=Gtk.WindowType.TOPLEVEL)
            self.set_title("Codex dot companion")
            self.set_decorated(False)
            self.set_resizable(False)
            self.set_size_request(1, 1)
            self.set_default_size(WINDOW_W, WINDOW_H)
            self.set_keep_above(True)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.set_accept_focus(False)
            self.set_focus_on_map(False)
            self.set_app_paintable(True)
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
            self.add_events(
                Gdk.EventMask.BUTTON_PRESS_MASK
                | Gdk.EventMask.POINTER_MOTION_MASK
                | Gdk.EventMask.LEAVE_NOTIFY_MASK
            )
            self.connect("draw", self.on_draw)
            self.connect("button-press-event", self.on_button_press)
            self.connect("motion-notify-event", self.on_motion)
            self.connect("leave-notify-event", self.on_leave)
            self.connect("destroy", Gtk.main_quit)

            screen = self.get_screen()
            visual = screen.get_rgba_visual()
            if visual is not None:
                self.set_visual(visual)
            self.install_css(screen)

            monitor = screen.get_primary_monitor()
            geo = screen.get_monitor_geometry(monitor if monitor >= 0 else 0)

            self.slots = display_slots()
            width, height = window_size_for_slots(len(self.slots))
            self.set_size_request(width, height)
            self.move(geo.x + geo.width - width - 28, geo.y + 74)
            self.resize(width, height)
            self.frame = 0
            self.done_seen_at: dict[str, float] = {}
            self.mascot_memory: dict[str, dict] = {}
            self.last_state_key = ""
            self.user_moved = False
            self.hover_name_idx: int | None = None
            self.name_editor_window = None
            self.name_editor_entry = None
            self.name_editor_idx: int | None = None
            GLib.timeout_add(OVERLAY_TICK_MS, self.tick)
            GLib.timeout_add(700, self.reload_state)

        def install_css(self, screen) -> None:
            css = b"""
            entry.codex-name-editor {
              background: rgba(13, 15, 22, 0.96);
              color: #f7fbff;
              border: 1px solid rgba(115, 235, 255, 0.68);
              border-radius: 8px;
              padding: 2px 7px;
              font: 700 9pt Sans;
            }
            """
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.css_provider = provider

        def slot_origin(self, idx: int) -> tuple[int, int]:
            slots = self.slots or display_slots()
            cols = min(4, max(1, len(slots)))
            return 12 + (idx % cols) * SLOT_W, 12 + (idx // cols) * SLOT_H

        def name_hit_index(self, px: float, py: float) -> int | None:
            slots = self.slots or display_slots()
            for idx in range(len(slots)):
                x, y = self.slot_origin(idx)
                if x + 8 <= px <= x + SLOT_W - 8 and y + 99 <= py <= y + 122:
                    return idx
            return None

        def on_button_press(self, _widget, event) -> bool:
            if event.button == 1:
                idx = self.name_hit_index(event.x, event.y)
                if idx is not None:
                    self.start_name_edit(idx)
                    return True
                self.finish_name_edit(save=True)
                self.user_moved = True
                self.begin_move_drag(
                    event.button,
                    int(event.x_root),
                    int(event.y_root),
                    event.time,
                )
                return True
            if event.button == 3:
                write_state("idle", source="right-click")
                self.slots = display_slots()
                self.queue_draw()
                return True
            return False

        def on_motion(self, _widget, event) -> bool:
            idx = self.name_hit_index(event.x, event.y)
            if idx != self.hover_name_idx:
                self.hover_name_idx = idx
                self.queue_draw()
            return False

        def on_leave(self, *_args) -> bool:
            if self.hover_name_idx is not None:
                self.hover_name_idx = None
                self.queue_draw()
            return False

        def start_name_edit(self, idx: int) -> None:
            self.finish_name_edit(save=True)
            x, y = self.slot_origin(idx)
            win_x, win_y = self.get_position()
            editor = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            editor.set_title("Edit Codex dot name")
            editor.set_decorated(False)
            editor.set_resizable(False)
            editor.set_keep_above(True)
            editor.set_skip_taskbar_hint(True)
            editor.set_skip_pager_hint(True)
            editor.set_accept_focus(True)
            editor.set_focus_on_map(True)
            editor.set_transient_for(self)
            editor.set_type_hint(Gdk.WindowTypeHint.UTILITY)

            entry = Gtk.Entry()
            entry.set_text(companion_name(idx))
            entry.set_width_chars(10)
            entry.set_max_length(24)
            entry.set_has_frame(True)
            entry.set_size_request(SLOT_W - 18, 24)
            entry.set_alignment(0.5)
            entry.get_style_context().add_class("codex-name-editor")
            editor.add(entry)

            self.name_editor_window = editor
            self.name_editor_entry = entry
            self.name_editor_idx = idx

            entry.connect("activate", lambda _entry: self.finish_name_edit(save=True))
            entry.connect("key-press-event", self.on_name_editor_key)

            editor.move(win_x + x + 9, win_y + y + 101)
            editor.show_all()
            editor.present()
            gdk_window = editor.get_window()
            if gdk_window is not None:
                gdk_window.focus(Gdk.CURRENT_TIME)
            entry.grab_focus()
            entry.select_region(0, -1)
            GLib.idle_add(self.focus_name_editor)

        def focus_name_editor(self) -> bool:
            editor = self.name_editor_window
            entry = self.name_editor_entry
            if editor is None or entry is None:
                return False
            editor.present()
            gdk_window = editor.get_window()
            if gdk_window is not None:
                gdk_window.focus(Gdk.CURRENT_TIME)
            entry.grab_focus()
            entry.select_region(0, -1)
            return False

        def on_name_editor_key(self, _entry, event) -> bool:
            if event.keyval == Gdk.KEY_Escape:
                self.finish_name_edit(save=False)
                return True
            return False

        def on_name_editor_focus_out(self, *_args) -> bool:
            GLib.idle_add(lambda: self.finish_name_edit(save=True) or False)
            return False

        def finish_name_edit(self, save: bool) -> None:
            editor = self.name_editor_window
            entry = self.name_editor_entry
            idx = self.name_editor_idx
            if editor is None:
                return
            self.name_editor_window = None
            self.name_editor_entry = None
            self.name_editor_idx = None
            if save and entry is not None and idx is not None:
                set_companion_name(idx, entry.get_text())
                self.slots = display_slots()
            editor.destroy()
            self.queue_draw()

        def reload_state(self) -> bool:
            slots = display_slots()
            if not slots:
                self.slots = []
                self.last_state_key = ""
                self.finish_name_edit(save=True)
                self.hide()
                return True
            if not self.get_visible():
                self.show_all()
            key = "|".join(
                f"{slot.get('id')}:{slot.get('state')}:{slot.get('updated_at')}:{slot.get('name')}"
                for slot in slots
            )
            if key != self.last_state_key:
                for slot in slots:
                    if slot.get("state") == "done":
                        self.done_seen_at.setdefault(str(slot.get("id")), now())
                self.last_state_key = key
            self.slots = slots
            live_ids = {str(slot.get("id", idx)) for idx, slot in enumerate(slots)}
            self.mascot_memory = {
                sid: value for sid, value in self.mascot_memory.items() if sid in live_ids
            }
            width, height = window_size_for_slots(len(slots))
            self.set_size_request(width, height)
            self.resize(width, height)
            if not self.user_moved:
                screen = self.get_screen()
                monitor = screen.get_primary_monitor()
                geo = screen.get_monitor_geometry(monitor if monitor >= 0 else 0)
                self.move(geo.x + geo.width - width - 28, geo.y + 74)
            self.set_keep_above(True)
            self.queue_draw()
            return True

        def tick(self) -> bool:
            self.frame += 1
            self.queue_draw()
            return True

        def on_draw(self, _widget, cr) -> bool:
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            self.draw_scene(cr)
            return False

        def draw_scene(self, cr) -> None:
            slots = self.slots or display_slots()
            width, height = window_size_for_slots(len(slots))
            self.round_rect(cr, 6, 6, width - 12, height - 12, 12, (0.035, 0.04, 0.048, 0.38))
            cols = min(4, max(1, len(slots)))
            for idx, slot in enumerate(slots):
                col = idx % cols
                row = idx // cols
                x = 12 + col * SLOT_W
                y = 12 + row * SLOT_H
                self.draw_pixel_slot(cr, slot, idx, x, y)

        def pbox(self, cr, x, y, w, h, size, color) -> None:
            cr.rectangle(round(x), round(y), w * size, h * size)
            cr.set_source_rgba(*color)
            cr.fill()

        def px(self, cr, ox, oy, x, y, w, h, color) -> None:
            self.pbox(cr, ox + x, oy + y, w, h, 1, color)

        def personality_for_index(self, idx: int) -> dict:
            return PERSONALITIES[idx % len(PERSONALITIES)]

        def resolve_mascot_status(self, slot, idx) -> str:
            sid = str(slot.get("id", idx))
            raw = slot.get("mascot_status") or mascot_status_for_state(slot.get("state"))
            rec = self.mascot_memory.setdefault(
                sid,
                {
                    "visible": "idle",
                    "working_started_at": 0.0,
                    "success_started_at": 0.0,
                    "success_key": None,
                    "sleep_phase": "awake",
                    "sleep_started_at": 0.0,
                    "sleep_due_at": 0.0,
                    "stir_due_at": 0.0,
                    "pending": None,
                },
            )
            stamp = now()
            event_key = f"{sid}:{slot.get('updated_at', 0)}"

            if raw == "error":
                rec["visible"] = "error"
                rec["pending"] = None
                rec["success_started_at"] = 0.0
                self.reset_sleep(rec)
                return "error"

            if raw == "working":
                if rec["visible"] != "working":
                    rec["working_started_at"] = stamp
                rec["visible"] = "working"
                rec["pending"] = None
                rec["success_started_at"] = 0.0
                rec["success_key"] = None
                self.reset_sleep(rec)
                return "working"

            if rec["visible"] == "working":
                elapsed = stamp - float(rec.get("working_started_at") or stamp)
                if elapsed < WORKING_MIN_VISIBLE_SECONDS:
                    rec["pending"] = raw
                    return "working"
                if rec.get("pending") == "success" or raw == "success":
                    rec["visible"] = "success"
                    rec["success_started_at"] = stamp
                    rec["success_key"] = event_key
                    rec["pending"] = None
                    self.reset_sleep(rec)
                    return "success"

            if raw == "success":
                if rec.get("success_key") != event_key:
                    rec["success_started_at"] = stamp
                    rec["success_key"] = event_key
                rec["visible"] = "success"
                rec["pending"] = None

            if rec["visible"] == "success":
                elapsed = stamp - float(rec.get("success_started_at") or stamp)
                if elapsed < SUCCESS_VISIBLE_SECONDS:
                    return "success"

            rec["visible"] = "idle"
            rec["pending"] = None
            return "idle"

        def reset_sleep(self, rec: dict) -> None:
            rec["sleep_phase"] = "awake"
            rec["sleep_started_at"] = 0.0
            rec["sleep_due_at"] = 0.0
            rec["stir_due_at"] = 0.0

        def sleep_phase_for_slot(self, slot, idx: int, status: str) -> tuple[str, float]:
            sid = str(slot.get("id", idx))
            rec = self.mascot_memory.setdefault(sid, {})
            personality = self.personality_for_index(idx)
            if status != "idle":
                self.reset_sleep(rec)
                return "awake", 0.0

            stamp = now()
            phase = rec.get("sleep_phase") or "awake"
            if not rec.get("sleep_due_at"):
                delay = SLEEP_DELAY_SECONDS * float(personality["sleep_delay"])
                rec["sleep_due_at"] = stamp + delay + idx * 0.55

            if phase == "awake":
                if stamp >= float(rec.get("sleep_due_at") or stamp):
                    rec["sleep_phase"] = "drowsy"
                    rec["sleep_started_at"] = stamp
                    return "drowsy", 0.0
                return "awake", 0.0

            if phase == "drowsy":
                elapsed = stamp - float(rec.get("sleep_started_at") or stamp)
                if elapsed >= DROWSY_SECONDS:
                    rec["sleep_phase"] = "asleep"
                    rec["sleep_started_at"] = stamp
                    stir_delay = ASLEEP_STIR_MIN_SECONDS + random.random() * ASLEEP_STIR_SPREAD_SECONDS
                    rec["stir_due_at"] = stamp + stir_delay * float(personality["sleep_delay"])
                    return "asleep", 0.0
                return "drowsy", elapsed

            if phase == "asleep":
                if stamp >= float(rec.get("stir_due_at") or (stamp + 1)):
                    rec["sleep_phase"] = "stirring"
                    rec["sleep_started_at"] = stamp
                    return "stirring", 0.0
                return "asleep", stamp - float(rec.get("sleep_started_at") or stamp)

            if phase == "stirring":
                elapsed = stamp - float(rec.get("sleep_started_at") or stamp)
                if elapsed >= STIR_SECONDS:
                    rec["sleep_phase"] = "awake"
                    rec["sleep_started_at"] = stamp
                    awake_delay = AWAKE_AFTER_STIR_MIN_SECONDS + random.random() * AWAKE_AFTER_STIR_SPREAD_SECONDS
                    rec["sleep_due_at"] = stamp + awake_delay * float(personality["sleep_delay"])
                    rec["stir_due_at"] = 0.0
                    return "awake", 0.0
                return "stirring", elapsed

            rec["sleep_phase"] = "awake"
            return "awake", 0.0

        def draw_agent_mascot(self, cr, status: str, sleep_phase: str, sleep_elapsed: float, idx: int, x: int, y: int) -> None:
            personality = self.personality_for_index(idx)
            mood = str(personality.get("mood", ""))
            t = int(self.frame * float(personality["tempo"])) + idx * 7
            idle_period = int(personality["idle_period"])
            blink_period = int(personality["blink_period"])
            work_amp = float(personality["work_amp"])
            arm_amp = float(personality["arm_amp"])
            sleep_bob = int(personality["sleep_bob"])
            startle_amp = float(personality["startle"])
            success_amp = float(personality["success"])
            body = (0.298, 0.616, 1.0, 1.0)
            body_hi = (0.561, 0.784, 1.0, 1.0)
            body_dark = (0.110, 0.373, 0.706, 1.0)
            eye = (0.039, 0.067, 0.102, 1.0)
            mint = (0.365, 0.949, 0.631, 1.0)
            sweat = (0.722, 0.957, 1.0, 0.76)
            code = (0.561, 0.784, 1.0, 0.92)
            shadow = (0.0, 0.0, 0.0, 0.16)

            bx = 0
            by = 0
            if status == "idle":
                if sleep_phase == "stirring":
                    step = min(5, int((sleep_elapsed / STIR_SECONDS) * 6))
                    by = round([3, -7, 0, -3, 0, 0][step] * startle_amp)
                elif sleep_phase == "asleep":
                    by = (4 + sleep_bob) if (t // 28) % 2 else (2 + sleep_bob)
                elif sleep_phase == "drowsy":
                    by = (2 + sleep_bob) if (t // 12) % 2 else (1 + sleep_bob)
                else:
                    by = -1 if (t // idle_period) % 2 else 0
            elif status == "working":
                if mood == "reluctant":
                    bx, by = [(-1, 1), (0, 1), (1, 0), (0, 1)][t % 4]
                else:
                    bx, by = [
                        (-round(1 * work_amp), -round(1 * work_amp)),
                        (0, 0),
                        (max(1, round(2 * work_amp)), max(1, round(1 * work_amp))),
                    ][t % 3]
            elif status == "success":
                by = round([0, -5, 0, -2, 0, 0][(t // 2) % 6] * success_amp)
            elif status == "error":
                bx = [-2, 0, 2][t % 3]

            ox = x + bx
            oy = y + by
            self.px(cr, x, y, 16, 49, 25, 2, shadow)

            arm_left_y = 25
            arm_right_y = 23
            if status == "working":
                if mood == "reluctant" and (t // 8) % 3 == 0:
                    arm_left_y += 2
                    arm_right_y += 4
                else:
                    arm_left_y += round(6 * arm_amp) if t % 2 else 0
                    arm_right_y += round(-2 * arm_amp) if t % 2 else round(5 * arm_amp)
            elif status == "success":
                arm_left_y -= round(4 * success_amp)
                arm_right_y -= round(4 * success_amp)
            elif status == "error":
                arm_right_y += 2
            elif status == "idle":
                if sleep_phase == "stirring":
                    step = min(5, int((sleep_elapsed / STIR_SECONDS) * 6))
                    lift = round([-6, -6, -1, -3, 0, 0][step] * startle_amp)
                    arm_left_y += lift
                    arm_right_y += lift
                elif sleep_phase == "asleep":
                    arm_left_y += 2
                    arm_right_y += 2
                elif sleep_phase == "drowsy":
                    arm_left_y += 1
                    arm_right_y += 1

            self.px(cr, ox + 10, oy + arm_left_y, 0, 0, 6, 9, body)
            self.px(cr, ox + 40, oy + arm_right_y, 0, 0, 8, 10, body)

            self.px(cr, ox, oy, 18, 14, 20, 4, body_hi)
            self.px(cr, ox, oy, 14, 18, 28, 21, body)
            self.px(cr, ox, oy, 12, 24, 32, 10, body)
            self.px(cr, ox, oy, 14, 35, 28, 5, body_dark)

            feet = [(16, 40, 4, 8), (24, 40, 4, 6), (32, 40, 4, 6), (40, 40, 4, 8)]
            for foot_idx, (fx, fy, fw, fh) in enumerate(feet):
                fy_offset = 0
                if status == "working":
                    fy_offset = max(1, round(2 * work_amp)) if (t + foot_idx) % 2 else 0
                elif status == "success" and foot_idx in {0, 3}:
                    fy_offset = -round(3 * success_amp) if (t // 2) % 3 == 1 else 0
                self.px(cr, ox, oy, fx, fy + fy_offset, fw, fh, body_dark)

            if status == "working":
                face_shift = -1 if (t // 3) % 2 else 1
                if mood == "reluctant":
                    self.px(cr, ox, oy, 20 + face_shift, 29, 7, 2, eye)
                    self.px(cr, ox, oy, 32 + face_shift, 29, 7, 2, eye)
                    self.px(cr, ox, oy, 20 + face_shift, 25, 7, 2, body_dark)
                    self.px(cr, ox, oy, 32 + face_shift, 25, 7, 2, body_dark)
                else:
                    self.px(cr, ox, oy, 21 + face_shift, 28, 5, 3, eye)
                    self.px(cr, ox, oy, 33 + face_shift, 28, 5, 3, eye)
                self.px(cr, ox, oy, 27 + face_shift, 24, 2, 2, eye)
                self.px(cr, ox, oy, 30 + face_shift, 24, 2, 2, eye)
                self.px(cr, ox, oy, 21 + face_shift, 33, 5, 2, body_dark)
                self.px(cr, ox, oy, 33 + face_shift, 33, 5, 2, body_dark)
            elif status == "success":
                self.px(cr, ox, oy, 21, 28, 4, 3, eye)
                self.px(cr, ox, oy, 33, 28, 4, 3, eye)
            elif status == "error":
                self.px(cr, ox, oy, 18, 22, 6, 2, eye)
                self.px(cr, ox, oy, 33, 22, 6, 2, eye)
                self.px(cr, ox, oy, 21, 28, 4, 3, eye)
                self.px(cr, ox, oy, 33, 27, 4, 5, eye)
                self.px(cr, ox, oy, 44, 15 + (t % 4), 3, 5, sweat)
            else:
                if sleep_phase == "asleep":
                    self.px(cr, ox, oy, 21, 30, 4, 1, eye)
                    self.px(cr, ox, oy, 33, 30, 4, 1, eye)
                elif sleep_phase == "drowsy":
                    self.px(cr, ox, oy, 21, 28, 4, 3, eye)
                    self.px(cr, ox, oy, 33, 28, 4, 3, eye)
                elif sleep_phase == "stirring":
                    step = min(5, int((sleep_elapsed / STIR_SECONDS) * 6))
                    if step in {0, 1}:
                        self.px(cr, ox, oy, 21, 24, 4, 8, eye)
                        self.px(cr, ox, oy, 33, 24, 4, 8, eye)
                    elif step == 3:
                        self.px(cr, ox, oy, 21, 28, 4, 3, eye)
                        self.px(cr, ox, oy, 33, 28, 4, 3, eye)
                    else:
                        self.px(cr, ox, oy, 21, 25, 4, 7, eye)
                        self.px(cr, ox, oy, 33, 25, 4, 7, eye)
                elif t % blink_period in {blink_period - 8, blink_period - 7, blink_period - 6}:
                    self.px(cr, ox, oy, 21, 29, 4, 1, eye)
                    self.px(cr, ox, oy, 33, 29, 4, 1, eye)
                else:
                    self.px(cr, ox, oy, 21, 25, 4, 7, eye)
                    self.px(cr, ox, oy, 33, 25, 4, 7, eye)

            self.draw_mascot_variant(cr, ox, oy, idx, status, sleep_phase, body_hi, body_dark, eye, code)

            if status == "working":
                self.draw_work_fx(cr, ox, oy, t, sweat, code, eye, personality)
            elif status == "success":
                self.draw_success_fx(cr, ox, oy, t, mint, personality)
            elif status == "idle" and sleep_phase == "asleep":
                self.draw_sleep_fx(cr, ox, oy, t, body_hi, personality)
            elif status == "idle" and sleep_phase == "stirring":
                self.draw_startle_fx(cr, ox, oy, sleep_elapsed, body_hi, personality)

        def draw_mascot_variant(self, cr, ox, oy, idx: int, status: str, sleep_phase: str, body_hi, body_dark, eye, code) -> None:
            variant = idx % 8
            if variant == 0:
                self.px(cr, ox, oy, 39, 17, 2, 2, body_hi)
                self.px(cr, ox, oy, 43, 15, 2, 2, body_hi)
                return

            if variant == 1:
                frame = (body_hi[0], body_hi[1], body_hi[2], 0.9)
                self.px(cr, ox, oy, 18, 23, 10, 2, frame)
                self.px(cr, ox, oy, 18, 32, 10, 2, frame)
                self.px(cr, ox, oy, 18, 25, 2, 7, frame)
                self.px(cr, ox, oy, 26, 25, 2, 7, frame)
                self.px(cr, ox, oy, 31, 23, 10, 2, frame)
                self.px(cr, ox, oy, 31, 32, 10, 2, frame)
                self.px(cr, ox, oy, 31, 25, 2, 7, frame)
                self.px(cr, ox, oy, 39, 25, 2, 7, frame)
                self.px(cr, ox, oy, 28, 28, 3, 2, frame)
                return

            if variant == 2:
                self.px(cr, ox, oy, 23, 10, 4, 4, body_dark)
                self.px(cr, ox, oy, 27, 8, 3, 3, body_hi)
                self.px(cr, ox, oy, 30, 10, 3, 4, body_dark)
                return

            if variant == 3:
                glyph = (body_hi[0], body_hi[1], body_hi[2], 0.86)
                self.px(cr, ox, oy, 16, 20, 3, 3, glyph)
                self.px(cr, ox, oy, 20, 20, 6, 2, glyph)
                self.px(cr, ox, oy, 16, 24, 3, 3, glyph)
                return

            if variant == 4:
                self.px(cr, ox, oy, 38, 12, 3, 3, body_hi)
                self.px(cr, ox, oy, 43, 15, 3, 3, body_hi)
                self.px(cr, ox, oy, 41, 19, 3, 3, body_dark)
                return

            if variant == 5:
                if status == "idle" and sleep_phase in {"drowsy", "asleep"}:
                    self.px(cr, ox, oy, 18, 24, 20, 2, body_dark)
                else:
                    self.px(cr, ox, oy, 20, 21, 8, 3, body_dark)
                    self.px(cr, ox, oy, 31, 21, 8, 3, body_dark)
                return

            if variant == 6:
                loop = (body_dark[0], body_dark[1], body_dark[2], 0.88)
                self.px(cr, ox, oy, 45, 28, 3, 3, loop)
                self.px(cr, ox, oy, 48, 25, 3, 3, loop)
                self.px(cr, ox, oy, 51, 28, 3, 3, loop)
                self.px(cr, ox, oy, 48, 31, 3, 3, loop)
                return

            echo = (body_hi[0], body_hi[1], body_hi[2], 0.52)
            self.px(cr, ox, oy, 11, 16, 3, 3, echo)
            self.px(cr, ox, oy, 7, 20, 3, 3, echo)
            self.px(cr, ox, oy, 11, 24, 3, 3, echo)

        def draw_work_fx(self, cr, ox, oy, t: int, sweat, code, eye, personality: dict) -> None:
            work_amp = float(personality["work_amp"])
            mood = str(personality.get("mood", ""))
            self.px(cr, ox, oy, 16, 45, 25, 5, eye)
            for kx, kw, up in [(19, 3, t % 2 == 0), (25, 3, t % 2 == 1), (31, 3, t % 2 == 0), (36, 2, t % 2 == 1)]:
                self.px(cr, ox, oy, kx, 47 - (1 if up else 0), kw, 1, code)

            if mood == "reluctant" and (t // 10) % 4 == 0:
                self.px(cr, ox, oy, 19, 42, 18, 2, (code[0], code[1], code[2], 0.55))
                self.px(cr, ox, oy, 39, 42, 3, 2, (code[0], code[1], code[2], 0.45))
                return

            code_period = max(9, round(13 / max(0.72, work_amp)))
            code_phase = t % code_period
            if code_phase < 8:
                lift = code_phase // 3
                self.px(cr, ox, oy, 17, 40 - lift, 7, 2, code)
                self.px(cr, ox, oy, 26, 38 - lift, 9, 2, code)
            if 3 <= code_phase < 11:
                lift = (code_phase - 3) // 3
                self.px(cr, ox, oy, 37, 40 - lift, 5, 2, code)
                self.px(cr, ox, oy, 34, 36 - lift, 6, 2, code)

            def sweat_packet(start: int, rects: list[tuple[int, int, int, int]], alpha: float) -> None:
                sweat_period = max(12, round(16 / max(0.72, work_amp)))
                phase = (t - start) % sweat_period
                if phase > 7:
                    return
                step = min(3, max(0, phase // 2))
                dx = [0, 1, 4, 9][step]
                dy = [0, -1, -4, -8][step]
                opacity = [0.0, alpha, alpha * 0.85, 0.0][step]
                if opacity <= 0:
                    return
                color = (sweat[0], sweat[1], sweat[2], opacity)
                for rx, ry, rw, rh in rects:
                    self.px(cr, ox, oy, rx + dx, ry + dy, rw, rh, color)

            packet_a = [(42, 14, 2, 2), (45, 16, 2, 2), (48, 18, 2, 2)]
            packet_b = [(42, 12, 1, 1), (45, 14, 1, 1), (48, 16, 1, 1)]
            packet_c = [(42, 19, 1, 1), (45, 21, 1, 1), (48, 23, 1, 1)]
            alpha_mul = min(1.0, 0.72 + work_amp * 0.22)
            for offset in (1, 7):
                sweat_packet(offset, packet_a, 0.95 * alpha_mul)
                sweat_packet(offset + 1, packet_b, 0.82 * alpha_mul)
                sweat_packet(offset + 2, packet_c, 0.70 * alpha_mul)

        def draw_success_fx(self, cr, ox, oy, t: int, mint, personality: dict) -> None:
            if t % 18 > 10:
                return
            spread = round(2 * float(personality["success"]))
            self.px(cr, ox, oy, 9, 12, 2, 6, mint)
            self.px(cr, ox, oy, 7 - spread, 14, 6 + spread, 2, mint)
            self.px(cr, ox, oy, 45, 10, 2, 6, mint)
            self.px(cr, ox, oy, 43, 12, 6 + spread, 2, mint)

        def draw_sleep_fx(self, cr, ox, oy, t: int, body_hi, personality: dict) -> None:
            phase = (t // 5) % 28
            if phase > 18:
                return
            lift = phase // 5
            alpha = 0.85 if phase < 14 else 0.45
            color = (body_hi[0], body_hi[1], body_hi[2], alpha)
            zx = 42 + lift + int(personality["sleep_bob"])
            zy = 7 - lift
            self.px(cr, ox, oy, zx, zy, 8, 2, color)
            self.px(cr, ox, oy, zx + 6, zy + 2, 2, 2, color)
            self.px(cr, ox, oy, zx + 4, zy + 4, 2, 2, color)
            self.px(cr, ox, oy, zx + 2, zy + 6, 2, 2, color)
            self.px(cr, ox, oy, zx, zy + 8, 8, 2, color)

        def draw_startle_fx(self, cr, ox, oy, sleep_elapsed: float, body_hi, personality: dict) -> None:
            if sleep_elapsed > 0.72 * float(personality["startle"]):
                return
            color = (body_hi[0], body_hi[1], body_hi[2], 0.82)
            self.px(cr, ox, oy, 14, 9, 2, 5, color)
            self.px(cr, ox, oy, 10, 15, 5, 2, color)
            self.px(cr, ox, oy, 42, 9, 2, 5, color)
            self.px(cr, ox, oy, 45, 15, 5, 2, color)

        def draw_pixel_slot(self, cr, slot, idx, x, y) -> None:
            state = normalize_state(slot.get("state", "idle"))
            mascot_idx = int(slot.get("mascot_index", idx)) % len(DEFAULT_NAMES)
            mascot_status = self.resolve_mascot_status(slot, idx)
            sleep_phase, sleep_elapsed = self.sleep_phase_for_slot(slot, idx, mascot_status)

            self.round_rect(cr, x + 4, y + 4, SLOT_W - 8, SLOT_H - 8, 9, (0.03, 0.035, 0.044, 0.58))
            self.draw_agent_mascot(cr, mascot_status, sleep_phase, sleep_elapsed, mascot_idx, x + 23, y + 18)

            name = slot.get("name", companion_name(idx))
            if mascot_status == "working":
                label = f"{name} working"
            elif mascot_status == "success":
                label = f"{name} done"
            elif mascot_status == "error":
                label = f"{name} error"
            elif state == "stale":
                label = f"{name} stale"
            else:
                label = f"{name} idle"
            if self.hover_name_idx == idx:
                self.round_rect(cr, x + 8, y + 101, SLOT_W - 16, 21, 6, (0.36, 0.95, 1.0, 0.12))
                self.pbox(cr, x + 18, y + 119, 31, 1, 1, (0.36, 0.95, 1.0, 0.62))
                self.pbox(cr, x + SLOT_W - 23, y + 106, 2, 7, 2, (0.36, 0.95, 1.0, 0.70))
                self.pbox(cr, x + SLOT_W - 19, y + 110, 4, 2, 1, (0.36, 0.95, 1.0, 0.70))
            self.draw_text(cr, label, x + 4, y + 106, SLOT_W - 8, 14, 8.2, (0.94, 0.96, 0.98, 0.95), Pango.Weight.BOLD)
            self.draw_text(
                cr,
                trim_cwd(slot.get("cwd")),
                x + 4,
                y + 120,
                SLOT_W - 8,
                12,
                6.6,
                (0.70, 0.77, 0.83, 0.84),
                Pango.Weight.NORMAL,
            )

        def round_rect(self, cr, x, y, w, h, r, color) -> None:
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
            cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
            cr.set_source_rgba(*color)
            cr.fill()

        def draw_text(self, cr, text, x, y, w, h, size, color, weight) -> None:
            layout = PangoCairo.create_layout(cr)
            layout.set_width(int(w * Pango.SCALE))
            layout.set_height(int(h * Pango.SCALE))
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            layout.set_alignment(Pango.Alignment.CENTER)
            desc = Pango.FontDescription("Sans")
            desc.set_size(int(size * Pango.SCALE))
            desc.set_weight(weight)
            layout.set_font_description(desc)
            layout.set_text(text, -1)
            cr.move_to(x, y)
            cr.set_source_rgba(*color)
            PangoCairo.show_layout(cr, layout)

    win = DotOverlay()
    if win.slots:
        win.show_all()
    else:
        win.hide()

    def remove_pid() -> None:
        try:
            if read_pid() == os.getpid():
                PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def request_quit(*_args) -> None:
        remove_pid()
        Gtk.main_quit()

    signal.signal(signal.SIGTERM, request_quit)
    signal.signal(signal.SIGINT, request_quit)
    Gtk.main()
    remove_pid()
    return 0


def open_mascot_preview() -> int:
    if not MASCOT_PREVIEW_FILE.exists():
        print(f"error: preview file not found: {MASCOT_PREVIEW_FILE}", file=sys.stderr)
        return 1

    preview_uri = MASCOT_PREVIEW_FILE.as_uri()
    print(preview_uri)
    if os.environ.get("DISPLAY"):
        try:
            subprocess.Popen(
                ["xdg-open", preview_uri],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except FileNotFoundError:
            pass
    return 0


def read_mascot_server() -> dict | None:
    try:
        payload = json.loads(MASCOT_SERVER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        pid = int(payload.get("pid"))
        port = int(payload.get("port"))
    except Exception:
        return None
    if not is_running(pid):
        return None
    return {"pid": pid, "port": port}


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def start_mascot_server() -> int:
    ensure_dir()
    existing = read_mascot_server()
    if existing:
        url = f"http://127.0.0.1:{existing['port']}/agent_mascot_preview.html?dev=1"
        print(url)
        return 0

    port = next((candidate for candidate in range(MASCOT_SERVER_PORT, MASCOT_SERVER_PORT + 40) if port_available(candidate)), None)
    if port is None:
        print("error: no available local preview port", file=sys.stderr)
        return 1

    with MASCOT_SERVER_LOG.open("ab", buffering=0) as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(APP_DIR)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )

    payload = {"pid": proc.pid, "port": port, "updated_at": now()}
    MASCOT_SERVER_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    url = f"http://127.0.0.1:{port}/agent_mascot_preview.html?dev=1"
    print(url)
    if os.environ.get("DISPLAY"):
        try:
            subprocess.Popen(
                ["xdg-open", url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except FileNotFoundError:
            pass
    return 0


def stop_mascot_server() -> int:
    existing = read_mascot_server()
    if existing:
        try:
            os.kill(existing["pid"], signal.SIGTERM)
        except OSError:
            pass
    MASCOT_SERVER_FILE.unlink(missing_ok=True)
    return 0


def shuffle_mascots() -> int:
    ASSIGNMENTS_FILE.unlink(missing_ok=True)
    start_overlay()
    print("mascot assignments cleared")
    return 0


def usage() -> int:
    print("usage: codex-dot start|stop|restart|status|names|set-names NAME...|mascot-preview|mascot-server|mascot-server-stop|mascot-shuffle|working|success|done|error|attention|idle|hook-start|hook-stop|overlay")
    return 2


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "start"

    if cmd == "overlay":
        return overlay_main()
    if cmd == "start":
        start_overlay()
        return 0
    if cmd == "stop":
        stop_overlay()
        return 0
    if cmd == "restart":
        stop_overlay()
        time.sleep(0.2)
        start_overlay()
        return 0
    if cmd == "status":
        pid = read_pid()
        slots = display_slots()
        print(
            json.dumps(
                {
                    "running": bool(pid),
                    "pid": pid,
                    "codex_processes": codex_process_count(),
                    "slots": slots,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if cmd == "mascot-preview":
        return open_mascot_preview()
    if cmd == "mascot-server":
        return start_mascot_server()
    if cmd == "mascot-server-stop":
        return stop_mascot_server()
    if cmd == "mascot-shuffle":
        return shuffle_mascots()
    if cmd == "names":
        print(json.dumps({"config": str(CONFIG_FILE), "names": companion_names()}, ensure_ascii=False, indent=2))
        return 0
    if cmd == "set-names":
        names = argv[2:]
        if not names:
            print("error: provide at least one name", file=sys.stderr)
            return 2
        write_config({"names": names})
        start_overlay()
        return 0
    if cmd in {"working", "success", "done", "error", "attention", "idle"}:
        write_state(cmd, source="manual")
        start_overlay()
        return 0
    if cmd == "hook-start":
        write_state("working", source="hook")
        start_overlay()
        return 0
    if cmd == "hook-stop":
        write_state("done", source="hook")
        start_overlay()
        return 0
    return usage()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
