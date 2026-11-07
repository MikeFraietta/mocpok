"""Import the 1,727 MeepleLM rulebooks (github.com/leroy9472/MeepleLM, data/rulebooks).

These are LLM-restructured rulebooks keyed by BoardGameGeek id, not the publishers' original text.
Requires the sparse clone at raw/meeplelm/repo (see README).
"""
import csv
import sys

from common import RAW, already_have, log, write_doc

SRC = "meeplelm"
REPO = RAW / "meeplelm" / "repo" / "data"


def main():
    names = {}
    with (REPO / "metadata" / "boardgames_ranks.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            names[row["id"]] = (row["name"], row["yearpublished"], row["rank"])
    have = already_have(SRC)
    n = 0
    for p in sorted((REPO / "rulebooks").rglob("*.md")):
        bgg_id = p.stem
        doc_id = f"bgg-{bgg_id}"
        if doc_id in have:
            continue
        name, year, rank = names.get(bgg_id, (None, None, None))
        if write_doc(
            source=SRC,
            doc_id=doc_id,
            title=name or f"BGG {bgg_id}",
            text=p.read_text(encoding="utf-8", errors="replace"),
            url=f"https://boardgamegeek.com/boardgame/{bgg_id}",
            license="MeepleLM repo (MIT badge); underlying rules (c) original publishers",
            kind="llm_restructured_rules",
            ext="md",
            extra={"bgg_id": int(bgg_id), "year": year, "bgg_rank": rank},
        ):
            n += 1
    log(f"[{SRC}] wrote {n} docs")


if __name__ == "__main__":
    sys.exit(main())
