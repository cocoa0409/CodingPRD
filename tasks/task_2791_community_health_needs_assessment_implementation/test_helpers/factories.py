"""Request-payload factories.

Every factory returns a plain ``dict`` of valid defaults and merges
``**overrides`` last, so a test can vary exactly the one field it cares about.
Monetary amounts are emitted as JSON numbers of integer cents; effort is emitted
as integer basis points.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import constants as C
from .types import (
    BoardActionType,
    Category,
    DataSourceType,
    EvalType,
    IndicatorDomain,
    PartyType,
    ScoringVariant,
    Sector,
    Subgroup,
)

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


# --------------------------------------------------------------------------
# AssessmentCycle
# --------------------------------------------------------------------------
def cycle_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "fiscal_year": C.FISCAL_YEAR,
        "service_area_name": C.SERVICE_AREA_NAME,
        "prior_year_cost_to_charge_ratio": C.PRIOR_YEAR_RATIO,
        "total_operating_expense_cents": C.TOTAL_OPERATING_EXPENSE_CENTS,
    }
    payload.update(overrides)
    return payload


def board_action_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "action_type": BoardActionType.ADOPT,
        "quorum_present": True,
        "votes_for": C.VOTES_FOR,
        "votes_against": C.VOTES_AGAINST,
    }
    payload.update(overrides)
    return payload


def publish_cycle_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "public_url": "https://riverbend.example.org/chna/2026",
        "public_comment_channel": "chna-comments@riverbend.example.org",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# HealthIndicator / IndicatorDataPoint
# --------------------------------------------------------------------------
def indicator_payload(cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "domain": IndicatorDomain.BEHAVIORAL_HEALTH,
        "name": C.INDICATOR_NAME,
        "benchmark_value": C.BENCHMARK_VALUE,
    }
    payload.update(overrides)
    return payload


def data_point_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "population_subgroup": Subgroup.OVERALL,
        "source_type": DataSourceType.PUBLIC_DATASET,
        "value": C.OVERALL_VALUE,
        "collected_on": C.COLLECTED_ON,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# ResponsibleParty
# --------------------------------------------------------------------------
def internal_party_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": C.INTERNAL_PARTY_NAME,
        "party_type": PartyType.INTERNAL,
        "fte_capacity_bp": C.BASIS_POINTS_PER_FTE,
    }
    payload.update(overrides)
    return payload


def partner_party_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": C.PARTNER_PARTY_NAME,
        "party_type": PartyType.PARTNER,
        "fte_capacity_bp": C.BASIS_POINTS_PER_FTE,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# StakeholderInterview
# --------------------------------------------------------------------------
def interview_payload(cycle_id: str, facilitator_party_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "facilitator_party_id": facilitator_party_id,
        "organization_name": C.ORGANIZATION_NAME,
        "sector": Sector.SAFETY_NET_PROVIDER,
        "starts_at": C.INTERVIEW_STARTS_AT,
        "ends_at": C.INTERVIEW_ENDS_AT,
    }
    payload.update(overrides)
    return payload


def complete_interview_payload(
    domain: str = IndicatorDomain.BEHAVIORAL_HEALTH,
    rating: int = 5,
    attendee_count: int = C.ATTENDEE_COUNT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "concern_ratings": {domain: rating},
        "attendee_count": attendee_count,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# PriorityCandidate
# --------------------------------------------------------------------------
def candidate_payload(cycle_id: str, indicator_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "indicator_id": indicator_id,
        "hospital_capacity_score": C.HOSPITAL_CAPACITY_SCORE,
    }
    payload.update(overrides)
    return payload


def score_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"scoring_variant": ScoringVariant.EQUAL_WEIGHT}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# ImplementationStrategy / StrategyObjective
# --------------------------------------------------------------------------
def strategy_payload(candidate_id: str, expected_candidate_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "candidate_id": candidate_id,
        "title": C.STRATEGY_TITLE,
        "authorized_budget_cents": C.AUTHORIZED_BUDGET_CENTS,
        "expected_candidate_version": expected_candidate_version,
    }
    payload.update(overrides)
    return payload


def objective_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "metric_name": C.OBJECTIVE_METRIC_NAME,
        "baseline_value": C.OBJECTIVE_BASELINE_VALUE,
        "target_value": C.OBJECTIVE_TARGET_VALUE,
        "target_date": C.OBJECTIVE_TARGET_DATE,
    }
    payload.update(overrides)
    return payload


def report_progress_payload(actual_value: float, as_of_date: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"actual_value": actual_value, "as_of_date": as_of_date}
    payload.update(overrides)
    return payload


def execution_status_payload(to_execution_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_execution_state": to_execution_state}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# PartnershipAgreement / ResourceCommitment
# --------------------------------------------------------------------------
def agreement_payload(cycle_id: str, party_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "party_id": party_id,
        "pledged_cents": C.PLEDGED_CENTS,
        "accountability_metric": C.ACCOUNTABILITY_METRIC,
        "shared_accountability_pct": C.SHARED_ACCOUNTABILITY_PCT,
        "term_start": C.TERM_START,
        "term_end": C.TERM_END,
    }
    payload.update(overrides)
    return payload


def commitment_payload(
    strategy_id: str,
    party_id: str,
    partnership_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "strategy_id": strategy_id,
        "party_id": party_id,
        "fte_bp": C.COMMITMENT_FTE_BP,
        "funding_cents": C.COMMITMENT_FUNDING_CENTS,
        "effective_from": C.COMMITMENT_EFFECTIVE_FROM,
        "effective_to": C.COMMITMENT_EFFECTIVE_TO,
    }
    if partnership_id is not None:
        payload["partnership_id"] = partnership_id
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# CommunityBenefitReport / ExpensePosting
# --------------------------------------------------------------------------
def report_payload(cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"cycle_id": cycle_id, "fiscal_year": C.FISCAL_YEAR}
    payload.update(overrides)
    return payload


def charge_based_posting_payload(
    report_id: str,
    expected_report_version: int,
    charges_cents: int,
    category: str = Category.FINANCIAL_ASSISTANCE,
    **overrides: Any,
) -> Dict[str, Any]:
    """A charge-based posting: ``charges_cents`` >= 1 and ``direct_cost_cents`` exactly 0."""
    payload: Dict[str, Any] = {
        "report_id": report_id,
        "category": category,
        "charges_cents": charges_cents,
        "direct_cost_cents": 0,
        "expected_report_version": expected_report_version,
    }
    payload.update(overrides)
    return payload


def cost_based_posting_payload(
    report_id: str,
    expected_report_version: int,
    direct_cost_cents: int,
    category: str = Category.COMMUNITY_HEALTH_IMPROVEMENT,
    **overrides: Any,
) -> Dict[str, Any]:
    """A cost-based posting: ``direct_cost_cents`` >= 1 and ``charges_cents`` exactly 0."""
    payload: Dict[str, Any] = {
        "report_id": report_id,
        "category": category,
        "charges_cents": 0,
        "direct_cost_cents": direct_cost_cents,
        "expected_report_version": expected_report_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# ProgressEvaluation
# --------------------------------------------------------------------------
def evaluation_payload(cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "eval_type": EvalType.ANNUAL,
        "period_year": C.FISCAL_YEAR,
    }
    payload.update(overrides)
    return payload


def publish_evaluation_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"public_url": f"https://riverbend.example.org/eval/{_next()}"}
    payload.update(overrides)
    return payload
