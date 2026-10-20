import sys
import os
import ctypes
import traceback
import faulthandler
import datetime

# ============================================================
# CRASH REPORTING
# Double-clicking main.py closes the console instantly on error,
# so every error is written to error.log (in the data folder) and
# shown in a message box.
# ============================================================

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (file locations; must come first)

ERROR_LOG = paths.ERROR_LOG


def _report_crash(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))

    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}")
    except Exception:
        pass

    print(text, file=sys.stderr)

    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            text[-1800:] + f"\n\nFull log: {ERROR_LOG}",
            "Screen Translator — error",
            0x10,
        )
    except Exception:
        pass


sys.excepthook = _report_crash

# Native crashes (segfaults inside Qt / ctranslate2) go to crash.log
try:
    _fault_file = open(paths.CRASH_LOG, "w", encoding="utf-8")
    faulthandler.enable(_fault_file)
except Exception:
    pass

import re
import html
import ctypes.wintypes
import sqlite3
import shutil
import threading
from pathlib import Path
from string import Template

# ============================================================
# ARGOS (must be configured before import of translate)
# ============================================================

# Model folders are chosen in paths.py (SCREEN_TRANSLATOR_MODELS, <app>/models, C:\\ArgosModels, ...).
import argostranslate.settings

ARGOS_DIR = paths.configure_argos()

import argostranslate.translate

import mss
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from lookup import LookupDB, is_short

from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QSystemTrayIcon, QMenu, QStyle, QTabWidget, QLineEdit,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QMessageBox, QDialog,
    QPlainTextEdit, QButtonGroup, QGraphicsDropShadowEffect, QAbstractItemView,
)
from PySide6.QtCore import (
    Qt, QRect, QPoint, QSize, QSettings, QTimer, QObject, Signal,
    QRunnable, QThreadPool, QAbstractNativeEventFilter,
)
from PySide6.QtGui import (
    QImage, QColor, QPainter, QPen, QAction, QCursor, QKeySequence, QShortcut, QFont,
    QTextCursor, QIcon,
)


# ============================================================
# SETTINGS
# ============================================================

# Order: TESSERACT_PATH env, <app>/tesseract, default install folder, PATH (see paths.py).
TESSERACT_PATH = paths.find_tesseract()
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_Q = 0x51
WM_HOTKEY = 0x0312
HOTKEY_ID = 1

APP_DIR = paths.APP_DIR
DB_PATH = paths.DB_PATH
LOOKUP_PATH = paths.LOOKUP_PATH

LANG_NAMES = {"en": "English", "ru": "Русский"}

WORD_RE = r"[A-Za-z]+(?:['-][A-Za-z]+)*"
CYR_RE = re.compile(r"[А-Яа-яЁё]")
LAT_RE = re.compile(r"[A-Za-z]")


# ============================================================
# THEME
# ============================================================

def _rgba(color, alpha):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _theme(**c):
    c["accent_soft"] = _rgba(c["accent"], 0.14)
    c["accent_soft2"] = _rgba(c["accent"], 0.35)
    return c


THEMES = {
    "Midnight": _theme(
        bg="#14161b", surface="#1c1f26", surface2="#252932", hover="#2c313b", pressed="#343a46",
        border="#2a2f39", border_hi="#3a404d", text="#e9ebef", muted="#8b92a1", faint="#6a7180",
        accent="#7c9dff", accent_hi="#93afff", on_accent="#0e1424", danger="#ff7b7b",
    ),
    "Graphite": _theme(
        bg="#161616", surface="#1f1f21", surface2="#2a2a2d", hover="#323236", pressed="#3b3b40",
        border="#2d2d31", border_hi="#3f3f45", text="#ececee", muted="#8f8f98", faint="#717179",
        accent="#f2a65a", accent_hi="#f5b878", on_accent="#1c1208", danger="#ff7b7b",
    ),
    "Forest": _theme(
        bg="#111815", surface="#18221d", surface2="#213029", hover="#293a32", pressed="#32463c",
        border="#24342b", border_hi="#34493d", text="#e6efe9", muted="#8aa095", faint="#5c7066",
        accent="#5fd39a", accent_hi="#7fe0b0", on_accent="#07140d", danger="#ff8a80",
    ),
    "Rose": _theme(
        bg="#1a1318", surface="#231a21", surface2="#2e2229", hover="#382a32", pressed="#43333c",
        border="#33262e", border_hi="#473641", text="#f3e9ee", muted="#a58f9a", faint="#826c77",
        accent="#f472b6", accent_hi="#f78fc7", on_accent="#2a0f1e", danger="#ff8a80",
    ),
    "Light": _theme(
        bg="#f3f4f8", surface="#ffffff", surface2="#eceef4", hover="#e3e6ee", pressed="#d8dce7",
        border="#dde0e9", border_hi="#c3c9d6", text="#1d2330", muted="#5f6878", faint="#8b93a3",
        accent="#2f5be6", accent_hi="#4f74ee", on_accent="#ffffff", danger="#c23636",
    ),
}

DEFAULT_THEME = "Midnight"

# The live palette. MainWindow.apply_theme() updates it in place, so everything that
# reads COLORS[...] when it is built picks up the current theme.
COLORS = dict(THEMES[DEFAULT_THEME])

STYLE_TEMPLATE = Template("""
QWidget {
    background: $bg;
    color: $text;
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLabel { background: transparent; }
QWidget#clear { background: transparent; }
QLabel#title { font-size: 21px; font-weight: 700; }
QLabel#subtitle, QLabel#muted { color: $muted; font-size: 12px; }
QLabel#caption { color: $faint; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#panelTitle { font-size: 13px; font-weight: 600; }
QLabel#status { color: $accent; font-size: 12px; }
QLabel#error { color: $danger; font-size: 12px; }
QLabel#empty { color: $faint; font-size: 13px; padding: 40px 0; }

QFrame#panel {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#panel:hover { border-color: $border_hi; }
QFrame#divider { background: $border; border: none; min-height: 1px; max-height: 1px; }

QPlainTextEdit#editor, QTextBrowser#plain {
    background: transparent;
    border: none;
    padding: 0;
    font-size: 16px;
    selection-background-color: $accent_soft2;
}
QPlainTextEdit#editor[role="output"], QTextBrowser#plain[role="output"] { color: $accent; }
QTextBrowser#plain[role="source"] { font-weight: 600; }
QTextBrowser#plain[role="details"] { font-size: 13px; }

QPushButton {
    background: $surface2;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 8px 14px;
    color: $text;
}
QPushButton:hover { background: $hover; border-color: $border_hi; }
QPushButton:pressed { background: $pressed; }
QPushButton::menu-indicator { image: none; width: 0; }
QPushButton#primary {
    background: $accent;
    border: 1px solid $accent;
    color: $on_accent;
    font-weight: 600;
}
QPushButton#primary:hover { background: $accent_hi; border-color: $accent_hi; }
QPushButton#icon {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 0;
    color: $muted;
    font-size: 14px;
    min-width: 30px; max-width: 30px;
    min-height: 28px; max-height: 28px;
}
QPushButton#icon:hover { background: $surface2; border-color: $border; color: $text; }
QPushButton#icon[active="true"] { background: $accent_soft; border-color: $accent; color: $accent; }
QPushButton#round {
    border-radius: 19px;
    padding: 0;
    font-size: 17px;
    min-width: 38px; max-width: 38px;
    min-height: 38px; max-height: 38px;
    background: $surface;
}
QPushButton#round:hover { border-color: $accent; color: $accent; }
QPushButton#seg {
    border-radius: 0;
    padding: 7px 14px;
    background: $surface;
    color: $muted;
}
QPushButton#seg:hover { color: $text; }
QPushButton#seg[pos="first"] { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#seg[pos="mid"], QPushButton#seg[pos="last"] { border-left: none; }
QPushButton#seg[pos="last"] { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QPushButton#seg:checked { background: $accent_soft; color: $accent; font-weight: 600; }

QTabWidget::pane { border: none; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: $muted;
    padding: 8px 16px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 13px;
}
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }

QLineEdit {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 9px 12px;
    selection-background-color: $accent_soft2;
}
QLineEdit:focus { border-color: $accent; }

QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item, QListWidget::item:hover, QListWidget::item:selected {
    background: transparent; border: none;
}
QFrame#card {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}
QFrame#card:hover { border-color: $border_hi; }
QFrame#card[pinned="true"] { border-left: 3px solid $accent; }

QFrame#popup {
    background: $surface;
    border: 1px solid $border_hi;
    border-radius: 14px;
}

QMenu {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item { padding: 7px 18px; border-radius: 6px; }
QMenu::item:selected { background: $surface2; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }

QToolTip {
    background: $surface2;
    color: $text;
    border: 1px solid $border;
    padding: 4px 8px;
}

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border_hi; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { height: 0; }
""")


