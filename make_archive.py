#!/usr/bin/env python3
"""
Build the searchable archive.

    python3 make_archive.py              # from GitHub Releases
    python3 make_archive.py --limit 200  # how far back to go

Why this exists
---------------
The podcast reaches people who already know about it. Search reaches the
ones who do not. Lawyers look up case names and neutral citations
constantly, so the most valuable thing this project can put on the open
web is a page per edition carrying its running order as real text - "2026
INSC 955", "Sandeep S Ghandat v. Reserve Bank of India" - indexed and
linkable.

Until now that text existed only inside GitHub release notes and inside
an MP3, neither of which a search engine can use. This writes:

    public/archive/index.html        every edition, filterable in the page
    public/archive/<tag>/index.html  one edition, running order as text
    public/sitemap.xml               so crawlers find all of it
    public/robots.txt

The source of truth is still the release list - nothing here keeps state.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import podcast
from podcast import fmt_duration

ROOT = Path(__file__).parent
PUBLIC = ROOT / "public"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def clock(dt) -> str:
    """
    "1:06 PM" - built by hand, not strftime("%-I:%M %p").

    The dash modifier that strips a leading zero is a glibc extension and
    raises ValueError on Windows. This project already shipped that bug
    once; it is not shipping it twice.
    """
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def e(s) -> str:
    return html.escape(str(s or ""), quote=True)


# ==========================================================================
# Shared stylesheet
# ==========================================================================
# One file rather than inlining into every edition page: thirty copies of
# the same eight kilobytes helps nobody, and a shared sheet is cached after
# the first page a reader opens.

CSS = """/* Today in the Supreme Court - archive
   Same ink, paper and lamp as the player page. */
:root {
  --paper:#f2f3f6; --surface:#fff; --surface-2:#e9ebf0;
  --ink:#141824; --ink-2:#414962; --ink-3:#6d768f;
  --rule:#d3d7e2; --rule-2:#bfc4d3;
  --lamp:#b45309; --judgment:#0f6e63;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper:#0d1119; --surface:#141a25; --surface-2:#1c2432;
    --ink:#eef1f7; --ink-2:#a8b1c6; --ink-3:#767f96;
    --rule:#252e3e; --rule-2:#334054;
    --lamp:#e8a33d; --judgment:#3fb3a2;
  }
}
:root[data-theme="dark"] {
  --paper:#0d1119; --surface:#141a25; --surface-2:#1c2432;
  --ink:#eef1f7; --ink-2:#a8b1c6; --ink-3:#767f96;
  --rule:#252e3e; --rule-2:#334054;
  --lamp:#e8a33d; --judgment:#3fb3a2;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:16px; line-height:1.6;
}
.wrap{max-width:54rem;margin:0 auto;padding:clamp(1.25rem,4vw,2.5rem) clamp(1rem,4vw,2rem) 4rem}
a{color:var(--ink);text-underline-offset:2px}
a:hover{color:var(--lamp)}
.eyebrow{
  font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:.688rem;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3)
}
.top{
  display:flex;flex-wrap:wrap;gap:.75rem 1.25rem;align-items:baseline;
  justify-content:space-between;border-bottom:2px solid var(--ink);
  padding-bottom:1rem;margin-bottom:1.75rem
}
.top a{text-decoration:none}
h1{
  font-family:Newsreader,Georgia,"Times New Roman",serif;font-weight:500;
  font-size:clamp(1.7rem,4.5vw,2.5rem);line-height:1.1;letter-spacing:-.015em;
  margin:.15rem 0 0;text-wrap:balance
}
.sub{color:var(--ink-2);font-size:.938rem;margin:.5rem 0 0}
.tools{display:flex;flex-wrap:wrap;gap:.5rem;margin:1.5rem 0}
.tools input{
  flex:1 1 20rem;min-width:0;font:inherit;font-size:.938rem;
  padding:.6rem .8rem;border:1px solid var(--rule-2);border-radius:3px;
  background:var(--surface);color:var(--ink)
}
.tools input:focus{outline:2px solid var(--lamp);outline-offset:1px}
.count{
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.75rem;
  color:var(--ink-3);align-self:center
}
.ed{border-bottom:1px solid var(--rule);padding:1.15rem 0}
.ed h2{
  font-family:Newsreader,Georgia,serif;font-size:1.25rem;font-weight:500;
  margin:0 0 .3rem;line-height:1.25
}
.ed h2 a{text-decoration:none}
.ed .meta{
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.75rem;
  color:var(--ink-3);font-variant-numeric:tabular-nums;margin-bottom:.5rem
}
.ed ul{margin:.4rem 0 0;padding-left:1.1rem;color:var(--ink-2);font-size:.938rem}
.ed li{margin:.22rem 0;text-wrap:pretty}
mark{background:color-mix(in srgb,var(--lamp) 28%,transparent);color:inherit;border-radius:2px}
.story{border-bottom:1px solid var(--rule);padding:1.35rem 0}
.story h2{
  font-family:Newsreader,Georgia,serif;font-size:1.2rem;font-weight:500;
  line-height:1.35;margin:0;text-wrap:pretty
}
.story .line{
  display:flex;flex-wrap:wrap;gap:.5rem .85rem;align-items:center;
  margin-top:.55rem;font-size:.875rem;color:var(--ink-3)
}
.pub{color:var(--ink-2);font-weight:500}
.cite{
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.75rem;
  color:var(--judgment);border:1px solid color-mix(in srgb,var(--judgment) 35%,transparent);
  padding:.1rem .38rem;border-radius:2px;font-variant-numeric:tabular-nums
}
.at{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.75rem;font-variant-numeric:tabular-nums}
audio{width:100%;margin:1.25rem 0 .25rem}
.note{
  margin-top:2.5rem;padding-top:1rem;border-top:2px solid var(--rule-2);
  font-size:.875rem;color:var(--ink-3);line-height:1.6
}
.note strong{color:var(--ink);font-weight:500}
.pager{display:flex;flex-wrap:wrap;gap:1rem;margin-top:2rem;font-size:.875rem}
.empty{padding:2rem;text-align:center;color:var(--ink-3);border:1px dashed var(--rule-2);border-radius:4px}
@media print{.tools,.pager{display:none}}
"""


def head(title: str, desc: str, canonical: str, site: str, depth: int) -> str:
    """Shared <head>. `depth` is how many levels below the site root."""
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canonical)}">
<link rel="icon" type="image/png" sizes="32x32" href="{up}favicon-32.png">
<link rel="apple-touch-icon" sizes="180x180" href="{up}apple-touch-icon.png">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Today in the Supreme Court">
<meta property="og:locale" content="en_IN">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(site)}social-card.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(site)}social-card.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap">
<link rel="stylesheet" href="{up}archive.css">
<link rel="alternate" type="application/rss+xml"
      title="Today in the Supreme Court" href="{e(site)}feed.xml">
</head>
<body>
<div class="wrap">"""


