"""Allow-lists and normalisation shared by the query layer.

Nothing in the query layer may reference a table or column that is not listed
here. `bookings` is intentionally absent: it contains guest PII and the
read-only role cannot read it.
"""
from __future__ import annotations

import re

ALLOWED_TABLES: dict[str, frozenset[str]] = {
    "properties": frozenset({
        "id", "name", "address_line", "city", "region", "postal_code",
        "property_type", "description", "created_at",
    }),
    "rooms": frozenset({
        "id", "property_id", "unit_label", "room_type", "monthly_rent",
        "deposit", "size_sqm", "max_occupants", "available_from", "is_active",
        "description",
    }),
    "amenities": frozenset({"id", "name", "category"}),
    "room_amenities": frozenset({"room_id", "amenity_id"}),
    "policies": frozenset({"id", "property_id", "policy_type", "description"}),
    "room_blocks": frozenset({"id", "room_id", "start_date", "end_date", "reason"}),
    "room_blocked_ranges": frozenset({"room_id", "start_date", "end_date", "source"}),
}

FORBIDDEN_TABLES = frozenset({"bookings", "users", "sessions", "secrets"})

FORBIDDEN_KEYWORDS = frozenset({
    "insert", "update", "delete", "drop", "alter", "create", "grant", "revoke",
    "truncate", "copy", "call", "merge", "vacuum", "analyze", "attach", "detach",
    "pragma", "set", "reset", "listen", "notify", "load", "lock", "comment",
    "refresh", "reindex", "cluster", "security", "owner", "dblink",
})

FORBIDDEN_TOKENS = (
    "pg_", "information_schema", "pg_catalog", "pg_sleep", "pg_read_file",
    "pg_ls_dir", "lo_import", "lo_export", "current_setting", "set_config",
    "dblink", ";" , "--", "/*", "*/",
)

SORT_OPTIONS = {
    "rent_asc": "r.monthly_rent ASC, r.id ASC",
    "rent_desc": "r.monthly_rent DESC, r.id ASC",
    "size_desc": "r.size_sqm DESC NULLS LAST, r.id ASC",
    "newest": "r.id DESC",
}

AMENITY_SYNONYMS: dict[str, str] = {
    "wi-fi": "wifi", "wi fi": "wifi", "internet": "wifi", "wifi": "wifi",
    "fitness": "gym", "fitness center": "gym", "gym": "gym",
    "washer": "laundry", "washing machine": "laundry", "laundry": "laundry",
    "in-unit laundry": "laundry", "dryer": "laundry",
    "garage": "parking", "parking": "parking", "car park": "parking",
    "terrace": "balcony", "balcony": "balcony",
    "roof": "rooftop", "roof deck": "rooftop", "rooftop": "rooftop",
    "pet": "pet_friendly", "pets": "pet_friendly", "pet friendly": "pet_friendly",
    "pet-friendly": "pet_friendly", "dog": "pet_friendly", "cat": "pet_friendly",
    "swimming pool": "pool", "pool": "pool",
    "ac": "air_conditioning", "a/c": "air_conditioning",
    "air conditioning": "air_conditioning", "air-conditioning": "air_conditioning",
    "dishwasher": "dishwasher",
}

_WS = re.compile(r"\s+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def normalise_amenity(value: str) -> str:
    key = _WS.sub(" ", value.strip().lower())
    return AMENITY_SYNONYMS.get(key, key.replace(" ", "_").replace("-", "_"))


def normalise_amenities(values: list[str] | None) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        item = normalise_amenity(value)
        if item and item not in seen:
            seen.append(item)
    return seen
