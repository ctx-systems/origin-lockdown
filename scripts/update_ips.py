#!/usr/bin/env python3
"""Refresh ips/<provider>-v4.txt and ips/<provider>-v6.txt for every
provider in sources.json with method "fetch". Standard library only.

Usage: python3 scripts/update_ips.py [provider-id ...]
"""
import ipaddress
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IPS = ROOT / "ips"
UA = "origin-lockdown-updater (+https://github.com/ctx-systems/origin-lockdown)"

# Refuse to write a list that shrank this much: a broken endpoint should
# fail the run, not silently lock out a CDN.
MAX_SHRINK = 0.5


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse(endpoint, body):
    """Return a list of (family, network) tuples."""
    fmt = endpoint["format"]
    if fmt == "text":
        items = [line.strip() for line in body.splitlines()]
    elif fmt == "json-array":
        items = json.loads(body)
    elif fmt == "json-keys":
        data = json.loads(body)
        items = [ip for key in endpoint["keys"] for ip in data.get(key, [])]
    elif fmt == "aws":
        data = json.loads(body)
        svc = endpoint["service"]
        items = [p["ip_prefix"] for p in data["prefixes"] if p["service"] == svc]
        items += [p["ipv6_prefix"] for p in data["ipv6_prefixes"] if p["service"] == svc]
    else:
        raise ValueError(f"unknown format {fmt}")

    out = []
    for item in items:
        if not item or item.startswith("#"):
            continue
        net = ipaddress.ip_network(item, strict=False)  # raises on garbage
        out.append((f"v{net.version}", net))
    return out


def write(path, nets):
    old = path.read_text().split() if path.exists() else []
    if old and len(nets) < len(old) * MAX_SHRINK:
        raise RuntimeError(f"{path.name}: {len(old)} -> {len(nets)} entries, refusing")
    text = "".join(f"{n}\n" for n in nets)
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


def main(only):
    sources = json.loads((ROOT / "sources.json").read_text())["providers"]
    failed = []
    for p in sources:
        if p["method"] != "fetch" or (only and p["id"] not in only):
            continue
        try:
            found = {"v4": set(), "v6": set()}
            for ep in p["endpoints"]:
                for family, net in parse(ep, get(ep["url"])):
                    found[family].add(net)
            for family, nets in found.items():
                if not nets:
                    continue
                path = IPS / f"{p['id']}-{family}.txt"
                changed = write(path, sorted(nets))
                print(f"{'updated' if changed else 'same   '} {path.name} ({len(nets)})")
        except Exception as exc:  # keep going, report at the end
            failed.append(p["id"])
            print(f"FAILED  {p['id']}: {exc}", file=sys.stderr)
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
