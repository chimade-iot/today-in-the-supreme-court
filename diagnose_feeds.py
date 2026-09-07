#!/usr/bin/env python3
"""
Dump what each candidate feed actually contains.

--check-sources tells you whether a feed answers. This tells you what is
inside it, which is what you need when a feed answers but the bulletin
still comes up empty - usually because the Supreme Court filter cannot
find the court anywhere in the entry.

    python3 diagnose_feeds.py                 # every source
    python3 diagnose_feeds.py kanoon          # just matching ones
    python3 diagnose_feeds.py --entries 5     # show more entries each
"""
from __future__ import annotations

import argparse
import sys

import sources
from sources import _parse_feed, _clean, which_court, is_for_bulletin

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def show(entry, n: int, feed_url: str = "") -> None:
    title = _clean(getattr(entry, "title", ""))
    link = getattr(entry, "link", "")
    summary = _clean(getattr(entry, "summary", ""))
    tags = [t.get("term", "") for t in getattr(entry, "tags", []) or []]
    court = which_court(title, link, feed_url)
    passes = is_for_bulletin(title, link, feed_url)

    print(f"    [{n}] {'ADMITTED' if passes else 'REJECTED'}  (reads as: {court})")
    print(f"        title   : {title[:110]}")
    print(f"        link    : {link[:110]}")
    if tags:
        print(f"        tags    : {', '.join(t for t in tags if t)[:110]}")
    print(f"        fields  : {', '.join(sorted(k for k in entry.keys()))[:110]}")
    if summary:
        print(f"        summary : {summary[:220]}")
    else:
        print("        summary : (empty)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("match", nargs="?", default="",
                    help="only sources whose name contains this text")
    ap.add_argument("--entries", type=int, default=3)
    args = ap.parse_args()

    for src in sources.REGISTRY:
        if args.match and args.match.lower() not in src.name.lower():
            continue
        print(f"\n{'=' * 74}\n{src.name}   [tier: {src.tier}]\n{'=' * 74}")
        for url in src.candidates:
            parsed = _parse_feed(url)
            if parsed is None:
                print(f"  {url}\n    -> no response / not a feed")
                continue
            entries = parsed.entries
            passing = sum(
                1 for e in entries
                if is_for_bulletin(_clean(getattr(e, "title", "")),
                                   getattr(e, "link", ""), url)
            )
            print(f"  {url}\n    -> {len(entries)} entries, "
                  f"{passing} pass the Supreme Court filter")
            for i, e in enumerate(entries[: args.entries], 1):
                show(e, i, url)


if __name__ == "__main__":
    main()
