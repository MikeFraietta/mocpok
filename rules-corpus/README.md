# Board game rules corpus

> **What's in this repo:** the collector scripts and the metadata manifests (title, source URL, license, size and hash for each of the 3,132 documents collected on November 7, 2026). **The rule text itself isn't included**, because most of it is copyrighted or licensed with restrictions (see the license column below). Run the scripts to rebuild the corpus locally. MocPok doesn't train on it yet; it's the dataset for our planned fine-tune.

Text corpus of board/card/tabletop game rules for training or grounding a board-game LLM.
Every document is one game (or one rules book) saved as plain text/markdown. Its source URL,
license, and the *kind* of text it is are recorded in `corpus/manifest.jsonl` (first run) and
`corpus/manifests/*.jsonl` (one shard per later collector run).

## Sources

| source | what it is | kind | license | docs |
|---|---|---|---|---|
| `meeplelm` | Rulebooks from the MeepleLM paper (ACL 2026, github.com/leroy9472/MeepleLM), top BGG games | `llm_restructured_rules` (LLM-rewritten, may contain errors) | repo says MIT; underlying rules (c) publishers | 1,725 |
| `ludii` | Ludii / Digital Ludeme Project: traditional & historical games, English rules + formal rules code | `formal_game_description` | CC BY-NC-ND 4.0 | 1,296 |
| `gutenberg` | Public-domain rules books (Foster's Complete Hoyle, whist, bridge, chess, go, mah-jong, ...) | `rules_book` | Public domain (US) | 38 |
| `hasbro` | Official instruction PDFs from instructions.hasbro.com (Monopoly, Clue, Risk, Avalon Hill, ...) → text | `official_rulebook` | (c) Hasbro, all rights reserved | in progress (893 games in catalog) |
| `wikipedia` | English Wikipedia articles from board/card/dice/abstract game categories | `encyclopedia_article` | CC BY-SA 4.0 | in progress |

Not used on purpose: BoardGameGeek file downloads (its terms forbid scraping), piracy/mirror sites.

Note: 13 off-topic Gutenberg books (about the painter Whistler, etc.) were deleted after the first
run; their lines are still in `corpus/manifest.jsonl` and `build_dataset.py` drops them.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install pypdf requests   # optional: pymupdf (faster PDFs)
cd scripts
../.venv/bin/python collect_ludii.py
../.venv/bin/python collect_hasbro.py
../.venv/bin/python collect_wikipedia.py --depth 2
../.venv/bin/python collect_gutenberg.py
# MeepleLM needs a sparse clone first:
#   GIT_LFS_SKIP_SMUDGE=1 git -c filter.lfs.process= -c filter.lfs.smudge=cat -c filter.lfs.required=false \
#     clone --depth 1 --filter=blob:none --sparse https://github.com/leroy9472/MeepleLM.git ../raw/meeplelm/repo
#   (cd ../raw/meeplelm/repo && git sparse-checkout set data/rulebooks data/metadata)
../.venv/bin/python collect_meeplelm.py
../.venv/bin/python build_dataset.py --export ../rules.jsonl
```

Collectors resume where they stopped (they skip games whose file already exists), are rate-limited
per host, check robots.txt, and stop if free disk drops under 300 MB (`MIN_FREE_MB` env var).
`CORPUS_ROOT` points them at a different corpus folder; `CACHE_DIR` moves the crawl cache.

Hasbro is bandwidth-heavy: ~870 PDFs averaging ~5 MB are downloaded (only the text is kept).

## Filtering for training

`build_dataset.py` merges the manifests, dedupes by content hash, and writes
`corpus/manifest_clean.jsonl` and `corpus/stats.json`. Export subsets by kind/license, e.g. only
openly licensed human-written text:

```bash
python build_dataset.py --export open.jsonl --license-filter "CC BY-SA|Public domain"
```

Licensing is your call: `official_rulebook` and `meeplelm` text is publishers' copyrighted material
(freely posted, but not openly licensed); `ludii` is non-commercial; `wikipedia` requires attribution
and share-alike; `gutenberg` is public domain in the US.
