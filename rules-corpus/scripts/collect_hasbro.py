"""Official game instructions from instructions.hasbro.com (robots.txt allows /*, disallows /api/*).

Every instruction page embeds the full product catalog, so we read it once, keep the games
(by brand or "game" in the name), then fetch each game's page head to find its PDF, download
the PDF to memory, extract text, and keep only the text.
"""
import argparse
import json
import re
import sys
import time

from common import DiskFull, Fetcher, already_have, log, pdf_bytes_to_text, write_doc

SRC = "hasbro"
BASE = "https://instructions.hasbro.com"
GAME_BRANDS = {
    "Hasbro Games", "Monopoly", "Avalon Hill", "Yahtzee", "Dungeons & Dragons", "Cranium", "Clue",
    "Trivial Pursuit", "Scrabble", "Operation", "Bop It", "Connect 4", "Battleship", "The Game of Life",
    "Simon", "Milton Bradley", "Candy Land", "Trouble", "Guess Who?", "Guess Who", "Sorry!", "Sorry",
    "Twister", "Risk", "Cootie", "Memory", "Stratego", "Elefun & Friends", "Boggle", "Guesstures", "Jenga",
    "Hi Ho! Cherry-O", "Pictureka!", "Catchphrase", "Electronic Catch Phrase", "Aggravation",
    "Hungry Hungry Hippos", "Cuponk", "Pretty Pretty Princess", "Rook", "Mystery Date", "Girl Talk",
    "Chutes & Ladders", "Chutes  Ladders", "Axis & Allies", "Taboo", "Parker Brothers", "Wizards Of the Coast",
    "Magic the Gathering", "Ants in the Pants", "Funglish", "Don't Spill the Beans", "The Game of Things...",
    "Don't Break the Ice", "SPLIT", "Hasbro Card Games", "Barrel of Monkeys", "Whac a Mole", "Ouija",
    "Hangman", "Boxers or Briefs", "Family Game Night", "Scattergories", "Guess Where?", "Parcheesi",
    "Bejeweled", "Dropmix", "Raise the Fun - Classic", "Funny or Die",
}
NOT_GAMES = re.compile(r"\b(video game|puzzle|figure|blaster|plush)\b", re.I)
PDF_RE = re.compile(r"https://assets-[a-z0-9-]+\.kc-usercontent\.com(?::443)?/[^\"'\s<>]+?\.pdf", re.I)
MAX_PDF = 40 * 1024 * 1024
JSTR = r'"((?:[^"\\]|\\.)*)"'


def catalog(f: Fetcher):
    r = f.get(f"{BASE}/en-us/instruction/acquire")
    r.raise_for_status()
    items = re.findall(r'\{"sku":' + JSTR + ',"slug":' + JSTR + ',"brand":' + JSTR + ',"name":' + JSTR, r.text)
    seen, out = set(), []
    for sku, slug, brand, name in items:
        brand = json.loads(f'"{brand}"')
        name = json.loads(f'"{name}"')
        if slug in seen:
            continue
        seen.add(slug)
        is_game = brand in GAME_BRANDS or re.search(r"\bgames?\b", name, re.I)
        if is_game and not NOT_GAMES.search(name):
            out.append({"sku": sku, "slug": slug, "brand": brand, "name": name})
    return out


def first_pdf(f: Fetcher, url: str) -> str | None:
    r = f.get(url, stream=True)
    if r.status_code != 200:
        return None
    buf = b""
    for chunk in r.iter_content(16384):
        buf += chunk
        m = PDF_RE.search(buf.decode("utf-8", "ignore"))
        if m:
            r.close()
            return m.group(0).replace(":443/", "/")
        if len(buf) > 200_000:
            break
    r.close()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--profile", action="store_true", help="print per-step timings")
    args = ap.parse_args()
    f = Fetcher(delay=1.0)
    games = catalog(f)
    log(f"[{SRC}] {len(games)} game products in catalog")
    have = already_have(SRC)
    n = skipped = 0
    for i, g in enumerate(games):
        if args.limit and n >= args.limit:
            break
        doc_id = f"{g['sku']}-{g['slug']}"[:150]
        if doc_id in have:
            continue
        page = f"{BASE}/en-us/instruction/{g['slug']}"
        try:
            t0 = time.time()
            pdf = first_pdf(f, page)
            t1 = time.time()
            if not pdf:
                skipped += 1
                continue
            r = f.get(pdf, check_robots=False)  # CDN asset linked from an allowed page
            t2 = time.time()
            if r.status_code != 200 or len(r.content) > MAX_PDF:
                skipped += 1
                continue
            text = pdf_bytes_to_text(r.content)
            t3 = time.time()
            if args.profile:
                log(f"  {g['slug']}: page {t1-t0:.1f}s, pdf {t2-t1:.1f}s ({len(r.content)/1e6:.1f} MB), "
                    f"extract {t3-t2:.1f}s")
            if write_doc(
                source=SRC, doc_id=doc_id, title=g["name"], text=text, url=page,
                license="(c) Hasbro; publicly posted instructions, all rights reserved",
                kind="official_rulebook",
                extra={"pdf_url": pdf, "brand": g["brand"], "sku": g["sku"], "pdf_bytes": len(r.content)},
            ):
                n += 1
            else:
                skipped += 1  # image-only PDF (needs OCR) or empty
        except DiskFull:
            raise
        except Exception as e:
            log(f"[{SRC}] {g['slug']}: {type(e).__name__}: {e}")
            skipped += 1
        if i % 25 == 0:
            log(f"[{SRC}] {i}/{len(games)} written={n} skipped={skipped}")
    log(f"[{SRC}] done: wrote {n}, skipped {skipped} (no PDF / image-only / error)")


if __name__ == "__main__":
    sys.exit(main())
