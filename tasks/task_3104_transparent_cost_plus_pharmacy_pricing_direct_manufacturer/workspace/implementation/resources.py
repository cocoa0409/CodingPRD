"""Resource record construction, wire serialisation and pagination.

Every resource carries the same four system-managed fields (PRD §2.4):
id, created_at, updated_at and version. Derived fields are computed on read
and are never stored (see registry.SERIALIZERS).
"""

import copy
from datetime import timedelta

from clock import now, now_iso, to_iso
from store import new_id

# Fields that are re-derived on read and therefore never persisted.
COMPUTED_FIELDS = {
    "drugs": (
        "demand_units_30d",
        "supply_units",
        "sourcing_status",
        "effective_unit_cost_cents",
        "ship_interval_days",
        "expansion_score",
    ),
    "prices": ("interval_days", "effective_per_unit_cents", "drug_sourcing_status"),
    "orders": (
        "acquisition_cost_cents",
        "is_blended_cost",
        "primary_units",
        "fallback_units",
        "markup_cents",
        "pharmacy_fee_cents",
        "shipping_fee_cents",
        "patient_price_cents",
    ),
    "comparisons": (
        "typical_retail_price_cents",
        "benefit_covered_price_cents",
        "stale_deadline_at",
    ),
    "claims": ("reserved_quantity",),
}

# Map name -> ordered list of (wire field, internal key) source mapping.
# Plain fields are read straight off the record; computed fields are filled by
# registry.SERIALIZERS after the plain pass.
EXPORT_MAP = {
    "manufacturers": ["manufacturer_name", "status"],
    "drugs": [
        "drug_name",
        "strength",
        "dosage_form",
        "is_controlled",
        "state",
        "packaging",
        "retail_reference_price_cents",
        "insured_reference_price_cents",
    ],
    "pharmacies": [
        "pharmacy_name",
        "domicile_state_code",
        "shipping_enabled",
        "status",
    ],
    "licenses": ["pharmacy_id", "state_code", "license_number", "status", "verified_at", "expiry_at"],
    "prices": [
        "drug_id",
        "manufacturer_id",
        "unit_cost_cents",
        "available_units",
        "reliability_tier",
        "packaging",
        "price_status",
        "sourcing_status",
    ],
    "patients": ["full_name", "email", "home_state_code", "status"],
    "prescribers": ["prescriber_name", "npi", "license_state_code", "status"],
    "prescriptions": [
        "patient_id",
        "prescriber_id",
        "drug_id",
        "ship_state_code",
        "total_refills_authorized",
        "status",
        "rejection_reason_code",
    ],
    "requests": ["prescription_id", "packaged_quantity", "consumed_quantity", "status"],
    "orders": [
        "prescription_id",
        "request_id",
        "pharmacy_id",
        "quantity",
        "ship_state_code",
        "paid_at",
        "status",
        "source_price_id",
        "sub_source_price_id",
        "retail_reference_price_cents",
        "insured_reference_price_cents",
    ],
    "shipments": [
        "order_id",
        "request_id",
        "shipment_seq",
        "status",
        "dispatch_at",
        "delivery_at",
    ],
    "claims": ["prescription_id", "claim_seq", "status", "denied_at", "denial_reason_code"],
    "comparisons": ["order_id", "status", "state"],
    "substantiations": [
        "order_id",
        "source_kind",
        "source_reference",
        "observed_at",
        "valid_until",
        "status",
    ],
}

# Derived internal state that is never exported to patients or operators.
INTERNAL_FIELDS = {
    "drugs": ("packaging_str", "reserved_total"),
    "prescriptions": ("refills_consumed",),
    "comparisons": (
        "comparison_created_at",
        "first_retail_cents",
        "first_benefit_cents",
        "ever_substantiated",
    ),
    "orders": ("cancel_reason_code",),
    "claims": ("order_id",),
    "requests": ("submitted_at",),
}


def blank_record(payload=None):
    """Build a record with only the system-managed fields stamped."""
    stamp = now()
    record = {
        "id": new_id(),
        "created_at": to_iso(stamp),
        "updated_at": to_iso(stamp),
        "version": 1,
    }
    if payload:
        record.update(payload)
    return record


def internal_of(kind, record):
    for field in INTERNAL_FIELDS.get(kind, ()):
        record.setdefault(field, None)
    return record


def touch(record):
    """A mutation refreshes updated_at and increments version (PRD §2.4)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()
    return record


def created_at_of(record):
    from clock import parse_iso

    return parse_iso(record.get("created_at"))


def updated_at_of(record):
    from clock import parse_iso

    return parse_iso(record.get("updated_at"))


def _plain_export(kind, record):
    out = {}
    for field in EXPORT_MAP[kind]:
        value = record.get(field)
        out[field] = value
    return out


def snapshot(kind, record):
    """The persisted shape of a record: system fields plus stored fields."""
    out = {
        "id": record.get("id"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "version": record.get("version", 1),
    }
    out.update(_plain_export(kind, record))
    for field in INTERNAL_FIELDS.get(kind, ()):
        if field in record:
            out[field] = copy.deepcopy(record[field])
    return out


def deep_copy(kind, record):
    if kind is None:
        return copy.deepcopy(record)
    cloned = {}
    for key, value in record.items():
        cloned[key] = copy.deepcopy(value)
    return cloned


def parse_pagination(query, total):
    """limit/offset per PRD §2.3: default 10, min 1, max 100, offset default 0."""
    limit = _as_int(query.get("limit"))
    offset = _as_int(query.get("offset"))
    if limit is None:
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset is None:
        offset = 0
    if offset < 0:
        offset = 0
    window = total - offset
    has_more = window > limit
    return {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def _as_int(value):
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def paginate(records):
    return records


def days_after(moment, days):
    return moment + timedelta(days=days)


# Book-keeping keys the server keeps on records but never exposes on the wire.
PRUNE_KEYS = frozenset(
    (
        "packaging_str",
        "reserved_total",
        "comparison_created_at",
        "first_retail_cents",
        "first_benefit_cents",
        "ever_substantiated",
        "cancel_reason_code",
        "submitted_at",
    )
)


def prune(value):
    """Strip server-side book-keeping from an outgoing payload."""
    if isinstance(value, dict):
        return {
            key: prune(item) for key, item in value.items() if key not in PRUNE_KEYS
        }
    if isinstance(value, list):
        return [prune(item) for item in value]
    return value