"""Domain assertions for the Newsroom Standards & Corrections API."""

import re
from typing import Any, Dict, Iterable, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from . import constants as C

_ISO_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$"
)

# ─── Instants ─────────────────────────────────────────


def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    PRD §2.4 requires "an ISO 8601 UTC instant with exactly three
    fractional-second digits"; this helper lets equality assertions compare
    the instant itself rather than the width of its fractional part.
    """
    assert isinstance(value, str), f"Not a timestamp string: {value!r}"
    match = _ISO_RE.match(value)
    assert match, f"Not an ISO 8601 UTC instant: {value!r}"
    date_part, time_part, frac, zone = match.groups()
    assert zone in ("Z", "+00:00", "-00:00"), f"Instant is not UTC: {value!r}"
    millis = (frac or "").ljust(3, "0")[:3]
    return f"{date_part}T{time_part}.{millis}Z"


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_declared_instant(value: Any) -> None:
    """Assert the value is an ISO 8601 UTC instant with three fractional digits."""
    assert isinstance(value, str), f"Timestamp must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC timestamp: {value!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value), (
        f"Timestamp must carry exactly three fractional digits: {value!r}"
    )


# ─── Envelope and identity ────────────────────────────


def assert_envelope_meta(response) -> Dict[str, Any]:
    """Assert PRD §2.2 envelope metadata and return the ``meta`` object."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert_declared_instant(meta.get("api_request_timestamp"))
    return meta


def assert_bare_uuid(value: Any) -> None:
    """Assert an identifier is a bare UUID with no type prefix (PRD §2.4)."""
    assert isinstance(value, str), f"Identifier must be a string: {value!r}"
    assert is_valid_uuid(value), f"Identifier must be a bare UUID: {value!r}"


def assert_versioned_resource(resource: Dict[str, Any], version: int = 1) -> None:
    """Assert the full identity set of PRD §2.4 with the expected ``version``."""
    assert_bare_uuid(resource["id"])
    assert_declared_instant(resource["created_at"])
    assert_declared_instant(resource["updated_at"])
    assert resource["version"] == version, (
        f"Expected version {version}, got {resource['version']}"
    )


def assert_append_only_resource(resource: Dict[str, Any]) -> None:
    """Assert an append-only record carries only ``id`` and ``created_at``.

    PRD §2.4: a ``TrainingRecord`` and a ``StandardsAuditEvent`` carry only
    ``id`` and ``created_at``; both ``updated_at`` and ``version`` are absent.
    """
    assert_bare_uuid(resource["id"])
    assert_declared_instant(resource["created_at"])
    assert "updated_at" not in resource, (
        "Append-only records must not expose 'updated_at'"
    )
    assert "version" not in resource, "Append-only records must not expose 'version'"


# ─── Decimal figures ──────────────────────────────────


def assert_two_decimal_number(value: Any) -> None:
    """Assert a decimal figure is a JSON number, not a string (PRD §2.7)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"Decimal figures are returned as numbers, not strings: {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"Value carries more than two decimal places: {value!r}"
    )


def assert_decimal_equals(actual: Any, expected: float) -> None:
    """Assert a two-decimal figure equals the expected value."""
    assert_two_decimal_number(actual)
    assert float(actual) == pytest.approx(expected, abs=0.01), (
        f"Expected {expected:.2f}, got {actual}"
    )


def assert_integer_score(value: Any) -> None:
    """Assert a severity score or penalty figure is a plain integer (PRD §2.7)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"Severity and penalty figures are integers: {value!r}"
    )


# ─── Stories ──────────────────────────────────────────


def assert_story_dimensions(
    story: Dict[str, Any], publication_status: str, standards_status: str
) -> None:
    """Assert both of the story's independent state dimensions (PRD §2.11)."""
    assert story["publication_status"] == publication_status, (
        f"Expected publication_status {publication_status}, "
        f"got {story['publication_status']}"
    )
    assert story["standards_status"] == standards_status, (
        f"Expected standards_status {standards_status}, "
        f"got {story['standards_status']}"
    )


def assert_risk_figures(
    story: Dict[str, Any],
    estimate: Optional[float] = None,
    actual: Optional[float] = None,
    tier: Optional[str] = None,
) -> None:
    """Assert the story's risk indices and tier (PRD §3.2, §3.5)."""
    if estimate is not None:
        assert_decimal_equals(story["risk_index_estimate"], estimate)
    if actual is not None:
        assert_decimal_equals(story["risk_index_actual"], actual)
    if tier is not None:
        assert story["risk_tier"] == tier, (
            f"Expected risk_tier {tier}, got {story['risk_tier']}"
        )