def build_style():
    return STYLE_TEMPLATE.substitute(COLORS)


def make_label(text="", name=None, wrap=False):
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def make_button(text, name=None, tooltip=None, callback=None):
    button = QPushButton(text)
    if name:
        button.setObjectName(name)
    if tooltip:
        button.setToolTip(tooltip)
    if callback:
        button.clicked.connect(callback)
    button.setCursor(Qt.PointingHandCursor)
    return button


def make_panel():
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    return frame, layout


def make_divider():
    line = QFrame()
    line.setObjectName("divider")
    return line


# ============================================================
# TRANSLATION ENGINE
# ============================================================

def app_icon(style=None):
    """Icon from assets/icon.png (bundled with the app); falls back to a Qt standard icon."""
    base = getattr(sys, "_MEIPASS", paths.APP_DIR)
    path = os.path.join(base, "assets", "icon.png")
    if os.path.exists(path):
        return QIcon(path)
    return style.standardIcon(QStyle.SP_ComputerIcon) if style else QIcon()


class ModelMissing(Exception):
    pass


def detect_direction(text):
    """Returns (src, dst). Cyrillic-dominant text -> ru→en, otherwise en→ru."""
    if len(CYR_RE.findall(text)) > len(LAT_RE.findall(text)):
        return "ru", "en"
    return "en", "ru"


class Translator:

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}

    def _get(self, src, dst):
        key = (src, dst)
        if key in self._cache:
            return self._cache[key]

        languages = {
            lang.code: lang
            for lang in argostranslate.translate.get_installed_languages()
        }

        translation = None
        if src in languages and dst in languages:
            translation = languages[src].get_translation(languages[dst])

        if translation is not None:
            self._cache[key] = translation

        return translation

    def translate(self, text, src="en", dst="ru"):
        with self._lock:
            translation = self._get(src, dst)

            if translation is None:
                raise ModelMissing(
                    f"Argos model {src} → {dst} is not installed. Put the model folders into "
                    f"{ARGOS_DIR} (or run tools\\install_models.bat)."
                )

            # Translate line by line to keep the user's line breaks.
            lines = []
            for line in text.split("\n"):
                lines.append(translation.translate(line) if line.strip() else line)

            return "\n".join(lines)

    def safe_translate(self, text, src="en", dst="ru"):
        try:
            return True, self.translate(text, src, dst)
        except ModelMissing as e:
            return False, str(e)
        except Exception as e:
            message = f"Translation error: {type(e).__name__}: {e}"
            print(message)
            return False, message


class _TaskSignals(QObject):
    finished = Signal(int, bool, str)


class TranslateTask(QRunnable):

    def __init__(self, translator, request_id, text, src, dst):
        super().__init__()
        self.signals = _TaskSignals()
        self.translator = translator
        self.request_id = request_id
        self.text = text
        self.src = src
        self.dst = dst

    def run(self):
        ok, result = self.translator.safe_translate(self.text, self.src, self.dst)
        self.signals.finished.emit(self.request_id, ok, result)


# ============================================================
# DICTIONARY DATABASE
# ============================================================

class DictionaryDB:

    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original TEXT NOT NULL,
                translation TEXT NOT NULL,
                source_text TEXT,
                pinned INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP
            )
        """)

        column_names = [
            column["name"]
            for column in self.conn.execute("PRAGMA table_info(translations)").fetchall()
        ]

        if "last_used" not in column_names:
            self.conn.execute("ALTER TABLE translations ADD COLUMN last_used TIMESTAMP")

        self.conn.execute("""
            UPDATE translations SET last_used = created_at WHERE last_used IS NULL
        """)
        self.conn.commit()

    def add(self, original, translation, source_text=""):
        original = original.strip()
        translation = translation.strip()

        if not original or not translation:
            return

        existing = self.find(original, translation)

        if existing:
            self.conn.execute("""
                UPDATE translations
                SET last_used = CURRENT_TIMESTAMP, source_text = ?
                WHERE id = ?
            """, (source_text, existing["id"]))
        else:
            self.conn.execute("""
                INSERT INTO translations (original, translation, source_text, created_at, last_used)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (original, translation, source_text))

        self.conn.commit()

    def find(self, original, translation):
        return self.conn.execute("""
            SELECT * FROM translations
            WHERE original = ? AND translation = ?
            LIMIT 1
        """, (original.strip(), translation.strip())).fetchone()

    def get_all(self, search=""):
        search = search.strip()
        order = "ORDER BY pinned DESC, datetime(last_used) DESC, id DESC"

        if search:
            pattern = f"%{search}%"
            return self.conn.execute(f"""
                SELECT * FROM translations
                WHERE original LIKE ? OR translation LIKE ? OR source_text LIKE ?
                {order}
            """, (pattern, pattern, pattern)).fetchall()

        return self.conn.execute(f"SELECT * FROM translations {order}").fetchall()

    def toggle_pin(self, entry_id):
        self.conn.execute("""
            UPDATE translations
            SET pinned = CASE WHEN pinned = 0 THEN 1 ELSE 0 END
            WHERE id = ?
        """, (entry_id,))
        self.conn.commit()

    def delete(self, entry_id):
        self.conn.execute("DELETE FROM translations WHERE id = ?", (entry_id,))
        self.conn.commit()

    def clear_all(self):
        self.conn.execute("DELETE FROM translations")
        self.conn.commit()

    def get_by_id(self, entry_id):
        return self.conn.execute(
            "SELECT * FROM translations WHERE id = ?", (entry_id,)
        ).fetchone()

    def close(self):
        self.conn.close()


# ============================================================
# GLOBAL HOTKEY
# ============================================================

class GlobalHotkeyFilter(QAbstractNativeEventFilter):

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, eventType, message):
        if eventType == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.callback()
        return False, 0


