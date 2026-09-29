"""
Domain assertions for the institutional research reporting contract.

Timestamp comparisons always route through canonical_instant() so that a server
echoing a different sub-second width than the literal in a test is not treated as
a contract violation, while the instant itself is still compared exactly.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant
from .constants import (
    CONTROLLED_ROUNDING_BASE,
    ONE_DECIMAL,
    TWO_DECIMALS,
)

# ─── Numeric shape ────────────────────────────────────────────────


def assert_json_number(value: Any, field: str) -> None:
    """Percentages and monetary values are returned as JSON numbers, never as strings."""
    assert not isinstance(value, str), f"{field} must be a JSON number, got the string {value!r}"
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__}"
    )


def assert_integer_count(value: Any, field: str) -> None:
    """Whole integers, no rounding, apply to every count in the contract."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole integer, got {value!r}"
    )


def round_half_up(value: Any, places: int) -> float:
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def assert_one_decimal(value: Any, field: str) -> None:
    """A percentage describing reported data carries one decimal place."""
    if value is None:
        return
    assert_json_number(value, field)
    assert round_half_up(value, ONE_DECIMAL) == float(value), (
        f"{field} must be rounded to {ONE_DECIMAL} decimal place, got {value!r}"
    )


def assert_two_decimals(value: Any, field: str) -> None:
    """A delta percentage carries two decimal places."""
    if value is None:
        return
    assert_json_number(value, field)
    assert round_half_up(value, TWO_DECIMALS) == float(value), (
        f"{field} must be rounded to {TWO_DECIMALS} decimal places, got {value!r}"
    )


def assert_equals_number(actual: Any, expected: Any, field: str) -> None:
    if expected is None:
        assert actual is None, f"{field} must be null, got {actual!r}"
        return
    assert_json_number(actual, field)
    assert float(actual) == float(expected), f"{field} must be {expected}, got {actual!r}"


def assert_null(value: Any, field: str) -> None:
    """An undefined derived figure is null, not zero."""
    assert value is None, f"{field} must be null, got {value!r}"


# ─── Common fields ────────────────────────────────────────────────


def assert_common_fields(row: Dict[str, Any], label: str = "row") -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row.get("id")), f"{label}.id must be a UUID, got {row.get('id')!r}"
    assert "_" not in str(row["id"]), f"{label}.id must carry no type prefix, got {row['id']!r}"
    for field in ("created_at", "updated_at"):
        assert is_iso8601_timestamp(row.get(field)), (
            f"{label}.{field} must be an ISO 8601 timestamp, got {row.get(field)!r}"
        )
    assert_integer_count(row.get("version"), f"{label}.version")
    assert row["version"] >= 1, f"{label}.version must start at 1, got {row['version']}"


def assert_version(row: Dict[str, Any], expected: int, label: str = "row") -> None:
    assert row.get("version") == expected, (
        f"{label}.version must be {expected}, got {row.get('version')!r}"
    )


def assert_version_bumped(after: Dict[str, Any], before: Dict[str, Any], label: str = "row") -> None:
    """Recomputation counts as mutation, so the version increases by at least 1."""
    assert after["version"] > before["version"], (
        f"{label}.version must advance past {before['version']}, got {after['version']}"
    )


def assert_immutable_definition_shape(row: Dict[str, Any]) -> None:
    """A federal definition carries only id and created_at; updated_at and version are absent."""
    assert is_valid_uuid(row.get("id")), f"definition.id must be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"definition.created_at must be an ISO 8601 timestamp, got {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, "a federal definition must not carry updated_at"
    assert "version" not in row, "a federal definition must not carry version"


# ─── Instants ─────────────────────────────────────────────────────


def assert_instant_equals(actual: Optional[str], expected: Optional[str], field: str) -> None:
    if expected is None:
        assert actual is None, f"{field} must be null, got {actual!r}"
        return
    assert actual is not None, f"{field} must be stamped, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field} must be {expected}, got {actual!r}"
    )


