"""Domain assertions layered on top of the framework validators.

Timestamp comparison always goes through normalise_instant()/assert_instant():
two renderings of the same UTC instant that differ only in sub-second width or
in the trailing designator are the same instant and must compare equal.
"""

import re
from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import (
    RELIABILITY_CEILING,
    RELIABILITY_FLOOR,
    SURCHARGE_TIER_0_BP,
    SURCHARGE_TIER_1_BP,
    SURCHARGE_TIER_1_HEADS,
    SURCHARGE_TIER_2_BP,
    SURCHARGE_TIER_2_HEADS,
    SURCHARGE_TIER_3_BP,
    SURCHARGE_TIER_3_HEADS,
    TIER_2_FLOOR,
    TIER_3_FLOOR,
    TIER_4_FLOOR,
)

# ------------------------------------------------------------------ timestamps

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def normalise_instant(value: Optional[str]) -> Optional[str]:
    """Canonicalise an ISO-8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Sub-second width and the case of the designator are rendering details, not
    semantics, so they are erased before any equality check.
    """
    if value is None:
        return None
    match = _INSTANT_RE.match(value.strip())
    if match is None:
        return value
    tz = match.group("tz")
    if tz not in ("Z", "z") and tz.replace(":", "") not in ("+0000", "-0000"):
        # A non-UTC offset is a different rendering the tests never produce;
        # return it untouched so the mismatch surfaces loudly.
        return value
    frac = (match.group("frac") or "")[:3].ljust(3, "0")
    return f"{match.group('date')}T{match.group('time')}.{frac}Z"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    assert normalise_instant(actual) == normalise_instant(expected), (
        f"{prefix}expected instant {expected!r}, got {actual!r}"
    )


