"""Entity assertions, response checks and domain invariant checkers.

Three layers live here:

1. **Field and response helpers** — nested-path reads, field equality, exact
   ``error_id`` checks, HTTP status checks and paginated-envelope checks.
2. **Entity assertions** — ``assert_{entity}(data)`` for each of the ten
   resources, validating the system-managed properties (PRD §2.6), the
   declared enum memberships and the field types.
3. **Invariant checkers** — ``assert_{entity}_invariants(data)`` for the
   relations the PRD states must hold on any read of that resource, plus the
   two conservation invariants of PRD §3.4.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    assert_version_incremented,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .constants import (
    PAGINATION_FIELDS,
    SCORE_CEILING,
    SCORE_FLOOR,
    TIER_ORDER,
)
from .types import (
    AllocationStatus,
    CapitalCallMilestone,
    CapitalCallStatus,
    DeveloperStatus,
    DeveloperType,
    ExitEventStatus,
    FundPosture,
    FundStatus,
    GuaranteeStatus,
    GuaranteeType,
    InvestorStatus,
    InvestorType,
    ProjectStatus,
    ReviewStatus,
    RiskTier,
    SubscriptionStatus,
    UnderwritingStage,
)

__all__ = [
    # field / response helpers
    "get_field",
    "assert_field",
    "assert_field_present",
    "assert_field_null",
    "assert_status_code",
    "assert_error_id",
    "assert_error_is_one_of",
    "assert_paginated_shape",
    "assert_common_fields",
    "assert_money_field",
    "assert_ratio_field",
    "assert_iso_field",
    "assert_same_instant",
    # version / OCC
    "assert_version_advanced",
    "assert_version_unchanged",
    "assert_stale_version_rejected",
    # entity assertions
    "assert_developer",
    "assert_investor",
    "assert_fund",
    "assert_subscription",
    "assert_project",
    "assert_allocation",
    "assert_capital_call",
    "assert_guarantee",
    "assert_portfolio_review",
    "assert_exit_event",
    # invariant checkers
    "assert_developer_invariants",
    "assert_investor_invariants",
    "assert_fund_invariants",
    "assert_subscription_invariants",
    "assert_project_invariants",
    "assert_allocation_invariants",
    "assert_capital_call_invariants",
    "assert_guarantee_invariants",
    "assert_portfolio_review_invariants",
    "assert_exit_event_invariants",
    # conservation invariants
    "assert_credit_dollars_conserved",
    "assert_subscribed_equity_conserved",
]

_MISSING = object()

_STATUS_VALUES = {
    "Developer": [m.value for m in DeveloperStatus],
    "Investor": [m.value for m in InvestorStatus],
    "SyndicationFund": [m.value for m in FundStatus],
    "FundSubscription": [m.value for m in SubscriptionStatus],
    "Project": [m.value for m in ProjectStatus],
    "Allocation": [m.value for m in AllocationStatus],
    "CapitalCall": [m.value for m in CapitalCallStatus],
    "Guarantee": [m.value for m in GuaranteeStatus],
    "PortfolioReview": [m.value for m in ReviewStatus],
    "ExitEvent": [m.value for m in ExitEventStatus],
}


# =============================================================================
# Field access
# =============================================================================

def get_field(data: Dict[str, Any], path: str, default: Any = _MISSING) -> Any:
    """Read a dotted path out of a nested response payload.

    ``get_field(body, "data.allocations.0.status")`` walks dicts and lists.
    Raises ``KeyError`` (or ``IndexError``) when the path is absent, unless a
    ``default`` is supplied.
    """
    current: Any = data
    for segment in str(path).split("."):
        try:
            if isinstance(current, dict):
                current = current[segment]
            elif isinstance(current, (list, tuple)):
                current = current[int(segment)]
            else:
                raise KeyError(segment)
        except (KeyError, IndexError, TypeError, ValueError):
            if default is not _MISSING:
                return default
            raise KeyError(f"Path {path!r} not found (failed at {segment!r})")
    return current


def assert_field(data: Dict[str, Any], path: str, expected: Any, message: str = "") -> Any:
    """Assert a nested field equals ``expected``; returns the actual value."""
    actual = get_field(data, path)
    detail = f" ({message})" if message else ""
    assert actual == expected, (
        f"Expected {path} == {expected!r}, got {actual!r}{detail}"
    )
    return actual


def assert_field_present(data: Dict[str, Any], path: str) -> Any:
    """Assert a nested field exists and is not ``None``."""
    value = get_field(data, path)
    assert value is not None, f"Expected {path} to be present and non-null"
    return value


def assert_field_null(data: Dict[str, Any], path: str) -> None:
    """Assert a nested field exists and is ``None``."""
    value = get_field(data, path)
    assert value is None, f"Expected {path} to be null, got {value!r}"


# =============================================================================
# Response-level checks
# =============================================================================

def assert_status_code(response, expected_status: int) -> None:
    """Assert the raw HTTP status code, with the body in the failure message."""
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )


def assert_error_id(response, expected_error_id, expected_status: Optional[int] = None) -> dict:
    """Assert the response is an error envelope carrying exactly ``error_id``.

    The HTTP status is cross-checked against the registered error catalog when
    ``expected_status`` is omitted.
    """
    return validate_error(response, expected_error_id, expected_status)


def assert_error_is_one_of(response, acceptable_error_ids: List) -> str:
    """Assert the response carries one of several acceptable error ids.

    Use where the PRD does not pin a single precedence outcome. Returns the
    actual error id.
    """
    return validate_error_is_one_of(response, list(acceptable_error_ids))


def assert_paginated_shape(
    response,
    expected_total_count: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    exact_rows: Optional[int] = None,
    min_rows: Optional[int] = None,
    max_rows: Optional[int] = None,
):
    """Validate a list envelope and its four ``meta`` pagination fields.

    Returns ``(data_list, meta_dict)``. ``total_count`` is the size of the whole
    filtered set, not of the returned page.
    """
    data, meta = validate_paginated(response)
    for field in PAGINATION_FIELDS:
        assert field in meta, f"meta is missing pagination field {field!r}"

    if expected_total_count is not None:
        assert meta["total_count"] == expected_total_count, (
            f"Expected total_count {expected_total_count}, got {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"Expected has_more {expected_has_more}, got {meta['has_more']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"Expected limit {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"Expected offset {expected_offset}, got {meta['offset']}"
        )
    if exact_rows is not None:
        assert len(data) == exact_rows, (
            f"Expected {exact_rows} rows on the page, got {len(data)}"
        )
    if min_rows is not None:
        assert len(data) >= min_rows, f"Expected at least {min_rows} rows, got {len(data)}"
    if max_rows is not None:
        assert len(data) <= max_rows, f"Expected at most {max_rows} rows, got {len(data)}"
    return data, meta


def assert_common_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """Validate the four system-managed properties every resource carries.

    PRD §2.6: ``id`` (UUID), ``created_at`` / ``updated_at`` (ISO 8601 UTC with
    milliseconds) and ``version`` (integer, incremented on every modification).
    """
    assert isinstance(data, dict), f"{label} must be a JSON object, got {type(data)}"
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    )
    for field in ("created_at", "updated_at"):
        assert is_iso8601_timestamp(data.get(field, "")), (
            f"{label}.{field} must be an ISO 8601 UTC timestamp, got {data.get(field)!r}"
        )
    version = data.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{label}.version must be at least 1, got {version}"


def assert_money_field(data: Dict[str, Any], field: str, label: str = "resource") -> int:
    """Assert a ``_cents`` field is a whole number of cents (never a float)."""
    value = get_field(data, field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label}.{field} must be integer cents, got {value!r}"
    )
    assert value >= 0, f"{label}.{field} must be non-negative, got {value}"
    return value


def assert_ratio_field(
    data: Dict[str, Any], field: str, places: int = 6, label: str = "resource"
) -> float:
    """Assert a decimal ratio field carries at most ``places`` decimal places."""
    value = get_field(data, field)
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label}.{field} must be numeric, got {value!r}"
    )
    assert_cost_precision(float(value), places)
    return float(value)


def assert_iso_field(data: Dict[str, Any], field: str, label: str = "resource") -> str:
    """Assert a timestamp field is ISO 8601 UTC."""
    value = get_field(data, field)
    assert is_iso8601_timestamp(value), (
        f"{label}.{field} must be an ISO 8601 UTC timestamp, got {value!r}"
    )
    return value


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> str:
    """Assert two ISO 8601 instants denote the same point in time.

    The PRD pins the *instant* a temporal field must carry (a deadline, a
    computed expiry, a supplied date) and pins a fractional-digit count only
    for the three system-managed fields ``created_at``, ``updated_at`` and
    ``api_request_timestamp`` (PRD §2.2, §2.6).  It never states whether a
    caller-supplied or clock-derived date is echoed byte-for-byte or
    canonicalised, so a test must compare the instant rather than the spelling.
    """
    parsed_actual = _parse_iso(actual)
    parsed_expected = _parse_iso(expected)
    assert parsed_actual is not None, f"{label} is not an ISO 8601 UTC timestamp: {actual!r}"
    assert parsed_expected is not None, f"bad expected {label}: {expected!r}"
    assert parsed_actual == parsed_expected, (
        f"{label} is {actual!r} ({parsed_actual.isoformat()}), "
        f"expected the instant {expected!r} ({parsed_expected.isoformat()})"
    )
    return actual


# =============================================================================
# Version / optimistic concurrency
# =============================================================================

def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any]) -> int:
    """Assert ``after.version`` is strictly greater than ``before.version``.

    PRD §2.6: every modification — including a derived-field recomputation —
    increments the version of the row whose field changed.
    """
    assert_version_incremented(after["version"], before["version"])
    return after["version"]


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Assert a rejected write left the resource's version untouched."""
    assert after["version"] == before["version"], (
        f"Version changed on a rejected operation: {before['version']} -> {after['version']}"
    )


