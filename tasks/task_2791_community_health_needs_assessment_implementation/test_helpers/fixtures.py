"""Composite setup helpers.

Each pytest test runs against a freshly relaunched server and an empty
database, so every precondition has to be rebuilt from scratch through the
declared endpoints.  These helpers encode the one worked example the suite
threads throughout, and each of them accepts ``**overrides`` so a test can vary
exactly the literal it is probing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    BOARD,
    COMPLIANCE,
    OFFICER,
    STEWARD,
    make_partner_representative_headers,
)
from .types import (
    ApprovalState,
    CycleStatus,
    DataSourceType,
    IndicatorDomain,
    ScoringVariant,
    SignatorySide,
    Subgroup,
)

#: The staged pipeline, in the order the phases must be walked.
STAGES: List[str] = [
    "DRAFT",
    "DATA_COLLECTION",
    "INDICATOR",
    "INPUT_GATHERING",
    "INTERVIEW_COMPLETED",
    "PRIORITIZATION",
    "CANDIDATE_SCORED",
    "CANDIDATE_SELECTED",
    "STRATEGY_DEVELOPMENT",
    "STRATEGY_WITH_OBJECTIVE",
    "SUBMITTED",
    "BOARD_REVIEW",
    "ADOPTED",
]


@dataclass
class Scenario:
    """Identifiers minted while walking the pipeline."""

    api: ApiClient
    stage: str = "DRAFT"
    cycle_id: str = ""
    indicator_id: str = ""
    data_point_ids: List[str] = field(default_factory=list)
    facilitator_party_id: str = ""
    interview_id: str = ""
    candidate_id: str = ""
    strategy_id: str = ""
    objective_id: str = ""
    partner_party_id: str = ""
    agreement_id: str = ""
    commitment_id: str = ""
    report_id: str = ""

    # -- convenience reads ------------------------------------------------
    def cycle(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_cycle(self.cycle_id, headers=headers))

    def indicator(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_indicator(self.indicator_id, headers=headers))

    def candidate(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_candidate(self.candidate_id, headers=headers))

    def strategy(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_strategy(self.strategy_id, headers=headers))

    def objective(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_objective(self.objective_id, headers=headers))

    def agreement(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_agreement(self.agreement_id, headers=headers))

    def commitment(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_commitment(self.commitment_id, headers=headers))

    def partner(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_party(self.partner_party_id, headers=headers))

    def facilitator(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_party(self.facilitator_party_id, headers=headers))

    def report(self, headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
        return get_success_data(self.api.get_report(self.report_id, headers=headers))

    @property
    def partner_headers(self) -> Dict[str, str]:
        return make_partner_representative_headers(self.partner_party_id)


# --------------------------------------------------------------------------
# Tier 1 — state progression
# --------------------------------------------------------------------------
def create_cycle(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A fresh cycle in ``DRAFT`` with ``posture`` ``OPEN``."""
    return get_success_data(api.create_cycle(F.cycle_payload(**overrides)), 201)


def advance_to(api: ApiClient, cycle_id: str, *statuses: str) -> Dict[str, Any]:
    """Walk the declared chain one rung at a time."""
    data: Dict[str, Any] = {}
    for status in statuses:
        headers = COMPLIANCE if status == CycleStatus.CLOSED else OFFICER
        data = get_success_data(api.advance_cycle(cycle_id, status, headers=headers), 200)
    return data


# --------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# --------------------------------------------------------------------------
def add_indicator(api: ApiClient, cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_indicator(F.indicator_payload(cycle_id, **overrides)), 201)


def add_data_point(api: ApiClient, indicator_id: str, **overrides: Any) -> Dict[str, Any]:
    """Observations are the data steward's exclusive territory."""
    return get_success_data(
        api.create_data_point(indicator_id, F.data_point_payload(**overrides), headers=STEWARD), 201
    )


def make_indicator_sufficient(
    api: ApiClient,
    indicator_id: str,
    overall_value: float = C.OVERALL_VALUE,
    high_value: float = C.SUBGROUP_HIGH_VALUE,
    low_value: float = C.SUBGROUP_LOW_VALUE,
    collected_on: str = C.COLLECTED_ON,
    source_type: str = DataSourceType.PUBLIC_DATASET,
) -> List[str]:
    """Three observations: one ``OVERALL`` plus two named subgroups.

    ``data_state`` is ``SUFFICIENT`` when ``latest_overall_value`` is not null
    and ``subgroup_count`` is at least 2, so this is the minimum evidence base a
    candidate can be scored against.
    """
    ids = []
    for subgroup, value in (
        (Subgroup.OVERALL, overall_value),
        (Subgroup.BLACK_NH, high_value),
        (Subgroup.WHITE_NH, low_value),
    ):
        data = add_data_point(
            api,
            indicator_id,
            population_subgroup=subgroup,
            value=value,
            collected_on=collected_on,
            source_type=source_type,
        )
        ids.append(data["id"])
    return ids


