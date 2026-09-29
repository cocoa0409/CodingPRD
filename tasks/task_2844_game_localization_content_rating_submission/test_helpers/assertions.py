"""Domain assertions for the Game Localization & Rating Submission API.

These wrap the framework's generic structural helpers with the rules this
specification states: the common resource properties of §2.4, the three-digit
fractional-second timestamp rendering, the rounding scales of §2.8, the
created_at ascending ordering of §2.3 and the derived-counter definitions of §3.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DESCRIPTOR_WEIGHTS,
    RATING_BAND_UPPER_BOUNDS,
    RATING_STRICTNESS,
    SEVERITY_WEIGHTS,
    SURFACE_UPLIFT,
)

# ─── Instants ──────────────────────────────────────────────────────────


def normalize_instant(value: str) -> str:
    """Render an ISO 8601 UTC instant with exactly three fractional digits.

    Both ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000Z`` denote the
    same instant; comparisons go through this so that a difference in written
    precision is never mistaken for a difference in value.
    """
    assert isinstance(value, str), f"Expected an instant string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"Instant must be a UTC instant ending in Z: {value!r}"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "") -> None:
    """Assert two UTC instants denote the same moment."""
    assert actual is not None, f"{label or 'instant'} must not be null"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label or 'instant'}: expected {expected}, got {actual}"
    )


def assert_three_fractional_digits(value: str, label: str = "") -> None:
    """Assert an instant is rendered with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label or 'timestamp'} must be a string"
    assert_timestamp_format(value)
    assert "." in value and len(value.split(".", 1)[1]) == 4, (
        f"{label or 'timestamp'} must carry exactly three fractional digits: {value!r}"
    )


