"""Domain assertions for the Police Professional Standards API.

These wrap the shared structural helpers with the vocabulary of this contract:
instants compare on their canonical form rather than on raw strings, quantities
that the contract fixes to a stated number of decimal places compare on that
rounding, and the common entity shapes are checked once here instead of in every
test.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant


# ── Instants ───────────────────────────────────────────────────────────────

def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment.

    Sub-second precision is not part of the comparison: both sides are reduced
    to a canonical three-digit form first, so a value rendered without a
    fractional part still matches the same moment rendered with one.
    """
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant in the rendering the contract uses."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"{label}: must be rendered in UTC with a Z suffix: {value!r}"


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_quantity(actual: Any, expected: float, places: int = 2, label: str = "value") -> None:
    """Assert a fixed-precision quantity equals the expected figure at that precision."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label}: expected {expected} at {places} decimal places, got {actual}"
    )


def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a two-decimal-place figure, the precision most scores are carried at."""
    assert_quantity(actual, expected, 2, label)


def assert_one_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a one-decimal-place figure, the precision the sustain rate is carried at."""
    assert_quantity(actual, expected, 1, label)


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money amount, which the contract carries as an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


# ── Envelope and common fields ─────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the meta block carries a prefixed request id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_identity_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert a resource carries a server-minted UUID and a UTC creation instant."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")


def assert_mutable_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert the full identity quartet on a resource that can be mutated."""
    assert_identity_fields(data, label)
    assert_instant_format(data["updated_at"], f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert an append-only record carries only an identifier and a creation instant.

    Append-only records are never updated, so they expose neither an update
    instant nor a version counter.
    """
    assert_identity_fields(data, label)
    assert "updated_at" not in data, f"{label} is append-only and must not expose updated_at"
    assert "version" not in data, f"{label} is append-only and must not expose version"


def assert_created_equals_updated(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert a freshly created resource has not been touched since creation."""
    assert_instant(data["updated_at"], data["created_at"], f"{label}.updated_at")
    assert data["version"] == 1, f"{label}.version on creation must be 1, got {data['version']}"


# ── Listing envelope ───────────────────────────────────────────────────────

def assert_list_page(meta: Dict[str, Any], limit: int, offset: int, total: int, has_more: bool) -> None:
    """Assert a list response reports the page it served and the size of the collection."""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset: expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"meta.total_count: expected {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_single_read_omits_pagination(body: Dict[str, Any]) -> None:
    """Assert a single-resource read carries none of the pagination figures."""
    meta = body["meta"]
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta, f"a single read must omit meta.{key}"


def assert_ids_in_order(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert a list came back in exactly the expected order of identifiers."""
    actual = [row["id"] for row in rows]
    expected = list(expected_ids)
    assert actual == expected, f"row order: expected {expected}, got {actual}"


# ── Officer ledgers ────────────────────────────────────────────────────────

def assert_officer_ledgers(
    officer: Dict[str, Any],
    open_case_load: Optional[int] = None,
    imposed_suspension_days_total: Optional[int] = None,
    open_alert_count: Optional[int] = None,
    intervention_escalation_count: Optional[int] = None,
    credibility_disclosure_active: Optional[bool] = None,
) -> None:
    """Assert whichever of the officer's running totals a test cares about."""
    if open_case_load is not None:
        assert officer["open_case_load"] == open_case_load, (
            f"open_case_load: expected {open_case_load}, got {officer['open_case_load']}"
        )
    if imposed_suspension_days_total is not None:
        assert officer["imposed_suspension_days_total"] == imposed_suspension_days_total, (
            f"imposed_suspension_days_total: expected {imposed_suspension_days_total}, "
            f"got {officer['imposed_suspension_days_total']}"
        )
    if open_alert_count is not None:
        assert officer["open_alert_count"] == open_alert_count, (
            f"open_alert_count: expected {open_alert_count}, got {officer['open_alert_count']}"
        )
    if intervention_escalation_count is not None:
        assert officer["intervention_escalation_count"] == intervention_escalation_count, (
            f"intervention_escalation_count: expected {intervention_escalation_count}, "
            f"got {officer['intervention_escalation_count']}"
        )
    if credibility_disclosure_active is not None:
        assert officer["credibility_disclosure_active"] is credibility_disclosure_active, (
            f"credibility_disclosure_active: expected {credibility_disclosure_active}, "
            f"got {officer['credibility_disclosure_active']}"
        )


def assert_officer_risk(
    officer: Dict[str, Any],
    eis_score: Optional[float] = None,
    eis_alert_level: Optional[str] = None,
) -> None:
    """Assert the officer's stored risk dimension."""
    if eis_score is not None:
        assert_two_dp(officer["eis_score"], eis_score, "officer.eis_score")
    if eis_alert_level is not None:
        assert officer["eis_alert_level"] == eis_alert_level, (
            f"eis_alert_level: expected {eis_alert_level}, got {officer['eis_alert_level']}"
        )


# ── Composite entity assertions ────────────────────────────────────────────

def assert_investigation_window(
    investigation: Dict[str, Any],
    statutory_days: int,
    required_certification_level: int,
    due_at: str,
) -> None:
    """Assert the statutory window the classification selected for an investigation."""
    assert investigation["statutory_days"] == statutory_days, (
        f"statutory_days: expected {statutory_days}, got {investigation['statutory_days']}"
    )
    assert investigation["required_certification_level"] == required_certification_level, (
        f"required_certification_level: expected {required_certification_level}, "
        f"got {investigation['required_certification_level']}"
    )
    assert_instant(investigation["due_at"], due_at, "investigation.due_at")


def assert_eis_profile(
    profile: Dict[str, Any],
    event_count: Optional[int] = None,
    weighted_total: Optional[float] = None,
    composite_score: Optional[float] = None,
    alert_level: Optional[str] = None,
    breached_indicators: Optional[list] = None,
    peer_pool_size: Optional[int] = None,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
) -> None:
    """Assert whichever figures of the computed early-intervention profile matter."""
    if event_count is not None:
        assert profile["event_count"] == event_count, (
            f"event_count: expected {event_count}, got {profile['event_count']}"
        )
    if weighted_total is not None:
        assert_two_dp(profile["weighted_total"], weighted_total, "weighted_total")
    if composite_score is not None:
        assert_two_dp(profile["composite_score"], composite_score, "composite_score")
    if alert_level is not None:
        assert profile["alert_level"] == alert_level, (
            f"alert_level: expected {alert_level}, got {profile['alert_level']}"
        )
    if breached_indicators is not None:
        assert profile["breached_indicators"] == breached_indicators, (
            f"breached_indicators: expected {breached_indicators}, "
            f"got {profile['breached_indicators']}"
        )
    if peer_pool_size is not None:
        assert profile["peer_pool_size"] == peer_pool_size, (
            f"peer_pool_size: expected {peer_pool_size}, got {profile['peer_pool_size']}"
        )
    if window_start is not None:
        assert_instant(profile["window_start"], window_start, "window_start")
    if window_end is not None:
        assert_instant(profile["window_end"], window_end, "window_end")


def assert_eis_run_counters(
    run: Dict[str, Any],
    run_sequence: Optional[int] = None,
    evaluated_officer_count: Optional[int] = None,
    alerts_created: Optional[int] = None,
    alerts_promoted: Optional[int] = None,
    checkins_missed: Optional[int] = None,
    disclosures_expired: Optional[int] = None,
) -> None:
    """Assert the counters a sweep reports for the work it did."""
    for field, expected in (
        ("run_sequence", run_sequence),
        ("evaluated_officer_count", evaluated_officer_count),
        ("alerts_created", alerts_created),
        ("alerts_promoted", alerts_promoted),
        ("checkins_missed", checkins_missed),
        ("disclosures_expired", disclosures_expired),
    ):
        if expected is not None:
            assert run[field] == expected, f"{field}: expected {expected}, got {run[field]}"


def assert_discipline_days(
    discipline: Dict[str, Any],
    presumptive_prior_tier: Optional[int] = None,
    presumptive_days: Optional[int] = None,
    final_prior_tier: Optional[int] = None,
    final_days: Optional[int] = None,
    effective_days: Optional[int] = None,
) -> None:
    """Assert the two variants of the discipline matrix and the operative figure."""
    for field, expected in (
        ("presumptive_prior_tier", presumptive_prior_tier),
        ("presumptive_days", presumptive_days),
        ("final_prior_tier", final_prior_tier),
        ("final_days", final_days),
        ("effective_days", effective_days),
    ):
        if expected is not None:
            assert discipline[field] == expected, (
                f"{field}: expected {expected}, got {discipline[field]}"
            )


def assert_report_group(
    group: Dict[str, Any],
    group_key: str,
    total_complaints: Optional[int],
    sustained_complaints: Optional[int],
    sustain_rate_pct: Optional[float],
    suppressed: bool,
) -> None:
    """Assert one row of the outcome report, including a fully suppressed row."""
    assert group["group_key"] == group_key, (
        f"group_key: expected {group_key}, got {group['group_key']}"
    )
    assert group["suppressed"] is suppressed, (
        f"{group_key}.suppressed: expected {suppressed}, got {group['suppressed']}"
    )
    if total_complaints is None:
        assert group["total_complaints"] is None, f"{group_key}.total_complaints must be null"
        assert group["sustained_complaints"] is None, f"{group_key}.sustained_complaints must be null"
        assert group["sustain_rate_pct"] is None, f"{group_key}.sustain_rate_pct must be null"
        return
    assert group["total_complaints"] == total_complaints, (
        f"{group_key}.total_complaints: expected {total_complaints}, got {group['total_complaints']}"
    )
    assert group["sustained_complaints"] == sustained_complaints, (
        f"{group_key}.sustained_complaints: expected {sustained_complaints}, "
        f"got {group['sustained_complaints']}"
    )
    assert_one_dp(group["sustain_rate_pct"], sustain_rate_pct, f"{group_key}.sustain_rate_pct")