def assert_instant_stamped(value: Optional[str], field: str) -> None:
    assert value is not None, f"{field} must be stamped from the logical clock, got null"
    assert is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 timestamp, got {value!r}"
    )


def assert_instant_before(earlier: str, later: str, label: str = "") -> None:
    assert canonical_instant(earlier) < canonical_instant(later), (
        f"{label}: {earlier!r} must precede {later!r}"
    )


def assert_calendar_date(value: Any, field: str) -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


# ─── Envelope ─────────────────────────────────────────────────────


def assert_error_body_leaks_nothing(body: Dict[str, Any]) -> None:
    """An error envelope carries only the two request fields in meta and only the error pair."""
    meta = body.get("meta", {})
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only the two request fields, got {sorted(meta.keys())}"
    )
    assert body.get("response_type") == "error", (
        f"error envelope response_type must be 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data") or {}
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data must carry only error_id and message, got {sorted(data.keys())}"
    )


# ─── Reporting cycle ──────────────────────────────────────────────


def assert_cycle_posture(cycle: Dict[str, Any], expected: str) -> None:
    assert cycle.get("snapshot_posture") == expected, (
        f"cycle.snapshot_posture must be {expected}, got {cycle.get('snapshot_posture')!r}"
    )


def assert_cycle_ledger(
    cycle: Dict[str, Any],
    frozen_file_count: Optional[int] = None,
    active_record_count: Optional[int] = None,
    reopen_count: Optional[int] = None,
) -> None:
    """The derived extract ledgers are whole integers recomputed on every registration."""
    for field, expected in (
        ("frozen_file_count", frozen_file_count),
        ("active_record_count", active_record_count),
        ("reopen_count", reopen_count),
    ):
        if expected is None:
            continue
        assert_integer_count(cycle.get(field), f"cycle.{field}")
        assert cycle[field] == expected, (
            f"cycle.{field} must be {expected}, got {cycle[field]}"
        )


# ─── Survey component and edit checks ─────────────────────────────


def assert_component_status(
    component: Dict[str, Any],
    prep_status: Optional[str] = None,
    edit_status: Optional[str] = None,
    fatal_open_count: Optional[int] = None,
) -> None:
    """Preparation status and edit status advance as two independent dimensions."""
    if prep_status is not None:
        assert component.get("prep_status") == prep_status, (
            f"component.prep_status must be {prep_status}, got {component.get('prep_status')!r}"
        )
    if edit_status is not None:
        assert component.get("edit_status") == edit_status, (
            f"component.edit_status must be {edit_status}, got {component.get('edit_status')!r}"
        )
    if fatal_open_count is not None:
        assert_integer_count(component.get("fatal_open_count"), "component.fatal_open_count")
        assert component["fatal_open_count"] == fatal_open_count, (
            f"component.fatal_open_count must be {fatal_open_count}, got {component['fatal_open_count']}"
        )


def assert_sequence_numbers_ascending(checks: Iterable[Dict[str, Any]]) -> None:
    """Edit checks are numbered from 1 upward in the order the cascade raised them."""
    numbers = [c["sequence_no"] for c in checks]
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"edit check sequence_no must run 1..{len(numbers)}, got {numbers}"
    )


def assert_metric_keys_ascending(checks: Iterable[Dict[str, Any]]) -> None:
    """The cascade walks the component's metrics in metric_key ascending order."""
    keys = [c["metric_key"] for c in checks]
    assert keys == sorted(keys), f"edit check metric_key order must ascend, got {keys}"


