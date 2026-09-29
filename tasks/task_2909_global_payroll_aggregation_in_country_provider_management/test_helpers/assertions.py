"""Domain assertions for the Global Payroll Aggregation API.

Instant comparison is canonicalised in exactly one place — `canonical_instant` —
at the three-fractional-digit width the PRD mandates, so every call site compares
instants the same way.
"""

import re
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import APPEND_ONLY_FIELDS, COMMON_FIELDS

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ─── Instants and dates (PRD 2.4) ─────────────────────────────────────────────


def canonical_instant(value: str) -> str:
    """Render an ISO 8601 UTC instant with exactly three fractional digits.

    The single place where sub-second width is normalised, so that comparing a
    literal such as `2026-08-26T17:00:00.000Z` against a server value never
    fails purely on fractional-digit width.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 instant string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"Not an ISO 8601 UTC instant: {value!r}"
    date_part, time_part, frac = match.group(1), match.group(2), match.group(3) or ""
    millis = (frac + "000")[:3]
    return f"{date_part}T{time_part}.{millis}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same millisecond."""
    assert actual is not None, f"{label} must not be null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label} expected {expected}, got {actual}"
    )


def assert_instant_format(value: Any, label: str = "instant") -> None:
    """PRD 2.4: instants render with exactly three fractional digits and a `Z`."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601 UTC: {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"{label} is not ISO 8601 UTC: {value!r}"
    assert match.group(3) is not None and len(match.group(3)) == 3, (
        f"{label} must carry exactly three fractional-second digits: {value!r}"
    )


def assert_date_only(value: Any, label: str = "date") -> None:
    """PRD 2.4: calendar-date fields are plain `YYYY-MM-DD` with no time part."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _DATE_RE.match(value), f"{label} must be a plain YYYY-MM-DD date: {value!r}"


# ─── Envelope and identity (PRD 2.2, 2.4) ─────────────────────────────────────


def assert_server_minted_id(entity: Dict[str, Any]) -> None:
    """PRD 2.4: every resource is identified by a server-minted UUID, no prefix."""
    assert "id" in entity, "resource is missing its `id`"
    assert is_valid_uuid(entity["id"]), (
        f"`id` must be a UUID with no type prefix: {entity['id']!r}"
    )


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """PRD 2.4: `created_at`, `updated_at` and `version` on the ten versioned kinds."""
    assert_server_minted_id(entity)
    for field in COMMON_FIELDS:
        assert field in entity, f"resource is missing common field `{field}`"
    assert_instant_format(entity["created_at"], "created_at")
    assert_instant_format(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int), "`version` must be an integer"
    assert entity["version"] >= 1, "`version` starts at 1 on creation"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_fields(entity: Dict[str, Any]) -> None:
    """PRD 2.4: an audit evidence item carries only `id` and `created_at`."""
    for field in APPEND_ONLY_FIELDS:
        assert field in entity, f"audit evidence item is missing `{field}`"
    assert_server_minted_id(entity)
    assert_instant_format(entity["created_at"], "created_at")
    assert "updated_at" not in entity, (
        "an audit evidence item has no `updated_at`, and the field must not appear"
    )
    assert "version" not in entity, (
        "an audit evidence item has no `version`, and the field must not appear"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: int,
    expected_has_more: bool,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
) -> None:
    """PRD 2.3: `total_count` counts matching rows before the page window."""
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is expected_has_more, (
        f"expected has_more {expected_has_more}, got {meta['has_more']}"
    )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"expected limit {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"expected offset {expected_offset}, got {meta['offset']}"
        )


# ─── Money and percentages (PRD 2.6) ──────────────────────────────────────────


def assert_minor_amount(value: Any, expected: int, label: str) -> None:
    """PRD 2.6: every `_minor` field is an integer number of minor units."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer minor-unit amount, got {value!r}"
    )
    assert value == expected, f"{label} expected {expected}, got {value}"


def assert_pct(value: Any, expected: float, label: str) -> None:
    """PRD 2.6: percentage-bearing fields carry two decimal places."""
    assert value is not None, f"{label} must not be null"
    assert abs(float(value) - expected) < 1e-9, (
        f"{label} expected {expected:.2f}, got {value}"
    )


def assert_field_values(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert a batch of exact field values on one resource representation."""
    for field, want in expected.items():
        assert field in entity, f"resource is missing field `{field}`"
        got = entity[field]
        if isinstance(want, float):
            assert abs(float(got) - want) < 1e-9, (
                f"`{field}` expected {want}, got {got}"
            )
        else:
            assert got == want, f"`{field}` expected {want!r}, got {got!r}"