def assert_instant_is_null(value: Any, label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    assert value is None, f"{prefix}expected null, got {value!r}"


def assert_iso_timestamp(value: Any, label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{prefix}expected an ISO-8601 timestamp, got {value!r}"
    )


# ------------------------------------------------------------------ envelopes


def ok(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate a success envelope and return its ``data`` object."""
    validate_success(response, expected_status)
    return get_success_data(response)


def created(response) -> Dict[str, Any]:
    return ok(response, 201)


def err(response, error_id: str) -> Dict[str, Any]:
    """Validate an error envelope carrying exactly ``error_id``.

    Per the standard error envelope, the ``error_id`` and its human-readable
    ``message`` both live inside ``data``, so that object is what is returned.
    """
    validate_error(response, error_id)
    body = response.json()
    return body.get("data", body)


def page(response):
    """Validate a paginated envelope; returns ``(items, meta)``."""
    return validate_paginated(response)


def assert_common_fields(entity: Dict[str, Any], *, versioned: bool = True) -> None:
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert_iso_timestamp(entity["created_at"], "created_at")
    if versioned:
        assert_iso_timestamp(entity["updated_at"], "updated_at")
        assert entity["version"] == 1 or isinstance(entity["version"], int)


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert an exact value for every named field, reporting all mismatches."""
    mismatches = []
    for field, value in expected.items():
        assert field in entity, f"field {field!r} missing from {sorted(entity)}"
        if entity[field] != value:
            mismatches.append(f"{field}: expected {value!r}, got {entity[field]!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_absent(entity: Dict[str, Any], *fields: str) -> None:
    present = [f for f in fields if f in entity]
    assert not present, f"fields unexpectedly present: {present}"


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert before[field] == after[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on an operation that stored nothing"
    )


def assert_version_advanced(
    before: Dict[str, Any], after: Dict[str, Any], steps: int = 1
) -> None:
    assert after["version"] == before["version"] + steps, (
        f"expected version {before['version'] + steps}, got {after['version']}"
    )


# ------------------------------------------------------------------ money / ratios


def assert_cents(actual: Any, expected: int, label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{prefix}cents must be a JSON integer, got {actual!r}"
    )
    assert actual == expected, f"{prefix}expected {expected} cents, got {actual}"


def assert_ratio(actual: Any, expected: float, label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{prefix}expected ratio {expected}, got {actual}"
    )


def assert_average(actual: Any, expected: Optional[float], label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    if expected is None:
        assert actual is None, f"{prefix}expected null average, got {actual!r}"
        return
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{prefix}expected average {expected}, got {actual}"
    )


# ------------------------------------------------------------------ derived rules


def expected_attendance_tier(attendance: int) -> str:
    if attendance >= TIER_4_FLOOR:
        return "TIER_4"
    if attendance >= TIER_3_FLOOR:
        return "TIER_3"
    if attendance >= TIER_2_FLOOR:
        return "TIER_2"
    return "TIER_1"


def expected_surcharge_bp(total_headcount: int) -> int:
    if total_headcount > SURCHARGE_TIER_3_HEADS:
        return SURCHARGE_TIER_3_BP
    if total_headcount > SURCHARGE_TIER_2_HEADS:
        return SURCHARGE_TIER_2_BP
    if total_headcount > SURCHARGE_TIER_1_HEADS:
        return SURCHARGE_TIER_1_BP
    return SURCHARGE_TIER_0_BP


def assert_reliability_in_range(score: Any, label: str = "reliability") -> None:
    assert isinstance(score, int), f"{label} must be an integer, got {score!r}"
    assert RELIABILITY_FLOOR <= score <= RELIABILITY_CEILING, (
        f"{label} {score} is outside the closed range "
        f"[{RELIABILITY_FLOOR}, {RELIABILITY_CEILING}]"
    )


def assert_ledger_identity(event: Dict[str, Any]) -> None:
    """total = approved + remaining must hold on every read of the event."""
    total = event["refund_budget_total_cents"]
    approved = event["refund_approved_total_cents"]
    remaining = event["refund_budget_remaining_cents"]
    assert approved + remaining == total, (
        f"ledger broken: approved {approved} + remaining {remaining} != total {total}"
    )


def assert_ledger(
    event: Dict[str, Any], *, approved: int, remaining: int, total: Optional[int] = None
) -> None:
    if total is not None:
        assert_cents(event["refund_budget_total_cents"], total, "refund_budget_total_cents")
    assert_cents(
        event["refund_approved_total_cents"], approved, "refund_approved_total_cents"
    )
    assert_cents(
        event["refund_budget_remaining_cents"], remaining, "refund_budget_remaining_cents"
    )
    assert_ledger_identity(event)


def assert_slot_fill(slot: Dict[str, Any], *, filled: int, required: int, status: str) -> None:
    assert_fields(
        slot,
        filled_headcount=filled,
        required_headcount=required,
        status=status,
    )


def assert_payout_totals(
    assignment: Dict[str, Any], *, base: int, gratuity: int, total: int
) -> None:
    assert_cents(assignment["base_pay_cents"], base, "base_pay_cents")
    assert_cents(assignment["gratuity_cents"], gratuity, "gratuity_cents")
    assert_cents(assignment["total_payout_cents"], total, "total_payout_cents")
    assert base + gratuity == total, (
        f"payout identity broken: {base} + {gratuity} != {total}"
    )


# ------------------------------------------------------------------ collections


def ids_of(items: Iterable[Dict[str, Any]]) -> List[str]:
    return [item["id"] for item in items]


def assert_ordered_by(
    items: List[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    values = [item[field] for item in items]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"items are not ordered by {field} "
        f"{'DESC' if descending else 'ASC'}: {values}"
    )


def find_by(items: Iterable[Dict[str, Any]], **match: Any) -> Optional[Dict[str, Any]]:
    for item in items:
        if all(item.get(k) == v for k, v in match.items()):
            return item
    return None


def only(items: List[Dict[str, Any]], **match: Any) -> Dict[str, Any]:
    """Assert exactly one item matches and return it."""
    hits = [i for i in items if all(i.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, f"expected exactly one match for {match}, got {len(hits)}"
    return hits[0]
