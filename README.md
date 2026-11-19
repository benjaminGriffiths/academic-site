# benjaminjamesgriffiths.com

A plain static site. Everything comes from `papers.yaml`. Push to GitHub and it rebuilds.

## What's here

| Path | What it is |
|---|---|
| `papers.yaml` | Your details and every paper. The only file you normally edit. |
| `pdfs/<slug>.pdf` | PDFs to host. The file name must match the paper's `slug`. |
| `static/` | Copied to the site root: `headshot.jpg`, `cv.pdf`, CSS, favicon. |
| `build.py` | Generates `_site/`. |
| `fetch_pdfs.py` | One-off: pulls your current Google Drive PDFs into `pdfs/`. |
| `.github/workflows/deploy.yml` | Builds and publishes on every push. |

## First-time setup

1. `pip install pyyaml`, then `python fetch_pdfs.py` to pull the PDFs from Drive.
2. Add `static/headshot.jpg`: a square crop, around 400 px. It appears as a small thumbnail beside your name.
3. Fill in the blank `links:` in `papers.yaml` (Scholar, ORCID, Bluesky), resolve every `verify: true`, and add the two missing DOIs.
4. Preview with `python build.py --serve`, then open http://localhost:8000.
5. Create a public GitHub repository and push this folder to `main`.
6. In the repository, go to **Settings → Pages → Source** and choose **GitHub Actions**.
7. Point the domain at GitHub Pages. With your registrar, set a `CNAME` record for `www` to `<username>.github.io`. Under Settings → Pages, enter the custom domain and tick **Enforce HTTPS**.
8. Remove the custom domain from Google Sites.
9. Add the site in Google Search Console and submit `/sitemap.xml`. This is optional, but it speeds up the first crawl.

Keep `base_url` as your own domain. Scholar keys on URLs, so moving domains later costs you the indexing. For the same reason, never change a paper's `slug` once it's live.

## Adding a paper

Copy an entry in `papers.yaml`, fill it in, drop `pdfs/<slug>.pdf` in place and push. That's all.

## Before hosting a PDF

Check the journal's self-archiving policy on Sherpa Romeo (https://v2.sherpa.ac.uk/romeo/). For subscription journals, the accepted manuscript is usually allowed but the publisher's typeset PDF usually isn't. Open-access CC BY papers are fine. The Scholar parser wants the title in the largest font at the top of page 1, the authors underneath and a References section, so a well-formatted accepted manuscript works.

## Checking Scholar will read a page

View the source of any paper page. You should see `citation_title`, one `citation_author` per author, `citation_publication_date` and, if a PDF exists, `citation_pdf_url`. Expect a few weeks to a few months before the [PDF] links appear in Scholar.
