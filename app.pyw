#!/usr/bin/env python3
"""
Screen Recorder — PySide6 + FFmpeg
Requires: pip install PySide6 && sudo apt install ffmpeg

Audio: uses PulseAudio monitor of default sink (captures whatever plays through speakers).
If no PulseAudio, falls back to ALSA default.
"""

import sys
import os
import subprocess
import signal
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QBrush, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QSizePolicy, QGraphicsDropShadowEffect,
    QFileDialog
)


# ─── AUDIO DETECTION ─────────────────────────────────────────────────────────

def detect_audio_source():
    """
    Returns (driver, device) tuple for ffmpeg audio capture.
    Priority: PulseAudio monitor source → PulseAudio default → ALSA default
    """
    try:
        # Try to get PulseAudio default sink monitor
        out = subprocess.check_output(
            ["pactl", "get-default-sink"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        if out:
            monitor = out + ".monitor"
            return ("pulse", monitor)
    except Exception:
        pass

    # Fallback: pulse with 'default'
    try:
        subprocess.check_output(
            ["pactl", "info"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return ("pulse", "default")
    except Exception:
        pass

    # Fallback: ALSA
    return ("alsa", "default")


# ─── PALETTE ─────────────────────────────────────────────────────────────────

T_DARK = {
    "bg":        "#141416",
    "surface":   "#1a1a1d",
    "surface2":  "#202023",
    "surface3":  "#2a2a2e",
    "border":    "#2e2e33",
    "text":      "#e8e8ec",
    "text2":     "#8a8a96",
    "text3":     "#48484f",
    "accent":    "#c0392b",
    "accentH":   "#a83224",
    "green":     "#2e9e58",
}

T_LIGHT = {
    "bg":        "#ffffff",
    "surface":   "#ffffff",
    "surface2":  "#f2f2f7",
    "surface3":  "#e5e5ea",
    "border":    "#d1d1d6",
    "text":      "#000000",
    "text2":     "#3c3c43",
    "text3":     "#8e8e93",
    "accent":    "#ff3b30",
    "accentH":   "#d73329",
    "green":     "#34c759",
}

T = T_DARK.copy()


# ─── FFMPEG THREAD ───────────────────────────────────────────────────────────

class RecorderThread(QThread):
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, output_path, quality, audio, parent=None):
        super().__init__(parent)
        self.output_path = output_path
        self.quality     = quality
        self.audio       = audio
        self._process    = None

    def run(self):
        display = os.environ.get("DISPLAY", ":0")
        crf_map = {"Low": "36", "Medium": "28", "High": "20", "Ultra": "14"}
        crf     = crf_map.get(self.quality, "28")

        cmd = [
            "ffmpeg", "-y",
            "-f", "x11grab",
            "-framerate", "30",
            "-i", f"{display}+0,0",
        ]

        if self.audio:
            driver, device = detect_audio_source()
            cmd += ["-f", driver, "-i", device]

        cmd += [
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", crf,
            "-pix_fmt", "yuv420p",
        ]

        if self.audio:
            cmd += ["-c:a", "aac", "-b:a", "128k"]

        cmd.append(self.output_path)

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,
            )
            _, err = self._process.communicate()
            if self._process.returncode not in (0, 255, -2):
                # Non-zero exit that isn't SIGINT — might be audio error
                # Retry without audio if audio was enabled
                if self.audio and b"Error opening input" in (err or b""):
                    self._retry_no_audio(display, crf)
                    return
            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))

    def _retry_no_audio(self, display, crf):
        """Silently retry without audio capture if audio device failed."""
        cmd = [
            "ffmpeg", "-y",
            "-f", "x11grab", "-framerate", "30",
            "-i", f"{display}+0,0",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", crf, "-pix_fmt", "yuv420p",
            self.output_path,
        ]
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
            self._process.wait()
            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        if self._process and self._process.poll() is None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGINT)
            except ProcessLookupError:
                pass


# ─── WAVEFORM ────────────────────────────────────────────────────────────────

class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._bars   = [0.10] * 56
        self._t      = QTimer(self)
        self._t.timeout.connect(self._step)
        self.setFixedHeight(36)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def start(self):
        self._active = True
        self._t.start(65)

    def stop(self):
        self._active = False
        self._t.stop()
        self._bars = [0.10] * 56
        self.update()

    def _step(self):
        import random
        self._bars.pop(0)
        self._bars.append(random.uniform(0.08, 1.0))
        self.update()

    def paintEvent(self, ev):
        p    = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n    = len(self._bars)
        gap  = 2
        bw   = max(2, (w - gap * (n - 1)) // n)
        mid  = int(n * 0.64)

        for i, v in enumerate(self._bars):
            bh = max(2, int(v * (h - 4)))
            x  = i * (bw + gap)
            y  = (h - bh) // 2

            if self._active and i <= mid:
                c = QColor(T["accent"])
                c.setAlpha(200 if i > mid - 6 else 120)
            else:
                c = QColor(T["border"])
                c.setAlpha(220)

            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x, y, bw, bh, 1, 1)


