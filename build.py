#!/usr/bin/env python3
"""Build the site from papers.yaml into _site/.

    python build.py            # build
    python build.py --serve    # build, then preview at http://localhost:8000

Needs PyYAML (pip install pyyaml). Nothing else.
"""
import datetime as dt
import html
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
OUT = ROOT / "_site"
PDFS = ROOT / "pdfs"
STATIC = ROOT / "static"

e = html.escape


# ── helpers ──────────────────────────────────────────────────────────────────
def norm_date(d):
    """Accept date objects, 'YYYY-MM', 'YYYY' or int; return (iso, highwire, year)."""
    s = d.isoformat() if isinstance(d, dt.date) else str(d)
    parts = s.split("-")
    return s, "/".join(parts), parts[0]


def split_name(a):
    fam, _, given = a.partition(",")
    return fam.strip(), given.strip()


def display_name(a):
    fam, given = split_name(a)
    return f"{given} {fam}".strip()


def is_me(a, site):
    fam, given = split_name(a)
    my_fam = site["name"].split()[-1]
    return fam == my_fam and given[:1] == site["name"][:1]


def authors_html(p, site):
    names = []
    for a in p["authors"]:
        n = e(display_name(a))
        names.append(f"<strong>{n}</strong>" if is_me(a, site) else n)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " &amp; " + names[-1]


def authors_short(p):
    fams = [split_name(a)[0] for a in p["authors"]]
    if len(fams) == 1:
        return fams[0]
    if len(fams) == 2:
        return f"{fams[0]} &amp; {fams[1]}"
    return f"{fams[0]} et al."


def pages(p):
    if p.get("first_page"):
        return p["first_page"] + (f"–{p['last_page']}" if p.get("last_page") else "")
    return p.get("article_number", "")


def citation_text(p):
    """APA-style plain citation."""
    def apa(a):
        fam, given = split_name(a)
        inits = " ".join(f"{g[0]}." for g in given.replace("-", " ").split() if g and g[0].isalpha())
        return f"{fam}, {inits}".strip(", ")
    au = [apa(a) for a in p["authors"]]
    au = au[0] if len(au) == 1 else ", ".join(au[:-1]) + ", & " + au[-1]
    s = f"{e(au)} ({p['year']}). {e(p['title'])}. <em>{e(p['journal'])}</em>"
    if p.get("volume"):
        s += f", <em>{e(p['volume'])}</em>"
        if p.get("issue"):
            s += f"({e(p['issue'])})"
    if pages(p):
        s += f", {e(pages(p))}"
    s += "."
    if p.get("doi"):
        s += f" https://doi.org/{e(p['doi'])}"
    return s


def bibtex(p):
    key = p["slug"].replace("-", "_")
    kind = "@misc" if p.get("preprint") else "@article"
    f = {
        "title": "{" + p["title"] + "}",
        "author": " and ".join(p["authors"]),
        "journal" if not p.get("preprint") else "howpublished": p["journal"],
        "year": p["year"],
        "volume": p.get("volume"),
        "number": p.get("issue"),
        "pages": pages(p).replace("–", "--") if pages(p) else None,
        "doi": p.get("doi"),
    }
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in f.items() if v)
    return f"{kind}{{{key},\n{body}\n}}"


# ── shared bits ──────────────────────────────────────────────────────────────
HEAD = """<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="icon" href="{root}assets/favicon.svg" type="image/svg+xml">
{extra}
</head>
"""

WAVE = """<div class="wave" aria-hidden="true"><svg viewBox="0 0 192 14" preserveAspectRatio="none">
<path d="M0 7 Q12 0 24 7 T48 7 T72 7 T96 7 T120 7 T144 7 T168 7 T192 7"/></svg></div>"""

LINK_LABELS = [
    ("google_scholar", "scholar"), ("orcid", "orcid"),
    ("bluesky", "bluesky"), ("linkedin", "linkedin"), ("github", "github"), ("university", "university"), ("cv", "cv"),
]


