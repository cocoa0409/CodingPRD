"""Entity assertions and domain invariant checkers.

Only properties the PRD states unambiguously are asserted here.  Fields whose
presence or default the PRD leaves to the implementer are deliberately not
checked.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BAND_MAX_DRAFT_FEET,
    BAND_TOW_SIZE_CAP,
    CLEANLINESS_RANK,
)


# ---------------------------------------------------------------------------
# Common property helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """Every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert "_" not in str(data.get("id", "")), "id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}")


def assert_immutable_reference_fields(data: dict):
    """The four immutable reference kinds carry ONLY id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable reference rows must not emit updated_at"
    assert "version" not in data, "immutable reference rows must not emit version"


def assert_three_fractional_digits(timestamp: str):
    """PRD §2.4: ISO 8601 UTC timestamp with three fractional digits."""
    assert is_iso8601_timestamp(timestamp), f"{timestamp!r} must be ISO 8601"
    assert "." in timestamp, f"{timestamp!r} must carry fractional seconds"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"{timestamp!r} must carry exactly three fractional digits"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_shipper(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0


def assert_commodity(data: dict):
    assert_immutable_reference_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["commodity_group"] in (
        "GRAIN", "COAL", "CHEMICAL", "PETROLEUM", "FERTILIZER", "AGGREGATE")
    assert data["residue_class"] in ("CLEAN", "DUSTY", "OILY", "TOXIC")
    assert isinstance(data["hazard_flag"], bool)
    assert float(data["stowage_factor"]) > 0


def assert_compatibility_rule(data: dict):
    assert_immutable_reference_fields(data)
    assert data["required_cleaning_level"] in ("NONE", "SWEEP", "WASH", "STEAM_CERT")
    assert isinstance(data["prohibited"], bool)


def assert_fuel_index_posting(data: dict):
    assert_immutable_reference_fields(data)
    assert isinstance(data["diesel_price_cents_per_gallon"], int)
    assert data["diesel_price_cents_per_gallon"] > 0


def assert_river_stage_reading(data: dict):
    assert_immutable_reference_fields(data)
    band = data["draft_restriction_band"]
    assert band in ("HIGH_WATER", "NORMAL", "LOW", "CRITICAL")
    assert float(data["max_draft_feet"]) == BAND_MAX_DRAFT_FEET[band], (
        f"band {band} fixes max_draft_feet {BAND_MAX_DRAFT_FEET[band]}, "
        f"got {data['max_draft_feet']}")
    assert data["tow_size_cap_barges"] == BAND_TOW_SIZE_CAP[band], (
        f"band {band} fixes tow_size_cap_barges {BAND_TOW_SIZE_CAP[band]}, "
        f"got {data['tow_size_cap_barges']}")


def assert_tariff_filing(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "FILED", "EFFECTIVE", "SUPERSEDED")
    assert isinstance(data["fuel_surcharge_table"], list) and data["fuel_surcharge_table"]
    assert float(data["base_rate_cents_per_ton_mile"]) > 0


def assert_barge(data: dict):
    assert_common_fields(data)
    assert isinstance(data["hull_number"], str) and data["hull_number"]
    assert data["operational_status"] in ("IDLE", "FLEETED", "IN_TOW", "OUT_OF_SERVICE")
    assert data["cleanliness_status"] in CLEANLINESS_RANK
    assert isinstance(data["capacity_tons"], int) and data["capacity_tons"] > 0
    assert float(data["light_draft_feet"]) > 0
    assert float(data["tons_per_inch_immersion"]) > 0


def assert_cleaning_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("barge_id", ""))
    assert data["status"] in ("ORDERED", "IN_PROGRESS", "COMPLETED", "FAILED_INSPECTION")
    assert data["required_cleaning_level"] in ("NONE", "SWEEP", "WASH", "STEAM_CERT")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_fleeting_berth(data: dict):
    assert_common_fields(data)
    assert isinstance(data["capacity_barges"], int) and data["capacity_barges"] > 0
    assert isinstance(data["occupied_barge_count"], int)
    assert data["occupied_barge_count"] >= 0, "occupancy may never go negative"


def assert_fleeting_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("barge_id", ""))
    assert is_valid_uuid(data.get("fleeting_berth_id", ""))
    assert data["status"] in ("RESERVED", "RELEASED", "CANCELLED")
    assert isinstance(data["estimated_fee_cents"], int)
    assert isinstance(data["billable_days"], int) and data["billable_days"] >= 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_lock(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert isinstance(data["granted_reservation_count"], int)
    assert data["granted_reservation_count"] >= 0


def assert_lock_reservation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("lock_id", ""))
    assert is_valid_uuid(data.get("tow_id", ""))
    assert data["status"] in (
        "REQUESTED", "GRANTED", "IN_CHAMBER", "CLEARED", "DENIED", "CANCELLED")
    assert data["priority_class"] in ("PRIORITY", "COMMERCIAL", "RECREATIONAL")
    assert isinstance(data["cut_count"], int) and data["cut_count"] >= 1
    assert isinstance(data["delay_minutes"], int) and data["delay_minutes"] >= 0


def assert_tow(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "BUILDING", "SEALED", "UNDERWAY", "DELAYED", "ARRIVED", "BROKEN_UP")
    assert isinstance(data["barge_count"], int) and data["barge_count"] >= 0
    assert isinstance(data["total_loaded_tons"], int) and data["total_loaded_tons"] >= 0
    assert float(data["max_draft_feet"]) >= 0
    assert isinstance(data["accrued_delay_minutes"], int)
    assert data["accrued_delay_minutes"] >= 0
    assert isinstance(data["pending_lock_reservation_count"], int)
    assert data["pending_lock_reservation_count"] >= 0


def assert_barge_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("tow_id", ""))
    assert is_valid_uuid(data.get("barge_id", ""))
    assert is_valid_uuid(data.get("freight_contract_id", ""))
    assert data["status"] in ("PLANNED", "CONFIRMED", "LOADED", "DISCHARGED", "DROPPED")
    assert data["discharge_status"] in (
        "NOT_ARRIVED", "ARRIVED", "UNLOADING", "COMPLETED", "DISPUTED")
    assert isinstance(data["cut_position"], int) and data["cut_position"] > 0
    assert isinstance(data["loaded_tons"], int) and data["loaded_tons"] > 0


def assert_freight_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("shipper_id", ""))
    assert is_valid_uuid(data.get("commodity_id", ""))
    assert data["movement_status"] in (
        "DRAFT", "BOOKED", "ACTIVE", "IN_TRANSIT", "DISCHARGED", "CLOSED", "CANCELLED")
    assert data["billing_status"] in (
        "NOT_BILLED", "INVOICED", "ADJUSTED", "PAID", "VOID")
    assert data["claim_settlement_basis"] in ("DEDUCTIBLE", "FRANCHISE")
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0


def assert_cargo_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("freight_contract_id", ""))
    assert is_valid_uuid(data.get("barge_assignment_id", ""))
    assert data["claim_type"] in ("SHORTAGE", "DAMAGE", "CONTAMINATION")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "ASSESSED",
        "APPROVED", "DENIED", "WITHDRAWN")
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["settlement_cents"], int) and data["settlement_cents"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_charge_breakdown_shape(data: dict, expected_variant: str):
    """Every charge-breakdown payload field named in PRD §3.8."""
    assert data["variant"] == expected_variant, (
        f"expected variant {expected_variant}, got {data.get('variant')!r}")
    for field in (
        "billable_line_count", "linehaul_cents", "fuel_surcharge_cents",
        "fleeting_fee_cents", "cleaning_fee_cents", "demurrage_cents",
        "subtotal_cents", "volume_rebate_cents", "claim_credit_cents", "total_cents",
    ):
        assert field in data, f"charge breakdown must carry {field}"
        assert isinstance(data[field], int), f"{field} must be a whole-cent integer"


def assert_waterfall_consistent(data: dict):
    """PRD §3.8 waterfall: subtotal is the five buckets; total is subtotal minus
    the rebate minus the claim credit, floored at zero."""
    expected_subtotal = (
        data["linehaul_cents"] + data["fuel_surcharge_cents"] + data["fleeting_fee_cents"]
        + data["cleaning_fee_cents"] + data["demurrage_cents"]
    )
    assert data["subtotal_cents"] == expected_subtotal, (
        f"subtotal must be the sum of the five buckets: expected {expected_subtotal}, "
        f"got {data['subtotal_cents']}")
    expected_total = max(
        0,
        data["subtotal_cents"] - data["volume_rebate_cents"] - data["claim_credit_cents"],
    )
    assert data["total_cents"] == expected_total, (
        f"total must be subtotal minus rebate minus claim credit floored at 0: "
        f"expected {expected_total}, got {data['total_cents']}")


def assert_tow_rollup(tow: dict, assignments):
    """PRD §3.5: the rollup runs over PLANNED, CONFIRMED and LOADED assignments."""
    active = [a for a in assignments if a["status"] in ("PLANNED", "CONFIRMED", "LOADED")]
    assert tow["barge_count"] == len(active), (
        f"barge_count must count the active assignments: expected {len(active)}, "
        f"got {tow['barge_count']}")
    assert tow["total_loaded_tons"] == sum(a["loaded_tons"] for a in active), (
        "total_loaded_tons must sum the active assignments' loaded_tons")
    expected_draft = max([float(a["barge_draft_feet"]) for a in active], default=0.0)
    assert abs(float(tow["max_draft_feet"]) - expected_draft) < 1e-9, (
        f"max_draft_feet must be the greatest active barge_draft_feet: "
        f"expected {expected_draft}, got {tow['max_draft_feet']}")


def parse_instant(value: str):
    """Parse an ISO 8601 UTC instant, tolerating an optional fractional part."""
    from datetime import datetime, timezone

    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant"):
    """Compare two ISO 8601 instants by value, not by serialisation."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}")