def add_internal_party(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Party registration is not gated by any cycle phase."""
    return get_success_data(api.create_party(F.internal_party_payload(**overrides)), 201)


def add_partner_party(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_party(F.partner_party_payload(**overrides)), 201)


def add_interview(
    api: ApiClient, cycle_id: str, facilitator_party_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_interview(F.interview_payload(cycle_id, facilitator_party_id, **overrides)), 201
    )


def complete_interview(
    api: ApiClient,
    interview_id: str,
    domain: str = IndicatorDomain.BEHAVIORAL_HEALTH,
    rating: int = 5,
    attendee_count: int = C.ATTENDEE_COUNT,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_interview(
            interview_id,
            F.complete_interview_payload(
                domain=domain, rating=rating, attendee_count=attendee_count, **overrides
            ),
        ),
        200,
    )


def add_candidate(api: ApiClient, cycle_id: str, indicator_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_candidate(F.candidate_payload(cycle_id, indicator_id, **overrides)), 201
    )


def score_candidate(
    api: ApiClient, candidate_id: str, scoring_variant: str = ScoringVariant.EQUAL_WEIGHT
) -> Dict[str, Any]:
    return get_success_data(api.score_candidate(candidate_id, scoring_variant), 200)


def select_candidate(
    api: ApiClient, candidate_id: str, rationale: str = "Highest composite need with hospital capacity to act"
) -> Dict[str, Any]:
    return get_success_data(api.select_candidate(candidate_id, rationale), 200)


def add_strategy(api: ApiClient, candidate_id: str, **overrides: Any) -> Dict[str, Any]:
    """Reads the candidate's current version first, as the create token requires."""
    version = api.candidate_version(candidate_id)
    return get_success_data(
        api.create_strategy(F.strategy_payload(candidate_id, version, **overrides)), 201
    )


def add_objective(api: ApiClient, strategy_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_objective(strategy_id, F.objective_payload(**overrides)), 201)


def add_agreement(api: ApiClient, cycle_id: str, party_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_agreement(F.agreement_payload(cycle_id, party_id, **overrides)), 201
    )


def execute_agreement(api: ApiClient, agreement_id: str, party_id: str) -> Dict[str, Any]:
    """Both signatures, hospital first, which closes the fork-join.

    Only on reaching the join does ``funding_state`` move ``UNFUNDED`` to
    ``PLEDGED``.
    """
    get_success_data(api.sign_agreement(agreement_id, SignatorySide.HOSPITAL, headers=OFFICER), 200)
    return get_success_data(
        api.sign_agreement(
            agreement_id, SignatorySide.PARTNER, headers=make_partner_representative_headers(party_id)
        ),
        200,
    )


def add_commitment(
    api: ApiClient,
    strategy_id: str,
    party_id: str,
    partnership_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_commitment(
            F.commitment_payload(strategy_id, party_id, partnership_id, **overrides)
        ),
        201,
    )


# --------------------------------------------------------------------------
# Tier 3 — full-lifecycle shortcuts
# --------------------------------------------------------------------------
def build_scenario(
    api: ApiClient,
    stage: str = "ADOPTED",
    with_partner: bool = False,
    cycle_overrides: Optional[Dict[str, Any]] = None,
    indicator_overrides: Optional[Dict[str, Any]] = None,
    interview_overrides: Optional[Dict[str, Any]] = None,
    candidate_overrides: Optional[Dict[str, Any]] = None,
    strategy_overrides: Optional[Dict[str, Any]] = None,
    objective_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    commitment_overrides: Optional[Dict[str, Any]] = None,
    completion_overrides: Optional[Dict[str, Any]] = None,
    scoring_variant: str = ScoringVariant.EQUAL_WEIGHT,
    overall_value: float = C.OVERALL_VALUE,
    high_value: float = C.SUBGROUP_HIGH_VALUE,
    low_value: float = C.SUBGROUP_LOW_VALUE,
) -> Scenario:
    """Walk the pipeline as far as ``stage`` and hand back every identifier.

    The stages, in order, are the members of :data:`STAGES`.  Stopping early is
    how a test obtains a cycle sitting in exactly the phase it needs.
    """
    assert stage in STAGES, f"unknown stage {stage!r}"
    limit = STAGES.index(stage)
    sc = Scenario(api=api, stage=stage)

    cycle = create_cycle(api, **(cycle_overrides or {}))
    sc.cycle_id = cycle["id"]
    if limit < STAGES.index("DATA_COLLECTION"):
        return sc

    advance_to(api, sc.cycle_id, CycleStatus.DATA_COLLECTION)
    if limit < STAGES.index("INDICATOR"):
        return sc

    indicator = add_indicator(api, sc.cycle_id, **(indicator_overrides or {}))
    sc.indicator_id = indicator["id"]
    sc.data_point_ids = make_indicator_sufficient(
        api,
        sc.indicator_id,
        overall_value=overall_value,
        high_value=high_value,
        low_value=low_value,
    )
    sc.facilitator_party_id = add_internal_party(api)["id"]
    if limit < STAGES.index("INPUT_GATHERING"):
        return sc

    advance_to(api, sc.cycle_id, CycleStatus.INPUT_GATHERING)
    sc.interview_id = add_interview(
        api, sc.cycle_id, sc.facilitator_party_id, **(interview_overrides or {})
    )["id"]
    if limit < STAGES.index("INTERVIEW_COMPLETED"):
        return sc

    complete_interview(api, sc.interview_id, **(completion_overrides or {}))
    if limit < STAGES.index("PRIORITIZATION"):
        return sc

    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)
    sc.candidate_id = add_candidate(
        api, sc.cycle_id, sc.indicator_id, **(candidate_overrides or {})
    )["id"]
    if limit < STAGES.index("CANDIDATE_SCORED"):
        return sc

    score_candidate(api, sc.candidate_id, scoring_variant)
    if limit < STAGES.index("CANDIDATE_SELECTED"):
        return sc

    select_candidate(api, sc.candidate_id)
    if limit < STAGES.index("STRATEGY_DEVELOPMENT"):
        return sc

    advance_to(api, sc.cycle_id, CycleStatus.STRATEGY_DEVELOPMENT)
    sc.strategy_id = add_strategy(api, sc.candidate_id, **(strategy_overrides or {}))["id"]
    if limit < STAGES.index("STRATEGY_WITH_OBJECTIVE"):
        return sc

    sc.objective_id = add_objective(api, sc.strategy_id, **(objective_overrides or {}))["id"]
    if with_partner:
        sc.partner_party_id = add_partner_party(api)["id"]
        sc.agreement_id = add_agreement(
            api, sc.cycle_id, sc.partner_party_id, **(agreement_overrides or {})
        )["id"]
        execute_agreement(api, sc.agreement_id, sc.partner_party_id)
        sc.commitment_id = add_commitment(
            api,
            sc.strategy_id,
            sc.partner_party_id,
            sc.agreement_id,
            **(commitment_overrides or {}),
        )["id"]
    if limit < STAGES.index("SUBMITTED"):
        return sc

    get_success_data(api.submit_strategy(sc.strategy_id), 200)
    if limit < STAGES.index("BOARD_REVIEW"):
        return sc

    advance_to(api, sc.cycle_id, CycleStatus.BOARD_REVIEW)
    if limit < STAGES.index("ADOPTED"):
        return sc

    get_success_data(api.board_action(sc.cycle_id, F.board_action_payload(), headers=BOARD), 200)
    return sc