def build_hotkey_from_qt(modifiers, key):
    modifier = 0
    names = []

    if modifiers & Qt.ControlModifier:
        modifier |= MOD_CONTROL
        names.append("Ctrl")
    if modifiers & Qt.AltModifier:
        modifier |= MOD_ALT
        names.append("Alt")
    if modifiers & Qt.ShiftModifier:
        modifier |= MOD_SHIFT
        names.append("Shift")
    if modifiers & Qt.MetaModifier:
        modifier |= MOD_WIN
        names.append("Win")

    if Qt.Key_A <= key <= Qt.Key_Z:
        letter = chr(key - Qt.Key_A + ord("A"))
        names.append(letter)
        return " + ".join(names), ord(letter)

    if Qt.Key_0 <= key <= Qt.Key_9:
        number = str(key - Qt.Key_0)
        names.append(number)
        return " + ".join(names), ord(number)

    if Qt.Key_F1 <= key <= Qt.Key_F12:
        n = key - Qt.Key_F1 + 1
        names.append(f"F{n}")
        return " + ".join(names), 0x70 + n - 1

    special_keys = {
        Qt.Key_Space: ("Space", 0x20),
        Qt.Key_Escape: ("Esc", 0x1B),
        Qt.Key_Return: ("Enter", 0x0D),
        Qt.Key_Enter: ("Enter", 0x0D),
        Qt.Key_Tab: ("Tab", 0x09),
        Qt.Key_Backspace: ("Backspace", 0x08),
        Qt.Key_Delete: ("Delete", 0x2E),
        Qt.Key_Insert: ("Insert", 0x2D),
        Qt.Key_Home: ("Home", 0x24),
        Qt.Key_End: ("End", 0x23),
        Qt.Key_PageUp: ("Page Up", 0x21),
        Qt.Key_PageDown: ("Page Down", 0x22),
        Qt.Key_Left: ("Left", 0x25),
        Qt.Key_Right: ("Right", 0x27),
        Qt.Key_Up: ("Up", 0x26),
        Qt.Key_Down: ("Down", 0x28),
    }

    if key in special_keys:
        key_name, vk = special_keys[key]
        names.append(key_name)
        return " + ".join(names), vk

    return None


