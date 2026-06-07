#!/usr/bin/env python3
"""pinnow — Pinterest Downloader (macOS GUI)"""

import sys
import os
import subprocess
import re
import time
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QTextEdit,
    QFileDialog, QSpinBox, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QPropertyAnimation, QEasingCurve, QRect, QTimer, QLockFile, QStandardPaths
from PyQt6.QtGui import QFont, QFontDatabase, QColor, QPalette, QTextCursor, QPainter, QBrush, QPen, QLinearGradient, QIcon, QPixmap, QImage


APP_NAME = "pinnow"
APP_VERSION = "1.1.0"
ORG_NAME = "ChoiC0re"
BRAND_FONT_FILE = "FlorDeRuina-Semilla.otf"
PIN_IMAGE_FILE = "silver-pin.png"
UI_FONT_FILES = ("Pretendard-Light.otf", "Pretendard-Regular.otf", "Pretendard-Bold.otf")
BRAND_FONT_FAMILY = None
UI_FONT_FAMILY = None


def _resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def _load_brand_font() -> str:
    global BRAND_FONT_FAMILY
    if BRAND_FONT_FAMILY:
        return BRAND_FONT_FAMILY
    font_id = QFontDatabase.addApplicationFont(_resource_path("fonts", BRAND_FONT_FILE))
    if font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            BRAND_FONT_FAMILY = families[0]
            return BRAND_FONT_FAMILY
    BRAND_FONT_FAMILY = ".AppleSystemUIFont" if sys.platform == "darwin" else "Segoe UI"
    return BRAND_FONT_FAMILY


def _brand_font(point_size: int) -> QFont:
    font = QFont(_load_brand_font(), point_size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def _load_ui_font() -> str:
    global UI_FONT_FAMILY
    if UI_FONT_FAMILY:
        return UI_FONT_FAMILY
    for filename in UI_FONT_FILES:
        font_id = QFontDatabase.addApplicationFont(_resource_path("fonts", filename))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                UI_FONT_FAMILY = families[0]
    if UI_FONT_FAMILY:
        return UI_FONT_FAMILY
    UI_FONT_FAMILY = ".AppleSystemUIFont" if sys.platform == "darwin" else "Segoe UI"
    return UI_FONT_FAMILY


def _ui_font(point_size: float, weight=QFont.Weight.Light, letter_spacing=130) -> QFont:
    font = QFont(_load_ui_font())
    font.setPointSizeF(point_size)
    # Windows GDI 렌더러는 Light(25)를 너무 얇게 그림 — Normal(50)을 하한으로
    if sys.platform == "win32" and weight < QFont.Weight.Normal:
        weight = QFont.Weight.Normal
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, letter_spacing)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def _pin_pixmap(width: int, height: int) -> QPixmap:
    image = QImage(_resource_path("assets", PIN_IMAGE_FILE))
    if image.isNull():
        return QPixmap()
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.red() > 85 and color.green() < 70 and color.blue() < 55:
                color.setAlpha(0)
                image.setPixelColor(x, y, color)
    crop = QPixmap.fromImage(image).copy(260, 150, 430, 700)
    return crop.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _spaced(text: str) -> str:
    return " ".join(text)


def _user_cache_dir() -> str:
    path = ""
    if QApplication.instance() is not None:
        path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    if path:
        return path
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
        return os.path.join(root, ORG_NAME, APP_NAME, "Cache")
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Caches/{APP_NAME}")
    return os.path.expanduser(f"~/.cache/{APP_NAME}")


def _user_data_dir() -> str:
    path = ""
    if QApplication.instance() is not None:
        path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if path:
        return path
    if sys.platform == "win32":
        root = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
        return os.path.join(root, ORG_NAME, APP_NAME)
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    return os.path.expanduser(f"~/.local/share/{APP_NAME}")


def _playwright_browsers_path() -> str:
    return os.path.join(_user_cache_dir(), "ms-playwright")


os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _playwright_browsers_path())
os.environ.setdefault("PINNOW_DATA_DIR", _user_data_dir())

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pinnow as core


# ── Browser setup helpers ─────────────────────────────────────────────────────

def _is_browser_installed() -> bool:
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", _playwright_browsers_path())
    if not os.path.isdir(browsers_path):
        return False
    return any(
        e.startswith("chromium") and os.path.isdir(os.path.join(browsers_path, e))
        for e in os.listdir(browsers_path)
    )