def assert_stale_version_rejected(response, expected_error_id="ERR_STALE_VERSION") -> dict:
    """Assert an OCC mismatch was rejected with the stale-version error."""
    return assert_error_id(response, expected_error_id, expected_status=412)


# =============================================================================
# Internal field validators
# =============================================================================

def _int(data, name, label, nullable=False, minimum=None):
    value = data.get(name, _MISSING)
    assert value is not _MISSING, f"{label}.{name} is missing from the response"
    if value is None:
        assert nullable, f"{label}.{name} must not be null"
        return None
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label}.{name} must be an integer, got {value!r}"
    )
    if minimum is not None:
        assert value >= minimum, f"{label}.{name} must be >= {minimum}, got {value}"
    return value


def _num(data, name, label, nullable=False, minimum=None):
    value = data.get(name, _MISSING)
    assert value is not _MISSING, f"{label}.{name} is missing from the response"
    if value is None:
        assert nullable, f"{label}.{name} must not be null"
        return None
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label}.{name} must be numeric, got {value!r}"
    )
    if minimum is not None:
        assert float(value) >= minimum, f"{label}.{name} must be >= {minimum}, got {value}"
    return value


def _str(data, name, label, nullable=False, non_empty=True):
    value = data.get(name, _MISSING)
    assert value is not _MISSING, f"{label}.{name} is missing from the response"
    if value is None:
        assert nullable, f"{label}.{name} must not be null"
        return None
    assert isinstance(value, str), f"{label}.{name} must be a string, got {value!r}"
    if non_empty:
        assert value != "", f"{label}.{name} must not be empty"
    return value