def links_html(site, root):
    out = []
    for key, label in LINK_LABELS:
        v = site["links"].get(key)
        if not v:
            continue
        if key == "cv" and not v.startswith("http"):
            href = root + v
        else:
            href = v
        ext = ' rel="me noopener"' if href.startswith("http") else ""
        out.append(f'<a href="{e(href)}"{ext}>{label}</a>')
    return "\n".join(out)


def email_html(site):
    """Email stored reversed in data attributes; a short script reassembles it.
    Without JavaScript, visitors see the readable 'name [at] domain' form."""
    addr = site["links"].get("email")
    if not addr:
        return ""
    user, _, dom = addr.partition("@")
    return (f'<p class="email"><a class="obf" data-u="{e(user[::-1])}" data-d="{e(dom[::-1])}">'
            f'{e(user)} [at] {e(dom)}</a></p>')


def tutorials_html(tutorials):
    """The home page's Tutorials section: one numbered title per tutorial, in the paper-title
    style, the number standing where a paper's year goes."""
    if not tutorials:
        return ""
    rows = "\n".join(f"""<li>
  <span class="yr">{i}.</span>
  <div><a class="ttl" href="{e(t['url'])}">{e(t['title'])}</a></div>
</li>""" for i, t in enumerate(tutorials, start=1))
    return f"""
    <h2 class="label" id="tutorials">tutorials</h2>
    <ul class="papers">
{rows}
    </ul>
"""


# ── home page ────────────────────────────────────────────────────────────────
def home(site, papers, tutorials=()):
    rows = []
    prev_year = None
    for p in papers:
        yr = p["year"] if p["year"] != prev_year else ""
        prev_year = p["year"]
        page = f"papers/{p['slug']}/"
        if p["has_pdf"]:
            href, kind = f"{page}{p['slug']}.pdf", "pdf"
        elif p.get("journal_url"):
            href, kind = p["journal_url"], "journal"
        else:
            href, kind = page, None
        tags = [f'<a class="tag" href="{e(href)}">{kind}</a>'] if kind else []
        tags.append(f'<a class="tag" href="{page}">abstract</a>')
        pre = " · preprint" if p.get("preprint") else ""
        rows.append(f"""<li{' class="new-yr"' if yr else ''}>
  <span class="yr">{yr}</span>
  <div>
    <a class="ttl" href="{e(href)}">{e(p['title'])}</a>
    <span class="meta">{authors_short(p)} · <span class="jn">{e(p['journal'])}</span>{pre} · {' · '.join(tags)}</span>
  </div>
</li>""")

    person = {
        "@context": "https://schema.org", "@type": "Person",
        "name": site["name"], "jobTitle": site["role"],
        "worksFor": {"@type": "CollegeOrUniversity", "name": site["institution"]},
        "alumniOf": [{"@type": "CollegeOrUniversity", "name": n} for n in site.get("alumni_of", [])],
        "knowsAbout": site.get("knows_about", []),
        "url": site["base_url"] + "/",
        "sameAs": [v for k, v in site["links"].items() if v and str(v).startswith("http")],
    }
    if site["links"].get("orcid"):
        person["identifier"] = {"@type": "PropertyValue", "propertyID": "ORCID",
                                "value": site["links"]["orcid"].rstrip("/").split("/")[-1]}
    extra = f'<script type="application/ld+json">{json.dumps(person, ensure_ascii=False)}</script>'
    photo = site.get("photo")
    photo_html = (f'<img class="headshot" src="{e(photo)}" alt="Portrait of {e(site["name"])}" width="96" height="96">'
                  if photo and (STATIC / photo).exists() else "")

    return HEAD.format(
        title=e(site["name"]), desc=e(f"{site['name']}, {site['role']}, {site['department']}, {site['institution']}."),
        canonical=site["base_url"] + "/", root="", extra=extra,
    ) + f"""<body>
<main class="page">
    <header class="intro">
      <div>
        <h1 class="name">{e(site['name'])}</h1>
        <p class="role">{e(site['role'])}<span>{e(site['department'])}</span><span>{e(site['institution'])}</span></p>
        {email_html(site)}
      </div>
      {photo_html}
    </header>
    {WAVE}
    <nav class="links" aria-label="Profiles">
{links_html(site, "")}
    </nav>

    <p class="bio">{e(site['bio'].strip())}</p>

    <h2 class="label" id="papers">papers</h2>
    <ul class="papers">
{chr(10).join(rows)}
    </ul>
{tutorials_html(tutorials)}


    <footer>updated {dt.date.today().strftime('%B %Y')}</footer>
</main>
<script>
/* Builds the address in the browser so it never appears whole in the HTML */
document.querySelectorAll('a.obf').forEach(function (a) {{
  var r = function (s) {{ return s.split('').reverse().join(''); }};
  var m = r(a.dataset.u) + '@' + r(a.dataset.d);
  a.href = 'mailto:' + m;
  a.textContent = m;
}});
</script>
</body>
</html>
"""


