"""Domain assertions and pure calculators derived from the PRD.

Nothing here talks to the API; every function takes an already-unwrapped
response body (the `data` payload) or plain values. The single place the
`data` envelope is unwrapped is the framework's own `validate_success` /
`validate_error` / `get_success_data`, which the tests call directly.
"""
import math
import re
from decimal import ROUND_HALF_UP, Decimal

from .constants import (
    COUNTRY_RATE_CENTS,
    COUNTRY_RISK_POINTS,
    DEFAULT_COUNTRY_RISK_POINTS,
    DEFAULT_RATE_CENTS,
    MATCH_POINT_WEIGHTS,
    SURCHARGE_TIERS,
    THRESHOLD_RELAXED,
    THRESHOLD_STRICT,
)

_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_ANY_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$"
)
_PERIOD_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


# ----------------------------------------------------------------------
# Timestamps
# ----------------------------------------------------------------------
def canonical_instant(value: str) -> str:
    """Normalise any ISO-8601 UTC instant to the PRD's exact wire form.

    The PRD requires "ISO-8601 in UTC with exactly three fractional-second
    digits and a trailing Z". Implementations legitimately differ only in how
    many fractional digits they emit for a value the tests supplied, so every
    *equality* comparison between an expected literal and an observed instant
    goes through this canonicaliser. The literal three-digit form itself is
    asserted separately by `assert_instant_format`.
    """
    assert isinstance(value, str), f"expected an ISO-8601 instant string, got {value!r}"
    match = _ANY_INSTANT_RE.match(value)
    assert match, f"not an ISO-8601 UTC instant: {value!r}"
    date_part, time_part, fraction, zone = match.groups()
    assert zone in ("Z", "+00:00", "+0000"), f"instant is not UTC: {value!r}"
    fraction = (fraction or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{fraction}Z"


def assert_instant_format(value: str, field: str = "timestamp") -> None:
    """Assert the literal wire form: three fractional digits and a Z."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _INSTANT_RE.match(value), (
        f"{field} must be ISO-8601 UTC with exactly three fractional-second "
        f"digits and a trailing Z, got {value!r}"
    )


def assert_instant(actual: str, expected: str, field: str = "timestamp") -> None:
    """Assert two instants denote the same moment, ignoring fraction width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field} mismatch: expected {expected!r}, got {actual!r}"
    )


def assert_null(value, field: str = "field") -> None:
    assert value is None, f"{field} must be null, got {value!r}"


def assert_period_month(value: str, field: str = "period_month") -> None:
    assert isinstance(value, str) and _PERIOD_MONTH_RE.match(value), (
        f"{field} must match YYYY-MM, got {value!r}"
    )


# ----------------------------------------------------------------------
# Common fields
# ----------------------------------------------------------------------
def assert_common_fields(entity: dict, name: str = "entity") -> None:
    """Assert the four common fields of a mutable resource."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{name} is missing common field {field!r}"
    assert isinstance(entity["version"], int) and not isinstance(entity["version"], bool), (
        f"{name}.version must be an integer, got {entity['version']!r}"
    )
    assert entity["version"] >= 1, f"{name}.version must start at 1, got {entity['version']}"
    assert_instant_format(entity["created_at"], f"{name}.created_at")
    assert_instant_format(entity["updated_at"], f"{name}.updated_at")


def assert_immutable_common_fields(entity: dict, name: str = "entity") -> None:
    """Assert an immutable resource carries only `id` and `created_at`.

    The PRD exempts two resources from the mutable common-field set, so
    `updated_at` and `version` must be absent rather than merely unused.
    """
    for field in ("id", "created_at"):
        assert field in entity, f"{name} is missing common field {field!r}"
    assert_instant_format(entity["created_at"], f"{name}.created_at")
    assert "updated_at" not in entity, f"{name} must not carry updated_at"
    assert "version" not in entity, f"{name} must not carry version"


def assert_version(entity: dict, expected: int, name: str = "entity") -> None:
    assert entity["version"] == expected, (
        f"{name}.version expected {expected}, got {entity['version']}"
    )


# ----------------------------------------------------------------------
# Money
# ----------------------------------------------------------------------
def assert_cents(value, field: str = "amount_cents") -> None:
    """Assert a money field is a whole-cent JSON integer, never a string."""
    assert not isinstance(value, str), (
        f"{field} must be a JSON number of whole cents, not a string: {value!r}"
    )
    assert not isinstance(value, bool), f"{field} must be an integer, got {value!r}"
    assert isinstance(value, int), (
        f"{field} must be an integer number of cents, got {value!r} ({type(value).__name__})"
    )


def assert_cents_equal(value, expected: int, field: str = "amount_cents") -> None:
    assert_cents(value, field)
    assert value == expected, f"{field} expected {expected} cents, got {value}"


def round_half_up(numerator: int, denominator: int) -> int:
    """Round a rational to the nearest integer, halves away from zero."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def round_half_up_value(value) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------
