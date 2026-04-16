#!/usr/bin/env python3
"""
CrabCodeBar Universal -- cross-platform system tray crab.

Uses pystray to render an animated pixel crab in the system tray on macOS,
Windows, and Linux. Watches ~/.claude/state/crab.json (written by hook.py)
and derives the crab's behavioral state from Claude Code session activity.

States:
    asleep           no activity for idle_timeout seconds (default 5 min)
    waiting          session idle but recent (<idle_timeout)
    working          active tool use / prompt submission
    jumping-approval Notification or blocking tool (needs user input)
    jumping-finished Stop event (task completed)

Run directly:  python3 crabcodebar.py
Stop:           click tray icon > Quit (or Ctrl+C in terminal)
"""
import atexit
import os
import platform
import signal
import sys
import time
import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image

IS_MACOS = platform.system() == "Darwin"

_APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_APP_DIR))
from shared import (  # noqa: E402
    APPROVAL_TOOLS, BODY, BODY_DARK, CONFIG_PATH, DEFAULT_SOUND,
    PID_PATH, SOUND_NAMES, STATE_PATH, atomic_write_json, read_json,
)


# ---- Single-instance (kill-and-replace) ----
def _kill_existing():
    """If another CrabCodeBar process is running, kill it before starting."""
    try:
        pid = int(PID_PATH.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return
    if pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
        # Brief wait for clean shutdown
        for _ in range(10):
            try:
                os.kill(pid, 0)  # probe, no signal sent
            except OSError:
                break
            time.sleep(0.1)
    except OSError:
        pass  # process already gone


def _write_pid():
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))


def _remove_pid():
    try:
        # Only remove if it's still ours
        if PID_PATH.exists() and int(PID_PATH.read_text().strip()) == os.getpid():
            PID_PATH.unlink()
    except (ValueError, OSError):
        pass

# ---- Paths ----
SPRITE_DIR = _APP_DIR / "sprites"
SPRITE_CACHE_DIR = STATE_PATH.parent / "crab-sprites"

# ---- Donation link ----
COFFEE_URL = "https://paypal.me/bentleymaja"

# ---- User-selectable color palettes ----
# Each entry is (primary_body, dark_body) or None for "use sprite as-is."
COLOR_PALETTES = {
    "orange": None,
    "yellow": ((230, 190, 70),  (170, 135, 50)),
    "green":  ((104, 190, 104), (64, 140, 64)),
    "teal":   ((80, 180, 180),  (50, 130, 130)),
    "blue":   ((87, 142, 217),  (59, 99, 168)),
    "purple": ((155, 100, 200), (110, 70, 150)),
    "pink":   ((236, 125, 168), (186, 80, 125)),
    "red":    ((239, 68, 68),   (179, 50, 50)),
    "brown":  ((140, 95, 60),   (95, 60, 35)),
    "grey":   ((150, 150, 150), (95, 95, 95)),
    "black":  ((50, 50, 50),    (25, 25, 25)),
}

# ---- State machine ----
STATE_FRAMES = {
    "working":          [f"working_{i}" for i in range(3)],
    "jumping-approval": [f"jumping_{i}" for i in range(4)],
    "jumping-finished": [f"jumping_{i}" for i in range(4)],
    "waiting":          [f"waiting_{i}" for i in range(3)],
    "asleep":           [f"asleep_{i}"  for i in range(2)],
}

IDLE_TIMEOUT_DEFAULT = 300
STOP_CHEER_SEC = 20
FINISHED_CHEER_SEC = 4

IDLE_TIMEOUT_OPTIONS = {
    "30 sec":  30,
    "2 min":   120,
    "5 min":   300,
    "15 min":  900,
    "30 min":  1800,
    "1 hour":  3600,
    "Never":   0,
}


# ---- Sprite helpers ----
def build_sprite_cache(color):
    """Render tinted PNGs for `color` into the cache dir. Skips fresh frames."""
    tint = COLOR_PALETTES.get(color)
    if tint is None:
        return
    cache = SPRITE_CACHE_DIR / color
    cache.mkdir(parents=True, exist_ok=True)
    primary, dark = tint
    for frames in STATE_FRAMES.values():
        for name in frames:
            out = cache / f"{name}.png"
            src = SPRITE_DIR / f"{name}.png"
            try:
                if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
                    continue
            except OSError:
                pass
            img = Image.open(src).convert("RGBA")
            px = img.load()
            for y in range(img.height):
                for x in range(img.width):
                    r, g, b, a = px[x, y]
                    if (r, g, b) == BODY:
                        px[x, y] = (*primary, a)
                    elif (r, g, b) == BODY_DARK:
                        px[x, y] = (*dark, a)
            img.save(out, format="PNG")


