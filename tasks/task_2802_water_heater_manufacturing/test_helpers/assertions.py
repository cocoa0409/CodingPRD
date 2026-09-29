"""Domain assertions shared by the suite.

These wrap the PRD's standing invariants (the four conserved ledgers, the
envelope shape, the system-field contract and the declared rounding widths) so a
single test line can check a whole rule instead of restating it.
"""

from decimal import Decimal

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
)

from .constants import HARDNESS_FACTORS


def assert_system_fields(resource, expected_version=None):
    """Assert the four system fields the PRD grants to every versioned resource."""
    assert is_valid_uuid(resource["id"]), f"id is not a bare UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"])
    assert is_iso8601_timestamp(resource["updated_at"])
    assert isinstance(resource["version"], int)
    assert resource["version"] >= 1
    if expected_version is not None:
        assert resource["version"] == expected_version


def assert_immutable_record_fields(record):
    """Assert the lining-inspection shape: id and created_at, no mutation pair."""
    assert is_valid_uuid(record["id"])
    assert is_iso8601_timestamp(record["created_at"])
    assert "updated_at" not in record, "an immutable record must not carry updated_at"
    assert "version" not in record, "an immutable record must not carry version"


def assert_envelope_meta(response):
    """Assert the two meta fields every response carries."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    return meta


def assert_error_envelope(response, expected_error_id):
    """Assert a rejected call carries the uniform error envelope and identifier."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "an error envelope's meta carries only the two request fields, "
        f"found {sorted(body['meta'].keys())}"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"an error envelope's data carries only error_id and message, "
        f"found {sorted(body['data'].keys())}"
    )
    assert body["data"]["message"].strip() != ""
    return validate_error(response, expected_error_id)


def assert_no_pagination_meta(response):
    """Assert a single-resource read omits the four pagination fields."""
    meta = response.json()["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"a single-resource response must omit meta.{field}"


def assert_created_at_ascending(rows):
    """Assert a list read is ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ASC order: {stamps}"


# ----------------------------------------------------------------------
# The four conserved ledgers
# ----------------------------------------------------------------------
def assert_tank_lot_ledger(lot):
    """planned_quantity == wip_quantity + good_quantity + scrapped_quantity."""
    total = lot["wip_quantity"] + lot["good_quantity"] + lot["scrapped_quantity"]
    assert lot["planned_quantity"] == total, (
        f"tank ledger broken: planned {lot['planned_quantity']} != "
        f"wip {lot['wip_quantity']} + good {lot['good_quantity']} + "
        f"scrapped {lot['scrapped_quantity']}"
    )


def assert_component_lot_ledger(lot):
    """quantity == remaining_quantity + consumed_quantity."""
    total = lot["remaining_quantity"] + lot["consumed_quantity"]
    assert lot["quantity"] == total, (
        f"component ledger broken: quantity {lot['quantity']} != "
        f"remaining {lot['remaining_quantity']} + consumed {lot['consumed_quantity']}"
    )


def assert_reserve_ledger(model):
    """warranty_reserve_balance_cents == accrued - paid."""
    expected = model["warranty_reserve_accrued_cents"] - model["warranty_paid_cents"]
    assert model["warranty_reserve_balance_cents"] == expected, (
        f"reserve ledger broken: balance {model['warranty_reserve_balance_cents']} != "
        f"accrued {model['warranty_reserve_accrued_cents']} - "
        f"paid {model['warranty_paid_cents']}"
    )


def assert_notice_ledger(campaign, notices):
    """notice_count equals the number of notice rows the campaign owns."""
    assert campaign["notice_count"] == len(notices), (
        f"notice ledger broken: notice_count {campaign['notice_count']} != "
        f"{len(notices)} notice rows"
    )


# ----------------------------------------------------------------------
# Precision and money
# ----------------------------------------------------------------------
def assert_decimal_places(value, places):
    """Assert a numeric value carries at most the declared number of decimals."""
    quantised = Decimal(str(value)).normalize()
    exponent = -quantised.as_tuple().exponent
    assert exponent <= places, (
        f"{value!r} carries {exponent} decimal places, more than the declared {places}"
    )


def assert_whole_cents(value):
    """Assert a money field is a whole integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"money must be a whole integer number of cents, got {value!r}"
    )


def approx4(expected):
    """Comparison helper for the 4-decimal-place fields."""
    return pytest.approx(expected, abs=1e-9)


def approx2(expected):
    """Comparison helper for the 2-decimal-place fields."""
    return pytest.approx(expected, abs=1e-9)


# ----------------------------------------------------------------------
# Derived domain values
# ----------------------------------------------------------------------
def assert_hardness_band(unit, expected_band):
    """Assert both halves of the water-chemistry classification agree."""
    assert unit["water_hardness_band"] == expected_band
    assert unit["hardness_factor"] == pytest.approx(HARDNESS_FACTORS[expected_band])


def assert_serial_number(unit, prefix, period, sequence):
    """Assert the minted serial matches prefix-period-sequence with 5 digits."""
    expected = f"{prefix}-{period.replace('-', '')}-{sequence:05d}"
    assert unit["serial_number"] == expected, (
        f"serial {unit['serial_number']!r} does not match the declared "
        f"pattern {expected!r}"
    )


def assert_version_advanced(before, after):
    """Assert a mutation produced a strictly greater version."""
    assert after > before, (
        f"an accepted mutation must advance the version: {before} -> {after}"
    )


def assert_version_unchanged(before, after):
    """Assert a rejected call left the version alone."""
    assert after == before, (
        f"a rejected call must not advance the version: {before} -> {after}"
    )
