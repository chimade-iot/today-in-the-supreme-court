#!/usr/bin/env python3
"""
Today in the Supreme Court - daily bulletin builder.

    python3 build_bulletin.py                 # fetch live, build bulletin
    python3 build_bulletin.py --check-sources # which feeds are alive today
    python3 build_bulletin.py --sample        # build from the bundled sample
    python3 build_bulletin.py --dry-run       # print the script, make no audio

Outputs into public/:
    bulletin.mp3    the broadcast
    bulletin.json   cue points, per-item credits and links, disclaimer

The player reads bulletin.json to drive the source marquee, so the credit
on screen always matches the item being spoken.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import sources
from sources import Item, TIER_JUDGMENT, TIER_NEWS

# Windows still defaults stdout to a legacy codepage, so printing a headline
# that contains a rupee sign or an en dash raises UnicodeEncodeError before
# the bulletin ever gets built. Nudge the stream to UTF-8 where we can.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
PUBLIC = ROOT / "public"
WORK = ROOT / ".work"
VOICES = ROOT / "voices"

IST = timezone(timedelta(hours=5, minutes=30))

# Gaps, in seconds.
LEAD_IN = 2.0          # bed + sting play alone before the first word
GAP_AFTER_INTRO = 0.65
GAP_BETWEEN_ITEMS = 0.5
GAP_BEFORE_SIGNOFF = 0.8
TAIL = 3.2             # bed runs on under the outro

MAX_ITEMS = 8


# ==========================================================================
# 1. Turning legal headlines into something a broadcaster can read
# ==========================================================================

# Order matters. Longer and more specific patterns first, because
# "SC/ST" must not be mangled by the rule that expands a bare "SC".
SPEECH_RULES: list[tuple[str, str]] = [
    (r"\bSC/ST\b", "Scheduled Caste and Scheduled Tribe"),
    (r"\bSC & ST\b", "Scheduled Caste and Scheduled Tribe"),
    # "ST certificate" means Scheduled Tribe, not the Supreme Court, so this
    # has to fire before the bare SC/ST rules below.
    (r"\bST\s+(certificate|category|community|candidate|status|quota)\b",
     r"Scheduled Tribe \1"),
    (r"\bSC\s+(certificate|category|community|candidate|status|quota)\b",
     r"Scheduled Caste \1"),
    (r"\bOBC\b", "O.B.C."),
    # Indian money reads as "425 crore rupees", never "rupees 425 crore".
    (r"₹\s?([\d,.]+)[\s-]?crores?\b", r"\1 crore rupees"),
    (r"₹\s?([\d,.]+)[\s-]?lakhs?\b", r"\1 lakh rupees"),
    (r"₹\s?([\d,.]+)", r"\1 rupees"),
    (r"\bRs\.?\s?([\d,.]+)[\s-]?crores?\b", r"\1 crore rupees"),
    (r"\bRs\.?\s?([\d,.]+)[\s-]?lakhs?\b", r"\1 lakh rupees"),
    (r"\bRs\.?\s?([\d,.]+)", r"\1 rupees"),
    (r"\bu/s\b", "under Section"),
    (r"\bU/[Ss]\b", "under Section"),
    # Section numbers carry letter suffixes: 36AAA, 138, 482.
    (r"\bS\.?\s?(\d+[A-Z]*)\b", r"Section \1"),
    (r"\bSec\.?\s?(\d+[A-Z]*)\b", r"Section \1"),
    (r"\bArt\.?\s?(\d+[A-Z]*)\b", r"Article \1"),
    (r"\bArts\.?\s?(\d+)\b", r"Articles \1"),
    (r"\bO\.\s?(\d+)\s?R\.\s?(\d+)\b", r"Order \1 Rule \2"),
    (r"\bW\.?P\.?\b", "Writ Petition"),
    (r"\bSLP\b", "Special Leave Petition"),
    (r"\bPIL\b", "Public Interest Litigation"),
    (r"\bFIR\b", "First Information Report"),
    (r"\bCJI\b", "Chief Justice of India"),
    (r"\bJ\.\s", "Justice "),
    (r"\bJJ\.\s", "Justices "),
    (r"\bvs\.?\b", "versus"),
    (r"\bv\.\s", "versus "),
    (r"\bOrs\.?\b", "Others"),
    (r"\bAnr\.?\b", "Another"),
    (r"\bUOI\b", "Union of India"),
    (r"\bIPC\b", "the Indian Penal Code"),
    (r"\bCrPC\b", "the Criminal Procedure Code"),
    (r"\bCr\.?P\.?C\.?\b", "the Criminal Procedure Code"),
    (r"\bBNSS\b", "the Bharatiya Nagarik Suraksha Sanhita"),
    (r"\bBNS\b", "the Bharatiya Nyaya Sanhita"),
    (r"\bBSA\b", "the Bharatiya Sakshya Adhiniyam"),
    (r"\bNI Act\b", "the Negotiable Instruments Act"),
    (r"\bPMLA\b", "the Prevention of Money Laundering Act"),
    (r"\bIBC\b", "the Insolvency and Bankruptcy Code"),
    (r"\bCPC\b", "the Civil Procedure Code"),
    (r"\bNDPS\b", "the N.D.P.S. Act"),
    (r"\bUAPA\b", "the U.A.P.A."),
    (r"\bPOCSO\b", "POCSO"),
    (r"\bED\b", "the Enforcement Directorate"),
    (r"\bCBI\b", "the C.B.I."),
    (r"\bNCLT\b", "the N.C.L.T."),
    (r"\bNCLAT\b", "the N.C.L.A.T."),
    (r"\bUGC\b", "the U.G.C."),
    (r"\bGST\b", "G.S.T."),
    (r"\bHC\b", "High Court"),
    (r"\bSC\b", "Supreme Court"),
    (r"\bAP [Hh]igh [Cc]ourt\b", "the Andhra Pradesh High Court"),
    (r"\bMP [Hh]igh [Cc]ourt\b", "the Madhya Pradesh High Court"),
    (r"\bUP\b", "Uttar Pradesh"),
    (r"\bDMK\b", "D.M.K."),
    (r"\s*&\s*", " and "),
]


def speechify(text: str) -> str:
    """Expand legal shorthand so the TTS voice reads it like a human would."""
    out = text
    for pattern, repl in SPEECH_RULES:
        out = re.sub(pattern, repl, out)
    # Strip scare quotes, which the synthesiser sometimes voices - but only
    # the ones sitting at a word boundary, so "can't" and "Mayor's" survive.
    out = re.sub(r"[“”]", "", out)
    out = re.sub(r"(?<![A-Za-z])['‘’\"](?=[A-Za-z])", "", out)   # opening
    out = re.sub(r"(?<=[A-Za-z])['‘’\"](?![A-Za-z])", "", out)   # closing
    out = re.sub(r"(?<![A-Za-z])['‘’\"](?![A-Za-z])", "", out)   # stray
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    # Piper handles sentence breaks better than mid-line colons.
    out = out.replace(" : ", ". ").replace(": ", ". ")
    out = re.sub(r"\.{2,}", ".", out)
    out = re.sub(r"(^|(?<![A-Z])[.!?]\s+)([a-z])",
                 lambda m: m.group(1) + m.group(2).upper(), out)
    return _restore_proper(out.strip())


# Institution names that must keep their capitals even though their component
# words are ordinary ones. Applied last, so nothing upstream has to be careful.
PROPER_PHRASES = [
    (r"\bsupreme court\b", "Supreme Court"),
    (r"\bhigh court\b", "High Court"),
    (r"\bdistrict court\b", "District Court"),
    (r"\bconstitution bench\b", "Constitution Bench"),
    (r"\bchief justice\b", "Chief Justice"),
    (r"\bunion of india\b", "Union of India"),
    (r"\bcentral government\b", "Central Government"),
    (r"\bstate government\b", "State Government"),
    (r"\benforcement directorate\b", "Enforcement Directorate"),
]

# Capitalisation does not change pronunciation, but --dry-run is how you
# proof the bulletin before it airs, so put the place names back.
PLACES = ("andhra pradesh|arunachal pradesh|assam|bihar|chhattisgarh|goa|gujarat|"
          "haryana|himachal pradesh|jharkhand|karnataka|kerala|madhya pradesh|"
          "maharashtra|manipur|meghalaya|mizoram|nagaland|odisha|punjab|rajasthan|"
          "sikkim|tamil nadu|telangana|tripura|uttar pradesh|uttarakhand|"
          "west bengal|delhi|mumbai|bengaluru|bangalore|chennai|kolkata|hyderabad|"
          "ahmedabad|pune|jaipur|lucknow|india|indian|parliament|centre")
PROPER_PHRASES.append(
    (r"\b(" + PLACES + r")\b",
     lambda m: " ".join(w.capitalize() for w in m.group(1).split()))
)


def _restore_proper(s: str) -> str:
    for pattern, repl in PROPER_PHRASES:
        s = re.sub(pattern, repl, s, flags=re.I)
    return s


def _is_title_case(s: str) -> bool:
    """True if most substantial words are capitalised, i.e. a headline."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\u2019]*", s) if len(w) > 2]
    if len(words) < 4:
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.6


