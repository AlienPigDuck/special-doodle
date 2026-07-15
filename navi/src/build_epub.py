#!/usr/bin/env python3
"""Build an offline EPUB of 'The Mariner's Craft' for Calibre / e-readers.

Assembles the chapter Markdown (this folder) into one reflow-friendly HTML with a
light book stylesheet, renders a cover, and calls Calibre's `ebook-convert` to
produce the EPUB with a nested Part/section table of contents and embedded images.

    python3 navi/src/build_epub.py
Output: "/home/neil/Documents/Books and manuals/The Mariner's Craft/The Mariner's Craft.epub"
"""
import os, re, html, shutil, subprocess
import markdown
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_SRC = os.path.join(os.path.dirname(HERE), "img")          # navi/img
BUILD = "/tmp/navi-epub"
OUTDIR = "/home/neil/Documents/Books and manuals/The Mariner's Craft"
TITLE = "The Mariner's Craft"
SUBTITLE = "Finding your way by sky, sea, and reckoning — a practical book of traditional navigation"
AUTHOR = "christie.vip"
MD_EXT = ["extra", "sane_lists", "smarty"]


def convert(md):
    soup = BeautifulSoup(markdown.markdown(md, extensions=MD_EXT), "html.parser")
    # de-link every .md cross-reference (single-file book); fix outside image path
    for a in soup.find_all("a", href=True):
        if a["href"].endswith(".md") or ".md#" in a["href"] or re.search(r"\.md$", a["href"]):
            a.replace_with(a.get_text())
    for img in soup.find_all("img", src=True):
        if img["src"].startswith("../"):
            img["src"] = "img/" + os.path.basename(img["src"])
    # drop the web "Next:/Previous:" footer nav lines
    for p in soup.find_all("p"):
        t = p.get_text(strip=True).lower()
        if t.startswith("next:") or t.startswith("previous:"):
            p.decompose()
    # blockquote asides + boxed worked examples (mirror the web look)
    for bq in soup.find_all("blockquote"):
        bq["class"] = ["aside"]
    for p in soup.find_all("p"):
        st = p.find("strong")
        if st and st.get_text(strip=True).lower().startswith("worked example"):
            box = soup.new_tag("div"); box["class"] = ["worked"]
            p.insert_before(box); node = p
            while node and (node is p or node.name in ("ul", "ol", "pre")):
                nxt = node.find_next_sibling(); box.append(node.extract()); node = nxt
                if node and node.name not in ("ul", "ol", "pre"):
                    break
    return str(soup)


def front_matter():
    raw = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    guide = raw[raw.index("## How to read it"):]
    guide = re.sub(r"## Contents.*?(?=\n---\n)", "", guide, flags=re.S)   # drop repo contents list
    tagline = next((l.lstrip("# ").strip() for l in raw.splitlines() if l.startswith("###")), "")
    intro = raw.split(tagline, 1)[1].split("\n## ", 1)[0] if tagline else ""
    md = "# About This Book\n\n" + intro.strip() + "\n\n" + guide
    return convert(md)


CSS = """
body{font-family:Georgia,'Times New Roman',serif;line-height:1.6;margin:0 6%}
h1{font-family:'Palatino Linotype',Georgia,serif;text-align:center;font-size:1.9em;
   page-break-before:always;margin:1.2em 0 .2em;letter-spacing:.5px}
h1.notoc{page-break-before:avoid}
h2{font-family:'Palatino Linotype',Georgia,serif;font-size:1.35em;margin:1.6em 0 .4em;
   color:#33475a}
h3{font-style:italic;font-size:1.1em;margin:1.2em 0 .3em}
p{margin:0 0 .9em;text-align:justify}
img{max-width:100%;height:auto;display:block;margin:1.4em auto;
    border:1px solid #c9b98d;padding:8px;background:#fbf6ea;border-radius:3px}
blockquote.aside{border-left:3px solid #9a7b2e;background:#f3ecd8;
   margin:1.3em 0;padding:.6em 1em;font-size:.95em}
blockquote.aside strong:first-child{font-variant:small-caps;letter-spacing:.5px;color:#7a3f22}
.worked{border:1px solid #9a7b2e;background:#f5efdc;border-radius:4px;
   padding:.2em 1em .7em;margin:1.4em 0}
.worked::before{content:"⚓ Worked Example";display:block;font-variant:small-caps;
   letter-spacing:1px;color:#7a3f22;font-weight:bold;border-bottom:1px solid #c9b98d;
   margin:0 -1em .6em;padding:.5em 1em}
code{font-family:'DejaVu Sans Mono',monospace;font-size:.92em;background:#efe8d5;
   padding:0 .2em;border-radius:2px}
pre{background:#f2ecd9;border:1px solid #c9b98d;border-left:3px solid #9a7b2e;
   padding:.6em .9em;overflow:auto;white-space:pre-wrap}
pre code{background:none}
hr{border:0;border-top:1px solid #c9b98d;width:40%;margin:1.6em auto}
ul,ol{margin:0 0 1em 1.4em}
"""

