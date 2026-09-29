"""
Domain assertions layered on top of the shared validators.

The important local additions are:

* ``assert_instant_equals`` -- compares two ISO-8601 instants at millisecond
  resolution rather than by string identity, so a response is never failed merely
  for rendering a different sub-second width.
* ``assert_three_fractional_digits`` -- the one place a test asserts the rendered
  width, used only where the datetime convention itself is under test.
* ``total_count_of`` / ``page_of`` -- read pagination metadata out of ``meta``.
* ``assert_common_fields`` and ``assert_observation_fields`` -- the two shapes of
  common resource properties.
"""

import re
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

ISO_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# Instant handling
# ---------------------------------------------------------------------------
def parse_instant(value):
    """Parse an ISO-8601 UTC instant into an aware datetime, tolerating any width."""
    assert isinstance(value, str), f"expected an ISO-8601 instant string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"expected a trailing Z on instant {value!r}"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000000")[:6]
        body = f"{head}.{frac}"
    else:
        body = f"{body}.000000"
    return datetime.strptime(body, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)


def to_millis(value):
    """Truncate an ISO-8601 instant to whole milliseconds."""
    parsed = parse_instant(value)
    return parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)


def assert_instant_equals(actual, expected, label="instant"):
    """Assert two instants denote the same millisecond."""
    assert actual is not None, f"{label}: expected {expected!r} but got None"
    assert to_millis(actual) == to_millis(expected), (
        f"{label}: expected {expected!r} but got {actual!r}"
    )


def assert_three_fractional_digits(value, label="instant"):
    """Assert an instant is rendered with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label}: expected a string, got {value!r}"
    assert ISO_INSTANT_RE.match(value), (
        f"{label}: expected exactly three fractional digits and a trailing Z, "
        f"got {value!r}"
    )


def instant_plus_minutes(value, minutes):
    """Return the ISO-8601 rendering of an instant advanced by whole minutes."""
    moved = parse_instant(value) + timedelta(minutes=minutes)
    return render_instant(moved)


def instant_plus_hours(value, hours):
    """Return the ISO-8601 rendering of an instant advanced by whole hours."""
    moved = parse_instant(value) + timedelta(hours=hours)
    return render_instant(moved)


def render_instant(moment):
    """Render an aware datetime in the exact convention of the API."""
    text = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return f"{text[:-3]}Z"


def minutes_between(start, end):
    """Floored whole minutes from start to end."""
    delta = parse_instant(end) - parse_instant(start)
    return int(delta.total_seconds() // 60)


def hours_between(start, end):
    """Floored whole hours from start to end."""
    delta = parse_instant(end) - parse_instant(start)
    return int(delta.total_seconds() // 3600)


# ---------------------------------------------------------------------------
# Envelope / pagination helpers
# ---------------------------------------------------------------------------
def meta_of(response):
    """The ``meta`` object of any envelope."""
    body = response.json()
    assert "meta" in body, f"response body is missing meta: {body}"
    return body["meta"]


def total_count_of(response, expected_status=200):
    """The ``total_count`` reported in the meta of a paginated list response."""
    validate_success(response, expected_status)
    data, meta = validate_paginated(response)
    assert isinstance(meta["total_count"], int), (
        f"total_count must be an integer, got {meta['total_count']!r}"
    )
    return meta["total_count"]


def page_of(response, expected_status=200):
    """The (items, meta) pair of a paginated list response."""
    validate_success(response, expected_status)
    return validate_paginated(response)


def assert_total_count(response, expected, label="total_count"):
    actual = total_count_of(response)
    assert actual == expected, f"{label}: expected {expected} but got {actual}"


def assert_request_id_prefix(response):
    """The api_request_id is a server-generated identifier that starts with req_."""
    meta = meta_of(response)
    assert isinstance(meta.get("api_request_id"), str), (
        f"api_request_id must be a string, got {meta.get('api_request_id')!r}"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )


def assert_response_type(response, expected):
    body = response.json()
    assert body.get("response_type") == expected, (
        f"expected response_type {expected!r}, got {body.get('response_type')!r}"
    )


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------
def assert_common_fields(resource, expected_version=None, label="resource"):
    """A mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource.get("id")), (
        f"{label}: id must be a bare UUID, got {resource.get('id')!r}"
    )
    for field in ("created_at", "updated_at"):
        assert is_iso8601_timestamp(resource.get(field)), (
            f"{label}: {field} must be an ISO-8601 instant, got {resource.get(field)!r}"
        )
    assert isinstance(resource.get("version"), int), (
        f"{label}: version must be an integer, got {resource.get('version')!r}"
    )
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"{label}: expected version {expected_version}, got {resource['version']}"
        )


