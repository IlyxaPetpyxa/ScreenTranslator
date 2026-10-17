"""Alternative translations and usage examples (reads lookup.db built by build_lookup.py).

No Qt and no Windows-specific code here, so it can be tested anywhere.
"""
import html
import os
import re
import sqlite3

DEFAULT_COLORS = dict(
    text="#e9ebef",
    muted="#8b92a1",
    faint="#5d6371",
    accent="#7c9dff",
)

IDEAL_LEN = 45
MAX_SHOWN_VARIANTS = 8

# Words that match half of the database: examples for them are useless.
STOP_WORDS = {
    "the", "a", "an", "of", "to", "in", "on", "at", "is", "are", "was", "were",
    "be", "and", "or", "it", "i", "you", "he", "she", "we", "they", "this", "that",
    "и", "в", "на", "я", "ты", "он", "она", "мы", "вы", "они", "не", "что", "это", "с", "к", "по",
}

TOKEN_RE = {
    "en": re.compile(r"[A-Za-z0-9]+"),
    "ru": re.compile(r"[А-Яа-яЁё0-9]+"),
}

_PUNCT = " \t\n.,!?;:\"“”«»()[]{}…-–—"


def normalize(text):
    """Lower-case, trimmed of punctuation, single spaces."""
    return " ".join((text or "").strip(_PUNCT).casefold().split())


def tokens_of(text, lang):
    return TOKEN_RE[lang].findall(text or "")


def is_short(text, limit=3):
    return 0 < len(text.split()) <= limit


def en_candidates(word):
    """Possible dictionary forms of an English word (exact form first)."""
    w = normalize(word).strip("'")
    if not w:
        return []

    candidates = [w]

    def add(stem):
        if len(stem) >= 2 and stem not in candidates:
            candidates.append(stem)
        # running -> runn -> run
        if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            if stem[:-1] not in candidates:
                candidates.append(stem[:-1])

    if " " in w:
        return candidates

    if w.endswith("'s"):
        add(w[:-2])
    for suffix, replacement in (
        ("ies", "y"), ("ied", "y"), ("es", ""), ("s", ""),
        ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e"),
        ("ly", ""), ("er", ""), ("est", ""),
    ):
        if w.endswith(suffix) and len(w) - len(suffix) >= 2:
            add(w[: -len(suffix)] + replacement)
    return candidates


def ru_candidates(word):
    w = normalize(word)
    if not w:
        return []
    out = [w]
    if "ё" in w:
        out.append(w.replace("ё", "е"))
    return out


def highlight(text, query_tokens, color):
    """Escapes text and wraps words that start like any query token."""
    prefixes = []
    for token in query_tokens:
        token = token.lower()
        cut = len(token) - 3 if len(token) >= 6 else len(token) - 1 if len(token) >= 4 else len(token)
        prefixes.append(re.escape(token[: max(cut, 2)]))
    if not prefixes:
        return html.escape(text)

    pattern = re.compile(r"\b(?:" + "|".join(prefixes) + r")\w*", re.IGNORECASE)
    out = []
    pos = 0
    for m in pattern.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        out.append(f'<span style="color:{color}; font-weight:600;">{html.escape(m.group())}</span>')
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


