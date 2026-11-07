"""Merge manifests, dedupe, write a clean manifest + stats, and optionally export training JSONL.

  python build_dataset.py                      # corpus/manifest_clean.jsonl + corpus/stats.json
  python build_dataset.py --export out.jsonl   # one {"id","title","text",...} line per doc
  python build_dataset.py --export out.jsonl --exclude-kind llm_restructured_rules \
        --license-filter "CC BY-SA|Public domain"     # e.g. only openly licensed, human-written text

Reads corpus/manifest.jsonl plus every shard in corpus/manifests/. Entries whose file was deleted
(e.g. off-topic books removed by hand) are dropped.
"""
import argparse
import collections
import json
import re
import sys

from common import CORPUS, MANIFEST, MANIFEST_DIR, ROOT


def manifest_lines():
    files = [MANIFEST] if MANIFEST.exists() else []
    files += sorted(MANIFEST_DIR.glob("*.jsonl")) if MANIFEST_DIR.exists() else []
    for p in files:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export")
    ap.add_argument("--exclude-kind", action="append", default=[])
    ap.add_argument("--exclude-source", action="append", default=[])
    ap.add_argument("--license-filter", help="regex; keep only docs whose license matches")
    args = ap.parse_args()

    rows, seen_hash, seen_id = [], set(), set()
    dupes = missing = 0
    for d in manifest_lines():
        key = (d["source"], d["doc_id"])
        if key in seen_id:
            continue
        seen_id.add(key)
        if not (ROOT / d["path"]).exists():
            missing += 1
            continue
        if d["sha256"] in seen_hash:
            dupes += 1
            continue
        seen_hash.add(d["sha256"])
        rows.append(d)

    (CORPUS / "manifest_clean.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    by_src = collections.defaultdict(lambda: {"docs": 0, "chars": 0})
    for r in rows:
        s = by_src[(r["source"], r["kind"], r["license"])]
        s["docs"] += 1
        s["chars"] += r["chars"]
    stats = {
        "total_docs": len(rows),
        "total_chars": sum(r["chars"] for r in rows),
        "approx_tokens": sum(r["chars"] for r in rows) // 4,
        "exact_duplicates_dropped": dupes,
        "removed_or_missing_files": missing,
        "by_source": [{"source": k[0], "kind": k[1], "license": k[2], **v} for k, v in sorted(by_src.items())],
    }
    (CORPUS / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"{'source':<11}{'kind':<26}{'docs':>7}{'MB':>8}")
    for b in stats["by_source"]:
        print(f"{b['source']:<11}{b['kind']:<26}{b['docs']:>7}{b['chars']/1e6:>8.1f}")
    print(f"TOTAL {stats['total_docs']} docs, {stats['total_chars']/1e6:.1f}M chars "
          f"(~{stats['approx_tokens']/1e6:.1f}M tokens); dropped {dupes} dupes, {missing} removed/missing")

    if args.export:
        lic = re.compile(args.license_filter) if args.license_filter else None
        n = 0
        with open(args.export, "w", encoding="utf-8") as out:
            for r in rows:
                if r["kind"] in args.exclude_kind or r["source"] in args.exclude_source:
                    continue
                if lic and not lic.search(r["license"]):
                    continue
                text = (ROOT / r["path"]).read_text(encoding="utf-8")
                out.write(json.dumps({"id": f"{r['source']}/{r['doc_id']}", "title": r["title"], "text": text,
                                      "source": r["source"], "kind": r["kind"], "license": r["license"],
                                      "url": r["url"]}, ensure_ascii=False) + "\n")
                n += 1
        print(f"exported {n} docs -> {args.export}")


if __name__ == "__main__":
    sys.exit(main())
