# Codex Dot Companion

Tiny desktop mascot overlay for Codex sessions.

It shows one small pixel companion per running Codex process. Each terminal keeps the
same companion while that Codex process is alive, and a new companion can be assigned
when Codex is started again.

## What It Installs

- `~/.codex/dot-companion/codex_dot.py`
- `~/.codex/dot-companion/agent_mascot_preview.html`
- `~/.codex/dot-companion/codex-dot`
- Codex hooks in `~/.codex/hooks.json`

Runtime files such as `state.json`, `assignments.json`, logs, and pid files stay local
and are not part of this repository.

## Install From A Clone

```bash
git clone https://github.com/okj1223/codex-dot-companion.git
cd codex-dot-companion
./install.sh
```

On Ubuntu/Debian, the overlay needs GTK/Cairo Python bindings:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo
```

Install without starting the overlay:

```bash
./install.sh --no-start
```

## Commands

```bash
~/.codex/dot-companion/codex-dot status
~/.codex/dot-companion/codex-dot restart
~/.codex/dot-companion/codex-dot idle
~/.codex/dot-companion/codex-dot working
~/.codex/dot-companion/codex-dot mascot-server
```

The preview server prints a local URL for the browser roster.

## Optional pipx Install

```bash
pipx install git+https://github.com/okj1223/codex-dot-companion.git
codex-dot-install
```

`codex-dot-install` copies the preview HTML into `~/.codex/dot-companion`, merges the
Codex hooks, and starts the overlay.

## Git Push Flow

If this directory is not a git repo yet:

```bash
cd /home/okj/workspace/codex-dot-companion
git init
git add .
git commit -m "Package Codex dot companion"
```

Create a GitHub repo and push:

```bash
gh repo create codex-dot-companion --private --source=. --remote=origin --push
```

Or push to an existing remote:

```bash
git remote add origin git@github.com:okj1223/codex-dot-companion.git
git branch -M main
git push -u origin main
```

## Notes

- The installer backs up an existing `~/.codex/hooks.json` before writing.
- Existing non-companion hooks are preserved.
- Companion hooks are replaced to avoid duplicates.
- `CODEX_HOME` is supported for testing or non-default Codex config locations.

