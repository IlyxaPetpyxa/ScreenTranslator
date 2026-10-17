"""Where Screen Translator keeps its files. No Qt, safe to import from the tools.

Layout (portable by design - nothing is written outside these places):

    <app>/                   folder with Translator.exe (or the project root)
        data/                saved words, lookup.db, logs   <- used if this folder exists
        models/              Argos language models          <- optional, can be bundled
        tesseract/           portable Tesseract              <- optional, can be bundled

If <app>/data does not exist, %APPDATA%\\ScreenTranslator is used instead.
"""
import os
import shutil
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    APP_DIR = os.path.dirname(sys.executable)
else:
    # this file lives in <root>/src/ or <root>/tools/../src
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ScreenTranslator")


def data_dir(create=True):
    portable = os.path.join(APP_DIR, "data")
    path = portable if os.path.isdir(portable) else _user_data_dir()
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
    return path


DATA_DIR = data_dir()
DB_PATH = os.path.join(DATA_DIR, "dictionary.db")
LOOKUP_PATH = os.path.join(DATA_DIR, "lookup.db")
ERROR_LOG = os.path.join(DATA_DIR, "error.log")
CRASH_LOG = os.path.join(DATA_DIR, "crash.log")


# ---------------- Argos models ----------------

def _is_ascii(path):
    try:
        path.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def model_dirs():
    """Every folder that may hold Argos models (existing ones only)."""
    candidates = [
        os.environ.get("SCREEN_TRANSLATOR_MODELS"),
        os.path.join(APP_DIR, "models"),
        r"C:\ArgosModels",
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "ScreenTranslator", "models"),
    ]
    return [p for p in candidates if p and os.path.isdir(p)]


def model_install_dir():
    """Where new models should be installed."""
    env = os.environ.get("SCREEN_TRANSLATOR_MODELS")
    if env:
        return env
    existing = model_dirs()
    if existing:
        return existing[0]
    local = os.path.join(APP_DIR, "models")
    if _is_ascii(local):
        return local
    # The translation engine may fail to open models in folders with non-ASCII names
    # (e.g. a Cyrillic Windows user name), so fall back to an ASCII-only location.
    return os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "ScreenTranslator", "models")


def configure_argos():
    """Point argostranslate at our model folders. Call before importing argostranslate.translate."""
    from pathlib import Path

    primary = model_install_dir()
    os.environ["ARGOS_PACKAGES_DIR"] = primary

    import argostranslate.settings as settings

    dirs = [primary] + [d for d in model_dirs() if os.path.normcase(d) != os.path.normcase(primary)]
    settings.package_data_dir = Path(primary)
    settings.package_dirs = [Path(d) for d in dirs]
    return primary


# ---------------- Tesseract ----------------

def find_tesseract():
    candidates = [
        os.environ.get("TESSERACT_PATH"),
        os.path.join(APP_DIR, "tesseract", "tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        shutil.which("tesseract"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return r"C:\Program Files\Tesseract-OCR\tesseract.exe"
