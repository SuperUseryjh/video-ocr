from __future__ import annotations

import os
import sys

import cv2
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QProgressBar,
    QSlider, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from video_ocr.frame_view import FrameView
from video_ocr.ffmpeg import find_ffmpeg
from video_ocr.models import OcrResult
from video_ocr.updater import UpdateCheckWorker, UpdateDownloadWorker, install_update
from video_ocr.utils import export_results_csv, format_timestamp, frame_to_image
from video_ocr.version import __version__
from video_ocr.workers import ClipExportWorker, OcrWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"视频截取 & OCR 识别器 {__version__}")
        self.resize(1250, 780)
        self.capture: cv2.VideoCapture | None = None
        self.video_path = ""
        self.duration_ms = 0
        self.current_ms = 0
        self.fps = 25.0
        self.playback_rate = 1.0
        self.ocr_results: list[OcrResult] = []
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.audio_player = QMediaPlayer(self)
        self.audio_player.setAudioOutput(self.audio_output)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_frame)
        self._build_ui()
        if getattr(sys, "frozen", False):
            QTimer.singleShot(1500, self.check_for_update)

    def _build_ui(self) -> None:
        self.view = FrameView()
        self.view.selection_changed.connect(lambda rect: self.roi_label.setText(f"选区：{rect.width()} × {rect.height()} 像素"))
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.sliderMoved.connect(self.show_position)
        self.time_label = QLabel("00:00:00.000 / 00:00:00.000")
        self.open_button = QPushButton("打开视频")
        self.open_button.clicked.connect(self.open_video)
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.toggle_play)
        self.speed_spin = QSpinBox(); self.speed_spin.setRange(1, 40); self.speed_spin.setValue(10); self.speed_spin.setSuffix(" / 10 倍")
        self.speed_spin.valueChanged.connect(self.change_playback_rate)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal); self.volume_slider.setRange(0, 100); self.volume_slider.setValue(80)
        self.volume_slider.valueChanged.connect(lambda value: self.audio_output.setVolume(value / 100))
        self.start_spin = QSpinBox(); self.start_spin.setSuffix(" ms")
        self.end_spin = QSpinBox(); self.end_spin.setSuffix(" ms")
        for spin in (self.start_spin, self.end_spin):
            spin.setRange(0, 0)
        self.set_start = QPushButton("设为起点"); self.set_start.clicked.connect(lambda: self.start_spin.setValue(self.current_ms))
        self.set_end = QPushButton("设为终点"); self.set_end.clicked.connect(lambda: self.end_spin.setValue(self.current_ms))
        self.export_clip = QPushButton("导出片段"); self.export_clip.clicked.connect(self.save_clip)
        self.export_progress = QProgressBar(); self.export_progress.setRange(0, 100); self.export_progress.setValue(0); self.export_progress.setVisible(False)
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(100, 60000); self.interval_spin.setValue(1000); self.interval_spin.setSuffix(" ms")
        self.thread_spin = QSpinBox(); self.thread_spin.setRange(1, min(16, os.cpu_count() or 4)); self.thread_spin.setValue(min(4, self.thread_spin.maximum())); self.thread_spin.setSuffix(" 个")
        self.ocr_button = QPushButton("识别选定范围")
        self.ocr_button.clicked.connect(self.run_ocr)
        self.stop_ocr_button = QPushButton("终止 OCR")
        self.stop_ocr_button.setEnabled(False)
        self.stop_ocr_button.clicked.connect(self.stop_ocr)
        self.ocr_progress = QProgressBar(); self.ocr_progress.setRange(0, 100); self.ocr_progress.setValue(0); self.ocr_progress.setVisible(False)
        self.ocr_status = QLabel(""); self.ocr_status.setVisible(False)
        self.roi_label = QLabel("选区：整帧（可在预览画面拖拽框选）")
        controls = QVBoxLayout()
        video_group = QGroupBox("视频与播放")
        video_form = QFormLayout(video_group)
        video_form.addRow(self.open_button, self.play_button)
        video_form.addRow("播放倍速", self.speed_spin)
        video_form.addRow("音量", self.volume_slider)
        video_form.addRow("时间轴", self.position)
        video_form.addRow("当前时间", self.time_label)
        clip_group = QGroupBox("片段截取")
        clip_form = QFormLayout(clip_group)
        clip_form.addRow("起始时间", self.start_spin); clip_form.addRow("结束时间", self.end_spin)
        clip_form.addRow(self.set_start, self.set_end); clip_form.addRow(self.export_clip); clip_form.addRow("导出进度", self.export_progress)
        ocr_group = QGroupBox("OCR 识别")
        ocr_form = QFormLayout(ocr_group)
        ocr_form.addRow("采样间隔", self.interval_spin); ocr_form.addRow("并行线程", self.thread_spin); ocr_form.addRow(self.roi_label); ocr_form.addRow(self.ocr_button, self.stop_ocr_button); ocr_form.addRow("识别进度", self.ocr_progress); ocr_form.addRow(self.ocr_status)
        controls.addWidget(video_group); controls.addWidget(clip_group); controls.addWidget(ocr_group); controls.addStretch()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["时间", "识别结果", "置信度"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.export_csv = QPushButton("导出 OCR CSV")
        self.export_csv.clicked.connect(self.save_csv)
        self.update_button = QPushButton(f"检查更新（v{__version__}）")
        self.update_button.clicked.connect(self.check_for_update)
        results_layout = QVBoxLayout(); results_layout.addWidget(self.table); results_layout.addWidget(self.export_csv); results_layout.addWidget(self.update_button)
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.addWidget(self.view, 1); left_layout.addWidget(self.position); left_layout.addWidget(self.time_label)
        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.addLayout(controls); right_layout.addLayout(results_layout, 1)
        splitter = QSplitter(); splitter.addWidget(left); splitter.addWidget(right); splitter.setSizes([780, 470])
        self.setCentralWidget(splitter)

    def open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", "视频文件 (*.mp4 *.avi *.mkv *.mov *.wmv);;所有文件 (*)")
        if not path:
            return
        if self.capture:
            self.capture.release()
        self.capture = cv2.VideoCapture(path)
        if not self.capture.isOpened():
            QMessageBox.critical(self, "打开失败", "无法读取该视频文件。")
            return
        self.video_path = path
        self.audio_player.stop()
        self.audio_player.setSource(QUrl.fromLocalFile(path))
        self.fps = self.capture.get(cv2.CAP_PROP_FPS) or 25.0
        frames = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration_ms = round(frames / self.fps * 1000)
        for widget in (self.position, self.start_spin, self.end_spin):
            widget.setMaximum(self.duration_ms)
        self.start_spin.setValue(0); self.end_spin.setValue(self.duration_ms)
        self.show_position(0)

    def show_position(self, milliseconds: int) -> None:
        if not self.capture:
            return
        self.current_ms = milliseconds
        self.capture.set(cv2.CAP_PROP_POS_MSEC, milliseconds)
        ok, frame = self.capture.read()
        if ok:
            self.view.set_frame(frame_to_image(frame))
        self.position.blockSignals(True); self.position.setValue(milliseconds); self.position.blockSignals(False)
        self.time_label.setText(f"{format_timestamp(milliseconds)} / {format_timestamp(self.duration_ms)}")

    def change_playback_rate(self, value: int) -> None:
        self.playback_rate = value / 10
        self.audio_player.setPlaybackRate(self.playback_rate)
        if self.timer.isActive():
            self.timer.start(self.timer_interval())

    def timer_interval(self) -> int:
        return max(10, round(1000 / self.fps / self.playback_rate))

    def toggle_play(self) -> None:
        if not self.capture:
            return
        if self.timer.isActive():
            self.timer.stop(); self.audio_player.pause(); self.play_button.setText("播放")
        else:
            self.capture.set(cv2.CAP_PROP_POS_MSEC, self.current_ms)
            self.audio_player.setPosition(self.current_ms)
            self.audio_player.setPlaybackRate(self.playback_rate)
            self.audio_player.play()
            self.timer.start(self.timer_interval()); self.play_button.setText("暂停")

    def advance_frame(self) -> None:
        next_position = self.current_ms + round(1000 / self.fps * self.playback_rate)
        if next_position >= self.duration_ms:
            self.timer.stop(); self.play_button.setText("播放"); return
        ok, frame = self.capture.read()
        if ok:
            self.current_ms = next_position
            self.view.set_frame(frame_to_image(frame))
            self.position.blockSignals(True); self.position.setValue(next_position); self.position.blockSignals(False)
            self.time_label.setText(f"{format_timestamp(next_position)} / {format_timestamp(self.duration_ms)}")
        else:
            self.timer.stop(); self.audio_player.stop(); self.play_button.setText("播放")

    def save_clip(self) -> None:
        if not self.video_path:
            return
        start, end = self.start_spin.value(), self.end_spin.value()
        if end <= start:
            QMessageBox.warning(self, "时间范围无效", "结束时间必须晚于起始时间。")
            return
        output, _ = QFileDialog.getSaveFileName(self, "导出视频片段", "clip.mp4", "MP4 文件 (*.mp4)")
        if not output:
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            QMessageBox.critical(self, "缺少 FFmpeg", "未找到内嵌或系统 FFmpeg。请将 ffmpeg.exe 放入 bin 目录，或安装 FFmpeg 并加入 PATH。")
            return
        self.export_clip.setEnabled(False)
        self.export_progress.setValue(0)
        self.export_progress.setVisible(True)
        self.export_worker = ClipExportWorker(ffmpeg, self.video_path, start, end, output)
        self.export_worker.progress_changed.connect(self.export_progress.setValue)
        self.export_worker.completed.connect(lambda path: QMessageBox.information(self, "导出完成", f"已保存至：\n{path}"))
        self.export_worker.failed.connect(lambda error: QMessageBox.critical(self, "导出失败", error))
        self.export_worker.finished.connect(self.finish_export)
        self.export_worker.start()

    def finish_export(self) -> None:
        self.export_clip.setEnabled(True)
        self.export_progress.setVisible(False)

    def run_ocr(self) -> None:
        if not self.video_path:
            return
        self.ocr_button.setEnabled(False)
        self.stop_ocr_button.setEnabled(True)
        self.thread_spin.setEnabled(False)
        self.ocr_progress.setRange(0, 0)
        self.ocr_progress.setVisible(True)
        self.ocr_status.setText("正在准备 OCR 任务…")
        self.ocr_status.setVisible(True)
        self.ocr_results = []
        self.table.setRowCount(0)
        self.worker = OcrWorker(self.video_path, self.start_spin.value(), self.end_spin.value(), self.interval_spin.value(), self.view.selected_source_rect(), self.thread_spin.value())
        self.worker.progress_changed.connect(self.update_ocr_progress)
        self.worker.status_changed.connect(self.ocr_status.setText)
        self.worker.result_ready.connect(self.append_ocr_result)
        self.worker.completed.connect(lambda _: None)
        self.worker.failed.connect(lambda error: QMessageBox.critical(self, "OCR 失败", error))
        self.worker.finished.connect(self.finish_ocr)
        self.worker.start()

    def stop_ocr(self) -> None:
        if hasattr(self, "worker") and self.worker.isRunning():
            self.stop_ocr_button.setEnabled(False)
            self.ocr_status.setText("正在终止 OCR，等待当前识别帧完成…")
            self.worker.cancel()

    def update_ocr_progress(self, current: int, total: int) -> None:
        self.ocr_progress.setRange(0, total)
        self.ocr_progress.setValue(current)

    def finish_ocr(self) -> None:
        self.ocr_button.setEnabled(True)
        self.stop_ocr_button.setEnabled(False)
        self.thread_spin.setEnabled(True)
        self.ocr_progress.setVisible(False)
        self.ocr_status.setVisible(False)

    def show_ocr_results(self, results: list[OcrResult]) -> None:
        self.ocr_results = results
        self.table.setRowCount(len(results))
        for row, item in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(format_timestamp(item.timestamp_ms)))
            self.table.setItem(row, 1, QTableWidgetItem(item.text))
            self.table.setItem(row, 2, QTableWidgetItem(f"{item.confidence:.2%}"))

    def append_ocr_result(self, item: OcrResult) -> None:
        self.ocr_results.append(item)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(format_timestamp(item.timestamp_ms)))
        self.table.setItem(row, 1, QTableWidgetItem(item.text))
        self.table.setItem(row, 2, QTableWidgetItem(f"{item.confidence:.2%}"))
        self.table.scrollToBottom()

    def save_csv(self) -> None:
        if not self.ocr_results:
            return
        output, _ = QFileDialog.getSaveFileName(self, "导出 OCR 结果", "ocr_results.csv", "CSV 文件 (*.csv)")
        if not output:
            return
        export_results_csv(output, self.ocr_results)

    def check_for_update(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        self.update_button.setEnabled(False)
        self.update_worker = UpdateCheckWorker()
        self.update_worker.update_available.connect(self.offer_update)
        self.update_worker.failed.connect(lambda _: None)
        self.update_worker.finished.connect(lambda: self.update_button.setEnabled(True))
        self.update_worker.start()

    def offer_update(self, manifest: dict[str, str]) -> None:
        answer = QMessageBox.question(self, "发现更新", f"发现 v{manifest['version']}，是否下载并安装？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("正在下载更新…")
        self.update_download_worker = UpdateDownloadWorker(manifest)
        self.update_download_worker.progress_changed.connect(lambda value: self.update_button.setText(f"正在下载更新… {value}%"))
        self.update_download_worker.completed.connect(self.apply_update)
        self.update_download_worker.failed.connect(lambda error: QMessageBox.warning(self, "更新失败", error))
        self.update_download_worker.finished.connect(self.reset_update_button)
        self.update_download_worker.start()

    def apply_update(self, archive_path: str) -> None:
        try:
            install_update(archive_path)
            QApplication.quit()
        except Exception as error:
            QMessageBox.warning(self, "安装更新失败", str(error))

    def reset_update_button(self) -> None:
        self.update_button.setEnabled(True)
        self.update_button.setText(f"检查更新（v{__version__}）")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