# --------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# --------------------------------------------------------------------------
def open_report(api: ApiClient, cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    """Opening the report is not phase-gated; it seeds the cycle's unaudited ratio."""
    return get_success_data(api.create_report(F.report_payload(cycle_id, **overrides)), 201)


def post_charge_based(
    api: ApiClient,
    report_id: str,
    charges_cents: int,
    category: str = "FINANCIAL_ASSISTANCE",
    headers: Dict[str, str] = OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    """Post one charge-based expense, refreshing the concurrency token first.

    Each posting increments the owning report's ``version``, so the token has to
    be re-read between consecutive postings.
    """
    version = api.report_version(report_id, headers=headers)
    payload = F.charge_based_posting_payload(
        report_id, version, charges_cents, category=category, **overrides
    )
    return get_success_data(api.create_posting(payload, headers=headers), 201)


def post_cost_based(
    api: ApiClient,
    report_id: str,
    direct_cost_cents: int,
    category: str = "COMMUNITY_HEALTH_IMPROVEMENT",
    headers: Dict[str, str] = OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    """Post one cost-based expense, refreshing the concurrency token first."""
    version = api.report_version(report_id, headers=headers)
    payload = F.cost_based_posting_payload(
        report_id, version, direct_cost_cents, category=category, **overrides
    )
    return get_success_data(api.create_posting(payload, headers=headers), 201)


def report_with_postings(
    api: ApiClient, cycle_id: str, charge_amounts: Any = (), cost_amounts: Any = ()
) -> Dict[str, Any]:
    """An open report carrying the supplied charge-based and cost-based postings.

    ``charge_amounts`` and ``cost_amounts`` are iterables of
    ``(category, amount_cents)`` pairs or of bare amounts.
    """
    report = open_report(api, cycle_id)
    postings: List[Dict[str, Any]] = []
    for entry in charge_amounts:
        category, amount = entry if isinstance(entry, tuple) else ("FINANCIAL_ASSISTANCE", entry)
        postings.append(post_charge_based(api, report["id"], amount, category=category))
    for entry in cost_amounts:
        category, amount = (
            entry if isinstance(entry, tuple) else ("COMMUNITY_HEALTH_IMPROVEMENT", entry)
        )
        postings.append(post_cost_based(api, report["id"], amount, category=category))
    return {"report": report, "postings": postings}


def add_evaluation(api: ApiClient, cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    """Evaluations carry no cycle-phase gate at creation time."""
    return get_success_data(api.create_evaluation(F.evaluation_payload(cycle_id, **overrides)), 201)


def publish_evaluation(api: ApiClient, evaluation_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.publish_evaluation(evaluation_id, F.publish_evaluation_payload(**overrides)), 200
    )


# --------------------------------------------------------------------------
# Tier 5 — finalization and terminal states
# --------------------------------------------------------------------------
def publish_cycle(api: ApiClient, cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    """Publication is what sets ``public_availability_met`` to true."""
    return get_success_data(api.publish_cycle(cycle_id, F.publish_cycle_payload(**overrides)), 200)


def finalize_report(
    api: ApiClient,
    report_id: str,
    audited_cost_to_charge_ratio: float = C.AUDITED_RATIO,
    headers: Dict[str, str] = COMPLIANCE,
) -> Dict[str, Any]:
    """Only a compliance officer may lock the report, and never its opener."""
    return get_success_data(
        api.finalize_report(report_id, audited_cost_to_charge_ratio, headers=headers), 200
    )


def file_return(
    api: ApiClient, cycle_id: str, return_form_id: str = "FORM-990-SCHED-H-2026"
) -> Dict[str, Any]:
    """Filing drives the cycle's posture to ``FROZEN``."""
    return get_success_data(api.file_return(cycle_id, return_form_id, headers=COMPLIANCE), 200)


def filed_cycle(api: ApiClient, with_partner: bool = False) -> Scenario:
    """An adopted, published, locked and filed cycle — a ``FROZEN`` posture."""
    sc = build_scenario(api, stage="ADOPTED", with_partner=with_partner)
    bundle = report_with_postings(api, sc.cycle_id, cost_amounts=[850000])
    sc.report_id = bundle["report"]["id"]
    finalize_report(api, sc.report_id)
    publish_cycle(api, sc.cycle_id)
    file_return(api, sc.cycle_id)
    return sc


def suspend_strategy_by_void(api: ApiClient, sc: Scenario) -> Dict[str, Any]:
    """Retract the ``OVERALL`` observation, which drives the three-link void cascade.

    Retraction is exempt from the ``RESTRICTED`` gate but not from ``FROZEN``.
    """
    return get_success_data(
        api.void_data_point(sc.data_point_ids[0], "Source dataset withdrawn", headers=STEWARD), 200
    )


def submitted_strategy(api: ApiClient) -> Scenario:
    """A cycle in ``BOARD_REVIEW`` with one submitted strategy — posture ``RESTRICTED``."""
    return build_scenario(api, stage="BOARD_REVIEW")


def approved_strategy(api: ApiClient, with_partner: bool = False) -> Scenario:
    """An adopted cycle whose single strategy is ``APPROVED`` and ``ON_TRACK``."""
    return build_scenario(api, stage="ADOPTED", with_partner=with_partner)


def draft_strategy(api: ApiClient, with_partner: bool = False, **kwargs: Any) -> Scenario:
    """A cycle in ``STRATEGY_DEVELOPMENT`` whose strategy is still ``DRAFT``."""
    return build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE", with_partner=with_partner, **kwargs)


def assert_strategy_is_draft(strategy: Dict[str, Any]) -> None:
    assert strategy["approval_state"] == ApprovalState.DRAFT
