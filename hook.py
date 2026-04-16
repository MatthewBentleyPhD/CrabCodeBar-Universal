#!/usr/bin/env python3
"""
CrabCodeBar hook handler. One script, seven hook events.

Invoked by Claude Code with --event <EventName>. Reads the hook payload from
stdin (JSON, but we mostly ignore it). Writes the current event + timestamp
atomically to ~/.claude/state/crab.json.

The tray app consumes that file and derives the crab state.

Also plays an optional system sound on Notification (approval-needed),
PreToolUse for blocking tools (VSCode-extension fallback), and Stop (task
finished) events, based on the user's crab-config.json selection.

Cross-platform: works on macOS, Windows, and Linux.

Exits 0 quickly so it never blocks Claude Code. Silent on success.
"""
import json
import sys
import time
from pathlib import Path

# Ensure shared.py is importable when invoked by full path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import (  # noqa: E402
    ALLOWED_SOUNDS, APPROVAL_TOOLS, CONFIG_PATH, DEFAULT_SOUND,
    HOOK_EVENTS, SOUND_EVENT_KEY, STATE_PATH, atomic_write_json,
    play_sound, read_json,
)

VALID_EVENTS = set(HOOK_EVENTS)
MAX_FIELD_LEN = 256

APPROVAL_SOUND_LOCK = STATE_PATH.parent / "crab-approval-sound.lock"

# Dedupe window for approval sounds. In terminal Claude Code, both
# Notification and PreToolUse (for AskUserQuestion/ExitPlanMode) fire, so
# without this lock the same approval moment would play the sound twice.
APPROVAL_SOUND_DEDUPE_SEC = 3


def approval_sound_recently_played():
    """True if another hook invocation played an approval sound in the last
    APPROVAL_SOUND_DEDUPE_SEC seconds."""
    try:
        age = time.time() - APPROVAL_SOUND_LOCK.stat().st_mtime
        return age < APPROVAL_SOUND_DEDUPE_SEC
    except (FileNotFoundError, OSError):
        return False


def mark_approval_sound_played():
    try:
        APPROVAL_SOUND_LOCK.touch()
    except OSError:
        pass


def play_sound_for_event(event, tool_name=None):
    """Play the user-configured sound for this event, if any. Non-blocking."""
    key = SOUND_EVENT_KEY.get(event)
    if key is None and event == "PreToolUse" and tool_name in APPROVAL_TOOLS:
        # VSCode-extension fallback: Notification doesn't fire, so treat
        # blocking tool calls as the approval signal.
        key = "sound_approval"
    if key is None:
        return
    # Dedupe approval sounds: in terminal Claude Code both Notification and
    # PreToolUse fire for the same approval moment. First one in wins.
    if key == "sound_approval" and approval_sound_recently_played():
        return
    cfg = read_json(CONFIG_PATH)
    name = cfg.get(key, DEFAULT_SOUND)
    if name not in ALLOWED_SOUNDS or name == "None":
        return
    play_sound(name)
    if key == "sound_approval":
        mark_approval_sound_played()


def _safe_str(val):
    """Return val if it's a short string, else None."""
    if isinstance(val, str) and len(val) <= MAX_FIELD_LEN:
        return val
    return None


def read_payload():
    """Best-effort read of Claude Code hook JSON payload from stdin."""
    if sys.stdin.isatty():
        return {}
    try:
        data = sys.stdin.read(65536)  # 64 KB hard cap
        if not data.strip():
            return {}
        return json.loads(data)
    except (json.JSONDecodeError, ValueError, OSError):
        return {}


def main():
    # Fast arg parse: exactly --event <name>, no argparse import needed.
    try:
        idx = sys.argv.index("--event")
        event = sys.argv[idx + 1]
    except (ValueError, IndexError):
        print("Usage: hook.py --event <EventName>", file=sys.stderr)
        sys.exit(1)

    if event not in VALID_EVENTS:
        print(f"CrabCodeBar hook: unknown event '{event}'", file=sys.stderr)
        sys.exit(0)  # exit 0 so Claude Code is not blocked

    payload = read_payload()
    session_id = _safe_str(payload.get("session_id"))
    tool_name = _safe_str(payload.get("tool_name"))
    stop_reason = _safe_str(payload.get("stop_reason"))

    state = {
        "last_event": event,
        "last_event_timestamp": time.time(),
        "session_id": session_id,
    }
    if tool_name is not None:
        state["tool_name"] = tool_name
    if stop_reason is not None:
        state["stop_reason"] = stop_reason

    try:
        atomic_write_json(STATE_PATH, state)
    except Exception as e:
        # Never fail loudly -- don't block Claude Code if disk is full etc.
        print(f"CrabCodeBar hook: {e}", file=sys.stderr)
        sys.exit(0)

    # Play sound after state is recorded. Failures here are swallowed too.
    try:
        play_sound_for_event(event, tool_name)
    except Exception:
        pass


if __name__ == "__main__":
    main()
