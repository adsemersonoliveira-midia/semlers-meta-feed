#!/usr/bin/env python3
"""
Semler's — Validação local do Meta Vehicle Catalog CSV
Roda antes do upload para o Meta Business Manager.

Usage:
    python3 meta-catalog-validate.py meta_catalog_2026-05-12.csv
    python3 meta-catalog-validate.py meta_catalog_2026-05-12.csv --skip-url-check
"""

import csv
import re
import sys
import urllib.request
import urllib.error
from collections import defaultdict

REQUIRED_FIELDS = [
    "vehicle_id", "title", "description", "url", "make", "model", "year",
    "mileage.value", "mileage.unit", "price", "state_of_vehicle",
    "image[0].url", "address.addr1", "address.city", "address.region",
    "address.country",
]

VALID_AVAILABILITY = {"available", "not available"}
VALID_CONDITION = {"new", "used", "refurbished"}
VALID_FUEL = {"diesel", "gasoline", "electric", "hybrid_diesel", "hybrid_gasoline", "other", ""}
VALID_MILEAGE_UNIT = {"KM", "MI", ""}
PRICE_RE = re.compile(r"^\d+(\.\d+)?\s+[A-Z]{3}$")

URL_SAMPLE_SIZE = 10  # how many image + listing URLs to probe


BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def check_url(url: str, timeout: int = 8) -> tuple[bool, int, str]:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.status, ""
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # Cloudflare may block HEAD but allow GET — try GET fallback
            try:
                req2 = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
                with urllib.request.urlopen(req2, timeout=timeout) as r2:
                    return True, r2.status, ""
            except urllib.error.HTTPError as e2:
                return False, e2.code, str(e2)
            except Exception as e2:
                return False, 0, str(e2)
        return False, e.code, str(e)
    except Exception as e:
        return False, 0, str(e)


def validate(csv_path: str, skip_url_check: bool = False):
    errors = []
    warnings = []
    ids_seen = {}
    vehicle_ids_seen = {}

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    print(f"\n{'='*60}")
    print(f"  Semlers — Meta Catalog Validator")
    print(f"  Arquivo: {csv_path}")
    print(f"  Total de linhas: {total}")
    print(f"{'='*60}\n")

    # ── Field-level validation ────────────────────────────────────
    for i, row in enumerate(rows, start=2):  # row 1 is header
        row_id = row.get("vehicle_id", f"[linha {i}]")

        # Required fields
        for field in REQUIRED_FIELDS:
            if not row.get(field, "").strip():
                errors.append(f"Linha {i} (vehicle_id={row_id}): campo obrigatório vazio — '{field}'")

        # Duplicate vehicle_id
        vid = row.get("vehicle_id", "")
        if vid and vid in vehicle_ids_seen:
            warnings.append(f"Linha {i}: vehicle_id duplicado '{vid}' (linha {vehicle_ids_seen[vid]})")
        elif vid:
            vehicle_ids_seen[vid] = i

        # availability
        av = row.get("availability", "").strip().lower()
        if av not in VALID_AVAILABILITY:
            errors.append(f"Linha {i} (vehicle_id={row_id}): availability inválido — '{av}'")

        # condition
        cond = row.get("condition", "").strip().lower()
        if cond not in VALID_CONDITION:
            errors.append(f"Linha {i} (vehicle_id={row_id}): condition inválido — '{cond}'")

        # price format
        price = row.get("price", "").strip()
        if price and not PRICE_RE.match(price):
            errors.append(f"Linha {i} (vehicle_id={row_id}): price com formato inválido — '{price}' (esperado: '129900 CAD')")

        # image[0].url HTTPS
        img = row.get("image[0].url", "").strip()
        if img and not img.startswith("https://"):
            errors.append(f"Linha {i} (vehicle_id={row_id}): image[0].url não é HTTPS — '{img[:80]}'")

        # url format
        link = row.get("url", "").strip()
        if link and not link.startswith("https://"):
            errors.append(f"Linha {i} (vehicle_id={row_id}): url não é HTTPS — '{link}'")

        # fuel_type
        fuel = row.get("fuel_type", "").strip().lower()
        if fuel not in VALID_FUEL:
            warnings.append(f"Linha {i} (vehicle_id={row_id}): fuel_type desconhecido — '{fuel}'")

        # mileage consistency
        mv = row.get("mileage.value", "").strip()
        mu = row.get("mileage.unit", "").strip().upper()
        if mv and not mu:
            errors.append(f"Linha {i} (vehicle_id={row_id}): mileage.value preenchido mas mileage.unit vazio")
        if mu and mu not in VALID_MILEAGE_UNIT:
            errors.append(f"Linha {i} (vehicle_id={row_id}): mileage.unit inválido — '{mu}'")

        # year plausibility
        year = row.get("year", "").strip()
        if year and (not year.isdigit() or not (1950 <= int(year) <= 2030)):
            warnings.append(f"Linha {i} (vehicle_id={row_id}): year fora do intervalo esperado — '{year}'")

        # title length
        title = row.get("title", "")
        if len(title) > 150:
            warnings.append(f"Linha {i} (vehicle_id={row_id}): title > 150 chars ({len(title)})")

        # description length
        desc = row.get("description", "")
        if len(desc) > 5000:
            warnings.append(f"Linha {i} (vehicle_id={row_id}): description > 5000 chars ({len(desc)})")

    # ── Summary stats ─────────────────────────────────────────────
    available_count = sum(1 for r in rows if r.get("availability") == "available")
    types = defaultdict(int)
    for r in rows:
        types[r.get("body_style", "?")] += 1

    fuels = defaultdict(int)
    for r in rows:
        fuels[r.get("fuel_type", "") or "(vazio)"] += 1

    print("── Stats ─────────────────────────────────────────────────")
    print(f"  Disponíveis:     {available_count}/{total}")
    print(f"  Body styles:     {dict(types)}")
    print(f"  Fuel types:      {dict(fuels)}")
    has_mileage = sum(1 for r in rows if r.get("mileage.value"))
    print(f"  Com quilometragem: {has_mileage}/{total}")
    print()

    # ── URL probing (optional) ────────────────────────────────────
    if not skip_url_check:
        print("── Verificação de URLs (amostra) ─────────────────────────")

        # Sample image URLs from first N rows with images
        img_urls = [r["image[0].url"] for r in rows if r.get("image[0].url")][:URL_SAMPLE_SIZE]
        print(f"  Testando {len(img_urls)} URLs de imagem…")
        img_fails = []
        for url in img_urls:
            ok, code, msg = check_url(url)
            status = f"✓ {code}" if ok else f"✗ {code} {msg[:60]}"
            short = url[:70] + "…" if len(url) > 70 else url
            print(f"    [{status}] {short}")
            if not ok:
                img_fails.append(url)

        # Sample listing URLs
        listing_urls = [r["url"] for r in rows if r.get("url")][:5]
        print(f"\n  Testando {len(listing_urls)} URLs de listagem (semlers.com)…")
        listing_fails = []
        for url in listing_urls:
            ok, code, msg = check_url(url)
            status = f"✓ {code}" if ok else f"✗ {code} {msg[:60]}"
            print(f"    [{status}] {url}")
            if not ok:
                listing_fails.append((url, code, msg))

        print()
        if img_fails:
            errors.append(f"{len(img_fails)} URLs de imagem retornaram erro na amostra")
        if listing_fails:
            for url, code, msg in listing_fails:
                errors.append(f"URL de listagem com erro {code}: {url}")

    # ── Results ───────────────────────────────────────────────────
    print("── Erros (bloqueantes) ───────────────────────────────────")
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("  Nenhum erro encontrado.")

    print()
    print("── Avisos (revisar) ──────────────────────────────────────")
    if warnings:
        for w in warnings[:20]:
            print(f"  ⚠ {w}")
        if len(warnings) > 20:
            print(f"  … e mais {len(warnings) - 20} avisos.")
    else:
        print("  Nenhum aviso.")

    print()
    verdict = "REPROVADO" if errors else "APROVADO"
    marker = "✗" if errors else "✓"
    print(f"{'='*60}")
    print(f"  {marker} Resultado: {verdict} — {len(errors)} erro(s), {len(warnings)} aviso(s)")
    print(f"{'='*60}\n")

    return len(errors) == 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Uso: python3 meta-catalog-validate.py <arquivo.csv> [--skip-url-check]")
        sys.exit(1)

    path = args[0]
    skip_urls = "--skip-url-check" in args
    ok = validate(path, skip_url_check=skip_urls)
    sys.exit(0 if ok else 1)