# Fee calculators
# ----------------------------------------------------------------------
def prorated_unit_fee_cents(monthly_fee_cents: int, active_days: int, days_in_month: int) -> int:
    """One unit's provisional fee: rounded half up before any summation."""
    return round_half_up(monthly_fee_cents * active_days, days_in_month)


def provisional_amount_cents(monthly_fee_cents: int, active_days_per_unit, days_in_month: int) -> int:
    """Sum of per-unit prorated fees, each rounded before the sum."""
    return sum(
        prorated_unit_fee_cents(monthly_fee_cents, days, days_in_month)
        for days in active_days_per_unit
    )


def final_amount_cents(monthly_fee_cents: int, units: int) -> int:
    """A final assessment charges the full monthly fee per unit, unrounded."""
    return monthly_fee_cents * units


# ----------------------------------------------------------------------
# Call-attempt calculators
# ----------------------------------------------------------------------
def billable_minutes(requested_duration_seconds: int) -> int:
    """At least one minute, otherwise the seconds rounded up to a minute."""
    return max(1, math.ceil(requested_duration_seconds / 60))


def rate_cents_per_minute(country_code: str) -> int:
    return COUNTRY_RATE_CENTS.get(str(country_code), DEFAULT_RATE_CENTS)


def estimated_base_cents(country_code: str, requested_duration_seconds: int) -> int:
    return rate_cents_per_minute(country_code) * billable_minutes(requested_duration_seconds)


def country_risk_points(country_code: str) -> int:
    return COUNTRY_RISK_POINTS.get(str(country_code), DEFAULT_COUNTRY_RISK_POINTS)


def surcharge_pct(day_subtotal_cents: int) -> int:
    """The single tier whose floor is the greatest floor at or below the subtotal."""
    applicable = 0
    for floor, pct in SURCHARGE_TIERS:
        if day_subtotal_cents >= floor:
            applicable = pct
    return applicable


def projected_day_total_cents(day_subtotal_cents: int) -> int:
    """Subtotal plus one half-up rounding of the surcharge component alone."""
    pct = surcharge_pct(day_subtotal_cents)
    return day_subtotal_cents + round_half_up(day_subtotal_cents * pct, 100)


# ----------------------------------------------------------------------
# Numbers, addresses and identifiers
# ----------------------------------------------------------------------
def expected_e164(npa_nxx: str, line_number: str) -> str:
    """The PRD derives e164 as "+1" followed by npa_nxx then line_number."""
    return f"+1{npa_nxx}{line_number}"


