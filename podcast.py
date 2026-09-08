#!/usr/bin/env python3
"""
Turn the daily bulletin into a podcast.

    python3 podcast.py episode    # package the current build as an episode
    python3 podcast.py feed       # write public/feed.xml from the archive
    python3 podcast.py check      # validate the feed against the spec

Where episodes live, and why
----------------------------
The site is rebuilt from scratch on every run and `public/` is replaced
wholesale, so anything written there is gone by the next edition. A
podcast cannot work that way: a feed points at episodes by URL, and those
URLs have to keep working for as long as the episode is listed. Podcast
apps that get a 404 show a broken episode; ones that see a URL change
re-download it.

Three places the archive could live, and why this one:

  Committed to the repo. Simple and durable, but two editions a day at
  about 1.5 MB each is roughly a gigabyte a year of binaries in git
  history, which cannot be pruned without rewriting history. Rejected.

  Carried forward from the live site. Each build downloads the previous
  episodes back out of Pages and re-uploads them. No repo growth, but the
  archive only exists in the last successful deploy, so one bad run loses
  it. Rejected.

  GitHub Releases. Release assets are permanent, have stable URLs, do not
  count against repo size, and are free on public repos. Better still,
  the release list IS the archive - so the feed is regenerated from
  GitHub each time rather than from a state file that could drift or be
  lost. Nothing to corrupt, and a rebuild from an empty checkout produces
  the identical feed.

Each episode is one release: the tag is its timestamp, the notes carry
the running order, and the MP3 is the asset the feed points at.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

import requests

ROOT = Path(__file__).parent
PUBLIC = ROOT / "public"
ASSETS = ROOT / "assets"
IST = timezone(timedelta(hours=5, minutes=30))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ==========================================================================
# Configuration
# ==========================================================================

DEFAULTS = {
    "title": "Today in the Supreme Court",
    "subtitle": "A daily audio bulletin of the Supreme Court of India",
    "description": (
        "A free daily audio bulletin of the Supreme Court of India, for the "
        "legal fraternity. Each edition runs a few minutes: what the Court "
        "held, who reported it, and where to read the judgment in full. "
        "Generated automatically from public sources, with every story "
        "credited and linked. Not legal advice."
    ),
    "author": "Today in the Supreme Court",
    # Apple requires a contact address on the feed. Put a real one here.
    "email": "",
    "language": "en-IN",
    "category": "News",
    "subcategory": "Daily News",
    "explicit": "false",
    # Filled in from GITHUB_REPOSITORY when running in Actions.
    "owner": "",
    "repo": "",
    "site": "",
}

CONFIG_PATH = ROOT / "podcast.json"


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))

    # Actions supplies owner/repo for free; derive the Pages URL from them.
    slug = os.environ.get("GITHUB_REPOSITORY", "")
    if slug and "/" in slug and not cfg["owner"]:
        cfg["owner"], cfg["repo"] = slug.split("/", 1)
    if cfg["owner"] and cfg["repo"] and not cfg["site"]:
        cfg["site"] = f"https://{cfg['owner']}.github.io/{cfg['repo']}/"

    for key in ("owner", "repo", "site", "email"):
        env = os.environ.get(f"PODCAST_{key.upper()}")
        if env:
            cfg[key] = env
    return cfg


def require(cfg: dict, *keys: str) -> None:
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        sys.exit(
            f"Missing config: {', '.join(missing)}.\n"
            f"Set them in podcast.json, or as PODCAST_* environment "
            f"variables. Inside GitHub Actions owner/repo/site are derived "
            f"from GITHUB_REPOSITORY automatically."
        )


# ==========================================================================
# Packaging one episode
# ==========================================================================

META_OPEN, META_CLOSE = "<!--meta", "-->"


def make_episode(cfg: dict) -> dict:
    """
    Prepare the current build for release: a dated MP3, notes listing the
    running order, and a machine-readable block the feed generator reads
    back so it never has to re-download the audio to learn its length.
    """
    data = json.loads((PUBLIC / "bulletin.json").read_text(encoding="utf-8"))
    src = PUBLIC / data.get("audio", "bulletin.mp3")
    if not src.exists():
        sys.exit(f"No audio at {src}. Run build_bulletin.py first.")

    when = datetime.fromisoformat(data["generated_at"])
    stamp = when.strftime("%Y%m%d-%H%M")
    tag = f"ep-{stamp}"
    slug = f"today-in-the-supreme-court-{stamp}.mp3"

    out_dir = ROOT / ".episode"
    out_dir.mkdir(exist_ok=True)
    dest = out_dir / slug
    shutil.copy2(src, dest)

    items = [c for c in data["cues"] if c.get("kind") == "item"]
    meta = {
        "tag": tag,
        "file": slug,
        "bytes": dest.stat().st_size,
        "duration": round(float(data["duration"])),
        "published": when.isoformat(),
        "item_count": len(items),
        "sources": data.get("sources", []),
    }

    lines = [
        f"Edition of {data.get('generated_at_display', '')}.",
        "",
        f"{len(items)} " + ("story" if len(items) == 1 else "stories")
        + f", {fmt_duration(meta['duration'])}."
        + (f" Reporting by {', '.join(meta['sources'])}." if meta["sources"] else ""),
        "",
        "### In this edition",
        "",
    ]
    for i, c in enumerate(items, 1):
        head = c.get("headline", "").strip()
        cite = f" `{c['citation']}`" if c.get("citation") else ""
        link = c.get("link", "")
        credit = c.get("credit", "")
        lines.append(
            f"{i}. {head}{cite}  \n"
            f"   — {credit}" + (f" · [read it]({link})" if link else "")
        )
    lines += [
        "",
        "---",
        "",
        "Generated automatically from public sources. Every story is credited "
        "and linked to its publisher. This is not legal advice and is no "
        "substitute for the official record — read the full judgment at the "
        "primary source before relying on it.",
        "",
        f"{META_OPEN} {json.dumps(meta)} {META_CLOSE}",
    ]

    notes = out_dir / "notes.md"
    notes.write_text("\n".join(lines), encoding="utf-8")

    title = f"{data.get('generated_at_display', stamp)}"
    (out_dir / "episode.json").write_text(json.dumps(meta, indent=2),
                                          encoding="utf-8")

    # Hand values to the workflow without it having to parse anything.
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"tag={tag}\n")
            fh.write(f"title={title}\n")
            fh.write(f"file={dest}\n")
            fh.write(f"notes={notes}\n")

    print(f"episode  {tag}")
    print(f"  title    {title}")
    print(f"  audio    {dest}  ({meta['bytes'] / 1_048_576:.1f} MB, "
          f"{fmt_duration(meta['duration'])})")
    print(f"  notes    {notes}")
    return meta


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# ==========================================================================
# Reading the archive back out of GitHub Releases
# ==========================================================================

def fetch_releases(cfg: dict, limit: int = 100) -> list[dict]:
    url = (f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}"
           f"/releases?per_page={min(limit, 100)}")
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "today-in-the-supreme-court"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as e:
        sys.exit(
            f"Could not reach the GitHub API: {e}\n"
            f"Refusing to write a feed, because an empty one would make "
            f"every published episode disappear from subscribers' apps. "
            f"The previous deploy stays live; try again."
        )

    if r.status_code == 404:
        # A repo with no releases yet answers 200 with []; a 404 means the
        # repo or owner is wrong, which is worth saying plainly.
        sys.exit(
            f"GitHub says {cfg['owner']}/{cfg['repo']} does not exist, or is "
            f"private. Check owner and repo in podcast.json."
        )
    if r.status_code == 403:
        sys.exit(
            "GitHub API refused the request (403). Unauthenticated calls are "
            "limited to 60 an hour; set GITHUB_TOKEN. Not writing a feed, "
            "since an empty one would unpublish every episode."
        )
    r.raise_for_status()
    return r.json()


def parse_release(rel: dict) -> dict | None:
    """Turn one release into an episode, or None if it is not one."""
    tag = rel.get("tag_name", "")
    if not tag.startswith("ep-") or rel.get("draft"):
        return None

    mp3 = next((a for a in rel.get("assets", [])
                if a.get("name", "").endswith(".mp3")), None)
    if not mp3:
        return None

    meta = {}
    body = rel.get("body") or ""
    m = re.search(re.escape(META_OPEN) + r"\s*(\{.*?\})\s*" + re.escape(META_CLOSE),
                  body, re.S)
    if m:
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            meta = {}

    published = meta.get("published") or rel.get("published_at") or rel.get("created_at")
    try:
        when = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except Exception:
        when = datetime.now(IST)

    # Strip the machine block out of what listeners see.
    shown = re.sub(re.escape(META_OPEN) + r".*?" + re.escape(META_CLOSE),
                   "", body, flags=re.S).strip()

    return {
        "tag": tag,
        "title": rel.get("name") or tag,
        "notes": shown,
        "url": mp3["browser_download_url"],
        "bytes": mp3.get("size") or meta.get("bytes") or 0,
        "duration": meta.get("duration", 0),
        "published": when,
        "item_count": meta.get("item_count", 0),
        "sources": meta.get("sources", []),
    }


# ==========================================================================
# The feed
# ==========================================================================

def build_feed(cfg: dict, episodes: list[dict]) -> str:
    site = cfg["site"].rstrip("/") + "/"
    feed_url = site + "feed.xml"
    cover = site + "cover.png"
    now = datetime.now(timezone.utc)

    def esc(s):
        return escape(str(s or ""))

    owner_block = ""
    if cfg.get("email"):
        owner_block = (
            "    <itunes:owner>\n"
            f"      <itunes:name>{esc(cfg['author'])}</itunes:name>\n"
            f"      <itunes:email>{esc(cfg['email'])}</itunes:email>\n"
            "    </itunes:owner>\n"
        )

    head = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{esc(cfg['title'])}</title>
    <link>{esc(site)}</link>
    <description>{esc(cfg['description'])}</description>
    <language>{esc(cfg['language'])}</language>
    <lastBuildDate>{format_datetime(now)}</lastBuildDate>
    <generator>today-in-the-supreme-court</generator>
    <copyright>Reporting credited to each publisher named in the episode.</copyright>
    <atom:link href="{esc(feed_url)}" rel="self" type="application/rss+xml"/>
    <itunes:author>{esc(cfg['author'])}</itunes:author>
    <itunes:summary>{esc(cfg['description'])}</itunes:summary>
    <itunes:subtitle>{esc(cfg['subtitle'])}</itunes:subtitle>
    <itunes:type>episodic</itunes:type>
    <itunes:explicit>{esc(cfg['explicit'])}</itunes:explicit>
    <itunes:image href="{esc(cover)}"/>
    <image>
      <url>{esc(cover)}</url>
      <title>{esc(cfg['title'])}</title>
      <link>{esc(site)}</link>
    </image>
    <itunes:category text="{esc(cfg['category'])}">
      <itunes:category text="{esc(cfg['subcategory'])}"/>
    </itunes:category>
{owner_block}"""

    body = []
    for ep in episodes:
        summary = re.sub(r"[#*`\[\]]|\(https?://[^)]+\)", "", ep["notes"])
        summary = re.sub(r"\n{2,}", "\n\n", summary).strip()
        body.append(f"""    <item>
      <title>{esc(ep['title'])}</title>
      <link>{esc(site)}</link>
      <guid isPermaLink="false">{esc(ep['tag'])}</guid>
      <pubDate>{format_datetime(ep['published'])}</pubDate>
      <description>{esc(summary)}</description>
      <content:encoded><![CDATA[{ep['notes']}]]></content:encoded>
      <enclosure url="{esc(ep['url'])}" length="{int(ep['bytes'])}" type="audio/mpeg"/>
      <itunes:duration>{fmt_duration(ep['duration'])}</itunes:duration>
      <itunes:explicit>{esc(cfg['explicit'])}</itunes:explicit>
      <itunes:episodeType>full</itunes:episodeType>
      <itunes:image href="{esc(cover)}"/>
    </item>""")

    return head + "\n".join(body) + "\n  </channel>\n</rss>\n"


