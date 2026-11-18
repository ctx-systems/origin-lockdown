#!/usr/bin/env python3
"""Check every provider in sources.json with method "manual" against its
doc_url: scrape the IPs shown on the page and compare them with ips/*.txt.
Never writes lists, it only reports. Standard library only.

Exits 1 and prints a Markdown report if any page differs or can't be read.

Usage: python3 scripts/check_manual.py [provider-id ...]
"""
import html
import ipaddress
import json
import re
import sys
from pathlib import Path

from update_ips import ROOT, get

# Page chrome (scripts, styles, SVG paths, attributes) is full of
# dotted numbers that look like IPs, so only visible text is scanned.
NOISE = re.compile(r"<(script|style|svg|noscript)\b.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
CANDIDATE = re.compile(
    r"(?<![\w.:/-])"
    r"(?:\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?"
    r"|[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,7}(?:/\d{1,3})?)"
    r"(?![\w.:/-])"
)


def scrape(body):
    text = html.unescape(TAG.sub(" ", NOISE.sub(" ", body)))
    found = set()
    for m in CANDIDATE.findall(text):
        try:
            found.add(ipaddress.ip_network(m, strict=False))
        except ValueError:
            pass
    return found


def ours(p):
    files = p.get("files") or [
        f"ips/{p['id']}-{f}.txt" for f in ("v4", "v6") if (ROOT / f"ips/{p['id']}-{f}.txt").exists()
    ]
    nets = set()
    for f in files:
        for line in (ROOT / f).read_text().split():
            nets.add(ipaddress.ip_network(line, strict=False))
    return nets


def main(only):
    sources = json.loads((ROOT / "sources.json").read_text())["providers"]
    report = []
    for p in sources:
        if p["method"] != "manual" or (only and p["id"] not in only):
            continue
        have = ours(p)
        try:
            page = scrape(get(p["doc_url"]))
        except Exception as exc:
            report.append(f"### {p['name']}\n\n{p['doc_url']}\n\nCould not fetch the page: `{exc}`\n")
            continue
        gone, new = sorted(have - page), sorted(page - have)
        print(f"{'differs' if gone or new else 'same   '} {p['id']} ({len(have)} listed, {len(page)} on page)")
        if gone or new:
            lines = [f"### {p['name']}\n", p["doc_url"], ""]
            lines += [f"- not on the page anymore: `{n}`" for n in gone]
            lines += [f"- new on the page: `{n}`" for n in new]
            report.append("\n".join(lines) + "\n")
    if report:
        print("\n" + "\n".join(report))
        sys.exit(1)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