# Crop ~15% off top and bottom so the crab fills more of the tray icon.
# Some animation extremes (max-height jump tip, sleep-pose feet) clip
# slightly, which is an acceptable trade-off for a larger icon.
CROP_TOP = 6     # pixels from top edge  (~15% of 39)
CROP_BOTTOM = 6  # pixels from bottom edge


def load_frame(color, frame_name):
    """Return a PIL Image for the given color and frame name, cropped for tray."""
    tint = COLOR_PALETTES.get(color)
    if tint is None:
        img = Image.open(SPRITE_DIR / f"{frame_name}.png").convert("RGBA")
    else:
        cache_path = SPRITE_CACHE_DIR / color / f"{frame_name}.png"
        src_path = SPRITE_DIR / f"{frame_name}.png"
        try:
            if cache_path.exists() and cache_path.stat().st_mtime >= src_path.stat().st_mtime:
                img = Image.open(cache_path).convert("RGBA")
            else:
                raise OSError
        except OSError:
            build_sprite_cache(color)
            try:
                img = Image.open(cache_path).convert("RGBA")
            except OSError:
                img = Image.open(src_path).convert("RGBA")
    w, h = img.size
    return img.crop((0, CROP_TOP, w, h - CROP_BOTTOM))


# ---- State derivation ----
def derive_state(data, idle_timeout=IDLE_TIMEOUT_DEFAULT):
    """Return (state_name, last_event, elapsed_seconds)."""
    last_event = data.get("last_event")
    ts = data.get("last_event_timestamp")
    tool_name = data.get("tool_name")
    stop_reason = data.get("stop_reason")

    if last_event is None or ts is None:
        return "asleep", None, 0

    now = time.time()
    elapsed = now - ts

    if last_event == "SessionEnd":
        return "asleep", last_event, elapsed
    if idle_timeout and elapsed > idle_timeout:
        return "asleep", last_event, elapsed
    if last_event == "Notification":
        return "jumping-approval", last_event, elapsed
    if last_event == "PreToolUse" and tool_name in APPROVAL_TOOLS:
        return "jumping-approval", last_event, elapsed
    if last_event == "Stop":
        cheer = FINISHED_CHEER_SEC if stop_reason == "end_turn" else STOP_CHEER_SEC
        state = "jumping-finished" if elapsed < cheer else "waiting"
        return state, last_event, elapsed
    # All other events (PreToolUse, PostToolUse, UserPromptSubmit,
    # SessionStart) mean Claude is working. Stay in "working" until a
    # state-changing event (Stop, Notification, SessionEnd) arrives or
    # idle_timeout expires.
    return "working", last_event, elapsed


