#!/usr/bin/env python3
"""
Non-destructively merge CrabCodeBar hook config into ~/.claude/settings.json.

Creates a timestamped backup before writing. Safe to run multiple times
(checks for and replaces existing CrabCodeBar hooks by marker or command path).

Usage:
    python3 install_hooks.py              # install / update
    python3 install_hooks.py --uninstall  # remove CrabCodeBar hooks only
"""
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import (  # noqa: E402
    HOOK_EVENTS, HOOK_MARKER, SETTINGS_PATH, atomic_write_json,
)

HOOK_SCRIPT = Path(__file__).resolve().parent / "hook.py"
MAX_BACKUPS = 3


def crab_hook_entry(event):
    cmd = f'python3 "{HOOK_SCRIPT}" --event {event}'
    return {
        "matcher": "*",
        "hooks": [{"type": "command", "command": cmd}],
        "_source": HOOK_MARKER,
    }


def is_crab_entry(entry):
    """Recognize our entries by the _source marker, with legacy fallback."""
    if entry.get("_source") == HOOK_MARKER:
        return True
    # Legacy detection for entries written before the marker was added
    try:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            if "hook.py --event" in cmd:
                return True
    except AttributeError:
        pass
    return False


def load_settings():
    if not SETTINGS_PATH.exists():
        return {}
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"\nError: {SETTINGS_PATH} is not valid JSON: {e}", file=sys.stderr)
        print("Fix or delete it before running install_hooks.py.", file=sys.stderr)
        sys.exit(1)


def backup_settings():
    if not SETTINGS_PATH.exists():
        return None
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = SETTINGS_PATH.with_suffix(f".json.backup-{ts}")
    shutil.copy2(SETTINGS_PATH, backup)
    # Prune: keep only the most recent backups
    backups = sorted(SETTINGS_PATH.parent.glob("settings.json.backup-*"))
    for old in backups[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass
    return backup


def install():
    settings = load_settings()
    settings.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        existing = settings["hooks"].get(event, [])
        # Remove any prior CrabCodeBar entries; keep others as-is
        cleaned = [e for e in existing if not is_crab_entry(e)]
        cleaned.append(crab_hook_entry(event))
        settings["hooks"][event] = cleaned
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(SETTINGS_PATH, settings, indent=2)


def uninstall():
    if not SETTINGS_PATH.exists():
        return
    settings = load_settings()
    hooks = settings.get("hooks", {})
    for event in HOOK_EVENTS:
        existing = hooks.get(event, [])
        cleaned = [e for e in existing if not is_crab_entry(e)]
        if cleaned:
            hooks[event] = cleaned
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    atomic_write_json(SETTINGS_PATH, settings, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    backup = backup_settings()
    if backup:
        print(f"Backed up settings to {backup}")

    if args.uninstall:
        uninstall()
        print(f"Removed CrabCodeBar hooks from {SETTINGS_PATH}")
    else:
        install()
        print(f"Installed CrabCodeBar hooks in {SETTINGS_PATH}")
        print(f"Hook script: {HOOK_SCRIPT}")
        print("Registered events:", ", ".join(HOOK_EVENTS))


if __name__ == "__main__":
    main()
