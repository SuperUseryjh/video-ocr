import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .version import __version__


UPDATE_MANIFEST_URL = "https://static.yaoonion.fun/video-ocr/latest.json"


def parse_version(value: str) -> tuple[int, ...]:
    parts = value.lstrip("v").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("版本号必须使用 X.Y.Z 格式。")
    return tuple(int(part) for part in parts)


def fetch_manifest(url: str = UPDATE_MANIFEST_URL) -> dict[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": f"VideoOCR/{__version__}"})
    with urllib.request.urlopen(request, timeout=10) as response:
        manifest = json.loads(response.read().decode("utf-8"))
    required = {"version", "url", "sha256"}
    if not required.issubset(manifest) or not manifest["url"].startswith("https://"):
        raise ValueError("更新清单格式无效。")
    return manifest


class UpdateCheckWorker(QThread):
    update_available = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            manifest = fetch_manifest()
            if parse_version(manifest["version"]) > parse_version(__version__):
                self.update_available.emit(manifest)
        except Exception as error:
            self.failed.emit(str(error))


class UpdateDownloadWorker(QThread):
    progress_changed = Signal(int)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, manifest: dict[str, str]) -> None:
        super().__init__()
        self.manifest = manifest

    def run(self) -> None:
        archive_path = ""
        try:
            descriptor, archive_path = tempfile.mkstemp(prefix="video_ocr_update_", suffix=".zip")
            os.close(descriptor)
            request = urllib.request.Request(self.manifest["url"], headers={"User-Agent": f"VideoOCR/{__version__}"})
            with urllib.request.urlopen(request, timeout=30) as response, open(archive_path, "wb") as stream:
                total = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        self.progress_changed.emit(round(downloaded * 100 / total))
            hasher = hashlib.sha256()
            with open(archive_path, "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            if digest.lower() != self.manifest["sha256"].lower():
                raise ValueError("更新包校验失败，已取消安装。")
            self.progress_changed.emit(100)
            self.completed.emit(archive_path)
        except Exception as error:
            if archive_path:
                Path(archive_path).unlink(missing_ok=True)
            self.failed.emit(str(error))


def install_update(archive_path: str) -> None:
    install_dir = Path(sys.executable).resolve().parent
    temporary_dir = Path(tempfile.mkdtemp(prefix="video_ocr_install_"))
    with zipfile.ZipFile(archive_path) as archive:
        if any(Path(member).is_absolute() or ".." in Path(member).parts for member in archive.namelist()):
            raise ValueError("更新包包含不安全路径。")
        archive.extractall(temporary_dir)
    candidates = [path for path in temporary_dir.iterdir() if path.is_dir() and (path / "VideoOCR.exe").is_file()]
    if len(candidates) != 1:
        raise ValueError("更新包内容无效。")
    new_dir = candidates[0]
    backup_dir = install_dir.with_name(f"{install_dir.name}.backup")
    script_path = temporary_dir / "apply_update.cmd"
    script_path.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'if exist "{backup_dir}" rmdir /s /q "{backup_dir}"\r\n'
        f'move /y "{install_dir}" "{backup_dir}"\r\n'
        f'move /y "{new_dir}" "{install_dir}"\r\n'
        f'start "" "{install_dir / "VideoOCR.exe"}"\r\n'
        f'rmdir /s /q "{temporary_dir}"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", str(script_path)], creationflags=subprocess.CREATE_NEW_CONSOLE)
