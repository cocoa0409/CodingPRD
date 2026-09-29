"""Domain assertions for the Termite Bond & WDO Inspection API."""

import re

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import CONDUCIVE_CODES, parse_instant
from .types import (
    COMMON_FIELDS_IMMUTABLE,
    COMMON_FIELDS_MUTABLE,
    ENTITY_CONTRACTS,
    FORBIDDEN_IMMUTABLE_FIELDS,
)

MONEY_TOLERANCE = 0.005

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LICENSE_RE = re.compile(r"^[A-Z]{2}-\d{5}$")
_EPA_RE = re.compile(r"^\d{3,5}-\d{2,4}$")
_PERMIT_RE = re.compile(r"^FUM-\d{6}$")
_GRID_RE = re.compile(r"^[A-J](10|[1-9])$")


# ---------------------------------------------------------------------------
# Envelope and common-field shape
# ---------------------------------------------------------------------------


def assert_common_fields(data, entity="unknown"):
    """A mutable resource carries id, created_at, updated_at and version."""
    for field in COMMON_FIELDS_MUTABLE:
        assert field in data, "%s response is missing '%s'" % (entity, field)
    assert is_valid_uuid(data["id"]), "%s id is not a UUID: %r" % (entity, data["id"])
    assert_instant_shape(data["created_at"])
    assert_instant_shape(data["updated_at"])
    assert isinstance(data["version"], int), "%s version must be an integer" % entity
    assert data["version"] >= 1, "%s version starts at 1" % entity


def assert_immutable_record_fields(data, entity="unknown"):
    """An immutable record exposes only id and created_at, never updated_at/version."""
    for field in COMMON_FIELDS_IMMUTABLE:
        assert field in data, "%s response is missing '%s'" % (entity, field)
    assert is_valid_uuid(data["id"]), "%s id is not a UUID: %r" % (entity, data["id"])
    assert_instant_shape(data["created_at"])
    for field in FORBIDDEN_IMMUTABLE_FIELDS:
        assert field not in data, (
            "%s is immutable and must not expose '%s'" % (entity, field)
        )


def assert_entity_shape(data, entity):
    """Assert the declared domain fields and common-field tier for an entity."""
    domain_fields, immutable = ENTITY_CONTRACTS[entity]
    for field in domain_fields:
        assert field in data, "%s response is missing '%s'" % (entity, field)
    if immutable:
        assert_immutable_record_fields(data, entity)
    else:
        assert_common_fields(data, entity)


def assert_envelope_meta(response):
    """The success envelope's meta carries a req_-prefixed id and a 3-digit instant."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        "api_request_id must start with 'req_': %r" % meta["api_request_id"]
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert _INSTANT_RE.match(meta["api_request_timestamp"]), (
        "api_request_timestamp needs exactly three fractional digits: %r"
        % meta["api_request_timestamp"]
    )


def assert_error_envelope(response):
    """The error envelope's meta carries only api_request_id and timestamp."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "error meta must carry only api_request_id and api_request_timestamp: %r"
        % sorted(body["meta"].keys())
    )


# ---------------------------------------------------------------------------
# Scalar formats
# ---------------------------------------------------------------------------


def assert_instant_shape(value):
    """An instant is rendered with exactly three fractional digits and a Z."""
    assert isinstance(value, str), "instant must be a string, got %r" % (value,)
    assert _INSTANT_RE.match(value), (
        "instant must render as YYYY-MM-DDTHH:MM:SS.mmmZ, got %r" % value
    )


def assert_date_shape(value):
    """A calendar date is YYYY-MM-DD."""
    assert isinstance(value, str), "date must be a string, got %r" % (value,)
    assert _DATE_RE.match(value), "date must render as YYYY-MM-DD, got %r" % value


def assert_instant_equals(actual, expected):
    """Compare two instants by value, tolerating fractional-digit width."""
    assert actual is not None, "expected instant %r, got None" % (expected,)
    assert parse_instant(actual) == parse_instant(expected), (
        "expected instant %r, got %r" % (expected, actual)
    )


def assert_money(actual, expected):
    """Money is a JSON number equal to the expected value to the cent."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        "money must be a JSON number, got %r" % (actual,)
    )
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        "expected %.2f, got %r" % (expected, actual)
    )


def assert_two_decimal_places(value):
    """A money field carries at most two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        "money must be a JSON number, got %r" % (value,)
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        "money must carry at most two decimals, got %r" % (value,)
    )


def assert_license_number_shape(value):
    """A licence number is two uppercase letters, a hyphen and five digits."""
    assert _LICENSE_RE.match(value or ""), (
        "license_number must match AA-99999, got %r" % (value,)
    )


def assert_epa_number_shape(value):
    """An EPA number is three to five digits, a hyphen, then two to four digits."""
    assert _EPA_RE.match(value or ""), (
        "product_epa_number must match 999-99, got %r" % (value,)
    )


def assert_permit_number_shape(value):
    """A fumigation permit is the letters FUM, a hyphen and six digits."""
    assert _PERMIT_RE.match(value or ""), (
        "fumigation_permit_number must match FUM-999999, got %r" % (value,)
    )


def assert_grid_ref_shape(value):
    """A grid_ref is a column letter A-J followed by a row number 1-10."""
    assert _GRID_RE.match(value or ""), "grid_ref must match A1..J10, got %r" % (value,)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def validate_unpaginated(response, expected_status=200):
    """Validate a 2xx list response without assuming a pagination block."""
    assert response.status_code == expected_status, (
        "Expected %d, got %d: %s"
        % (expected_status, response.status_code, response.text)
    )
    body = response.json()
    assert body["response_type"] == "array", (
        "list responses declare response_type 'array', got %r" % body["response_type"]
    )
    assert isinstance(body["data"], list), "list response data must be an array"
    return body["data"]