def _enum(data, name, label, allowed, nullable=False):
    value = data.get(name, _MISSING)
    assert value is not _MISSING, f"{label}.{name} is missing from the response"
    if value is None:
        assert nullable, f"{label}.{name} must not be null"
        return None
    assert value in allowed, (
        f"{label}.{name} must be one of {allowed}, got {value!r}"
    )
    return value


# =============================================================================
# Entity assertions
# =============================================================================

def assert_developer(data: Dict[str, Any]) -> None:
    """Validate a Developer resource (PRD §3.1)."""
    label = "Developer"
    assert_common_fields(data, label)
    _str(data, "name", label)
    _enum(data, "developer_type", label, [m.value for m in DeveloperType])
    _int(data, "sponsor_experience_months", label, minimum=0)
    _int(data, "projects_completed", label, minimum=0)
    _int(data, "net_worth_cents", label, minimum=0)
    _int(data, "liquid_assets_cents", label, minimum=0)
    _int(data, "guarantee_exposure_cents", label, minimum=0)
    _int(data, "active_project_count", label, minimum=0)
    _enum(data, "status", label, _STATUS_VALUES[label])
    assert_developer_invariants(data)


def assert_investor(data: Dict[str, Any]) -> None:
    """Validate an Investor resource (PRD §3.2)."""
    label = "Investor"
    assert_common_fields(data, label)
    _str(data, "name", label)
    _enum(data, "investor_type", label, [m.value for m in InvestorType])
    _int(data, "committed_capacity_cents", label, minimum=0)
    _enum(data, "risk_tier", label, [m.value for m in RiskTier])
    _int(data, "outstanding_commitment_cents", label, minimum=0)
    _int(data, "funded_cents", label, minimum=0)
    _enum(data, "status", label, _STATUS_VALUES[label])
    assert_investor_invariants(data)


