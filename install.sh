#!/usr/bin/env bash
set -euo pipefail

start_overlay=1
if [[ "${1:-}" == "--no-start" ]]; then
  start_overlay=0
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
codex_home="${CODEX_HOME:-$HOME/.codex}"
app_dir="$codex_home/dot-companion"

python3 - <<'PY'
import sys

missing = []
try:
    import cairo  # noqa: F401
except Exception:
    missing.append("python3-cairo")

try:
    import gi
    gi.require_version("Gtk", "3.0")
except Exception:
    missing.extend(["python3-gi", "gir1.2-gtk-3.0"])

if missing:
    print("Missing desktop runtime dependencies:", ", ".join(dict.fromkeys(missing)), file=sys.stderr)
    print("Ubuntu/Debian:", file=sys.stderr)
    print("  sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo", file=sys.stderr)
    raise SystemExit(1)
PY

mkdir -p "$app_dir"
install -m 0755 "$repo_dir/src/codex_dot_companion/codex_dot.py" "$app_dir/codex_dot.py"
install -m 0644 "$repo_dir/src/codex_dot_companion/agent_mascot_preview.html" "$app_dir/agent_mascot_preview.html"

if [[ ! -f "$app_dir/config.json" ]]; then
  printf '{\n  "names": [\n    "Blink",\n    "Pip",\n    "Nib",\n    "Glyph",\n    "Bit",\n    "Nod",\n    "Loop",\n    "Echo"\n  ]\n}\n' > "$app_dir/config.json"
fi

cat > "$app_dir/codex-dot" <<EOF
#!/usr/bin/env bash
exec /usr/bin/python3 "$app_dir/codex_dot.py" "\$@"
EOF
chmod 0755 "$app_dir/codex-dot"

python3 "$repo_dir/scripts/install_hooks.py" "$app_dir/codex-dot"

if [[ "$start_overlay" == "1" ]]; then
  "$app_dir/codex-dot" start
fi

echo "installed Codex dot companion under $app_dir"
echo "try: $app_dir/codex-dot status"

