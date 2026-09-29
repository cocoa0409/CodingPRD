"""
Domain assertion helpers for the Venue Music Licensing API.

Three envelope facts govern every helper here, and every test in the suite:

1. ``validate_success(response)`` **already unwraps the envelope exactly once**.
   It returns the value of ``data``, so a caller writes
   ``venue = validate_success(resp)`` and then ``venue["status"]`` — never
   ``validate_success(resp)["data"]``.
2. ``validate_paginated(response)`` takes only the response and returns the
   two-tuple ``(rows, meta)``, where ``meta`` carries the four pagination fields
   PRD §2.3 requires on every list endpoint.  Because that section says "Every
   endpoint that returns a list accepts two query parameters" and "List
   responses carry four pagination fields inside the envelope's ``meta``
   object", every list read in this suite is a paginated read.
   :func:`validate_unpaginated_list` exists for the shape where a list arrives
   without those ``meta`` fields, so a caller never has to hand-roll it.
3. Timestamps are never compared byte-for-byte.  PRD §2.2 pins the envelope's
   own timestamp to "three fractional digits", but resource instants may be
   echoed with or without a fractional part.  :func:`canonical_instant`
   normalises both forms to a single comparable value, and
   :func:`assert_instant_equals` is the only sanctioned way to compare two
   instants.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

Row = Dict[str, Any]

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?)?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


# ─── Instants and dates (PRD §2.4, §2.5) ──────────────────────────────────


def canonical_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant or date into a timezone-aware ``datetime``.

    Accepts every width the API may legitimately echo: a bare calendar date, a
    second-precision instant, and an instant with one to nine fractional
    digits, with either a ``Z`` suffix or a numeric UTC offset.  Comparing the
    returned values — never the raw strings — is what keeps the suite immune to
    a difference in fractional-digit width.
    """
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"not an ISO-8601 date or instant: {value!r}"
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    micros = 0
    if fraction:
        micros = int((fraction + "000000")[:6])
    parsed = datetime(
        int(year),
        int(month),
        int(day),
        int(hour or 0),
        int(minute or 0),
        int(second or 0),
        micros,
        tzinfo=timezone.utc,
    )
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta_minutes = sign * (int(body[:2]) * 60 + int(body[2:]))
        parsed = parsed - timedelta(minutes=delta_minutes)
    return parsed


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two instants denote the same moment, ignoring formatting width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r} but read {actual!r}"
    )


def assert_instant_in(actual: str, candidates: Sequence[str], label: str = "instant") -> None:
    """Assert an instant equals one of several acceptable moments."""
    wanted = [canonical_instant(c) for c in candidates]
    assert canonical_instant(actual) in wanted, (
        f"{label}: {actual!r} is none of {list(candidates)!r}"
    )


def assert_date_equals(actual: str, expected: str, label: str = "date") -> None:
    """Assert two calendar dates denote the same day, ignoring any time part."""
    assert canonical_instant(actual).date() == canonical_instant(expected).date(), (
        f"{label}: expected {expected!r} but read {actual!r}"
    )


def assert_is_instant(value: Any, label: str = "instant") -> None:
    """Assert a field is a parseable ISO-8601 instant."""
    assert isinstance(value, str) and value, f"{label} must be a non-empty string"
    canonical_instant(value)


def assert_days_apart(start: str, end: str, days: int, label: str = "interval") -> None:
    """Assert a half-open interval spans exactly ``days`` calendar days."""
    span = canonical_instant(end) - canonical_instant(start)
    actual_days = span.total_seconds() / 86400.0
    assert actual_days == float(days), (
        f"{label}: expected {days} days from {start!r} to {end!r}, "
        f"but the span is {actual_days}"
    )


# ─── List reads (PRD §2.3) ────────────────────────────────────────────────


def read_page(response, expected_total: Optional[int] = None) -> Tuple[List[Row], Row]:
    """Validate a paginated list read and optionally pin its ``total_count``.

    Returns ``(rows, meta)``.  ``total_count`` is, per PRD §2.3, "the number of
    rows matching the request's filters before ``limit`` and ``offset`` are
    applied", so pinning it is how a test proves an absence as well as a
    presence.
    """
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']} "
            f"(rows: {[r.get('id') for r in rows]})"
        )
    return rows, meta