def assert_fund(data: Dict[str, Any]) -> None:
    """Validate a SyndicationFund resource (PRD §3.3)."""
    label = "SyndicationFund"
    assert_common_fields(data, label)
    _str(data, "fund_name", label)
    _int(data, "target_equity_cents", label, minimum=0)
    _num(data, "price_per_credit_dollar", label, minimum=0)
    _num(data, "target_yield_pct", label)
    _num(data, "close_threshold_pct", label, minimum=0)
    assert_iso_field(data, "subscription_open_date", label)
    assert_iso_field(data, "subscription_close_date", label)
    _enum(data, "status", label, _STATUS_VALUES[label])
    _enum(data, "posture", label, [m.value for m in FundPosture])
    _int(data, "funded_equity_cents", label, minimum=0)
    _int(data, "subscribed_equity_cents", label, minimum=0)
    _int(data, "awarded_credits_total_cents", label, minimum=0)
    _int(data, "delivered_credits_total_cents", label, minimum=0)
    _int(data, "priced_value_cents", label, minimum=0)
    _int(data, "realized_value_cents", label, minimum=0)
    _num(data, "priced_yield_pct", label)
    _num(data, "realized_yield_pct", label)
    _int(data, "subscription_count", label, minimum=0)
    assert_fund_invariants(data)


def assert_subscription(data: Dict[str, Any]) -> None:
    """Validate a FundSubscription resource (PRD §3.2)."""
    label = "FundSubscription"
    assert_common_fields(data, label)
    _str(data, "fund_id", label)
    _str(data, "investor_id", label)
    _int(data, "committed_cents", label, minimum=0)
    schedule = data.get("payin_schedule")
    assert isinstance(schedule, list) and schedule, (
        f"{label}.payin_schedule must be a non-empty array"
    )
    for entry in schedule:
        assert isinstance(entry, dict), f"{label}.payin_schedule entries must be objects"
        assert "milestone" in entry and "share_pct" in entry, (
            f"{label}.payin_schedule entries must carry milestone and share_pct"
        )
        assert entry["milestone"] in [m.value for m in CapitalCallMilestone], (
            f"{label}.payin_schedule milestone {entry['milestone']!r} is not declared"
        )
    _num(data, "executed_price_per_credit_dollar", label, minimum=0)
    _enum(data, "status", label, _STATUS_VALUES[label])
    _int(data, "paid_in_cents", label, minimum=0)
    _int(data, "unfunded_commitment_cents", label, minimum=0)
    _int(data, "shortfall_cents", label, minimum=0)
    assert_subscription_invariants(data)


