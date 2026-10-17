"""Builds lookup.db for Screen Translator: alternative translations + usage examples.

Sources (downloaded once, ~90 MB):
  * WikDict en-ru / ru-en dictionaries (derived from Wiktionary, CC BY-SA 4.0)
  * Tatoeba English-Russian sentence pairs (CC BY 2.0 FR)

Only the Python standard library is needed.
If a download fails, the script prints direct links: save the files into the
"lookup_data" folder (build/lookup_data) and run it again.
"""
import argparse
import bz2
import datetime
import gzip
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import paths  # noqa: E402
WORK = os.path.join(ROOT, "build")          # scratch: downloads, source dictionaries (git-ignored)
OUT_DIR = os.path.join(ROOT, "data")        # lookup.db goes here (the app uses <root>/data when it exists)

WIKDICT = "https://download.wikdict.com/dictionaries/sqlite/2/"
TATOEBA = "https://downloads.tatoeba.org/exports/per_language/"

SOURCES = {
    "en-ru.sqlite3": WIKDICT + "en-ru.sqlite3",
    "ru-en.sqlite3": WIKDICT + "ru-en.sqlite3",
    "eng_sentences.tsv.bz2": TATOEBA + "eng/eng_sentences.tsv.bz2",
    "rus_sentences.tsv.bz2": TATOEBA + "rus/rus_sentences.tsv.bz2",
    "eng-rus_links.tsv.bz2": TATOEBA + "eng/eng-rus_links.tsv.bz2",
}

MAX_PAIRS = 450_000
EN_LEN = (12, 90)
RU_MAX = 130
IDEAL_LEN = 45
MAX_VARIANTS = 10
MAX_VARIANT_LEN = 40

LICENSES = """Data used by Screen Translator (lookup.db)

Alternative translations:
  WikDict (https://www.wikdict.com), derived from Wiktionary / DBnary.
  License: CC BY-SA 4.0  https://creativecommons.org/licenses/by-sa/4.0/

Example sentences:
  Tatoeba (https://tatoeba.org) - contributors of the Tatoeba project.
  License: CC BY 2.0 FR  https://creativecommons.org/licenses/by/2.0/fr/
"""


# ============================================================
# DOWNLOAD
# ============================================================

def fmt(n):
    return f"{n / 1024 / 1024:.1f} MB"


def find_source(data_dir, name):
    """Path of a source file: exact name first, else a browser-renamed copy
    such as 'eng_sentences (1).tsv.bz2'. Returns None if nothing suitable exists."""
    exact = os.path.join(data_dir, name)
    if os.path.exists(exact) and os.path.getsize(exact) > 0:
        return exact

    stem = name.split(".")[0]
    found = []
    for f in os.listdir(data_dir):
        rest = f[len(stem):]
        full = os.path.join(data_dir, f)
        if (f.startswith(stem) and rest.startswith((".", " ", "("))
                and not f.endswith((".part", ".unpacked", ".crdownload"))
                and os.path.isfile(full) and os.path.getsize(full) > 0):
            found.append(full)
    return max(found, key=os.path.getmtime) if found else None