# ─── Common resource properties ────────────────────────────────────────


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None,
                         label: str = "resource") -> None:
    """Assert the id / created_at / updated_at / version quartet of §2.4."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id must be a UUID string with no type prefix: {entity.get('id')!r}"
    )
    assert_three_fractional_digits(entity["created_at"], f"{label}.created_at")
    assert_three_fractional_digits(entity["updated_at"], f"{label}.updated_at")
    assert isinstance(entity.get("version"), int), f"{label}.version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {entity['version']}"
        )


def assert_fresh_row(entity: Dict[str, Any], label: str = "resource") -> None:
    """A newly created row starts at version 1."""
    assert_common_fields(entity, expected_version=1, label=label)


def assert_version_is(entity: Dict[str, Any], expected: int, label: str = "resource") -> None:
    assert entity["version"] == expected, (
        f"{label}.version: expected {expected}, got {entity['version']}"
    )


def assert_version_bumped_by(after: Dict[str, Any], before: Dict[str, Any],
                             delta: int, label: str = "resource") -> None:
    """Assert exactly ``delta`` mutations landed on a row."""
    assert after["version"] == before["version"] + delta, (
        f"{label}.version: expected {before['version'] + delta} "
        f"({before['version']} + {delta}), got {after['version']}"
    )
    if delta > 0:
        assert normalize_instant(after["updated_at"]) >= normalize_instant(
            before["updated_at"]
        ), f"{label}.updated_at must refresh on every mutation"


def assert_unchanged_row(after: Dict[str, Any], before: Dict[str, Any],
                         label: str = "resource") -> None:
    """A read, or a refused write, mutates nothing."""
    assert after["version"] == before["version"], (
        f"{label}.version must not move: {before['version']} → {after['version']}"
    )
    assert_instant_equals(after["updated_at"], before["updated_at"],
                          f"{label}.updated_at")


# ─── Numeric scales (§2.8) ─────────────────────────────────────────────


def assert_money_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Monetary amounts are integer cents carried as JSON numbers."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_effort_units(actual: Any, expected: float, label: str = "text_effort_units") -> None:
    """Effort totals carry two decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert round(float(actual), 2) == round(expected, 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_defect_density(actual: Any, expected: float, label: str = "defect_density") -> None:
    """Defect density is rounded half up to four decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert round(float(actual), 4) == round(expected, 4), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )


def assert_whole_minutes(actual: Any, expected: int, label: str = "minutes") -> None:
    """Booth and talent minute totals are whole minutes computed exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a whole number of minutes, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ─── Ordering (§2.3) ───────────────────────────────────────────────────


def assert_created_at_ascending(rows: List[Dict[str, Any]],
                                natural_key: Optional[str] = None) -> None:
    """Assert a listing is ordered oldest first, ties broken by the natural key."""
    previous = None
    for row in rows:
        current = normalize_instant(row["created_at"])
        if previous is not None:
            assert current >= previous[0], (
                f"List is not ordered by created_at ascending: {previous[0]} then {current}"
            )
            if natural_key is not None and current == previous[0]:
                assert str(row[natural_key]) >= str(previous[1]), (
                    f"Tie on created_at must be broken by {natural_key} ascending: "
                    f"{previous[1]} then {row[natural_key]}"
                )
        previous = (current, row.get(natural_key) if natural_key else None)


def assert_id_order(rows: List[Dict[str, Any]], expected_ids: List[str],
                    label: str = "listing") -> None:
    assert [row["id"] for row in rows] == expected_ids, (
        f"{label}: expected ids {expected_ids}, got {[row['id'] for row in rows]}"
    )


def assert_pagination_meta(meta: Dict[str, Any], limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"meta.offset: expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


# ─── Derived arithmetic mirrors ────────────────────────────────────────


def tm_factor(tm_match_pct: int) -> float:
    """The translation-memory factor bands of §3.2."""
    if tm_match_pct >= 95:
        return 0.10
    if tm_match_pct >= 75:
        return 0.45
    if tm_match_pct >= 50:
        return 0.75
    return 1.00


def _round_half_up(value: float, places: int) -> float:
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def effort_units(rows: List[Dict[str, Any]]) -> float:
    """Per-key contributions rounded to one decimal, then summed and rounded to two.

    Each row supplies ``source_char_count``, ``tm_match_pct`` and ``ui_surface``.
    """
    total = 0.0
    for row in rows:
        raw = (
            row["source_char_count"] / 100.0
            * tm_factor(row["tm_match_pct"])
            * SURFACE_UPLIFT[row["ui_surface"]]
        )
        total += _round_half_up(raw, 1)
    return _round_half_up(total, 2)


def base_risk_points(codes: List[str]) -> int:
    """The sum of the descriptor weights of an effective disclosure set."""
    return sum(DESCRIPTOR_WEIGHTS[code] for code in codes)


def band_for_score(score: int) -> str:
    """Map a risk score onto its rating band."""
    for band, upper in RATING_BAND_UPPER_BOUNDS:
        if score <= upper:
            return band
    return "ADULTS_ONLY_18"


def weighted_points(severities: List[str]) -> int:
    """Severity weights of the open set."""
    return sum(SEVERITY_WEIGHTS[severity] for severity in severities)


def is_no_stricter_than(candidate: str, target: str) -> bool:
    """True when ``candidate`` sits at or before ``target`` in the strictness order."""
    return RATING_STRICTNESS[candidate] <= RATING_STRICTNESS[target]


# ─── Entity shape assertions ───────────────────────────────────────────


def assert_new_title(title: Dict[str, Any]) -> None:
    """A newly registered title opens in PLANNING with zeroed counters."""
    assert_fresh_row(title, "title")
    assert title["localization_state"] == "PLANNING"
    assert title["string_lock"] is False
    assert title["release_gate_state"] == "OPEN"
    assert title["extracted_key_count"] == 0
    assert title["market_plan_count"] == 0
    assert title["ready_market_count"] == 0


def assert_new_market_plan(plan: Dict[str, Any]) -> None:
    """A new market plan opens in DRAFT with a zeroed effort and cost ledger."""
    assert_fresh_row(plan, "market_plan")
    assert plan["status"] == "DRAFT"
    assert plan["blocked_reason"] is None
    assert_effort_units(plan["text_effort_units"], 0.00)
    assert plan["text_effort_variant"] is None
    assert_money_cents(plan["localization_cost_cents"], 0, "localization_cost_cents")
    assert_money_cents(plan["overage_cents"], 0, "overage_cents")


def assert_new_translation_unit(unit: Dict[str, Any]) -> None:
    """Cascade-created units open PENDING / NOT_CHECKED with empty text."""
    assert_fresh_row(unit, "translation_unit")
    assert unit["translation_status"] == "PENDING"
    assert unit["qa_status"] == "NOT_CHECKED"
    assert unit["target_text"] is None
    assert unit["target_char_count"] == 0
    assert unit["applied_tm_match_pct"] is None
    assert unit["overflow_chars"] == 0
    assert unit["open_bug_count"] == 0


def assert_new_qa_pass(qa_pass: Dict[str, Any], opened_by_user_id: str) -> None:
    """A new pass opens OPEN with a zeroed density ledger."""
    assert_fresh_row(qa_pass, "qa_pass")
    assert qa_pass["status"] == "OPEN"
    assert qa_pass["opened_by_user_id"] == opened_by_user_id
    assert qa_pass["reopen_count"] == 0
    assert qa_pass["weighted_defect_points"] == 0
    assert_defect_density(qa_pass["defect_density"], 0.0000)
    assert qa_pass["closed_at_utc"] is None


def assert_new_submission(submission: Dict[str, Any]) -> None:
    """A new submission opens DRAFT with every outcome field still null."""
    assert_fresh_row(submission, "rating_submission")
    assert submission["status"] == "DRAFT"
    assert submission["assigned_rating"] is None
    assert submission["self_assessed_risk_score"] is None
    assert submission["board_adjusted_risk_score"] is None
    assert submission["projected_rating_band"] is None
    assert submission["submitted_by_user_id"] is None
    assert submission["reviewed_by_user_id"] is None
    assert submission["submitted_at_utc"] is None
    assert_money_cents(submission["fee_cents"], 0, "fee_cents")
    assert submission["appeal_count"] == 0


def assert_iso_or_null(value: Any, label: str = "timestamp") -> None:
    assert value is None or is_iso8601_timestamp(value), (
        f"{label} must be null or an ISO 8601 UTC timestamp: {value!r}"
    )
