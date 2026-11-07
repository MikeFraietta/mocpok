"""Ludii game descriptions (ludii.games/downloads/allGames.zip, ~2.4 MB).

Each .lud file holds formal rules in the Ludii game language plus metadata with an English
(description ...) and (rules ...) string. We save the English rules, description, source, and the
formal .lud code together, which is useful both as natural-language rules and as structured rules.
Ludii is distributed under CC BY-NC-ND 4.0 (non-commercial).
"""
import io
import re
import sys
import zipfile

from common import Fetcher, already_have, log, slugify, write_doc

SRC = "ludii"
URL = "https://ludii.games/downloads/allGames.zip"


def field(src: str, name: str) -> str:
    m = re.search(r'\(' + name + r'\s+"((?:[^"\\]|\\.)*)"', src, re.S)
    return m.group(1).replace('\\"', '"').strip() if m else ""


def main():
    f = Fetcher(delay=1.0, timeout=120)
    r = f.get(URL)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    have = already_have(SRC)
    n = 0
    for info in zf.infolist():
        if not info.filename.endswith(".lud") or "/bad" in info.filename.lower() or "/test" in info.filename.lower():
            continue
        src = zf.read(info).decode("utf-8", "replace")
        name = info.filename.rsplit("/", 1)[-1][:-4]
        category = "/".join(info.filename.split("/")[:-1])
        doc_id = slugify(f"{category}-{name}")
        if doc_id in have:
            continue
        desc, rules, origin = field(src, "description"), field(src, "rules"), field(src, "source")
        if not rules and not desc:
            continue
        code = re.split(r"\n\s*\(metadata", src)[0].strip()
        text = f"# {name}\n\n"
        if desc:
            text += f"## Description\n{desc}\n\n"
        if rules:
            text += f"## Rules\n{rules}\n\n"
        if origin:
            text += f"## Source\n{origin}\n\n"
        text += f"## Formal rules (Ludii game description language)\n```\n{code}\n```\n"
        if write_doc(
            source=SRC, doc_id=doc_id, title=name, text=text,
            url=f"https://ludii.games/details.php?keyword={name.replace(' ', '%20')}",
            license="CC BY-NC-ND 4.0 (Ludii / Digital Ludeme Project)", kind="formal_game_description",
            ext="md", extra={"ludii_path": info.filename, "has_english_rules": bool(rules)},
        ):
            n += 1
    log(f"[{SRC}] done: wrote {n}")


if __name__ == "__main__":
    sys.exit(main())
