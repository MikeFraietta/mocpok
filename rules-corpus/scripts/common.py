"""Shared helpers for the board game rules corpus collectors.

Layout (relative to the corpus root: $CORPUS_ROOT, or this file's parent's parent):
  corpus/<source>/<doc_id>.txt|.md   one plain-text/markdown document per game
  corpus/manifest.jsonl              manifest from the first collection run
  corpus/manifests/*.jsonl           one manifest shard per later collector run
  raw/                               cache for crawls ($CACHE_DIR overrides)

Collectors never read existing corpus files: they resume by listing file names, and each run writes
its manifest to a new shard. That keeps them working when the folder is synced by iCloud Drive and
macOS has offloaded older files.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings are noise here

ROOT = Path(os.environ.get("CORPUS_ROOT") or Path(__file__).resolve().parent.parent)
CORPUS = ROOT / "corpus"
RAW = Path(os.environ.get("CACHE_DIR") or ROOT / "raw")
MANIFEST = CORPUS / "manifest.jsonl"
MANIFEST_DIR = CORPUS / "manifests"

# Generic client name on purpose (no personal contact details).
USER_AGENT = "BoardGameRulesCorpus/0.1 (research dataset builder; python-requests)"

# Stop writing when the disk gets this low.
MIN_FREE_BYTES = int(os.environ.get("MIN_FREE_MB", "300")) * 1024 * 1024

_RUN = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"


class DiskFull(RuntimeError):
    pass


def check_disk(min_free: int = MIN_FREE_BYTES) -> int:
    free = shutil.disk_usage(ROOT).free
    if free < min_free:
        raise DiskFull(f"only {free/1e6:.0f} MB free (< {min_free/1e6:.0f} MB guard); stopping")
    return free


def slugify(s: str, maxlen: int = 120) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen] or "untitled"


class Fetcher:
    """requests.Session with a per-host delay, retries, and robots.txt checks."""

    def __init__(self, delay: float = 1.0, timeout: float = 60.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=20)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[base] = rp
        return self._robots[base].can_fetch(USER_AGENT, url)

    def get(self, url: str, *, params=None, stream=False, check_robots=True, retries=3, **kw):
        if check_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        r = None
        for attempt in range(retries):
            wait = self._last.get(host, 0) + self.delay - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.time()
            try:
                r = self.s.get(url, params=params, timeout=self.timeout, stream=stream, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(int(r.headers.get("Retry-After", 5 * (attempt + 1))))
                    continue
                return r
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(3 * (attempt + 1))
        return r


def pdf_bytes_to_text(data: bytes) -> str:
    """PyMuPDF if installed (much faster), else pypdf."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as doc:
            return clean_text("\n\n".join(page.get_text() for page in doc))
    except ImportError:
        pass
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for pg in reader.pages:
        try:
            pages.append(pg.extract_text() or "")
        except Exception:  # malformed page; keep going
            pages.append("")
    return clean_text("\n\n".join(pages))


def clean_text(t: str) -> str:
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{4,}", "\n\n\n", t)
    return t.strip() + "\n"


def already_have(source: str) -> set[str]:
    """doc_ids already saved for a source, from file names only (no file reads)."""
    d = CORPUS / source
    return {p.stem for p in d.iterdir()} if d.exists() else set()


def write_doc(
    *,
    source: str,
    doc_id: str,
    title: str,
    text: str,
    url: str,
    license: str,
    kind: str,
    ext: str = "txt",
    lang: str = "en",
    extra: dict | None = None,
) -> Path | None:
    """Write one document and append its manifest line. Returns None if text is too short.

    kind: what the text is, e.g.
      "official_rulebook"       publisher's own rules text (PDF -> text)
      "llm_restructured_rules"  rules rewritten by an LLM (synthetic, may contain errors)
      "encyclopedia_article"    Wikipedia-style description incl. rules section
      "rules_book"              public-domain book of rules for many games
      "formal_game_description" machine-readable rules (e.g. Ludii .lud)
    """
    text = clean_text(text)
    if len(text) < 200:
        return None
    check_disk()
    d = CORPUS / source
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{doc_id}.{ext}"
    path.write_text(text, encoding="utf-8")
    rec = {
        "source": source,
        "doc_id": doc_id,
        "title": title,
        "path": str(path.relative_to(ROOT)),
        "url": url,
        "license": license,
        "kind": kind,
        "lang": lang,
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        rec.update(extra)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    with (MANIFEST_DIR / f"{source}-{_RUN}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def log(*a):
    print(*a, file=sys.stderr, flush=True)
