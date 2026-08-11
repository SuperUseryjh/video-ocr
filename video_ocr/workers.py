import os
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QRect, QThread, Signal

from .models import OcrResult


class OcrWorker(QThread):
    progress_changed = Signal(int, int)
    status_changed = Signal(str)
    result_ready = Signal(object)
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, path: str, start_ms: int, end_ms: int, interval_ms: int, roi: QRect, thread_count: int) -> None:
        super().__init__()
        self.path, self.start_ms, self.end_ms = path, start_ms, end_ms
        self.interval_ms, self.roi = interval_ms, roi
        self.thread_count = thread_count
        self.cancel_requested = threading.Event()

    def cancel(self) -> None:
        self.cancel_requested.set()

    def run(self) -> None:
        try:
            from rapidocr import RapidOCR

            timestamps = list(range(self.start_ms, self.end_ms + 1, self.interval_ms))
            total_frames = len(timestamps)
            engines = threading.local()

            def recognize_frame(timestamp: int) -> OcrResult | None:
                if self.cancel_requested.is_set():
                    return None
                capture = cv2.VideoCapture(self.path)
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp)
                ok, frame = capture.read()
                capture.release()
                if self.cancel_requested.is_set():
                    return None
                if not ok:
                    return OcrResult(timestamp, "无法读取视频帧", 0.0)
                if not self.roi.isNull():
                    frame = frame[self.roi.y():self.roi.y() + self.roi.height(), self.roi.x():self.roi.x() + self.roi.width()]
                if not hasattr(engines, "engine"):
                    engines.engine = RapidOCR()
                output = engines.engine(frame)
                if not output.txts:
                    return OcrResult(timestamp, "未识别到文字", 0.0)
                return OcrResult(timestamp, "\n".join(output.txts), float(np.mean(output.scores)))

            self.status_changed.emit("正在初始化 OCR 引擎…")
            results: list[OcrResult] = []
            completed_count = 0
            with ThreadPoolExecutor(max_workers=self.thread_count) as executor:
                futures = [executor.submit(recognize_frame, timestamp) for timestamp in timestamps]
                for future in as_completed(futures):
                    if self.cancel_requested.is_set():
                        for pending in futures:
                            pending.cancel()
                        break
                    completed_count += 1
                    result = future.result()
                    if result:
                        results.append(result)
                        self.result_ready.emit(result)
                    self.progress_changed.emit(completed_count, total_frames)
                    self.status_changed.emit(f"已完成 {completed_count} / {total_frames} 帧（{len(results)} 条文字结果）")
            results.sort(key=lambda item: item.timestamp_ms)
            self.status_changed.emit(f"OCR 已终止，已保留 {len(results)} 条结果" if self.cancel_requested.is_set() else "OCR 识别完成")
            self.completed.emit(results)
        except Exception as error:
            self.failed.emit(str(error))


class ClipExportWorker(QThread):
    progress_changed = Signal(int)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, ffmpeg: str, video_path: str, start_ms: int, end_ms: int, output_path: str) -> None:
        super().__init__()
        self.ffmpeg = ffmpeg
        self.video_path = video_path
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.output_path = output_path

    def run(self) -> None:
        progress_path = ""
        try:
            duration_ms = self.end_ms - self.start_ms
            descriptor, progress_path = tempfile.mkstemp(prefix="video_ocr_progress_", suffix=".txt")
            os.close(descriptor)
            Path(progress_path).unlink(missing_ok=True)
            command = [
                self.ffmpeg, "-y", "-ss", f"{self.start_ms / 1000:.3f}", "-t", f"{duration_ms / 1000:.3f}",
                "-i", self.video_path, "-c", "copy", "-progress", progress_path, "-nostats", self.output_path,
            ]
            process = subprocess.Popen(command, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            while process.poll() is None:
                if Path(progress_path).exists():
                    for line in Path(progress_path).read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.startswith("out_time_ms="):
                            exported_ms = int(line.partition("=")[2]) // 1000
                            self.progress_changed.emit(min(100, round(exported_ms * 100 / duration_ms)))
                time.sleep(0.1)
            stderr = process.stderr.read() if process.stderr else ""
            if process.returncode == 0:
                self.progress_changed.emit(100)
                self.completed.emit(self.output_path)
            else:
                self.failed.emit(stderr[-800:] or "FFmpeg 执行失败。")
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if progress_path:
                Path(progress_path).unlink(missing_ok=True)
