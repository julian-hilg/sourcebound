"""A Chromium to lay out and photograph slides: found, never downloaded.

Any Chromium does: Chrome, Edge, Chromium, or the browser Playwright installed.  It is run
headless from the command line (`--dump-dom`, `--screenshot`, `--print-to-pdf`), so no Python
browser package is needed.  `SB_CHROMIUM` names one explicitly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOW = ("No Chromium browser was found. Install Google Chrome or Microsoft Edge (either is enough), "
       "or set the environment variable SB_CHROMIUM to the path of a Chromium executable.")
NAMES = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome", "msedge", "microsoft-edge"]


def _candidates() -> list[Path]:
    home = Path.home()
    out: list[Path] = []
    if sys.platform == "darwin":
        for app, exe in (("Google Chrome", "Google Chrome"), ("Microsoft Edge", "Microsoft Edge"), ("Chromium", "Chromium"),
                         ("Brave Browser", "Brave Browser")):
            out += [Path(f"/Applications/{app}.app/Contents/MacOS/{exe}"), home / f"Applications/{app}.app/Contents/MacOS/{exe}"]
        caches = [home / "Library/Caches/ms-playwright"]
    elif os.name == "nt":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for root in filter(None, roots):
            out += [Path(root) / "Google/Chrome/Application/chrome.exe", Path(root) / "Microsoft/Edge/Application/msedge.exe",
                    Path(root) / "Chromium/Application/chrome.exe"]
        caches = [Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "ms-playwright"]
    else:
        caches = [home / ".cache/ms-playwright"]
    for cache in [Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])] if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else caches:
        if cache.is_dir():                              # newest first; the full browser before the headless shell
            for pattern in ("chromium-*/chrome-*/Chromium.app/Contents/MacOS/Chromium", "chromium-*/chrome-*/chrome", "chromium-*/chrome-*/chrome.exe",
                            "chromium_headless_shell-*/chrome-*/headless_shell", "chromium_headless_shell-*/chrome-*/chrome-headless-shell",
                            "chromium_headless_shell-*/chrome-*/chrome-headless-shell.exe", "chromium_headless_shell-*/chrome-*/headless_shell.exe"):
                out += sorted(cache.glob(pattern), reverse=True)
    return out


def find() -> Path | None:
    """The Chromium to use, or None."""
    env = os.environ.get("SB_CHROMIUM")
    if env:
        return Path(env) if Path(env).is_file() else None
    for name in NAMES:
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    return next((p for p in _candidates() if p.is_file()), None)


def _run(exe: Path, args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    # Its own profile, never the person's. On Windows the browser may still hold a file of it for a
    # moment after it exits: a profile that cannot be removed at once must not fail the render.
    with tempfile.TemporaryDirectory(prefix="sb-chromium-", ignore_cleanup_errors=True) as profile:
        base = [str(exe), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
                "--disable-extensions", "--disable-background-networking", "--allow-file-access-from-files",
                f"--user-data-dir={profile}"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            base.append("--no-sandbox")
        r = subprocess.run(base + args, capture_output=True, timeout=timeout)
        if r.returncode != 0 and sys.platform.startswith("linux") and "--no-sandbox" not in base:
            # Containers and some Linux desktops forbid the browser's sandbox, and it then crashes at
            # start. The page it opens is a local file this renderer wrote, with no network access
            # in its policy, so one retry without the sandbox is safe.
            r = subprocess.run(base + ["--no-sandbox"] + args, capture_output=True, timeout=timeout)
        return r


def dom(exe: Path, html: Path, *, width: int, height: int) -> str:
    """The page after its scripts ran (all slides laid out), as HTML."""
    r = _run(exe, [f"--window-size={width},{height}", "--virtual-time-budget=10000", "--dump-dom", html.as_uri()])
    text = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0 and "sb-report" not in text:
        raise RuntimeError(f"{exe.name} could not open the slides: {r.stderr.decode('utf-8', errors='replace')[-400:]}")
    return text


def screenshot(exe: Path, html: Path, anchor: str, out: Path, *, width: int, height: int, scale: float) -> None:
    r = _run(exe, [f"--window-size={width},{height}", f"--force-device-scale-factor={scale}", "--virtual-time-budget=10000",
                   "--default-background-color=ffffffff", f"--screenshot={out}", f"{html.as_uri()}#{anchor}"])
    if not out.exists():
        raise RuntimeError(f"{exe.name} wrote no image for {anchor}: {r.stderr.decode('utf-8', errors='replace')[-400:]}")


def pdf(exe: Path, html: Path, out: Path) -> None:
    r = _run(exe, ["--virtual-time-budget=10000", "--no-pdf-header-footer", "--print-to-pdf-no-header", f"--print-to-pdf={out}", html.as_uri()])
    if not out.exists():
        raise RuntimeError(f"{exe.name} wrote no PDF: {r.stderr.decode('utf-8', errors='replace')[-400:]}")