FOOT = """</div>
</body>
</html>
"""


def disclaimer(site: str) -> str:
    return f"""<p class="note">
<strong>This is not legal advice.</strong> Each edition is generated
automatically from public sources and is no substitute for the official
record &mdash; read the full judgment at the primary source before relying on
it. Every story is credited to the publisher that reported it and linked to
their own page.
</p>
<p class="pager">
<a href="{e(site)}">Listen to today's edition</a>
<a href="{e(site)}archive/">All editions</a>
<a href="{e(site)}feed.xml">RSS feed</a>
</p>"""


# ==========================================================================
# One edition
# ==========================================================================

def episode_page(ep: dict, site: str, cfg: dict, has_audio: bool) -> str:
    when = ep["published"]
    day = f"{when.day} {when.strftime('%B %Y')}"
    title = f"Supreme Court of India &mdash; {day} bulletin"
    plain_title = f"Supreme Court of India - {day} bulletin"
    canonical = f"{site}archive/{ep['tag']}/"
    items = ep.get("items") or []

    heads = [i["headline"] for i in items if i.get("headline")]
    desc = (f"{len(items)} Supreme Court stories, {fmt_duration(ep['duration'])}. "
            + "; ".join(h.rstrip(".") for h in heads[:3]))[:300]

    parts = [head(plain_title, desc, canonical, site, 2)]
    parts.append(f"""
<div class="top">
  <div>
    <span class="eyebrow">Today in the Supreme Court &middot; Archive</span>
    <h1>{title}</h1>
  </div>
  <a class="eyebrow" href="{e(site)}archive/">&larr; All editions</a>
</div>
<p class="sub">
  {len(items)} {"story" if len(items) == 1 else "stories"} &middot;
  {fmt_duration(ep['duration'])} &middot;
  edition of {e(ep['title'])}
  {("&middot; reporting by " + e(", ".join(ep.get("sources", [])))) if ep.get("sources") else ""}
</p>""")

    if has_audio:
        name = ep["url"].rsplit("/", 1)[-1]
        parts.append(f'\n<audio controls preload="none" '
                     f'src="../../episodes/{e(name)}"></audio>')
    else:
        rel = f"https://github.com/{cfg['owner']}/{cfg['repo']}/releases/tag/{ep['tag']}"
        parts.append(f'\n<p class="sub">Audio for this edition is in the '
                     f'<a href="{e(rel)}">release archive</a>.</p>')

    parts.append('\n<div class="eyebrow" style="margin:2rem 0 .25rem">Running order</div>')
    for i, it in enumerate(items, 1):
        headline = e(it.get("headline", ""))
        link = it.get("link", "")
        heading = (f'<a href="{e(link)}" rel="noopener">{headline}</a>'
                   if link else headline)
        bits = [f'<span class="pub">{e(it.get("credit", ""))}</span>']
        if it.get("citation"):
            bits.append(f'<span class="cite">{e(it["citation"])}</span>')
        if it.get("start"):
            bits.append(f'<span class="at">at {fmt_duration(it["start"])}</span>')
        if link:
            host = link.split("//")[-1].split("/")[0].replace("www.", "")
            bits.append(f'<a href="{e(link)}" rel="noopener">read at {e(host)} &rarr;</a>')
        parts.append(f"""
<div class="story">
  <h2>{heading}</h2>
  <div class="line">{"".join(bits)}</div>
</div>""")

    if not items:
        parts.append('\n<p class="empty">No running order recorded for this edition.</p>')

    # Structured data: tells a crawler this is an episode of a series, and
    # which show it belongs to, rather than leaving it to guess.
    ld = {
        "@context": "https://schema.org",
        "@type": "PodcastEpisode",
        "url": canonical,
        "name": plain_title,
        "datePublished": when.isoformat(),
        "timeRequired": f"PT{int(ep['duration'])}S",
        "description": desc,
        "partOfSeries": {
            "@type": "PodcastSeries",
            "name": cfg["title"],
            "url": site,
        },
        "associatedMedia": {
            "@type": "MediaObject",
            "contentUrl": ep["url"],
            "encodingFormat": "audio/mpeg",
        },
    }
    parts.append('\n<script type="application/ld+json">'
                 + json.dumps(ld, ensure_ascii=False) + "</script>")
    parts.append("\n" + disclaimer(site))
    parts.append(FOOT)
    return "".join(parts)