def _decap(s: str) -> str:
    """
    Headlines arrive Title Cased Like This, which makes the synthesiser
    stress every single word. Drop the line to sentence case.

    Only acronyms need protecting. Capitalisation does not change how a
    proper noun is pronounced, and the running order shows each
    publisher's headline verbatim, so nothing the reader sees depends on
    what happens here - which is why this can be blunt instead of
    maintaining an endless list of words to lower-case.
    """
    if not _is_title_case(s):
        return s
    out = []
    for w in s.split():
        # Split on internal punctuation so "AI-generated" keeps its acronym.
        parts = re.split(r"([-/])", w)
        rebuilt = []
        for part in parts:
            core = re.sub(r"[^A-Za-z]", "", part)
            # "NCTE's" reduces to "NCTEs", which is not all-caps, so test
            # the stem too or possessive acronyms get spoken as words.
            stem = core[:-1] if core[-1:] == "s" else core
            is_acronym = ((core.isupper() and len(core) > 1)
                          or (stem.isupper() and len(stem) > 1))
            if not core or is_acronym:
                rebuilt.append(part)
            else:
                rebuilt.append(part.lower())
        out.append("".join(rebuilt))
    return " ".join(out)


def _lead_lower(s: str) -> str:
    """Lower-case the first letter of a clause, unless it opens an acronym."""
    m = re.match(r"\s*([A-Za-z]+)", s)
    if not m:
        return s
    first = m.group(1)
    if first.isupper() and len(first) > 1:
        return s
    i = m.start(1)
    return s[:i] + first[0].lower() + s[i + 1:]