def read_rows(response, expected_total: Optional[int] = None) -> List[Row]:
    """Same as :func:`read_page` but discards the ``meta`` object."""
    rows, _meta = read_page(response, expected_total)
    return rows


def validate_unpaginated_list(response, expected_status: int = 200) -> List[Row]:
    """Validate a list read whose envelope carries no pagination ``meta``.

    ``validate_paginated`` hard-requires ``limit``, ``offset``, ``total_count``
    and ``has_more``; use this helper instead for any list-shaped ``data`` that
    arrives without them, so the test still checks the envelope and the array
    shape rather than reaching into the raw JSON.
    """
    data = validate_success(response, expected_status)
    assert isinstance(data, list), f"expected a list in data, got {type(data)}"
    body = response.json()
    assert body["response_type"] == "array", (
        f"a list read must declare response_type 'array', got {body['response_type']!r}"
    )
    return data


def assert_empty_list(response) -> None:
    """Assert a list read matched nothing at all."""
    rows, meta = validate_paginated(response)
    assert rows == [], f"expected no rows, got {[r.get('id') for r in rows]}"
    assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"
    assert meta["has_more"] is False, "an empty page cannot have more rows beyond it"


def ids_of(rows: Iterable[Row]) -> List[str]:
    """The ``id`` of every row, in the order the list endpoint returned them."""
    return [row["id"] for row in rows]


def find_row(rows: Iterable[Row], **match: Any) -> Row:
    """Return the single row matching every keyword field, asserting uniqueness."""
    hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, (
        f"expected exactly one row matching {match}, found {len(hits)}"
    )
    return hits[0]


def rows_matching(rows: Iterable[Row], **match: Any) -> List[Row]:
    """Every row matching all the keyword fields."""
    return [r for r in rows if all(r.get(k) == v for k, v in match.items())]


# ─── Money and rates (PRD §2.6) ───────────────────────────────────────────


def assert_money(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money field is exactly the expected integer number of cents.

    PRD §2.6 types every money field as "an integer number of cents", so the
    value on the wire must be a JSON integer — a string, a float or a bool is a
    contract violation even when it stringifies to the right digits.
    """
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r} "
        f"({type(actual).__name__})"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_bp(actual: Any, expected: int, label: str = "basis points") -> None:
    """Assert a basis-point field is exactly the expected integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of basis points, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} bp, got {actual}"


def assert_count(actual: Any, expected: int, label: str = "count") -> None:
    """Assert a count field is exactly the expected integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer, got {actual!r} ({type(actual).__name__})"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """Assert a two-decimal percentage or score field.

    PRD §2.6 rounds these "to two decimal places", so the comparison allows
    only the slack a binary float representation of a two-decimal value needs.
    """
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r} ({type(actual).__name__})"
    )
    assert math.isclose(float(actual), float(expected), abs_tol=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_not_pct(actual: Any, forbidden: float, label: str = "percentage") -> None:
    """Assert a percentage field is *not* a particular near-miss value."""
    assert not math.isclose(float(actual), float(forbidden), abs_tol=0.005), (
        f"{label}: {actual} must not equal the near-miss value {forbidden}"
    )


def assert_not_money(actual: Any, forbidden: int, label: str = "amount") -> None:
    """Assert a money field is *not* a particular near-miss amount.

    Used where the PRD's ordering of rounding and summation produces one figure
    and the naive alternative ordering produces another: pinning the correct
    figure and rejecting the near miss is what makes the ordering observable.
    """
    assert actual != forbidden, (
        f"{label}: {actual} equals the near-miss amount {forbidden}, which the "
        f"stated order of operations rules out"
    )


# ─── Row shapes (PRD §2.5) ────────────────────────────────────────────────


def assert_versioned_row(row: Row, label: str = "row") -> None:
    """Assert a row carries the full audit triplet of PRD §2.5."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in row, f"{label} must expose {field}"
    assert isinstance(row["version"], int) and not isinstance(row["version"], bool), (
        f"{label}.version must be an integer, got {row['version']!r}"
    )
    assert_is_instant(row["created_at"], f"{label}.created_at")
    assert_is_instant(row["updated_at"], f"{label}.updated_at")