def normalize_comparison_value(value: str) -> str:
    """Uppercase, then strip every non-alphanumeric character."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def expected_normalized_location_key(address_line1: str, unit: str, postal_code: str) -> str:
    """UPPER(alnum(address_line1)) + "|" + UPPER(alnum(unit)) + "|" + postal_code."""
    return "|".join(
        (
            normalize_comparison_value(address_line1),
            normalize_comparison_value(unit or ""),
            postal_code,
        )
    )


def expected_match_points(claimed: dict, on_file: dict) -> int:
    """Sum the weights of the comparison points that agree after normalising.

    `claimed` and `on_file` are keyed by the five comparison point names.
    """
    total = 0
    for point, weight in MATCH_POINT_WEIGHTS.items():
        if normalize_comparison_value(claimed.get(point, "")) == normalize_comparison_value(
            on_file.get(point, "")
        ):
            total += weight
    return total


def expected_mismatch_fields(claimed: dict, on_file: dict) -> list:
    """The disagreeing comparison points, sorted ascending as plain strings."""
    return sorted(
        point
        for point in MATCH_POINT_WEIGHTS
        if normalize_comparison_value(claimed.get(point, ""))
        != normalize_comparison_value(on_file.get(point, ""))
    )


def match_threshold(csr_match_policy: str) -> int:
    return THRESHOLD_STRICT if csr_match_policy == "STRICT" else THRESHOLD_RELAXED


# ----------------------------------------------------------------------
# Number-block census
# ----------------------------------------------------------------------
def assert_block_census(
    block: dict,
    minted: int = None,
    available: int = None,
    reserved: int = None,
    assigned: int = None,
    parked: int = None,
) -> None:
    """Assert the census counters, and always the PRD's summation invariant.

    The PRD states the four status counters always sum to `minted_count`, so
    that invariant is checked on every census read regardless of which
    individual expectations the caller passed.
    """
    for field in (
        "minted_count",
        "available_count",
        "reserved_count",
        "assigned_count",
        "parked_count",
    ):
        assert field in block, f"number block is missing census field {field!r}"
        assert isinstance(block[field], int) and not isinstance(block[field], bool), (
            f"number block {field} must be an integer, got {block[field]!r}"
        )
    total = (
        block["available_count"]
        + block["reserved_count"]
        + block["assigned_count"]
        + block["parked_count"]
    )
    assert total == block["minted_count"], (
        "available_count + reserved_count + assigned_count + parked_count must "
        f"equal minted_count: {block['available_count']} + {block['reserved_count']} + "
        f"{block['assigned_count']} + {block['parked_count']} != {block['minted_count']}"
    )
    expectations = {
        "minted_count": minted,
        "available_count": available,
        "reserved_count": reserved,
        "assigned_count": assigned,
        "parked_count": parked,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert block[field] == expected, (
                f"number block {field} expected {expected}, got {block[field]}"
            )


def census_snapshot(block: dict) -> dict:
    """The five counters as a plain dict, for before/after comparisons."""
    return {
        field: block[field]
        for field in (
            "minted_count",
            "available_count",
            "reserved_count",
            "assigned_count",
            "parked_count",
        )
    }


# ----------------------------------------------------------------------
# List responses
# ----------------------------------------------------------------------
def validate_unpaginated(response, expected_status: int = 200) -> list:
    """Unwrap a list response without requiring pagination metadata.

    Kept alongside the framework's `validate_paginated` so a caller never has
    to fake pagination metadata for a collection that does not advertise it;
    every collection endpoint in this contract is paginated, so tests that
    care about the metadata use `validate_paginated` instead.
    """
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    rows = body["data"]
    assert isinstance(rows, list), f"expected data to be a list, got {type(rows).__name__}"
    return rows


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"meta.limit expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more expected {has_more}, got {meta['has_more']!r}"
    )


def ids_of(rows: list) -> list:
    return [row["id"] for row in rows]


def assert_ordered_by_created_at(rows: list, descending: bool = False) -> None:
    """Assert list ordering on `created_at`, canonicalised before comparing."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    expected = sorted(stamps, reverse=descending)
    assert stamps == expected, (
        f"rows are not ordered by created_at {'descending' if descending else 'ascending'}: {stamps}"
    )


def find_by(rows: list, **criteria) -> dict:
    """The single row matching every keyword criterion."""
    matches = [row for row in rows if all(row.get(k) == v for k, v in criteria.items())]
    assert len(matches) == 1, (
        f"expected exactly one row matching {criteria}, found {len(matches)}"
    )
    return matches[0]


def count_by(rows: list, **criteria) -> int:
    return len([row for row in rows if all(row.get(k) == v for k, v in criteria.items())])
