# Semler's Meta Catalog Feed

Auto-generated Meta Vehicle Catalog feed for Semler's, regenerated hourly from the SandHills inventory CSV.

## How it works

1. **`meta-catalog-feed.py`** fetches the public SandHills inventory feed and transforms each row into Meta Vehicle Catalog format (field remapping, price/availability normalization, image URL extraction, etc.)
2. **`meta-catalog-validate.py`** validates the output against Meta's catalog schema
3. **GitHub Action** runs both hourly and commits `meta_catalog.csv` if it changed

## Meta feed URL

Point the Meta Business Manager catalog at the raw GitHub URL:

```
https://raw.githubusercontent.com/adsemersonoliveira-midia/semlers-meta-feed/main/meta_catalog.csv
```

## Local usage

```bash
python3 meta-catalog-feed.py                          # generates meta_catalog_YYYY-MM-DD.csv
python3 meta-catalog-feed.py --output meta_catalog.csv  # custom output name
python3 meta-catalog-feed.py --dry-run                # prints first 5 rows to stdout
python3 meta-catalog-validate.py meta_catalog.csv     # validates
```

## Data source

- **SandHills CSV feed:** public, no auth required, updates as inventory changes
- **Filter:** excludes attachments (tires, blades, buckets) — only vehicles
- **Required fields:** rows missing price, images, year, or make are skipped