# ─── STATUS DOT ──────────────────────────────────────────────────────────────

class Dot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(7, 7)
        self._color = T["text3"]
        self._alpha = 255
        self._t     = QTimer(self)
        self._t.timeout.connect(self._blink)

    def recording(self):
        self._color = T["accent"]
        self._t.start(540)

    def idle(self, saved=False):
        self._color = T["green"] if saved else T["text3"]
        self._t.stop()
        self._alpha = 255
        self.update()

    def _blink(self):
        self._alpha = 70 if self._alpha == 255 else 255
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._color)
        c.setAlpha(self._alpha)
        p.setBrush(QBrush(c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 7, 7)

    def update_theme(self):
        self._color = T["accent"] if self._t.isActive() else T["text3"]
        self.update()


# ─── MAIN WINDOW ─────────────────────────────────────────────────────────────

class Recorder(QMainWindow):
    def __init__(self):
        super().__init__()
        self._is_dark   = True
        self._recording = False
        self._thread    = None
        self._elapsed   = 0
        self._cd_val    = 0
        self._save_dir  = str(Path.home() / "Videos")
        self._drag_pos  = None
        Path(self._save_dir).mkdir(exist_ok=True)

        self.setWindowTitle("Recorder")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(410, 460)

        self._build()
        self._apply_styles()

    # ── BUILD ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)

        card = QWidget()
        card.setObjectName("card")
        sh = QGraphicsDropShadowEffect()
        sh.setBlurRadius(60)
        sh.setOffset(0, 16)
        sh.setColor(QColor(0, 0, 0, 160))
        card.setGraphicsEffect(sh)

        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── Titlebar ─────────────────────────────────────────────────────────
        tb   = QWidget()
        tb.setObjectName("tb")
        tb.setFixedHeight(46)
        tbh  = QHBoxLayout(tb)
        tbh.setContentsMargins(16, 0, 12, 0)
        tbh.setSpacing(8)

        self._dot = Dot()
        self._lbl_st = QLabel("Ready")
        self._lbl_st.setObjectName("lbl_st")

        tbh.addWidget(self._dot)
        tbh.addWidget(self._lbl_st)
        tbh.addStretch()

        # Window controls
        self._btn_min   = self._mkbtn("−", 28, 28, "wc_btn")
        self._btn_theme = self._mkbtn("◑", 28, 28, "wc_btn")
        self._btn_close = self._mkbtn("✕", 28, 28, "wc_close")

        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_theme.clicked.connect(self._toggle_theme)
        self._btn_close.clicked.connect(self.close)

        tbh.addWidget(self._btn_min)
        tbh.addWidget(self._btn_theme)
        tbh.addSpacing(2)
        tbh.addWidget(self._btn_close)

        v.addWidget(tb)

        # ── Body ─────────────────────────────────────────────────────────────
        body  = QWidget()
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(22, 20, 22, 22)
        body_v.setSpacing(0)

        # Title row
        tr = QHBoxLayout()
        tl = QVBoxLayout()
        tl.setSpacing(1)

        sup = QLabel("SCREEN")
        sup.setObjectName("lbl_sup")
        main = QLabel("Recorder")
        main.setObjectName("lbl_main")
        tl.addWidget(sup)
        tl.addWidget(main)

        self._lbl_timer = QLabel("00:00")
        self._lbl_timer.setObjectName("lbl_timer")
        self._lbl_timer.setAlignment(Qt.AlignRight | Qt.AlignBottom)

        tr.addLayout(tl)
        tr.addStretch()
        tr.addWidget(self._lbl_timer)

        body_v.addLayout(tr)
        body_v.addSpacing(18)

        # Waveform
        ww = QWidget()
        ww.setObjectName("wave_wrap")
        ww.setFixedHeight(52)
        wl = QVBoxLayout(ww)
        wl.setContentsMargins(14, 8, 14, 8)
        self._wave = WaveformWidget()
        wl.addWidget(self._wave)
        body_v.addWidget(ww)
        body_v.addSpacing(24)

        # Settings — no dividers, just vertical spacing
        body_v.addWidget(self._row("Quality", self._combo(["Low", "Medium", "High", "Ultra"], 1), "_q"))
        body_v.addSpacing(10)
        body_v.addWidget(self._row("Format",  self._combo(["mp4", "mkv", "webm"], 0), "_f"))
        body_v.addSpacing(10)

        # Audio checkbox row
        ar  = QHBoxLayout()
        ar.setContentsMargins(0, 0, 0, 0)
        albl = QLabel("Audio")
        albl.setObjectName("lbl_row")
        albl.setFixedWidth(88)
        self._chk = QCheckBox("Capture system / mic audio")
        self._chk.setObjectName("chk")
        self._chk.setChecked(True)
        ar.addWidget(albl)
        ar.addWidget(self._chk)
        body_v.addLayout(ar)
        body_v.addSpacing(10)

        # Path row
        pr  = QHBoxLayout()
        pr.setContentsMargins(0, 0, 0, 0)
        plbl = QLabel("Save to")
        plbl.setObjectName("lbl_row")
        plbl.setFixedWidth(88)
        self._lbl_path = QLabel(self._save_dir)
        self._lbl_path.setObjectName("lbl_path")
        self._lbl_path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._btn_path = self._mkbtn("…", 28, 26, "wc_btn")
        self._btn_path.clicked.connect(self._pick_dir)
        pr.addWidget(plbl)
        pr.addWidget(self._lbl_path)
        pr.addWidget(self._btn_path)
        body_v.addLayout(pr)
        body_v.addSpacing(24)

        # Action row
        act = QHBoxLayout()
        act.setSpacing(8)
        self._btn_rec  = self._mkbtn("● Record", 130, 36, "btn_rec")
        self._btn_stop = self._mkbtn("■ Stop",    98, 36, "btn_stop")
        self._btn_stop.setEnabled(False)
        self._btn_rec.clicked.connect(self._on_record)
        self._btn_stop.clicked.connect(self._on_stop)
        act.addWidget(self._btn_rec)
        act.addWidget(self._btn_stop)
        act.addStretch()
        body_v.addLayout(act)

        v.addWidget(body)
        outer.addWidget(card)

        # Timers
        self._tmr_cd  = QTimer(self)
        self._tmr_cd.timeout.connect(self._tick_cd)
        self._tmr_el  = QTimer(self)
        self._tmr_el.timeout.connect(self._tick_el)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _mkbtn(self, text, w, h, obj):
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setFixedSize(w, h)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _combo(self, items, default=0):
        cb = QComboBox()
        cb.setObjectName("combo")
        cb.setCursor(Qt.PointingHandCursor)
        for i in items:
            cb.addItem(i)
        cb.setCurrentIndex(default)
        cb.setFixedWidth(124)
        return cb

    def _row(self, label, widget, attr):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setObjectName("lbl_row")
        lbl.setFixedWidth(88)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(widget)
        setattr(self, attr, widget)
        w = QWidget()
        w.setLayout(row)
        return w

    def _noop(self):
        pass

    def _toggle_theme(self):
        self._is_dark = not self._is_dark
        T.update(T_DARK if self._is_dark else T_LIGHT)
        self._apply_styles()
        self._dot.update_theme()
        self._wave.update()

    # ── STYLES ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        # SF Pro fallback chain
        sf = "'SF Pro Display', '.SF NS Display', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif"
        sfm = "'SF Mono', 'SF Pro Mono', 'DejaVu Sans Mono', monospace"
        t   = T

        self.setStyleSheet(f"""
            QWidget#root {{ background: transparent; }}

            QWidget#card {{
                background: {t['surface']};
                border-radius: 10px;
                border: 1px solid {t['border']};
            }}

            QWidget#tb {{
                background: {t['surface2']};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom: 1px solid {t['border']};
            }}

            QWidget#wave_wrap {{
                background: {t['surface2']};
                border: 1px solid {t['border']};
                border-radius: 6px;
            }}

            QLabel#lbl_st {{
                color: {t['text3']};
                font-size: 11px;
                font-family: {sfm};
                letter-spacing: 0.3px;
            }}
            QLabel#lbl_sup {{
                color: {t['text3']};
                font-size: 10px;
                font-family: {sf};
                font-weight: 500;
                letter-spacing: 2.5px;
            }}
            QLabel#lbl_main {{
                color: {t['text']};
                font-size: 30px;
                font-weight: 600;
                font-family: {sf};
            }}
            QLabel#lbl_timer {{
                color: {t['text3']};
                font-size: 20px;
                font-weight: 300;
                font-family: {sfm};
                letter-spacing: 2px;
            }}
            QLabel#lbl_row {{
                color: {t['text2']};
                font-size: 12px;
                font-family: {sf};
                font-weight: 400;
            }}
            QLabel#lbl_path {{
                color: {t['text3']};
                font-size: 11px;
                font-family: {sf};
            }}

            QComboBox#combo {{
                background: {t['surface2']};
                color: {t['text']};
                border: 1px solid {t['border']};
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 12px;
                font-family: {sf};
            }}
            QComboBox#combo:hover {{ border-color: {t['surface3']}; }}
            QComboBox#combo::drop-down {{ border: none; width: 14px; }}
            QComboBox#combo QAbstractItemView {{
                background: {t['surface2']};
                color: {t['text']};
                border: 1px solid {t['border']};
                selection-background-color: {t['surface3']};
                selection-color: {t['text']};
                outline: none;
            }}

            QCheckBox#chk {{
                color: {t['text2']};
                font-size: 12px;
                font-family: {sf};
                spacing: 8px;
            }}
            QCheckBox#chk::indicator {{
                width: 14px; height: 14px;
                border-radius: 3px;
                border: 1px solid {t['border']};
                background: {t['surface2']};
            }}
            QCheckBox#chk::indicator:checked {{
                background: {t['accent']};
                border: 1px solid {t['accent']};
            }}

            QPushButton#wc_btn {{
                background: transparent;
                color: {t['text3']};
                border: none;
                border-radius: 5px;
                font-size: 13px;
                font-family: {sf};
            }}
            QPushButton#wc_btn:hover {{
                background: {t['surface3']};
                color: {t['text2']};
            }}

            QPushButton#wc_close {{
                background: transparent;
                color: {t['text3']};
                border: none;
                border-radius: 5px;
                font-size: 11px;
                font-family: {sf};
            }}
            QPushButton#wc_close:hover {{
                background: {t['accent']};
                color: #ffffff;
            }}

            QPushButton#btn_rec {{
                background: {t['accent']};
                color: #ffffff;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                font-weight: 500;
                font-family: {sf};
                letter-spacing: 0.1px;
            }}
            QPushButton#btn_rec:hover {{ background: {t['accentH']}; }}
            QPushButton#btn_rec:disabled {{
                background: {t['surface3']};
                color: {t['text3']};
            }}

            QPushButton#btn_stop {{
                background: {t['surface2']};
                color: {t['text2']};
                border: 1px solid {t['border']};
                border-radius: 5px;
                font-size: 12px;
                font-weight: 500;
                font-family: {sf};
            }}
            QPushButton#btn_stop:hover {{
                background: {t['surface3']};
                color: {t['text']};
            }}
            QPushButton#btn_stop:disabled {{
                background: {t['surface2']};
                color: {t['text3']};
                border-color: {t['border']};
            }}
        """)

    # ── LOGIC ─────────────────────────────────────────────────────────────────

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Save recordings to", self._save_dir)
        if d:
            self._save_dir = d
            self._lbl_path.setText(d if len(d) < 36 else "…" + d[-32:])

    def _on_record(self):
        if self._recording:
            return
        self._cd_val = 3
        self._btn_rec.setEnabled(False)
        self._lbl_st.setText(f"Starting in {self._cd_val}…")
        self._tmr_cd.start(1000)

    def _tick_cd(self):
        self._cd_val -= 1
        if self._cd_val > 0:
            self._lbl_st.setText(f"Starting in {self._cd_val}…")
        else:
            self._tmr_cd.stop()
            self._start()

    def _start(self):
        fmt     = self._f.currentText()
        quality = self._q.currentText()
        audio   = self._chk.isChecked()
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        out     = os.path.join(self._save_dir, f"rec_{ts}.{fmt}")

        self._thread = RecorderThread(out, quality, audio, self)
        self._thread.finished.connect(self._on_done)
        self._thread.error.connect(self._on_err)
        self._thread.start()

        self._recording = True
        self._elapsed   = 0
        self._wave.start()
        self._dot.recording()
        self._tmr_el.start(1000)
        self._btn_stop.setEnabled(True)
        self._lbl_st.setText("Recording")

        QTimer.singleShot(300, self.showMinimized)

    def _on_stop(self):
        if self._thread:
            self._thread.stop()
        self._recording = False
        self._wave.stop()
        self._tmr_el.stop()
        self._btn_rec.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._lbl_timer.setText("00:00")
        self._lbl_st.setText("Saving…")

    def _tick_el(self):
        self._elapsed += 1
        m, s = divmod(self._elapsed, 60)
        self._lbl_timer.setText(f"{m:02d}:{s:02d}")

    def _on_done(self, path):
        self._dot.idle(saved=True)
        self._lbl_st.setText("Saved")
        self.showNormal()

    def _on_err(self, msg):
        self._dot.idle()
        self._lbl_st.setText("Error")
        self._recording = False
        self._wave.stop()
        self._tmr_el.stop()
        self._btn_rec.setEnabled(True)
        self._btn_stop.setEnabled(False)

    # ── DRAG ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()


# ─── ENTRY ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Recorder")
    win = Recorder()
    win.show()
    sys.exit(app.exec())
