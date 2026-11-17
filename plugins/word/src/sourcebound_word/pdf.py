"""A Word file as PDF: through Microsoft Word where it is installed (Windows), else LibreOffice.

    sb word pdf FILE [--out FILE.pdf] [--engine word|libreoffice]

Word gives the layout exactly as a person sees it in Word. Two things it does differently from a
browser, and the report says so:

* Fields are refreshed first (tables of contents, cross-references), which Word does not do by
  itself when it is driven by a program.
* Fonts in OpenType format with PostScript outlines (.otf, "CFF") cannot be embedded by Word: Word
  draws their text as shapes. The PDF then looks right but its text cannot be searched, selected
  or read aloud. The report lists such fonts (`outlined_fonts`).

Word is driven through PowerShell and COM, so no Python package for Windows is needed. Word runs
hidden; a Word that does not answer within `timeout` seconds is stopped (only the instance this
call started). On this kind of machine `Document.ExportAsFixedFormat` was seen to hang in hidden
Word while `SaveAs2(..., 17)` did not, so SaveAs2 is used.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

WORD_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$before = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$w = New-Object -ComObject Word.Application
# the PID is written only if this call started a new Word: an instance the person has open is never stopped
$new = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id })
if ($new.Count -eq 1) { Set-Content -LiteralPath $env:SB_PID_FILE -Value $new[0].Id }
$w.Visible = $false
$w.DisplayAlerts = 0
try {
  $w.AutomationSecurity = 3
  $d = $w.Documents.Open($env:SB_IN, $false, $false, $false)
  if ($env:SB_FIELDS -eq '1') {
    foreach ($t in $d.TablesOfContents) { [void]$t.Update() }
    foreach ($t in $d.TablesOfFigures) { [void]$t.Update() }
    [void]$d.Fields.Update()
  }
  $d.SaveAs2($env:SB_OUT, 17)
  $d.Close(0)
} finally { $w.Quit() }
"""


def engines() -> list[str]:
    """The engines this machine has, in the order they are tried."""
    have = []
    if sys.platform == "win32" and _word_installed():
        have.append("word")
    if _soffice():
        have.append("libreoffice")
    return have


def _word_installed() -> bool:
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
        return True
    except OSError:
        return False


def _soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(p).exists():
            return p
    return None


def outlined_fonts(docx: Path) -> list[str]:
    """Fonts the file uses that are installed as OpenType/CFF (.otf) only: Word outlines their text in PDF."""
    if sys.platform != "win32":
        return []
    import re
    used: set[str] = set()
    with zipfile.ZipFile(docx) as z:
        for n in z.namelist():
            if n.startswith("word/") and n.endswith(".xml"):
                used |= set(re.findall(r'w:(?:ascii|hAnsi)="([^"]+)"', z.read(n).decode("utf-8", "replace")))
    try:
        import winreg
        files: dict[str, list[str]] = {}
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                k = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                files.setdefault(re.sub(r"\s*\((TrueType|OpenType)\)$", "", name), []).append(str(value).lower())
                i += 1
    except OSError:
        return []
    return sorted(f for f in used if files.get(f) and all(v.endswith(".otf") for v in files[f]))


def to_pdf(docx: str | Path, out: str | Path | None = None, *, engine: str | None = None,
           fields: bool = True, timeout: int = 180) -> dict:
    """Write `out` (default: next to the file, .pdf) and return {pdf, engine, seconds, outlined_fonts, notes}."""
    src = Path(docx).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"no such file: {src}")
    dest = Path(out).expanduser().resolve() if out else src.with_suffix(".pdf")
    have = engines()
    if engine and engine not in have:
        raise RuntimeError(f"PDF engine {engine} is not available here (available: {', '.join(have) or 'none'})")
    order = [engine] if engine else have
    if not order:
        raise RuntimeError("no PDF engine: install Microsoft Word (Windows) or LibreOffice (`soffice` on PATH)")
    errors = []
    for name in order:
        t0 = time.monotonic()
        try:
            notes = (_word if name == "word" else _libreoffice)(src, dest, fields=fields, timeout=timeout)
        except (RuntimeError, subprocess.SubprocessError, OSError) as e:
            errors.append(f"{name}: {e}")
            continue
        outlined = outlined_fonts(src) if name == "word" else []
        if outlined:
            notes.append("text in " + ", ".join(outlined) + " is drawn as shapes (OpenType/CFF fonts cannot be embedded by Word): "
                         "the PDF looks right, but that text cannot be searched or selected")
        return {"pdf": str(dest), "engine": name, "seconds": round(time.monotonic() - t0, 1),
                "outlined_fonts": outlined, "notes": notes}
    raise RuntimeError("PDF not written:\n  " + "\n  ".join(errors))


def _word(src: Path, dest: Path, *, fields: bool, timeout: int) -> list[str]:
    # Word works on a local copy: files on network shares and long paths are a common cause of prompts
    with tempfile.TemporaryDirectory(prefix="sb-pdf-") as tmp:
        local_in, local_out, pid_file = Path(tmp) / ("in" + src.suffix), Path(tmp) / "out.pdf", Path(tmp) / "word.pid"
        shutil.copy2(src, local_in)
        env = {**os.environ, "SB_IN": str(local_in), "SB_OUT": str(local_out), "SB_PID_FILE": str(pid_file),
               "SB_FIELDS": "1" if fields else "0"}
        proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", WORD_SCRIPT], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            _, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            _stop_word(pid_file)
            raise RuntimeError(f"Word did not finish within {timeout} s (stopped)")
        if proc.returncode or not local_out.exists():
            _stop_word(pid_file)
            raise RuntimeError((err or "").strip().splitlines()[-1] if (err or "").strip() else "Word wrote no PDF")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_out, dest)
    return ["fields refreshed (table of contents, references)"] if fields else []


def _stop_word(pid_file: Path) -> None:
    """Stop the Word instance this call started, never another one."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8-sig").strip())
    except (OSError, ValueError):
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def _libreoffice(src: Path, dest: Path, *, fields: bool, timeout: int) -> list[str]:
    exe = _soffice()
    if not exe:
        raise RuntimeError("LibreOffice not found")
    with tempfile.TemporaryDirectory(prefix="sb-pdf-") as tmp:
        # a private profile: a LibreOffice the person has open does not block the conversion
        profile = Path(tmp, "profile").as_uri()
        cmd = [exe, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        made = Path(tmp) / (src.stem + ".pdf")
        if r.returncode or not made.exists():
            raise RuntimeError((r.stderr or r.stdout or "LibreOffice wrote no PDF").strip())
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(made, dest)
    notes = ["converted with LibreOffice: layout can differ from Word (line breaks, fonts)"]
    if fields:
        notes.append("fields are not refreshed by LibreOffice: a table of contents shows what Word last saved")
    return notes


def convert(path: Path, out: Path) -> tuple[Path, list[str]]:
    """The converter Sourcebound calls (`api.converter(".docx", ".pdf", ...)`)."""
    rep = to_pdf(path, out)
    return Path(rep["pdf"]), [f"PDF by {rep['engine']}"] + rep["notes"]
