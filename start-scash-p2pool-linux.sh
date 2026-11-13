#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# If double-clicked or right-clicked -> "Run" from a Linux file manager (Nemo, Nautilus, Dolphin, Thunar)
# with no terminal window attached, re-launch automatically inside a visible 128x42 desktop terminal!
has_no_banner=0
for _arg in "$@"; do
    if [ "$_arg" = "--no-banner" ] || [ "$_arg" = "--headless" ]; then
        has_no_banner=1
    fi
done

if [ "$has_no_banner" -eq 0 ] && [ ! -t 0 ] && [ ! -t 1 ] && [ -z "${SCASH_IN_TERM:-}" ] && [ -z "${CI:-}" ] && [ -z "${GITHUB_ACTIONS:-}" ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    export SCASH_IN_TERM=1
    SELF="$DIR/start-scash-p2pool-linux.sh"
    if command -v gnome-terminal >/dev/null 2>&1; then
        exec gnome-terminal --geometry=128x42 --title="Scash P2Pool (QtKawaii v0.2.0)" -- "$SELF" "$@"
    elif command -v mate-terminal >/dev/null 2>&1; then
        exec mate-terminal --geometry=128x42 --title="Scash P2Pool (QtKawaii v0.2.0)" -x "$SELF" "$@"
    elif command -v xfce4-terminal >/dev/null 2>&1; then
        exec xfce4-terminal --geometry=128x42 --title="Scash P2Pool (QtKawaii v0.2.0)" -x "$SELF" "$@"
    elif command -v konsole >/dev/null 2>&1; then
        exec konsole -p "TerminalColumns=128" -p "TerminalRows=42" -e "$SELF" "$@"
    elif command -v tilix >/dev/null 2>&1; then
        exec tilix -e "$SELF" "$@"
    elif command -v kitty >/dev/null 2>&1; then
        exec kitty -o initial_window_width=128c -o initial_window_height=42c --title="Scash P2Pool (QtKawaii v0.2.0)" "$SELF" "$@"
    elif command -v alacritty >/dev/null 2>&1; then
        exec alacritty -o window.dimensions.columns=128 -o window.dimensions.lines=42 -T "Scash P2Pool (QtKawaii v0.2.0)" -e "$SELF" "$@"
    elif command -v lxterminal >/dev/null 2>&1; then
        exec lxterminal --geometry=128x42 -t "Scash P2Pool (QtKawaii v0.2.0)" -e "$SELF" "$@"
    elif command -v x-terminal-emulator >/dev/null 2>&1; then
        exec x-terminal-emulator -e "$SELF" "$@"
    elif command -v xterm >/dev/null 2>&1; then
        exec xterm -geometry 128x42 -T "Scash P2Pool (QtKawaii v0.2.0)" -e "$SELF" "$@"
    fi
fi

export LD_LIBRARY_PATH="$DIR:$DIR/node/lib:$DIR/miner/lib:${LD_LIBRARY_PATH:-}"
if [ -x "$DIR/runtime/pypy2/bin/pypy" ]; then
    "$DIR/runtime/pypy2/bin/pypy" "$DIR/start_scash_p2pool.py" "$@"
elif command -v pypy >/dev/null 2>&1; then
    pypy "$DIR/start_scash_p2pool.py" "$@"
elif command -v python3 >/dev/null 2>&1; then
    python3 "$DIR/start_scash_p2pool.py" "$@"
else
    python "$DIR/start_scash_p2pool.py" "$@"
fi
rc=$?
if [ "$rc" -ne 0 ] && [ -n "${SCASH_IN_TERM:-}" ]; then
    echo ""
    echo "[NOTICE] Scash P2Pool exited with code $rc. Press Enter to close..."
    read -r _
fi
exit "$rc"
