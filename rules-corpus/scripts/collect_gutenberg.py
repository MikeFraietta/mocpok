"""Public-domain books of game rules from Project Gutenberg (Hoyle, chess, whist, card games, ...).

Uses Gutenberg's official offline catalog CSV (streamed, not saved) to find books whose subjects
or bookshelves are about games, then fetches each plain-text file and strips the PG boilerplate.
"""
import csv
import io
import re
import sys

from common import DiskFull, Fetcher, already_have, log, write_doc

SRC = "gutenberg"
CATALOG = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
SUBJECT_RE = re.compile(
    r"\b(board games|card games|games$|games --|dice games|chess|checkers|draughts|go \(game\)|"
    r"whist\b|bridge \(game\)|poker|cribbage|backgammon|dominoes|solitaire \(game\)|"
    r"mah ?jong|bezique|euchre|piquet|skat|indoor games|parlor games|word games|games -- rules|"
    r"hoyle|wargames?|kriegsspiel)",
    re.I,
)
EXCLUDE_RE = re.compile(r"\b(fiction|juvenile fiction|poetry|drama|periodicals|football|baseball|"
                        r"golf|tennis|cricket|olympic|hunting|fishing|gymnastics|athletics|sports|skating|whistler|parapsychology)\b", re.I)
START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I | re.S)
END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", re.I)


def strip_pg(t: str) -> str:
    m = START.search(t)
    if m:
        t = t[m.end():]
    m = END.search(t)
    if m:
        t = t[: m.start()]
    return t


def main():
    f = Fetcher(delay=2.0, timeout=180)
    r = f.get(CATALOG)
    r.raise_for_status()
    books = []
    for row in csv.DictReader(io.StringIO(r.content.decode("utf-8"))):
        if row.get("Type") != "Text" or row.get("Language") != "en":
            continue
        subj = f"{row.get('Subjects', '')}; {row.get('Bookshelves', '')}"
        if SUBJECT_RE.search(subj) and not EXCLUDE_RE.search(row.get("Subjects", "")):
            books.append(row)
    del r
    log(f"[{SRC}] {len(books)} candidate books")
    have = already_have(SRC)
    n = 0
    for b in books:
        bid = b["Text#"]
        doc_id = f"pg{bid}"
        if doc_id in have:
            continue
        url = f"https://www.gutenberg.org/cache/epub/{bid}/pg{bid}.txt"
        try:
            t = f.get(url)
            if t.status_code != 200:
                continue
            if write_doc(
                source=SRC, doc_id=doc_id, title=b["Title"].replace("\n", " "),
                text=strip_pg(t.content.decode("utf-8", "replace")),
                url=f"https://www.gutenberg.org/ebooks/{bid}", license="Public domain (US); Project Gutenberg",
                kind="rules_book",
                extra={"authors": b.get("Authors"), "subjects": b.get("Subjects"), "issued": b.get("Issued")},
            ):
                n += 1
        except DiskFull:
            raise
        except Exception as e:
            log(f"[{SRC}] {bid}: {type(e).__name__}: {e}")
    log(f"[{SRC}] done: wrote {n}")


if __name__ == "__main__":
    sys.exit(main())
