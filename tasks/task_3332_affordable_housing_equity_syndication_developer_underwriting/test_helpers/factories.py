"""Payload factories — one per resource, input fields only.

Every factory returns a request body for its endpoint and accepts ``**overrides``
for the values a test needs to control. Computed fields are never emitted;
optional fields with a server-side default are emitted explicitly unless the
matching ``omit_*`` flag is set, which is how a defaults test expresses
"the client did not send this field".

Defaults mirror the canonical scenario in :mod:`test_helpers.constants`, so a
factory with no arguments builds a body that satisfies every declared
constraint.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_2026_09_02,
    COMPLIANCE_PERIOD_MONTHS_DEFAULT,
    FUND_CLOSE_THRESHOLD_DEFAULT,
    ROFR_WINDOW_DAYS_DEFAULT,
    SCENARIO,
)

__all__ = [
    "FACTORY_DEFAULTS",
    "PAYIN_SCHEDULE_FIVE",
    "PAYIN_SCHEDULE_SINGLE",
    "payin_schedule",
    "stale_version",
    "create_developer_payload",
    "create_investor_payload",
    "create_fund_payload",
    "create_subscription_payload",
    "create_payin_payload",
    "create_project_payload",
    "create_allocation_payload",
    "record_delivery_payload",
    "close_allocation_payload",
    "rescind_allocation_payload",
    "distribute_allocation_payload",
    "create_capital_call_payload",
    "capital_call_transition_payload",
    "create_guarantee_payload",
    "draw_guarantee_payload",
    "create_review_payload",
    "resolve_review_payload",
    "create_exit_event_payload",
    "exercise_exit_event_payload",
    "record_milestone_payload",
    "update_project_payload",
    "update_fund_payload",
    "set_clock_payload",
]


FACTORY_DEFAULTS: Dict[str, Any] = {
    "DEVELOPER": dict(SCENARIO["developer_cedar"]),
    "INVESTOR": dict(SCENARIO["investor_meridian"]),
    "FUND": dict(SCENARIO["fund_iv"]),
    "PROJECT": dict(SCENARIO["project_riverside"]),
    "ALLOCATION": dict(SCENARIO["allocation_oregon"]),
    "SUBSCRIPTION_COMMITTED_CENTS": 460_000_000,
    "CAPITAL_CALL_SCHEDULED_DATE": "2026-10-01T00:00:00Z",
    "CAPITAL_CALL_DUE_DATE": "2026-10-31T00:00:00Z",
    "CAPITAL_CALL_MILESTONE_SHARE": 0.20,
    "GUARANTEE_TYPE": "COMPLETION",
    "GUARANTEE_AMOUNT_CENTS": 90_000_000,
    "GUARANTEE_RECAPTURE_PCT": 0.0,
    "GUARANTEE_START": "2026-09-01T00:00:00Z",
    "GUARANTEE_END": "2031-09-01T00:00:00Z",
    "REVIEW_PERIOD_INDEX": 1,
    "REVIEW_PERIOD_END": "2026-06-30T00:00:00Z",
    "REVIEW_OCCUPANCY_PCT": 1.0,
    "REVIEW_DSCR_OBSERVED": 1.5,
    "REVIEW_RESERVE_BALANCE_CENTS": 30_000_000,
    "EXIT_YEAR": 15,
    "ROFR_NOTICE_DATE": "2031-01-01T00:00:00Z",
    "EXERCISE_DEADLINE": "2031-06-30T00:00:00Z",
}


#: The five-milestone schedule at an even 20 percent per milestone.
PAYIN_SCHEDULE_FIVE: List[Dict[str, Any]] = [
    {"milestone": "CONSTRUCTION_START", "share_pct": 0.2},
    {"milestone": "CONSTRUCTION_50PCT", "share_pct": 0.2},
    {"milestone": "LEASE_UP_50PCT", "share_pct": 0.2},
    {"milestone": "LEASE_UP_STABILIZED", "share_pct": 0.2},
    {"milestone": "PLACED_IN_SERVICE", "share_pct": 0.2},
]

#: A single-milestone schedule; the shares must sum to 1.0.
PAYIN_SCHEDULE_SINGLE: List[Dict[str, Any]] = [
    {"milestone": "CONSTRUCTION_START", "share_pct": 1.0},
]


def payin_schedule(*entries) -> List[Dict[str, Any]]:
    """Build a ``payin_schedule`` from ``(milestone, share_pct)`` pairs.

    ``payin_schedule(("CONSTRUCTION_START", 0.5), ("PLACED_IN_SERVICE", 0.5))``
    """
    return [{"milestone": milestone, "share_pct": share} for milestone, share in entries]


def stale_version(current_version: int) -> int:
    """Return a version that cannot match the current one.

    Any mismatch is rejected with ``ERR_STALE_VERSION``; this helper picks a
    value that is never a legal current version so a stale-version test does
    not have to reason about how many writes have landed.
    """
    return int(current_version) + 1


# =============================================================================
# Developer / Investor
# =============================================================================

def create_developer_payload(**overrides) -> Dict[str, Any]:
    """Body for ``POST /developers`` (PlatformAdmin)."""
    payload = dict(FACTORY_DEFAULTS["DEVELOPER"])
    payload.update(overrides)
    return payload


def create_investor_payload(**overrides) -> Dict[str, Any]:
    """Body for ``POST /investors`` (PlatformAdmin)."""
    payload = dict(FACTORY_DEFAULTS["INVESTOR"])
    payload.update(overrides)
    return payload


# =============================================================================
# Fund / subscription
# =============================================================================

def create_fund_payload(omit_close_threshold: bool = False, **overrides) -> Dict[str, Any]:
    """Body for ``POST /funds`` (Underwriter, PlatformAdmin).

    ``close_threshold_pct`` is emitted explicitly by default; pass
    ``omit_close_threshold=True`` to leave it out and exercise the server-side
    default.
    """
    payload = dict(FACTORY_DEFAULTS["FUND"])
    payload.update(overrides)
    if omit_close_threshold:
        payload.pop("close_threshold_pct", None)
    return payload


def create_subscription_payload(
    investor_id: str,
    expected_fund_version: int,
    committed_cents: int = FACTORY_DEFAULTS["SUBSCRIPTION_COMMITTED_CENTS"],
    payin_schedule_entries: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Body for ``POST /funds/{fund_id}/subscriptions``.

    ``expected_fund_version`` is mandatory — the endpoint is one of the three
    writes that enforce the revision band.
    """
    payload: Dict[str, Any] = {
        "investor_id": investor_id,
        "committed_cents": committed_cents,
        "payin_schedule": (
            payin_schedule_entries
            if payin_schedule_entries is not None
            else [dict(entry) for entry in PAYIN_SCHEDULE_FIVE]
        ),
        "expected_fund_version": expected_fund_version,
    }
    payload.update(overrides)
    return payload


