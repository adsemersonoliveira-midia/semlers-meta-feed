#!/usr/bin/env python3
"""
Semler's — SandHills CSV → Meta Vehicle Catalog
Fetches the SandHills inventory feed and outputs a Meta-compatible CSV.

Usage:
    python3 meta-catalog-feed.py             # outputs meta_catalog_YYYY-MM-DD.csv
    python3 meta-catalog-feed.py --dry-run   # print first 5 rows to stdout only

Meta Vehicle Catalog spec:
https://developers.facebook.com/docs/marketing-api/catalog/reference/vehicle-catalog
"""

import csv
import io
import re
import sys
import urllib.request
from datetime import date

FEED_URL = (
    "https://dealers.sandhills.com/DataExchange/ExportZipFile/Recurring/"
    "17010241/C75F37C98B438E7E98A970FD1A579526?Extension=csv"
)

# Inventory types to exclude — accessories/parts, not sellable vehicles
EXCLUDED_TYPES = {
    "Construction_Attachments",
    "Truck_Attachments",
    "Agricultural_Attachments",
}

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def parse_images(picture_list: str) -> list:
    """Split comma-separated image URLs and return HTTPS URLs only."""
    if not picture_list:
        return []
    return [u.strip() for u in picture_list.split(",") if u.strip().startswith("https")]


def normalize_availability(status: str) -> str:
    return "available" if status.upper() == "ACTIVE" else "not available"


def normalize_condition(condition: str) -> str:
    mapping = {"used": "used", "new": "new", "refurbished": "refurbished"}
    return mapping.get(condition.lower(), "used")


def normalize_fuel(fueltype: str) -> str:
    mapping = {
        "diesel": "diesel",
        "gasoline": "gasoline",
        "petrol": "gasoline",
        "electric": "electric",
        "hybrid": "hybrid_gasoline",
        "natural gas": "other",
        "propane": "other",
    }
    return mapping.get(fueltype.lower(), "other") if fueltype else ""


def extract_year_from_display(display_name: str) -> str:
    """Pull first 4-digit year from DisplayName (e.g. '2008 PETERBILT 389')."""
    m = YEAR_RE.search(display_name)
    return m.group(0) if m else ""


def normalize_mileage(value: str, unit: str) -> tuple:
    """Return (numeric_value, unit_code) where unit_code is KM or MI."""
    if not value:
        return "", ""
    # Strip non-numeric characters (commas, spaces)
    cleaned = "".join(c for c in value if c.isdigit())
    if not cleaned:
        return "", ""
    unit_code = "KM" if "kilometer" in unit.lower() else "MI"
    return cleaned, unit_code


def derive_body_style(inventory_type: str, category: str) -> str:
    cat = category.lower()
    if inventory_type == "Trucks":
        if "dump" in cat:
            return "truck"
        if "vocational" in cat:
            return "truck"
        return "truck"
    if inventory_type == "Trailers":
        return "other"
    return "other"


def clean_title(display_name: str, year: str, manufacturer: str, model: str) -> str:
    """Build a clean title from structured fields, trim to 150 chars."""
    title = f"{year} {manufacturer} {model}".strip()
    return title[:150]


def transform_row(row: dict):
    """Map a SandHills row to a Meta Vehicle Catalog row. Returns None to skip."""
    # Skip attachments/parts — not vehicles
    if row.get("InventoryType", "") in EXCLUDED_TYPES:
        return None
    # Skip if not for sale or not displayed
    if row.get("ForSale", "").lower() != "true":
        return None
    if row.get("DisplayOnSite", "").lower() != "yes":
        return None
    # Skip if no price
    price_val = row.get("ForSaleListPrice", "").strip()
    if not price_val:
        return None
    # Skip if no images
    images = parse_images(row.get("PictureList", ""))
    if not images:
        return None

    display_name = row.get("DisplayName", "")

    # year: use structured field, fallback to DisplayName parse
    year = row.get("Year", "").strip() or extract_year_from_display(display_name)
    if not year:
        return None  # year is required by Meta

    # make: use structured field; skip if missing
    make = row.get("Manufacturer", "").strip()
    if not make:
        return None

    # model: use structured field, fallback to Category slug
    model = row.get("Model", "").strip()
    if not model:
        category = row.get("Category", "")
        # Use the last segment of the category path as a readable model fallback
        model = category.split(" - ")[-1].strip() if category else "Unknown"

    # vehicle_id: StockNumber preferred, fallback to DSInventoryLookupID
    vehicle_id = row.get("StockNumber", "").strip() or row.get("DSInventoryLookupID", "")

    # Mileage
    mileage_value, mileage_unit = normalize_mileage(
        row.get("mileage", ""), row.get("mileagetype", "")
    )

    # VIN: prefer dedicated vin field, fallback to VINSerialNumber
    vin = row.get("vin", "") or row.get("VINSerialNumber", "")

    currency = row.get("CurrencyCode", "CAD") or "CAD"
    price = f"{price_val} {currency}"

    # Link: transform MarketBook URL to semlers.com (confirmed working — GET 200 with Chrome UA)
    listing_url = row.get("ListingDetailsURL", "").replace(
        "https://www.marketbook.ca", "https://semlers.com"
    )

    result = {
        "id": row.get("DSInventoryLookupID", ""),
        "vehicle_id": vehicle_id,
        "title": clean_title(display_name, year, make, model),
        "description": row.get("Description", "")[:5000],
        "availability": normalize_availability(row.get("Status", "")),
        "condition": normalize_condition(row.get("Condition", "used")),
        "price": price,
        "link": listing_url,
        "image_link": images[0],
        "year": year,
        "make": make,
        "model": model,
        "vin": vin,
        "mileage.value": mileage_value,
        "mileage.unit": mileage_unit,
        "transmission": row.get("transmission", ""),
        "fuel_type": normalize_fuel(row.get("fueltype", "")),
        "exterior_color": row.get("color", ""),
        "drivetrain": row.get("drive", ""),
        "body_style": derive_body_style(
            row.get("InventoryType", ""), row.get("Category", "")
        ),
    }

    # Additional images (Meta supports up to 9 extras = indices 0–8)
    for i, url in enumerate(images[1:10]):
        result[f"additional_image_link[{i}]"] = url

    return result


META_COLUMNS = [
    "id",
    "vehicle_id",
    "title",
    "description",
    "availability",
    "condition",
    "price",
    "link",
    "image_link",
    "year",
    "make",
    "model",
    "vin",
    "mileage.value",
    "mileage.unit",
    "transmission",
    "fuel_type",
    "exterior_color",
    "drivetrain",
    "body_style",
] + [f"additional_image_link[{i}]" for i in range(9)]


def main():
    dry_run = "--dry-run" in sys.argv
    # --output <file> to override default name; else use date-stamped name
    output_arg = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_arg = sys.argv[idx + 1]

    print(f"Fetching SandHills feed…", file=sys.stderr)
    with urllib.request.urlopen(FEED_URL, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    skipped = 0
    for row in reader:
        transformed = transform_row(row)
        if transformed is None:
            skipped += 1
        else:
            rows.append(transformed)

    print(f"  {len(rows)} rows included, {skipped} skipped", file=sys.stderr)

    if dry_run:
        writer = csv.DictWriter(sys.stdout, fieldnames=META_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows[:5]:
            writer.writerow(r)
        return

    output_file = output_arg or f"meta_catalog_{date.today().isoformat()}.csv"
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=META_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Saved → {output_file}", file=sys.stderr)
    print(output_file)


if __name__ == "__main__":
    main()