# ==========================================================================
# The index
# ==========================================================================

def index_page(eps: list[dict], site: str, cfg: dict) -> str:
    canonical = f"{site}archive/"
    total_items = sum(len(x.get("items") or []) for x in eps)
    desc = (f"Every edition of Today in the Supreme Court - {len(eps)} "
            f"bulletins covering {total_items} Supreme Court of India "
            f"stories, searchable by case name or citation.")

    parts = [head("Archive - Today in the Supreme Court", desc, canonical, site, 2)]
    parts.append(f"""
<div class="top">
  <div>
    <span class="eyebrow">Today in the Supreme Court</span>
    <h1>Archive</h1>
  </div>
  <a class="eyebrow" href="{e(site)}">&larr; Today's edition</a>
</div>
<p class="sub">
  {len(eps)} editions, {total_items} stories. Type to filter by case name,
  citation, publisher or date &mdash; it searches every headline below.
</p>

<div class="tools">
  <input id="q" type="search" autocomplete="off"
         placeholder="e.g. arbitration, 2026 INSC 955, bail, Verdictum"
         aria-label="Filter editions">
  <span class="count" id="count"></span>
</div>
<div id="list">""")

    for ep in eps:
        when = ep["published"]
        items = ep.get("items") or []
        day = f"{when.day} {when.strftime('%B %Y')}"
        blob = " ".join(
            [day, when.strftime("%A"), ep["title"]]
            + [i.get("headline", "") for i in items]
            + [i.get("credit", "") for i in items]
            + [i.get("citation", "") for i in items]
        )
        lis = "".join(
            f"<li>{e(i.get('headline',''))}"
            + (f' <span class="cite">{e(i["citation"])}</span>' if i.get("citation") else "")
            + "</li>"
            for i in items
        )
        parts.append(f"""
  <div class="ed" data-s="{e(blob.lower())}">
    <h2><a href="{e(ep['tag'])}/">{e(day)} &middot; {e(clock(when))} edition</a></h2>
    <div class="meta">{len(items)} {"story" if len(items)==1 else "stories"}
      &middot; {fmt_duration(ep['duration'])}
      {("&middot; " + e(", ".join(ep.get("sources", [])))) if ep.get("sources") else ""}</div>
    <ul>{lis}</ul>
  </div>""")

    parts.append("""
</div>
<p class="empty" id="none" hidden>Nothing matches that. Try a shorter word,
or a citation like <code>INSC</code>.</p>
""")

    parts.append("""
<script>
(function () {
  var q = document.getElementById("q");
  var eds = [].slice.call(document.querySelectorAll(".ed"));
  var count = document.getElementById("count");
  var none = document.getElementById("none");

  function show(n) {
    count.textContent = n === eds.length
      ? eds.length + " editions"
      : n + " of " + eds.length + " editions";
    none.hidden = n !== 0;
  }

  function run() {
    // Every term has to match, so "bail 2026" narrows rather than widens.
    var terms = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
    var shown = 0;
    eds.forEach(function (ed) {
      var hay = ed.getAttribute("data-s");
      var hit = terms.every(function (t) { return hay.indexOf(t) !== -1; });
      ed.hidden = !hit;
      if (hit) shown++;
    });
    show(shown);
  }

  q.addEventListener("input", run);
  // Allow linking straight to a search: /archive/?q=arbitration
  var pre = new URLSearchParams(location.search).get("q");
  if (pre) { q.value = pre; }
  run();
})();
</script>
""")
    parts.append(disclaimer(site))
    parts.append(FOOT)
    return "".join(parts)