def assert_tier_banded_from_estimate(story: Dict[str, Any]) -> None:
    """Assert ``risk_tier`` is banded from ``risk_index_estimate`` (PRD §3.2)."""
    estimate = float(story["risk_index_estimate"])
    if estimate >= C.RISK_TIER_HIGH_FLOOR:
        expected = C.TIER_HIGH
    elif estimate >= C.RISK_TIER_ELEVATED_FLOOR:
        expected = C.TIER_ELEVATED
    else:
        expected = C.TIER_STANDARD
    assert story["risk_tier"] == expected, (
        f"Estimate {estimate} should band as {expected}, got {story['risk_tier']}"
    )


def assert_story_counters(
    story: Dict[str, Any],
    approved_sources: Optional[int] = None,
    revoked_sources: Optional[int] = None,
    severe_corrections: Optional[int] = None,
    open_corrections: Optional[int] = None,
) -> None:
    """Assert the story's four derived counters (PRD §3.2)."""
    if approved_sources is not None:
        assert story["approved_anonymous_source_count"] == approved_sources
    if revoked_sources is not None:
        assert story["revoked_anonymous_source_count"] == revoked_sources
    if severe_corrections is not None:
        assert story["severe_correction_count"] == severe_corrections
    if open_corrections is not None:
        assert story["open_correction_request_count"] == open_corrections


# ─── Correction severity ──────────────────────────────


def expected_raw_severity(category: str, subject_flag: bool, reach: int) -> int:
    """Reproduce the raw severity figure of PRD §3.6."""
    raw = C.CATEGORY_WEIGHTS[category]
    if subject_flag:
        raw += C.SUBJECT_FLAG_POINTS
    if reach >= 100000:
        raw += 6
    elif reach >= 10000:
        raw += 4
    elif reach >= 1000:
        raw += 2
    return raw


def expected_band(raw: int) -> str:
    """Band read off the raw figure and off nothing else (PRD §3.6)."""
    if raw >= C.BAND_RAW_FLOORS[C.BAND_SEVERE]:
        return C.BAND_SEVERE
    if raw >= C.BAND_RAW_FLOORS[C.BAND_MAJOR]:
        return C.BAND_MAJOR
    if raw >= C.BAND_RAW_FLOORS[C.BAND_MINOR]:
        return C.BAND_MINOR
    return C.BAND_TRIVIAL


def expected_stored_score(raw: int) -> int:
    """Raw figure plus the surcharge determined by its band (PRD §3.6)."""
    return raw + C.BAND_SURCHARGE[expected_band(raw)]


def assert_provisional_severity(
    request: Dict[str, Any], score: int, band: str
) -> None:
    """Assert the intake severity run of PRD §3.6."""
    assert_integer_score(request["provisional_severity_score"])
    assert request["provisional_severity_score"] == score, (
        f"Expected provisional_severity_score {score}, "
        f"got {request['provisional_severity_score']}"
    )
    assert request["provisional_severity_band"] == band, (
        f"Expected provisional_severity_band {band}, "
        f"got {request['provisional_severity_band']}"
    )


def assert_adjudicated_severity(
    request: Dict[str, Any], score: int, band: str
) -> None:
    """Assert the adjudication severity run of PRD §3.6."""
    assert_integer_score(request["adjudicated_severity_score"])
    assert request["adjudicated_severity_score"] == score, (
        f"Expected adjudicated_severity_score {score}, "
        f"got {request['adjudicated_severity_score']}"
    )
    assert request["adjudicated_severity_band"] == band, (
        f"Expected adjudicated_severity_band {band}, "
        f"got {request['adjudicated_severity_band']}"
    )


def assert_band_not_rebanded_from_score(request: Dict[str, Any]) -> None:
    """Assert the stored score equals raw plus the band's own surcharge.

    PRD §3.6: "the band comes from the raw figure, the surcharge comes from
    the band, and the band is never re-derived from the final score."
    """
    band = request["adjudicated_severity_band"]
    score = request["adjudicated_severity_score"]
    raw = score - C.BAND_SURCHARGE[band]
    assert expected_band(raw) == band, (
        f"Score {score} in band {band} implies raw {raw}, which bands as "
        f"{expected_band(raw)}"
    )


# ─── Reviewer minute ledger ───────────────────────────


