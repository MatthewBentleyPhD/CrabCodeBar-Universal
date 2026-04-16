#!/usr/bin/env python3
"""
Cross-platform installer for CrabCodeBar Universal.

Handles installation, uninstallation, auto-start registration, and updates
on macOS, Windows, and Linux.

Usage:
    python3 install.py              # install (idempotent)
    python3 install.py --uninstall  # full removal
    python3 install.py --update     # pull latest changes and reinstall
    python3 install.py --no-autostart  # install without auto-start on login
"""
import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PLATFORM = platform.system()

sys.path.insert(0, str(APP_DIR))
from shared import (  # noqa: E402
    AUTOSTART_PATH, PID_PATH, RUNTIME_DIRS, RUNTIME_FILES, STATE_PATH,
)

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CRAB_PY = APP_DIR / "crabcodebar.py"


# ---- Output helpers ----
def info(msg):
    print(f"==> {msg}")


def warn(msg):
    print(f"  [!] {msg}")


def fail(msg):
    print(f"\nError: {msg}", file=sys.stderr)
    sys.exit(1)


# ---- Python check ----
def check_python():
    v = sys.version_info
    if v < (3, 8):
        fail(f"Python 3.8+ required (found {v.major}.{v.minor}.{v.micro})")
    info(f"Python {v.major}.{v.minor}.{v.micro}")


# ---- Dependency installation ----
def install_pip_dep(name, import_name=None):
    """Install a pip package if not already importable."""
    import_name = import_name or name.lower()
    try:
        __import__(import_name)
        info(f"  {name} already installed")
        return
    except ImportError:
        pass
    info(f"  Installing {name}...")
    for extra_args in (["--user"], []):
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", *extra_args, name],
                stdout=subprocess.DEVNULL,
            )
            return
        except subprocess.CalledProcessError:
            continue
    print(f"\nError: Could not install {name}.")
    print("Try installing manually:")
    print(f"  pip3 install {name}")
    sys.exit(1)


def check_linux_system_deps():
    """On Linux, check for system packages needed by pystray/PIL."""
    if PLATFORM != "Linux":
        return
    missing = []
    # pystray on Linux needs an AppIndicator library.
    for mod in ("gi",):
        try:
            __import__(mod)
        except ImportError:
            missing.append("python3-gi (PyGObject)")
    # Check for AppIndicator
    try:
        import gi
        gi.require_version("AppIndicator3", "0.1")
    except (ImportError, ValueError):
        missing.append("gir1.2-appindicator3-0.1")
    if missing:
        warn("Missing Linux system packages:")
        for pkg in missing:
            print(f"       {pkg}")
        print()
        print("  Install with your package manager, e.g.:")
        print("    sudo apt install python3-gi gir1.2-appindicator3-0.1  # Debian/Ubuntu")
        print("    sudo dnf install python3-gobject libappindicator-gtk3  # Fedora")
        print("    sudo pacman -S python-gobject libappindicator-gtk3     # Arch")
        print()
        resp = input("  Continue anyway? [y/N] ").strip().lower()
        if resp != "y":
            sys.exit(1)


def install_deps():
    check_linux_system_deps()
    install_pip_dep("Pillow", "PIL")
    install_pip_dep("pystray", "pystray")
    if PLATFORM == "Darwin":
        install_pip_dep("pyobjc-framework-Cocoa", "AppKit")


# ---- Sprite generation ----
def generate_sprites():
    subprocess.check_call([sys.executable, str(APP_DIR / "generate_sprites.py")])


# ---- Hook installation ----
def install_hooks():
    subprocess.check_call([sys.executable, str(APP_DIR / "install_hooks.py")])


def uninstall_hooks():
    subprocess.check_call([
        sys.executable, str(APP_DIR / "install_hooks.py"), "--uninstall"
    ])


# ---- Auto-start registration ----
def register_autostart():
    """Register CrabCodeBar to start on login."""
    info(f"Registering auto-start ({PLATFORM})...")

    if PLATFORM == "Darwin":
        _register_macos()
    elif PLATFORM == "Windows":
        _register_windows()
    else:
        _register_linux()

    info(f"  Auto-start registered: {AUTOSTART_PATH}")