def write_feed(cfg: dict, limit: int) -> Path:
    require(cfg, "owner", "repo", "site")
    releases = fetch_releases(cfg)
    episodes = [e for e in (parse_release(r) for r in releases) if e]
    episodes.sort(key=lambda e: e["published"], reverse=True)
    episodes = episodes[:limit]

    PUBLIC.mkdir(exist_ok=True)
    xml = build_feed(cfg, episodes)
    out = PUBLIC / "feed.xml"
    out.write_text(xml, encoding="utf-8")

    for name in ("cover.png", "cover-600.png"):
        src = ASSETS / name
        if src.exists():
            shutil.copy2(src, PUBLIC / name)

    print(f"{out}  ({len(episodes)} episode(s))")
    for e in episodes[:5]:
        print(f"  {e['published'].strftime('%Y-%m-%d %H:%M')}  "
              f"{fmt_duration(e['duration']):>7}  {e['title']}")
    if len(episodes) > 5:
        print(f"  ... and {len(episodes) - 5} more")
    if not episodes:
        print("  (no releases tagged ep-* yet; the feed is valid but empty)")
    return out


# ==========================================================================
# Validation
# ==========================================================================

def check_feed(cfg: dict) -> int:
    """Check the generated feed against what Apple and Spotify require."""
    path = PUBLIC / "feed.xml"
    if not path.exists():
        sys.exit("No public/feed.xml. Run `podcast.py feed` first.")

    import xml.etree.ElementTree as ET
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
          "atom": "http://www.w3.org/2005/Atom"}
    problems, warnings = [], []

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        sys.exit(f"feed.xml is not well-formed XML: {e}")
    ch = root.find("channel")
    if ch is None:
        sys.exit("feed.xml has no <channel>")

    def txt(tag):
        el = ch.find(tag, ns)
        return (el.text or "").strip() if el is not None else ""

    for tag, label in (("title", "channel title"),
                       ("link", "channel link"),
                       ("description", "channel description"),
                       ("language", "language")):
        if not txt(tag):
            problems.append(f"missing {label}")

    if ch.find("itunes:image", ns) is None:
        problems.append("missing itunes:image (Apple will not accept the feed)")
    if ch.find("itunes:category", ns) is None:
        problems.append("missing itunes:category")
    if ch.find("atom:link", ns) is None:
        warnings.append("no atom:link rel=self (recommended)")
    if ch.find("itunes:owner", ns) is None:
        warnings.append("no itunes:owner email — Apple Podcasts requires one "
                        "to claim the show; set \"email\" in podcast.json")

    items = ch.findall("item")
    if not items:
        warnings.append("feed has no episodes yet")

    seen_guids = set()
    for i, it in enumerate(items, 1):
        where = f"item {i}"
        enc = it.find("enclosure")
        if enc is None:
            problems.append(f"{where}: no <enclosure>")
        else:
            if not enc.get("url"):
                problems.append(f"{where}: enclosure has no url")
            if not (enc.get("length") or "").isdigit() or enc.get("length") == "0":
                problems.append(f"{where}: enclosure length must be the byte size")
            if enc.get("type") != "audio/mpeg":
                problems.append(f"{where}: enclosure type should be audio/mpeg")
        guid = it.find("guid")
        if guid is None or not (guid.text or "").strip():
            problems.append(f"{where}: missing guid")
        elif guid.text in seen_guids:
            problems.append(f"{where}: duplicate guid {guid.text}")
        else:
            seen_guids.add(guid.text)
        if it.find("pubDate") is None:
            problems.append(f"{where}: missing pubDate")
        dur = it.find("itunes:duration", ns)
        if dur is None or not (dur.text or "").strip():
            warnings.append(f"{where}: no itunes:duration")

    print(f"feed.xml — {len(items)} episode(s), {path.stat().st_size} bytes")
    for w in warnings:
        print(f"  warning  {w}")
    for p in problems:
        print(f"  PROBLEM  {p}")
    if not problems:
        print("  valid: required elements present for Apple and Spotify")
    return 1 if problems else 0


# ==========================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("episode", help="package the current build for release")
    f = sub.add_parser("feed", help="write public/feed.xml from GitHub Releases")
    f.add_argument("--limit", type=int, default=60,
                   help="how many recent episodes to list (default 60)")
    sub.add_parser("check", help="validate public/feed.xml")

    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == "episode":
        make_episode(cfg)
    elif args.cmd == "feed":
        write_feed(cfg, args.limit)
    elif args.cmd == "check":
        sys.exit(check_feed(cfg))


if __name__ == "__main__":
    main()
