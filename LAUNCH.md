# Launch Notes

Use these when sharing Codex Dot Companion publicly.

## Short Post

I made a tiny desktop mascot overlay for Codex.

One running Codex terminal gets one companion. It works while Codex works, rests
when that session is idle, and keeps the same character for the life of the
Codex process.

It runs locally, uses Codex hooks plus local session logs, and does not send
telemetry.

Install:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo
pipx install git+https://github.com/okj1223/codex-dot-companion.git
codex-dot-install
```

https://github.com/okj1223/codex-dot-companion

## Show HN

Title:

```text
Show HN: Codex Dot Companion - tiny desktop mascots for Codex sessions
```

Body:

```text
I built a small local desktop overlay for Codex sessions.

Each running Codex terminal gets a tiny pixel companion. It animates while Codex
is working, rests when the session is idle, and keeps the same character for the
life of the Codex process.

It is a Python/GTK overlay. It reads local process metadata, Codex hooks, and
local session logs. It does not send telemetry or make network requests.

The fun install path is to paste the repo URL into Codex and ask it to install
the GTK/Cairo dependencies, run codex-dot-install, and verify codex-dot status.
Manual install is in the README.
```

## Good GitHub Topics

```text
codex
openai-codex
python
gtk
desktop-overlay
mascot
cli-tool
developer-tools
```