# ── paper page ───────────────────────────────────────────────────────────────
def paper_page(site, p):
    base = site["base_url"]
    url = f"{base}/papers/{p['slug']}/"
    pdf_name = f"{p['slug']}.pdf"

    # Highwire Press tags — what Google Scholar reads
    m = [("citation_title", p["title"])]
    m += [("citation_author", a) for a in p["authors"]]
    m += [("citation_publication_date", p["hw_date"])]
    m += [("citation_journal_title", p["journal"])]
    for k_yaml, k_meta in [("volume", "citation_volume"), ("issue", "citation_issue"),
                           ("first_page", "citation_firstpage"), ("last_page", "citation_lastpage"),
                           ("doi", "citation_doi")]:
        if p.get(k_yaml):
            m.append((k_meta, p[k_yaml]))
    if p.get("article_number") and not p.get("first_page"):
        m.append(("citation_firstpage", p["article_number"]))
    m.append(("citation_abstract_html_url", url))
    if p["has_pdf"]:
        m.append(("citation_pdf_url", url + pdf_name))
    # Dublin Core duplicates for other indexers
    m += [("DC.title", p["title"])] + [("DC.creator", a) for a in p["authors"]]
    m += [("DC.date", p["iso_date"])]
    if p.get("doi"):
        m.append(("DC.identifier", f"doi:{p['doi']}"))
    meta = "\n".join(f'<meta name="{k}" content="{e(str(v))}">' for k, v in m)

    ld = {
        "@context": "https://schema.org", "@type": "ScholarlyArticle",
        "headline": p["title"], "name": p["title"], "url": url,
        "datePublished": p["iso_date"],
        "author": [{"@type": "Person", "name": display_name(a)} for a in p["authors"]],
        "isPartOf": {"@type": "Periodical", "name": p["journal"]},
        "abstract": p.get("abstract", "").strip(),
    }
    if p.get("doi"):
        ld["sameAs"] = f"https://doi.org/{p['doi']}"
        ld["identifier"] = {"@type": "PropertyValue", "propertyID": "DOI", "value": p["doi"]}
    if p["has_pdf"]:
        ld["encoding"] = {"@type": "MediaObject", "encodingFormat": "application/pdf",
                          "contentUrl": url + pdf_name}
    extra = meta + f'\n<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
    if p["has_pdf"]:
        extra += f'\n<link rel="alternate" type="application/pdf" href="{pdf_name}">'

    btns = []
    if p["has_pdf"]:
        btns.append(f'<a class="btn primary" href="{pdf_name}">download pdf</a>')
    if p.get("journal_url"):
        btns.append(f'<a class="btn" href="{e(p["journal_url"])}">{"biorxiv" if p.get("preprint") else "journal"}</a>')
    if p.get("preprint_url"):
        btns.append(f'<a class="btn" href="{e(p["preprint_url"])}">preprint</a>')
    if p.get("doi"):
        btns.append(f'<a class="btn" href="https://doi.org/{e(p["doi"])}">doi</a>')
    for alt in p.get("also", []) or []:
        btns.append(f'<a class="btn" href="{e(alt["url"])}">{e(alt["label"])}</a>')

    vol = f", {e(p['volume'])}" if p.get("volume") else ""
    return HEAD.format(
        title=e(f"{p['title']} | {site['name']}"),
        desc=e((p.get("abstract") or p["title"]).strip()[:155]),
        canonical=url, root="../../", extra=extra,
    ) + f"""<body class="paper">
<header class="top"><a class="wordmark" href="../../">{e(site['name'])}</a></header>
<main class="article">
  <p class="label">{e(p['journal'])}{vol} · {p['year']}{' · preprint' if p.get('preprint') else ''}</p>
  <h1>{e(p['title'])}</h1>
  <p class="authors">{authors_html(p, site)}</p>
  {WAVE}
  <div class="btns">{''.join(btns)}</div>

  <h2 class="label">abstract</h2>
  <p class="abstract">{e((p.get('abstract') or '').strip())}</p>

  <h2 class="label">cite</h2>
  <p class="cite">{citation_text(p)}</p>
  <details><summary>bibtex</summary><pre>{e(bibtex(p))}</pre></details>

  <p class="back"><a href="../../#papers">← all papers</a></p>
</main>
</body>
</html>
"""