class HotkeyDialog(QDialog):

    def __init__(self, parent, current_text):
        super().__init__(parent)
        self.result_hotkey = None

        self.setWindowTitle("Change Hotkey")
        self.setFixedSize(380, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        title = make_label("Screen translation hotkey", "panelTitle")
        title.setStyleSheet("font-size: 15px;")
        layout.addWidget(title)

        layout.addWidget(make_label(f"Current: {current_text}", "muted"))

        self.capture_label = make_label("Press a new key combination…", "status", wrap=True)
        self.capture_label.setStyleSheet("font-size: 15px; padding: 10px 0;")
        layout.addWidget(self.capture_label)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(make_button("Cancel", callback=self.reject))
        layout.addLayout(buttons)

    def keyPressEvent(self, event):
        key = event.key()

        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return

        modifiers = event.modifiers()

        if modifiers == Qt.NoModifier:
            self.capture_label.setText("Use at least one modifier (Alt, Ctrl, Shift or Win).")
            return

        hotkey = build_hotkey_from_qt(modifiers, key)

        if hotkey is None:
            self.capture_label.setText("This key is not supported.")
            return

        self.result_hotkey = hotkey
        self.accept()


# ============================================================
# SCREEN SELECTOR
# ============================================================

class ScreenSelector(QWidget):

    def __init__(self, screenshot, callback, geometry=None):
        super().__init__()

        self.screenshot = screenshot
        self.callback = callback
        self.start_pos = None
        self.end_pos = None

        # The screenshot is in physical pixels, Qt windows are in logical (scaled) pixels.
        # With Windows display scaling (125%, 150%...) they differ, so the ratio is needed
        # to show the picture at the right size and to map the selection back to pixels.
        geometry = geometry or QRect(0, 0, screenshot.width, screenshot.height)
        self.origin = geometry.topLeft()
        self.scale = screenshot.width / max(geometry.width(), 1)

        image = screenshot.convert("RGBA")
        self._data = image.tobytes("raw", "RGBA")
        self.qimage = QImage(
            self._data, image.width, image.height, QImage.Format_RGBA8888
        )
        self.qimage.setDevicePixelRatio(self.scale)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setCursor(QCursor(Qt.CrossCursor))
        self.setGeometry(geometry)

        self.show()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawImage(0, 0, self.qimage)
        painter.fillRect(self.rect(), QColor(8, 10, 16, 140))

        if self.start_pos and self.end_pos:
            rect = QRect(self.start_pos, self.end_pos).normalized()
            source = QRect(
                round(rect.x() * self.scale), round(rect.y() * self.scale),
                round(rect.width() * self.scale), round(rect.height() * self.scale),
            )
            painter.drawImage(rect, self.qimage, source)
            painter.setPen(QPen(QColor(COLORS["accent"]), 2))
            painter.drawRoundedRect(rect, 3, 3)
        else:
            hint = "Drag to select text  ·  Esc to cancel"
            font = QFont("Segoe UI", 11)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            w = metrics.horizontalAdvance(hint) + 32
            h = metrics.height() + 16
            box = QRect((self.width() - w) // 2, 28, w, h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(28, 31, 38, 230))
            painter.drawRoundedRect(box, h // 2, h // 2)
            painter.setPen(QColor("#e9ebef"))
            painter.drawText(box, Qt.AlignCenter, hint)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.position().toPoint()
            self.end_pos = self.start_pos
            self.update()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            self.end_pos = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self.start_pos:
            return

        self.end_pos = event.position().toPoint()
        rect = QRect(self.start_pos, self.end_pos).normalized()
        self.close()

        if rect.width() > 5 and rect.height() > 5:
            self.callback(rect, self.screenshot, self.scale, self.origin)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


# ============================================================
# DICTIONARY
# ============================================================

class DictionaryCard(QFrame):

    def __init__(self, entry, pin_callback, delete_callback,
                 variants=None, examples_loader=None, resized_callback=None):
        super().__init__()

        self.entry = entry
        self._examples_loader = examples_loader
        self._examples_loaded = False
        self._resized_callback = resized_callback
        self.setObjectName("card")
        self.setProperty("pinned", bool(entry["pinned"]))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)

        original = make_label(entry["original"], wrap=True)
        original.setStyleSheet("font-size: 15px; font-weight: 600;")
        original.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(original, 1, Qt.AlignTop)

        self.examples_button = None
        if examples_loader:
            self.examples_button = make_button("💬", "icon", "Примеры", self.toggle_examples)
            top.addWidget(self.examples_button, 0, Qt.AlignTop)

        pin_button = make_button(
            "📌", "icon",
            "Unpin" if entry["pinned"] else "Pin",
            lambda: pin_callback(entry["id"]),
        )
        pin_button.setProperty("active", bool(entry["pinned"]))
        top.addWidget(pin_button, 0, Qt.AlignTop)

        delete_button = make_button("🗑", "icon", "Delete", lambda: delete_callback(entry["id"]))
        top.addWidget(delete_button, 0, Qt.AlignTop)

        layout.addLayout(top)

        translation = make_label(entry["translation"], wrap=True)
        translation.setStyleSheet(f"font-size: 14px; color: {COLORS['accent']};")
        translation.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(translation)

        if variants:
            variants_label = make_label("Варианты перевода: " + ", ".join(variants), wrap=True)
            variants_label.setStyleSheet(f"font-size: 12px; color: {COLORS['muted']};")
            variants_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(variants_label)

        source = (entry["source_text"] or "").strip()
        if source and source != entry["original"].strip():
            source_label = make_label(f"From: {source}", wrap=True)
            source_label.setStyleSheet(f"font-size: 11px; color: {COLORS['faint']};")
            layout.addWidget(source_label)

        self.examples_label = QLabel()
        self.examples_label.setTextFormat(Qt.RichText)
        self.examples_label.setWordWrap(True)
        self.examples_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.examples_label.setStyleSheet("font-size: 12px; padding-top: 4px;")
        self.examples_label.hide()
        layout.addWidget(self.examples_label)

    def toggle_examples(self):
        showing = not self.examples_label.isHidden()

        if showing:
            self.examples_label.hide()
        else:
            if not self._examples_loaded:
                self._examples_loaded = True
                text = self._examples_loader()
                self.examples_label.setText(
                    text or f'<span style="color:{COLORS["faint"]};">Примеров не найдено</span>'
                )
            self.examples_label.show()

        self.examples_button.setProperty("active", not showing)
        self.examples_button.style().unpolish(self.examples_button)
        self.examples_button.style().polish(self.examples_button)

        self.updateGeometry()
        if self._resized_callback:
            QTimer.singleShot(0, self._resized_callback)


class CardList(QListWidget):
    """QListWidget that keeps word-wrapped item widgets at the right height."""

    def __init__(self):
        super().__init__()
        self.setSpacing(3)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_hints()

    def update_hints(self):
        width = max(100, self.viewport().width() - 8)

        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            if widget.hasHeightForWidth():
                height = widget.heightForWidth(width)
            else:
                height = widget.sizeHint().height()
            item.setSizeHint(QSize(width, height))


# ============================================================
# DETAILS: variants | examples (two columns)
# ============================================================

class DetailsView(QWidget):
    """Two columns: «Варианты перевода» on the left, «Примеры» on the right."""

    GAP = 18

    def __init__(self, max_height=190):
        super().__init__()
        self.setObjectName("clear")
        self.max_height = max_height

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.hint_label = make_label("", "muted", wrap=True)
        self.hint_label.setTextFormat(Qt.RichText)
        self.hint_label.hide()
        outer.addWidget(self.hint_label)

        self.columns = QWidget()
        self.columns.setObjectName("clear")
        row = QHBoxLayout(self.columns)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(self.GAP)

        self.variants_col, self.variants_browser = self._column("ВАРИАНТЫ ПЕРЕВОДА")
        self.examples_col, self.examples_browser = self._column("ПРИМЕРЫ")
        row.addWidget(self.variants_col, 2)
        row.addWidget(self.examples_col, 3)
        outer.addWidget(self.columns)

        self.hide()

    @staticmethod
    def _column(title):
        column = QWidget()
        column.setObjectName("clear")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(make_label(title, "caption"))

        browser = QTextBrowser()
        browser.setObjectName("plain")
        browser.setProperty("role", "details")
        browser.setOpenLinks(False)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(browser)
        layout.addStretch()
        return column, browser

    @staticmethod
    def _set_shown(widget, shown):
        if shown:
            widget.show()
        else:
            widget.hide()

    def set_content(self, variants_html="", examples_html="", hint=""):
        """Fills the columns. Returns True if there is something to show."""
        has_variants, has_examples = bool(variants_html), bool(examples_html)

        if hint and not (has_variants or has_examples):
            self.columns.hide()
            self.hint_label.setText(hint)
            self.hint_label.show()
            self.show()
            return True

        self.hint_label.hide()
        if has_variants:
            self.variants_browser.setHtml(variants_html)
        if has_examples:
            self.examples_browser.setHtml(examples_html)

        self._set_shown(self.variants_col, has_variants)
        self._set_shown(self.examples_col, has_examples)

        anything = has_variants or has_examples
        self._set_shown(self.columns, anything)
        self._set_shown(self, anything)
        return anything

    def fit(self, width):
        """Sizes the columns to their content for the given total width."""
        both = not self.variants_col.isHidden() and not self.examples_col.isHidden()
        usable = max(240, width - (self.GAP if both else 0))

        tallest = 0
        for column, browser, column_width in (
            (self.variants_col, self.variants_browser, usable * 2 // 5 if both else usable),
            (self.examples_col, self.examples_browser, usable * 3 // 5 if both else usable),
        ):
            if column.isHidden():
                continue
            browser.document().setTextWidth(column_width)
            height = int(browser.document().size().height()) + 6
            height = max(30, min(height, self.max_height))
            browser.setFixedHeight(height)
            tallest = max(tallest, height)
        return tallest


# ============================================================
# RESULT POPUP
# ============================================================

class ResultWindow(QWidget):

    SHADOW = 14

    def __init__(self, parent_window, original, translation, position, source_text=None):
        super().__init__(parent_window)

        self.parent_window = parent_window
        self.original = original
        self.translation = translation
        self.source_text = source_text or original
        self.word_map = {}
        self._drag_offset = None

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("ResultWindow { background: transparent; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SHADOW, self.SHADOW, self.SHADOW, self.SHADOW)

        card = QFrame()
        card.setObjectName("popup")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 12, 14)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        header.addWidget(make_label("EN → RU", "caption"))
        header.addStretch()
        header.addWidget(make_label("click a word for details", "muted"))
        header.addSpacing(6)
        header.addWidget(make_button("✕", "icon", "Close (Esc)", self.close))
        layout.addLayout(header)

        # Source
        self.source_browser = QTextBrowser()
        self.source_browser.setObjectName("plain")
        self.source_browser.setProperty("role", "source")
        self.source_browser.setOpenLinks(False)
        self.source_browser.anchorClicked.connect(self.word_clicked)
        self._no_scrollbars(self.source_browser)
        self.build_clickable_source()
        layout.addWidget(self.source_browser)

        layout.addWidget(make_divider())

        # Translation
        self.translation_browser = QTextBrowser()
        self.translation_browser.setObjectName("plain")
        self.translation_browser.setProperty("role", "output")
        self.translation_browser.setOpenLinks(False)
        self._no_scrollbars(self.translation_browser)
        self.show_full_translation()
        layout.addWidget(self.translation_browser)

        # Variants | examples (hidden when there is nothing to show)
        self.details_divider = make_divider()
        self.details_divider.hide()
        layout.addWidget(self.details_divider)

        self.details_view = DetailsView(max_height=210)
        layout.addWidget(self.details_view)

        # Buttons
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(make_button("📌  Pin", "primary", callback=self.pin_translation))
        buttons.addWidget(make_button("⧉  Copy", callback=self.copy_translation))
        buttons.addStretch()
        buttons.addWidget(make_button("Open app", callback=self.open_translator))
        layout.addLayout(buttons)

        if is_short(self.original):
            self.set_details(
                parent_window.details_parts(self.original, "en", "ru", translation)
            )

        self.position_window(position)

    @staticmethod
    def _no_scrollbars(widget):
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    # ---------------- content ----------------

    def build_clickable_source(self):
        self.source_browser.setHtml(
            clickable_html(self.original, self.word_map)
        )

    def word_clicked(self, url):
        word = self.word_map.get(url.toString().removeprefix("wordid:"), "")
        if word:
            self.parent_window.select_word_in_result(self, word)

    def show_full_translation(self):
        self.translation_browser.setPlainText(self.translation)

    def highlight_translation(self, word_translation, selected_word):
        self.parent_window.show_selected_word(
            self.translation_browser, self.translation, selected_word, word_translation
        )
        self.adjust_popup_size()

    def set_details(self, parts):
        """parts = (variants_html, examples_html)"""
        shown = self.details_view.set_content(parts[0], parts[1])
        if shown:
            self.details_divider.show()
        else:
            self.details_divider.hide()

    def keep_on_screen(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        if frame.bottom() > available.bottom():
            self.move(frame.x(), max(available.top(), available.bottom() - frame.height()))

    # ---------------- geometry ----------------

    def adjust_popup_size(self):
        screen = QApplication.primaryScreen()
        max_width = 760
        if screen:
            max_width = min(760, int(screen.availableGeometry().width() * 0.7))

        n = len(self.original)
        if n < 45:
            desired = 400
        elif n < 100:
            desired = 520
        elif n < 180:
            desired = 640
        else:
            desired = max_width

        if not self.details_view.isHidden():
            desired = max(desired, 580)  # two columns need some room

        desired = max(380, min(desired, max_width))
        self.setFixedWidth(desired)

        doc_width = desired - 2 * self.SHADOW - 18 - 12 - 8

        if not self.details_view.isHidden():
            self.details_view.fit(doc_width)

        for browser, cap in ((self.source_browser, 360), (self.translation_browser, 360)):
            browser.document().setTextWidth(doc_width)
            height = int(browser.document().size().height()) + 6
            browser.setFixedHeight(max(30, min(height, cap)))

        self.adjustSize()

    def position_window(self, position):
        screen = QApplication.primaryScreen()
        self.adjust_popup_size()

        if not screen:
            self.show()
            return

        available = screen.availableGeometry()
        x = position.x() - self.SHADOW
        y = position.y() + 6

        if y + self.height() > available.bottom():
            y = position.y() - self.height() - 6

        x = max(available.left(), min(x, available.right() - self.width()))
        y = max(available.top(), y)

        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    # ---------------- drag & keys ----------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    # ---------------- actions ----------------

    def pin_translation(self):
        self.parent_window.add_and_pin(self.original, self.translation, self.source_text)
        self.close()

    def copy_translation(self):
        QApplication.clipboard().setText(self.translation)

    def open_translator(self):
        self.close()
        self.parent_window.open_tab(MainWindow.TAB_SCREEN)

    def closeEvent(self, event):
        if self.parent_window.result_window is self:
            self.parent_window.result_window = None
        super().closeEvent(event)


def clickable_html(text, word_map):
    """Builds HTML where every English word is a link 'wordid:N'."""
    word_map.clear()
    parts = []
    index = 0

    for part in re.findall(WORD_RE + r"|[^A-Za-z]+", text):
        if re.fullmatch(WORD_RE, part):
            word_id = str(index)
            word_map[word_id] = part
            parts.append(
                f'<a href="wordid:{word_id}" style="color:{COLORS["text"]};'
                f'text-decoration:none;">{html.escape(part)}</a>'
            )
            index += 1
        else:
            parts.append(html.escape(part))

    return "".join(parts)


# ============================================================
# MAIN WINDOW
# ============================================================

class MainWindow(QWidget):

    TAB_TEXT = 0
    TAB_SCREEN = 1
    TAB_DICTIONARY = 2

    def __init__(self):
        super().__init__()

        self.current_text = ""
        self.current_translation = ""
        self.selector = None
        self.result_window = None
        self.main_word_map = {}

        # text translator state
        self._request_id = 0
        self._tasks = {}
        self._last_source = None
        self._last_ok = False

        self.translator = Translator()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(1)

        self.settings = QSettings("ScreenTranslator", "ScreenTranslator")
        self.hotkey_text = self.settings.value("hotkey_text", "Alt + Q")
        self.hotkey_modifiers = self.settings.value("hotkey_modifiers", MOD_ALT, type=int)
        self.hotkey_vk = self.settings.value("hotkey_vk", VK_Q, type=int)
        self.text_mode = self.settings.value("text_mode", "auto")
        if self.text_mode not in ("auto", "en-ru", "ru-en"):
            self.text_mode = "auto"

        self._screen_details_args = None
        self.theme_name = DEFAULT_THEME
        self.apply_theme(self.settings.value("theme", DEFAULT_THEME), initial=True)

        self.dictionary = DictionaryDB(DB_PATH)
        self.lookup = LookupDB(LOOKUP_PATH)
        self._lookup_hint_shown = False

        self.setWindowTitle("Screen Translator")
        self.resize(880, 660)
        self.setMinimumSize(700, 520)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(450)
        self.debounce.timeout.connect(self.run_text_translation)

        self.build_ui()
        self.setup_tray()
        self.install_hotkey()

        # Load both models in the background so the first translation is fast.
        QTimer.singleShot(300, self.warm_up_models)

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("Screen Translator", "title"))
        self.subtitle = make_label("", "subtitle")
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch()

        self.theme_button = make_button("🎨  Theme", tooltip="Change theme")
        self.theme_menu = QMenu(self)
        self.theme_actions = {}
        for theme_name in THEMES:
            action = QAction(theme_name, self)
            action.triggered.connect(lambda checked=False, n=theme_name: self.apply_theme(n))
            self.theme_menu.addAction(action)
            self.theme_actions[theme_name] = action
        self.theme_button.setMenu(self.theme_menu)
        self.update_theme_menu()
        header.addWidget(self.theme_button, 0, Qt.AlignVCenter)

        self.hotkey_button = make_button(
            "", tooltip="Change screen-capture hotkey", callback=self.change_hotkey
        )
        header.addWidget(self.hotkey_button, 0, Qt.AlignVCenter)

        self.select_button = make_button(
            "📷  Capture", "primary", "Select an area of the screen", self.start_selection
        )
        header.addWidget(self.select_button, 0, Qt.AlignVCenter)

        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)

        self.build_text_tab()
        self.build_screen_tab()
        self.build_dictionary_tab()

        self.update_hotkey_labels()

    # ========================================================
    # TEXT TRANSLATOR TAB
    # ========================================================

    def build_text_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(12)

        # --- mode bar ---
        bar = QHBoxLayout()
        bar.setSpacing(0)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}

        modes = [("auto", "Auto"), ("en-ru", "EN → RU"), ("ru-en", "RU → EN")]
        for i, (key, label) in enumerate(modes):
            button = make_button(label, "seg")
            button.setCheckable(True)
            button.setProperty("mode", key)
            button.setProperty("pos", "first" if i == 0 else "last" if i == len(modes) - 1 else "mid")
            button.setChecked(key == self.text_mode)
            self.mode_group.addButton(button)
            self.mode_buttons[key] = button
            bar.addWidget(button)

        self.mode_group.buttonClicked.connect(
            lambda b: self.set_mode(b.property("mode"))
        )

        bar.addSpacing(14)
        self.detect_label = make_label("", "muted")
        bar.addWidget(self.detect_label)
        bar.addStretch()
        bar.addWidget(make_label("Ctrl+Enter — translate now", "muted"))
        layout.addLayout(bar)

        # --- panes ---
        panes = QHBoxLayout()
        panes.setSpacing(10)

        # source
        src_panel, src_layout = make_panel()
        src_header = QHBoxLayout()
        self.src_lang_label = make_label("", "panelTitle")
        src_header.addWidget(self.src_lang_label)
        src_header.addStretch()
        self.char_count = make_label("", "muted")
        src_header.addWidget(self.char_count)
        src_header.addWidget(make_button("✕", "icon", "Clear", self.clear_text))
        src_layout.addLayout(src_header)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setObjectName("editor")
        self.input_edit.setPlaceholderText("Type or paste text…\nВведите или вставьте текст…")
        self.input_edit.textChanged.connect(self.on_input_changed)
        src_layout.addWidget(self.input_edit)

        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(seq), self.input_edit)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(self.translate_now)

        panes.addWidget(src_panel, 1)

        # swap
        swap = make_button("⇄", "round", "Swap languages", self.swap_languages)
        panes.addWidget(swap, 0, Qt.AlignVCenter)

        # output
        dst_panel, dst_layout = make_panel()
        dst_header = QHBoxLayout()
        self.dst_lang_label = make_label("", "panelTitle")
        dst_header.addWidget(self.dst_lang_label)
        dst_header.addStretch()
        self.text_status = make_label("", "status")
        dst_header.addWidget(self.text_status)
        dst_header.addWidget(make_button("⧉", "icon", "Copy translation", self.copy_text_translation))
        dst_header.addWidget(make_button("📌", "icon", "Pin to dictionary", self.pin_text_translation))
        dst_layout.addLayout(dst_header)

        self.output_edit = QPlainTextEdit()
        self.output_edit.setObjectName("editor")
        self.output_edit.setProperty("role", "output")
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("Translation")
        dst_layout.addWidget(self.output_edit)

        panes.addWidget(dst_panel, 1)
        layout.addLayout(panes, 1)

        self.text_details_panel, self.text_details = self.make_details_panel()
        layout.addWidget(self.text_details_panel)

        self.tabs.addTab(tab, "✏️  Text")
        self.update_direction_labels()

    def current_direction(self, text=None):
        if self.text_mode == "en-ru":
            return "en", "ru"
        if self.text_mode == "ru-en":
            return "ru", "en"
        if text is None:
            text = self.input_edit.toPlainText()
        return detect_direction(text)

    def update_direction_labels(self):
        text = self.input_edit.toPlainText()
        src, dst = self.current_direction(text)
        self.src_lang_label.setText(LANG_NAMES[src])
        self.dst_lang_label.setText(LANG_NAMES[dst])

        if self.text_mode == "auto" and text.strip():
            self.detect_label.setText(f"Detected: {LANG_NAMES[src]}")
        elif self.text_mode == "auto":
            self.detect_label.setText("Language is detected automatically")
        else:
            self.detect_label.setText("")

    def set_mode(self, mode):
        self.text_mode = mode
        self.mode_buttons[mode].setChecked(True)
        self.settings.setValue("text_mode", mode)
        self.update_direction_labels()
        self._last_source = None
        self.translate_now()

    def on_input_changed(self):
        text = self.input_edit.toPlainText()
        self.char_count.setText(f"{len(text)}" if text else "")
        self.update_direction_labels()

        if not text.strip():
            self.debounce.stop()
            self._request_id += 1
            self._last_source = None
            self.output_edit.clear()
            self.text_status.setText("")
            self.text_details_panel.hide()
            return

        self.debounce.start()

    def translate_now(self):
        self.debounce.stop()
        self.run_text_translation()

    def run_text_translation(self):
        text = self.input_edit.toPlainText()
        if not text.strip():
            return

        src, dst = self.current_direction(text)
        self._request_id += 1
        request_id = self._request_id

        self.text_status.setObjectName("status")
        self.text_status.setStyleSheet("")
        self.text_status.setText("Translating…")

        task = TranslateTask(self.translator, request_id, text, src, dst)
        task.signals.finished.connect(
            lambda rid, ok, result, t=text: self.on_text_translated(rid, ok, result, t)
        )
        self._tasks[request_id] = task
        self.pool.start(task)

    def on_text_translated(self, request_id, ok, result, source):
        self._tasks.pop(request_id, None)

        if request_id != self._request_id:
            return  # outdated result, user kept typing

        self._last_source = source
        self._last_ok = ok

        if ok:
            self.text_status.setText("")
            self.output_edit.setPlainText(result)
            self.update_text_details(source, result)
        else:
            self.output_edit.setPlainText("")
            self.text_details_panel.hide()
            self.flash_status("⚠ " + result, error=True, ms=8000)

    def swap_languages(self):
        text = self.input_edit.toPlainText()
        src, dst = self.current_direction(text)
        output = self.output_edit.toPlainText() if self._last_ok else ""

        if self.text_mode != "auto":
            self.text_mode = f"{dst}-{src}"
            self.mode_buttons[self.text_mode].setChecked(True)
            self.settings.setValue("text_mode", self.text_mode)

        if output.strip():
            self.input_edit.setPlainText(output)  # triggers translation
            self.input_edit.moveCursor(QTextCursor.End)
        else:
            self.update_direction_labels()
            self.translate_now()

        self.input_edit.setFocus()

    def clear_text(self):
        self.input_edit.clear()
        self.input_edit.setFocus()

    def flash_status(self, text, error=False, ms=1600):
        self.text_status.setText(text)
        self.text_status.setStyleSheet(f"color: {COLORS['danger'] if error else COLORS['accent']};")
        QTimer.singleShot(ms, lambda: self.text_status.text() == text and self.text_status.setText(""))

    def copy_text_translation(self):
        output = self.output_edit.toPlainText()
        if output.strip():
            QApplication.clipboard().setText(output)
            self.flash_status("Copied ✓")

    def pin_text_translation(self):
        source = self.input_edit.toPlainText()
        output = self.output_edit.toPlainText()

        if not source.strip() or not output.strip() or not self._last_ok:
            return

        if source != self._last_source:
            self.flash_status("Wait for the translation…")
            return

        self.add_and_pin(source.strip(), output.strip(), source.strip())
        self.flash_status("Pinned ✓")

    def warm_up_models(self):
        for src, dst in (("en", "ru"), ("ru", "en")):
            task = TranslateTask(self.translator, -1, "hi" if src == "en" else "привет", src, dst)
            self._tasks[f"warm-{src}"] = task
            self.pool.start(task)

    # ========================================================
    # SCREEN TAB
    # ========================================================

    def build_screen_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)

        src_panel, src_layout = make_panel()
        src_header = QHBoxLayout()
        src_header.addWidget(make_label("RECOGNIZED TEXT", "caption"))
        src_header.addStretch()
        src_header.addWidget(make_label("click a word to translate it", "muted"))
        src_layout.addLayout(src_header)

        self.source_browser = QTextBrowser()
        self.source_browser.setObjectName("plain")
        self.source_browser.setProperty("role", "source")
        self.source_browser.setOpenLinks(False)
        self.source_browser.anchorClicked.connect(self.word_clicked_in_main)
        self.source_browser.setPlaceholderText(
            "Press the hotkey or “Capture” and select an area with text."
        )
        src_layout.addWidget(self.source_browser)
        layout.addWidget(src_panel, 2)

        dst_panel, dst_layout = make_panel()
        dst_header = QHBoxLayout()
        dst_header.addWidget(make_label("TRANSLATION", "caption"))
        dst_header.addStretch()
        dst_header.addWidget(make_button("⧉", "icon", "Copy translation",
                                         lambda: QApplication.clipboard().setText(self.current_translation)))
        dst_header.addWidget(make_button("📌", "icon", "Pin to dictionary", self.pin_current_translation))
        dst_layout.addLayout(dst_header)

        self.translation_label = QTextBrowser()
        self.translation_label.setObjectName("plain")
        self.translation_label.setProperty("role", "output")
        self.translation_label.setOpenLinks(False)
        dst_layout.addWidget(self.translation_label)
        layout.addWidget(dst_panel, 3)

        self.screen_details_panel, self.screen_details = self.make_details_panel()
        layout.addWidget(self.screen_details_panel)

        self.tabs.addTab(tab, "📷  Screen")

    # ========================================================
    # DICTIONARY TAB
    # ========================================================

    def build_dictionary_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍  Search translations…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh_dictionary)
        top.addWidget(self.search_edit, 1)
        top.addWidget(make_button("🗑  Clear all", tooltip="Delete every entry",
                                  callback=self.clear_dictionary))
        layout.addLayout(top)

        self.dictionary_stats = make_label("", "muted")
        layout.addWidget(self.dictionary_stats)

        self.dictionary_list = CardList()
        layout.addWidget(self.dictionary_list, 1)

        self.tabs.addTab(tab, "📚  Dictionary")
        self.refresh_dictionary()

    # ========================================================
    # SCREEN CAPTURE + OCR
    # ========================================================

    def start_selection(self):
        if self.result_window:
            self.result_window.close()

        self.hide()
        QApplication.processEvents()

        screen = QApplication.primaryScreen()
        geometry = screen.geometry() if screen else None

        with mss.mss() as sct:
            data = sct.grab(sct.monitors[1])
            screenshot = Image.frombytes("RGB", data.size, data.rgb)

        self.selector = ScreenSelector(screenshot, self.process_selection, geometry)
        self.selector.show()

    def process_selection(self, rect, screenshot, scale=1.0, origin=None):
        # rect is in logical pixels; the screenshot is in physical pixels
        crop = screenshot.crop((
            round(rect.left() * scale), round(rect.top() * scale),
            round((rect.right() + 1) * scale), round((rect.bottom() + 1) * scale),
        ))
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
        crop = ImageEnhance.Contrast(crop).enhance(1.35)
        crop = crop.filter(ImageFilter.SHARPEN)

        text = pytesseract.image_to_string(crop, lang="eng", config="--psm 6")
        text = " ".join(text.split()).strip()

        if not text:
            self.source_browser.setPlainText("No text detected.")
            self.translation_label.clear()
            self.screen_details_panel.hide()
            self.open_tab(self.TAB_SCREEN)
            return

        self.current_text = text
        self.set_clickable_main_source(text)

        translation = self.translate_text(text)
        self.current_translation = translation
        self.show_main_translation(translation)
        self.update_screen_details(text, translation)

        self.dictionary.add(text, translation, text)
        self.refresh_dictionary()

        self.result_window = ResultWindow(
            self, text, translation,
            QPoint(rect.left(), rect.bottom()) + (origin or QPoint(0, 0)), text
        )

    # ========================================================
    # TRANSLATION HELPERS
    # ========================================================

    def translate_text(self, text, src="en", dst="ru"):
        return self.translator.safe_translate(text, src, dst)[1]

    def translate_word(self, word):
        clean = re.sub(r"[^A-Za-z'-]", "", word).strip()
        if not clean:
            return ""
        ok, result = self.translator.safe_translate(clean, "en", "ru")
        return result.strip() if ok else ""

    def set_clickable_main_source(self, text):
        self.source_browser.setHtml(clickable_html(text, self.main_word_map))

    def word_clicked_in_main(self, url):
        word = self.main_word_map.get(url.toString().removeprefix("wordid:"), "")
        if word:
            self.select_word_in_main(word)

    def select_word_in_main(self, word):
        word_translation = self.translate_word(word)
        if word_translation:
            self.show_selected_word(
                self.translation_label, self.current_translation, word, word_translation
            )
            self.set_details_panel(
                self.screen_details_panel, self.screen_details,
                self.details_parts(word, "en", "ru", word_translation),
            )

    def select_word_in_result(self, result_window, word):
        word_translation = self.translate_word(word)
        if word_translation:
            result_window.highlight_translation(word_translation, word)
            result_window.set_details(self.details_parts(word, "en", "ru", word_translation))
            result_window.adjust_popup_size()
            result_window.keep_on_screen()

    def show_selected_word(self, widget, full_text, selected_word, word_translation):
        if not (full_text and selected_word and word_translation):
            return

        c = COLORS
        result_html = (
            f'{html.escape(full_text).replace(chr(10), "<br>")}'
            f'<table style="margin-top:12px;" cellspacing="0" cellpadding="0"><tr><td>'
            f'<span style="background-color:{c["accent"]}; color:{c["on_accent"]}; font-weight:600;">'
            f'&nbsp;{html.escape(selected_word.strip())}&nbsp;</span>'
            f'<span style="color:{c["muted"]};">&nbsp;&nbsp;→&nbsp;&nbsp;</span>'
            f'<span style="color:{c["text"]};">{html.escape(word_translation.strip())}</span>'
            f'</td></tr></table>'
        )
        self.set_translation_widget(widget, result_html)

    def set_translation_widget(self, widget, html_text):
        if isinstance(widget, QLabel):
            widget.setText(html_text)
        else:
            widget.setHtml(html_text)

    def show_main_translation(self, translation):
        self.translation_label.setPlainText(translation)

    # ========================================================
    # THEMES
    # ========================================================

    def apply_theme(self, name, initial=False):
        if name not in THEMES:
            name = DEFAULT_THEME
        self.theme_name = name

        COLORS.clear()
        COLORS.update(THEMES[name])

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_style())

        self.settings.setValue("theme", name)
        self.update_theme_menu()

        if not initial:
            self.refresh_after_theme_change()

    def update_theme_menu(self):
        for name, action in getattr(self, "theme_actions", {}).items():
            action.setText(("●   " if name == self.theme_name else "      ") + name)

    def refresh_after_theme_change(self):
        """Re-renders everything that has colors baked into its HTML or inline styles."""
        self.refresh_dictionary()

        if self.current_text:
            self.set_clickable_main_source(self.current_text)
            self.show_main_translation(self.current_translation)
            if self._screen_details_args and not self.screen_details_panel.isHidden():
                self.update_screen_details(*self._screen_details_args)

        if not self.text_details_panel.isHidden():
            self.update_text_details(
                self.input_edit.toPlainText(), self.output_edit.toPlainText()
            )

    # ========================================================
    # VARIANTS + EXAMPLES
    # ========================================================

    def details_parts(self, text, src, dst, main_translation=""):
        """(variants_html, examples_html) for a word / short phrase."""
        return self.lookup.details_parts(text, src, dst, main_translation, COLORS)

    def make_details_panel(self):
        panel, layout = make_panel()
        panel.hide()
        view = DetailsView(max_height=190)
        layout.addWidget(view)
        return panel, view

    def set_details_panel(self, panel, view, parts, hint=""):
        if view.set_content(parts[0], parts[1], hint):
            view.fit(max(300, self.width() - 2 * 22 - 2 * 16))
            panel.show()
        else:
            panel.hide()

    def lookup_hint_html(self):
        return ("Варианты перевода и примеры ещё не установлены. "
                "Запусти <b>build_lookup.bat</b> один раз и перезапусти программу.")

    def short_details(self, text, translation, direction):
        """(variants_html, examples_html, hint_html) for a word / short phrase."""
        text = text.strip()
        if not is_short(text) or "\n" in text:
            return "", "", ""

        src, dst = direction
        variants, examples = self.details_parts(text, src, dst, translation)

        hint = ""
        if not (variants or examples) and not self.lookup.available and not self._lookup_hint_shown:
            self._lookup_hint_shown = True
            hint = self.lookup_hint_html()
        return variants, examples, hint

    def update_text_details(self, source, translation):
        variants, examples, hint = self.short_details(
            source, translation, self.current_direction(source)
        )
        self.set_details_panel(
            self.text_details_panel, self.text_details, (variants, examples), hint
        )

    def update_screen_details(self, text, translation):
        self._screen_details_args = (text, translation)
        variants, examples, hint = self.short_details(text, translation, ("en", "ru"))
        self.set_details_panel(
            self.screen_details_panel, self.screen_details, (variants, examples), hint
        )

    # ========================================================
    # DICTIONARY ACTIONS
    # ========================================================

    def add_and_pin(self, original, translation, source=""):
        self.dictionary.add(original, translation, source)
        entry = self.dictionary.find(original, translation)
        if entry and not entry["pinned"]:
            self.dictionary.toggle_pin(entry["id"])
        self.refresh_dictionary()

    def pin_current_translation(self):
        if self.current_text and self.current_translation:
            self.add_and_pin(self.current_text, self.current_translation, self.current_text)

    def refresh_dictionary(self):
        if not hasattr(self, "dictionary_list"):
            return

        entries = self.dictionary.get_all(self.search_edit.text())
        scroll = self.dictionary_list.verticalScrollBar().value()
        self.dictionary_list.clear()

        if not entries:
            item = QListWidgetItem()
            text = "Nothing found." if self.search_edit.text().strip() else (
                "Your dictionary is empty.\nTranslations from the screen and pinned texts appear here."
            )
            label = make_label(text, "empty")
            label.setAlignment(Qt.AlignCenter)
            self.dictionary_list.addItem(item)
            self.dictionary_list.setItemWidget(item, label)

        for entry in entries:
            item = QListWidgetItem()
            variants, examples_loader = self.card_lookup(entry)
            card = DictionaryCard(
                entry, self.pin_dictionary_entry, self.delete_dictionary_entry,
                variants, examples_loader, self.dictionary_list.update_hints,
            )
            self.dictionary_list.addItem(item)
            self.dictionary_list.setItemWidget(item, card)

        self.dictionary_list.update_hints()
        self.dictionary_list.verticalScrollBar().setValue(scroll)
        self.update_dictionary_stats()

    def card_lookup(self, entry):
        """(other translations, lazy examples loader) for a dictionary entry."""
        original = entry["original"].strip()
        if not self.lookup.available or not is_short(original):
            return None, None

        src, dst = detect_direction(original)
        variants = self.lookup.other_variants(original, src, dst, entry["translation"])[:5]

        loader = None
        if self.lookup.has_examples:
            loader = lambda: self.lookup.examples_html(original, src, COLORS)
        return variants, loader

    def pin_dictionary_entry(self, entry_id):
        self.dictionary.toggle_pin(entry_id)
        self.refresh_dictionary()

    def delete_dictionary_entry(self, entry_id):
        self.dictionary.delete(entry_id)
        self.refresh_dictionary()

    def update_dictionary_stats(self):
        entries = self.dictionary.get_all()
        words = sum(1 for e in entries if len(e["original"].split()) == 1)
        pinned = sum(1 for e in entries if e["pinned"])
        self.dictionary_stats.setText(
            f"{len(entries)} entries  ·  {words} words  ·  "
            f"{len(entries) - words} phrases  ·  {pinned} pinned"
        )

    def clear_dictionary(self):
        if not self.dictionary.get_all():
            return

        result = QMessageBox.question(
            self, "Clear Dictionary",
            "Delete all translations?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return

        self.dictionary.clear_all()
        self.current_text = ""
        self.current_translation = ""
        self.refresh_dictionary()

    # ========================================================
    # TRAY
    # ========================================================

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(app_icon(self.style()))
        self.tray.setToolTip("Screen Translator")

        menu = QMenu()
        for text, slot in (
            ("📷  Translate screen", self.start_selection),
            ("✏️  Text translator", lambda: self.open_tab(self.TAB_TEXT)),
            ("📚  Dictionary", lambda: self.open_tab(self.TAB_DICTIONARY)),
        ):
            action = QAction(text, self)
            action.triggered.connect(slot)
            menu.addAction(action)

        menu.addSeparator()
        exit_action = QAction("✕  Exit", self)
        exit_action.triggered.connect(self.exit_application)
        menu.addAction(exit_action)

        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_tab(self.TAB_TEXT)

    def open_tab(self, index):
        self.show()
        self.raise_()
        self.activateWindow()
        self.tabs.setCurrentIndex(index)
        if index == self.TAB_TEXT:
            self.input_edit.setFocus()

    # kept for compatibility with the old API
    def open_translator(self):
        self.open_tab(self.TAB_TEXT)

    def open_dictionary(self):
        self.open_tab(self.TAB_DICTIONARY)

    # ========================================================
    # HOTKEY
    # ========================================================

    def install_hotkey(self):
        self.hotkey_filter = GlobalHotkeyFilter(self.start_selection)
        QApplication.instance().installNativeEventFilter(self.hotkey_filter)
        self.register_current_hotkey()

    def save_hotkey(self):
        self.settings.setValue("hotkey_text", self.hotkey_text)
        self.settings.setValue("hotkey_modifiers", self.hotkey_modifiers)
        self.settings.setValue("hotkey_vk", self.hotkey_vk)
        self.settings.sync()

    def register_current_hotkey(self):
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, HOTKEY_ID)

        if user32.RegisterHotKey(None, HOTKEY_ID, self.hotkey_modifiers | MOD_NOREPEAT, self.hotkey_vk):
            return

        self.hotkey_text = "Alt + Q"
        self.hotkey_modifiers = MOD_ALT
        self.hotkey_vk = VK_Q
        self.save_hotkey()
        user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT | MOD_NOREPEAT, VK_Q)
        self.update_hotkey_labels()

    def change_hotkey(self):
        dialog = HotkeyDialog(self, self.hotkey_text)

        if dialog.exec() != QDialog.Accepted or not dialog.result_hotkey:
            return

        new_text, new_vk = dialog.result_hotkey
        new_modifiers = 0
        if "Ctrl" in new_text:
            new_modifiers |= MOD_CONTROL
        if "Alt" in new_text:
            new_modifiers |= MOD_ALT
        if "Shift" in new_text:
            new_modifiers |= MOD_SHIFT
        if "Win" in new_text:
            new_modifiers |= MOD_WIN

        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, HOTKEY_ID)

        if not user32.RegisterHotKey(None, HOTKEY_ID, new_modifiers | MOD_NOREPEAT, new_vk):
            QMessageBox.warning(
                self, "Hotkey unavailable",
                "This key combination is already used by Windows or another program.",
            )
            user32.RegisterHotKey(None, HOTKEY_ID, self.hotkey_modifiers | MOD_NOREPEAT, self.hotkey_vk)
            return

        self.hotkey_text = new_text
        self.hotkey_modifiers = new_modifiers
        self.hotkey_vk = new_vk
        self.save_hotkey()
        self.update_hotkey_labels()

    def update_hotkey_labels(self):
        if hasattr(self, "subtitle"):
            self.subtitle.setText(
                f"Offline EN ⇄ RU translator  ·  screen capture: {self.hotkey_text}"
            )
        if hasattr(self, "hotkey_button"):
            self.hotkey_button.setText(f"⌨  {self.hotkey_text}")

    # kept for compatibility
    update_hotkey_subtitle = update_hotkey_labels

    # ========================================================
    # CLOSE / EXIT
    # ========================================================

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def exit_application(self):
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        self.pool.clear()
        self.pool.waitForDone(3000)
        self.dictionary.close()
        self.lookup.close()
        self.tray.hide()
        QApplication.quit()


# ============================================================
# MAIN
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(build_style())
    app.setWindowIcon(app_icon())

    window = MainWindow()
    window.open_tab(MainWindow.TAB_TEXT)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