# ==========================================================================
# Crawler plumbing
# ==========================================================================

def write_sitemap(eps: list[dict], site: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [(site, now, "daily", "1.0"), (f"{site}archive/", now, "daily", "0.8")]
    for ep in eps:
        urls.append((f"{site}archive/{ep['tag']}/",
                     ep["published"].strftime("%Y-%m-%d"), "monthly", "0.6"))
    body = "\n".join(
        f"  <url><loc>{e(u)}</loc><lastmod>{d}</lastmod>"
        f"<changefreq>{c}</changefreq><priority>{p}</priority></url>"
        for u, d, c, p in urls
    )
    (PUBLIC / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n", encoding="utf-8")

    (PUBLIC / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {site}sitemap.xml\n",
        encoding="utf-8")


# ==========================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="Build the searchable archive.")
    ap.add_argument("--limit", type=int, default=200,
                    help="how many editions back to publish (default 200)")
    args = ap.parse_args()

    cfg = podcast.load_config()
    podcast.require(cfg, "owner", "repo", "site")
    site = cfg["site"].rstrip("/") + "/"

    releases = podcast.fetch_releases(cfg, limit=100)
    eps = [x for x in (podcast.parse_release(r) for r in releases) if x]
    eps.sort(key=lambda x: x["published"], reverse=True)
    eps = eps[: args.limit]

    if not eps:
        print("No editions found; nothing to archive.")
        return

    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "archive").mkdir(exist_ok=True)
    (PUBLIC / "archive.css").write_text(CSS, encoding="utf-8")

    episodes_dir = PUBLIC / "episodes"
    recovered = 0
    for ep in eps:
        name = ep["url"].rsplit("/", 1)[-1].split("?")[0]
        has_audio = (episodes_dir / name).exists()
        d = PUBLIC / "archive" / ep["tag"]
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(
            episode_page(ep, site, cfg, has_audio), encoding="utf-8")
        if ep.get("items"):
            recovered += len(ep["items"])

    (PUBLIC / "archive" / "index.html").write_text(
        index_page(eps, site, cfg), encoding="utf-8")
    write_sitemap(eps, site)

    print(f"archive: {len(eps)} editions, {recovered} stories indexed")
    print(f"  {PUBLIC / 'archive' / 'index.html'}")
    print(f"  {PUBLIC / 'archive'}/<tag>/index.html  x{len(eps)}")
    print(f"  {PUBLIC / 'sitemap.xml'}  and robots.txt")


if __name__ == "__main__":
    main()
