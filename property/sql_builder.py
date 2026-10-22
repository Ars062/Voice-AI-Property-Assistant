"""Compile a validated `PropertyQueryPlan` into parameterised SQL.

Only fixed, allow-listed table/column names are interpolated. Every user value
is passed as a bind parameter.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

from property.query_plan import PropertyQueryPlan
from property.schema import SORT_OPTIONS

_SELECT = """
SELECT
    r.id,
    r.unit_label,
    r.room_type,
    r.monthly_rent,
    r.deposit,
    r.size_sqm,
    r.max_occupants,
    r.available_from,
    r.description,
    p.id   AS property_id,
    p.name AS property_name,
    p.city,
    p.region,
    p.address_line,
    COALESCE(
        array_agg(DISTINCT a.name ORDER BY a.name)
        FILTER (WHERE a.name IS NOT NULL),
        '{}'
    ) AS amenities
FROM rooms r
JOIN properties p ON p.id = r.property_id
LEFT JOIN room_amenities ra ON ra.room_id = r.id
LEFT JOIN amenities a ON a.id = ra.amenity_id
"""

_GROUP = "GROUP BY r.id, p.id"
_LIMIT = "LIMIT :limit"


def build_search(plan: PropertyQueryPlan) -> tuple[TextClause, dict]:
    where: list[str] = ["r.is_active IS TRUE"]
    params: dict = {}

    if plan.city:
        where.append("p.city ILIKE :city")
        params["city"] = f"%{plan.city}%"
    if plan.property_name:
        where.append("p.name ILIKE :property_name")
        params["property_name"] = f"%{plan.property_name}%"
    if plan.property_type:
        where.append("p.property_type ILIKE :property_type")
        params["property_type"] = f"%{plan.property_type}%"
    if plan.room_type:
        where.append("r.room_type ILIKE :room_type")
        params["room_type"] = f"%{plan.room_type}%"
    if plan.min_rent is not None:
        where.append("r.monthly_rent >= :min_rent")
        params["min_rent"] = plan.min_rent
    if plan.max_rent is not None:
        where.append("r.monthly_rent <= :max_rent")
        params["max_rent"] = plan.max_rent
    if plan.min_size_sqm is not None:
        where.append("r.size_sqm >= :min_size_sqm")
        params["min_size_sqm"] = plan.min_size_sqm
    if plan.min_occupants is not None:
        where.append("r.max_occupants >= :min_occupants")
        params["min_occupants"] = plan.min_occupants

    for index, amenity in enumerate(plan.amenities):
        key = f"amenity_{index}"
        where.append(
            "EXISTS ("
            "  SELECT 1 FROM room_amenities fra"
            "  JOIN amenities fa ON fa.id = fra.amenity_id"
            f"  WHERE fra.room_id = r.id AND fa.name = :{key}"
            ")"
        )
        params[key] = amenity

    if plan.available_from and plan.available_to:
        where.append("r.available_from <= :avail_from")
        where.append(
            "NOT EXISTS ("
            "  SELECT 1 FROM room_blocked_ranges br"
            "  WHERE br.room_id = r.id"
            "    AND br.start_date < :avail_to"
            "    AND br.end_date > :avail_from"
            ")"
        )
        params["avail_from"] = plan.available_from
        params["avail_to"] = plan.available_to
    elif plan.available_from:
        where.append("r.available_from <= :avail_from")
        where.append(
            "NOT EXISTS ("
            "  SELECT 1 FROM room_blocked_ranges br"
            "  WHERE br.room_id = r.id"
            "    AND br.start_date <= :avail_from"
            "    AND br.end_date > :avail_from"
            ")"
        )
        params["avail_from"] = plan.available_from
    elif plan.available_to:
        where.append("r.available_from <= :avail_to")
        params["avail_to"] = plan.available_to

    sql = (
        _SELECT
        + "WHERE " + " AND ".join(where) + "\n"
        + _GROUP + "\n"
        + "ORDER BY " + SORT_OPTIONS[plan.sort_by] + "\n"
        + _LIMIT
    )
    params["limit"] = plan.limit
    return text(sql), params
