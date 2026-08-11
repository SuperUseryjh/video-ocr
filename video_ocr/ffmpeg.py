import shutil
import sys
from pathlib import Path


def find_ffmpeg() -> str | None:
    executable_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    roots = [Path(__file__).resolve().parent.parent]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(sys.executable).resolve().parent)
        roots.insert(1, Path(getattr(sys, "_MEIPASS", sys.executable)).resolve())
    for root in roots:
        embedded = root / "bin" / executable_name
        if embedded.is_file():
            return str(embedded)
    return shutil.which("ffmpeg")