# Verbs that mean the court decided something.
HOLDING_VERB = re.compile(
    r"\b(holds?|held|gives?|grant(s|ed)?|allow(s|ed)?|reject(s|ed)?|refus(e|es|ed)|"
    r"dismiss(es|ed)?|uphold(s)?|upheld|quash(es|ed)?|set(s)? aside|direct(s|ed)?|"
    r"order(s|ed)?|criticis(e|es|ed)|criticiz(e|es|ed)|object(s|ed)?|clarifi(es|ed)|"
    r"overturn(s|ed)?|revers(es|ed)|acquit(s|ted)?|convict(s|ed)?|remand(s|ed)?|"
    r"modifi(es|ed)|enhanc(es|ed)|confirm(s|ed)|permit(s|ted)?|"
    r"rul(es|ed)|declar(es|ed)|restor(es|ed)|stay(s|ed)?)\b", re.I)

# A headline that ends in a bare court name is using it as a byline.
BARE_COURT = re.compile(r"^(the\s+)?supreme court\.?$", re.I)

# Verbs that mean somebody said something to the court.
REPORTING_VERB = re.compile(
    r"\b(tells?|told|says?|said|asks?|argues?|argued|submits?|submitted|urges?|"
    r"urged|informs?|informed|questions?|seeks?|sought|writes?|wrote|"
    r"responds?|responded|pleads?|contends?)\b", re.I)