def assert_project(data: Dict[str, Any]) -> None:
    """Validate a Project resource (PRD §3.4)."""
    label = "Project"
    assert_common_fields(data, label)
    _str(data, "developer_id", label)
    _str(data, "fund_id", label)
    _str(data, "project_name", label)
    state_code = _str(data, "state_code", label)
    assert re.fullmatch(r"[A-Z]{2}", state_code), (
        f"{label}.state_code must be exactly two uppercase letters, got {state_code!r}"
    )
    _int(data, "total_credit_dollars_cents", label, minimum=0)
    _int(data, "construction_budget_cents", label, minimum=0)
    _int(data, "construction_loan_cents", label, minimum=0)
    _int(data, "operating_pro_forma_noi_cents", label, minimum=0)
    _int(data, "debt_service_cents", label, minimum=0)
    _num(data, "market_study_absorption_score", label, minimum=0)
    assert data["market_study_absorption_score"] <= 1, (
        f"{label}.market_study_absorption_score must be at most 1"
    )
    _int(data, "sponsor_experience_months", label, minimum=0)
    assert_iso_field(data, "placed_in_service_deadline", label)
    _str(data, "placed_in_service_at", label, nullable=True)
    _int(data, "compliance_period_months", label, minimum=1)
    _enum(data, "status", label, _STATUS_VALUES[label])
    _enum(data, "underwriting_stage", label, [m.value for m in UnderwritingStage])
    _int(data, "preliminary_equity_cents", label)
    _int(data, "final_equity_cents", label, nullable=True)
    _int(data, "underwritten_equity_cents", label)
    _num(data, "dscr", label, minimum=0)
    _int(data, "operating_deficit_cents", label, minimum=0)
    _int(data, "committed_credit_dollars_cents", label, minimum=0)
    _int(data, "delivered_credit_dollars_cents", label, minimum=0)
    _int(data, "compliance_failure_count", label, minimum=0)
    _int(data, "underwritten_gap_cents", label, minimum=0)
    assert_project_invariants(data)


def assert_allocation(data: Dict[str, Any]) -> None:
    """Validate an Allocation resource (PRD §3.4)."""
    label = "Allocation"
    assert_common_fields(data, label)
    _str(data, "project_id", label)
    _str(data, "state_agency", label)
    _int(data, "awarded_credit_dollars_cents", label, minimum=0)
    _num(data, "commitment_fee_pct", label, minimum=0)
    assert_iso_field(data, "awarded_date", label)
    assert_iso_field(data, "placed_in_service_deadline", label)
    _enum(data, "status", label, _STATUS_VALUES[label])
    _int(data, "delivered_credit_dollars_cents", label, minimum=0)
    _num(data, "delivery_ratio", label, minimum=0)
    assert_allocation_invariants(data)


def assert_capital_call(data: Dict[str, Any]) -> None:
    """Validate a CapitalCall resource (PRD §3.5)."""
    label = "CapitalCall"
    assert_common_fields(data, label)
    _str(data, "project_id", label)
    _enum(data, "milestone", label, [m.value for m in CapitalCallMilestone])
    assert_iso_field(data, "scheduled_date", label)
    assert_iso_field(data, "due_date", label)
    _int(data, "base_call_cents", label, minimum=0)
    _num(data, "credit_delivery_adjuster_pct", label, minimum=0)
    _int(data, "called_amount_cents", label, minimum=0)
    _int(data, "settled_amount_cents", label, minimum=0)
    _int(data, "shortfall_cents", label, minimum=0)
    _enum(data, "status", label, _STATUS_VALUES[label])
    assert_capital_call_invariants(data)