def assert_page(response, expected_total, expected_rows=None, expected_has_more=None):
    """Validate a paginated collection read and its meta block."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        "expected total_count %d, got %d" % (expected_total, meta["total_count"])
    )
    if expected_rows is not None:
        assert len(rows) == expected_rows, (
            "expected %d rows on the page, got %d" % (expected_rows, len(rows))
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            "expected has_more %r, got %r" % (expected_has_more, meta["has_more"])
        )
    return rows, meta


def assert_created_at_ascending(rows):
    """Collections come back oldest row first."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "rows must be ordered by created_at ascending"


def assert_station_index_ascending(rows):
    """The station listing beneath a plan is ordered by station_index ascending."""
    indexes = [row["station_index"] for row in rows]
    assert indexes == sorted(indexes), (
        "stations must be ordered by station_index ascending, got %r" % indexes
    )


def assert_ids_equal(rows, expected_ids):
    """The page holds exactly these ids, in this order."""
    assert [row["id"] for row in rows] == list(expected_ids), (
        "expected ids %r, got %r" % (list(expected_ids), [row["id"] for row in rows])
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_repair_liability_conserved(bond):
    """PRD 2.8: cap == paid + reserved + remaining, exactly, in every status."""
    total = (
        bond["claims_paid_to_date_usd"]
        + bond["reserved_claim_amount_usd"]
        + bond["remaining_repair_cap_usd"]
    )
    assert total == pytest.approx(bond["repair_liability_cap_usd"], abs=MONEY_TOLERANCE), (
        "conservation law broken: cap %r != paid %r + reserved %r + remaining %r"
        % (
            bond["repair_liability_cap_usd"],
            bond["claims_paid_to_date_usd"],
            bond["reserved_claim_amount_usd"],
            bond["remaining_repair_cap_usd"],
        )
    )


def assert_conducive_counts_conserved(prop):
    """PRD 2.8: open + waived == total on every structure."""
    assert (
        prop["open_conducive_condition_count"]
        + prop["waived_conducive_condition_count"]
        == prop["total_conducive_condition_count"]
    ), (
        "count law broken: open %r + waived %r != total %r"
        % (
            prop["open_conducive_condition_count"],
            prop["waived_conducive_condition_count"],
            prop["total_conducive_condition_count"],
        )
    )


def assert_bond_money(
    bond,
    base_premium_usd=None,
    repair_liability_cap_usd=None,
    annual_premium_usd=None,
    claims_paid_to_date_usd=None,
    reserved_claim_amount_usd=None,
    remaining_repair_cap_usd=None,
):
    """Assert whichever bond money fields the caller named, then the invariant."""
    expectations = (
        ("base_premium_usd", base_premium_usd),
        ("repair_liability_cap_usd", repair_liability_cap_usd),
        ("annual_premium_usd", annual_premium_usd),
        ("claims_paid_to_date_usd", claims_paid_to_date_usd),
        ("reserved_claim_amount_usd", reserved_claim_amount_usd),
        ("remaining_repair_cap_usd", remaining_repair_cap_usd),
    )
    for field, expected in expectations:
        if expected is not None:
            assert_money(bond[field], expected)
    assert_repair_liability_conserved(bond)


def assert_claim_money(
    claim,
    eligible_damage_usd=None,
    excluded_pre_existing_usd=None,
    deductible_usd=None,
    projected_payout_usd=None,
    approved_payout_usd=None,
):
    """Assert whichever claim money fields the caller named."""
    expectations = (
        ("eligible_damage_usd", eligible_damage_usd),
        ("excluded_pre_existing_usd", excluded_pre_existing_usd),
        ("deductible_usd", deductible_usd),
        ("projected_payout_usd", projected_payout_usd),
        ("approved_payout_usd", approved_payout_usd),
    )
    for field, expected in expectations:
        if expected is not None:
            assert_money(claim[field], expected)


def assert_renewal_invoice(
    invoice,
    base_renewal_fee_usd=None,
    inspection_fee_usd=None,
    conducive_surcharge_usd=None,
    late_fee_usd=None,
    invoice_total_usd=None,
):
    """Assert the four priced components and that the total is their exact sum."""
    expectations = (
        ("base_renewal_fee_usd", base_renewal_fee_usd),
        ("inspection_fee_usd", inspection_fee_usd),
        ("conducive_surcharge_usd", conducive_surcharge_usd),
        ("late_fee_usd", late_fee_usd),
        ("invoice_total_usd", invoice_total_usd),
    )
    for field, expected in expectations:
        if expected is not None:
            assert_money(invoice[field], expected)
    component_sum = (
        invoice["base_renewal_fee_usd"]
        + invoice["inspection_fee_usd"]
        + invoice["conducive_surcharge_usd"]
        + invoice["late_fee_usd"]
    )
    assert invoice["invoice_total_usd"] == pytest.approx(
        component_sum, abs=MONEY_TOLERANCE
    ), (
        "invoice_total_usd %r must be the exact sum of the four rounded components (%r)"
        % (invoice["invoice_total_usd"], component_sum)
    )


def assert_status(data, expected_status, entity="resource"):
    """Assert a resource's status."""
    assert data["status"] == expected_status, (
        "expected %s status %r, got %r" % (entity, expected_status, data["status"])
    )


def assert_version(data, expected_version, entity="resource"):
    """Assert a resource's version counter."""
    assert data["version"] == expected_version, (
        "expected %s version %d, got %r" % (entity, expected_version, data["version"])
    )


def assert_conducive_code_valid(code):
    """A waiver or notation code is drawn from the declared domain, excluding NONE."""
    assert code in CONDUCIVE_CODES, "unknown conducive_code %r" % (code,)