def assert_observation_fields(resource, label="observation"):
    """An append-only observation carries only id and created_at."""
    assert is_valid_uuid(resource.get("id")), (
        f"{label}: id must be a bare UUID, got {resource.get('id')!r}"
    )
    assert is_iso8601_timestamp(resource.get("created_at")), (
        f"{label}: created_at must be an ISO-8601 instant, "
        f"got {resource.get('created_at')!r}"
    )
    assert "updated_at" not in resource, (
        f"{label}: an append-only observation must not expose updated_at"
    )
    assert "version" not in resource, (
        f"{label}: an append-only observation must not expose version"
    )


def assert_no_type_prefix(identifier, label="id"):
    """Identifiers never carry a type prefix; the value is the bare UUID string."""
    assert is_valid_uuid(identifier), (
        f"{label}: expected a bare UUID with no type prefix, got {identifier!r}"
    )


# ---------------------------------------------------------------------------
# Money and integers
# ---------------------------------------------------------------------------
def assert_whole_cents(value, expected=None, label="money"):
    """Money is always an integer count of whole cents and never a decimal fraction."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label}: money must be an integer count of whole cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{label}: expected {expected} cents, got {value}"


def assert_ledger(surgeon, gross, credited, outstanding, label="ledger"):
    """Assert the three surgeon money-ledger fields together."""
    assert_whole_cents(
        surgeon.get("gross_billed_cents"), gross, f"{label}.gross_billed_cents"
    )
    assert_whole_cents(
        surgeon.get("credited_fee_cents"), credited, f"{label}.credited_fee_cents"
    )
    assert_whole_cents(
        surgeon.get("outstanding_fee_cents"),
        outstanding,
        f"{label}.outstanding_fee_cents",
    )
    assert (
        surgeon["outstanding_fee_cents"]
        == surgeon["gross_billed_cents"] - surgeon["credited_fee_cents"]
    ), f"{label}: outstanding must equal gross minus credited, got {surgeon}"


def assert_dimensions(tissue, disposition, custody, label="tissue"):
    """Assert both independent tissue state dimensions in one call."""
    assert tissue.get("disposition_status") == disposition, (
        f"{label}: expected disposition_status {disposition!r}, "
        f"got {tissue.get('disposition_status')!r}"
    )
    assert tissue.get("custody_status") == custody, (
        f"{label}: expected custody_status {custody!r}, "
        f"got {tissue.get('custody_status')!r}"
    )


def assert_one_decimal(value, expected, label="decimal"):
    """A one-decimal-place decimal comparison."""
    assert value is not None, f"{label}: expected {expected} but got None"
    assert abs(float(value) - float(expected)) < 0.05, (
        f"{label}: expected {expected} but got {value}"
    )


def assert_two_decimals(value, expected, label="decimal"):
    """A two-decimal-place decimal comparison."""
    assert value is not None, f"{label}: expected {expected} but got None"
    assert abs(float(value) - float(expected)) < 0.005, (
        f"{label}: expected {expected} but got {value}"
    )


__all__ = [
    "ISO_INSTANT_RE",
    "parse_instant",
    "to_millis",
    "assert_instant_equals",
    "assert_three_fractional_digits",
    "instant_plus_minutes",
    "instant_plus_hours",
    "render_instant",
    "minutes_between",
    "hours_between",
    "meta_of",
    "total_count_of",
    "page_of",
    "assert_total_count",
    "assert_request_id_prefix",
    "assert_response_type",
    "assert_common_fields",
    "assert_observation_fields",
    "assert_no_type_prefix",
    "assert_whole_cents",
    "assert_ledger",
    "assert_dimensions",
    "assert_one_decimal",
    "assert_two_decimals",
]