def assert_guarantee(data: Dict[str, Any]) -> None:
    """Validate a Guarantee resource (PRD §3.6)."""
    label = "Guarantee"
    assert_common_fields(data, label)
    _str(data, "project_id", label)
    _enum(data, "guarantee_type", label, [m.value for m in GuaranteeType])
    _int(data, "guaranteed_amount_cents", label, minimum=0)
    _num(data, "recapture_pct", label, minimum=0)
    assert_iso_field(data, "coverage_start_date", label)
    assert_iso_field(data, "coverage_end_date", label)
    _int(data, "drawn_amount_cents", label, minimum=0)
    _int(data, "remaining_capacity_cents", label, minimum=0)
    _enum(data, "status", label, _STATUS_VALUES[label])
    assert_guarantee_invariants(data)


def assert_portfolio_review(data: Dict[str, Any]) -> None:
    """Validate a PortfolioReview resource (PRD §3.7)."""
    label = "PortfolioReview"
    assert_common_fields(data, label)
    _str(data, "project_id", label)
    _int(data, "review_period_index", label, minimum=0)
    assert_iso_field(data, "review_period_end", label)
    _num(data, "occupancy_pct", label, minimum=0)
    _num(data, "dscr_observed", label, minimum=0)
    _int(data, "reserve_balance_cents", label, minimum=0)
    _int(data, "corrected_reserve_balance_cents", label, nullable=True, minimum=0)
    _int(data, "risk_score", label, minimum=SCORE_FLOOR)
    assert data["risk_score"] <= SCORE_CEILING, (
        f"{label}.risk_score must be at most {SCORE_CEILING}, got {data['risk_score']}"
    )
    _enum(data, "status", label, _STATUS_VALUES[label])
    _str(data, "escalated_at", label, nullable=True)
    assert_portfolio_review_invariants(data)


def assert_exit_event(data: Dict[str, Any]) -> None:
    """Validate an ExitEvent resource (PRD §3.9)."""
    label = "ExitEvent"
    assert_common_fields(data, label)
    _str(data, "project_id", label)
    _int(data, "exit_year", label, minimum=0)
    assert_iso_field(data, "rofr_notice_date", label)
    _int(data, "rofr_window_days", label, minimum=1)
    assert_iso_field(data, "exercise_deadline", label)
    _int(data, "option_price_cents", label, minimum=0)
    assert_iso_field(data, "rofr_expires_at", label)
    _int(data, "cumulative_distributions_cents", label, minimum=0)
    _enum(data, "status", label, _STATUS_VALUES[label])
    assert_exit_event_invariants(data)


# =============================================================================
# Invariant checkers
# =============================================================================

def assert_developer_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of a Developer."""
    assert data["guarantee_exposure_cents"] >= 0
    assert data["active_project_count"] >= 0
    assert data["status"] in _STATUS_VALUES["Developer"]
    assert data["net_worth_cents"] >= 0
    assert data["liquid_assets_cents"] >= 0


def assert_investor_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of an Investor."""
    assert data["outstanding_commitment_cents"] >= 0
    assert data["funded_cents"] >= 0
    assert data["outstanding_commitment_cents"] <= data["committed_capacity_cents"], (
        "outstanding_commitment_cents must not exceed committed_capacity_cents"
    )
    assert data["status"] in _STATUS_VALUES["Investor"]