def assert_null_fields(entity: Dict[str, Any], fields: Iterable[str]) -> None:
    """Assert each named field is present and null."""
    for field in fields:
        assert field in entity, f"resource is missing field `{field}`"
        assert entity[field] is None, f"`{field}` expected null, got {entity[field]!r}"


# ─── Domain entity assertions ─────────────────────────────────────────────────


def assert_cycle_state(
    cycle: Dict[str, Any], status: str, hold_reason: Optional[str] = None
) -> None:
    """PRD 3.3: `hold_reason` is null whenever the status is not `ON_HOLD`."""
    assert cycle["status"] == status, (
        f"cycle expected status {status}, got {cycle['status']}"
    )
    assert cycle["hold_reason"] == hold_reason, (
        f"cycle expected hold_reason {hold_reason!r}, got {cycle['hold_reason']!r}"
    )


def assert_provider_standing(
    provider: Dict[str, Any],
    status: str,
    service_score: Optional[float] = None,
    open_penalty_minor: Optional[int] = None,
    score_variant_applied: Optional[str] = None,
) -> None:
    """PRD 3.8: standing, score and penalty exposure are read together."""
    assert provider["status"] == status, (
        f"provider expected status {status}, got {provider['status']}"
    )
    if service_score is not None:
        assert_pct(provider["service_score"], service_score, "service_score")
    if open_penalty_minor is not None:
        assert_minor_amount(
            provider["open_penalty_minor"], open_penalty_minor, "open_penalty_minor"
        )
    if score_variant_applied is not None:
        assert provider["score_variant_applied"] == score_variant_applied, (
            "provider expected score_variant_applied "
            f"{score_variant_applied}, got {provider['score_variant_applied']}"
        )


def assert_variance_analysis(
    run: Dict[str, Any],
    variance_basis: str,
    variance_pct: Optional[float],
    headcount_drift_pct: Optional[float],
    variance_material: bool,
) -> None:
    """PRD 3.5: the four variance fields persisted on every scored run."""
    assert run["variance_basis"] == variance_basis, (
        f"expected variance_basis {variance_basis}, got {run['variance_basis']}"
    )
    if variance_pct is None:
        assert run["variance_pct"] is None, (
            f"expected variance_pct null, got {run['variance_pct']}"
        )
    else:
        assert_pct(run["variance_pct"], variance_pct, "variance_pct")
    if headcount_drift_pct is None:
        assert run["headcount_drift_pct"] is None, (
            f"expected headcount_drift_pct null, got {run['headcount_drift_pct']}"
        )
    else:
        assert_pct(run["headcount_drift_pct"], headcount_drift_pct, "headcount_drift_pct")
    assert run["variance_material"] is variance_material, (
        f"expected variance_material {variance_material}, got {run['variance_material']}"
    )


def assert_penalty_assessment(
    filing: Dict[str, Any],
    late_days: int,
    base_penalty_minor: int,
    surcharge_minor: int,
    total_penalty_minor: int,
    provider_share_minor: int,
    client_share_minor: int,
    penalty_owner: str,
) -> None:
    """PRD 3.7: the seven-step penalty assessment, plus the ownership label."""
    assert filing["late_days"] == late_days, (
        f"expected late_days {late_days}, got {filing['late_days']}"
    )
    assert_minor_amount(
        filing["base_penalty_minor"], base_penalty_minor, "base_penalty_minor"
    )
    assert_minor_amount(filing["surcharge_minor"], surcharge_minor, "surcharge_minor")
    assert_minor_amount(
        filing["total_penalty_minor"], total_penalty_minor, "total_penalty_minor"
    )
    assert_minor_amount(
        filing["provider_share_minor"], provider_share_minor, "provider_share_minor"
    )
    assert_minor_amount(
        filing["client_share_minor"], client_share_minor, "client_share_minor"
    )
    assert (
        filing["provider_share_minor"] + filing["client_share_minor"]
        == filing["total_penalty_minor"]
    ), "the two shares must sum exactly to the total with no rounding drift"
    assert filing["penalty_owner"] == penalty_owner, (
        f"expected penalty_owner {penalty_owner}, got {filing['penalty_owner']}"
    )


def find_by(rows: Iterable[Dict[str, Any]], field: str, value: Any) -> Dict[str, Any]:
    """Return the single row whose `field` equals `value`."""
    matches = [row for row in rows if row.get(field) == value]
    assert len(matches) == 1, (
        f"expected exactly one row with {field}={value!r}, found {len(matches)}"
    )
    return matches[0]