def assert_edit_check(
    check: Dict[str, Any],
    check_code: Optional[str] = None,
    metric_key: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    sequence_no: Optional[int] = None,
    variance_pct: Any = "__skip__",
    observed_value: Any = "__skip__",
    prior_year_value: Any = "__skip__",
    explanation_round: Optional[int] = None,
) -> None:
    if check_code is not None:
        assert check.get("check_code") == check_code, (
            f"edit_check.check_code must be {check_code}, got {check.get('check_code')!r}"
        )
    if metric_key is not None:
        assert check.get("metric_key") == metric_key, (
            f"edit_check.metric_key must be {metric_key}, got {check.get('metric_key')!r}"
        )
    if severity is not None:
        assert check.get("severity") == severity, (
            f"edit_check.severity must be {severity}, got {check.get('severity')!r}"
        )
    if status is not None:
        assert check.get("status") == status, (
            f"edit_check.status must be {status}, got {check.get('status')!r}"
        )
    if sequence_no is not None:
        assert check.get("sequence_no") == sequence_no, (
            f"edit_check.sequence_no must be {sequence_no}, got {check.get('sequence_no')!r}"
        )
    if variance_pct != "__skip__":
        assert_equals_number(check.get("variance_pct"), variance_pct, "edit_check.variance_pct")
        assert_one_decimal(check.get("variance_pct"), "edit_check.variance_pct")
    if observed_value != "__skip__":
        assert_equals_number(check.get("observed_value"), observed_value, "edit_check.observed_value")
    if prior_year_value != "__skip__":
        assert_equals_number(
            check.get("prior_year_value"), prior_year_value, "edit_check.prior_year_value"
        )
    if explanation_round is not None:
        assert check.get("explanation_round") == explanation_round, (
            f"edit_check.explanation_round must be {explanation_round}, "
            f"got {check.get('explanation_round')!r}"
        )


# ─── Cohorts and rate variants ────────────────────────────────────


def assert_cohort_counts(
    cohort: Dict[str, Any],
    initial_count: Optional[int] = None,
    exclusion_count: Optional[int] = None,
    adjusted_count: Optional[int] = None,
    completers_count: Optional[int] = None,
    retained_count: Optional[int] = None,
) -> None:
    """The five headcounts are always recomputed from scratch over every member."""
    for field, expected in (
        ("initial_count", initial_count),
        ("exclusion_count", exclusion_count),
        ("adjusted_count", adjusted_count),
        ("completers_count", completers_count),
        ("retained_count", retained_count),
    ):
        if expected is None:
            continue
        assert_integer_count(cohort.get(field), f"cohort.{field}")
        assert cohort[field] == expected, (
            f"cohort.{field} must be {expected}, got {cohort[field]}"
        )


def assert_cohort_conservation(row: Dict[str, Any], label: str = "cohort") -> None:
    """adjusted_count plus exclusion_count always equals initial_count."""
    adjusted = row["adjusted_count"]
    excluded = row["exclusion_count"]
    initial = row["initial_count"]
    assert adjusted + excluded == initial, (
        f"{label}: adjusted_count {adjusted} plus exclusion_count {excluded} "
        f"must equal initial_count {initial}"
    )


def assert_rate_variants(
    row: Dict[str, Any],
    federal_rate_pct: Any = "__skip__",
    ranking_rate_pct: Any = "__skip__",
) -> None:
    if federal_rate_pct != "__skip__":
        assert_equals_number(row.get("federal_rate_pct"), federal_rate_pct, "federal_rate_pct")
        assert_one_decimal(row.get("federal_rate_pct"), "federal_rate_pct")
    if ranking_rate_pct != "__skip__":
        assert_equals_number(row.get("ranking_rate_pct"), ranking_rate_pct, "ranking_rate_pct")
        assert_one_decimal(row.get("ranking_rate_pct"), "ranking_rate_pct")


def assert_divergence_is_difference_of_published_variants(summary: Dict[str, Any]) -> None:
    """The divergence is computed from the two already-rounded variants."""
    federal = summary.get("federal_rate_pct")
    ranking = summary.get("ranking_rate_pct")
    divergence = summary.get("rate_divergence_pp")
    if federal is None or ranking is None:
        assert_null(divergence, "rate_divergence_pp")
        return
    assert_one_decimal(divergence, "rate_divergence_pp")
    expected = round_half_up(float(federal) - float(ranking), ONE_DECIMAL)
    assert float(divergence) == expected, (
        f"rate_divergence_pp must be {expected} — the federal rate {federal} minus "
        f"the ranking rate {ranking} — got {divergence}"
    )


