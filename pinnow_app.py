#!/usr/bin/env python3
"""pinnow — Pinterest Downloader (macOS GUI)"""

import sys
import os
import subprocess

os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    os.path.expanduser("~/Library/Caches/ms-playwright"),
)
import re
import time
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QTextEdit,
    QFileDialog, QSpinBox, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QPropertyAnimation, QEasingCurve, QRect, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QTextCursor, QPainter, QBrush, QPen, QLinearGradient, QIcon, QPixmap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pinnow as core


# ── Browser setup helpers ─────────────────────────────────────────────────────

def _is_browser_installed() -> bool:
    browsers_path = os.environ.get(
        "PLAYWRIGHT_BROWSERS_PATH",
        os.path.expanduser("~/Library/Caches/ms-playwright"),
    )
    if not os.path.isdir(browsers_path):
        return False
    return any(
        e.startswith("chromium") and os.path.isdir(os.path.join(browsers_path, e))
        for e in os.listdir(browsers_path)
    )


def _install_chromium(status_cb):
    try:
        from playwright._impl._driver import compute_driver_executable
        result = compute_driver_executable()
        cmd = list(result) if isinstance(result, (list, tuple)) else [str(result)]
        cmd += ["install", "chromium"]
    except Exception as e:
        raise RuntimeError(f"playwright 드라이버를 찾을 수 없습니다: {e}")

    env = os.environ.copy()
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
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
        self.setFixedSize(460, 300)
        self.setStyleSheet(f"background: {BG};")
        self._build_ui()
        self._start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(52, 44, 52, 44)
        layout.setSpacing(0)

        title = QLabel("pinnow")
        title.setFont(QFont(".AppleSystemUIFont", 28, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {WHITE}; letter-spacing: -0.5px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(6)

        headline = QLabel("브라우저 첫 실행 준비 중")
        headline.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.Medium))
        headline.setStyleSheet(f"color: {MUTED};")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(headline)

        layout.addSpacing(28)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)   # indeterminate
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                border: none; border-radius: 3px; background: {BG_LIGHT};
            }}
            QProgressBar::chunk {{
                border-radius: 3px; background: {SILVER};
            }}
        """)
        layout.addWidget(self.bar)

        layout.addSpacing(14)

        self.status_lbl = QLabel("Chromium 다운로드 중...")
        self.status_lbl.setFont(QFont("Menlo", 10))
        self.status_lbl.setStyleSheet(f"color: {SILVER_D};")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        layout.addStretch()

        note = QLabel("Pinterest 보드 스캔에 필요한 브라우저입니다.\n약 150–200 MB · 최초 1회만 설치됩니다.")
        note.setFont(QFont(".AppleSystemUIFont", 11))
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
                pin_list = core.fetch_board_pins(self.url, self.max_pins)
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
                    with open(failed_path, "w") as f:
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
SILVER   = "#D9D9D9"   # 핀 실버
SILVER_D = "#B0B0B0"   # 실버 어두운
WHITE    = "#FFFFFF"
TEXT_W   = "#F0F0F0"   # 다크 배경 위 텍스트
TEXT_S   = "#2a2a2a"   # 실버 위 텍스트
MUTED    = "#C4A8A8"   # 다크 배경 위 보조 텍스트


# ── Custom Widgets ─────────────────────────────────────────────────────────────

class PillInput(QLineEdit):
    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(44)
        self.setStyleSheet(f"""
            QLineEdit {{
                background: {SILVER};
                border: 1.5px solid transparent;
                border-radius: 12px;
                padding: 0 16px;
                font-size: 13px;
                color: {TEXT_S};
                selection-background-color: {BG};
            }}
            QLineEdit:focus {{
                background: {WHITE};
                border: 1.5px solid {SILVER_D};
            }}
            QLineEdit::placeholder {{
                color: #999999;
            }}
        """)


class PillButton(QPushButton):
    def __init__(self, text, primary=False, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(44)
        if primary:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {SILVER};
                    color: {BG};
                    border: none;
                    border-radius: 12px;
                    font-size: 14px;
                    font-weight: 700;
                    letter-spacing: 0.2px;
                }}
                QPushButton:hover {{ background: {WHITE}; }}
                QPushButton:pressed {{ background: {SILVER_D}; }}
                QPushButton:disabled {{
                    background: {BG_LIGHT};
                    color: {MUTED};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {SILVER};
                    border: 1.5px solid {SILVER_D};
                    border-radius: 12px;
                    font-size: 13px;
                    font-weight: 500;
                }}
                QPushButton:hover {{ background: {BG_LIGHT}; color: {WHITE}; }}
                QPushButton:pressed {{ background: {BG}; }}
                QPushButton:disabled {{ color: {MUTED}; border-color: #6B3030; }}
            """)


class StatusCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setObjectName("statusCard")
        self.setStyleSheet(f"""
            QWidget#statusCard {{
                background: {BG_LIGHT};
                border-radius: 14px;
                border: 1px solid #A03020;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(14)

        self.icon_label = QLabel("⏸")
        self.icon_label.setFixedWidth(28)
        self.icon_label.setFont(QFont(".AppleSystemUIFont", 20))
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self.title_label = QLabel("준비됨")
        self.title_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet(f"background: transparent; border: none; color: {TEXT_W};")

        self.sub_label = QLabel("URL을 입력하고 다운로드를 시작하세요")
        self.sub_label.setFont(QFont(".AppleSystemUIFont", 11))
        self.sub_label.setStyleSheet(f"background: transparent; border: none; color: {MUTED};")

        text_col.addWidget(self.title_label)
        text_col.addWidget(self.sub_label)
        layout.addLayout(text_col)
        layout.addStretch()

        self.count_label = QLabel("")
        self.count_label.setFont(QFont(".AppleSystemUIFont", 22, QFont.Weight.Bold))
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
        lbl.setFont(QFont(".AppleSystemUIFont", 11, QFont.Weight.DemiBold))
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
        self.text.setFixedHeight(120)
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
            self.anim.setEndValue(154)
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
        self.text.setFixedHeight(130)
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
            self.anim.setEndValue(146)
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
    background: {SILVER};
    border: 1.5px solid transparent;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 13px;
    color: {TEXT_S};
    min-height: 36px;
}}
QSpinBox:focus {{
    background: {WHITE};
    border: 1.5px solid {SILVER_D};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 20px;
    border: none;
    background: transparent;
}}
QProgressBar {{
    border: none;
    border-radius: 3px;
    background: {BG_LIGHT};
    max-height: 6px;
}}
QProgressBar::chunk {{
    border-radius: 3px;
    background: {SILVER};
}}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pinnow")
        self.setMinimumSize(520, 560)
        self.setMaximumWidth(640)
        self.resize(560, 600)
        self._worker = None
        self._thread = None
        self._output = os.path.expanduser("~/Downloads/pinnow")
        self.setStyleSheet(GLOBAL_STYLE)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 32, 28, 24)
        layout.setSpacing(0)

        # ── Header
        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)

        dot = QLabel("●")
        dot.setFont(QFont(".AppleSystemUIFont", 16))
        dot.setStyleSheet(f"color: {SILVER};")
        logo_row.addWidget(dot)

        title = QLabel("pinnow")
        title.setFont(QFont(".AppleSystemUIFont", 22, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {WHITE}; letter-spacing: -0.5px;")
        logo_row.addWidget(title)
        logo_row.addStretch()

        sub = QLabel("Pinterest Image Downloader")
        sub.setFont(QFont(".AppleSystemUIFont", 11))
        sub.setStyleSheet(f"color: {MUTED};")
        logo_row.addWidget(sub)

        layout.addLayout(logo_row)
        layout.addSpacing(24)

        # ── URL 입력
        url_label = QLabel("URL")
        url_label.setFont(QFont(".AppleSystemUIFont", 11, QFont.Weight.Medium))
        url_label.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(url_label)
        layout.addSpacing(5)

        self.url_input = PillInput("pinterest.com/username/board  또는  pin.it/xxxxx")
        layout.addWidget(self.url_input)
        layout.addSpacing(14)

        # ── 저장 폴더
        folder_label = QLabel("저장 위치")
        folder_label.setFont(QFont(".AppleSystemUIFont", 11, QFont.Weight.Medium))
        folder_label.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(folder_label)
        layout.addSpacing(5)

        row_dir = QHBoxLayout()
        row_dir.setSpacing(8)
        self.dir_input = PillInput()
        self.dir_input.setText(self._output)
        row_dir.addWidget(self.dir_input)

        browse_btn = PillButton("찾기")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse)
        row_dir.addWidget(browse_btn)
        layout.addLayout(row_dir)
        layout.addSpacing(14)

        # ── 최대 핀 수
        row_max = QHBoxLayout()
        row_max.setSpacing(10)

        max_label = QLabel("최대 핀 수")
        max_label.setFont(QFont(".AppleSystemUIFont", 11, QFont.Weight.Medium))
        max_label.setStyleSheet(f"color: {MUTED};")
        row_max.addWidget(max_label)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 9999)
        self.max_spin.setValue(999)
        self.max_spin.setFixedWidth(100)
        row_max.addWidget(self.max_spin)
        row_max.addStretch()
        layout.addLayout(row_max)
        layout.addSpacing(22)

        # ── 버튼 행
        row_btn = QHBoxLayout()
        row_btn.setSpacing(10)

        self.start_btn = PillButton("다운로드 시작", primary=True)
        self.start_btn.setFont(QFont(".AppleSystemUIFont", 14, QFont.Weight.DemiBold))
        self.start_btn.clicked.connect(self._start)
        row_btn.addWidget(self.start_btn)

        self.stop_btn = PillButton("중단")
        self.stop_btn.setFixedWidth(80)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        row_btn.addWidget(self.stop_btn)

        layout.addLayout(row_btn)
        layout.addSpacing(18)

        # ── 진행바
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        layout.addSpacing(14)

        # ── 상태 카드
        self.status_card = StatusCard()
        layout.addWidget(self.status_card)
        layout.addSpacing(12)

        # ── 실패 목록 패널
        self.failed_panel = FailedPanel()
        layout.addWidget(self.failed_panel)
        layout.addSpacing(4)

        # ── 로그 토글 & Finder 버튼
        log_row = QHBoxLayout()
        self.log_toggle = QPushButton("로그 보기")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setFixedHeight(28)
        self.log_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {MUTED};
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

        self.open_btn = QPushButton("Finder에서 열기 →")
        self.open_btn.setEnabled(False)
        self.open_btn.setFixedHeight(28)
        self.open_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {WHITE};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ color: {SILVER}; }}
            QPushButton:disabled {{ color: #6B3030; }}
        """)
        self.open_btn.clicked.connect(self._open_finder)
        log_row.addWidget(self.open_btn)
        layout.addLayout(log_row)

        self.log_panel = LogPanel()
        layout.addWidget(self.log_panel)

        layout.addStretch()

    def _toggle_log(self):
        self.log_panel.toggle()
        self.log_toggle.setText("로그 숨기기" if self.log_panel._visible else "로그 보기")
        QTimer.singleShot(240, lambda: self.resize(self.width(),
            self.minimumSizeHint().height() + 20 if self.log_panel._visible else 600))

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.dir_input.text())
        if path:
            self.dir_input.setText(path)

    def _set_progress(self, cur: int, total: int):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(cur)
            pct = int(cur / total * 100)
            self.status_card.set_state("⬇", "다운로드 중", f"{cur} / {total}개", f"{pct}%")

    def _set_status(self, msg: str):
        self.status_card.set_state("⏳", msg, "잠시 기다려 주세요", "")

    def _log(self, msg: str):
        self.log_panel.append(msg)

    def _start(self):
        url = self.url_input.text().strip()
        output = self.dir_input.text().strip()
        if not url:
            self.status_card.set_state("⚠", "URL을 입력하세요", "pinterest.com 링크 또는 pin.it 단축 URL", "")
            return

        self._output = output
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.progress.setValue(0)
        self.log_panel.text.clear()
        self.failed_panel.hide_panel()
        self.status_card.set_state("⏳", "시작 중...", "브라우저를 여는 중입니다", "")

        self._thread = QThread()
        self._worker = DownloadWorker(url, output, self.max_spin.value())
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

        if fail == 0:
            self.status_card.set_state("✓", "완료", "모든 이미지가 저장되었습니다", f"{ok}개")
        else:
            self.status_card.set_state("⚠", f"완료  {ok}개 성공 / {fail}개 실패", "아래 링크를 다시 시도해보세요", f"{fail}개")

    def _open_finder(self):
        os.system(f'open "{self._output}"')


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("macOS")
    app.setFont(QFont(".AppleSystemUIFont", 13))

    if _is_browser_installed():
        win = MainWindow()
        win.show()
    else:
        setup = SetupWindow()
        win = MainWindow()

        def _launch():
            setup.close()
            win.show()

        setup.setup_done.connect(_launch)
        setup.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