def create_payin_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    """Body for ``POST /subscriptions/{subscription_id}/payins``."""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# =============================================================================
# Project / allocation
# =============================================================================

def create_project_payload(
    developer_id: str,
    fund_id: str,
    omit_compliance_period_months: bool = False,
    **overrides,
) -> Dict[str, Any]:
    """Body for ``POST /projects`` (Underwriter).

    ``compliance_period_months`` is emitted explicitly by default; pass
    ``omit_compliance_period_months=True`` to exercise the 180-month default.
    """
    payload = dict(FACTORY_DEFAULTS["PROJECT"])
    payload.update({"developer_id": developer_id, "fund_id": fund_id})
    payload.update(overrides)
    if omit_compliance_period_months:
        payload.pop("compliance_period_months", None)
    return payload


def create_allocation_payload(**overrides) -> Dict[str, Any]:
    """Body for ``POST /projects/{project_id}/allocations`` with action=CREATE."""
    payload = {"action": "CREATE"}
    payload.update(FACTORY_DEFAULTS["ALLOCATION"])
    payload.update(overrides)
    return payload


def record_delivery_payload(
    allocation_id: str, delivered_credit_dollars_cents: int, **overrides
) -> Dict[str, Any]:
    """Body for the RECORD_DELIVERY action on the allocations endpoint."""
    payload = {
        "action": "RECORD_DELIVERY",
        "allocation_id": allocation_id,
        "delivered_credit_dollars_cents": delivered_credit_dollars_cents,
    }
    payload.update(overrides)
    return payload