def headline_to_line(item: Item) -> str:
    """
    Build the spoken line for one item.

    TIER_NEWS items get headline + credit only - we never voice a
    publisher's article prose. TIER_JUDGMENT items may carry a short
    summary drawn from the judgment itself, which section 52(1)(q)
    puts outside copyright.
    """
    h = item.headline.strip().rstrip(".")

    # Indian legal headlines commonly read "PROPOSITION : Court ACTION".
    # Reversing that into "Court ACTION, holding that PROPOSITION" is how a
    # broadcaster would say it - but only when the right half really is a
    # decision. When somebody is being quoted, keep it as reported speech.
    # Publishers punctuate this separator inconsistently: "A : B", "A: B".
    parts = re.split(r"\s*:\s+", h, maxsplit=1)
    if len(parts) == 2 and len(parts[0].split()) > 2:
        left, right = parts[0].strip(), parts[1].strip()
        if BARE_COURT.match(right):
            # "PROPOSITION : Supreme Court" is a byline, not a sentence.
            # Read it as the holding it actually is.
            body = f"The Supreme Court has held that {_lead_lower(_decap(left))}"
        elif REPORTING_VERB.search(right):
            # Radio convention: flag the quotation explicitly.
            body = f"{_decap(right)}, quote, {_decap(left)}, unquote"
        elif HOLDING_VERB.search(right):
            body = f"{_decap(right)}, holding that {_lead_lower(_decap(left))}"
        else:
            body = f"{_decap(left)}. {_decap(right)}"
    else:
        body = _decap(h)

    line = speechify(body)
    m = re.search(r"[A-Za-z]", line)
    if m:
        i = m.start()
        line = line[:i] + line[i].upper() + line[i + 1:]
    if not line.endswith("."):
        line += "."

    if item.tier == TIER_JUDGMENT and item.summary:
        extra = speechify(_first_sentences(item.summary, 2))
        if extra:
            line += " " + extra

    line += f" That's reported by {item.source_name}."
    return line


def _first_sentences(text: str, n: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]).strip()


# ==========================================================================
# 2. Assembling the running order
# ==========================================================================

def fmt_date(dt: datetime) -> str:
    """
    "Sunday, 6 September 2026".

    Built by hand rather than with strftime("%A, %-d %B %Y"): the dash
    modifier that strips a leading zero is a glibc extension, so it works
    on Linux and macOS and raises ValueError: Invalid format string on
    Windows. (%#d is the Windows spelling, which fails everywhere else.)
    """
    return f"{dt.strftime('%A')}, {dt.day} {dt.strftime('%B')} {dt.year}"


def fmt_datetime(dt: datetime) -> str:
    """"6 September 2026, 11:57 AM IST" - portable, for the same reason."""
    hour12 = dt.hour % 12 or 12
    meridiem = "AM" if dt.hour < 12 else "PM"
    return (f"{dt.day} {dt.strftime('%B')} {dt.year}, "
            f"{hour12}:{dt.minute:02d} {meridiem} IST")


def build_script(items: list[Item], now: datetime) -> list[dict]:
    """
    Produce the ordered list of segments. Each segment is a dict with the
    text to speak plus the metadata the player needs for its marquee.
    """
    day = fmt_date(now)
    hour = now.hour
    greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")

    segments: list[dict] = []

    # Naming the publishers in the opening is how a bulletin credits its
    # desks, and it means the attribution is heard even by someone who
    # never looks at the page.
    names = []
    for it in items:
        if it.source_name not in names:
            names.append(it.source_name)
    if len(names) > 1:
        credit_clause = (
            " Today's edition draws on "
            + ", ".join(names[:-1]) + " and " + names[-1] + "."
        )
    elif names:
        credit_clause = f" Today's edition draws on {names[0]}."
    else:
        credit_clause = ""

    segments.append({
        "kind": "open",
        "text": (
            f"{greeting}. This is Today in the Supreme Court, "
            f"your daily digest of the Supreme Court of India, for {day}."
            f"{credit_clause} "
            f"Here are today's {'stories' if len(items) != 1 else 'story'}."
        ),
        "credit": "Today in the Supreme Court",
        "link": "",
        "source_url": "",
    })

    for i, it in enumerate(items, start=1):
        segments.append({
            "kind": "item",
            "index": i,
            "text": f"{_ordinal_lead(i)} {headline_to_line(it)}",
            "headline": it.headline,
            "credit": it.source_name,
            "link": it.link,
            "source_url": it.source_url,
            "tier": it.tier,
            "citation": it.citation,
            "published": it.published,
        })

    segments.append({
        "kind": "close",
        "text": (
            "That's the bulletin. Every item is linked on the page, and the "
            "full text of any judgment should be read at the primary source "
            "before you rely on it. This digest is generated automatically "
            "and is not legal advice. Today in the Supreme Court will be back "
            "with the next edition."
        ),
        "credit": "Today in the Supreme Court",
        "link": "",
        "source_url": "",
    })
    return segments


