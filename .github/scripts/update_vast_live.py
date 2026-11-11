#!/usr/bin/env python3
"""Refresh vast-live.json from the public vast.ai search API. No API key required.

If the search fails or a field is missing, keep the last known values in vast-live.json.
Never writes IPs, keys, or other host-identifying network details.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MACHINE_ID = 156929
LISTING_URL = (
    "https://cloud.vast.ai/create/"
    "?machineId=156929&isOfferVerified=false&isOfferAvailable=false"
)
ENDPOINTS = (
    "https://console.vast.ai/api/v0/bundles/",
    "https://cloud.vast.ai/api/v0/bundles/",
)
QUERIES = (
    {"machine_id": {"eq": MACHINE_ID}},
    {
        "machine_id": {"eq": MACHINE_ID},
        "verified": {"eq": False},
        "rentable": {"eq": False},
    },
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Polaroy-live-stats/1.0; +https://polaroytech.com/)"
    ),
    "Accept": "application/json",
    "Origin": "https://cloud.vast.ai",
    "Referer": "https://cloud.vast.ai/create/",
}
ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "vast-live.json"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def load_previous() -> dict:
    if not JSON_PATH.exists():
        return {}
    try:
        data = json.loads(JSON_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: could not read existing {JSON_PATH.name}: {exc}", file=sys.stderr)
        return {}


def fetch_offers() -> list:
    errors = []
    for base in ENDPOINTS:
        for query in QUERIES:
            qs = urllib.parse.urlencode({"q": json.dumps(query, separators=(",", ":"))})
            url = f"{base}?{qs}"
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    payload = json.loads(response.read().decode())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{url} -> {exc}")
                continue
            offers = payload.get("offers") if isinstance(payload, dict) else None
            if isinstance(offers, list) and offers:
                return offers
            errors.append(f"{url} -> no offers")
    raise RuntimeError("public search returned no offers; " + "; ".join(errors))


def pick_offer(offers: list) -> dict:
    for offer in offers:
        if offer.get("machine_id") == MACHINE_ID:
            return offer
    raise RuntimeError("search results did not include machine 156929")


def availability(offer: dict) -> str:
    if offer.get("rented") is True:
        return "Rented"
    if offer.get("rentable") is True:
        return "Available"
    return "Unavailable"


def from_unix(value) -> str | None:
    if value in (None, "", 0):
        return None
    try:
        return iso(datetime.fromtimestamp(float(value), tz=timezone.utc))
    except (OSError, OverflowError, ValueError):
        return None


def first(*values):
    for value in values:
        if value is not None:
            return value
    return None


def extract(offer: dict) -> dict:
    search = offer.get("search") if isinstance(offer.get("search"), dict) else {}
    price = first(search.get("gpuCostPerHour"), offer.get("dph_base"), offer.get("dph_total"))
    end_date = first(offer.get("end_date"), offer.get("start_date") and None)
    return {
        "machine_id": MACHINE_ID,
        "listing_url": LISTING_URL,
        "price_per_hour": price,
        "reliability": first(offer.get("reliability2"), offer.get("reliability")),
        "tflops": offer.get("total_flops"),
        "dlperf": offer.get("dlperf"),
        "gpu_name": offer.get("gpu_name"),
        "gpu_ram_mb": offer.get("gpu_ram") or offer.get("gpu_total_ram"),
        "cpu_name": offer.get("cpu_name"),
        "cpu_cores": offer.get("cpu_cores") or offer.get("cpu_cores_effective"),
        "ram_mb": offer.get("cpu_ram"),
        "disk_gb": offer.get("disk_space"),
        "disk_name": offer.get("disk_name"),
        "inet_up_mbps": offer.get("inet_up"),
        "inet_down_mbps": offer.get("inet_down"),
        "listing_end": from_unix(end_date),
        "duration_seconds": offer.get("duration"),
        "rentable": offer.get("rentable"),
        "rented": offer.get("rented"),
        "availability": availability(offer),
    }


DISPLAY_KEYS = (
    "machine_id",
    "listing_url",
    "price_per_hour",
    "reliability",
    "tflops",
    "dlperf",
    "gpu_name",
    "gpu_ram_mb",
    "cpu_name",
    "cpu_cores",
    "ram_mb",
    "disk_gb",
    "disk_name",
    "inet_up_mbps",
    "inet_down_mbps",
    "listing_end",
    "duration_seconds",
    "rentable",
    "rented",
    "availability",
)


def merge(previous: dict, incoming: dict) -> dict:
    merged = {}
    used_fallback = []
    for key in DISPLAY_KEYS:
        value = incoming.get(key)
        if value is None or value == "":
            if key in previous and previous[key] not in (None, ""):
                merged[key] = previous[key]
                used_fallback.append(key)
            else:
                merged[key] = value
        else:
            merged[key] = value
    if used_fallback:
        print("using last known values for: " + ", ".join(used_fallback))
    return merged


def write_json(data: dict) -> bool:
    text = json.dumps(data, indent=2, allow_nan=False) + "\n"
    if JSON_PATH.exists() and JSON_PATH.read_text() == text:
        print("vast-live.json already up to date")
        return False
    tmp = JSON_PATH.with_suffix(".json.tmp")
    tmp.write_text(text)
    tmp.replace(JSON_PATH)
    print(f"wrote {JSON_PATH}")
    return True


def main() -> int:
    previous = load_previous()
    try:
        offer = pick_offer(fetch_offers())
        incoming = extract(offer)
    except Exception as exc:
        print(f"search failed; leaving last known values in place: {exc}", file=sys.stderr)
        return 0
    merged = merge(previous, incoming)
    merged["last_updated"] = iso(now_utc())
    write_json(merged)
    print(
        "machine={machine_id} price=${price} availability={avail}".format(
            machine_id=merged.get("machine_id"),
            price=merged.get("price_per_hour"),
            avail=merged.get("availability"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