def close_allocation_payload(allocation_id: str, **overrides) -> Dict[str, Any]:
    """Body for the CLOSE action on the allocations endpoint."""
    payload = {"action": "CLOSE", "allocation_id": allocation_id}
    payload.update(overrides)
    return payload


def rescind_allocation_payload(allocation_id: str, **overrides) -> Dict[str, Any]:
    """Body for the RESCIND action on the allocations endpoint."""
    payload = {"action": "RESCIND", "allocation_id": allocation_id}
    payload.update(overrides)
    return payload


def distribute_allocation_payload(allocation_id: str, **overrides) -> Dict[str, Any]:
    """Body for the DISTRIBUTE action on the allocations endpoint."""
    payload = {"action": "DISTRIBUTE", "allocation_id": allocation_id}
    payload.update(overrides)
    return payload


# =============================================================================
# Capital calls
# =============================================================================

def create_capital_call_payload(
    milestone: str,
    expected_project_version: int,
    scheduled_date: Optional[str] = None,
    due_date: Optional[str] = None,
    milestone_share: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    """Body for ``POST /projects/{project_id}/capital-calls``.

    ``expected_project_version`` is mandatory — the endpoint enforces the
    revision band.
    """
    payload: Dict[str, Any] = {
        "milestone": milestone,
        "scheduled_date": scheduled_date or FACTORY_DEFAULTS["CAPITAL_CALL_SCHEDULED_DATE"],
        "due_date": due_date or FACTORY_DEFAULTS["CAPITAL_CALL_DUE_DATE"],
        "milestone_share": (
            milestone_share
            if milestone_share is not None
            else FACTORY_DEFAULTS["CAPITAL_CALL_MILESTONE_SHARE"]
        ),
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def capital_call_transition_payload(
    action: str, funded_amount_cents: Optional[int] = None, **overrides
) -> Dict[str, Any]:
    """Body for ``POST /capital-calls/{call_id}/transitions``.

    ``funded_amount_cents`` is only meaningful for ``action=SETTLE``.
    """
    payload: Dict[str, Any] = {"action": action}
    if funded_amount_cents is not None:
        payload["funded_amount_cents"] = funded_amount_cents
    payload.update(overrides)
    return payload


def record_milestone_payload(milestone: str, **overrides) -> Dict[str, Any]:
    """Body for ``POST /projects/{project_id}/milestones``."""
    payload: Dict[str, Any] = {"milestone": milestone}
    payload.update(overrides)
    return payload


# =============================================================================
# Guarantees
# =============================================================================

def create_guarantee_payload(**overrides) -> Dict[str, Any]:
    """Body for ``POST /projects/{project_id}/guarantees``."""
    payload = {
        "guarantee_type": FACTORY_DEFAULTS["GUARANTEE_TYPE"],
        "guaranteed_amount_cents": FACTORY_DEFAULTS["GUARANTEE_AMOUNT_CENTS"],
        "recapture_pct": FACTORY_DEFAULTS["GUARANTEE_RECAPTURE_PCT"],
        "coverage_start_date": FACTORY_DEFAULTS["GUARANTEE_START"],
        "coverage_end_date": FACTORY_DEFAULTS["GUARANTEE_END"],
    }
    payload.update(overrides)
    return payload


def draw_guarantee_payload(requested_amount_cents: int, **overrides) -> Dict[str, Any]:
    """Body for ``POST /guarantees/{guarantee_id}/draw``.

    A zero amount is the reinstatement path, not a draw.
    """
    payload: Dict[str, Any] = {"requested_amount_cents": requested_amount_cents}
    payload.update(overrides)
    return payload


# =============================================================================
# Compliance reviews
# =============================================================================

def create_review_payload(**overrides) -> Dict[str, Any]:
    """Body for ``POST /projects/{project_id}/reviews``.

    The defaults score into the ESCALATED band.  PRD §3.7 weights the terms as
    35 x occupancy, 30 x min(dscr, 1.5) / 1.5 and 20 for a reserve below
    50000000 cents, each rounded half-up before summing, so occupancy 1.0 and
    DSCR 1.5 with a 30000000-cent reserve score 35 + 30 + 20 = 85 — the lowest
    score the PRD lets a ComplianceOfficer escalate (a score of 85 or above
    resolves into `ESCALATED`).
    """
    payload = {
        "review_period_index": FACTORY_DEFAULTS["REVIEW_PERIOD_INDEX"],
        "review_period_end": FACTORY_DEFAULTS["REVIEW_PERIOD_END"],
        "occupancy_pct": FACTORY_DEFAULTS["REVIEW_OCCUPANCY_PCT"],
        "dscr_observed": FACTORY_DEFAULTS["REVIEW_DSCR_OBSERVED"],
        "reserve_balance_cents": FACTORY_DEFAULTS["REVIEW_RESERVE_BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def resolve_review_payload(
    outcome: Optional[str] = None,
    corrected_reserve_balance_cents: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """Body for ``POST /reviews/{review_id}/resolve``.

    Omitting ``outcome`` is the "derive the classification from the risk score"
    path. ``corrected_reserve_balance_cents`` is only read with a CURED
    outcome.
    """
    payload: Dict[str, Any] = {}
    if outcome is not None:
        payload["outcome"] = outcome
    if corrected_reserve_balance_cents is not None:
        payload["corrected_reserve_balance_cents"] = corrected_reserve_balance_cents
    payload.update(overrides)
    return payload


# =============================================================================
# Exit events
# =============================================================================

def create_exit_event_payload(
    omit_rofr_window_days: bool = False, **overrides
) -> Dict[str, Any]:
    """Body for ``POST /projects/{project_id}/exit-events``.

    ``rofr_window_days`` is emitted explicitly by default; pass
    ``omit_rofr_window_days=True`` to exercise the 90-day default.
    """
    payload = {
        "exit_year": FACTORY_DEFAULTS["EXIT_YEAR"],
        "rofr_notice_date": FACTORY_DEFAULTS["ROFR_NOTICE_DATE"],
        "rofr_window_days": ROFR_WINDOW_DAYS_DEFAULT,
        "exercise_deadline": FACTORY_DEFAULTS["EXERCISE_DEADLINE"],
    }
    payload.update(overrides)
    if omit_rofr_window_days:
        payload.pop("rofr_window_days", None)
    return payload


def exercise_exit_event_payload(action: str, **overrides) -> Dict[str, Any]:
    """Body for ``POST /exit-events/{exit_event_id}/exercise``."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# =============================================================================
# Project / fund edits and the clock
# =============================================================================

def update_project_payload(expected_project_version: int, **overrides) -> Dict[str, Any]:
    """Body for ``PUT /projects/{project_id}``.

    ``expected_project_version`` is mandatory. Use ``underwriting_action`` to
    finalize, ``allocation_action`` + ``allocation_id`` to reserve or release,
    or any underwriting input to edit (which reverts FINAL to PRELIMINARY while
    the project is still UNDERWRITING).
    """
    payload: Dict[str, Any] = {"expected_project_version": expected_project_version}
    payload.update(overrides)
    return payload


def update_fund_payload(expected_fund_version: int, **overrides) -> Dict[str, Any]:
    """Body for ``PUT /funds/{fund_id}``.

    ``expected_fund_version`` is mandatory.
    """
    payload: Dict[str, Any] = {"expected_fund_version": expected_fund_version}
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str = CLOCK_2026_09_02, **overrides) -> Dict[str, Any]:
    """Body for ``POST /_clock/set_current_utc`` (PlatformAdmin only)."""
    payload: Dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
