#!/usr/bin/env python3
"""
Source adapters for Today in the Supreme Court.

Design note on copyright
------------------------
Two tiers of source, treated differently on purpose:

  TIER_JUDGMENT  Court judgments and orders, and official government
                 material. Section 52(1)(q) of the Copyright Act 1957
                 puts reproduction of a court judgment outside
                 infringement, so we can summarise these freely.

  TIER_NEWS      Private legal news publishers (LiveLaw, Bar & Bench,
                 SCC Blog and friends). We take the HEADLINE and the
                 LINK only. We never read their article prose into the
                 bulletin. The broadcast line is built from the headline
                 plus our own framing, and every item is credited and
                 linked back on air and on the page.

If you add a source, set its tier honestly. The script generator in
build_bulletin.py enforces the distinction.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Iterable

import feedparser
import requests

IST = timezone(timedelta(hours=5, minutes=30))

TIER_JUDGMENT = "judgment"
TIER_NEWS = "news"

UA = "TodayInTheSupremeCourt/1.0 (+non-commercial legal news digest; contact via repo)"

# --------------------------------------------------------------------------
# Which court is this about?
# --------------------------------------------------------------------------
#
# One classifier, used by every adapter. Earlier versions let each adapter
# decide for itself and the rules drifted apart: only one of them checked
# for High Courts, so a Karnataka High Court story reached air through
# another. Anything that decides what belongs in a Supreme Court bulletin
# lives here and nowhere else.

SC_HINTS = re.compile(
    r"\b(supreme court|apex court|constitution bench|cji|"
    r"chief justice of india|supremecourt)\b", re.I,
)
HC_HINTS = re.compile(r"\b(high court|highcourt|hc)\b", re.I)

SUPREME, HIGH, UNKNOWN = "supreme", "high", "unknown"


def _normalise(*parts: str) -> str:
    """
    Flatten text and URLs into one comparable string.

    URLs separate words with hyphens and underscores, so "supreme court"
    never matched ".../supreme-court/..." and the URL argument was silently
    doing nothing at all. Turning separators into spaces makes the same
    vocabulary work on both.
    """
    blob = " ".join(p or "" for p in parts)
    return re.sub(r"[-_/]+", " ", blob)


def which_court(title: str, link: str = "", feed_url: str = "") -> str:
    """
    Classify a story as SUPREME, HIGH or UNKNOWN.

    The headline decides. A publisher's Supreme Court feed is only
    consulted when the headline names no court at all, because feeds get
    mis-filed: Verdictum's Supreme Court feed carried "No Vested Right To
    Choose Investigating Officer: Karnataka High Court Dismisses Plea
    Against ED", and trusting the feed's name over the headline put a High
    Court order into a Supreme Court bulletin.

    Never pass article body text here. Judgments cite the Supreme Court
    constantly; the citation is not the court that decided the case.
    """
    head = _normalise(title)
    sc_in_head = bool(SC_HINTS.search(head))
    hc_in_head = bool(HC_HINTS.search(head))

    # "Supreme Court criticises AP High Court" names both, and is ours.
    if sc_in_head:
        return SUPREME
    if hc_in_head:
        return HIGH

    # Headline names no court. Fall back to where it was published.
    where = _normalise(link, feed_url)
    if SC_HINTS.search(where):
        return SUPREME
    if HC_HINTS.search(where):
        return HIGH
    return UNKNOWN


def is_for_bulletin(title: str, link: str = "", feed_url: str = "") -> bool:
    """The single admission test. Only Supreme Court stories get in."""
    return which_court(title, link, feed_url) == SUPREME


@dataclass
class Item:
    """One thing the bulletin will read out."""
    headline: str
    link: str
    source_name: str
    source_url: str
    tier: str
    published: str | None = None          # ISO 8601
    summary: str = ""                     # only ever populated for TIER_JUDGMENT
    bench: str = ""
    citation: str = ""                    # e.g. "2026 INSC 950"
    extras: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


# Neutral citations turn up inside article slugs on several sites, in the
# form ".../something-2026-insc-950-more-slug". They are worth digging out:
# a listener can note "2026 INSC 950" and pull the judgment later.
INSC_RE = re.compile(r"\b(\d{4})[-\s]?insc[-\s]?(\d{1,5})\b", re.I)


def extract_citation(*texts: str) -> str:
    for t in texts:
        m = INSC_RE.search(t or "")
        if m:
            return f"{m.group(1)} INSC {m.group(2)}"
    return ""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> requests.Response | None:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code == 200 and r.content:
            return r
    except Exception:
        return None
    return None


def _parse_feed(url: str):
    r = _get(url)
    if r is None:
        return None
    parsed = feedparser.parse(r.content)
    if parsed.bozo and not parsed.entries:
        return None
    return parsed


def _entry_date(e) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        v = getattr(e, key, None)
        if v:
            return datetime.fromtimestamp(time.mktime(v), tz=timezone.utc).isoformat()
    return None


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------

def harvest(source: "Source", urls: list[str], limit: int,
            want_summary: bool = False) -> list[Item]:
    """
    Walk EVERY candidate feed for a source and merge the results.

    The first-match-wins version of this was a bug: Verdictum's Supreme
    Court feed carries about two entries while its general feed carries
    twelve, so stopping at the first URL that returned anything meant
    taking the two and never looking at the twelve. Publishers split their
    output across several narrow feeds, so merging is the right default.

    Admission is decided by which_court() for every source alike. There is
    deliberately no per-adapter override: letting each adapter filter for
    itself is how a Karnataka High Court order once reached a Supreme Court
    bulletin.
    """
    seen: set[str] = set()
    out: list[Item] = []
    for url in urls:
        parsed = _parse_feed(url)
        if not parsed or not parsed.entries:
            continue
        for e in parsed.entries:
            title = _clean(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            if not title:
                continue
            key = (link or title).strip().lower()
            if key in seen:
                continue
            if not is_for_bulletin(title, link, url):
                continue
            summary = _clean(getattr(e, "summary", ""))
            seen.add(key)
            out.append(Item(
                headline=title,
                link=link,
                source_name=source.name,
                source_url=source.homepage,
                tier=source.tier,
                published=_entry_date(e),
                citation=extract_citation(link, title),
                summary=summary[:600] if want_summary else "",
            ))
            if len(out) >= limit:
                return out
    return out


class Source:
    name = "abstract"
    homepage = ""
    tier = TIER_NEWS
    candidates: list[str] = []

    def fetch(self, limit: int = 12) -> list[Item]:
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        """
        Report every candidate that answers, not just the first.

        Worth seeing all of them: a publisher's court-specific feed is
        often much thinner than its general one, and the counts are what
        tell you whether the bulletin is drawing on the fuller feed.
        """
        live = []
        for url in self.candidates:
            parsed = _parse_feed(url)
            if parsed is None:
                continue
            n = len(parsed.entries)
            if n:
                live.append(f"{url} -> {n}")
        if live:
            return True, "; ".join(live)
        return False, "no candidate feed returned entries"


class IndianKanoonSupremeCourt(Source):
    """
    Indian Kanoon's per-court feed for the Supreme Court.

    Heads up: as of the last check this feed parsed as valid RSS but
    carried ZERO items, while the all-courts feed was healthy. It is kept
    first in the chain because when it works it is the best source we
    have - actual judgments, tier JUDGMENT - but the pipeline must not
    depend on it. Run `--check-sources` before trusting it.
    """
    name = "Indian Kanoon (Supreme Court)"
    homepage = "https://indiankanoon.org/"
    tier = TIER_JUDGMENT
    candidates = [
        "https://indiankanoon.org/feeds/latest/supremecourt/",
        "https://indiankanoon.org/feeds/latest/scorders/",
    ]

    def fetch(self, limit: int = 12) -> list[Item]:
        out: list[Item] = []
        for url in self.candidates:
            parsed = _parse_feed(url)
            if not parsed or not parsed.entries:
                continue
            for e in parsed.entries[:limit]:
                title = _clean(getattr(e, "title", ""))
                if not title:
                    continue
                out.append(Item(
                    headline=title,
                    link=getattr(e, "link", ""),
                    source_name=self.name,
                    source_url=self.homepage,
                    tier=TIER_JUDGMENT,
                    published=_entry_date(e),
                    summary=_clean(getattr(e, "summary", ""))[:600],
                ))
            if out:
                break
        return out[:limit]


class IndianKanoonAllCourts(Source):
    """All-courts judgments feed, filtered down to Supreme Court items."""
    name = "Indian Kanoon"
    homepage = "https://indiankanoon.org/"
    tier = TIER_JUDGMENT
    candidates = ["https://indiankanoon.org/feeds/latest/judgments/"]

    def fetch(self, limit: int = 12) -> list[Item]:
        parsed = _parse_feed(self.candidates[0])
        if not parsed:
            return []
        out = []
        for e in parsed.entries:
            title = _clean(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            summary = _clean(getattr(e, "summary", ""))
            # The feed mixes every court together and the item title does
            # not name the court, so look for the signal in the body.
            if not is_for_bulletin(title, link):
                continue
            out.append(Item(
                headline=title,
                link=link,
                source_name=self.name,
                source_url=self.homepage,
                tier=TIER_JUDGMENT,
                published=_entry_date(e),
                summary=summary[:600],
            ))
            if len(out) >= limit:
                break
        return out


class LiveLaw(Source):
    name = "LiveLaw"
    homepage = "https://www.livelaw.in/"
    tier = TIER_NEWS
    # NEEDS ATTENTION. None of these are confirmed: /rss/top-stories
    # returned 404 and /feed/ returned 500 on the last check. LiveLaw may
    # simply be refusing non-browser clients, so the 500 could be the
    # User-Agent rather than the path. If LiveLaw shows DEAD in
    # --check-sources, open the site and look for the feed link in the page
    # source, then put the working URL at the top of this list. The other
    # three publishers cover the same ground meanwhile.
    candidates = [
        "https://www.livelaw.in/rss/supreme-court",
        "https://www.livelaw.in/rss/top-stories",
        "https://www.livelaw.in/rss.xml",
        "https://www.livelaw.in/feed/",
    ]

    def fetch(self, limit: int = 12) -> list[Item]:
        return harvest(self, self.candidates, limit)


class BarAndBench(Source):
    name = "Bar & Bench"
    homepage = "https://www.barandbench.com/"
    tier = TIER_NEWS
    candidates = [
        "https://www.barandbench.com/feed",           # verified
        "https://www.barandbench.com/rss",
        "https://www.barandbench.com/news/rss",
    ]

    def fetch(self, limit: int = 12) -> list[Item]:
        return harvest(self, self.candidates, limit)


class Verdictum(Source):
    """
    Verdictum's Supreme Court desk. Worth keeping near the top of the
    registry: it covers the Court only, so nothing has to be filtered out,
    and its article slugs usually carry the INSC neutral citation.
    """
    name = "Verdictum"
    homepage = "https://www.verdictum.in/"
    tier = TIER_NEWS
    # /feed is VERIFIED working (all courts, 12 entries) - the SC-specific
    # path is tried first on the chance it exists, and the adapter applies
    # the Supreme Court filter whenever it falls through to a general feed.
    candidates = [
        "https://www.verdictum.in/rss/supreme-court",
        "https://www.verdictum.in/feed",              # verified
        "https://www.verdictum.in/rss",
    ]

    def fetch(self, limit: int = 12) -> list[Item]:
        return harvest(self, self.candidates, limit)


class SCCBlog(Source):
    name = "SCC Online Blog"
    homepage = "https://www.scconline.com/blog/"
    tier = TIER_NEWS
    candidates = [
        "https://www.scconline.com/blog/category/supreme-court/feed/",
        "https://www.scconline.com/blog/feed/",       # verified
    ]

    def fetch(self, limit: int = 12) -> list[Item]:
        return harvest(self, self.candidates, limit)


# Order matters: judgment-tier sources first, news-tier as enrichment.
#
# Indian Kanoon is deliberately NOT in this list. Its per-court Supreme
# Court feeds return zero entries, and its all-courts feed - which does
# work, with about 20 entries - carries no court anywhere in the entry:
# not in the title ("Harendra vs The State Of Madhya Pradesh on 20 August,
# 2026"), not in the link (/doc/3557904/), and it publishes no category or
# tag fields at all. The only court signal is inside the judgment text,
# and that is precisely the signal that cannot be trusted, because every
# judgment cites the Supreme Court.
#
# Running the filter over that feed passed exactly one entry out of twenty,
# and that one was a High Court judgment citing a Supreme Court precedent.
# A bulletin that announces High Court cases as Supreme Court judgments is
# worse than a bulletin without judgment-tier sources, so the adapters stay
# in this file, importable and ready, but out of the default rotation.
#
# To bring judgment-tier content back, the options are: Indian Kanoon's
# authenticated API, which does expose the court as a field; the eSCR /
# Digital Supreme Court Reports service at digiscr.sci.gov.in; or resolving
# each Indian Kanoon doc page to read its court, at the cost of one
# request per item.
DISABLED: list[Source] = [
    IndianKanoonSupremeCourt(),
    IndianKanoonAllCourts(),
]

REGISTRY: list[Source] = [
    Verdictum(),
    LiveLaw(),
    BarAndBench(),
    SCCBlog(),
]


# Two headlines about the same judgment share most of their distinctive
# words even when the publishers phrase them differently, so compare
# content words rather than whole strings.
_STOP = set("""
a an and are as at be by for from has have in is it its of on or that the to
was were will with supreme court india judgment order says said not can cant
must after against under over while when what which who whose
""".split())


def _fingerprint(headline: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", headline.lower())
    return frozenset(w for w in words if len(w) > 3 and w not in _STOP)


def _is_duplicate(item: Item, seen: list[tuple[frozenset[str], str]]) -> bool:
    """
    Has this story already gone in, under another masthead?

    A shared neutral citation is conclusive. Failing that, compare
    distinctive words.

    The thresholds below are calibrated against real headlines rather than
    guessed. Two newsrooms writing up the same judgment phrase it quite
    differently - the same RBI co-operative bank ruling scored 0.50 across
    two mastheads, and an NDPS vehicle-disposal ruling 0.44 - while eight
    genuinely distinct Supreme Court stories from one day peaked at 0.08
    against each other. That leaves a wide gap, so 0.35 separates them
    cleanly without being anywhere near the false-positive range.
    """
    fp = _fingerprint(item.headline)
    cite = (item.citation or "").strip().upper()

    for other_fp, other_cite in seen:
        if cite and other_cite and cite == other_cite:
            return True
        if not fp or not other_fp:
            continue
        shared = fp & other_fp
        overlap = len(shared) / min(len(fp), len(other_fp))
        if overlap >= 0.35 and len(shared) >= 4:
            return True
    return False


def collect(limit: int = 8, per_source_cap: int | None = None,
            prefer_judgments: bool = True) -> list[Item]:
    """
    Gather up to `limit` items spread across as many publishers as possible.

    The naive version of this drained each source in turn, which meant the
    first feed to answer filled the whole bulletin and everything after it
    was ignored. Instead: pull a batch from every live source, then deal
    them out round-robin, so a five-item edition sourced from three
    publishers credits three publishers.

    `per_source_cap` bounds how much any one source can contribute. It
    defaults to roughly an even share, with a floor of two so a bulletin
    built from only one or two live feeds still fills up.
    """
    order = REGISTRY
    if prefer_judgments:
        order = sorted(REGISTRY, key=lambda s: 0 if s.tier == TIER_JUDGMENT else 1)

    # --- gather from everything that is alive ---------------------------
    pools: list[tuple[Source, list[Item]]] = []
    for src in order:
        try:
            items = src.fetch(limit=limit)
        except Exception as exc:      # a dead source must never kill the build
            print(f"  ! {src.name}: {exc}")
            continue
        if items:
            pools.append((src, items))
            print(f"  + {src.name}: {len(items)} available")
        else:
            print(f"  - {src.name}: no items")

    if not pools:
        return []

    # An explicit cap is an instruction and is honoured even if that leaves
    # the bulletin short. A derived one is only a balancing hint, so the
    # top-up pass below may exceed it rather than air a half-empty edition.
    strict_cap = per_source_cap is not None
    if per_source_cap is None:
        per_source_cap = max(2, -(-limit // max(len(pools), 1)))

    # --- deal round-robin ----------------------------------------------
    picked: list[Item] = []
    seen: list[tuple[frozenset[str], str]] = []
    taken = {src.name: 0 for src, _ in pools}
    cursors = {src.name: 0 for src, _ in pools}

    progress = True
    while len(picked) < limit and progress:
        progress = False
        for src, items in pools:
            if len(picked) >= limit:
                break
            if taken[src.name] >= per_source_cap:
                continue
            i = cursors[src.name]
            while i < len(items):
                cand = items[i]
                i += 1
                if _is_duplicate(cand, seen):
                    continue
                picked.append(cand)
                seen.append((_fingerprint(cand.headline),
                             (cand.citation or '').strip().upper()))
                taken[src.name] += 1
                progress = True
                break
            cursors[src.name] = i

    # --- if the cap left us short, top up from whoever has more ---------
    if len(picked) < limit and not strict_cap:
        for src, items in pools:
            for cand in items[cursors[src.name]:]:
                if len(picked) >= limit:
                    break
                if _is_duplicate(cand, seen):
                    continue
                picked.append(cand)
                seen.append((_fingerprint(cand.headline),
                             (cand.citation or '').strip().upper()))
                taken[src.name] += 1

    spread = ", ".join(f"{n}×{c}" for n, c in taken.items() if c)
    print(f"  = {len(picked)} items across {sum(1 for c in taken.values() if c)} "
          f"source(s): {spread}")
    return picked


def check_all() -> None:
    print("Source health check\n" + "-" * 60)
    for src in REGISTRY:
        ok, detail = src.health()
        print(f"{'OK  ' if ok else 'DEAD'}  {src.name:<34} {detail}")


if __name__ == "__main__":
    check_all()
