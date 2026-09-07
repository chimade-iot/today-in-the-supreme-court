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

### A live caveat on Indian Kanoon

Indian Kanoon publishes per-court RSS feeds and the Supreme Court one is
the natural spine for this project. **At the time of writing it returns
valid RSS with zero items**, while the all-courts `judgments` feed is
healthy. The pipeline therefore keeps the SC feed first in the chain, falls
through to the all-courts feed filtered to Supreme Court matters, and then
to the news publishers. Run `--check-sources` before assuming any of them
works today.

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
index.html            the player
sample_items.json     real items, for offline builds
public/               what gets deployed
```

## Licence

Code and the generated music: do what you like with them. The headlines and
links belong to the publishers they credit.
