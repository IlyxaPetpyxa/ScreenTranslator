"""Builds dist/ScreenTranslator.zip - the file you give to other people.

The zip contains the Python code, the language models, lookup.db, Tesseract (optional),
the Python installer, all libraries (wheels) and install.bat - installation works with no internet.
The first run needs internet on THIS computer (use a VPN if needed); downloads are cached in build/.

    python tools/make_release.py
    python tools/make_release.py --no-tesseract    # smaller; screen capture then needs Tesseract installed
    python tools/make_release.py --no-lookup

Never included: your dictionary.db, logs, .venv, the downloaded source files.
"""
import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import paths  # noqa: E402

PY_VERSION = "3.12.8"           # keep in sync with install.bat
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-amd64.exe"
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
CACHE = os.path.join(ROOT, "build", "release_cache")

FOLDER = "ScreenTranslator"          # top-level folder inside the zip
OUT = os.path.join(ROOT, "dist", "ScreenTranslator.zip")

CODE_FILES = [
    "install.bat", "Translator.bat", "requirements.txt", "README.md", "LICENSE",
    "src/main.py", "src/lookup.py", "src/paths.py",
    "assets/icon.ico", "assets/icon.png",
    "tools/launcher.cs", "tools/install_models.py",
]

README_TXT = """SCREEN TRANSLATOR
=================

1. Unzip this archive to a folder with a short Latin path, for example C:\\ScreenTranslator
   (not to a folder with Russian letters in its name).
2. Run install.bat once (a few minutes, NO internet needed).
3. Start the program with Translator.exe.

Python, libraries, language models and the dictionary are already inside, nothing is downloaded.
Your saved words are stored in the "data" folder. To remove the program, delete the folder.

---

1. Распакуйте архив в папку с коротким латинским путём, например C:\\ScreenTranslator
   (не в папку с русскими буквами).
2. Один раз запустите install.bat (несколько минут, интернет НЕ нужен).
3. Дальше запускайте программу через Translator.exe.

Языковые модели и словарь уже лежат в архиве. Сохранённые слова хранятся в папке data.
Чтобы удалить программу, просто удалите папку.
"""


def has_models(path):
    return any(os.path.isdir(os.path.join(path, name)) for name in os.listdir(path))


def fetch(url, dest):
    """Download once; later builds reuse the cached file."""
    if os.path.exists(dest) and os.path.getsize(dest) > 1024 * 1024:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"Downloading {url} ...")
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)
    return dest


def download_wheels(dest):
    """Wheels for Windows / Python 3.12, whatever Python runs this script."""
    if os.path.isdir(dest) and os.listdir(dest):
        return dest
    os.makedirs(dest, exist_ok=True)
    print("Downloading libraries for Windows (hundreds of MB, please wait)...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "download", "-r", os.path.join(ROOT, "requirements.txt"),
        "--dest", dest, "--only-binary=:all:",
        "--platform", "win_amd64", "--python-version", "3.12", "--implementation", "cp",
    ])
    return dest


def add_tree(z, src, arcname):
    count, size = 0, 0
    for base, _, files in os.walk(src):
        for f in files:
            full = os.path.join(base, f)
            z.write(full, os.path.join(FOLDER, arcname, os.path.relpath(full, src)))
            count += 1
            size += os.path.getsize(full)
    return count, size / 1024 / 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-tesseract", action="store_true")
    parser.add_argument("--no-lookup", action="store_true")
    parser.add_argument("--no-offline", action="store_true",
                        help="do not bundle the Python installer and libraries (install.bat will download them)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)

    problems = []

    # Fetch everything first so a network failure does not leave a half-written zip.
    installer = vcredist = wheels = None
    if not args.no_offline:
        try:
            installer = fetch(PY_URL, os.path.join(CACHE, os.path.basename(PY_URL)))
            wheels = download_wheels(os.path.join(CACHE, "wheels"))
        except Exception as e:  # noqa: BLE001
            sys.exit(f"Could not download the offline components: {e}\n"
                     "Turn on your VPN and run again, or use --no-offline.")
        try:
            vcredist = fetch(VCREDIST_URL, os.path.join(CACHE, "vc_redist.x64.exe"))
        except Exception as e:  # noqa: BLE001
            problems.append(f"vc_redist.x64.exe not downloaded ({e}); a clean Windows may need it")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in CODE_FILES:
            full = os.path.join(ROOT, rel)
            if os.path.exists(full):
                z.write(full, os.path.join(FOLDER, rel))
            else:
                problems.append(f"missing file: {rel}")
        z.writestr(os.path.join(FOLDER, "README.txt"), README_TXT)

        # data/ switches the app to portable mode (saved words stay inside the folder)
        z.writestr(os.path.join(FOLDER, "data", ".keep"), "")

        lookup = os.path.join(ROOT, "data", "lookup.db")
        lic = os.path.join(ROOT, "data", "LOOKUP_DATA_LICENSES.txt")
        if not args.no_lookup:
            if os.path.exists(lookup):
                z.write(lookup, os.path.join(FOLDER, "data", "lookup.db"))
                print(f"+ lookup.db ({os.path.getsize(lookup) / 1024 / 1024:.0f} MB)")
                if os.path.exists(lic):
                    z.write(lic, os.path.join(FOLDER, "LOOKUP_DATA_LICENSES.txt"))
            else:
                problems.append("data/lookup.db not found: no variants/examples (run tools/build_lookup.bat)")

        model_src = next((d for d in paths.model_dirs() if has_models(d)), None)
        if model_src:
            n, mb = add_tree(z, model_src, "models")
            print(f"+ models from {model_src}: {n} files, {mb:.0f} MB")
        else:
            problems.append("no Argos models found: run tools/install_models.bat first")

        if installer:
            z.write(installer, os.path.join(FOLDER, "installer", os.path.basename(installer)))
            print(f"+ Python installer ({os.path.getsize(installer) / 1024 / 1024:.0f} MB)")
        if vcredist:
            z.write(vcredist, os.path.join(FOLDER, "installer", "vc_redist.x64.exe"))
        if wheels:
            n, mb = add_tree(z, wheels, "wheels")
            print(f"+ libraries: {n} files, {mb:.0f} MB")
            if mb > 1200:
                problems.append(f"libraries are {mb:.0f} MB - something huge (torch?) got pulled in; check wheels")

        if not args.no_tesseract:
            tess = paths.find_tesseract()
            if os.path.exists(tess):
                n, mb = add_tree(z, os.path.dirname(tess), "tesseract")
                print(f"+ Tesseract from {os.path.dirname(tess)}: {n} files, {mb:.0f} MB")
            else:
                problems.append("Tesseract not found: screen capture will need it installed separately")

    print(f"\nZip: {OUT} ({os.path.getsize(OUT) / 1024 / 1024:.0f} MB)")
    for p in problems:
        print("!", p)
    if not any(p.startswith(("no Argos", "missing file")) for p in problems):
        print("OK: ready to share.")


if __name__ == "__main__":
    main()