class LookupDB:

    def __init__(self, path):
        self.conn = None
        self.has_variants = False
        self.has_examples = False

        if not path or not os.path.exists(path):
            return

        try:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            tables = {
                r[0] for r in self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
            }
            self.has_variants = "variants" in tables and bool(
                self.conn.execute("SELECT 1 FROM variants LIMIT 1").fetchone())
            self.has_examples = {"pairs", "en_fts", "ru_fts"} <= tables and bool(
                self.conn.execute("SELECT 1 FROM pairs LIMIT 1").fetchone())
        except sqlite3.Error as e:
            print(f"lookup.db could not be opened: {e}")
            self.close()

    @property
    def available(self):
        return self.has_variants or self.has_examples

    # ---------------- variants ----------------

    def variants(self, text, src, dst):
        """All stored translations of a word/phrase (best first)."""
        if not self.has_variants:
            return []

        candidates = en_candidates(text) if src == "en" else ru_candidates(text)
        pair = f"{src}-{dst}"

        try:
            for candidate in candidates:
                row = self.conn.execute(
                    "SELECT translations FROM variants WHERE pair = ? AND word = ?",
                    (pair, candidate),
                ).fetchone()
                if row:
                    return [t for t in row[0].split("\t") if t]
        except sqlite3.Error as e:
            print("lookup variants error:", e)
        return []

    def other_variants(self, text, src, dst, main_translation=""):
        """Variants without the translation that is already shown."""
        skip = {normalize(main_translation)} if main_translation else set()
        result = []
        for v in self.variants(text, src, dst):
            if normalize(v) in skip or normalize(v) in (normalize(x) for x in result):
                continue
            result.append(v)
        return result[:MAX_SHOWN_VARIANTS]

    # ---------------- examples ----------------

    @staticmethod
    def _fts_query(tokens, src):
        if len(tokens) == 1 and src == "ru":
            t = tokens[0].lower()
            cut = 2 if len(t) >= 7 else 1 if len(t) >= 5 else 0
            stem = t[: len(t) - cut]
            return f'"{stem}"*' if cut else f'"{stem}"'
        return '"' + " ".join(t.lower() for t in tokens) + '"'

    def examples(self, text, src, limit=3):
        """[(sentence in src language, sentence in the other language), ...]"""
        if not self.has_examples:
            return []

        tokens = tokens_of(text, src)
        if not tokens or len(tokens) > 4:
            return []
        if len(tokens) == 1 and tokens[0].lower() in STOP_WORDS:
            return []

        table = "en_fts" if src == "en" else "ru_fts"
        try:
            rows = self.conn.execute(
                f"SELECT p.en, p.ru FROM {table} "
                f"JOIN pairs p ON p.id = {table}.rowid "
                f"WHERE {table} MATCH ? "
                f"ORDER BY ABS(p.len - ?) LIMIT ?",
                (self._fts_query(tokens, src), IDEAL_LEN, limit),
            ).fetchall()
        except sqlite3.Error as e:
            print("lookup examples error:", e)
            return []

        return [(en, ru) if src == "en" else (ru, en) for en, ru in rows]

    # ---------------- html ----------------

    def variants_html(self, text, src, dst, main_translation="", colors=None):
        """Other translations, one per line ('' if there are none)."""
        c = {**DEFAULT_COLORS, **(colors or {})}
        variants = self.other_variants(text, src, dst, main_translation)
        return "".join(
            f'<div style="margin-top:{0 if i == 0 else 3}px; color:{c["text"]};">{html.escape(v)}</div>'
            for i, v in enumerate(variants)
        )

    def examples_html(self, text, src, colors=None, max_examples=3):
        """Usage examples ('' if there are none)."""
        c = {**DEFAULT_COLORS, **(colors or {})}
        examples = self.examples(text, src, max_examples)
        if not examples:
            return ""
        tokens = tokens_of(text, src)
        return "".join(
            f'<div style="margin-top:{0 if i == 0 else 8}px; color:{c["text"]};">'
            f'{highlight(first, tokens, c["accent"])}</div>'
            f'<div style="color:{c["muted"]};">{html.escape(second)}</div>'
            for i, (first, second) in enumerate(examples)
        )

    def details_parts(self, text, src, dst, main_translation="", colors=None, max_examples=3):
        """(variants_html, examples_html) for a word or short phrase."""
        text = (text or "").strip()
        if not text or not self.available:
            return "", ""
        return (
            self.variants_html(text, src, dst, main_translation, colors),
            self.examples_html(text, src, colors, max_examples),
        )

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
        self.conn = None
        self.has_variants = False
        self.has_examples = False
