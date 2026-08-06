# Architecture and repository slimming

## Canonical data flow

```text
data/reports + data/videos (raw source compatibility)
                    |
                    v
data/staging/       normalized identities, enrichments and AI caches
                    |
                    v
data/curated/       canonical products, matrices and compare payloads
                    |
                    v
web/public/data/    compact generated publishing payload (not tracked)
                    |
                    v
site/               Astro build output (not tracked)
```

Legacy `data/products`, `data/enrich`, `data/compare` and `data/matrix` remain
read fallbacks during migration, but new writes target staging/curated only.
Run `python scripts/migrate_data_layout.py --apply` before removing legacy
mirrors from version control.

## Build commands

- `python scripts/pipeline.py derive`: rebuild canonical derived data.
- `python scripts/pipeline.py derive --with-ai`: also refresh only missing or changed AI caches.
- `python scripts/pipeline.py site`: generate compact web data and build Astro.
- `python scripts/pipeline.py all --with-ai`: run both stages locally.

Data updates and Pages deployment are separate GitHub workflows. A normal code
push builds the website only; crawling, price lookup and AI enrichment run only
in the scheduled/manual data workflow.

## Publishing budget

- Product index contains card fields only, including one precomputed card image.
- Product detail JSON keeps only fields consumed by the UI.
- At most 2 summary images and 2 images per unboxing section are published.
- Images are converted to WebP with a 1440-pixel maximum edge and quality 78.
- Generated public data, optimized images and `site/` are never committed.