def assert_immutable_row(row: Row, label: str = "row") -> None:
    """Assert a registry row is the thin shape: ``id`` and ``created_at`` only.

    PRD §2.5 says these rows "carry only ``id`` and ``created_at``", so the
    absence of ``updated_at`` and ``version`` is part of the contract.
    """
    assert "id" in row, f"{label} must expose id"
    assert "created_at" in row, f"{label} must expose created_at"
    assert "version" not in row, f"{label} must not expose a version field"
    assert "updated_at" not in row, f"{label} must not expose an updated_at field"
    assert_is_instant(row["created_at"], f"{label}.created_at")


def assert_version(row: Row, expected: int, label: str = "row") -> None:
    """Assert a row's revision counter sits at an exact value."""
    assert_count(row.get("version"), expected, f"{label}.version")


def assert_version_unchanged(after: Row, before: Row, label: str = "row") -> None:
    """Assert a refused call left the row's revision counter alone.

    PRD §2.5 increments ``version`` on "every mutation", so an unchanged
    counter is the observable proof that a rejected request wrote nothing.
    """
    assert after["version"] == before["version"], (
        f"{label}.version moved from {before['version']} to {after['version']}, "
        f"but the refused call must not have written"
    )
    assert_instant_equals(
        after["updated_at"], before["updated_at"], f"{label}.updated_at"
    )


def assert_version_advanced(after: Row, before: Row, by: int = 1, label: str = "row") -> None:
    """Assert a successful mutation advanced the revision counter."""
    assert after["version"] == before["version"] + by, (
        f"{label}.version: expected {before['version'] + by}, got {after['version']}"
    )


# ─── The venue money ledger (PRD §2.9) ────────────────────────────────────


def assert_ledger_identity(venue: Row) -> None:
    """Assert the venue ledger identity of PRD §2.9 holds.

    "``outstanding_balance_cents`` plus ``settled_amount_cents`` plus
    ``voided_amount_cents`` always equals ``lifetime_assessed_cents``."
    """
    outstanding = venue["outstanding_balance_cents"]
    settled = venue["settled_amount_cents"]
    voided = venue["voided_amount_cents"]
    lifetime = venue["lifetime_assessed_cents"]
    assert outstanding + settled + voided == lifetime, (
        "ledger identity broken: outstanding "
        f"{outstanding} + settled {settled} + voided {voided} "
        f"!= lifetime {lifetime}"
    )


def assert_venue_ledger(
    venue: Row,
    outstanding: int,
    settled: int,
    voided: int,
    lifetime: int,
) -> None:
    """Pin all four ledger columns and re-check the identity that binds them."""
    assert_money(
        venue["outstanding_balance_cents"], outstanding, "outstanding_balance_cents"
    )
    assert_money(venue["settled_amount_cents"], settled, "settled_amount_cents")
    assert_money(venue["voided_amount_cents"], voided, "voided_amount_cents")
    assert_money(venue["lifetime_assessed_cents"], lifetime, "lifetime_assessed_cents")
    assert_ledger_identity(venue)


def assert_coverage(venue: Row, covered_share_bp: int, posture: str) -> None:
    """Pin the two coverage-roll-up fields of PRD §2.10 together."""
    assert_bp(venue["covered_share_bp"], covered_share_bp, "covered_share_bp")
    assert venue["coverage_posture"] == posture, (
        f"coverage_posture: expected {posture!r}, got {venue['coverage_posture']!r}"
    )


def assert_license_dimensions(
    license_row: Row, coverage_status: str, billing_status: str
) -> None:
    """Pin a licence's two independent state dimensions (PRD §2.11) together."""
    assert license_row["coverage_status"] == coverage_status, (
        f"coverage_status: expected {coverage_status!r}, "
        f"got {license_row['coverage_status']!r}"
    )
    assert license_row["billing_status"] == billing_status, (
        f"billing_status: expected {billing_status!r}, "
        f"got {license_row['billing_status']!r}"
    )


def assert_assessment(
    assessment: Row, kind: str, amount: int, status: str, paid: Optional[int] = None
) -> None:
    """Pin a fee assessment's kind, amount, status and settled portion."""
    assert assessment["assessment_kind"] == kind, (
        f"assessment_kind: expected {kind!r}, got {assessment['assessment_kind']!r}"
    )
    assert_money(assessment["amount_cents"], amount, "amount_cents")
    assert assessment["status"] == status, (
        f"assessment status: expected {status!r}, got {assessment['status']!r}"
    )
    if paid is not None:
        assert_money(assessment["paid_amount_cents"], paid, "paid_amount_cents")