def _register_macos():
    plist = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>com.crabcodebar</string>
            <key>ProgramArguments</key>
            <array>
                <string>{sys.executable}</string>
                <string>{CRAB_PY}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <false/>
            <key>StandardOutPath</key>
            <string>/tmp/crabcodebar.log</string>
            <key>StandardErrorPath</key>
            <string>/tmp/crabcodebar.log</string>
        </dict>
        </plist>
    """)
    AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_PATH.write_text(plist)


def _register_windows():
    # VBScript wrapper to launch without a visible console window.
    vbs = textwrap.dedent(f"""\
        Set WshShell = CreateObject("WScript.Shell")
        WshShell.Run """{sys.executable}"" ""{CRAB_PY}""", 0, False
    """)
    AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_PATH.write_text(vbs)


def _register_linux():
    desktop = textwrap.dedent(f"""\
        [Desktop Entry]
        Type=Application
        Name=CrabCodeBar
        Exec={sys.executable} {CRAB_PY}
        Hidden=false
        NoDisplay=false
        X-GNOME-Autostart-enabled=true
        Comment=Animated pixel crab companion for Claude Code
    """)
    AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_PATH.write_text(desktop)


def remove_autostart():
    if AUTOSTART_PATH.exists():
        AUTOSTART_PATH.unlink()
        info(f"  Removed auto-start: {AUTOSTART_PATH}")
    else:
        info("  No auto-start entry found")


# ---- Process management ----
def kill_running():
    """Kill any running CrabCodeBar process via PID file."""
    try:
        pid = int(PID_PATH.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.1)
        info(f"  Stopped running instance (PID {pid})")
    except OSError:
        pass


# ---- State file cleanup ----
def clean_state_files():
    """Remove all CrabCodeBar runtime files and directories."""
    for f in RUNTIME_FILES:
        try:
            f.unlink()
        except (FileNotFoundError, OSError):
            pass
    for d in RUNTIME_DIRS:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    info("  Removed state and config files")


# ---- Updater ----
def update():
    """Pull latest changes from git remote and reinstall."""
    if not (APP_DIR / ".git").exists():
        # Check if parent is the git root (installed inside a larger repo)
        git_dir = APP_DIR
        while git_dir != git_dir.parent:
            if (git_dir / ".git").exists():
                break
            git_dir = git_dir.parent
        else:
            fail("Not a git repository. Download the latest version manually.")

    info("Pulling latest changes...")
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            warn("git pull failed:")
            print(result.stderr.strip())
            fail("Could not update. Try pulling manually.")
        if "Already up to date" in result.stdout:
            info("  Already up to date")
        else:
            print(result.stdout.strip())
    except FileNotFoundError:
        fail("git not found. Install git and try again.")

    info("Reinstalling...")
    kill_running()
    install_deps()
    generate_sprites()
    install_hooks()
    info("Update complete. Restart the tray app to use the new version.")


# ---- Main flows ----
def do_install(autostart=True):
    info(f"Installing CrabCodeBar Universal ({PLATFORM})...")
    print()

    info("Checking Python version...")
    check_python()

    info("Checking dependencies...")
    install_deps()

    info("Generating sprites...")
    generate_sprites()

    info("Installing Claude Code hooks...")
    install_hooks()

    if autostart:
        register_autostart()
    else:
        info("Skipping auto-start registration (--no-autostart)")

    print()
    info("Installed!")
    info(f"Run the tray app:  python3 {CRAB_PY}")
    info("The crab will appear in your system tray.")
    info("To stop: right-click the crab > Quit")
    if autostart:
        info("CrabCodeBar will start automatically on login.")
        info("To disable auto-start, run:  python3 install.py --no-autostart")


def do_uninstall():
    info("Uninstalling CrabCodeBar Universal...")
    print()

    info("Stopping running instance...")
    kill_running()

    info("Removing Claude Code hooks...")
    uninstall_hooks()

    info("Removing auto-start...")
    remove_autostart()

    info("Cleaning up state files...")
    clean_state_files()

    print()
    info("Uninstalled.")
    info("The CrabCodeBar application folder has NOT been deleted.")
    info(f"To fully remove, delete: {APP_DIR}")


def main():
    parser = argparse.ArgumentParser(
        description="Install, uninstall, or update CrabCodeBar Universal."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--uninstall", action="store_true",
                       help="Full uninstall (hooks, auto-start, state files)")
    group.add_argument("--update", action="store_true",
                       help="Pull latest from git and reinstall")
    parser.add_argument("--no-autostart", action="store_true",
                        help="Skip auto-start registration during install")
    args = parser.parse_args()

    if args.uninstall:
        do_uninstall()
    elif args.update:
        update()
    else:
        do_install(autostart=not args.no_autostart)


if __name__ == "__main__":
    main()
