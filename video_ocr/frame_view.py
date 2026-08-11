from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel


class FrameView(QLabel):
    selection_changed = Signal(QRect)

    def __init__(self) -> None:
        super().__init__("打开视频后将在此显示预览")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background:#15181d; color:#b5becb; border:1px solid #3a4350;")
        self._image = QImage()
        self._draw_rect = QRect()
        self._start = QPoint()
        self._selecting = False

    def set_frame(self, image: QImage) -> None:
        self._image = image
        self.update()

    def image_rect(self) -> QRect:
        if self._image.isNull():
            return QRect()
        scale = min(self.width() / self._image.width(), self.height() / self._image.height())
        width = round(self._image.width() * scale)
        height = round(self._image.height() * scale)
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def selected_source_rect(self) -> QRect:
        target = self.image_rect()
        if self._draw_rect.isNull() or target.isNull():
            return QRect()
        clipped = self._draw_rect.intersected(target)
        if clipped.isNull():
            return QRect()
        x = (clipped.x() - target.x()) * self._image.width() // target.width()
        y = (clipped.y() - target.y()) * self._image.height() // target.height()
        w = clipped.width() * self._image.width() // target.width()
        h = clipped.height() * self._image.height() // target.height()
        return QRect(x, y, w, h)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._image.isNull():
            return
        painter = QPainter(self)
        target = self.image_rect()
        painter.drawImage(target, self._image)
        if not self._draw_rect.isNull():
            painter.setPen(QPen(Qt.GlobalColor.green, 2))
            painter.drawRect(self._draw_rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(event.position().toPoint()):
            self._start = event.position().toPoint()
            self._draw_rect = QRect(self._start, self._start)
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            self._draw_rect = QRect(self._start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._selecting:
            self._selecting = False
            self._draw_rect = QRect(self._start, event.position().toPoint()).normalized()
            self.selection_changed.emit(self.selected_source_rect())
            self.update()
