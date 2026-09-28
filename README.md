# Qualys Portal Hub

A static link hub for Qualys public resources: a dashboard plus one resource-library tab per module. Everything is driven by CSV files, so links can be edited straight from the GitHub web UI.

## Layout

```
index.html           dashboard: quick tiles, module grid, public resources, search across all modules
<module>.html        one thin page per module (only sets <body data-module="...">)
modules.csv          one row per module tab: drives the sidebar, the dashboard grid and each page's header tiles
links/<module>.csv   the resource library for one module
links/public.csv     public Qualys links shown on the dashboard
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

## Run locally

The pages load their CSVs with `fetch`, so open them through a web server rather than as `file://` pages:

```
python -m http.server 8000
```

Then browse to http://localhost:8000.