def _install_chromium(status_cb):
    os.makedirs(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", _playwright_browsers_path()), exist_ok=True)
    try:
        from playwright._impl._driver import compute_driver_executable
        result = compute_driver_executable()
        cmd = list(result) if isinstance(result, (list, tuple)) else [str(result)]
        cmd += ["install", "chromium"]
    except Exception as e:
        raise RuntimeError(f"playwright 드라이버를 찾을 수 없습니다: {e}")

    env = os.environ.copy()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if line:
            status_cb(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"설치 실패 (종료 코드: {proc.returncode})")


# ── Setup Worker & Window ──────────────────────────────────────────────────────

class SetupWorker(QObject):
    status   = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            _install_chromium(self.status.emit)
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class SetupWindow(QWidget):
    setup_done = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("pinnow")
        self.setFixedSize(400, 300)
        self.setStyleSheet(f"background: {BG};")
        self._build_ui()
        self._start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 34, 40, 34)
        layout.setSpacing(0)

        title = QLabel("pinnow")
        title.setFont(_brand_font(48))
        title.setStyleSheet(f"color: {WHITE};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(2)

        headline = QLabel("첫 실행 준비 중")
        headline.setFont(_ui_font(15, QFont.Weight.Bold))
        headline.setStyleSheet(f"color: {MUTED};")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(headline)

        layout.addSpacing(30)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)   # indeterminate
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                border: none; border-radius: 4px; background: {PANEL};
            }}
            QProgressBar::chunk {{
                border-radius: 4px; background: {SILVER};
            }}
        """)
        layout.addWidget(self.bar)

        layout.addSpacing(14)

        self.status_lbl = QLabel("Pinterest 보드 스캔용 브라우저를 설치하고 있어요.")
        self.status_lbl.setFont(QFont("Menlo", 10))
        self.status_lbl.setStyleSheet(f"color: {SILVER_D};")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        layout.addStretch()

        note = QLabel("약 150-200 MB · 최초 1회만 설치됩니다.")
        note.setFont(_ui_font(11))
        note.setStyleSheet(f"color: {MUTED};")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)

    def _start(self):
        self._thread = QThread()
        self._worker = SetupWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self.status_lbl.setText)
        self._worker.finished.connect(self._on_done)
        self._thread.start()

    def _on_done(self, success: bool, error: str):
        self._thread.quit()
        self._thread.wait()
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if success:
            self.status_lbl.setText("설치 완료! 앱을 시작합니다...")
            QTimer.singleShot(1000, self.setup_done.emit)
        else:
            self.status_lbl.setText(f"오류: {error}\n앱을 다시 시작해 주세요.")


# ── Worker ────────────────────────────────────────────────────────────────────

class DownloadWorker(QObject):
    log          = pyqtSignal(str)
    progress     = pyqtSignal(int, int)
    status       = pyqtSignal(str)
    finished     = pyqtSignal(int, int, str)
    failed_urls  = pyqtSignal(list)

    def __init__(self, url: str, output: str, max_pins: int):
        super().__init__()
        self.url = url
        self.output = output
        self.max_pins = max_pins
        self._stop = False

    def run(self):
        try:
            os.makedirs(self.output, exist_ok=True)
            url = self.url
            # pin.it 단축 URL은 실제 URL로 먼저 resolve
            if "pin.it" in url:
                self.status.emit("URL 확인 중...")
                url = core.resolve_short_url(url)
                self.log.emit(f"→ {url}")
            is_pin = bool(re.search(r"/pin/\d+", url))
            self.url = url

            if is_pin:
                self.status.emit("이미지 URL 가져오는 중...")
                self.log.emit(f"핀: {self.url}")
                img_url, pin_id = core.get_pin_image_url(self.url)
                if not img_url:
                    self.log.emit("이미지 URL을 찾을 수 없습니다.")
                    self.finished.emit(0, 1, "")
                    return
                clean = img_url.split("?")[0]
                ext = clean.rsplit(".", 1)[-1] or "jpg"
                safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(pin_id))
                dest = os.path.join(self.output, f"pin_{safe_id}.{ext}")
                self.status.emit("다운로드 중...")
                self.progress.emit(0, 1)
                ok = core.download_with_fallback(img_url, dest)
                self.progress.emit(1, 1)
                if ok:
                    self.log.emit(f"저장 완료  {dest}")
                    self.finished.emit(1, 0, "")
                else:
                    self.log.emit("다운로드 실패")
                    self.finished.emit(0, 1, "")
            else:
                self.status.emit("보드 스캔 중...")
                self.log.emit(f"보드: {self.url}")
                pin_list = core.fetch_board_pins(self.url, self.max_pins, log_cb=self.log.emit)
                self.log.emit(f"{len(pin_list)}개 핀 발견")
                self.status.emit(f"{len(pin_list)}개 다운로드 중...")

                ok = fail = 0
                failed_urls = []
                total = len(pin_list)

                for i, p in enumerate(pin_list):
                    if self._stop:
                        self.log.emit("다운로드 중단됨")
                        break
                    ext = p["url"].split("?")[0].rsplit(".", 1)[-1] or "jpg"
                    dest = os.path.join(self.output, f"pin_{p['id']}.{ext}")
                    if os.path.exists(dest):
                        ok += 1
                    elif core.download_with_fallback(p["url"], dest):
                        ok += 1
                    else:
                        fail += 1
                        failed_urls.append(f"https://www.pinterest.com/pin/{p['id']}/")
                    self.progress.emit(i + 1, total)
                    time.sleep(0.05)

                failed_path = ""
                if failed_urls:
                    failed_path = os.path.join(self.output, "failed_pins.txt")
                    with open(failed_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(failed_urls) + "\n")
                    self.failed_urls.emit(failed_urls)

                self.finished.emit(ok, fail, failed_path)

        except Exception as e:
            self.log.emit(f"오류: {e}")
            self.finished.emit(0, 0, "")


# ── 팔레트 (아이콘 이미지 추출)
# 배경: 딥 다크 마룬 #73170E
# 실버: #D9D9D9  /  실버 어두운: #A0A0A0
# 텍스트: 흰색 on 다크, 다크 on 실버

BG       = "#73170E"   # 아이콘 배경 딥 레드
BG_LIGHT = "#8B1F12"   # 살짝 밝은 레드 (hover 등)
BG_DARK  = "#4A0C07"
PANEL    = "#681208"
BORDER   = "#A73524"
SILVER   = "#D9D9D9"   # 핀 실버
SILVER_D = "#B0B0B0"   # 실버 어두운
WHITE    = "#FFFFFF"
TEXT_W   = "#F0F0F0"   # 다크 배경 위 텍스트
TEXT_S   = "#2a2a2a"   # 실버 위 텍스트
MUTED    = "#C4A8A8"   # 다크 배경 위 보조 텍스트
MUTED_D  = "#9F7774"


# ── Custom Widgets ─────────────────────────────────────────────────────────────

class PillInput(QLineEdit):
    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(44)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setFont(_ui_font(11.0))
        self.setStyleSheet(f"""
            QLineEdit {{
                background: #F7F7F6;
                border: 3px solid {SILVER};
                border-radius: 12px;
                padding: 0 16px;
                color: {TEXT_S};
                selection-background-color: {BG};
            }}
            QLineEdit:focus {{
                background: {WHITE};
                border: 3px solid {WHITE};
                color: {BG};
            }}
            QLineEdit:hover {{
                background: {WHITE};
                border: 3px solid {WHITE};
            }}
            QLineEdit::placeholder {{
                color: #9A9A9A;
            }}
        """)


class PillButton(QPushButton):
    def __init__(self, text, primary=False, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(42)
        self.setFont(_ui_font(11.0))
        self.setStyleSheet(f"""
            QPushButton {{
                background: #F7F7F6;
                color: #8F8F8F;
                border: 3px solid {SILVER};
                border-radius: 11px;
            }}
            QPushButton:hover {{ background: {WHITE}; color: {BG}; border-color: {WHITE}; }}
            QPushButton:pressed {{ background: {SILVER_D}; }}
            QPushButton:disabled {{
                background: #EFE8E6;
                color: #B5B5B5;
                border-color: {SILVER_D};
            }}
        """)


class StatusCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setObjectName("statusCard")
        self.setStyleSheet(f"""
            QWidget#statusCard {{
                background: transparent;
                border: none;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel("⏸")
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setFont(_ui_font(11))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet(f"""
            background: {BG_DARK};
            border: 1px solid {BORDER};
            border-radius: 12px;
            color: {SILVER};
        """)
        layout.addWidget(self.icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)

        self.title_label = QLabel("ready")
        self.title_label.setFont(_ui_font(10, QFont.Weight.Bold))
        self.title_label.setStyleSheet(f"background: transparent; border: none; color: {TEXT_W};")

        self.sub_label = QLabel("waiting for a pinterest link")
        self.sub_label.setFont(_ui_font(8))
        self.sub_label.setStyleSheet(f"background: transparent; border: none; color: {MUTED_D};")

        text_col.addWidget(self.title_label)
        text_col.addWidget(self.sub_label)
        layout.addLayout(text_col)
        layout.addStretch()

        self.count_label = QLabel("")
        self.count_label.setFont(_ui_font(13, QFont.Weight.Black))
        self.count_label.setStyleSheet(f"background: transparent; border: none; color: {SILVER};")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.count_label)

    def set_state(self, icon, title, sub, count=""):
        self.icon_label.setText(icon)
        self.title_label.setText(title)
        self.sub_label.setText(sub)
        self.count_label.setText(count)


class FailedPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible = False
        self.setMaximumHeight(0)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        lbl = QLabel("다운로드 실패 목록")
        lbl.setFont(_ui_font(11, QFont.Weight.DemiBold))
        lbl.setStyleSheet(f"color: {SILVER}; background: transparent;")
        header.addWidget(lbl)
        header.addStretch()

        self.copy_btn = QPushButton("전체 복사")
        self.copy_btn.setFixedHeight(24)
        self.copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {SILVER_D};
                border-radius: 6px;
                color: {SILVER_D};
                font-size: 11px;
                padding: 0 8px;
            }}
            QPushButton:hover {{ color: {WHITE}; border-color: {SILVER}; }}
        """)
        self.copy_btn.clicked.connect(self._copy_all)
        header.addWidget(self.copy_btn)
        layout.addLayout(header)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Menlo", 10))
        self.text.setStyleSheet(f"""
            QTextEdit {{
                background: #3A0A06;
                color: {SILVER};
                border-radius: 10px;
                padding: 10px 12px;
                border: none;
            }}
        """)
        self.text.setFixedHeight(80)
        layout.addWidget(self.text)

        self.anim = QPropertyAnimation(self, b"maximumHeight")
        self.anim.setDuration(250)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def _copy_all(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.copy_btn.setText("복사됨 ✓")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("전체 복사"))

    def set_urls(self, urls: list):
        self.text.setPlainText("\n".join(urls))
        if not self._visible:
            self.anim.setStartValue(0)
            self.anim.setEndValue(112)
            self._visible = True
            self.anim.start()

    def hide_panel(self):
        if self._visible:
            self.anim.setStartValue(self.maximumHeight())
            self.anim.setEndValue(0)
            self._visible = False
            self.anim.start()


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible = False
        self.setMaximumHeight(0)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Menlo", 11))
        self.text.setStyleSheet(f"""
            QTextEdit {{
                background: #3A0A06;
                color: {SILVER};
                border-radius: 12px;
                padding: 12px 14px;
                border: none;
            }}
        """)
        self.text.setFixedHeight(80)
        layout.addWidget(self.text)

        self.anim = QPropertyAnimation(self, b"maximumHeight")
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def toggle(self):
        if self._visible:
            self.anim.setStartValue(self.maximumHeight())
            self.anim.setEndValue(0)
            self._visible = False
        else:
            self.anim.setStartValue(0)
            self.anim.setEndValue(96)
            self._visible = True
        self.anim.start()

    def append(self, msg: str):
        self.text.append(msg)
        self.text.moveCursor(QTextCursor.MoveOperation.End)


# ── 메인 윈도우 ───────────────────────────────────────────────────────────────

GLOBAL_STYLE = f"""
QMainWindow, QWidget#root {{
    background: {BG};
}}
QLabel {{
    color: {TEXT_W};
    background: transparent;
}}
QSpinBox {{
    background: #EFE8E6;
    border: 1.5px solid transparent;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 14px;
    font-weight: 700;
    color: {TEXT_S};
    min-height: 38px;
}}
QSpinBox:focus {{
    background: {WHITE};
    border: 1.5px solid {SILVER};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 20px;
    border: none;
    background: transparent;
}}
QProgressBar {{
    border: none;
    border-radius: 4px;
    background: {PANEL};
    min-height: 8px;
    max-height: 8px;
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background: {SILVER};
}}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pinnow")
        self.setFixedSize(400, 540)
        # Windows: 최대화 버튼 제거 (setFixedSize만으로는 제거 안 됨)
        if sys.platform == "win32":
            self.setWindowFlag(Qt.WindowType.MSWindowsFixedSizeDialogHint)
        self._worker = None
        self._thread = None
        self._output = os.path.expanduser("~/Downloads/pinnow")
        self.setStyleSheet(GLOBAL_STYLE)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(36, 60, 36, 18)
        layout.setSpacing(0)

        # ── Header
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        title = QLabel("pinnow")
        title.setFont(_brand_font(52))
        title.setStyleSheet(f"color: {WHITE};")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(title, 1)

        tagline = QLabel("for all the\nheavy users\nof pinterest")
        tagline.setFont(_ui_font(10.0))
        tagline.setStyleSheet(f"color: {WHITE};")
        tagline.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(tagline)

        layout.addLayout(header_row)

        layout.addSpacing(26)

        self.url_input = PillInput("drop your pinterest link here!")
        layout.addWidget(self.url_input)
        layout.addSpacing(12)

        self.dir_input = PillInput()
        self.dir_input.setPlaceholderText("your images go to")
        self.dir_input.setReadOnly(True)
        self.dir_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dir_input.mousePressEvent = lambda event: self._browse()
        layout.addWidget(self.dir_input)

        layout.addSpacing(20)

        action_row = QHBoxLayout()
        action_row.setSpacing(20)

        pin_art = QLabel()
        pin_art.setFixedSize(90, 140)
        pin_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pin_art.setPixmap(_pin_pixmap(90, 140))
        action_row.addWidget(pin_art)

        control_col = QVBoxLayout()
        control_col.setSpacing(8)

        self.start_btn = PillButton("download images", primary=True)
        self.start_btn.clicked.connect(self._start)
        control_col.addWidget(self.start_btn)

        self.stop_btn = PillButton("stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        control_col.addWidget(self.stop_btn)

        pin_box = QFrame()
        pin_box.setFixedHeight(52)
        pin_box.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: 3px solid {SILVER};
                border-radius: 10px;
            }}
        """)
        pin_layout = QVBoxLayout(pin_box)
        pin_layout.setContentsMargins(10, 6, 10, 6)
        pin_layout.setSpacing(1)

        max_label = QLabel("verified pin")
        max_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        max_label.setFont(_ui_font(11.0, QFont.Weight.Bold))
        max_label.setStyleSheet(f"color: {WHITE}; background: transparent; border: none;")
        pin_layout.addWidget(max_label)

        self.pin_count_label = QLabel("999")
        self.pin_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin_count_label.setFont(_ui_font(13.0, QFont.Weight.Bold))
        self.pin_count_label.setStyleSheet(f"""
            QLabel {{
                background: transparent;
                border: none;
                color: {WHITE};
            }}
        """)
        pin_layout.addWidget(self.pin_count_label)
        control_col.addWidget(pin_box)
        control_col.addStretch()
        action_row.addLayout(control_col, 1)

        layout.addLayout(action_row)
        layout.addSpacing(14)

        # ── 진행바
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        layout.addSpacing(8)

        # ── 상태 카드 (항상 표시 — 레이아웃 shift 방지)
        self.status_card = StatusCard()
        layout.addWidget(self.status_card)

        # ── 실패 목록 패널
        self.failed_panel = FailedPanel()
        layout.addWidget(self.failed_panel)

        layout.addStretch()

        # ── 로그 토글 & Finder 버튼
        log_row = QHBoxLayout()
        self.log_toggle = QPushButton("details")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setFixedHeight(24)
        self.log_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {MUTED_D};
                font-size: 11px;
                text-align: left;
                padding: 0;
            }}
            QPushButton:hover {{ color: {SILVER}; }}
            QPushButton:checked {{ color: {SILVER}; font-weight: 600; }}
        """)
        self.log_toggle.clicked.connect(self._toggle_log)
        log_row.addWidget(self.log_toggle)
        log_row.addStretch()

        self.open_btn = QPushButton("open folder")
        self.open_btn.setEnabled(False)
        self.open_btn.setFixedHeight(24)
        self.open_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {WHITE};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{ color: {SILVER}; }}
            QPushButton:disabled {{ color: #6B3030; }}
        """)
        self.open_btn.clicked.connect(self._open_finder)
        log_row.addWidget(self.open_btn)
        self.log_row_widget = QWidget()
        self.log_row_widget.setLayout(log_row)
        layout.addWidget(self.log_row_widget)

        self.log_panel = LogPanel()
        self.log_panel.hide()
        layout.addWidget(self.log_panel)

        footer = QLabel("all rights reserved choic0re")
        footer.setFont(_ui_font(10.0))
        footer.setStyleSheet(f"color: {WHITE};")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        root.setFocus()

    def _toggle_log(self):
        self.log_panel.toggle()
        self.log_toggle.setText("hide details" if self.log_panel._visible else "details")

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.dir_input.text() or self._output)
        if path:
            self.dir_input.setText(path)
            self._output = path

    def _set_progress(self, cur: int, total: int):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(cur)
            self.pin_count_label.setText(str(cur))
            pct = int(cur / total * 100)
            self.status_card.set_state("⬇", "다운로드 중", f"{cur} / {total}개", f"{pct}%")

    def _set_status(self, msg: str):
        self.status_card.set_state("⏳", msg, "잠시 기다려 주세요", "")

    def _log(self, msg: str):
        self.log_panel.append(msg)

    def _start(self):
        url = self.url_input.text().strip()
        output = self.dir_input.text().strip() or self._output
        if not url:
            self.status_card.set_state("⚠", "URL을 입력하세요", "pinterest.com 링크 또는 pin.it 단축 URL", "")
            return

        self._output = output
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.progress.setValue(0)
        self.pin_count_label.setText("0")
        self.log_panel.text.clear()
        self.failed_panel.hide_panel()
        self.status_card.set_state("⏳", "시작 중...", "브라우저를 여는 중입니다", "")

        self._thread = QThread()
        self._worker = DownloadWorker(url, output, 999)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(self._set_progress)
        self._worker.status.connect(self._set_status)
        self._worker.finished.connect(self._done)
        self._worker.failed_urls.connect(self.failed_panel.set_urls)
        self._thread.start()

    def _stop(self):
        if self._worker:
            self._worker._stop = True
        self.stop_btn.setEnabled(False)
        self.status_card.set_state("⏸", "중단 중...", "현재 다운로드 완료 후 멈춥니다", "")

    def _done(self, ok: int, fail: int, failed_path: str):
        self._thread.quit()
        self._thread.wait()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.open_btn.setEnabled(True)
        self.progress.setMaximum(max(ok + fail, 1))
        self.progress.setValue(ok + fail)
        self.pin_count_label.setText(str(ok))

        if fail == 0:
            self.status_card.set_state("✓", "완료", "모든 이미지가 저장되었습니다", f"{ok}개")
        else:
            self.status_card.set_state("⚠", f"{ok}개 성공 / {fail}개 실패", "details 눌러서 확인", f"{fail}개 누락")

        # 완료 시 log 패널 자동 오픈
        if not self.log_panel._visible:
            self.log_toggle.setChecked(True)
            self.log_panel.toggle()

    def _open_finder(self):
        path = os.path.abspath(self._output)
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main():
    # Windows: UTF-8 강제 (cp949 디코드 오류 방지)
    if sys.platform == "win32":
        os.environ["PYTHONUTF8"] = "1"
        os.environ["PYTHONIOENCODING"] = "utf-8"
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
                sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass

    # Windows: QApplication 생성 전 DPI 설정 필수
    if sys.platform == "win32":
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
        os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "RoundPreferFloor")

    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv)

    lock_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation) or _user_cache_dir()
    os.makedirs(lock_dir, exist_ok=True)
    lock = QLockFile(os.path.join(lock_dir, f"pinnow.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        return

    app._pinnow_lock = lock
    app.setStyle("macOS" if sys.platform == "darwin" else "Fusion")

    # Windows Fusion 테마의 기본 팔레트가 앱 배경을 덮어쓰는 문제 방지
    if sys.platform == "win32":
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Window,         QColor(BG))
        pal.setColor(QPalette.ColorRole.WindowText,     QColor(TEXT_W))
        pal.setColor(QPalette.ColorRole.Base,           QColor(BG_DARK))
        pal.setColor(QPalette.ColorRole.AlternateBase,  QColor(BG_LIGHT))
        pal.setColor(QPalette.ColorRole.Text,           QColor(TEXT_W))
        pal.setColor(QPalette.ColorRole.BrightText,     QColor(WHITE))
        pal.setColor(QPalette.ColorRole.Button,         QColor(SILVER))
        pal.setColor(QPalette.ColorRole.ButtonText,     QColor(TEXT_S))
        pal.setColor(QPalette.ColorRole.Highlight,      QColor(BG_LIGHT))
        pal.setColor(QPalette.ColorRole.HighlightedText,QColor(WHITE))
        app.setPalette(pal)

    app.setFont(_ui_font(13))

    if _is_browser_installed():
        win = MainWindow()
        win.show()
    else:
        setup = SetupWindow()
        state = {"win": None}

        def _launch():
            setup.close()
            win = MainWindow()
            state["win"] = win
            win.show()

        setup.setup_done.connect(_launch)
        setup.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
