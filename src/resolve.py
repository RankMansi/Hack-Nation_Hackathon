"""Module B, part 1: address -> legal jurisdiction stack via the Census Geocoder (never the postal city)."""

import csv
import io
import json
import re
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

from .config import ADDRESSES, CACHE, CITIES, OUTPUTS, STATES

BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
COORD_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
BENCHMARK = "Public_AR_Current"
VINTAGE = "Current_Current"

ALIASES = {
    "address_id": ["address_id", "id"],
    "street": ["street", "address", "site_address", "street_address"],
    "city": ["city", "postal_city"],
    "state": ["state", "st"],
    "zip": ["zip", "zipcode", "zip_code"],
    "year_built": ["year_built", "yearbuilt", "yr_built"],
    "units": ["units", "unit_count", "num_units"],
    "use_code": ["use_code", "usecode", "use"],
    "use_description": ["use_description"],
    "source_dataset": ["source_dataset"],
    "retrieved_at": ["retrieved_at"],
}


def _int(v: str) -> int | None:
    v = (v or "").strip()
    return int(float(v)) if re.fullmatch(r"\d+(\.0+)?", v) and int(float(v)) > 0 else None


def load_addresses() -> list[dict]:
    with ADDRESSES.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = {h.strip().lower(): h for h in reader.fieldnames}
        unmapped = [h for h in header if not any(h in a for a in ALIASES.values())]
        if unmapped:
            raise SystemExit(f"Address CSV has columns with no alias: {unmapped}")
        col = {k: next((header[a] for a in al if a in header), None) for k, al in ALIASES.items()}
        rows = []
        for r in reader:
            get = lambda k: (r.get(col[k]) or "").strip() if col[k] else ""
            rows.append({
                "address_id": get("address_id"),
                "street": get("street"),
                "postal_city": get("city"),
                "state": get("state"),
                "zip": get("zip"),
                "year_built": _int(get("year_built")),
                "units": _int(get("units")),
                "use_code": get("use_code") or None,
                "use_description": get("use_description") or None,
                "source_dataset": get("source_dataset") or None,
            })
    return rows


def clean_street(street: str) -> str:
    s = street.split("/")[0].strip().rstrip(".")
    s = re.sub(r"^(\d+)[A-Z]?\s*-\s*[\d.]+[A-Z]?\b", r"\1", s)
    s = re.sub(r"\s+(#|APT|UNIT|STE|LOT)\s*\S+$", "", s, flags=re.I)
    s = re.sub(r"\b0+(\d+(ST|ND|RD|TH))\b", r"\1", s, flags=re.I)
    s = re.sub(r"\bAV$", "AVE", s, flags=re.I)
    s = re.sub(r"\bMT\b", "MOUNT", s, flags=re.I)
    return s


def _post_batch(rows: list[tuple]) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("benchmark", BENCHMARK), ("vintage", VINTAGE)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n')
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="a.csv"\r\nContent-Type: text/csv\r\n\r\n{buf.getvalue()}\r\n')
    parts.append(f"--{boundary}--\r\n")
    req = urllib.request.Request(BATCH_URL, data="".join(parts).encode(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_batch(body: str) -> dict[str, dict]:
    out = {}
    for row in csv.reader(io.StringIO(body)):
        if len(row) >= 6 and row[2] == "Match":
            x, y = row[5].split(",")
            out[row[0]] = {"matched_address": row[4], "match_type": row[3], "lon": float(x), "lat": float(y)}
    return out


def geocode(addresses: list[dict]) -> dict[str, dict]:
    cache_file = CACHE / "census_batch.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    passes = [
        lambda a: (a["address_id"], a["street"], a["postal_city"], a["state"], a["zip"]),
        lambda a: (a["address_id"], clean_street(a["street"]), a["postal_city"], a["state"], a["zip"]),
        lambda a: (a["address_id"], clean_street(a["street"]), a["postal_city"], a["state"], ""),
    ]
    matches, bodies = {}, []
    try:
        for make in passes:
            todo = [make(a) for a in addresses if a["address_id"] not in matches]
            if not todo:
                break
            body = _post_batch(todo)
            bodies.append(body)
            matches.update(_parse_batch(body))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Census batch geocoding failed: {e}. Not falling back to the postal city.") from e
    (CACHE / "census_batch_raw.txt").write_text("\n\n".join(bodies))
    cache_file.write_text(json.dumps(matches, indent=1))
    return matches


def place_for(lon: float, lat: float) -> dict:
    q = urllib.parse.urlencode({
        "x": lon, "y": lat, "benchmark": BENCHMARK, "vintage": VINTAGE,
        "layers": "Incorporated Places,Counties,States", "format": "json",
    })
    for _ in range(3):
        try:
            with urllib.request.urlopen(f"{COORD_URL}?{q}", timeout=60) as resp:
                g = json.load(resp)["result"]["geographies"]
            state = (g.get("States") or [{}])[0].get("STUSAB")
            county = (g.get("Counties") or [{}])[0].get("NAME")
            places = g.get("Incorporated Places") or []
            place = places[0].get("BASENAME") if places else None
            return {"state": state, "county": county, "place": place}
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit(f"Census coordinates lookup failed for {lon},{lat}.")


def run() -> dict[str, dict]:
    addresses = load_addresses()
    matches = geocode(addresses)
    places_file = CACHE / "census_places.json"
    places = json.loads(places_file.read_text()) if places_file.exists() else {}
    todo = [aid for aid in matches if aid not in places]
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for aid, res in zip(todo, pool.map(lambda a: place_for(matches[a]["lon"], matches[a]["lat"]), todo)):
                places[aid] = res
        places_file.write_text(json.dumps(places, indent=1))

    stacks, unresolved = {}, []
    for a in addresses:
        aid = a["address_id"]
        geo = places.get(aid)
        state = geo["state"] if geo else a["state"]
        place = geo["place"] if geo else None
        city = f"{place}, {state}" if place in CITIES and CITIES[place] == state else None
        stacks[aid] = {
            **a,
            "geocoded": bool(geo),
            "matched_address": matches.get(aid, {}).get("matched_address"),
            "stack": {
                "state": state if state in STATES else None,
                "county": geo["county"] if geo else None,
                "place": place,
                "city": city,
            },
        }
        if not city:
            why = "no Census match" if not geo else f"Census place '{place}' is not one of the nine cities"
            unresolved.append(f"{aid}\t{a['street']}, {a['postal_city']}, {a['state']} {a['zip']}\t{why}")
    (CACHE / "stacks.json").write_text(json.dumps(stacks, indent=1))
    (OUTPUTS / "unresolved-addresses.txt").write_text("\n".join(unresolved) + ("\n" if unresolved else ""))
    resolved = sum(1 for s in stacks.values() if s["stack"]["city"])
    print(f"resolve: {len(addresses)} addresses, {len(matches)} geocoded, {resolved} in a covered city, {len(unresolved)} unresolved")
    return stacks
