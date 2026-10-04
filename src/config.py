from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INCOMING = ROOT / "data" / "incoming"
CACHE = ROOT / "data" / "cache"
OUTPUTS = ROOT / "outputs"

MANIFEST = RAW / "corpus" / "corpus_manifest.csv"
CORPUS_DIR = RAW / "corpus"
ADDRESSES = RAW / "data" / "sample_addresses.csv"
CHANGE_TESTS = RAW / "dev" / "change_tests.json"

DEFAULT_AS_OF = "2026-10-01"

CATEGORIES = [
    "rent_increase_limits",
    "just_cause_eviction",
    "security_deposits",
    "application_screening_fees",
    "screening_restrictions",
    "algorithmic_rent_setting",
]

CATEGORY_LABELS = {
    "rent_increase_limits": "Rent increase limits",
    "just_cause_eviction": "Just-cause eviction",
    "security_deposits": "Security deposits",
    "application_screening_fees": "Application & screening fees",
    "screening_restrictions": "Screening restrictions",
    "algorithmic_rent_setting": "Algorithmic rent-setting",
}

STATES = {"CA": "California", "NJ": "New Jersey", "MA": "Massachusetts"}

CITIES = {
    "Los Angeles": "CA",
    "San Francisco": "CA",
    "San Diego": "CA",
    "Berkeley": "CA",
    "Santa Ana": "CA",
    "Jersey City": "NJ",
    "Hoboken": "NJ",
    "Newark": "NJ",
    "Boston": "MA",
    "Cambridge": "MA",
}

JURISDICTIONS = list(STATES) + [f"{c}, {s}" for c, s in CITIES.items()]