# ─── Publications and the restatement ledger ──────────────────────


def assert_publication_ledger(
    publication: Dict[str, Any],
    published_value: Any = "__skip__",
    original_value: Any = "__skip__",
    net_applied_delta: Any = "__skip__",
    restatement_count: Optional[int] = None,
    publication_status: Optional[str] = None,
) -> None:
    if published_value != "__skip__":
        assert_equals_number(publication.get("published_value"), published_value, "published_value")
    if original_value != "__skip__":
        assert_equals_number(publication.get("original_value"), original_value, "original_value")
    if net_applied_delta != "__skip__":
        assert_equals_number(
            publication.get("net_applied_delta"), net_applied_delta, "net_applied_delta"
        )
        assert_one_decimal(publication.get("net_applied_delta"), "net_applied_delta")
    if restatement_count is not None:
        assert_integer_count(publication.get("restatement_count"), "restatement_count")
        assert publication["restatement_count"] == restatement_count, (
            f"restatement_count must be {restatement_count}, got {publication['restatement_count']}"
        )
    if publication_status is not None:
        assert publication.get("publication_status") == publication_status, (
            f"publication_status must be {publication_status}, "
            f"got {publication.get('publication_status')!r}"
        )
    assert_ledger_invariant(publication)


def assert_ledger_invariant(publication: Dict[str, Any]) -> None:
    """published_value always equals original_value plus net_applied_delta."""
    expected = round_half_up(
        float(publication["original_value"]) + float(publication["net_applied_delta"]),
        ONE_DECIMAL,
    )
    assert float(publication["published_value"]) == expected, (
        f"published_value {publication['published_value']} must equal original_value "
        f"{publication['original_value']} plus net_applied_delta "
        f"{publication['net_applied_delta']} — expected {expected}"
    )


def assert_restatement(
    restatement: Dict[str, Any],
    status: Optional[str] = None,
    origin: Optional[str] = None,
    requested_by_user_id: Any = "__skip__",
    baseline_value: Any = "__skip__",
    proposed_value: Any = "__skip__",
    delta_pct: Any = "__skip__",
    public_notice_required: Any = "__skip__",
) -> None:
    if status is not None:
        assert restatement.get("status") == status, (
            f"restatement.status must be {status}, got {restatement.get('status')!r}"
        )
    if origin is not None:
        assert restatement.get("origin") == origin, (
            f"restatement.origin must be {origin}, got {restatement.get('origin')!r}"
        )
    if requested_by_user_id != "__skip__":
        assert restatement.get("requested_by_user_id") == requested_by_user_id, (
            f"restatement.requested_by_user_id must be {requested_by_user_id!r}, "
            f"got {restatement.get('requested_by_user_id')!r}"
        )
    if baseline_value != "__skip__":
        assert_equals_number(restatement.get("baseline_value"), baseline_value, "baseline_value")
    if proposed_value != "__skip__":
        assert_equals_number(restatement.get("proposed_value"), proposed_value, "proposed_value")
    if delta_pct != "__skip__":
        assert_equals_number(restatement.get("delta_pct"), delta_pct, "delta_pct")
        assert_two_decimals(restatement.get("delta_pct"), "delta_pct")
    if public_notice_required != "__skip__":
        assert restatement.get("public_notice_required") is public_notice_required, (
            f"public_notice_required must be {public_notice_required}, "
            f"got {restatement.get('public_notice_required')!r}"
        )


# ─── External submissions ─────────────────────────────────────────