def open_text(path):
    """Opens a .bz2 or already unpacked text file."""
    with open(path, "rb") as f:
        head = f.read(3)
    if head == b"BZh":
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def _download_once(url, dest):
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            last = 0.0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 0.5:
                    last = now
                    if total:
                        print(f"\r    {fmt(done)} / {fmt(total)}  ({done * 100 // total}%)   ",
                              end="", flush=True)
                    else:
                        print(f"\r    {fmt(done)}   ", end="", flush=True)
        print(f"\r    {fmt(done)} downloaded.                    ")
        os.replace(part, dest)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def _unpack_if_needed(path):
    """Some mirrors serve archives; make sure sqlite files are plain sqlite."""
    if not path.endswith(".sqlite3"):
        return
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"SQLite format 3"):
        return
    tmp = path + ".unpacked"
    if head.startswith(b"PK"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if not n.endswith("/"))
            with z.open(name) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
    elif head.startswith(b"\x1f\x8b"):
        with gzip.open(path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
    else:
        raise RuntimeError(f"{os.path.basename(path)} is not a SQLite file")
    os.replace(tmp, path)


def import_from_downloads(data_dir):
    """Copies source files that were saved next to this script or into Downloads."""
    folders = [HERE, ROOT, WORK, os.path.join(os.path.expanduser("~"), "Downloads")]
    for name in SOURCES:
        if find_source(data_dir, name):
            continue
        for folder in folders:
            if not os.path.isdir(folder) or os.path.abspath(folder) == os.path.abspath(data_dir):
                continue
            found = find_source(folder, name)
            if found:
                dest = os.path.join(data_dir, name)
                print(f"[import] {name}: copying from {found}")
                shutil.copyfile(found, dest)
                break


def fetch_all(data_dir):
    """Downloads every missing source. Returns the list of names that failed."""
    failed = []
    for name, url in SOURCES.items():
        dest = os.path.join(data_dir, name)
        existing = find_source(data_dir, name)
        if existing:
            print(f"[have] {name}" + ("" if existing == dest else f"  (found as {os.path.basename(existing)})"))
            continue

        print(f"[download] {name}")
        print(f"    {url}")
        ok = False
        for attempt in (1, 2):
            try:
                _download_once(url, dest)
                _unpack_if_needed(dest)
                ok = True
                break
            except Exception as e:
                print(f"\n    attempt {attempt} failed: {type(e).__name__}: {e}")
        if not ok:
            failed.append(name)
    return failed


# ============================================================
# VARIANTS (WikDict)
# ============================================================

def split_translations(value):
    if not value:
        return []
    if "|" in value:
        parts = re.split(r"\s*\|\s*", value)
    else:
        parts = [value]
    return [p.strip() for p in parts if p.strip()]


def read_wikdict(path):
    """Returns {word: [translations]} or raises RuntimeError with the schema."""
    db = sqlite3.connect(path)
    try:
        objects = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")]
        schema = {
            t: [c[1] for c in db.execute(f'PRAGMA table_info("{t}")')]
            for t in objects
        }

        for table in ("simple_translation", "translation"):
            columns = schema.get(table, [])
            if "written_rep" in columns and "trans_list" in columns:
                order = " ORDER BY score DESC" if "score" in columns else ""
                rows = db.execute(
                    f'SELECT written_rep, trans_list FROM "{table}"{order}')
                result = {}
                for word, trans_list in rows:
                    word = (word or "").strip().lower()
                    if not word or len(word) > 60:
                        continue
                    bucket = result.setdefault(word, [])
                    seen = {t.casefold() for t in bucket}
                    for t in split_translations(trans_list):
                        if len(t) > MAX_VARIANT_LEN or t.casefold() in seen:
                            continue
                        seen.add(t.casefold())
                        bucket.append(t)
                return {w: v[:MAX_VARIANTS] for w, v in result.items() if v}

        lines = [f"  {t}: {', '.join(cols)}" for t, cols in schema.items()]
        raise RuntimeError(
            "Unknown WikDict schema (expected a table with written_rep + trans_list).\n"
            "Tables and columns found:\n" + "\n".join(lines))
    finally:
        db.close()


# ============================================================
# EXAMPLES (Tatoeba)
# ============================================================

def load_sentences(path, wanted):
    texts = {}
    with open_text(path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t", 2)
            if len(parts) != 3 or not parts[0].isdigit():
                continue
            sid = int(parts[0])
            if sid in wanted:
                text = " ".join(parts[2].split())
                if text:
                    texts[sid] = text
    return texts


def build_pairs(links_path, eng_path, rus_path):
    links = []
    wanted = set()
    with open_text(links_path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                a, b = int(parts[0]), int(parts[1])
                links.append((a, b))
                wanted.add(a)
                wanted.add(b)
    print(f"    links: {len(links):,}")

    eng = load_sentences(eng_path, wanted)
    rus = load_sentences(rus_path, wanted)
    print(f"    english sentences: {len(eng):,}, russian sentences: {len(rus):,}")

    seen_en = set()
    pairs = []
    for a, b in links:
        if a in eng and b in rus:
            en, ru = eng[a], rus[b]
        elif b in eng and a in rus:
            en, ru = eng[b], rus[a]
        else:
            continue

        if not (EN_LEN[0] <= len(en) <= EN_LEN[1]) or len(ru) > RU_MAX:
            continue
        if "http" in en.lower() or "http" in ru.lower():
            continue

        key = en.casefold()
        if key in seen_en:
            continue
        seen_en.add(key)
        pairs.append((en, ru))

    print(f"    usable pairs: {len(pairs):,}")
    if len(pairs) > MAX_PAIRS:
        pairs.sort(key=lambda p: abs(len(p[0]) - IDEAL_LEN))
        pairs = pairs[:MAX_PAIRS]
        print(f"    kept {len(pairs):,} (closest to a comfortable length)")
    return pairs


# ============================================================
# DATABASE
# ============================================================

def build_database(data_dir, out_path):
    def have(name):
        return find_source(data_dir, name)

    tmp = out_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)

    conn = sqlite3.connect(tmp)
    conn.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE variants (
            pair TEXT NOT NULL,
            word TEXT NOT NULL,
            translations TEXT NOT NULL,
            PRIMARY KEY (pair, word)
        ) WITHOUT ROWID;
        CREATE TABLE pairs (
            id INTEGER PRIMARY KEY,
            en TEXT NOT NULL,
            ru TEXT NOT NULL,
            len INTEGER NOT NULL
        );
    """)

    stats = {}

    # ---- variants ----
    for pair in ("en-ru", "ru-en"):
        name = f"{pair}.sqlite3"
        path = have(name)
        if not path:
            print(f"[skip] variants {pair}: {name} is missing")
            continue
        print(f"[build] variants {pair}")
        try:
            data = read_wikdict(path)
        except Exception as e:
            print("\n!! Could not read", name)
            print(e)
            print("!! Send this text to the developer. Examples will still be built.\n")
            continue
        conn.executemany(
            "INSERT OR REPLACE INTO variants VALUES (?, ?, ?)",
            [(pair, w, "\t".join(v)) for w, v in data.items()],
        )
        stats[f"variants_{pair}"] = len(data)
        print(f"    words: {len(data):,}")

    # ---- examples ----
    need = ("eng-rus_links.tsv.bz2", "eng_sentences.tsv.bz2", "rus_sentences.tsv.bz2")
    paths = [have(n) for n in need]
    if all(paths):
        print("[build] example sentences")
        for n, pth in zip(need, paths):
            print(f"    {n}: {os.path.basename(pth)} ({fmt(os.path.getsize(pth))})")
        pairs = build_pairs(*paths)
        if not pairs:
            print("\n!! No example sentences could be extracted - the files look wrong.")
            print("!! Send the lines above to the developer.\n")
        conn.executemany(
            "INSERT INTO pairs (en, ru, len) VALUES (?, ?, ?)",
            [(en, ru, len(en)) for en, ru in pairs],
        )
        print("    building search index...")
        conn.executescript("""
            CREATE VIRTUAL TABLE en_fts USING fts5(
                en, content='pairs', content_rowid='id',
                tokenize='porter unicode61 remove_diacritics 2');
            CREATE VIRTUAL TABLE ru_fts USING fts5(
                ru, content='pairs', content_rowid='id',
                tokenize='unicode61 remove_diacritics 0');
            INSERT INTO en_fts(en_fts) VALUES('rebuild');
            INSERT INTO ru_fts(ru_fts) VALUES('rebuild');
        """)
        stats["pairs"] = len(pairs)
    else:
        print("[skip] examples: these Tatoeba files were not found in", data_dir)
        for n, pth in zip(need, paths):
            if not pth:
                print("    missing:", n)

    if not stats:
        conn.close()
        os.remove(tmp)
        raise RuntimeError("Nothing to build: no source files were available.")

    stats["built_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in stats.items()])
    conn.commit()
    conn.close()

    try:
        os.replace(tmp, out_path)
    except PermissionError:
        raise RuntimeError(
            "lookup.db is in use. Close Screen Translator completely "
            "(tray icon -> Exit) and run this script again.")

    with open(os.path.join(os.path.dirname(out_path), "LOOKUP_DATA_LICENSES.txt"),
              "w", encoding="utf-8") as f:
        f.write(LICENSES)

    return stats


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=os.path.join(WORK, "lookup_data"))
    parser.add_argument("--out", default=os.path.join(OUT_DIR, "lookup.db"))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--keep", action="store_true",
                        help="never ask about deleting downloaded files")
    args = parser.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    import_from_downloads(args.data_dir)

    failed = [] if args.no_download else fetch_all(args.data_dir)

    print()
    stats = build_database(args.data_dir, args.out)

    print("\nDone:", ", ".join(f"{k}={v}" for k, v in stats.items() if k != "built_at"))
    print(f"lookup.db: {fmt(os.path.getsize(args.out))}")

    if failed:
        print("\n!! These files could not be downloaded:")
        for name in failed:
            print(f"   {name}\n     {SOURCES[name]}")
        print(f"\n   Save them (with the same names) into:\n   {args.data_dir}\n"
              "   and run this script again - it will add the missing parts.")
        return

    if args.keep:
        return

    size = sum(os.path.getsize(os.path.join(args.data_dir, n))
               for n in os.listdir(args.data_dir))
    try:
        answer = input(f"\nDelete downloaded source files ({fmt(size)})? "
                       "If you delete them, a rebuild needs to download again. [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() == "y":
        shutil.rmtree(args.data_dir, ignore_errors=True)
        print("Deleted.")

    print("\nRestart Screen Translator.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\nERROR:", type(e).__name__, e)
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass
