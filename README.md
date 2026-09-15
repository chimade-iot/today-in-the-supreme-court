# Today in the Supreme Court

A free daily audio bulletin of the Supreme Court of India, for the legal
fraternity. One page, one play button, a broadcaster-style read over a
music bed, and every source credited on air and on screen.

Static site, no server, no cost. GitHub Actions builds the bulletin twice a
day and GitHub Pages serves it.

---

## How it works

```
feeds ──▶ build_bulletin.py ──▶ script + cue sheet ──▶ TTS ──▶ ffmpeg mix
                                                                    │
                                              public/bulletin.mp3 ◀─┘
                                              public/bulletin.json
                                              public/index.html
```

`bulletin.json` carries a cue point for every segment, so the player knows
exactly which story is being spoken at any moment. That is what drives the
credit ticker along the bottom of the page and the highlight in the running
order — the source on screen always matches the source in your ear.

## Quick start

```bash
pip install -r requirements.txt
sudo apt-get install ffmpeg        # or: brew install ffmpeg

python3 make_bed.py                # synthesise the music bed (once)
python3 build_bulletin.py          # fetch, voice, mix
cd public && python3 -m http.server 8000
```

Then open http://localhost:8000.

Useful flags:

| Command | What it does |
|---|---|
| `build_bulletin.py --check-sources` | which feeds are alive right now |
| `build_bulletin.py --dry-run` | print the script, make no audio |
| `build_bulletin.py --sample` | build from `sample_items.json`, no network |
| `build_bulletin.py --max-items 5` | shorter edition |
| `build_bulletin.py --per-source 2` | cap any one publisher at two items |
| `make_preview.py` | fold everything into one shareable `preview.html` |
| `podcast.py episode` | package the current build as an episode |
| `podcast.py feed` | mirror recent episodes onto the site and regenerate `feed.xml` |
| `podcast.py feed --window 60` | host and list 60 editions instead of 30 |
| `podcast.py check` | validate the feed against the podcast spec |
| `make_cover.py` | redraw the podcast cover art |

## Deploying

1. Push this repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions.**
3. **Actions tab → "Build and publish the daily bulletin" → Run workflow**
   to build the first edition immediately.

After that it runs itself at 07:30 and 18:30 IST, Monday to Saturday. Edit
the `cron` lines in `.github/workflows/daily.yml` to change that — they are
in UTC.

## The voice

Two engines, tried in that order:

- **edge-tts** — free, no account, no API key, and the closest thing to a
  newscaster register. Needs to reach Microsoft's endpoint. This is what
  runs in GitHub Actions.
- **Piper** — fully offline, from a local `.onnx` model. The fallback when
  there is no network, and what you want if you ever move this off Actions.

`build_bulletin.py` probes edge-tts for real rather than trusting that the
binary exists, because behind a restrictive network it installs happily and
then fails on every call.

To set up Piper locally:

```bash
pip install piper-tts
mkdir -p voices && cd voices
curl -LO https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-ryan-high.tar.gz
tar xzf voice-en-us-ryan-high.tar.gz
```

`voices/` is gitignored — the models are ~100 MB.

To use Amazon Polly's newscaster style or ElevenLabs instead, add a branch
to `synth()` in `build_bulletin.py`. Everything downstream works off the
returned duration, so nothing else needs to change.

## The music

`make_bed.py` synthesises the underscore and the stings from scratch with
numpy — a low drone, an eighth-note pulse, a sparse A-minor arpeggio and a
newsroom tick, crossfaded so it loops seamlessly. ffmpeg's sidechain
compressor ducks it under the voice.

Nothing here is sampled or borrowed, so there is no third-party music
licence to track and nothing to attribute. Change the key, tempo or
instrumentation at the top of `make_bed.py`.

## The podcast feed

Every build is also published as a podcast episode, so people can
subscribe in any app instead of remembering to open the page.

```
build_bulletin.py ──▶ public/bulletin.mp3
                              │
      podcast.py episode ─────┤  dated MP3 + show notes + metadata
                              ▼
              GitHub Release  ep-20260907-1224     ← the archive
                              │
      podcast.py feed  ◀──────┘  reads every ep-* release back
                              ▼
                      public/feed.xml
```

### Where episodes live, and why it matters

The site is rebuilt from scratch every run and `public/` is replaced
wholesale, so anything written there is gone by the next edition. A
podcast cannot work that way: the feed points at episodes by URL, and
those URLs have to keep working for as long as the episode is listed.
An app that gets a 404 shows a broken episode; one that sees a changed
URL re-downloads it.

Three options, and why this one:

| Where | Verdict |
|---|---|
| Committed to the repo | Durable, but two editions a day at ~1.5 MB is about a gigabyte a year of binaries in git history, unprunable without rewriting history. **No.** |
| Carried forward from the live site | No repo growth, but the archive exists only in the last successful deploy, so one bad run destroys it. **No.** |
| **GitHub Releases** | Permanent URLs, free on public repos, no repo growth — and the release list *is* the archive, so the feed regenerates from GitHub rather than from a state file that could drift. **Yes.** |

Because the archive is GitHub's release list, a rebuild from an empty
checkout produces an identical feed. There is no state to lose.

### But the feed must not point at Releases

Release assets are the archive, **not** the URLs the feed advertises. This
was found the hard way: the feed played fine in browsers and on Windows,
while Apple Podcasts answered *"this episode can't be played on this
device."* GitHub serves release assets like this:

```
Content-Type: application/octet-stream        ← not audio/mpeg
Content-Disposition: attachment               ← "download me, don't play me"
Location: ...?se=2026-09-08T07:38:52Z         ← signed, expires within the hour
```

Browsers ignore all three and play the file anyway, which is exactly why
the fault looked like an Apple quirk rather than a server one. Podcast
apps check the content type, and `application/octet-stream` is not audio.
None of it is configurable — Releases is a software-distribution endpoint,
not a media host.

So the two jobs are split:

- **GitHub Releases — the archive.** Permanent, free, never lost. Every
  edition ever published, with its running order, at a stable page.
- **GitHub Pages — the serving layer.** Plain static hosting, so `.mp3`
  goes out as `audio/mpeg`, inline, from a permanent URL, with byte
  ranges so apps can seek.

`podcast.py feed` mirrors the most recent editions out of Releases into
`public/episodes/` and points the enclosures there. The feed lists exactly
what the site is hosting, so no listed episode can 404. An episode that
fails to mirror is dropped from the feed rather than advertised with a URL
that would not play.

`--window` controls how many editions are hosted and listed, default 30 —
about a fortnight at two a day, roughly 70 MB. Older editions stay in
Releases and remain downloadable from their release page forever; they
simply stop appearing in podcast apps, which is normal for a daily news
show.

If the GitHub API is unreachable, `podcast.py feed` **fails the build
rather than writing an empty feed** — an empty feed would unpublish every
episode from every subscriber's app. A failed build leaves the previous
deploy serving, which is the safe outcome.

### An episode is published on the schedule, not on every push

`push` rebuilds and redeploys the site so a code change goes live, but it
must **not** publish an episode — that would ship an edition to everyone's
podcast app every time you edit a file. Three pushes in one morning became
three episodes before this was caught. Episodes are published only by the
cron schedule, or by a manual run with the box ticked.

### Before you submit it anywhere

Set `email` in `podcast.json`. Apple Podcasts will not let you claim a
show without a contact address on the feed, and `podcast.py check` warns
while it is blank.

```bash
python3 podcast.py episode   # package the current build
python3 podcast.py feed      # regenerate feed.xml from the releases
python3 podcast.py check     # validate against the podcast spec
```

`check` verifies what Apple and Spotify actually require: an
`itunes:image`, a category, and per episode an enclosure with a real byte
length, a unique GUID and a `pubDate`.

### Cover art

`make_cover.py` draws the 2000×2000 cover with PIL — the transmitter lamp
and signal arcs over the Court's name, in the site's palette. Run it once
and commit `assets/cover.png`; it never changes between editions, so the
build just copies it and never depends on a font being installed on the
runner. It was checked for legibility at 55 pixels, which is how most
people first see it.

### Listing on Apple and Spotify

Set `spotify` (and later `apple`) in `podcast.json` and the site shows a
"Listen on Spotify" button automatically — `podcast.py feed` writes those
into `public/links.json`, which the player reads, so adding a platform
never means editing `index.html`.

