"""Diagnostics for Screen Translator's variants/examples data. Double-click to run."""
import os
import sys
import sqlite3
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import paths  # noqa: E402
WORK = os.path.join(ROOT, "build")          # scratch: downloads, source dictionaries (git-ignored)
OUT_DIR = os.path.join(ROOT, "data")        # lookup.db goes here (the app uses <root>/data when it exists)
DATA = os.path.join(WORK, "lookup_data")
DB = os.path.join(OUT_DIR, "lookup.db")

NEEDED = ["eng_sentences", "rus_sentences", "eng-rus_links"]


def mb(n):
    return f"{n / 1024 / 1024:.1f} MB"


def stamp(path):
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")


def main():
    print("Folder:", HERE, "\n")
    verdict = []

    # --- source files
    print("== lookup_data ==")
    files = []
    if os.path.isdir(DATA):
        for f in sorted(os.listdir(DATA)):
            full = os.path.join(DATA, f)
            if os.path.isfile(full):
                files.append(f)
                print(f"  {f:45} {mb(os.path.getsize(full)):>9}  {stamp(full)}")
    else:
        print("  folder lookup_data does not exist (it is deleted if you answered 'y' after a build)")
    for stem in NEEDED:
        ok = any(f.startswith(stem) and f[len(stem):].startswith((".", " ", "(")) for f in files)
        print(f"  Tatoeba file {stem}: {'found' if ok else 'NOT FOUND'}")
    all_tatoeba = all(
        any(f.startswith(s) and f[len(s):].startswith((".", " ", "(")) for f in files) for s in NEEDED)

    # --- database
    print("\n== lookup.db ==")
    if not os.path.exists(DB):
        print("  lookup.db does not exist")
        print("\nVERDICT: run build_lookup.bat")
        return

    print(f"  size {mb(os.path.getsize(DB))}, built {stamp(DB)}")
    con = sqlite3.connect(DB)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        print("  tables:", ", ".join(sorted(tables)))
        for k, v in con.execute("SELECT key, value FROM meta"):
            print(f"  meta {k} = {v}")

        n_var = con.execute("SELECT COUNT(*) FROM variants").fetchone()[0] if "variants" in tables else 0
        n_pairs = con.execute("SELECT COUNT(*) FROM pairs").fetchone()[0] if "pairs" in tables else 0
        print(f"  variants rows: {n_var:,}   example pairs: {n_pairs:,}")

        if n_pairs:
            for q in ("hello", "love"):
                try:
                    rows = con.execute(
                        "SELECT p.en, p.ru FROM en_fts JOIN pairs p ON p.id = en_fts.rowid "
                        "WHERE en_fts MATCH ? LIMIT 2", (f'"{q}"',)).fetchall()
                    print(f"  search '{q}':", rows if rows else "nothing found")
                except sqlite3.Error as e:
                    print(f"  search '{q}' FAILED: {e}")
                    verdict.append("The search index is broken: " + str(e))
    finally:
        con.close()

    # --- verdict
    if not n_pairs:
        if all_tatoeba:
            newer = any(os.path.getmtime(os.path.join(DATA, f)) > os.path.getmtime(DB) for f in files)
            if newer:
                verdict.append("The Tatoeba files are newer than lookup.db: close Screen Translator "
                               "(tray icon -> Exit) and run build_lookup.bat again.")
            else:
                verdict.append("The files are present but the database has no examples: run "
                               "build_lookup.bat and send me everything it prints.")
        else:
            verdict.append("Tatoeba files are missing or have unexpected names: put all three into "
                           "lookup_data, then run build_lookup.bat.")
    else:
        verdict.append("The database contains examples. Restart Screen Translator completely "
                       "(tray icon -> Exit, then start it again) and try a short word like 'hello'.")

    print("\nVERDICT:")
    for v in verdict:
        print(" -", v)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("ERROR:", type(e).__name__, e)
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass
