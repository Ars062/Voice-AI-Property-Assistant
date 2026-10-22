"""Typed, structured property search plan.

The LLM is only ever allowed to produce this object (validated by Pydantic).
This object is then compiled into parameterised SQL by `sql_builder`. The model
never writes SQL on the primary path.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config import settings
from property.schema import SORT_OPTIONS, normalise_amenities

SortBy = Literal["rent_asc", "rent_desc", "size_desc", "newest"]


class PropertyQueryPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    city: str | None = None
    property_name: str | None = None
    property_type: str | None = None
    room_type: str | None = None
    min_rent: Decimal | None = Field(default=None, ge=0)
    max_rent: Decimal | None = Field(default=None, ge=0)
    min_size_sqm: Decimal | None = Field(default=None, gt=0)
    min_occupants: int | None = Field(default=None, ge=1, le=20)
    amenities: list[str] = Field(default_factory=list)
    available_from: date | None = None
    available_to: date | None = None
    sort_by: SortBy = "rent_asc"
    limit: int = Field(default=10, ge=1)

    @field_validator("city", "property_name", "property_type", "room_type", mode="before")
    @classmethod
    def _clean_text(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("amenities", mode="before")
    @classmethod
    def _clean_amenities(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return normalise_amenities(list(value))

    @field_validator("limit")
    @classmethod
    def _cap_limit(cls, value: int) -> int:
        return max(1, min(int(value), settings.query_max_rows))

    @model_validator(mode="after")
    def _check_ranges(self) -> "PropertyQueryPlan":
        if self.min_rent is not None and self.max_rent is not None:
            if self.min_rent > self.max_rent:
                raise ValueError("min_rent cannot exceed max_rent")
        if self.available_from and self.available_to:
            if self.available_to <= self.available_from:
                raise ValueError("available_to must be after available_from")
        return self

    def is_empty(self) -> bool:
        return not any([
            self.city, self.property_name, self.property_type, self.room_type,
            self.min_rent, self.max_rent, self.min_size_sqm, self.min_occupants,
            self.amenities, self.available_from, self.available_to,
        ])

    def describe(self) -> str:
        parts: list[str] = []
        if self.room_type:
            parts.append(self.room_type)
        if self.city:
            parts.append(f"in {self.city}")
        if self.min_rent is not None and self.max_rent is not None:
            parts.append(f"${self.min_rent}-${self.max_rent}/month")
        elif self.max_rent is not None:
            parts.append(f"under ${self.max_rent}/month")
        elif self.min_rent is not None:
            parts.append(f"over ${self.min_rent}/month")
        if self.min_occupants:
            parts.append(f"for {self.min_occupants}+ people")
        if self.amenities:
            parts.append("with " + ", ".join(self.amenities))
        if self.available_from:
            parts.append(f"available from {self.available_from.isoformat()}")
        return ", ".join(parts) or "any property"

    @classmethod
    def sort_options(cls) -> tuple[str, ...]:
        return tuple(SORT_OPTIONS)
