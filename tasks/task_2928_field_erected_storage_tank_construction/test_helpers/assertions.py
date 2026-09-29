"""Domain assertion helpers for the storage tank construction API."""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .api_client import canonical_instant
from .constants import TANK_SUMMARY_KEYS

MONEY = 0.005
WEIGHT = 0.005
THICKNESS_3DP = 0.0005
SPACING_4DP = 0.00005
RATE_4DP = 0.00005
ANGLE_1DP = 0.05
SETTLEMENT_3DP = 0.0005


# --- Structural assertions --------------------------------------------
def assert_bare_uuid(value):
    """The PRD: "`id` is a server-minted UUID with no type prefix of any kind"."""
    assert isinstance(value, str), f"identifier must be a string, got {value!r}"
    assert is_valid_uuid(value), f"identifier is not a bare UUID: {value!r}"


def assert_common_fields(entity, expected_version=None):
    """Assert the four common properties every resource family carries.

    The PRD: "Every resource in the system carries the same four common
    properties." and "This applies to all fourteen resource families in the
    system without exception, so there is no resource that lacks `updated_at`
    or lacks `version`."
    """
    assert_bare_uuid(entity["id"])
    assert_three_fractional_digits(entity["created_at"])
    assert_three_fractional_digits(entity["updated_at"])
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_three_fractional_digits(value):
    """The PRD: timestamps are "ISO 8601 UTC timestamps with exactly three
    fractional-second digits"."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    assert value.endswith("Z"), f"timestamp must be UTC with a Z suffix: {value!r}"
    assert "." in value, f"timestamp must carry a fractional part: {value!r}"
    frac = value.split(".", 1)[1][:-1]
    assert len(frac) == 3, f"timestamp must carry exactly three fractional digits: {value!r}"


def assert_instant(actual, expected, label="instant"):
    """Compare two ISO-8601 UTC instants irrespective of fractional width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_object_envelope(response, expected_status=200):
    """Assert a single-resource envelope and return its data payload."""
    body = response.json()
    data = validate_success(response, expected_status)
    assert body["response_type"] == "object", (
        f"expected response_type 'object', got {body['response_type']!r}"
    )
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert_three_fractional_digits(meta["api_request_timestamp"])
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta, (
            f"single-resource reads and writes carry no pagination keys, found {key!r}"
        )
    return data


def assert_error_envelope_meta(response):
    """The PRD: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."."""
    body = response.json()
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must hold exactly the two request keys, got {sorted(meta.keys())}"
    )
    assert meta["api_request_id"].startswith("req_")
    assert body["data"]["message"].strip(), "error message must be non-empty"


# --- Numeric assertions ------------------------------------------------
def assert_money(actual, expected, label="amount"):
    assert actual == pytest.approx(expected, abs=MONEY), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_weight(actual, expected, label="weight"):
    assert actual == pytest.approx(expected, abs=WEIGHT), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_thickness(actual, expected, label="thickness"):
    assert actual == pytest.approx(expected, abs=THICKNESS_3DP), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_settlement(actual, expected, label="settlement metric"):
    assert actual == pytest.approx(expected, abs=SETTLEMENT_3DP), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_spacing(actual, expected, label="point_spacing_in"):
    assert actual == pytest.approx(expected, abs=SPACING_4DP), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_reject_rate(actual, expected):
    assert actual == pytest.approx(expected, abs=RATE_4DP), (
        f"weld_reject_rate: expected {expected}, got {actual}"
    )


def assert_angle(actual, expected, label="degrees"):
    assert actual == pytest.approx(expected, abs=ANGLE_1DP), (
        f"{label}: expected {expected}, got {actual}"
    )


# --- Composite domain assertions ---------------------------------------
def assert_tank_state(tank, phase=None, posture=None, nonconformance_count=None):
    """The tank's two independent state dimensions plus its nonconformance tally."""
    if phase is not None:
        assert tank["construction_phase"] == phase, (
            f"construction_phase: expected {phase}, got {tank['construction_phase']}"
        )
    if posture is not None:
        assert tank["quality_posture"] == posture, (
            f"quality_posture: expected {posture}, got {tank['quality_posture']}"
        )
    if nonconformance_count is not None:
        assert tank["open_nonconformance_count"] == nonconformance_count, (
            f"open_nonconformance_count: expected {nonconformance_count}, "
            f"got {tank['open_nonconformance_count']}"
        )


def assert_source_ledger(source, reserved, consumed, available):
    """The PRD: "`permitted_volume_gal` equals `available_volume_gal` plus
    `reserved_volume_gal` plus `consumed_volume_gal` must hold after every hop"."""
    assert_money(source["reserved_volume_gal"], reserved, "reserved_volume_gal")
    assert_money(source["consumed_volume_gal"], consumed, "consumed_volume_gal")
    assert_money(source["available_volume_gal"], available, "available_volume_gal")
    assert_money(
        source["available_volume_gal"]
        + source["reserved_volume_gal"]
        + source["consumed_volume_gal"],
        source["permitted_volume_gal"],
        "volume ledger identity",
    )


def assert_plan_costs(
    plan, water, disposal, subtotal, surcharge_pct, surcharge, total
):
    assert_money(plan["water_cost_usd"], water, "water_cost_usd")
    assert_money(plan["disposal_cost_usd"], disposal, "disposal_cost_usd")
    assert_money(plan["subtotal_usd"], subtotal, "subtotal_usd")
    assert_money(plan["permit_surcharge_pct"], surcharge_pct, "permit_surcharge_pct")
    assert_money(plan["surcharge_usd"], surcharge, "surcharge_usd")
    assert_money(plan["total_cost_usd"], total, "total_cost_usd")


def assert_steel_conservation(tank, lots):
    """The PRD: "the tank's `steel_received_lb` minus its `steel_allocated_lb`
    equals the sum of `remaining_weight_lb` across every lot of the tank"."""
    remaining = sum(lot["remaining_weight_lb"] for lot in lots)
    assert_weight(
        tank["steel_received_lb"] - tank["steel_allocated_lb"],
        remaining,
        "steel conservation identity",
    )


def assert_summary_keys(summary):
    """The progress read returns the flat object of eighteen named fields."""
    assert set(summary.keys()) == set(TANK_SUMMARY_KEYS), (
        "tank summary keys differ: "
        f"missing {sorted(set(TANK_SUMMARY_KEYS) - set(summary.keys()))}, "
        f"unexpected {sorted(set(summary.keys()) - set(TANK_SUMMARY_KEYS))}"
    )


def assert_list_total(response, expected_total):
    """Assert a list response's pre-pagination total_count."""
    from prd_bench_local_runner.testing import validate_paginated

    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"total_count: expected {expected_total}, got {meta['total_count']}"
    )
    return rows, meta


def assert_unchanged(before, after, *fields):
    """Assert a set of fields is byte-identical across two reads of a resource."""
    for field in fields:
        assert before[field] == after[field], (
            f"{field} changed: {before[field]!r} -> {after[field]!r}"
        )
