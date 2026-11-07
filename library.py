#!/usr/bin/env python3
"""A small, real, local SQLite FTS5 reference shelf for the MocPok demo.

Only four explicitly selected, already hydrated corpus files are eligible for
indexing. This module never downloads files or scans the full corpus. The
resulting SQLite file contains the indexed text, so retrieval works without the
original corpus once the demo folder is copied. These references are retrieved
at request time; they are not model training data or new model weights.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = ROOT / "library.sqlite3"
MANIFEST_PATH = ROOT / "library_manifest.json"
CORPUS_ROOT = Path("/Users/mike/Desktop/board-game-rules-corpus/corpus")
CHUNK_CHARACTERS = 600
MAX_REFERENCES = 3
SCHEMA_VERSION = 1

# Display titles were checked against the contents, whose opening headings are
# generic section titles rather than game names. First headings are also kept
# in the database and manifest for faithful source metadata.
SELECTED_SOURCES = (
    ("meeplelm/bgg-30549.md", "Pandemic"),
    ("meeplelm/bgg-65244.md", "Forbidden Island"),
    ("meeplelm/bgg-1219.md", "Labyrinth variants"),
    ("meeplelm/bgg-822.md", "Carcassonne"),
)
FALLBACK_PATH = ROOT.parent / "MocPok_Dragon_Keys" / "Rules.md"
FALLBACK_SOURCE = "MocPok_Dragon_Keys/Rules.md"
STOP_WORDS = frozenset(
    "a an and are as at be before board but by can could do for from fun game "
    "games have i in into is it its let lets make me my need of on one or our "
    "please should some that the their them then there these they this to two "
    "up us want we what when where which who will with would you your family "
    "create help something tell about very new like than each also".split()
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _plain(text: str) -> str:
    """Keep the rules' words while removing simple Markdown presentation."""
    text = re.sub(r"!?(\[([^\]]+)\])\([^)]*\)", r"\2", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _split_long(text: str, maximum: int = CHUNK_CHARACTERS) -> list[str]:
    """Split paragraphs on words and preserve complete words where possible."""
    pieces = []
    text = text.strip()
    while len(text) > maximum:
        end = text.rfind("\n", maximum // 2, maximum + 1)
        if end < 0:
            end = text.rfind(" ", maximum // 2, maximum + 1)
        if end < 0:
            end = maximum
        pieces.append(text[:end].strip())
        text = text[end:].strip()
    if text:
        pieces.append(text)
    return pieces


def _chunks(markdown: str) -> list[tuple[str, str]]:
    """Group nearby paragraphs within their actual Markdown heading."""
    chunks: list[tuple[str, str]] = []
    heading = ""
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.extend((heading, part) for part in _split_long(buffer))
        buffer = ""

    for block in re.split(r"\n\s*\n", markdown.replace("\r\n", "\n")):
        block = block.strip()
        if not block or re.fullmatch(r"[-*_]{3,}", block):
            continue
        lines = block.splitlines()
        if lines and re.match(r"^#{1,6}\s+", lines[0]):
            flush()
            heading = _plain(re.sub(r"^#{1,6}\s+", "", lines[0]))
            block = "\n".join(lines[1:]).strip()
        cleaned = _plain(block)
        if not cleaned:
            continue
        if buffer and len(buffer) + 2 + len(cleaned) > CHUNK_CHARACTERS:
            flush()
        buffer = buffer + "\n\n" + cleaned if buffer else cleaned
        if len(buffer) >= CHUNK_CHARACTERS:
            flush()
    flush()
    return [(heading, body) for heading, body in chunks if body]


def _first_heading(text: str) -> str:
    match = re.search(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    return _plain(match.group(1)) if match else ""


def _read_allocated(path: Path) -> tuple[str | None, str]:
    """Avoid opening iCloud placeholders, which can wait for hydration."""
    try:
        stat = path.stat()
        if not stat.st_size:
            return None, "empty"
        if getattr(stat, "st_blocks", 1) == 0:
            return None, "cloud_placeholder_not_read"
        return path.read_text(encoding="utf-8", errors="replace"), "readable"
    except OSError as exc:
        return None, "unavailable:" + type(exc).__name__


def build_index() -> dict:
    """Rebuild atomically from the selected readable documents, never all books."""
    documents = []
    candidates = []
    for source, title in SELECTED_SOURCES:
        path = CORPUS_ROOT / source
        text, state = _read_allocated(path)
        candidates.append({"source": source, "state": state})
        if text:
            documents.append({
                "source": source, "title": title, "text": text,
                "kind": "llm_restructured_rules", "original_path": str(path),
            })
    fallback_used = not documents
    if fallback_used:
        text, state = _read_allocated(FALLBACK_PATH)
        candidates.append({"source": FALLBACK_SOURCE, "state": state})
        if text:
            documents.append({
                "source": FALLBACK_SOURCE,
                "title": _first_heading(text) or "MocPok: Dragon Keys",
                "text": text, "kind": "original_mocpok_rules",
                "original_path": str(FALLBACK_PATH),
            })

    ROOT.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=".library-", suffix=".sqlite3", dir=ROOT)
    os.close(handle)
    temporary = Path(temporary_name)
    indexed_at = _now()
    manifest_documents = []
    try:
        with sqlite3.connect(temporary) as connection:
            connection.executescript("""
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE books (
                    source TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    first_heading TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    chunks INTEGER NOT NULL
                );
                CREATE VIRTUAL TABLE passages USING fts5(
                    title, heading, body, source UNINDEXED,
                    tokenize = 'unicode61 remove_diacritics 2'
                );
            """)
            connection.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [("schema_version", str(SCHEMA_VERSION)), ("indexed_at", indexed_at)],
            )
            for document in documents:
                paragraphs = _chunks(document["text"])
                if not paragraphs:
                    continue
                digest = hashlib.sha256(document["text"].encode("utf-8")).hexdigest()
                heading = _first_heading(document["text"])
                connection.execute(
                    "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?)",
                    (document["source"], document["title"], document["kind"], heading, digest, len(paragraphs)),
                )
                connection.executemany(
                    "INSERT INTO passages (title, heading, body, source) VALUES (?, ?, ?, ?)",
                    [(document["title"], heading, body, document["source"]) for heading, body in paragraphs],
                )
                manifest_documents.append({
                    "source": document["source"], "title": document["title"],
                    "kind": document["kind"], "first_heading": heading,
                    "sha256": digest, "chunks": len(paragraphs),
                    "original_path": document["original_path"],
                })
            connection.execute("INSERT INTO passages(passages) VALUES ('optimize')")
            connection.commit()
            counts = {
                "indexed_books": connection.execute("SELECT count(*) FROM books").fetchone()[0],
                "chunks": connection.execute("SELECT count(*) FROM passages").fetchone()[0],
            }
        os.replace(temporary, DATABASE_PATH)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "indexed_at": indexed_at,
            "engine": "SQLite FTS5; local lexical retrieval",
            "library_counts": counts,
            "maximum_excerpt_characters": CHUNK_CHARACTERS,
            "maximum_references": MAX_REFERENCES,
            "model_training_performed": False,
            "full_corpus_indexed": False,
            "index_scope": "Only the named, already readable source files listed here are indexed.",
            "corpus_status": "Original MocPok rules only; external corpus not yet indexed." if fallback_used else "Four selected corpus candidates checked; counts report only readable indexed documents.",
            "source_note": "MeepleLM corpus documents are LLM-restructured rules references and may contain errors. They are not verified official rulebooks.",
            "fallback_used": fallback_used,
            "candidates": candidates,
            "documents": manifest_documents,
        }
        manifest_temp = MANIFEST_PATH.with_suffix(".json.tmp")
        manifest_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(manifest_temp, MANIFEST_PATH)
        return manifest
    finally:
        if temporary.exists():
            temporary.unlink()


def _query_terms(prompt: str) -> list[str]:
    words = re.findall(r"[^\W\d_]{3,}", str(prompt).casefold(), flags=re.UNICODE)
    terms = []
    for word in words:
        if word not in STOP_WORDS and word not in terms:
            terms.append(word)
        if len(terms) >= 18:
            break
    word_set = set(words)
    if word_set & {"maze", "labyrinth", "paths", "path"}:
        terms.extend(["maze", "labyrinth", "movement", "adjacent"])
    if word_set & {"cooperative", "cooperate", "cooperation", "together", "team"}:
        terms.extend(["cooperative", "team", "players"])
    if word_set & {"key", "keys", "crystal", "crystals", "pearl", "pearls", "treasure", "treasures"}:
        terms.extend(["treasure", "collect", "escape"])
    return list(dict.fromkeys(terms))[:28]


def _fts_query(terms: list[str]) -> str:
    # Every term is a Unicode letter-only token produced above. Quotes are still
    # escaped defensively, and the whole expression is a bound SQL parameter.
    return " OR ".join('"' + word.replace('"', '""') + '"*' for word in terms)


def search_references(prompt: str) -> dict:
    """Return at most three distinct documents and actual index row counts."""
    empty = {"references": [], "library_counts": {"indexed_books": 0, "chunks": 0}}
    if not DATABASE_PATH.is_file():
        return empty
    connection = sqlite3.connect(DATABASE_PATH.as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        counts = {
            "indexed_books": connection.execute("SELECT count(*) FROM books").fetchone()[0],
            "chunks": connection.execute("SELECT count(*) FROM passages").fetchone()[0],
        }
        terms = _query_terms(prompt)
        if not terms:
            return {"references": [], "library_counts": counts}
        query = _fts_query(terms)
        rows = connection.execute("""
            SELECT p.source, p.title, p.heading, p.body, b.kind,
                   bm25(passages, 2.5, 1.5, 1.0, 0.0) AS relevance
            FROM passages AS p JOIN books AS b ON b.source = p.source
            WHERE passages MATCH ? ORDER BY relevance, p.rowid LIMIT 80
        """, (query,)).fetchall()
        references = []
        seen = set()
        for row in rows:
            if row["source"] in seen:
                continue
            seen.add(row["source"])
            references.append({
                "source": row["source"], "title": row["title"],
                "excerpt": row["body"][:CHUNK_CHARACTERS], "kind": row["kind"],
            })
            if len(references) >= MAX_REFERENCES:
                break
        return {"references": references, "library_counts": counts}
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Index only the four named readable source files")
    parser.add_argument("--query", type=str, help="Search the existing local index")
    arguments = parser.parse_args()
    if arguments.build:
        manifest = build_index()
        print(json.dumps({"library_counts": manifest["library_counts"], "fallback_used": manifest["fallback_used"]}, indent=2))
    if arguments.query is not None:
        print(json.dumps(search_references(arguments.query), ensure_ascii=False, indent=2))
    if not arguments.build and arguments.query is None:
        parser.print_help()
