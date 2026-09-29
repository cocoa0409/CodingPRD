"""Domain assertion helpers for the awareness program API.

Instant comparison is canonicalising: the contract emits UTC instants with three
fractional-second digits, so a literal string comparison against
``2026-08-09T00:00:00Z`` would fail for a perfectly conforming server.  Every
helper here compares the underlying moment, not its spelling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from .constants import (
    POSTURE_BY_RANK,
    SECONDS_PER_DAY,
    SEVERITY_RANK,
)


# --------------------------------------------------------------------------- #
# Instants                                                                    #
# --------------------------------------------------------------------------- #


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, with or without fractional seconds."""
    assert isinstance(value, str), f"expected an ISO-8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Assert two ISO-8601 instants denote the same moment."""
    assert actual is not None, f"{label} was null, expected {expected}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_is_none(actual, label: str = "instant") -> None:
    assert actual is None, f"{label} should be null, got {actual!r}"


def assert_utc_millisecond_format(value: str, label: str = "timestamp") -> None:
    """Assert the instant is rendered as UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must be a UTC instant ending in Z, got {value}"
    assert "." in value, f"{label} must carry fractional seconds, got {value}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, f"{label} must carry three fractional digits, got {value}"


def days_between(earlier: str, later: str) -> int:
    """Whole elapsed days between two instants, seconds divided by 86400 and floored."""
    delta = (parse_instant(later) - parse_instant(earlier)).total_seconds()
    return int(delta // SECONDS_PER_DAY)


# --------------------------------------------------------------------------- #
# Numeric precision                                                           #
# --------------------------------------------------------------------------- #


def assert_rate(actual, expected: Optional[float], label: str = "rate") -> None:
    """Assert a rate/correlation matches a 4-decimal expectation, or is null."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert float(actual) == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_score(actual, expected: float, label: str = "score") -> None:
    """Assert a 2-decimal risk score, clamped into [0.00, 100.00]."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    value = float(actual)
    assert 0.0 <= value <= 100.0, f"{label} must be clamped into [0, 100], got {value}"
    assert value == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_decimal_places(actual, label: str = "rate") -> None:
    """Assert the value carries no more than four decimal places."""
    if actual is None:
        return
    assert round(float(actual), 4) == pytest.approx(float(actual), abs=1e-12), (
        f"{label} must be rounded to four decimal places, got {actual}"
    )


# --------------------------------------------------------------------------- #
# Envelope / identity                                                         #
# --------------------------------------------------------------------------- #


def assert_append_only_shape(row: dict, label: str = "row") -> None:
    """Assert an append-only row carries id and created_at but no version block."""
    assert "id" in row and "created_at" in row, f"{label} must carry id and created_at"
    assert "version" not in row, f"{label} must not carry a version field"
    assert "updated_at" not in row, f"{label} must not carry an updated_at field"


def assert_versioned_shape(row: dict, label: str = "row") -> None:
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in row, f"{label} must carry {field}"


def assert_version_is(row: dict, expected: int, label: str = "row") -> None:
    assert row["version"] == expected, (
        f"{label}.version: expected {expected}, got {row['version']}"
    )


def assert_no_prefix_uuid(value: str, label: str = "id") -> None:
    assert isinstance(value, str), f"{label} must be a string"
    assert "_" not in value and ":" not in value, f"{label} must be a bare UUID, got {value}"
    assert len(value) == 36, f"{label} must be a 36-character UUID, got {value}"


# --------------------------------------------------------------------------- #
# Employee axes                                                               #
# --------------------------------------------------------------------------- #


def assert_employee_axes(
    employee: dict,
    *,
    employment_status: Optional[str] = None,
    compliance_state: Optional[str] = None,
    access_posture: Optional[str] = None,
) -> None:
    """Assert the three independent employee state axes."""
    if employment_status is not None:
        assert employee["employment_status"] == employment_status, (
            f"employment_status: expected {employment_status}, "
            f"got {employee['employment_status']}"
        )
    if compliance_state is not None:
        assert employee["compliance_state"] == compliance_state, (
            f"compliance_state: expected {compliance_state}, "
            f"got {employee['compliance_state']}"
        )
    if access_posture is not None:
        assert employee["access_posture"] == access_posture, (
            f"access_posture: expected {access_posture}, got {employee['access_posture']}"
        )


def assert_posture_matches_rank(employee: dict, highest_active_rank: int) -> None:
    """Assert access_posture is the projection of the highest active severity rank."""
    expected = POSTURE_BY_RANK[highest_active_rank]
    assert employee["access_posture"] == expected, (
        f"rank {highest_active_rank} projects to {expected}, "
        f"got {employee['access_posture']}"
    )


def assert_ledgers(
    employee: dict,
    *,
    reserved_simulation_slots: Optional[int] = None,
    active_suspension_count: Optional[int] = None,
) -> None:
    """Assert the two employee counter ledgers."""
    if reserved_simulation_slots is not None:
        assert employee["reserved_simulation_slots"] == reserved_simulation_slots, (
            f"reserved_simulation_slots: expected {reserved_simulation_slots}, "
            f"got {employee['reserved_simulation_slots']}"
        )
    if active_suspension_count is not None:
        assert employee["active_suspension_count"] == active_suspension_count, (
            f"active_suspension_count: expected {active_suspension_count}, "
            f"got {employee['active_suspension_count']}"
        )


def assert_risk_scores(
    employee: dict, *, provisional: Optional[float] = None, settled: Optional[float] = None
) -> None:
    if provisional is not None:
        assert_score(employee["risk_score_provisional"], provisional, "risk_score_provisional")
    if settled is not None:
        assert_score(employee["risk_score_settled"], settled, "risk_score_settled")


# --------------------------------------------------------------------------- #
# Consequences and notices                                                    #
# --------------------------------------------------------------------------- #


def assert_consequence(
    consequence: dict,
    *,
    state: Optional[str] = None,
    consequence_type: Optional[str] = None,
    severity_rank: Optional[int] = None,
    lift_reason_code: Optional[str] = None,
) -> None:
    if state is not None:
        assert consequence["state"] == state, (
            f"consequence state: expected {state}, got {consequence['state']}"
        )
    if consequence_type is not None:
        assert consequence["consequence_type"] == consequence_type, (
            f"consequence_type: expected {consequence_type}, "
            f"got {consequence['consequence_type']}"
        )
        assert consequence["severity_rank"] == SEVERITY_RANK[consequence_type], (
            "severity_rank must agree with the pinned rank of the consequence type"
        )
    if severity_rank is not None:
        assert consequence["severity_rank"] == severity_rank, (
            f"severity_rank: expected {severity_rank}, got {consequence['severity_rank']}"
        )
    if lift_reason_code is not None:
        assert consequence["lift_reason_code"] == lift_reason_code, (
            f"lift_reason_code: expected {lift_reason_code}, "
            f"got {consequence['lift_reason_code']}"
        )


def assert_notice(
    notice: dict, *, state: Optional[str] = None, level: Optional[int] = None
) -> None:
    if state is not None:
        assert notice["state"] == state, (
            f"notice state: expected {state}, got {notice['state']}"
        )
    if level is not None:
        assert notice["level"] == level, (
            f"notice level: expected {level}, got {notice['level']}"
        )


# --------------------------------------------------------------------------- #
# Sweep counters                                                              #
# --------------------------------------------------------------------------- #


def assert_sweep_counters(
    sweep: dict,
    *,
    assignments_scanned: Optional[int] = None,
    reminders_sent_count: Optional[int] = None,
    overdue_count: Optional[int] = None,
    escalations_created_count: Optional[int] = None,
    consequences_applied_count: Optional[int] = None,
) -> None:
    expectations = {
        "assignments_scanned": assignments_scanned,
        "reminders_sent_count": reminders_sent_count,
        "overdue_count": overdue_count,
        "escalations_created_count": escalations_created_count,
        "consequences_applied_count": consequences_applied_count,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert sweep[field] == expected, (
                f"sweep {field}: expected {expected}, got {sweep[field]}"
            )


# --------------------------------------------------------------------------- #
# Deliveries and assignments                                                  #
# --------------------------------------------------------------------------- #


def assert_delivery(
    delivery: dict,
    *,
    state: Optional[str] = None,
    outcome_class: Optional[str] = None,
    effective_difficulty_tier: Optional[str] = None,
    excluded_reason: Optional[str] = None,
) -> None:
    if state is not None:
        assert delivery["state"] == state, (
            f"delivery state: expected {state}, got {delivery['state']}"
        )
    if outcome_class is not None:
        assert delivery["outcome_class"] == outcome_class, (
            f"outcome_class: expected {outcome_class}, got {delivery['outcome_class']}"
        )
    if effective_difficulty_tier is not None:
        assert delivery["effective_difficulty_tier"] == effective_difficulty_tier, (
            f"effective_difficulty_tier: expected {effective_difficulty_tier}, "
            f"got {delivery['effective_difficulty_tier']}"
        )
    if excluded_reason is not None:
        assert delivery["excluded_reason"] == excluded_reason, (
            f"excluded_reason: expected {excluded_reason}, got {delivery['excluded_reason']}"
        )


def assert_assignment(
    assignment: dict,
    *,
    state: Optional[str] = None,
    escalation_level: Optional[int] = None,
    attempt_count: Optional[int] = None,
    reminders_sent: Optional[int] = None,
    granted_extension_days: Optional[int] = None,
    days_overdue: Optional[int] = None,
    last_score_pct: Optional[int] = None,
) -> None:
    expectations = {
        "state": state,
        "escalation_level": escalation_level,
        "attempt_count": attempt_count,
        "reminders_sent": reminders_sent,
        "granted_extension_days": granted_extension_days,
        "days_overdue": days_overdue,
        "last_score_pct": last_score_pct,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert assignment[field] == expected, (
                f"assignment {field}: expected {expected}, got {assignment[field]}"
            )


def find_by_id(rows: list, row_id: str) -> dict:
    """Return the row with the given id from a listing, asserting it is present."""
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"row {row_id} not present in listing of {len(rows)} rows")


def ids_of(rows: list) -> list:
    return [row["id"] for row in rows]