# ---- Tray application ----
class CrabTray:
    def __init__(self):
        self.cfg = self._read_config()
        self.icon = None
        self._running = True

    def _read_config(self):
        defaults = {
            "color": "orange",
            "sound_approval": DEFAULT_SOUND,
            "sound_finished": DEFAULT_SOUND,
            "idle_timeout": IDLE_TIMEOUT_DEFAULT,
        }
        return {**defaults, **read_json(CONFIG_PATH)}

    def _save_config(self):
        atomic_write_json(CONFIG_PATH, self.cfg)

    # ---- Menu action factories ----
    def _make_set_color(self, color):
        def callback(icon, item):
            self.cfg["color"] = color
            self._save_config()
            build_sprite_cache(color)
        return callback

    def _make_set_sound(self, key, name):
        def callback(icon, item):
            self.cfg[key] = name
            self._save_config()
        return callback

    def _make_set_timeout(self, secs):
        def callback(icon, item):
            self.cfg["idle_timeout"] = secs
            self._save_config()
        return callback

    @staticmethod
    def _open_coffee(icon, item):
        webbrowser.open(COFFEE_URL)

    def _quit(self, icon, item):
        self._running = False
        icon.stop()

    # ---- Menu ----
    def _build_menu(self):
        color_items = tuple(
            pystray.MenuItem(
                c.capitalize(),
                self._make_set_color(c),
                checked=lambda item, c=c: self.cfg.get("color", "orange") == c,
            )
            for c in COLOR_PALETTES
        )

        approval_items = tuple(
            pystray.MenuItem(
                n,
                self._make_set_sound("sound_approval", n),
                checked=lambda item, n=n: self.cfg.get("sound_approval", DEFAULT_SOUND) == n,
            )
            for n in SOUND_NAMES
        )

        finished_items = tuple(
            pystray.MenuItem(
                n,
                self._make_set_sound("sound_finished", n),
                checked=lambda item, n=n: self.cfg.get("sound_finished", DEFAULT_SOUND) == n,
            )
            for n in SOUND_NAMES
        )

        timeout_items = tuple(
            pystray.MenuItem(
                label,
                self._make_set_timeout(secs),
                checked=lambda item, s=secs: self.cfg.get("idle_timeout", IDLE_TIMEOUT_DEFAULT) == s,
            )
            for label, secs in IDLE_TIMEOUT_OPTIONS.items()
        )

        return pystray.Menu(
            pystray.MenuItem("Sprite Color", pystray.Menu(*color_items)),
            pystray.MenuItem("Approval Sound", pystray.Menu(*approval_items)),
            pystray.MenuItem("Finished Sound", pystray.Menu(*finished_items)),
            pystray.MenuItem("Sleep After", pystray.Menu(*timeout_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Buy me a coffee", self._open_coffee),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    # ---- macOS direct icon setter ----
    _MENU_BAR_ICON_HEIGHT = 22.0  # points (standard macOS menu bar icon height)

    def _set_icon_macos(self, pil_img):
        """Bypass pystray's image conversion on macOS.

        pystray resizes every image to 22x22 (squashing the aspect ratio
        and shrinking the crab). This method converts the PIL image to an
        NSImage directly, then sets the point size so the icon fills the
        full menu bar height while preserving the aspect ratio.

        The setImage: call is dispatched to the main thread via
        performSelectorOnMainThread so the update renders on all displays,
        not just the active monitor.
        """
        import io
        from AppKit import NSImage as _NSImage, NSData
        from Foundation import NSSize

        # PIL -> PNG bytes -> NSImage (preserves full pixel dimensions)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        ns_data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
        ns_img = _NSImage.alloc().initWithData_(ns_data)

        # Scale point size so height fills the menu bar, width follows aspect.
        pw, ph = pil_img.size
        aspect = pw / ph
        h_pts = self._MENU_BAR_ICON_HEIGHT
        ns_img.setSize_(NSSize(h_pts * aspect, h_pts))

        # Dispatch to main thread so the image updates on all monitors.
        button = self.icon._status_item.button()
        button.performSelectorOnMainThread_withObject_waitUntilDone_(
            "setImage:", ns_img, False,
        )

    def _set_icon(self, pil_img):
        """Set the tray icon from a PIL image. Uses platform-native path on
        macOS to preserve correct sizing; falls back to pystray on others."""
        if IS_MACOS:
            try:
                self._set_icon_macos(pil_img)
                return
            except Exception:
                pass
        self.icon.icon = pil_img

    # ---- Animation loop (runs in background thread) ----
    def _update_loop(self):
        while self._running:
            try:
                data = read_json(STATE_PATH)
                idle_timeout = self.cfg.get("idle_timeout", IDLE_TIMEOUT_DEFAULT)
                state, last_event, elapsed = derive_state(data, idle_timeout)

                frames = STATE_FRAMES[state]
                frame_idx = int(time.time()) % len(frames)
                frame_name = frames[frame_idx]

                color = self.cfg.get("color", "orange")
                if color not in COLOR_PALETTES:
                    color = "orange"

                img = load_frame(color, frame_name)

                if self.icon:
                    self._set_icon(img)
                    if last_event:
                        self.icon.title = (
                            f"CrabCodeBar: {state} "
                            f"({last_event}, {elapsed:.0f}s ago)"
                        )
                    else:
                        self.icon.title = "CrabCodeBar: no activity"
            except Exception:
                pass

            time.sleep(1)

    # ---- Entry point ----
    def run(self):
        color = self.cfg.get("color", "orange")
        if color not in COLOR_PALETTES:
            color = "orange"
        initial = load_frame(color, "asleep_0")

        self.icon = pystray.Icon(
            "CrabCodeBar",
            icon=initial,
            title="CrabCodeBar",
            menu=self._build_menu(),
        )

        thread = threading.Thread(target=self._update_loop, daemon=True)
        thread.start()

        # Blocks until icon.stop() is called.
        self.icon.run()


def main():
    if not SPRITE_DIR.exists():
        print(f"Sprites not found at {SPRITE_DIR}")
        print("Run: python3 generate_sprites.py")
        sys.exit(1)

    _kill_existing()
    _write_pid()
    atexit.register(_remove_pid)

    # Graceful shutdown on SIGTERM (e.g., from a new instance replacing us).
    def _handle_term(signum, frame):
        _remove_pid()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _handle_term)

    CrabTray().run()


if __name__ == "__main__":
    main()
