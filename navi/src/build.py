#!/usr/bin/env python3
"""Build 'The Mariner's Craft' online book (christie.vip/navi) from Markdown.

Reads the chapter .md + README in this folder, emits styled static HTML into the
parent navi/ directory. Aesthetic: Admiral FitzRoy / age-of-sail. No server, no
JS framework — plain Pages-served HTML. Re-run after any content change:

    python3 navi/src/build.py
"""
import os, re, html
import markdown
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)               # navi/
ROMAN = {0: "0", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}

MD_EXT = ["extra", "sane_lists", "smarty"]


def slug(s):
    s = re.sub(r"<[^>]+>", "", s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "sec"


def chapters():
    out = []
    for fn in sorted(f for f in os.listdir(HERE) if re.match(r"\d\d-.*\.md$", f)):
        num = int(fn[:2])
        raw = open(os.path.join(HERE, fn), encoding="utf-8").read()
        h1 = raw.splitlines()[0].lstrip("# ").strip()          # "Part I — The Foundations"
        name = h1.split("—", 1)[1].strip() if "—" in h1 else h1
        out.append({"num": num, "file": fn, "raw": raw, "h1": h1, "name": name,
                    "out": f"part-{num}.html"})
    return out


def rewrite_links(soup, chap_by_num):
    """chapter .md links -> part-N.html; unknown .md links -> plain text."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"(?:.*/)?(\d\d)-[\w-]+\.md(#.*)?$", href)
        if m:
            a["href"] = f"part-{int(m.group(1))}.html{m.group(2) or ''}"
        elif href.endswith(".md") or href.endswith(".md/"):
            a.replace_with(a.get_text())                       # e.g. ../NAVIGATION.md


def rewrite_images(soup):
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if src.startswith("../"):
            img["src"] = "img/" + os.path.basename(src)        # ../latitude-vs-longitude.png
        img["loading"] = "lazy"


def style_blocks(soup):
    # blockquote asides
    for bq in soup.find_all("blockquote"):
        bq["class"] = bq.get("class", []) + ["aside"]
    # worked examples: wrap the "Worked example." paragraph + following lists/pre
    for p in soup.find_all("p"):
        st = p.find("strong")
        if st and st.get_text(strip=True).lower().startswith("worked example"):
            box = soup.new_tag("div"); box["class"] = ["worked"]
            p.insert_before(box)
            node = p
            while node and (node.name == "p" and node is p or node.name in ("ul", "ol", "pre")):
                nxt = node.find_next_sibling()
                box.append(node.extract())
                node = nxt
                if node and node.name not in ("ul", "ol", "pre"):
                    break


def anchor_sections(soup):
    secs = []
    for h in soup.find_all("h2"):
        sid = slug(h.get_text())
        h["id"] = sid
        secs.append((sid, h.get_text().strip()))
    return secs


def sidebar(chap_list, current, sections):
    li = []
    for c in chap_list:
        cur = c["num"] == current
        cls = ' class="current"' if cur else ""
        sub = ""
        if cur and sections:
            items = "".join(f'<li><a href="#{sid}">{html.escape(txt)}</a></li>'
                             for sid, txt in sections)
            sub = f'<ol class="sections">{items}</ol>'
        li.append(f'<li{cls}><a class="partlink" href="{c["out"]}">'
                  f'Part {ROMAN[c["num"]]} · {html.escape(c["name"])}</a>{sub}</li>')
    return ('<a class="brand" href="index.html">The Mariner’s Craft'
            '<small>Traditional Navigation</small></a><hr>'
            f'<nav><ol>{"".join(li)}</ol></nav>')


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="robots" content="noindex, nofollow">
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<link rel="icon" href="/favicon.ico">
<link rel="stylesheet" href="style.css">
</head>
<body>
{topbar}
<div class="scrim"></div>
<div class="wrap">
{sidebar}
<main class="content">
{body}
</main>
</div>
{script}
</body>
</html>"""

TOPBAR = ('<div class="topbar"><button class="menu-btn" aria-label="Contents">☰</button>'
          '<span class="t">The Mariner’s Craft</span></div>')

SCRIPT = """<script>
const b=document.body,mb=document.querySelector('.menu-btn');
if(mb){mb.addEventListener('click',()=>b.classList.toggle('nav-open'));
document.querySelector('.scrim').addEventListener('click',()=>b.classList.remove('nav-open'));
document.querySelectorAll('.sidebar a').forEach(a=>a.addEventListener('click',()=>b.classList.remove('nav-open')));}
</script>"""


def render_chapter(c, chap_list):
    body_md = c["raw"].split("\n", 1)[1] if c["raw"].startswith("#") else c["raw"]  # drop h1
    htmlbody = markdown.markdown(body_md, extensions=MD_EXT)
    soup = BeautifulSoup(htmlbody, "html.parser")
    chap_by_num = {c["num"]: c for c in chap_list}
    rewrite_links(soup, chap_by_num)
    rewrite_images(soup)
    style_blocks(soup)
    sections = anchor_sections(soup)
    # drop the trailing "Next: ..." paragraph (we render our own prev/next)
    for p in soup.find_all("p"):
        if p.get_text(strip=True).lower().startswith("next:") or \
           p.get_text(strip=True).lower().startswith("previous:"):
            p.decompose()
    # lede class on first paragraph for the drop cap
    first_p = soup.find("p")
    if first_p:
        first_p["class"] = first_p.get("class", []) + ["lede"]

    head = (f'<div class="eyebrow">Part {ROMAN[c["num"]]}</div>'
            f'<h1>{html.escape(c["name"])}</h1>')
    # prev / next
    prev = next((x for x in chap_list if x["num"] == c["num"] - 1), None)
    nxt = next((x for x in chap_list if x["num"] == c["num"] + 1), None)
    pa = (f'<a class="prev" href="{prev["out"]}"><span class="lbl">← Previous</span>'
          f'<span class="ttl">Part {ROMAN[prev["num"]]} · {html.escape(prev["name"])}</span></a>'
          if prev else '<a class="prev disabled"></a>')
    na = (f'<a class="next" href="{nxt["out"]}"><span class="lbl">Next →</span>'
          f'<span class="ttl">Part {ROMAN[nxt["num"]]} · {html.escape(nxt["name"])}</span></a>'
          if nxt else '<a class="next disabled"></a>')
    nav = f'<div class="chapnav">{pa}{na}</div>'

    body = head + str(soup) + nav
    return PAGE.format(title=f'{c["name"]} — The Mariner’s Craft',
                       topbar=TOPBAR, sidebar=f'<aside class="sidebar">{sidebar(chap_list, c["num"], sections)}</aside>',
                       body=body, script=SCRIPT)


def render_cover(chap_list):
    raw = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    lines = raw.splitlines()
    title = lines[0].lstrip("# ").strip()
    tagline = next((l.lstrip("# ").strip() for l in lines if l.startswith("###")), "")

    # intro = text between the ### subtitle and the first "## " heading
    after_tag = raw.split(tagline, 1)[1] if tagline in raw else raw
    intro_md = after_tag.split("\n## ", 1)[0].strip()
    intro_html = markdown.markdown(intro_md, extensions=MD_EXT)
    isoup = BeautifulSoup(intro_html, "html.parser"); rewrite_links(isoup, {})

    # guidance = everything from "## How to read it", minus the "## Contents" block
    guide_md = raw[raw.index("## How to read it"):]
    guide_md = re.sub(r"## Contents.*?(?=\n---\n)", "", guide_md, flags=re.S)
    gsoup = BeautifulSoup(markdown.markdown(guide_md, extensions=MD_EXT), "html.parser")
    rewrite_links(gsoup, {});
    for bq in gsoup.find_all("blockquote"): bq["class"] = ["aside"]

    # TOC cards from README's Contents entries
    cards = []
    for m in re.finditer(
            r"\*\*Part (0|[IVX]+) — ([^*]+?)\*\*[^\n]*?\((\d\d)-[\w-]+\.md\)\n(.*?)(?=\n\n|\n\*\*Part|\Z)",
            raw, flags=re.S):
        roman, name, num, desc = m.group(1), m.group(2).strip(), int(m.group(3)), m.group(4)
        desc = re.sub(r"[*`]", "", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        cards.append(
            f'<li><a href="part-{num}.html"><span class="pt">{roman}</span>'
            f'<span class="nm">{html.escape(name)}</span>'
            f'<span class="ds">{html.escape(desc)}</span></a></li>')
    toc = f'<section class="toc"><h2>The Contents</h2><ol>{"".join(cards)}</ol></section>'

    body = (
        '<div class="cover">'
        '<div class="rose">⚓</div>'
        f'<h1>{html.escape(title)}</h1>'
        f'<p class="tagline">{html.escape(tagline)}</p>'
        '<div class="divider"></div>'
        f'<div class="intro">{isoup}</div>'
        f'{toc}'
        '<div class="divider"></div>'
        f'<div class="intro">{gsoup}</div>'
        '</div>')
    return PAGE.format(title=f'{title} — Traditional Navigation',
                       topbar="", sidebar="", body=body, script="")


def main():
    ch = chapters()
    for c in ch:
        open(os.path.join(OUT, c["out"]), "w", encoding="utf-8").write(render_chapter(c, ch))
        print("wrote", c["out"])
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(render_cover(ch))
    print("wrote index.html")


if __name__ == "__main__":
    main()