def _ordinal_lead(i: int) -> str:
    leads = {
        1: "First.", 2: "Next.", 3: "Third.", 4: "Also today.",
        5: "Fifth.", 6: "Turning on.", 7: "Seventh.", 8: "And finally.",
    }
    return leads.get(i, "Next.")


# ==========================================================================
# 3. Voicing
# ==========================================================================

# Speaking rate for edge-tts. A touch under natural pace suits a news read.
EDGE_RATE = "-4%"


def edge_cmd(text: str, out_path: Path, voice: str) -> list[str]:
    """
    Build an edge-tts command line.

    Note `--rate=-4%` rather than `--rate", "-4%`. edge-tts parses with
    argparse, which reads any token starting with a dash as another flag,
    so the separated form makes it complain about missing arguments and
    exit with status 2 before synthesising anything. The joined form is
    the only one that survives a negative value.
    """
    return [
        "edge-tts",
        f"--rate={EDGE_RATE}",
        "--voice", voice,
        "--text", text,
        "--write-media", str(out_path),
    ]


def pick_voice() -> tuple[str, Path | None]:
    """
    Prefer edge-tts: its neural voices sit closest to a newscaster register.
    It needs to reach Microsoft's endpoint though, so probe it for real
    rather than trusting that the binary is on PATH - behind a restrictive
    egress policy it installs fine and then fails on every call. Piper is
    the fallback and runs entirely offline from a local model.
    """
    if shutil.which("edge-tts"):
        probe = WORK / "probe.mp3"
        WORK.mkdir(exist_ok=True)
        try:
            # Use the real command builder, so a malformed argument is
            # caught here rather than on the first segment of a live build.
            subprocess.run(
                edge_cmd("test", probe, "en-GB-RyanNeural"),
                check=True, capture_output=True, timeout=45,
            )
            if probe.exists() and probe.stat().st_size > 512:
                probe.unlink(missing_ok=True)
                return "edge", None
            print("  edge-tts reachable but produced no audio; using Piper.")
        except Exception:
            print("  edge-tts unreachable (network/egress); using Piper offline.")
        probe.unlink(missing_ok=True)

    model = VOICES / "en-us-ryan-high.onnx"
    if model.exists():
        return "piper", model
    model = next(VOICES.glob("*.onnx"), None)
    if model:
        return "piper", model
    sys.exit(
        "No TTS available. Either allow network access for edge-tts, or "
        "download a Piper voice into voices/ (see README)."
    )


def synth(text: str, out_wav: Path, engine: str, model: Path | None,
          edge_voice: str = "en-GB-RyanNeural") -> float:
    """Speak `text` into out_wav. Returns duration in seconds."""
    if engine == "edge":
        mp3 = out_wav.with_suffix(".edge.mp3")
        run_checked(edge_cmd(text, mp3, edge_voice), "edge-tts")
        run_checked(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3), "-ar", "44100", "-ac", "1",
                     str(out_wav)], "ffmpeg")
        mp3.unlink(missing_ok=True)
    else:
        proc = subprocess.run(
            ["piper", "-m", str(model), "-f", str(out_wav)],
            input=text.encode(), check=True, capture_output=True,
        )
        del proc
        # Piper writes at the model's rate; normalise to 44.1k mono.
        tmp = out_wav.with_suffix(".norm.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out_wav), "-ar", "44100",
                        "-ac", "1", str(tmp)], check=True, capture_output=True)
        tmp.replace(out_wav)
    return probe_duration(out_wav)


def run_checked(cmd: list[str], label: str) -> subprocess.CompletedProcess:
    """
    Run a command, and on failure show what it actually said.

    capture_output swallows stderr, so a bare CalledProcessError tells you
    a command failed but not why - which turns a one-line argument mistake
    into a debugging session. Print the tool's own message instead.
    """
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        out = (proc.stdout or b"").decode("utf-8", "replace").strip()
        print(f"\n  {label} failed (exit {proc.returncode})")
        print(f"  command: {' '.join(cmd[:6])} ...")
        # The last lines, not the first: ffmpeg prints a long build banner
        # before it gets to the actual complaint, and most tools put the
        # error at the end.
        lines = (err or out or "(no output)").splitlines()
        for line in lines[-12:]:
            print(f"    {line}")
        raise SystemExit(
            f"\n{label} could not run. The message above is from {label} "
            f"itself and usually says exactly what is wrong."
        )
    return proc


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


# ==========================================================================
# 4. Mixing
# ==========================================================================

def mix(segment_wavs: list[Path], offsets: list[float], total: float,
        out_mp3: Path) -> None:
    """
    Lay the voice segments on a timeline, loop the bed underneath, duck the
    bed against the voice with a sidechain compressor, and drop the intro
    and outro stings on top.
    """
    WORK.mkdir(exist_ok=True)
    voice = WORK / "voice.wav"

    # --- voice track: each segment delayed to its cue point ---------------
    inputs, filters, labels = [], [], []
    for i, (w, off) in enumerate(zip(segment_wavs, offsets)):
        inputs += ["-i", str(w)]
        filters.append(f"[{i}:a]adelay={int(off*1000)}|{int(off*1000)},"
                       f"apad=whole_dur={total}[v{i}]")
        labels.append(f"[v{i}]")
    filters.append("".join(labels) + f"amix=inputs={len(segment_wavs)}:"
                   f"normalize=0:duration=longest[voice]")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(filters),
         "-map", "[voice]", "-ar", "44100", "-ac", "1", str(voice)],
        check=True, capture_output=True,
    )

    # --- bed + ducking + stings -------------------------------------------
    bed = ASSETS / "bed.wav"
    intro = ASSETS / "intro.wav"
    outro = ASSETS / "outro.wav"
    outro_at = max(0.0, total - probe_duration(outro) - 0.15)

    fc = (
        # loop the bed to cover the whole bulletin, then top and tail it
        f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{total},"
        f"afade=t=in:st=0:d=1.5,afade=t=out:st={total-2.5}:d=2.5,"
        f"volume=0.55[bedraw];"
        # duck the bed whenever the voice is present
        f"[bedraw][0:a]sidechaincompress="
        f"threshold=0.035:ratio=9:attack=12:release=420:makeup=1[bed];"
        f"[2:a]adelay=0|0,volume=0.9[intro];"
        f"[3:a]adelay={int(outro_at*1000)}|{int(outro_at*1000)},volume=0.8[outro];"
        f"[0:a]volume=1.25[v];"
        f"[v][bed][intro][outro]amix=inputs=4:normalize=0:duration=longest,"
        f"alimiter=limit=0.94,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(voice), "-i", str(bed), "-i", str(intro),
         "-i", str(outro), "-filter_complex", fc, "-map", "[out]",
         "-codec:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
         str(out_mp3)],
        check=True, capture_output=True,
    )


# ==========================================================================
# 5. Orchestration
# ==========================================================================

SAMPLE = ROOT / "sample_items.json"