def assert_fund_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of a SyndicationFund."""
    assert data["subscribed_equity_cents"] >= 0
    assert data["funded_equity_cents"] >= 0
    assert data["subscription_count"] >= 0
    assert data["priced_value_cents"] >= 0
    assert data["realized_value_cents"] >= 0
    assert data["awarded_credits_total_cents"] >= 0
    assert data["delivered_credits_total_cents"] >= 0
    assert data["status"] in _STATUS_VALUES["SyndicationFund"]
    assert data["posture"] in [m.value for m in FundPosture]
    if data["subscribed_equity_cents"] == 0:
        assert data["priced_yield_pct"] == 0 or data["priced_yield_pct"] == 0.0, (
            "priced_yield_pct must be zero when subscribed_equity_cents is zero"
        )
    if data["funded_equity_cents"] == 0:
        assert data["realized_yield_pct"] == 0 or data["realized_yield_pct"] == 0.0, (
            "realized_yield_pct must be zero when funded_equity_cents is zero"
        )


def assert_subscription_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of a FundSubscription."""
    expected_unfunded = max(0, data["committed_cents"] - data["paid_in_cents"])
    assert data["unfunded_commitment_cents"] == expected_unfunded, (
        "unfunded_commitment_cents must equal committed_cents - paid_in_cents, "
        f"floored at zero (expected {expected_unfunded}, got "
        f"{data['unfunded_commitment_cents']})"
    )
    assert data["paid_in_cents"] >= 0
    assert data["shortfall_cents"] >= 0
    assert data["status"] in _STATUS_VALUES["FundSubscription"]


def assert_project_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of a Project."""
    expected_deficit = max(
        0, data["debt_service_cents"] - data["operating_pro_forma_noi_cents"]
    )
    assert data["operating_deficit_cents"] == expected_deficit, (
        "operating_deficit_cents must equal max(0, debt_service_cents - "
        f"operating_pro_forma_noi_cents) (expected {expected_deficit}, got "
        f"{data['operating_deficit_cents']})"
    )
    assert data["underwritten_gap_cents"] >= 0
    assert data["compliance_failure_count"] >= 0
    stage = data["underwriting_stage"]
    if stage == UnderwritingStage.FINAL.value:
        assert data["final_equity_cents"] is not None, (
            "final_equity_cents must be computed once underwriting_stage is FINAL"
        )
        assert data["underwritten_equity_cents"] == data["final_equity_cents"], (
            "underwritten_equity_cents must equal final_equity_cents at FINAL"
        )
    else:
        assert data["final_equity_cents"] is None, (
            "final_equity_cents must be null while underwriting_stage is PRELIMINARY"
        )
        assert data["underwritten_equity_cents"] == data["preliminary_equity_cents"], (
            "underwritten_equity_cents must equal preliminary_equity_cents while "
            "underwriting_stage is PRELIMINARY"
        )
    assert data["status"] in _STATUS_VALUES["Project"]


def assert_allocation_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of an Allocation."""
    assert data["delivered_credit_dollars_cents"] >= 0
    assert data["awarded_credit_dollars_cents"] >= 0
    if data["awarded_credit_dollars_cents"] > 0:
        expected_ratio = round(
            data["delivered_credit_dollars_cents"] / data["awarded_credit_dollars_cents"], 6
        )
        assert data["delivery_ratio"] == expected_ratio, (
            "delivery_ratio must equal delivered_credit_dollars_cents / "
            f"awarded_credit_dollars_cents (expected {expected_ratio}, got "
            f"{data['delivery_ratio']})"
        )
    assert data["status"] in _STATUS_VALUES["Allocation"]


