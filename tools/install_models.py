"""Downloads and installs Argos models (en<->ru) into the models folder (see paths.py).

Shows download progress. If the server is unreachable, prints the direct link:
download the .argosmodel file in a browser, put it next to this script
(or into C:\\ArgosModels) and run the script again - it installs local files first.
"""
import os
import sys
import time
import glob
import urllib.request
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import paths  # noqa: E402

ARGOS_DIR = paths.model_install_dir()
Path(ARGOS_DIR).mkdir(parents=True, exist_ok=True)

import argostranslate.settings  # noqa: E402
paths.configure_argos()

import argostranslate.package
import argostranslate.translate

WANTED = [("en", "ru"), ("ru", "en")]
# NOTE: never create folders inside ARGOS_DIR - Argos treats every
# sub-folder there as an installed model. Downloads live next to the script.
DL_DIR = Path(ROOT) / "build" / "downloads"
DL_DIR.mkdir(parents=True, exist_ok=True)

# Cleanup of the mistaken folder created by the previous version of this script.
_bad = Path(ARGOS_DIR) / "downloads"
if _bad.is_dir() and not (_bad / "metadata.json").exists():
    try:
        _bad.rmdir()  # only works if the folder is empty
        print("Removed stray folder:", _bad)
    except OSError:
        print(f"!! Please move/delete the folder {_bad} manually "
              "(it must not exist inside C:\\ArgosModels).")


def installed_pairs():
    pairs = set()
    for lang in argostranslate.translate.get_installed_languages():
        for tr in lang.translations_from:
            pairs.add((lang.code, tr.to_lang.code))
    return pairs


def fmt(n):
    return f"{n / 1024 / 1024:.1f} MB"


def download(url, dest):
    try:
        return _download(url, dest)
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise


def _download(url, dest):
    print(f"  URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        last = time.time()
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if time.time() - last > 0.5:
                last = time.time()
                if total:
                    print(f"\r  {fmt(done)} / {fmt(total)}  ({done * 100 // total}%)   ",
                          end="", flush=True)
                else:
                    print(f"\r  {fmt(done)}   ", end="", flush=True)
    print(f"\r  {fmt(done)} downloaded.                    ")
    return dest


def install_local_files(missing):
    """Installs any ready .argosmodel files that match missing pairs."""
    for src, dst in list(missing):
        patterns = [f"*{src}_{dst}*.argosmodel", f"*{src}-{dst}*.argosmodel"]
        for folder in (HERE, ARGOS_DIR, str(DL_DIR)):
            for pattern in patterns:
                for path in glob.glob(os.path.join(folder, pattern)):
                    print(f"Installing local file: {path}")
                    argostranslate.package.install_from_path(Path(path))
                    missing.remove((src, dst))
                    break
                if (src, dst) not in missing:
                    break
            if (src, dst) not in missing:
                break


def main():
    have = installed_pairs()
    print("Installed now:", ", ".join(f"{a}->{b}" for a, b in sorted(have)) or "nothing")

    missing = [p for p in WANTED if p not in have]
    if not missing:
        print("\nAll models are already installed. Nothing to do.")
        return

    print("Missing:", ", ".join(f"{a}->{b}" for a, b in missing))

    install_local_files(missing)
    if not missing:
        print("\nDone. Restart Screen Translator.")
        return

    print("\nUpdating package index...")
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()

    for src, dst in missing:
        package = next(
            (p for p in available if p.from_code == src and p.to_code == dst), None
        )
        if package is None:
            print(f"!! Package {src}->{dst} was not found in the index.")
            continue

        links = list(getattr(package, "links", None) or [])
        print(f"\nDownloading {src}->{dst} ...")
        dest = DL_DIR / f"translate-{src}_{dst}.argosmodel"
        ok = False

        for url in links:
            try:
                download(url, dest)
                ok = True
                break
            except Exception as e:
                print(f"\n  failed: {type(e).__name__}: {e}")

        if not ok and not links:
            try:
                dest = Path(package.download())
                ok = True
            except Exception as e:
                print(f"  failed: {type(e).__name__}: {e}")

        if not ok:
            print("\n!! Could not download automatically.")
            for url in links:
                print("   Open in a browser and save the file:", url)
            print(f"   Then put the .argosmodel file into {HERE}\n"
                  "   and run this script again.")
            continue

        print("  Installing...")
        argostranslate.package.install_from_path(dest)
        print(f"OK: {src}->{dst}")

    print("\nInstalled now:",
          ", ".join(f"{a}->{b}" for a, b in sorted(installed_pairs())))
    print("\nDone. Restart Screen Translator.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\nERROR:", type(e).__name__, e)
    input("\nPress Enter to close...")
