"""Domain assertion helpers and instant arithmetic.

Timestamp discipline: the PRD states every server-stamped instant is an ISO 8601
UTC instant with three fractional digits, while the deadlines and windows the
rules derive are whole seconds.  Every comparison in this suite therefore runs
through :func:`canonical_instant`, which reduces both sides to whole-second UTC
form, so a server that answers ``2026-08-05T09:00:00.000Z`` and a rule that says
``2026-08-05T09:00:00Z`` agree.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import (
    AGE_GROUP_MAX_SIZE,
    DEFAULT_PAGE_LIMIT,
    POSTING_BANNER_BY_STEP,
    RISK_TIER_HIGH_FLOOR,
    RISK_TIER_MODERATE_FLOOR,
    RISK_TIER_SEVERE_FLOOR,
    STAFF_CHILD_RATIO,
)

# Scores and risk numbers are carried to exactly two decimal places.
SCORE_TOLERANCE = 0.005


# ─── Instant handling ──────────────────────────────────────────────────
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    assert isinstance(value, str), f"Expected an ISO 8601 instant string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"Expected a UTC instant ending in 'Z', got {value!r}"
    return datetime.fromisoformat(text[:-1] + "+00:00")


def canonical_instant(value: str) -> str:
    """Reduce an instant to whole-second UTC form, e.g.
    ``2026-08-05T09:00:00.000Z`` -> ``2026-08-05T09:00:00Z``."""
    return parse_instant(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_instant(actual: Any, expected: str, field: str = "instant") -> None:
    """Assert two instants name the same second."""
    assert actual is not None, f"{field} must not be null"
    assert is_iso8601_timestamp(actual), f"{field} is not an ISO 8601 UTC instant: {actual!r}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {field} {canonical_instant(expected)}, got {canonical_instant(actual)}"
    )


def plus_seconds(value: str, seconds: int) -> str:
    return (parse_instant(value) + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def plus_minutes(value: str, minutes: int) -> str:
    return plus_seconds(value, minutes * 60)


def plus_hours(value: str, hours: int) -> str:
    return plus_seconds(value, hours * 3600)


def plus_days(value: str, days: int) -> str:
    return plus_seconds(value, days * 86400)


def plus_months(value: str, months: int) -> str:
    """Add whole calendar months, preserving the time of day."""
    moment = parse_instant(value)
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = moment.day
    while True:
        try:
            shifted = moment.replace(year=year, month=month, day=day)
            break
        except ValueError:
            day -= 1
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Numeric helpers ───────────────────────────────────────────────────
def assert_score(actual: Any, expected: float, field: str = "score") -> None:
    """Assert a 2-decimal score, risk number or display score."""
    assert actual is not None, f"{field} must not be null"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a JSON number, got {actual!r}"
    )
    assert float(actual) == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"Expected {field} {expected:.2f}, got {actual}"
    )


def assert_points(actual: Any, expected: int, field: str = "points") -> None:
    """Point assessments and balances are whole numbers."""
    assert actual is not None, f"{field} must not be null"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a JSON number, got {actual!r}"
    )
    assert float(actual) == pytest.approx(float(expected), abs=1e-9), (
        f"Expected {field} {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, field: str = "fine_amount_cents") -> None:
    """All monetary amounts are integer cent counts; there is no fractional
    currency, so the value must be an integer and never a string."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer cent count, got {actual!r}"
    )
    assert actual == expected, f"Expected {field} {expected}, got {actual}"


