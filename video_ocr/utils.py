import csv
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtGui import QImage

from .models import OcrResult


def format_timestamp(milliseconds: int) -> str:
    total_seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def frame_to_image(frame: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    return QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()


def export_results_csv(output_path: str, results: list[OcrResult]) -> None:
    with Path(output_path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["时间", "时间毫秒", "识别文本", "置信度"])
        writer.writerows((format_timestamp(item.timestamp_ms), item.timestamp_ms, item.text, item.confidence) for item in results)
