"""English Wikipedia articles about board, card, dice, tile and abstract games (CC BY-SA 4.0).

Walks game categories via the MediaWiki Action API, skipping categories about people, companies,
awards, media and video games, caches the candidate list, then saves each article's plain text.
robots.txt disallows /w/ for crawlers; the Action API is Wikimedia's sanctioned programmatic
interface (mediawiki.org/wiki/API:Etiquette): serial requests + maxlag, which we follow.
"""
import argparse
import json
import re
import sys
from collections import deque

from common import RAW, DiskFull, Fetcher, already_have, log, slugify, write_doc

SRC = "wikipedia"
API = "https://en.wikipedia.org/w/api.php"
API_OPTS = {"check_robots": False}
ROOTS = [
    "Board games", "Card games", "Dice games", "Tile-based games", "Abstract strategy games",
    "Board wargames", "Traditional board games", "Tabletop games", "Mancala games",
    "Chess variants", "Race games", "Dedicated deck card games", "Collectible card games",
    "Party games", "Cooperative board games", "Roll-and-move board games",
]
SKIP_CAT = re.compile(
    r"designer|publisher|compan|people|player|award|magazine|website|convention|video game|film|"
    r"television|tv |novel|book|comic|software|programs|engine|computer|online|museum|tournament|"
    r"championship|olympiad|competition|organi[sz]ation|federation|club|histor|by country|by year|"
    r"in fiction|terminology|openings|problems|theor|endgame|grandmaster|puzzle|lists? of|"
    r"template|wikipedia|stub|images|media|culture|journalists|writers|youtube|esports|casino",
    re.I,
)
SKIP_TITLE = re.compile(r"^(List of|Lists of|Outline of|Index of|History of|Glossary of)\b|\(disambiguation\)", re.I)
RULES_HDR = re.compile(r"^==+\s*(rules?|gameplay|game ?play|how to play|play|objective|setup|"
                       r"the game|mechanics|scoring|equipment|components)\b", re.I | re.M)


def members(f, cat):
    params = {"action": "query", "list": "categorymembers", "cmtitle": f"Category:{cat}",
              "cmtype": "page|subcat", "cmlimit": "500", "format": "json", "maxlag": "5"}
    while True:
        d = f.get(API, params=params, **API_OPTS).json()
        yield from d.get("query", {}).get("categorymembers", [])
        if "continue" not in d:
            return
        params.update(d["continue"])


def crawl(f, max_depth):
    cache = RAW / "wikipedia" / f"candidates-depth{max_depth}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pages, seen_cats = {}, set()
    q = deque((c, 0) for c in ROOTS)
    while q:
        cat, depth = q.popleft()
        if cat in seen_cats:
            continue
        seen_cats.add(cat)
        for m in members(f, cat):
            t = m["title"]
            if m["ns"] == 14:
                sub = t.split(":", 1)[1]
                if depth < max_depth and not SKIP_CAT.search(sub):
                    q.append((sub, depth + 1))
            elif m["ns"] == 0 and not SKIP_TITLE.search(t):
                pages.setdefault(t, cat)
        if len(seen_cats) % 50 == 0:
            log(f"[{SRC}] crawled {len(seen_cats)} categories, queue {len(q)}, {len(pages)} articles")
    log(f"[{SRC}] {len(seen_cats)} categories, {len(pages)} candidate articles")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages))
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    f = Fetcher(delay=0.2)
    pages = crawl(f, args.depth)
    have = already_have(SRC)
    n = 0
    for i, (title, cat) in enumerate(sorted(pages.items())):
        if args.limit and n >= args.limit:
            break
        doc_id = slugify(title)
        if doc_id in have:
            continue
        try:
            d = f.get(API, params={"action": "query", "prop": "extracts|info", "explaintext": "1",
                                   "exsectionformat": "wiki", "inprop": "url", "titles": title,
                                   "redirects": "1", "format": "json", "maxlag": "5"}, **API_OPTS).json()
            page = next(iter(d["query"]["pages"].values()))
            text = page.get("extract", "")
            if "player" not in text.lower():  # not about a playable game
                continue
            if write_doc(
                source=SRC, doc_id=doc_id, title=page.get("title", title), text=text,
                url=page.get("fullurl", f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"),
                license="CC BY-SA 4.0 (Wikipedia contributors)", kind="encyclopedia_article",
                extra={"category": cat, "has_rules_section": bool(RULES_HDR.search(text)),
                       "pageid": page.get("pageid")},
            ):
                n += 1
                have.add(doc_id)
        except DiskFull:
            raise
        except Exception as e:
            log(f"[{SRC}] {title}: {type(e).__name__}: {e}")
        if i % 200 == 0:
            log(f"[{SRC}] {i}/{len(pages)} written={n}")
    log(f"[{SRC}] done: wrote {n}")


if __name__ == "__main__":
    sys.exit(main())