def load_sample() -> list[Item]:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return [Item(**d) for d in data]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the daily SC bulletin.")
    ap.add_argument("--check-sources", action="store_true")
    ap.add_argument("--sample", action="store_true",
                    help="build from sample_items.json instead of the network")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the script and exit without making audio")
    ap.add_argument("--max-items", type=int, default=MAX_ITEMS)
    ap.add_argument("--per-source", type=int, default=None,
                    help="cap on items from any one publisher "
                         "(default: an even share, floor of 2)")
    args = ap.parse_args()

    if args.check_sources:
        sources.check_all()
        return

    now = datetime.now(IST)

    if args.sample:
        items = load_sample()[: args.max_items]
        print(f"Using bundled sample: {len(items)} items")
    else:
        print("Collecting items ...")
        items = sources.collect(limit=args.max_items,
                                per_source_cap=args.per_source)
        if not items:
            print("\nNo live source returned anything.")
            if SAMPLE.exists():
                print("Falling back to the bundled sample so the build still "
                      "produces a bulletin. Run --check-sources to see why.")
                items = load_sample()[: args.max_items]
            else:
                sys.exit(1)

    segments = build_script(items, now)

    if args.dry_run:
        print("\n" + "=" * 70)
        for s in segments:
            print(f"\n[{s['kind']}] ({s.get('credit','')})\n{s['text']}")
        print("\n" + "=" * 70)
        return

    engine, model = pick_voice()
    print(f"Voicing {len(segments)} segments with {engine} ...")

    WORK.mkdir(exist_ok=True)
    for f in WORK.glob("seg_*.wav"):
        f.unlink()

    wavs, offsets, cues = [], [], []
    cursor = LEAD_IN
    for i, seg in enumerate(segments):
        w = WORK / f"seg_{i:02d}.wav"
        dur = synth(seg["text"], w, engine, model)
        wavs.append(w)
        offsets.append(cursor)
        cues.append({
            "start": round(cursor, 3),
            "end": round(cursor + dur, 3),
            "kind": seg["kind"],
            "headline": seg.get("headline", ""),
            "credit": seg.get("credit", ""),
            "link": seg.get("link", ""),
            "source_url": seg.get("source_url", ""),
            "tier": seg.get("tier", ""),
            "citation": seg.get("citation", ""),
            "text": seg["text"],
        })
        cursor += dur
        cursor += (GAP_AFTER_INTRO if seg["kind"] == "open"
                   else GAP_BEFORE_SIGNOFF if i == len(segments) - 2
                   else GAP_BETWEEN_ITEMS)
        print(f"  {i:02d} {seg['kind']:<5} {dur:6.2f}s  {seg.get('credit','')}")

    total = cursor + TAIL
    PUBLIC.mkdir(exist_ok=True)
    out_mp3 = PUBLIC / "bulletin.mp3"
    print(f"Mixing {total:.1f}s ...")
    mix(wavs, offsets, total, out_mp3)

    payload = {
        "title": "Today in the Supreme Court",
        "generated_at": now.isoformat(),
        "generated_at_display": fmt_datetime(now),
        "duration": round(probe_duration(out_mp3), 2),
        "audio": "bulletin.mp3",
        "engine": engine,
        "item_count": len(items),
        "cues": cues,
        "sources": sorted({c["credit"] for c in cues if c.get("link")}),
        "disclaimer": (
            "Automatically generated digest. Not legal advice and not a "
            "substitute for the official record. Headlines and links are "
            "reproduced for reporting purposes with credit to each "
            "publisher; always read the full judgment at the primary "
            "source before relying on it."
        ),
    }
    (PUBLIC / "bulletin.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # public/ is what gets deployed, so the player ships alongside the audio.
    shutil.copy2(ROOT / "index.html", PUBLIC / "index.html")
    # Page assets: the share card link previews fetch, and the favicons.
    # These must sit next to index.html or the og:image URL 404s and the
    # preview silently falls back to a bare link.
    for name in ("social-card.png", "favicon-32.png", "apple-touch-icon.png",
                 "cover-600.png", "cover.png"):
        src = ASSETS / name
        if src.exists():
            shutil.copy2(src, PUBLIC / name)
    (PUBLIC / ".nojekyll").touch()

    print(f"\nDone.  {out_mp3}  ({payload['duration']:.1f}s)")
    print(f"       {PUBLIC / 'bulletin.json'}")
    print(f"       {PUBLIC / 'index.html'}")


if __name__ == "__main__":
    main()
