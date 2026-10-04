"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_candidate_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "legal_name": f"Test Candidate {n}",
        "email": f"candidate{n}@example.com",
        "home_market_code": "GA",
        "relocation_willing": True,
        "liquid_capital_cents": TEST_DEFAULTS["LIQUID_CAPITAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {"target_market_code": "GA"}
    defaults.update(overrides)
    return defaults


def create_interview_payload(**overrides) -> dict:
    defaults = {
        "interviewer_id": _uniq("fc"),
        "scheduled_for": "2026-09-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "market_plan_text": "plan",
        "financial_projection_cents": TEST_DEFAULTS["FINANCIAL_PROJECTION_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_restaurant_payload(**overrides) -> dict:
    defaults = {
        "site_code": _uniq("GA-ATL"),
        "market_code": "GA",
        "baseline_weekly_revenue_cents": TEST_DEFAULTS["BASELINE_WEEKLY_REVENUE_CENTS"],
        "equipment_value_cents": TEST_DEFAULTS["EQUIPMENT_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_experience_payload(host_restaurant_id, **overrides) -> dict:
    defaults = {
        "host_restaurant_id": host_restaurant_id,
        "starts_on": "2026-09-07T00:00:00Z",
        "ends_on": "2026-09-12T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(candidate_id, restaurant_id, **overrides) -> dict:
    defaults = {
        "candidate_id": candidate_id,
        "restaurant_id": restaurant_id,
        "base_share_bps": TEST_DEFAULTS["BASE_SHARE_BPS"],
        "effective_from": "2026-09-07T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_week_payload(**overrides) -> dict:
    defaults = {"week_start_on": "2026-09-07T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_scorecard_payload(**overrides) -> dict:
    defaults = {
        "period_start_on": "2026-09-07T00:00:00Z",
        "period_end_on": "2026-09-13T00:00:00Z",
        "food_safety_score": 90,
        "service_speed_score": 80,
        "community_engagement_score": 70,
    }
    defaults.update(overrides)
    return defaults


def create_relocation_request_payload(target_restaurant_id, **overrides) -> dict:
    defaults = {
        "kind": "RELOCATION",
        "target_restaurant_id": target_restaurant_id,
        "reason_text": "closer to home",
    }
    defaults.update(overrides)
    return defaults


def create_exit_payload(**overrides) -> dict:
    defaults = {
        "reason": "VOLUNTARY",
        "effective_on": "2026-10-07T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def cast_vote_payload(committee_member_id, vote="FOR", **overrides) -> dict:
    defaults = {"committee_member_id": committee_member_id, "vote": vote}
    defaults.update(overrides)
    return defaults
