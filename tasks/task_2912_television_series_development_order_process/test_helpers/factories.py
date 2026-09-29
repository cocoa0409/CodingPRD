"""Request payload builders.

Every money field is an integer count of cents and is sent as a JSON integer, never
a string. Every basis-point field is an integer. Date-only fields (holdback dates,
shoot dates, deadlines) are ``YYYY-MM-DD`` because the contract stores them as
calendar dates; the logical clock endpoint takes a full ISO-8601 instant.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CHAIN_OF_TITLE_CLEAN,
    COMMITTEE_CREATIVE,
    CONTINGENCY_CASTING,
    CONTINGENCY_SATISFIED,
    DECISION_APPROVED,
    GUILD_TIER_HIGH,
    PLATFORM_STREAMING,
    RECOMMENDATION_ADVANCE,
    REVIEW_ACCEPT,
    STEP_STORY,
    TIER_STANDARD,
)

JsonDict = Dict[str, Any]


def _merge(base: JsonDict, overrides: Optional[JsonDict]) -> JsonDict:
    payload = dict(base)
    if overrides:
        payload.update(overrides)
    return payload


# ─── Agencies ─────────────────────────────────────────
def agency_payload(overrides: Optional[JsonDict] = None) -> JsonDict:
    return _merge(
        {
            "name": "Halcyon Talent Partners",
            "agency_code": "HAL",
            "relationship_tier": TIER_STANDARD,
            "packaging_allowed": True,
            "annual_submission_cap": 5,
        },
        overrides,
    )


def rival_agency_payload(overrides: Optional[JsonDict] = None) -> JsonDict:
    return _merge(
        {
            "name": "Meridian Artists",
            "agency_code": "MRD",
            "relationship_tier": "PREMIER",
            "packaging_allowed": True,
            "annual_submission_cap": 4,
        },
        overrides,
    )


# ─── Slates ───────────────────────────────────────────
def slate_payload(overrides: Optional[JsonDict] = None) -> JsonDict:
    """The reference STREAMING/2027 slate used by the majority of the scenarios."""
    return _merge(
        {
            "platform": PLATFORM_STREAMING,
            "season_year": 2027,
            "total_dev_budget_cents": 400000000,
            "pattern_budget_per_episode_cents": 32000000,
            "license_fee_cap_per_episode_cents": 30000000,
            "max_deficit_per_episode_cents": 7000000,
            "episode_capacity": 20,
            "default_episode_count": 10,
            "max_backend_points_bps": 2000,
            "max_concurrent_pilot_shoots": 2,
        },
        overrides,
    )


def cable_slate_payload(overrides: Optional[JsonDict] = None) -> JsonDict:
    """A second, CABLE/2028 slate for cross-slate scenarios."""
    return _merge(
        {
            "platform": "CABLE",
            "season_year": 2028,
            "total_dev_budget_cents": 200000000,
            "pattern_budget_per_episode_cents": 18000000,
            "license_fee_cap_per_episode_cents": 17000000,
            "max_deficit_per_episode_cents": 4000000,
            "episode_capacity": 13,
            "default_episode_count": 13,
            "max_backend_points_bps": 1500,
            "max_concurrent_pilot_shoots": 1,
        },
        overrides,
    )


# ─── Writers ──────────────────────────────────────────
def writer_payload(agency_id: str, overrides: Optional[JsonDict] = None) -> JsonDict:
    return _merge(
        {
            "full_name": "Ada Reyes",
            "agency_id": agency_id,
            "guild_minimum_tier": GUILD_TIER_HIGH,
            "quote_per_step_cents": 5000000,
        },
        overrides,
    )


# ─── Holding deals ────────────────────────────────────
def holding_deal_payload(
    writer_id: str,
    slate_id: str,
    annual_cost_cents: int = 20000000,
    start_date: str = "2026-08-01",
    end_date: str = "2027-08-01",
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "writer_id": writer_id,
            "slate_id": slate_id,
            "annual_cost_cents": annual_cost_cents,
            "term_start_date": start_date,
            "term_end_date": end_date,
        },
        overrides,
    )


# ─── Pitches ──────────────────────────────────────────
def pitch_payload(
    agency_id: str, slate_id: str, overrides: Optional[JsonDict] = None
) -> JsonDict:
    return _merge(
        {
            "agency_id": agency_id,
            "slate_id": slate_id,
            "title": "Fault Lines",
            "logline": "A seismologist predicts the quake nobody wants to hear about.",
            "packaging_elements": [],
            "underlying_ip_key": "IP-FAULT-LINES",
        },
        overrides,
    )


def rights_check_payload(
    underlying_ip_key: str = "IP-FAULT-LINES",
    chain_of_title_status: str = CHAIN_OF_TITLE_CLEAN,
    holdback_start_date: str = "2026-01-01",
    holdback_end_date: str = "2026-03-01",
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "underlying_ip_key": underlying_ip_key,
            "chain_of_title_status": chain_of_title_status,
            "holdback_start_date": holdback_start_date,
            "holdback_end_date": holdback_end_date,
        },
        overrides,
    )


def coverage_payload(
    coverage_score: float = 82.5,
    recommendation: str = RECOMMENDATION_ADVANCE,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {"coverage_score": coverage_score, "recommendation": recommendation},
        overrides,
    )


# ─── Script deals ─────────────────────────────────────
def step_spec(step_type: str, fee_cents: int) -> JsonDict:
    return {"step_type": step_type, "fee_cents": fee_cents}


def script_deal_payload(
    project_id: str,
    writer_id: str,
    steps: Optional[List[JsonDict]] = None,
    guaranteed_step_count: int = 1,
    option_period_days: int = 60,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "project_id": project_id,
            "writer_id": writer_id,
            "guaranteed_step_count": guaranteed_step_count,
            "option_period_days": option_period_days,
            "steps": steps if steps is not None else [step_spec(STEP_STORY, 3000000)],
        },
        overrides,
    )


def review_payload(outcome: str = REVIEW_ACCEPT, overrides: Optional[JsonDict] = None) -> JsonDict:
    return _merge({"outcome": outcome}, overrides)


def cutoff_payload(
    cutoff_reason: str = "no further steps required",
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge({"cutoff_reason": cutoff_reason}, overrides)


# ─── Pilot orders ─────────────────────────────────────
def pilot_order_payload(
    project_id: str,
    budget_cents: int = 33000000,
    shoot_start_date: str = "2026-09-10",
    shoot_end_date: str = "2026-09-25",
    casting_deadline_date: str = "2026-09-05",
    location_deadline_date: str = "2026-09-08",
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "project_id": project_id,
            "budget_cents": budget_cents,
            "shoot_start_date": shoot_start_date,
            "shoot_end_date": shoot_end_date,
            "casting_deadline_date": casting_deadline_date,
            "location_deadline_date": location_deadline_date,
        },
        overrides,
    )


def contingency_payload(
    kind: str = CONTINGENCY_CASTING,
    resolution: str = CONTINGENCY_SATISFIED,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge({"kind": kind, "resolution": resolution}, overrides)


# ─── Test screenings ──────────────────────────────────
def screening_payload(
    expected_pilot_order_version: int,
    panel_size: int = 320,
    overall_score: int = 71,
    intent_to_view_score: int = 64,
    appeal_score: int = 58,
    comp_norm_index: float = 103.0,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "expected_pilot_order_version": expected_pilot_order_version,
            "panel_size": panel_size,
            "overall_score": overall_score,
            "intent_to_view_score": intent_to_view_score,
            "appeal_score": appeal_score,
            "comp_norm_index": comp_norm_index,
        },
        overrides,
    )


# ─── Negotiations ─────────────────────────────────────
def negotiation_payload(
    project_id: str,
    episode_count: int = 10,
    license_fee_per_episode_cents: int = 30000000,
    backend_points_bps: int = 1500,
    network_ownership_pct: int = 70,
    studio_ownership_pct: int = 30,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "project_id": project_id,
            "episode_count": episode_count,
            "license_fee_per_episode_cents": license_fee_per_episode_cents,
            "backend_points_bps": backend_points_bps,
            "network_ownership_pct": network_ownership_pct,
            "studio_ownership_pct": studio_ownership_pct,
        },
        overrides,
    )


def round_payload(
    episode_count: int,
    license_fee_per_episode_cents: int,
    backend_points_bps: int,
    network_ownership_pct: int,
    studio_ownership_pct: int,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "episode_count": episode_count,
            "license_fee_per_episode_cents": license_fee_per_episode_cents,
            "backend_points_bps": backend_points_bps,
            "network_ownership_pct": network_ownership_pct,
            "studio_ownership_pct": studio_ownership_pct,
        },
        overrides,
    )


# ─── Greenlight requests ──────────────────────────────
def greenlight_payload(
    project_id: str,
    negotiation_id: str,
    expected_project_version: int,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge(
        {
            "project_id": project_id,
            "negotiation_id": negotiation_id,
            "expected_project_version": expected_project_version,
        },
        overrides,
    )


def decision_payload(
    committee: str = COMMITTEE_CREATIVE,
    decision: str = DECISION_APPROVED,
    note: Optional[str] = None,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    payload: JsonDict = {"committee": committee, "decision": decision}
    if note is not None:
        payload["note"] = note
    return _merge(payload, overrides)


# ─── Projects ─────────────────────────────────────────
def abandon_payload(
    abandon_reason: str = "showrunner unavailable",
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge({"abandon_reason": abandon_reason}, overrides)


def turnaround_exercise_payload(
    successor_title: str = "Fault Lines (Studio)",
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge({"successor_title": successor_title}, overrides)


def terminate_holding_deal_payload(
    termination_reason: str = "writer signed elsewhere",
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return _merge({"termination_reason": termination_reason}, overrides)
