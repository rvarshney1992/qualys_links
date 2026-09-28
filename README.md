# Qualys Portal Hub

A static link hub for Qualys public resources: a dashboard plus one resource-library tab per module. Everything is driven by CSV files, so links can be edited straight from the GitHub web UI.

## Layout

```
index.html           dashboard: quick tiles, module grid, public resources, search across all modules
<module>.html        one thin page per module (only sets <body data-module="...">)
modules.csv          one row per module tab: drives the sidebar, the dashboard grid and each page's header tiles
links/<module>.csv   the resource library for one module
links/public.csv     public Qualys links shown on the dashboard
links/whats-new.csv  log of every link the weekly refresh added (drives whats-new.html)
scripts/update_links.py  the weekly refresh script
assets/hub.js        shared page logic (CSV parser, sidebar, tiles, search, category filters)
assets/hub.css       shared styles
```

## Add or change a link

Edit `links/<module>.csv`. The columns are `title,link,category`. Rows with the same category are grouped into one card, and each category also becomes a filter pill. If a title contains a comma, wrap it in double quotes:

```csv
title,link,category
"Purging: what, why, when",https://success.qualys.com/discussions/s/article/000006221,Purging
```

## Add a module tab

1. Add a row to `modules.csv`. `icon` is a Font Awesome solid icon name, e.g. `fa-shield-halved`. `docs`, `api`, `release_notes` and `product` fill the header tiles; leave any of them empty to hide that tile.
2. Copy any module page (for example `vmdr.html`) to `<id>.html` and change `data-module="vmdr"` to the new id.
3. Create `links/<id>.csv` with the header `title,link,category`.

## Weekly refresh

`.github/workflows/weekly-links.yml` runs every Saturday at 06:00 UTC (and on demand from the Actions tab). It runs `scripts/update_links.py`, which:

- reads the Qualys Blog and Qualys Notifications RSS feeds, matches each post to modules by its title and tags (`MODULE_KEYWORDS` in the script), and appends it to `links/<module>.csv` under `Blog`, `Release Notes` or `API`. Posts that match no module, and threat-research posts, go to `links/public.csv`;
- checks for this month's Product and TRU newsletter PDFs and adds them to `links/public.csv`;
- logs everything it added, plus that week's ThreatPROTECT advisories, to `links/whats-new.csv`, which `whats-new.html` displays week by week.

A link is never added twice. If a post lands in the wrong module, delete its row from that CSV; because it stays logged in `whats-new.csv`, it won't come back. To steer future matches, edit `MODULE_KEYWORDS`.

Preview locally without writing anything: `python scripts/update_links.py --dry-run`.

## Run locally

The pages load their CSVs with `fetch`, so open them through a web server rather than as `file://` pages:

```
python -m http.server 8000
```

Then browse to http://localhost:8000.