def assert_minute_ledger(
    reviewer: Dict[str, Any], reserved: int, available: int
) -> None:
    """Assert the reviewer's conserved minute ledger (PRD §3.4)."""
    assert reviewer["reserved_minutes"] == reserved, (
        f"Expected reserved_minutes {reserved}, got {reviewer['reserved_minutes']}"
    )
    assert reviewer["available_minutes"] == available, (
        f"Expected available_minutes {available}, got {reviewer['available_minutes']}"
    )
    assert (
        reviewer["reserved_minutes"] + reviewer["available_minutes"]
        == reviewer["weekly_capacity_minutes"]
    ), (
        "reserved_minutes and available_minutes must sum to "
        "weekly_capacity_minutes"
    )


def assert_minutes_conserved(reviewer: Dict[str, Any]) -> None:
    """Assert the ledger invariant of PRD §3.4 without pinning the split."""
    assert (
        reviewer["reserved_minutes"] + reviewer["available_minutes"]
        == reviewer["weekly_capacity_minutes"]
    )
    assert reviewer["available_minutes"] >= 0, "available_minutes may never go negative"


# ─── Newsroom posture ─────────────────────────────────


def expected_posture(count: int, threshold: int) -> str:
    """Reproduce the posture derivation of PRD §2.9."""
    if count >= 2 * threshold:
        return C.POSTURE_LOCKDOWN
    if count >= threshold:
        return C.POSTURE_HEIGHTENED
    return C.POSTURE_OPEN


def assert_posture(newsroom: Dict[str, Any], posture: str, count: int) -> None:
    """Assert the desk-wide posture and the count it is derived from."""
    assert newsroom["open_high_severity_count"] == count, (
        f"Expected open_high_severity_count {count}, "
        f"got {newsroom['open_high_severity_count']}"
    )
    assert newsroom["standards_posture"] == posture, (
        f"Expected standards_posture {posture}, "
        f"got {newsroom['standards_posture']}"
    )
    assert newsroom["standards_posture"] == expected_posture(
        count, newsroom["high_severity_open_threshold"]
    )


# ─── Lists and the transparency log ───────────────────


def assert_total_count(response, total_count: int) -> List[Dict[str, Any]]:
    """Assert a paginated list's ``total_count`` and return its rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    return rows


def assert_page(
    response, total_count: int, has_more: bool, row_count: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Assert the pagination fields of PRD §2.3 and return the rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )
    if row_count is not None:
        assert len(rows) == row_count, (
            f"Expected {row_count} rows in the window, got {len(rows)}"
        )
    return rows


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    """Assert a list is ordered by creation timestamp, oldest first (PRD §2.3)."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"Rows are not in created_at order: {stamps}"


def assert_audit_event(
    event: Dict[str, Any],
    event_type: str,
    subject_type: str,
    subject_id: str,
    actor_role: Optional[str] = None,
    actor_user_id: Optional[str] = "__unchecked__",
) -> None:
    """Assert one transparency-log entry of PRD §2.11."""
    assert event["event_type"] == event_type, (
        f"Expected event_type {event_type}, got {event['event_type']}"
    )
    assert event["subject_type"] == subject_type, (
        f"Expected subject_type {subject_type}, got {event['subject_type']}"
    )
    assert event["subject_id"] == subject_id
    if actor_role is not None:
        assert event["actor_role"] == actor_role, (
            f"Expected actor_role {actor_role}, got {event['actor_role']}"
        )
    if actor_user_id != "__unchecked__":
        assert event["actor_user_id"] == actor_user_id, (
            f"Expected actor_user_id {actor_user_id}, got {event['actor_user_id']}"
        )
    assert isinstance(event["summary"], str) and event["summary"].strip()
    assert_declared_instant(event["occurred_at"])


def assert_cascaded_event(event: Dict[str, Any]) -> None:
    """Assert an event the server raised for itself (PRD §2.11).

    ``actor_role`` is the literal string ``system`` and ``actor_user_id`` is
    null for a cascaded transition.
    """
    assert event["actor_role"] == C.ACTOR_SYSTEM, (
        f"Cascaded events carry actor_role 'system', got {event['actor_role']}"
    )
    assert event["actor_user_id"] is None, (
        "Cascaded events carry a null actor_user_id, got "
        f"{event['actor_user_id']}"
    )


def event_types(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """Collect the ``event_type`` of every row, in order."""
    return [row["event_type"] for row in rows]
