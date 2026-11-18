"""Office files as PDF, for looking at a render without opening Word or PowerPoint.

    to_pdf(path)   a .docx or .pptx as a PDF in a cache folder, or None where no converter is installed
    available()    the converter that would be used: "libreoffice", "word" (Windows, Office installed) or None

LibreOffice (`soffice --headless --convert-to pdf`) is used where it is on the PATH; on Windows
without it, Word or PowerPoint itself through PowerShell and COM (the only way to see a document
exactly as Word lays it out). A conversion never changes the file: Office opens it read-only. The
PDF is cached by path and modification time, so a document is converted once per change.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

SUFFIXES = {".docx", ".pptx"}
_LOCK = threading.Lock()            # one Office conversion at a time: COM drives one Word instance

# Opened read-only and invisible; SaveAs2/SaveAs with the PDF format (Word 17, PowerPoint 32). Word's
# ExportAsFixedFormat can hang in an invisible instance, SaveAs does not. Paths come in environment
# variables, never in the script text.
_PS = {
    ".docx": r"""
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$w.Visible = $false; $w.DisplayAlerts = 0
try { $d = $w.Documents.Open($env:SB_OFFICE_IN, $false, $true, $false); $d.SaveAs2($env:SB_OFFICE_OUT, 17); $d.Close(0) }
finally { $w.Quit() }
""",
    ".pptx": r"""
$ErrorActionPreference = 'Stop'
$p = New-Object -ComObject PowerPoint.Application
try { $d = $p.Presentations.Open($env:SB_OFFICE_IN, -1, 0, 0); $d.SaveAs($env:SB_OFFICE_OUT, 32); $d.Close() }
finally { $p.Quit() }
""",
}


def _soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _office_installed() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application"):
            return True
    except OSError:
        return False


def available() -> str | None:
    if _soffice():
        return "libreoffice"
    return "word" if _office_installed() else None


def cache_path(path: Path) -> Path:
    folder = Path(tempfile.gettempdir()) / "sourcebound-ui"
    folder.mkdir(exist_ok=True)
    key = hashlib.sha256(f"{path.resolve()}|{path.stat().st_mtime_ns}".encode()).hexdigest()[:24]
    return folder / f"{key}.pdf"


def to_pdf(path: Path, *, timeout: int = 180) -> Path | None:
    """The document as a PDF (cached), or None when it cannot be converted here."""
    path = Path(path)
    if path.suffix.lower() not in SUFFIXES or not path.is_file():
        return None
    out = cache_path(path)
    if out.exists():
        return out
    with _LOCK:
        if out.exists():
            return out
        soffice = _soffice()
        try:
            if soffice:
                with tempfile.TemporaryDirectory(prefix="sb-office-") as tmp:
                    subprocess.run([soffice, "--headless", "--norestore", f"-env:UserInstallation=file:///{Path(tmp, 'profile').as_posix()}",
                                    "--convert-to", "pdf", "--outdir", tmp, str(path)], capture_output=True, timeout=timeout)
                    made = Path(tmp) / f"{path.stem}.pdf"
                    if made.exists():
                        shutil.move(str(made), out)
            elif _office_installed():
                env = {**os.environ, "SB_OFFICE_IN": str(path.resolve()), "SB_OFFICE_OUT": str(out)}
                subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS[path.suffix.lower()]],
                               capture_output=True, timeout=timeout, env=env, cwd=os.environ.get("SystemRoot"))
        except (subprocess.SubprocessError, OSError):
            return None
    return out if out.exists() else None