def assert_reconciliation(
    submission: Dict[str, Any],
    federal_value: Any = "__skip__",
    raw_delta_pct: Any = "__skip__",
    allowance_pct: Any = "__skip__",
    effective_delta_pct: Any = "__skip__",
    tolerance_pct: Any = "__skip__",
    status: Optional[str] = None,
) -> None:
    if federal_value != "__skip__":
        assert_equals_number(submission.get("federal_value"), federal_value, "federal_value")
    for field, expected in (
        ("raw_delta_pct", raw_delta_pct),
        ("allowance_pct", allowance_pct),
        ("effective_delta_pct", effective_delta_pct),
        ("tolerance_pct", tolerance_pct),
    ):
        if expected == "__skip__":
            continue
        assert_equals_number(submission.get(field), expected, field)
        assert_two_decimals(submission.get(field), field)
    if status is not None:
        assert submission.get("status") == status, (
            f"submission.status must be {status}, got {submission.get('status')!r}"
        )


def assert_reconciliation_fields_all_null(submission: Dict[str, Any]) -> None:
    """A submission that never reconciled carries five null reconciliation figures."""
    for field in (
        "federal_value",
        "raw_delta_pct",
        "allowance_pct",
        "effective_delta_pct",
        "tolerance_pct",
    ):
        assert_null(submission.get(field), f"submission.{field}")


# ─── Disclosure avoidance ─────────────────────────────────────────


def assert_request_counters(
    request: Dict[str, Any],
    cell_count: Optional[int] = None,
    released_cell_count: Optional[int] = None,
    suppressed_cell_count: Optional[int] = None,
    residual_disclosure_risk: Any = "__skip__",
    status: Optional[str] = None,
) -> None:
    for field, expected in (
        ("cell_count", cell_count),
        ("released_cell_count", released_cell_count),
        ("suppressed_cell_count", suppressed_cell_count),
    ):
        if expected is None:
            continue
        assert_integer_count(request.get(field), f"data_request.{field}")
        assert request[field] == expected, (
            f"data_request.{field} must be {expected}, got {request[field]}"
        )
    if residual_disclosure_risk != "__skip__":
        assert request.get("residual_disclosure_risk") is residual_disclosure_risk, (
            f"residual_disclosure_risk must be {residual_disclosure_risk}, "
            f"got {request.get('residual_disclosure_risk')!r}"
        )
    if status is not None:
        assert request.get("status") == status, (
            f"data_request.status must be {status}, got {request.get('status')!r}"
        )


def assert_cell(
    cell: Dict[str, Any],
    suppression_state: Optional[str] = None,
    released_count: Any = "__skip__",
    raw_count: Any = "__skip__",
) -> None:
    if suppression_state is not None:
        assert cell.get("suppression_state") == suppression_state, (
            f"cell {cell.get('dimension_key')!r} suppression_state must be {suppression_state}, "
            f"got {cell.get('suppression_state')!r}"
        )
    if released_count != "__skip__":
        assert_equals_number(
            cell.get("released_count"), released_count,
            f"cell {cell.get('dimension_key')!r} released_count",
        )
    if raw_count != "__skip__":
        assert_equals_number(
            cell.get("raw_count"), raw_count,
            f"cell {cell.get('dimension_key')!r} raw_count",
        )


def assert_controlled_rounding(cell: Dict[str, Any]) -> None:
    """Controlled rounding releases every cell at its raw count snapped to a multiple of five."""
    expected = int(round_half_up(float(cell["raw_count"]) / CONTROLLED_ROUNDING_BASE, 0)) * (
        CONTROLLED_ROUNDING_BASE
    )
    assert cell["released_count"] == expected, (
        f"cell {cell.get('dimension_key')!r} released_count must be {expected} — "
        f"the raw count {cell['raw_count']} snapped to a multiple of {CONTROLLED_ROUNDING_BASE} — "
        f"got {cell['released_count']}"
    )


def cells_by_key(cells: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {cell["dimension_key"]: cell for cell in cells}


def rows_by_id(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {row["id"]: row for row in rows}


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_ordered_by(rows: Iterable[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows must be ordered by {field} ascending, got {values}"
