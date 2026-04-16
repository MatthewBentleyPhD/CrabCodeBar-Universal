"""Shared constants and helpers for CrabCodeBar Universal.

Single source of truth for values used across hook.py, crabcodebar.py,
install_hooks.py, and generate_sprites.py. Import from here instead of
redefining locally.

Cross-platform: works on macOS, Windows, and Linux.
"""
import json
import os
import platform
import signal
import subprocess
import tempfile
import time
from pathlib import Path

PLATFORM = platform.system()  # "Darwin", "Windows", "Linux"

# ---- Paths ----
STATE_DIR = Path.home() / ".claude" / "state"
STATE_PATH = STATE_DIR / "crab.json"
CONFIG_PATH = STATE_DIR / "crab-config.json"
PID_PATH = STATE_DIR / "crab.pid"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# ---- Auto-start paths (platform-dependent) ----
APP_NAME = "CrabCodeBar"
if PLATFORM == "Darwin":
    AUTOSTART_PATH = Path.home() / "Library" / "LaunchAgents" / "com.crabcodebar.plist"
elif PLATFORM == "Windows":
    AUTOSTART_PATH = (
        Path(os.environ.get("APPDATA", Path.home()))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        / "CrabCodeBar.vbs"
    )
else:
    AUTOSTART_PATH = Path.home() / ".config" / "autostart" / "crabcodebar.desktop"

# Files created at runtime that a full uninstall should clean up.
RUNTIME_FILES = [
    STATE_PATH,
    CONFIG_PATH,
    PID_PATH,
    STATE_DIR / "crab-approval-sound.lock",
]
RUNTIME_DIRS = [
    STATE_DIR / "crab-sprites",
]

# ---- Sprite body colors (RGB) ----
# generate_sprites.py draws with these; crabcodebar.py tints by matching them.
BODY = (217, 119, 87)
BODY_DARK = (168, 83, 59)

# ---- Hook events ----
# Ordered list so install_hooks.py can iterate deterministically.
HOOK_EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "SessionEnd",
]

# Tools that always pause for user input. A PreToolUse for one of these is
# treated like Notification (jumping crab + approval sound). This is the
# primary "waiting for approval" signal in the VSCode native extension,
# which does not fire the Notification hook.
APPROVAL_TOOLS = {"AskUserQuestion", "ExitPlanMode"}

# ---- Sounds ----
# Names map to macOS system sounds in /System/Library/Sounds/. On other
# platforms, only "None" and a generic system beep are supported for now.
SOUND_NAMES = [
    "None",
    "Basso", "Blow", "Bottle", "Frog", "Funk", "Glass", "Hero",
    "Morse", "Ping", "Pop", "Purr", "Sosumi", "Submarine", "Tink",
]
ALLOWED_SOUNDS = set(SOUND_NAMES)
DEFAULT_SOUND = "Tink"
SOUND_EVENT_KEY = {
    "Notification": "sound_approval",
    "Stop":         "sound_finished",
}

# ---- Hook entry marker ----
HOOK_MARKER = "crabcodebar"


# ---- Helpers ----
def read_json(path, default=None):
    """Read and parse a JSON file. Returns default on any failure."""
    if default is None:
        default = {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def atomic_write_json(path, data, indent=None):
    """Atomic JSON write via temp file + rename on the same filesystem.

    Sets file permissions to 0o600 (owner-only) on POSIX systems.
    Refuses to write through symlinks at the target path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to follow symlinks at the target path
    if path.is_symlink():
        path.unlink()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".crab.", suffix=".tmp")
    try:
        os.chmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)
            if indent:
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def kill_pid_file(pid_path=None, wait_iters=10, verbose=False):
    """Kill a process identified by a PID file. Used by both the tray app
    (kill-and-replace on startup) and the installer (stop running instance).

    Returns True if a process was killed, False otherwise.
    """
    if pid_path is None:
        pid_path = PID_PATH
    try:
        pid = int(Path(pid_path).read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return False
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(wait_iters):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.1)
        if verbose:
            print(f"  Stopped running instance (PID {pid})")
        return True
    except PermissionError:
        import sys
        print(f"CrabCodeBar: SIGTERM refused for PID {pid}; "
              "PID file may be stale", file=sys.stderr)
        return False
    except OSError:
        return False


def play_sound(name):
    """Play a named notification sound. Cross-platform, non-blocking, best-effort.

    On macOS: plays the matching system sound from /System/Library/Sounds/.
    On Windows: plays a system alert beep (sound name is ignored beyond None).
    On Linux: tries freedesktop notification sounds via paplay or aplay.
    """
    if not name or name == "None":
        return
    try:
        if PLATFORM == "Darwin":
            _play_macos(name)
        elif PLATFORM == "Windows":
            _play_windows(name)
        else:
            _play_linux(name)
    except Exception:
        pass


def _play_macos(name):
    sound_path = f"/System/Library/Sounds/{name}.aiff"
    if os.path.exists(sound_path):
        subprocess.Popen(
            ["afplay", sound_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _play_windows(name):
    import winsound
    # Map a few names to Windows system sounds; everything else gets a beep.
    win_map = {
        "Basso": winsound.MB_ICONHAND,
        "Funk": winsound.MB_ICONEXCLAMATION,
        "Glass": winsound.MB_ICONASTERISK,
        "Hero": winsound.MB_ICONASTERISK,
        "Ping": winsound.MB_ICONASTERISK,
        "Pop": winsound.MB_OK,
        "Tink": winsound.MB_OK,
    }
    winsound.MessageBeep(win_map.get(name, winsound.MB_OK))


def _play_linux(name):
    import shutil
    # Try common freedesktop notification sounds.
    candidates = [
        "/usr/share/sounds/freedesktop/stereo/bell.oga",
        "/usr/share/sounds/freedesktop/stereo/complete.oga",
        "/usr/share/sounds/freedesktop/stereo/message.oga",
    ]
    sound_file = None
    for path in candidates:
        if os.path.exists(path):
            sound_file = path
            break
    if not sound_file:
        return
    for player in ("paplay", "aplay", "ogg123"):
        if shutil.which(player):
            subprocess.Popen(
                [player, sound_file],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
