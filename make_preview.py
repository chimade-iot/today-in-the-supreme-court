#!/usr/bin/env python3
"""
Fold the whole bulletin into one self-contained HTML file.

The audio becomes a data: URI and the cue sheet is inlined as
window.__BULLETIN__, so preview.html plays anywhere with no server and no
sibling files - handy for sending someone the edition over WhatsApp or
email before the site is live.

    python3 make_preview.py [-o preview.html]
"""
import argparse
import base64
import json
import mimetypes
from pathlib import Path

ROOT = Path(__file__).parent
PUBLIC = ROOT / "public"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(ROOT / "preview.html"))
    ap.add_argument("--body-only", action="store_true",
                    help="emit only the page content, without the html/head "
                         "wrapper (for hosts that supply their own)")
    args = ap.parse_args()

    data = json.loads((PUBLIC / "bulletin.json").read_text(encoding="utf-8"))
    audio_path = PUBLIC / data.get("audio", "bulletin.mp3")
    mime = mimetypes.guess_type(audio_path.name)[0] or "audio/mpeg"
    b64 = base64.b64encode(audio_path.read_bytes()).decode()
    data["audio"] = f"data:{mime};base64,{b64}"

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    inline = ("<script>window.__BULLETIN__ = "
              + json.dumps(data).replace("</", "<\\/")
              + ";</script>")
    marker = "<script>\n(function () {"
    if marker not in html:
        raise SystemExit("index.html changed shape; update the marker here.")
    html = html.replace(marker, inline + "\n" + marker, 1)

    if args.body_only:
        # Start at the font link rather than <style>, so the typefaces still
        # load on hosts that supply their own document skeleton.
        start = html.index('<link rel="preconnect"')
        end = html.index("</body>")
        html = html[start:end]

    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    mb = out.stat().st_size / 1_048_576
    print(f"{out}  ({mb:.1f} MB, {data['item_count']} items, "
          f"{data['duration']:.0f}s)")


if __name__ == "__main__":
    main()