# ─── Common record shape (PRD §2.5) ────────────────────────────────────
def assert_versioned_record(record: Dict[str, Any], entity: str = "record") -> None:
    assert is_valid_uuid(record.get("id")), (
        f"{entity}.id must be a UUID with no type prefix, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"{entity}.created_at must be an ISO 8601 UTC instant, got {record.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(record.get("updated_at")), (
        f"{entity}.updated_at must be an ISO 8601 UTC instant, got {record.get('updated_at')!r}"
    )
    assert isinstance(record.get("version"), int) and not isinstance(
        record.get("version"), bool
    ), f"{entity}.version must be an integer, got {record.get('version')!r}"
    assert record["version"] >= 1, f"{entity}.version starts at 1, got {record['version']}"


def assert_checklist_item(item: Dict[str, Any]) -> None:
    """A ChecklistItem is immutable configuration: it carries only ``id`` and
    ``created_at`` and has neither ``updated_at`` nor ``version``."""
    assert is_valid_uuid(item.get("id")), f"checklist item id must be a UUID: {item.get('id')!r}"
    assert is_iso8601_timestamp(item.get("created_at")), (
        f"checklist item created_at must be an ISO 8601 instant: {item.get('created_at')!r}"
    )
    assert "version" not in item, "ChecklistItem must carry no version field"
    assert "updated_at" not in item, "ChecklistItem must carry no updated_at field"


# ─── Per-entity assertions ─────────────────────────────────────────────
def assert_provider(provider: Dict[str, Any], **expected: Any) -> None:
    assert_versioned_record(provider, "provider")
    for key, value in expected.items():
        assert provider.get(key) == value, (
            f"Expected provider.{key} == {value!r}, got {provider.get(key)!r}"
        )


def assert_inspection(inspection: Dict[str, Any], **expected: Any) -> None:
    assert_versioned_record(inspection, "inspection")
    for key, value in expected.items():
        assert inspection.get(key) == value, (
            f"Expected inspection.{key} == {value!r}, got {inspection.get(key)!r}"
        )


def assert_violation(violation: Dict[str, Any], **expected: Any) -> None:
    assert_versioned_record(violation, "violation")
    for key, value in expected.items():
        assert violation.get(key) == value, (
            f"Expected violation.{key} == {value!r}, got {violation.get(key)!r}"
        )


def assert_record(record: Dict[str, Any], entity: str = "record", **expected: Any) -> None:
    """Generic versioned-record assertion for the remaining entities."""
    assert_versioned_record(record, entity)
    for key, value in expected.items():
        assert record.get(key) == value, (
            f"Expected {entity}.{key} == {value!r}, got {record.get(key)!r}"
        )


def assert_fields_absent(record: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert record.get(field) is None, (
            f"Expected {field} to be null, got {record.get(field)!r}"
        )


# ─── Domain invariants (PRD §2.9) ──────────────────────────────────────
def assert_point_conservation(provider: Dict[str, Any]) -> None:
    """The lifetime balance must always equal the open balance plus the
    resolved balance."""
    open_points = provider["open_violation_points"]
    resolved = provider["resolved_violation_points"]
    lifetime = provider["lifetime_violation_points"]
    assert float(lifetime) == pytest.approx(float(open_points) + float(resolved), abs=1e-9), (
        "Point conservation broken: lifetime "
        f"{lifetime} != open {open_points} + resolved {resolved}"
    )


def assert_point_ledger(
    provider: Dict[str, Any], open_points: int, resolved_points: int, lifetime_points: int
) -> None:
    assert_points(provider["open_violation_points"], open_points, "open_violation_points")
    assert_points(
        provider["resolved_violation_points"], resolved_points, "resolved_violation_points"
    )
    assert_points(
        provider["lifetime_violation_points"], lifetime_points, "lifetime_violation_points"
    )
    assert_point_conservation(provider)


def assert_capacity_slots(
    provider: Dict[str, Any], licensed: int, suspended: int
) -> None:
    """A provider's total authorised slots is its licensed capacity plus its
    suspended capacity."""
    assert provider["licensed_capacity"] == licensed, (
        f"Expected licensed_capacity {licensed}, got {provider['licensed_capacity']}"
    )
    assert provider["suspended_capacity"] == suspended, (
        f"Expected suspended_capacity {suspended}, got {provider['suspended_capacity']}"
    )
    assert provider["suspended_capacity"] >= 0, "suspended_capacity may never be negative"


def assert_capacity_total_preserved(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    total_before = before["licensed_capacity"] + before["suspended_capacity"]
    total_after = after["licensed_capacity"] + after["suspended_capacity"]
    assert total_before == total_after, (
        f"Capacity slots not conserved: {total_before} -> {total_after}"
    )


def expected_risk_tier(score: float) -> str:
    """``LOW`` below 20, ``MODERATE`` from 20 up to but not including 45,
    ``HIGH`` from 45 up to but not including 70, ``SEVERE`` at 70 or above."""
    if score >= RISK_TIER_SEVERE_FLOOR:
        return "SEVERE"
    if score >= RISK_TIER_HIGH_FLOOR:
        return "HIGH"
    if score >= RISK_TIER_MODERATE_FLOOR:
        return "MODERATE"
    return "LOW"


def assert_risk(provider: Dict[str, Any], score: float, tier: str) -> None:
    assert_score(provider["risk_score"], score, "risk_score")
    assert provider["risk_tier"] == tier, (
        f"Expected risk_tier {tier}, got {provider['risk_tier']}"
    )
    assert tier == expected_risk_tier(score), (
        f"Risk tier {tier} disagrees with the banding of score {score}"
    )


def expected_required_staff_count(age_group: str, enrolled_count: int) -> int:
    ratio = STAFF_CHILD_RATIO[age_group]
    return -(-enrolled_count // ratio)


def assert_roster_flags(
    roster: Dict[str, Any],
    ratio_compliant: bool,
    group_size_compliant: bool,
    supervision_compliant: bool,
    required_staff_count: Optional[int] = None,
) -> None:
    assert roster["ratio_compliant"] is ratio_compliant, (
        f"Expected ratio_compliant {ratio_compliant}, got {roster['ratio_compliant']}"
    )
    assert roster["group_size_compliant"] is group_size_compliant, (
        f"Expected group_size_compliant {group_size_compliant}, "
        f"got {roster['group_size_compliant']}"
    )
    assert roster["supervision_compliant"] is supervision_compliant, (
        f"Expected supervision_compliant {supervision_compliant}, "
        f"got {roster['supervision_compliant']}"
    )
    if required_staff_count is not None:
        assert roster["required_staff_count"] == required_staff_count, (
            f"Expected required_staff_count {required_staff_count}, "
            f"got {roster['required_staff_count']}"
        )
        assert required_staff_count == expected_required_staff_count(
            roster["age_group"], roster["enrolled_count"]
        ), "required_staff_count disagrees with the statutory ratio table"


def assert_group_size_within_statutory_max(roster: Dict[str, Any]) -> None:
    ceiling = AGE_GROUP_MAX_SIZE[roster["age_group"]]
    assert roster["requested_group_size"] <= ceiling, (
        f"requested_group_size {roster['requested_group_size']} exceeds the statutory "
        f"maximum {ceiling} for {roster['age_group']}"
    )


def assert_banner_for_ladder_step(posting: Dict[str, Any], ladder_step: int) -> None:
    expected = POSTING_BANNER_BY_STEP[ladder_step]
    assert posting["enforcement_banner"] == expected, (
        f"Expected enforcement_banner {expected} at ladder step {ladder_step}, "
        f"got {posting['enforcement_banner']}"
    )


# ─── Computed reads ────────────────────────────────────────────────────
def assert_risk_assessment(
    data: Dict[str, Any],
    variant: str,
    risk_score: float,
    risk_tier: str,
    **counters: Any,
) -> None:
    """The provider risk-assessment read returns a computed object, not a
    provider row."""
    assert data["variant"] == variant, (
        f"Expected variant {variant}, got {data['variant']}"
    )
    assert_score(data["risk_score"], risk_score, "risk_score")
    assert data["risk_tier"] == risk_tier, (
        f"Expected risk_tier {risk_tier}, got {data['risk_tier']}"
    )
    for key, value in counters.items():
        assert data.get(key) == value, (
            f"Expected risk assessment {key} == {value!r}, got {data.get(key)!r}"
        )


def assert_compliance_score_read(
    data: Dict[str, Any],
    variant: str,
    compliance_score: float,
    raw_deduction: Optional[float] = None,
    violation_count: Optional[int] = None,
) -> None:
    """The inspection compliance-score read recomputes from current data."""
    assert data["variant"] == variant, (
        f"Expected variant {variant}, got {data['variant']}"
    )
    assert_score(data["compliance_score"], compliance_score, "compliance_score")
    if raw_deduction is not None:
        assert_score(data["raw_deduction"], raw_deduction, "raw_deduction")
    if violation_count is not None:
        assert data["violation_count"] == violation_count, (
            f"Expected violation_count {violation_count}, got {data['violation_count']}"
        )


# ─── List envelopes (PRD §2.3) ─────────────────────────────────────────
def assert_list_envelope(
    response, expected_total: Optional[int] = None, expected_ids: Optional[List[str]] = None
):
    """Every collection endpoint in this service is paginated, so every list
    response carries limit, offset, total_count and has_more in its meta."""
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_ids is not None:
        actual = [row["id"] for row in rows]
        assert actual == expected_ids, f"Expected rows {expected_ids}, got {actual}"
    return rows, meta


def assert_default_page_window(meta: Dict[str, Any]) -> None:
    """When ``limit`` is omitted it defaults to 10 and ``offset`` to 0."""
    assert meta["limit"] == DEFAULT_PAGE_LIMIT, (
        f"Expected default limit {DEFAULT_PAGE_LIMIT}, got {meta['limit']}"
    )
    assert meta["offset"] == 0, f"Expected default offset 0, got {meta['offset']}"


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered by ``created_at`` ascending."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "List results must be ordered by created_at ascending"