# ── build ────────────────────────────────────────────────────────────────────
def main():
    cfg = yaml.safe_load((ROOT / "papers.yaml").read_text(encoding="utf-8"))
    site, papers = cfg["site"], cfg["papers"]

    warnings = []
    slugs = set()
    for p in papers:
        if p["slug"] in slugs:
            sys.exit(f"Duplicate slug: {p['slug']}")
        slugs.add(p["slug"])
        p["iso_date"], p["hw_date"], p["year"] = norm_date(p["date"])
        for k in ("volume", "issue", "first_page", "last_page", "article_number"):
            if p.get(k) is not None:
                p[k] = str(p[k])
        p["has_pdf"] = (PDFS / f"{p['slug']}.pdf").exists()
        if not p["has_pdf"]:
            warnings.append(f"no PDF      {p['slug']}")
        if p.get("verify"):
            warnings.append(f"verify meta {p['slug']}")
        if not p.get("doi"):
            warnings.append(f"no DOI      {p['slug']}")
    papers.sort(key=lambda p: p["iso_date"], reverse=True)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    if STATIC.exists():
        shutil.copytree(STATIC, OUT, dirs_exist_ok=True)

    (OUT / "index.html").write_text(home(site, papers, cfg.get("tutorials") or []),
                                    encoding="utf-8")
    for p in papers:
        d = OUT / "papers" / p["slug"]
        d.mkdir(parents=True)
        (d / "index.html").write_text(paper_page(site, p), encoding="utf-8")
        if p["has_pdf"]:
            shutil.copy2(PDFS / f"{p['slug']}.pdf", d / f"{p['slug']}.pdf")

    base = site["base_url"]
    today = dt.date.today().isoformat()
    urls = [f"{base}/"] + [f"{base}/papers/{p['slug']}/" for p in papers]
    urls += [f"{base}/papers/{p['slug']}/{p['slug']}.pdf" for p in papers if p["has_pdf"]]
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(f"  <url><loc>{e(u)}</loc><lastmod>{today}</lastmod></url>" for u in urls)
        + "\n</urlset>\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n")
    (OUT / ".nojekyll").write_text("")
    if site.get("domain"):
        (OUT / "CNAME").write_text(site["domain"] + "\n")

    n_pdf = sum(p["has_pdf"] for p in papers)
    print(f"Built {len(papers)} paper pages ({n_pdf} with PDFs) → {OUT}")
    for w in warnings:
        print("  ·", w)

    if "--serve" in sys.argv:
        import functools, http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        print("Preview: http://localhost:8000  (Ctrl+C to stop)")
        http.server.ThreadingHTTPServer(("", 8000), handler).serve_forever()


if __name__ == "__main__":
    main()
