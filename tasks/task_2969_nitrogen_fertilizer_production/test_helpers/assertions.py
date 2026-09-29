"""Domain assertion helpers.

Each numeric helper pins the decimal class PRD section 2.6 declares for that
quantity, with a tolerance of half the least significant unit so an answer that
is out by one unit in the last place always fails.
"""

import re

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    TOL_GAS_PRICE,
    TOL_HOURS,
    TOL_MMBTU,
    TOL_MONEY,
    TOL_PCT,
    TOL_TONS,
)
from .types import FREIGHT_FIELDS, POSITION_FIELDS

_ISO_INSTANT_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# Numeric precision classes
# ---------------------------------------------------------------------------
def assert_money(actual, expected, label="money"):
    """Currency per ton and currency totals carry 2 decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=TOL_MONEY), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_not_money(actual, wrong, label="money"):
    """Assert a two-decimal figure is NOT the given near-miss value."""
    assert abs(float(actual) - float(wrong)) > TOL_MONEY, (
        f"{label}: value {actual} must not equal the near-miss {wrong}"
    )


def assert_tons(actual, expected, label="tonnage"):
    """Tonnages carry 3 decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=TOL_TONS), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_gas_price(actual, expected, label="gas price"):
    """Gas unit prices and freight per ton carry 4 decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=TOL_GAS_PRICE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_hours(actual, expected, label="hours"):
    """Operating hours and averaging periods carry 1 decimal place."""
    assert actual == pytest.approx(expected, abs=TOL_HOURS), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_mmbtu(actual, expected, label="mmbtu"):
    """Gas volumes in MMBtu carry 1 decimal place."""
    assert actual == pytest.approx(expected, abs=TOL_MMBTU), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct(actual, expected, label="percentage"):
    """Activity figures and fractions carry 2 decimal places."""
    assert actual == pytest.approx(expected, abs=TOL_PCT), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_integer(actual, expected, label="counter"):
    """Whole-day quantities and counters are exact integers."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a JSON integer, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Identity, version and timestamp shape
# ---------------------------------------------------------------------------
def assert_identity_fields(entity, label="resource"):
    """Every persisted resource carries a server-minted UUID and created_at."""
    assert is_valid_uuid(entity.get("id")), (
        f"{label}.id must be a UUID, got {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{label}.created_at must be an ISO 8601 timestamp, got {entity.get('created_at')!r}"
    )
    assert _ISO_INSTANT_MILLIS.match(entity["created_at"]), (
        f"{label}.created_at must carry exactly three fractional digits, "
        f"got {entity['created_at']!r}"
    )


def assert_versioned_entity(entity, expected_version=None, label="resource"):
    """A versioned family carries updated_at and an integer version."""
    assert_identity_fields(entity, label)
    assert "updated_at" in entity, f"{label} must carry updated_at"
    assert isinstance(entity.get("version"), int), (
        f"{label}.version must be an integer, got {entity.get('version')!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {entity['version']}"
        )


def assert_immutable_entity(entity, label="resource"):
    """ProductLine and EmissionsReading carry only id and created_at."""
    assert_identity_fields(entity, label)
    assert "version" not in entity, f"{label} must not expose a version field"
    assert "updated_at" not in entity, f"{label} must not expose an updated_at field"


def assert_instant_with_millis(value, label="timestamp"):
    """An ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _ISO_INSTANT_MILLIS.match(value), (
        f"{label} must be an ISO 8601 UTC instant with three fractional digits, "
        f"got {value!r}"
    )


def assert_request_meta(response):
    """meta.api_request_id starts with req_ and the timestamp carries millis."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_with_millis(meta.get("api_request_timestamp"), "api_request_timestamp")


def assert_response_type(response, expected):
    """response_type is 'object' for a single resource and 'array' for a list."""
    body = response.json()
    assert body.get("response_type") == expected, (
        f"expected response_type {expected!r}, got {body.get('response_type')!r}"
    )


def assert_single_resource_meta_has_no_pagination(response):
    """Single-resource responses carry none of the four pagination fields."""
    meta = response.json()["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, (
            f"single-resource meta must not carry {field}, got {meta!r}"
        )


# ---------------------------------------------------------------------------
# Family-shaped assertions
# ---------------------------------------------------------------------------
def assert_position(
    asset,
    on_hand=None,
    reserved=None,
    seasonal_reserve=None,
    available=None,
    label="asset",
):
    """Assert any subset of the four derived storage position figures."""
    for field in POSITION_FIELDS:
        assert field in asset, f"{label} must expose {field}"
    if on_hand is not None:
        assert_tons(asset["on_hand_tons"], on_hand, f"{label}.on_hand_tons")
    if reserved is not None:
        assert_tons(asset["reserved_tons"], reserved, f"{label}.reserved_tons")
    if seasonal_reserve is not None:
        assert_tons(
            asset["seasonal_reserve_tons"],
            seasonal_reserve,
            f"{label}.seasonal_reserve_tons",
        )
    if available is not None:
        assert_tons(asset["available_tons"], available, f"{label}.available_tons")


def assert_freight_breakdown(
    shipment, base=None, surcharge=None, total=None, per_ton=None, label="shipment"
):
    """Assert any subset of the freight breakdown written at booking."""
    for field in FREIGHT_FIELDS:
        assert field in shipment, f"{label} must expose {field}"
    if base is not None:
        assert_money(shipment["base_freight_usd"], base, f"{label}.base_freight_usd")
    if surcharge is not None:
        assert_money(
            shipment["fuel_surcharge_usd"], surcharge, f"{label}.fuel_surcharge_usd"
        )
    if total is not None:
        assert_money(shipment["freight_total_usd"], total, f"{label}.freight_total_usd")
    if per_ton is not None:
        assert_gas_price(
            shipment["freight_per_ton_usd"], per_ton, f"{label}.freight_per_ton_usd"
        )


def assert_unpriced_freight(shipment, label="shipment"):
    """A movement that was never booked carries no freight figures."""
    for field in FREIGHT_FIELDS:
        assert shipment.get(field) is None, (
            f"{label}.{field} must be null before booking, got {shipment.get(field)!r}"
        )


def assert_nulls(entity, fields, label="resource"):
    """Assert every named field is JSON null."""
    for field in fields:
        assert entity.get(field, "__absent__") is None, (
            f"{label}.{field} must be null, got {entity.get(field, '__absent__')!r}"
        )


def assert_status(entity, expected, field="status", label="resource"):
    """Assert a state-machine field holds the expected value."""
    assert entity.get(field) == expected, (
        f"{label}.{field}: expected {expected!r}, got {entity.get(field)!r}"
    )


def assert_list_total(page_meta, expected_total, label="list"):
    """Assert the total_count a filtered list reports before its page window."""
    assert page_meta["total_count"] == expected_total, (
        f"{label}: expected total_count {expected_total}, got {page_meta['total_count']}"
    )


def ids_of(items):
    """Project the id field out of a list page."""
    return [item["id"] for item in items]
