"""Composite setup builders.

Single-step builders create one row each; the tiered scenario builders stack
them into the states the tests need — an organisation bench, a proposed
placement, an active placement, an observed placement whose compliance ratio is
1.0, a scored assessment and a completed placement.

Every builder asserts its own setup succeeded, so a test that fails is failing
on its own trigger rather than on a silently broken precondition.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .api_client import EppApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    ASSESSMENT_SCORER,
    CREDENTIAL_ANALYST,
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    SUPERVISION_LEAD,
    make_candidate_headers,
    make_university_supervisor_headers,
)


@dataclass
class Scenario:
    """Everything a stacked setup produced, keyed by role in the story."""
    district: Optional[Dict[str, Any]] = None
    agreement: Optional[Dict[str, Any]] = None
    teacher: Optional[Dict[str, Any]] = None
    second_teacher: Optional[Dict[str, Any]] = None
    supervisor: Optional[Dict[str, Any]] = None
    candidate: Optional[Dict[str, Any]] = None
    exam_item: Optional[Dict[str, Any]] = None
    clearance_item: Optional[Dict[str, Any]] = None
    coursework_item: Optional[Dict[str, Any]] = None
    request: Optional[Dict[str, Any]] = None
    placement: Optional[Dict[str, Any]] = None
    cycles: List[Dict[str, Any]] = field(default_factory=list)
    assessment: Optional[Dict[str, Any]] = None

    # ─── id shortcuts ─────────────────────────────────
    @property
    def district_id(self) -> str:
        return self.district["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def teacher_id(self) -> str:
        return self.teacher["id"]

    @property
    def supervisor_id(self) -> str:
        return self.supervisor["id"]

    @property
    def candidate_id(self) -> str:
        return self.candidate["id"]

    @property
    def request_id(self) -> str:
        return self.request["id"]

    @property
    def placement_id(self) -> str:
        return self.placement["id"]

    @property
    def assessment_id(self) -> str:
        return self.assessment["id"]

    # ─── entity-backed identities ─────────────────────
    @property
    def supervisor_headers(self) -> Dict[str, str]:
        return make_university_supervisor_headers(self.supervisor_id)

    @property
    def candidate_headers(self) -> Dict[str, str]:
        return make_candidate_headers(self.candidate_id)


# ─── Clock ────────────────────────────────────────────

def set_clock(api: EppApiClient, current_utc: str) -> None:
    validate_success(api.set_clock(current_utc, PROGRAM_ADMIN))


def reset_clock(api: EppApiClient) -> None:
    set_clock(api, DEFAULT_CLOCK)


# ─── Single-row builders ──────────────────────────────

def create_district(api: EppApiClient, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.create_district(f.district_payload(**overrides), PROGRAM_ADMIN), 201)


def create_agreement(api: EppApiClient, district_id: str, activate: bool = True,
                     **overrides: Any) -> Dict[str, Any]:
    agreement = validate_success(
        api.create_agreement(f.agreement_payload(district_id, **overrides),
                             PROGRAM_ADMIN), 201)
    if activate:
        agreement = validate_success(
            api.activate_agreement(agreement["id"], PROGRAM_ADMIN))
    return agreement


def create_teacher(api: EppApiClient, district_id: str,
                   training_completed_on: Optional[str] = "2026-06-01",
                   **overrides: Any) -> Dict[str, Any]:
    teacher = validate_success(
        api.create_teacher(f.teacher_payload(district_id, **overrides),
                           SUPERVISION_LEAD), 201)
    if training_completed_on is not None:
        teacher = validate_success(api.record_training_completion(
            teacher["id"],
            f.training_completion_payload(training_completed_on),
            SUPERVISION_LEAD))
    return teacher


def create_supervisor(api: EppApiClient, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.create_supervisor(f.supervisor_payload(**overrides),
                              SUPERVISION_LEAD), 201)


def create_candidate(api: EppApiClient, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.create_candidate(f.candidate_payload(**overrides), PROGRAM_ADMIN), 201)


def add_item(api: EppApiClient, payload: Dict[str, Any],
             verify: bool = True) -> Dict[str, Any]:
    item = validate_success(
        api.create_readiness_item(payload, CREDENTIAL_ANALYST), 201)
    if verify:
        item = validate_success(api.verify_readiness_item(
            item["id"], f.verify_item_payload(), CREDENTIAL_ANALYST))
    return item


def add_exam_item(api: EppApiClient, candidate_id: str, verify: bool = True,
                  **overrides: Any) -> Dict[str, Any]:
    return add_item(api, f.exam_item_payload(candidate_id, **overrides), verify)


def add_clearance_item(api: EppApiClient, candidate_id: str, verify: bool = True,
                       **overrides: Any) -> Dict[str, Any]:
    return add_item(api, f.clearance_item_payload(candidate_id, **overrides), verify)


def add_coursework_item(api: EppApiClient, candidate_id: str, verify: bool = True,
                        **overrides: Any) -> Dict[str, Any]:
    return add_item(api, f.coursework_item_payload(candidate_id, **overrides), verify)


def open_request(api: EppApiClient, candidate_id: str,
                 preferred_district_id: Optional[str] = None,
                 **overrides: Any) -> Dict[str, Any]:
    return validate_success(api.create_placement_request(
        f.placement_request_payload(candidate_id,
                                    preferred_district_id=preferred_district_id,
                                    **overrides),
        PLACEMENT_COORDINATOR), 201)


def route(api: EppApiClient, request_id: str) -> Dict[str, Any]:
    return validate_success(api.route_request(request_id, PLACEMENT_COORDINATOR), 201)


def confirm(api: EppApiClient, placement_id: str) -> Dict[str, Any]:
    return validate_success(
        api.confirm_placement(placement_id, PLACEMENT_COORDINATOR))


def schedule_cycle(api: EppApiClient, placement_id: str, sequence_no: int,
                   cycle_type: str, window_start: str,
                   window_end: str) -> Dict[str, Any]:
    return validate_success(api.create_observation_cycle(
        f.observation_cycle_payload(placement_id, sequence_no=sequence_no,
                                    cycle_type=cycle_type,
                                    window_start=window_start,
                                    window_end=window_end),
        SUPERVISION_LEAD), 201)


def complete_cycle(api: EppApiClient, cycle_id: str, supervisor_id: str,
                   observed_at: str, rubric_score: float = 4.0,
                   advance_clock: bool = True) -> Dict[str, Any]:
    if advance_clock:
        set_clock(api, observed_at)
    return validate_success(api.complete_observation_cycle(
        cycle_id, f.cycle_complete_payload(observed_at, rubric_score),
        make_university_supervisor_headers(supervisor_id)))


def open_assessment(api: EppApiClient, placement_id: str,
                    **overrides: Any) -> Dict[str, Any]:
    return validate_success(api.create_performance_assessment(
        f.assessment_payload(placement_id, **overrides), ASSESSMENT_SCORER), 201)


def submit_assessment(api: EppApiClient, assessment_id: str, candidate_id: str,
                      **overrides: Any) -> Dict[str, Any]:
    return validate_success(api.submit_assessment(
        assessment_id, f.assessment_submit_payload(**overrides),
        make_candidate_headers(candidate_id)))


def score_assessment(api: EppApiClient, assessment_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     **overrides: Any) -> Dict[str, Any]:
    return validate_success(api.score_assessment(
        assessment_id, f.assessment_score_payload(**overrides),
        headers if headers is not None else ASSESSMENT_SCORER))


def complete_placement(api: EppApiClient, placement_id: str) -> Dict[str, Any]:
    return validate_success(api.complete_placement(
        placement_id, f.complete_placement_payload(), PLACEMENT_COORDINATOR))


# ─── The standard clinical calendar ───────────────────

DEFAULT_CYCLE_PLAN = (
    # sequence_no, cycle_type, window_start, window_end, observed_at, rubric_score
    (1, "FORMATIVE", "2026-09-14T00:00:00Z", "2026-09-19T00:00:00Z",
     "2026-09-16T15:00:00Z", 4.0),
    (2, "FORMATIVE", "2026-10-05T00:00:00Z", "2026-10-10T00:00:00Z",
     "2026-10-06T15:00:00Z", 4.0),
    (3, "SUMMATIVE", "2026-11-16T00:00:00Z", "2026-11-21T00:00:00Z",
     "2026-11-17T15:00:00Z", 4.5),
)

ASSESSMENT_WINDOW_OPENS = "2026-11-01T00:00:00Z"
ASSESSMENT_WINDOW_CLOSES = "2026-12-01T00:00:00Z"
SUBMISSION_CLOCK = "2026-11-18T09:00:00Z"
SETTLEMENT_CLOCK = "2026-12-08T00:00:00Z"

# A pass on the first attempt: 4.0, 3.5, 3.0 and 3.0 total exactly the cut score.
PASSING_SCORES = {
    "task_planning": 4.0,
    "task_instruction": 3.5,
    "task_assessment": 3.0,
    "task_professionalism": 3.0,
}


# ─── Tier 1: the organisation bench ───────────────────

def setup_bench(api: EppApiClient, *, clock: Optional[str] = DEFAULT_CLOCK,
                district: Optional[Dict[str, Any]] = None,
                agreement: Optional[Dict[str, Any]] = None,
                teacher: Optional[Dict[str, Any]] = None,
                supervisor: Optional[Dict[str, Any]] = None,
                training_completed_on: Optional[str] = "2026-06-01",
                activate_agreement: bool = True) -> Scenario:
    """A district, an active agreement, a qualified teacher and a supervisor."""
    if clock is not None and clock != DEFAULT_CLOCK:
        set_clock(api, clock)
    scenario = Scenario()
    scenario.district = create_district(api, **(district or {}))
    scenario.agreement = create_agreement(api, scenario.district_id,
                                          activate=activate_agreement,
                                          **(agreement or {}))
    scenario.teacher = create_teacher(api, scenario.district_id,
                                      training_completed_on=training_completed_on,
                                      **(teacher or {}))
    scenario.supervisor = create_supervisor(api, **(supervisor or {}))
    return scenario


def add_teacher(api: EppApiClient, scenario: Scenario,
                training_completed_on: Optional[str] = "2026-06-01",
                **overrides: Any) -> Dict[str, Any]:
    """A second cooperating teacher at the same district, kept on the scenario."""
    teacher = create_teacher(api, scenario.district_id,
                             training_completed_on=training_completed_on,
                             **overrides)
    scenario.second_teacher = teacher
    return teacher


# ─── Tier 2: a candidate who clears the readiness gate ─

def setup_ready_candidate(api: EppApiClient, *,
                          scenario: Optional[Scenario] = None,
                          candidate: Optional[Dict[str, Any]] = None,
                          exam: Optional[Dict[str, Any]] = None,
                          clearance: Optional[Dict[str, Any]] = None,
                          coursework: Optional[Dict[str, Any]] = None) -> Scenario:
    """A candidate with a verified exam, clearance and coursework block.

    A passing exam contributes 40 points, any clearance 35 and an 18-credit
    block 15, for the 90 that clears the readiness threshold.
    """
    scenario = scenario if scenario is not None else Scenario()
    scenario.candidate = create_candidate(api, **(candidate or {}))
    scenario.exam_item = add_exam_item(api, scenario.candidate_id, **(exam or {}))
    scenario.clearance_item = add_clearance_item(api, scenario.candidate_id,
                                                 **(clearance or {}))
    scenario.coursework_item = add_coursework_item(api, scenario.candidate_id,
                                                  **(coursework or {}))
    return scenario


# ─── Tier 3: a routed, proposed placement ─────────────

def setup_proposed_placement(api: EppApiClient, *, clock: Optional[str] = None,
                             district: Optional[Dict[str, Any]] = None,
                             agreement: Optional[Dict[str, Any]] = None,
                             teacher: Optional[Dict[str, Any]] = None,
                             supervisor: Optional[Dict[str, Any]] = None,
                             candidate: Optional[Dict[str, Any]] = None,
                             exam: Optional[Dict[str, Any]] = None,
                             clearance: Optional[Dict[str, Any]] = None,
                             coursework: Optional[Dict[str, Any]] = None,
                             request: Optional[Dict[str, Any]] = None,
                             training_completed_on: Optional[str] = "2026-06-01",
                             prefer_district: bool = True) -> Scenario:
    """The bench, a ready candidate, an open request and its PROPOSED placement."""
    scenario = setup_bench(api, clock=clock, district=district, agreement=agreement,
                           teacher=teacher, supervisor=supervisor,
                           training_completed_on=training_completed_on)
    setup_ready_candidate(api, scenario=scenario, candidate=candidate, exam=exam,
                          clearance=clearance, coursework=coursework)
    scenario.request = open_request(
        api, scenario.candidate_id,
        preferred_district_id=scenario.district_id if prefer_district else None,
        **(request or {}))
    scenario.placement = route(api, scenario.request_id)
    return scenario


# ─── Tier 4: a confirmed, active placement ────────────

def setup_active_placement(api: EppApiClient, **kwargs: Any) -> Scenario:
    """A confirmed placement, so the provisional stipend has accrued."""
    scenario = setup_proposed_placement(api, **kwargs)
    scenario.placement = confirm(api, scenario.placement_id)
    return scenario


# ─── Tier 5: an observed placement at full compliance ─

def setup_observed_placement(api: EppApiClient, *, cycle_plan=DEFAULT_CYCLE_PLAN,
                             **kwargs: Any) -> Scenario:
    """An active placement whose scheduled cycles were all observed.

    With every counted cycle completed and one of them summative, the
    compliance ratio reaches 1.0 and the summative requirement is met.
    """
    scenario = setup_active_placement(api, **kwargs)
    for sequence_no, cycle_type, start, end, _observed_at, _rubric in cycle_plan:
        scenario.cycles.append(
            schedule_cycle(api, scenario.placement_id, sequence_no, cycle_type,
                           start, end))
    for index, plan in enumerate(cycle_plan):
        scenario.cycles[index] = complete_cycle(
            api, scenario.cycles[index]["id"], scenario.supervisor_id,
            plan[4], plan[5])
    return scenario


def setup_scheduled_cycles(api: EppApiClient, scenario: Scenario,
                           cycle_plan=DEFAULT_CYCLE_PLAN) -> List[Dict[str, Any]]:
    """Schedule cycles on an existing placement without observing them."""
    for sequence_no, cycle_type, start, end, _observed, _rubric in cycle_plan:
        scenario.cycles.append(
            schedule_cycle(api, scenario.placement_id, sequence_no, cycle_type,
                           start, end))
    return scenario.cycles


# ─── Tier 6: a passed performance assessment ──────────

def setup_passed_assessment(api: EppApiClient, *,
                            window_opens_at: str = ASSESSMENT_WINDOW_OPENS,
                            window_closes_at: str = ASSESSMENT_WINDOW_CLOSES,
                            submission_clock: str = SUBMISSION_CLOCK,
                            scores: Optional[Dict[str, Any]] = None,
                            **kwargs: Any) -> Scenario:
    """An observed placement whose assessment was submitted and scored at the cut."""
    scenario = setup_observed_placement(api, **kwargs)
    scenario.assessment = open_assessment(api, scenario.placement_id,
                                          window_opens_at=window_opens_at,
                                          window_closes_at=window_closes_at)
    set_clock(api, submission_clock)
    scenario.assessment = submit_assessment(api, scenario.assessment_id,
                                            scenario.candidate_id)
    scenario.assessment = score_assessment(api, scenario.assessment_id,
                                           **(scores or PASSING_SCORES))
    return scenario


# ─── Tier 7: a completed placement ────────────────────

def setup_completed_placement(api: EppApiClient, *,
                              settlement_clock: str = SETTLEMENT_CLOCK,
                              **kwargs: Any) -> Scenario:
    """A placement carried all the way to COMPLETED with a settled stipend."""
    scenario = setup_passed_assessment(api, **kwargs)
    set_clock(api, settlement_clock)
    scenario.placement = complete_placement(api, scenario.placement_id)
    return scenario


# ─── Read-back helpers ────────────────────────────────

def read_placement(api: EppApiClient, placement_id: str) -> Dict[str, Any]:
    return validate_success(api.get_placement(placement_id, PLACEMENT_COORDINATOR))


def read_agreement(api: EppApiClient, agreement_id: str) -> Dict[str, Any]:
    return validate_success(api.get_agreement(agreement_id, PROGRAM_ADMIN))


def read_supervisor(api: EppApiClient, supervisor_id: str) -> Dict[str, Any]:
    return validate_success(api.get_supervisor(supervisor_id, SUPERVISION_LEAD))


def read_teacher(api: EppApiClient, teacher_id: str) -> Dict[str, Any]:
    return validate_success(api.get_teacher(teacher_id, SUPERVISION_LEAD))


def read_candidate(api: EppApiClient, candidate_id: str) -> Dict[str, Any]:
    return validate_success(api.get_candidate(candidate_id, PROGRAM_ADMIN))


def read_request(api: EppApiClient, request_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_placement_request(request_id, PLACEMENT_COORDINATOR))


def read_cycle(api: EppApiClient, cycle_id: str) -> Dict[str, Any]:
    return validate_success(api.get_observation_cycle(cycle_id, SUPERVISION_LEAD))


def read_item(api: EppApiClient, item_id: str) -> Dict[str, Any]:
    return validate_success(api.get_readiness_item(item_id, CREDENTIAL_ANALYST))


def read_assessment(api: EppApiClient, assessment_id: str) -> Dict[str, Any]:
    return validate_success(
        api.get_performance_assessment(assessment_id, ASSESSMENT_SCORER))