def assert_capital_call_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of a CapitalCall."""
    expected_shortfall = max(
        0, data["called_amount_cents"] - data["settled_amount_cents"]
    )
    assert data["shortfall_cents"] == expected_shortfall, (
        "shortfall_cents must equal max(0, called_amount_cents - "
        f"settled_amount_cents) (expected {expected_shortfall}, got "
        f"{data['shortfall_cents']})"
    )
    assert data["credit_delivery_adjuster_pct"] in (0.0, 0.05, 0.12, 0.20), (
        "credit_delivery_adjuster_pct must be one of the four band values, got "
        f"{data['credit_delivery_adjuster_pct']}"
    )
    assert data["status"] in _STATUS_VALUES["CapitalCall"]


def assert_guarantee_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of a Guarantee."""
    expected_capacity = max(
        0, data["guaranteed_amount_cents"] - data["drawn_amount_cents"]
    )
    assert data["remaining_capacity_cents"] == expected_capacity, (
        "remaining_capacity_cents must equal guaranteed_amount_cents - "
        f"drawn_amount_cents, floored at zero (expected {expected_capacity}, got "
        f"{data['remaining_capacity_cents']})"
    )
    assert data["drawn_amount_cents"] <= data["guaranteed_amount_cents"], (
        "drawn_amount_cents must never exceed guaranteed_amount_cents"
    )
    assert data["status"] in _STATUS_VALUES["Guarantee"]


def assert_portfolio_review_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of a PortfolioReview."""
    assert SCORE_FLOOR <= data["risk_score"] <= SCORE_CEILING, (
        f"risk_score must be clamped to [{SCORE_FLOOR}, {SCORE_CEILING}]"
    )
    if data["status"] == ReviewStatus.CURED.value:
        assert data["corrected_reserve_balance_cents"] is not None, (
            "corrected_reserve_balance_cents must be recorded with a CURED resolve"
        )
    if data["status"] in (
        ReviewStatus.ESCALATED.value,
        ReviewStatus.NONCOMPLIANT.value,
        ReviewStatus.CURED.value,
    ):
        assert data["escalated_at"] is not None, (
            "escalated_at must be stamped once a review has been escalated"
        )


def assert_exit_event_invariants(data: Dict[str, Any]) -> None:
    """Relations that hold on any read of an ExitEvent."""
    assert data["option_price_cents"] >= 0
    assert data["cumulative_distributions_cents"] >= 0
    assert data["rofr_window_days"] >= 1
    notice = _parse_iso(data["rofr_notice_date"])
    expires = _parse_iso(data["rofr_expires_at"])
    if notice is not None and expires is not None:
        expected = notice + timedelta(days=data["rofr_window_days"])
        assert expires == expected, (
            "rofr_expires_at must equal rofr_notice_date + rofr_window_days "
            f"(expected {expected.isoformat()}, got {expires.isoformat()})"
        )


# =============================================================================
# Conservation invariants (PRD §3.4)
# =============================================================================

def assert_credit_dollars_conserved(before_cents: int, after_cents: int) -> None:
    """Assert a commit/rescind pair returned committed credit dollars to par.

    PRD §3.4: after the pair the project's ``committed_credit_dollars_cents``
    equals its value immediately before the forward action, to the cent.
    """
    assert after_cents == before_cents, (
        "Credit dollars were not conserved across the pair: "
        f"before {before_cents}, after {after_cents}"
    )


def assert_subscribed_equity_conserved(
    fund: Dict[str, Any], subscriptions: List[Dict[str, Any]]
) -> None:
    """Assert the equity invariant after a subscription/default pair.

    PRD §3.4: ``subscribed_equity_cents`` plus the sum of ``committed_cents``
    across the fund's DEFAULTED subscriptions equals the sum of
    ``committed_cents`` across all of the fund's subscriptions, exactly.
    """
    all_committed = sum(s["committed_cents"] for s in subscriptions)
    defaulted_committed = sum(
        s["committed_cents"]
        for s in subscriptions
        if s["status"] == SubscriptionStatus.DEFAULTED.value
    )
    total = fund["subscribed_equity_cents"] + defaulted_committed
    assert total == all_committed, (
        "Equity invariant violated: subscribed_equity_cents "
        f"({fund['subscribed_equity_cents']}) + defaulted commitments "
        f"({defaulted_committed}) must equal total commitments ({all_committed})"
    )


# =============================================================================
# Internal helpers
# =============================================================================

def _parse_iso(value: str) -> Optional[datetime]:
    if not is_iso8601_timestamp(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            return None