Both index a show once, from its feed URL, and pull new episodes
automatically after that. Submit at
[podcastsconnect.apple.com](https://podcastsconnect.apple.com/) and
[podcasters.spotify.com](https://podcasters.spotify.com/). Everything
else — Pocket Casts, Overcast, AntennaPod, Castro — takes the feed URL
directly with no submission at all.

## Sources, and the copyright line this project draws

Sources sit in two tiers and the pipeline treats them differently on
purpose.

**Judgments and official material** — court judgments and orders,
government releases, regulator circulars. Section 52(1)(q) of the Copyright
Act 1957 puts reproduction of a court judgment outside infringement, so
these can be summarised freely and at length. This is the tier the bulletin
should lean on.

**Private legal news** — Verdictum, LiveLaw, Bar & Bench, SCC Online Blog.
The pipeline takes the **headline and the link only**. It never reads a
publisher's article prose into the bulletin. Each item is credited by name
in the opening, again by name as it is read, again in the ticker while it
plays, and linked to the publisher's own page in the running order.

### Spreading the bulletin across publishers

`collect()` pulls a batch from every live source and then deals them out
round-robin, rather than draining sources in order. This matters more than
it sounds: the drain-in-order version meant whichever feed answered first
filled the entire bulletin and every other source was ignored, so an
eight-item edition could credit exactly one publisher.

Each source is capped at roughly an even share, floor of two, so a
bulletin built from four live feeds credits four publishers. Pass
`--per-source N` to set the cap yourself; an explicit cap is honoured
strictly, even if that leaves a shorter edition, whereas the derived one
will be exceeded rather than air a half-empty bulletin.

Stories that several publishers covered are collapsed to one. A shared INSC
neutral citation is conclusive; otherwise the check compares distinctive
words. Those thresholds are calibrated against real headlines rather than
guessed — two newsrooms writing up the same judgment scored 0.44 and 0.50
against each other, while eight genuinely distinct stories from one day
peaked at 0.08, so the cut sits at 0.35 with a floor of four shared words.

Verdictum earns its place near the top of the registry: it covers the
Supreme Court only, so nothing has to be filtered out, and its article
slugs usually carry the INSC neutral citation, which the player shows
beside each story.

If you add a source, set its `tier` honestly in `sources.py`. The script
generator enforces the distinction.

### One classifier, not one per adapter

`which_court()` in `sources.py` is the only thing that decides whether a
story belongs in the bulletin, and every adapter goes through it. That
centralisation is the fix for a real escape: when adapters filtered for
themselves the rules drifted, and a Karnataka High Court order reached air
because only one adapter checked for High Courts.

The rules, in order:

1. If the **headline** names the Supreme Court, it is ours — including
   "Supreme Court criticises AP High Court", which names both.
2. Otherwise, if the headline names a High Court, it is not.
3. Only if the headline names no court at all does the article URL, and
   then the feed it came from, get a say.

A publisher's Supreme Court feed is the *weakest* signal, not the
strongest. Verdictum's SC feed carried a Karnataka High Court story;
trusting the feed's name over the headline is what let it through.

Two smaller things this fixed. Court names are matched after collapsing
hyphens and underscores to spaces, so `/supreme-court/` in a URL actually
matches — previously the URL argument was silently doing nothing, because
the pattern wanted a space. And `HC` is now recognised as well as "High
Court", so "Delhi HC Grants Interim Relief" is caught.

### Why Indian Kanoon is switched off

Indian Kanoon looks like the natural spine for this project — actual
judgments, and section 52(1)(q) means they can be summarised freely. It
does not work out, and the reason is worth recording so nobody re-adds it
hopefully.

Its per-court Supreme Court feeds return valid RSS with **zero entries**.
Its all-courts `judgments` feed does work, with around 20 entries, but the
entries carry no court **anywhere**:

```
title   : Harendra vs The State Of Madhya Pradesh Thr on 20 August, 2026
link    : https://indiankanoon.org/doc/3557904/
fields  : guidislink, id, link, links, summary, summary_detail, title, title_detail
summary : Per Justice G.S. Ahluwalia 1. By this common judgment, Cr.A. Nos. ...
```

No court in the title, none in the URL, and no category or tag fields at
all. The only court signal is inside the judgment text — and that is
exactly the signal that cannot be trusted, because virtually every
judgment cites the Supreme Court somewhere. Running the filter across that
feed passed **one entry out of twenty, and that one was a High Court
judgment citing a Supreme Court precedent**.

A bulletin that announces High Court cases as Supreme Court judgments is
worse than one with no judgment-tier source at all, so the adapters stay in
`sources.py` — importable, listed in `DISABLED` — but out of the rotation.

**This is why `_is_supreme_court()` reads the headline and URL only, never
the article body.** Publishers put the court in the headline; judgment text
mentions every court it cites.

To bring judgment-tier content back, in rough order of effort:

- **Indian Kanoon's authenticated API**, which does expose the court as a
  field rather than leaving it to be guessed.
- **eSCR / Digital Supreme Court Reports** at digiscr.sci.gov.in.
- **Resolving each Indian Kanoon doc page** to read its court, at one extra
  request per item.

The Supreme Court's own judgment search at sci.gov.in sits behind a CAPTCHA
and is deliberately not scraped.

## Two things worth thinking about before you publish

**Bar Council Rule 36.** If this carries your name as a practising
advocate, keep the advertising and solicitation rules in view. A neutral
public bulletin is one thing; firm branding or a "get in touch" line reads
differently.

**A podcast feed is nearly free from here.** The pipeline already produces
a dated MP3 with a title, a duration and a description. Emitting a podcast
RSS file as well is one more template, and it lets people subscribe in
Spotify or Apple Podcasts rather than remembering to open a webpage.

## Layout

```
build_bulletin.py     pipeline: fetch, script, voice, mix
sources.py            source adapters and the tier rules
make_bed.py           synthesises bed.wav, intro.wav, outro.wav
make_preview.py       folds a build into one shareable HTML file
podcast.py            episodes, the RSS feed, and feed validation
make_cover.py         draws the podcast cover art
diagnose_feeds.py     shows what each feed contains and how it classifies
index.html            the player
sample_items.json     real items, for offline builds
podcast.json          feed config: owner, repo, site, contact email
public/               what gets deployed
```

## Licence

Code and the generated music: do what you like with them. The headlines and
links belong to the publishers they credit.