COVER = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=EB+Garamond:ital@1&display=swap" rel="stylesheet">
<style>
html,body{margin:0;width:1600px;height:2400px}
body{background:
  radial-gradient(ellipse at 50% 12%, rgba(255,255,255,.35), rgba(255,255,255,0) 55%),
  repeating-linear-gradient(0deg, rgba(120,90,40,.03) 0 3px, transparent 3px 6px),
  linear-gradient(160deg,#f2e7cb,#e7d7ac 60%,#d8c48d);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  color:#3a2a15;font-family:'EB Garamond',Georgia,serif;text-align:center}
.frame{position:absolute;inset:60px;border:4px double #8a6a1e;border-radius:8px}
.rose{font-size:220px;line-height:1;color:#8a6a1e;margin-bottom:10px;
  font-family:'Cinzel',serif}
h1{font-family:'Cinzel',serif;font-weight:700;font-size:150px;line-height:1.02;
   letter-spacing:4px;margin:0 60px;color:#2a1c0e}
.tag{font-style:italic;font-size:58px;color:#5c4726;max-width:20ch;margin:60px auto 0;line-height:1.4}
.rule{width:46%;height:2px;background:linear-gradient(90deg,transparent,#8a6a1e,transparent);margin:70px auto}
.sub{font-family:'Cinzel',serif;font-size:46px;letter-spacing:8px;text-transform:uppercase;color:#7a3f22}
</style></head><body>
<div class="frame"></div>
<div class="rose">&#9875;&#65038;</div>
<h1>The Mariner&#x27;s Craft</h1>
<div class="rule"></div>
<div class="tag">Finding your way by sky, sea, and reckoning</div>
<div class="rule"></div>
<div class="sub">Traditional Navigation</div>
</body></html>"""


def main():
    if os.path.exists(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(BUILD)
    shutil.copytree(IMG_SRC, os.path.join(BUILD, "img"))

    parts = [front_matter()]
    for fn in sorted(f for f in os.listdir(HERE) if re.match(r"\d\d-.*\.md$", f)):
        parts.append(convert(open(os.path.join(HERE, fn), encoding="utf-8").read()))
    body = "\n<hr class='chapbreak'/>\n".join(parts)

    doc = (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{html.escape(TITLE)}</title>"
           f"<style>{CSS}</style></head><body>{body}</body></html>")
    open(os.path.join(BUILD, "book.html"), "w", encoding="utf-8").write(doc)
    open(os.path.join(BUILD, "cover.html"), "w", encoding="utf-8").write(COVER)

    # render cover
    subprocess.run(["chromium", "--headless", "--hide-scrollbars", "--no-sandbox",
                    "--force-device-scale-factor=1", "--virtual-time-budget=6000",
                    "--window-size=1600,2400",
                    f"--screenshot={BUILD}/cover.png", f"file://{BUILD}/cover.html"],
                   check=False, capture_output=True)

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, f"{TITLE}.epub")
    cmd = ["ebook-convert", os.path.join(BUILD, "book.html"), out,
           "--title", TITLE, "--authors", AUTHOR, "--language", "en",
           "--comments", SUBTITLE, "--book-producer", "christie.vip/navi",
           "--tags", "navigation,seamanship,reference",
           "--level1-toc", "//h:h1", "--level2-toc", "//h:h2",
           "--chapter", "//h:h1", "--page-breaks-before", "//h:h1",
           "--epub-inline-toc", "--max-toc-links", "0"]
    if os.path.exists(f"{BUILD}/cover.png"):
        cmd += ["--cover", f"{BUILD}/cover.png"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-1500:] if r.returncode == 0 else r.stdout + "\n" + r.stderr)
    print("\nEPUB:", out if r.returncode == 0 else "FAILED")


if __name__ == "__main__":
    main()
