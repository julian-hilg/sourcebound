"""A desktop icon that starts the web view (`sb ui`): offered by `sb init`, made by `sb install shortcut`.

Windows: a shortcut (.lnk) to the `sb` of this installation with the argument `ui`; its console
window shows the service and closing it stops the service.  macOS: an executable
`Sourcebound.command` (opens in Terminal).  Linux: a `sourcebound.desktop` launcher that runs in
a terminal.  The icon is optional: nothing else in Sourcebound depends on it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

NAME = "Sourcebound"


def available() -> bool:
    """The web view is part of this installation (the checkout has the frontend)."""
    home = config.home()
    return home is not None and (home / "frontend" / "package.json").exists()


def sb_executable() -> Path:
    return Path(sys.executable).parent / ("sb.exe" if os.name == "nt" else "sb")


def desktop() -> Path:
    """The user's desktop folder, also where Windows or XDG moved it (OneDrive, a redirected folder, a language)."""
    if os.name == "nt":
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    elif sys.platform != "darwin" and shutil.which("xdg-user-dir"):
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    return Path.home() / "Desktop"


def target(folder: Path | None = None) -> Path:
    folder = folder or desktop()
    if os.name == "nt":
        return folder / f"{NAME}.lnk"
    if sys.platform == "darwin":
        return folder / f"{NAME}.command"
    return folder / "sourcebound.desktop"


def create(folder: Path | None = None) -> Path:
    """Write the desktop icon and return its path; an existing one is replaced."""
    sb, home = sb_executable(), config.home()
    path = target(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # values travel in the environment: no quoting of paths inside the script
        script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SB_LNK); "
                  "$s.TargetPath = $env:SB_EXE; $s.Arguments = 'ui'; $s.WorkingDirectory = $env:SB_HOME; "
                  "$s.Description = 'Start the Sourcebound web view'; $s.Save()")
        env = {**os.environ, "SB_LNK": str(path), "SB_EXE": str(sb), "SB_HOME": str(home or Path.home())}
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             env=env, capture_output=True, text=True)
        if out.returncode or not path.exists():
            raise RuntimeError(f"could not create {path}: {out.stderr.strip() or 'PowerShell failed'}")
        return path
    if sys.platform == "darwin":
        path.write_text(f'#!/bin/sh\nexec "{sb}" ui\n', encoding="utf-8", newline="\n")
    else:
        icon = home / "frontend" / "public" / "logo.svg" if home else None
        lines = ["[Desktop Entry]", "Type=Application", f"Name={NAME}", "Comment=Start the Sourcebound web view",
                 f'Exec="{sb}" ui', "Terminal=true", "Categories=Science;Office;"]
        if icon and icon.exists():
            lines.append(f"Icon={icon}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path
