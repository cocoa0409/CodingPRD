"""Composite setup helpers.

Every helper builds state through the public API via api_client — never by
server internals — using get_success_data so setup failures surface as clear
"Setup step failed" errors. Ownership-gated calls always thread the acting
entity's real id through make_candidate_headers / make_assessor_headers.

Clock discipline (PRD §2.4): the server starts at 2026-09-01T00:00:00Z and
never uses wall-clock time. Helpers that need a working clock inside the
standard submission window call set_logical_clock themselves (default
STANDARD_WORK_CLOCK = 2027-01-10T00:00:00Z); pass clock=None to leave the
server at its startup default.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_assessor_headers,
    make_candidate_headers,
)

ANON = TEST_USERS["anonymous_headers"]
BOARD = TEST_USERS["board_admin_headers"]
SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]
INCENTIVE_ADMIN = TEST_USERS["incentive_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------
def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the server-held logical clock (BoardAdministrator only)."""
    return get_success_data(
        api_client.set_clock(factories.clock_payload(to_iso8601), BOARD)
    )


# ---------------------------------------------------------------------------
# Tier 1: single-entity progression
# ---------------------------------------------------------------------------
def create_open_cycle(clock: Optional[str] = factories.STANDARD_WORK_CLOCK, **cycle_overrides) -> dict:
    """Create a cycle and advance it DRAFT -> OPEN. Returns the OPEN cycle."""
    if clock is not None:
        set_logical_clock(clock)
    cycle = get_success_data(
        api_client.create_cycle(factories.create_cycle_payload(**cycle_overrides), BOARD)
    )
    cycle = get_success_data(
        api_client.transition_cycle(cycle["id"], factories.cycle_transition_payload("OPEN"), BOARD)
    )
    return cycle


def create_eligible_candidate(**candidate_overrides) -> dict:
    """Register -> submit eligibility evidence -> board APPROVE. Returns the
    ELIGIBLE candidate record."""
    candidate = get_success_data(
        api_client.create_candidate(factories.create_candidate_payload(**candidate_overrides), ANON)
    )
    headers = make_candidate_headers(candidate["id"])
    get_success_data(
        api_client.submit_eligibility(
            candidate["id"], factories.eligibility_evidence_payload(), headers
        )
    )
    candidate = get_success_data(
        api_client.verify_eligibility(
            candidate["id"], factories.verify_eligibility_payload("APPROVE"), BOARD
        )
    )
    return candidate


def create_default_benchmark(**overrides) -> dict:
    """Publish a calibration benchmark (default: P1, known_score 3.00, server
    default tolerance 0.25)."""
    return get_success_data(
        api_client.create_benchmark(factories.create_benchmark_payload(**overrides), SCORING_ADMIN)
    )


def create_recruited_assessor(**overrides) -> dict:
    """Recruit an assessor (status RECRUITED)."""
    return get_success_data(
        api_client.create_assessor(factories.create_assessor_payload(**overrides), SCORING_ADMIN)
    )


def transition_assessor(assessor_id: str, to: str) -> dict:
    return get_success_data(
        api_client.transition_assessor(assessor_id, factories.assessor_transition_payload(to), SCORING_ADMIN)
    )


def submit_calibration_read(benchmark_id: str, assessor: dict, score: float) -> dict:
    """Create a calibration assignment for the assessor (who must be
    CALIBRATING) and submit the score as that assessor. Calibration reads
    finalize immediately. Returns the FINALIZED assignment."""
    assignment = get_success_data(
        api_client.create_assignment(
            factories.create_assignment_payload(
                benchmark_id=benchmark_id, assessor_id=assessor["id"]
            ),
            SCORING_ADMIN,
        )
    )
    return get_success_data(
        api_client.submit_score(
            assignment["id"],
            factories.submit_score_payload(score),
            make_assessor_headers(assessor["id"]),
        )
    )


def create_active_assessor(
    benchmark_id: str,
    calibration_scores=(3.00, 3.25),
    **overrides,
) -> dict:
    """Walk an assessor RECRUITED -> IN_TRAINING -> CALIBRATING -> (two
    in-tolerance calibration reads -> auto CALIBRATED) -> ACTIVE.
    Default reads 3.00 / 3.25 sit within the default 0.25 tolerance of the
    default benchmark's known_score 3.00. Returns the ACTIVE assessor."""
    assessor = create_recruited_assessor(**overrides)
    transition_assessor(assessor["id"], "IN_TRAINING")
    transition_assessor(assessor["id"], "CALIBRATING")
    for score in calibration_scores:
        submit_calibration_read(benchmark_id, assessor, score)
    return transition_assessor(assessor["id"], "ACTIVE")


def create_active_assessors(benchmark_id: str, count: int = 2, district_base: int = 900) -> list:
    """N ACTIVE assessors with distinct home districts (D-900, D-901, ...) so
    none conflicts with the standard candidate district D-100."""
    return [
        create_active_assessor(benchmark_id, home_district_code=f"D-{district_base + i}")
        for i in range(count)
    ]


def create_assessment_center(slot_capacity: int = 5, **overrides) -> dict:
    return get_success_data(
        api_client.create_assessment_center(
            factories.create_assessment_center_payload(slot_capacity=slot_capacity, **overrides),
            BOARD,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: submissions and artifacts
# ---------------------------------------------------------------------------
def create_submission(cycle_id: str, candidate: dict, component_code: str) -> dict:
    """Begin a component attempt for the candidate (X-User-ID == candidate id).
    The first attempt in a cycle auto-creates the candidate's Certification."""
    return get_success_data(
        api_client.create_submission(
            cycle_id,
            factories.create_submission_payload(component_code),
            make_candidate_headers(candidate["id"]),
        )
    )


def upload_artifact(submission_id: str, candidate: dict, payload: dict) -> dict:
    return get_success_data(
        api_client.upload_artifact(submission_id, payload, make_candidate_headers(candidate["id"]))
    )


def upload_minimal_portfolio_artifacts(
    submission_id: str,
    candidate: dict,
    student_count=None,
    include_release_form: bool = False,
) -> list:
    """The minimal compliant portfolio set: one WRITTEN_COMMENTARY plus one
    VIDEO. With student_count >= 1 a RELEASE_FORM is required — pass
    include_release_form=True to stay compliant. Default omits the count
    (PRD §3.3: the count "must be at least 1 when supplied")."""
    artifacts = [
        upload_artifact(
            submission_id, candidate, factories.document_artifact_payload("WRITTEN_COMMENTARY")
        ),
        upload_artifact(
            submission_id,
            candidate,
            factories.video_artifact_payload(subject_student_count=student_count),
        ),
    ]
    if include_release_form:
        artifacts.append(
            upload_artifact(submission_id, candidate, factories.release_form_artifact_payload())
        )
    return artifacts


def submit_submission(submission_id: str, candidate: dict) -> dict:
    """Candidate submit (or resubmit from RETURNED). Returns SUBMITTED record."""
    return get_success_data(
        api_client.submit_submission(submission_id, make_candidate_headers(candidate["id"]))
    )


def tech_review(submission_id: str, decision: str = "ACCEPT", note=None) -> dict:
    """ScoringAdministrator technical review. ACCEPT -> SCORING; RETURN ->
    RETURNED."""
    return get_success_data(
        api_client.tech_review_submission(
            submission_id, factories.tech_review_payload(decision, note), SCORING_ADMIN
        )
    )


def create_portfolio_submission_in_state(
    cycle_id: str,
    candidate: dict,
    component_code: str = "P1",
    state: str = "IN_PROGRESS",
    student_count=None,
) -> dict:
    """Portfolio attempt walked to IN_PROGRESS, SUBMITTED, or SCORING."""
    submission = create_submission(cycle_id, candidate, component_code)
    if state == "IN_PROGRESS":
        return submission
    upload_minimal_portfolio_artifacts(submission["id"], candidate, student_count=student_count)
    submission = submit_submission(submission["id"], candidate)
    if state == "SUBMITTED":
        return submission
    submission = tech_review(submission["id"], "ACCEPT")
    if state == "SCORING":
        return submission
    raise ValueError(f"unsupported target state for this helper: {state}")


def create_eligible_candidate_with_assessment_submission(
    cycle_id: str,
    component_code: str = factories.STANDARD_ASSESSMENT_COMPONENT,
    **candidate_overrides,
) -> tuple:
    """ELIGIBLE candidate holding an IN_PROGRESS attempt of the cycle's
    ASSESSMENT component. Returns (candidate, submission)."""
    candidate = create_eligible_candidate(**candidate_overrides)
    submission = create_submission(cycle_id, candidate, component_code)
    return candidate, submission


# ---------------------------------------------------------------------------
# Tier 3: scoring flows
# ---------------------------------------------------------------------------
def create_live_assignment(submission_id: str, assessor: Optional[dict] = None) -> dict:
    """Create a live scoring assignment. assessor=None invokes the selector
    policy; otherwise the explicit assessor is assigned."""
    return get_success_data(
        api_client.create_assignment(
            factories.create_assignment_payload(
                submission_id=submission_id,
                assessor_id=assessor["id"] if assessor else None,
            ),
            SCORING_ADMIN,
        )
    )


def submit_assignment_score(assignment_id: str, assessor: dict, score: float) -> dict:
    """The owning assessor submits their blind score (X-User-ID == assessor id)."""
    return get_success_data(
        api_client.submit_score(
            assignment_id,
            factories.submit_score_payload(score),
            make_assessor_headers(assessor["id"]),
        )
    )


def score_portfolio_with_read_pair(
    submission_id: str, assessor1: dict, assessor2: dict, score1: float, score2: float
) -> dict:
    """Two blind reads on a SCORING portfolio submission. |d| <= 0.50 finalizes
    both and SCORES the attempt (final_score = round_half_up mean); |d| > 0.50
    moves it to ADJUDICATION_REQUIRED. Returns the refreshed submission."""
    assignment1 = create_live_assignment(submission_id, assessor1)
    submit_assignment_score(assignment1["id"], assessor1, score1)
    assignment2 = create_live_assignment(submission_id, assessor2)
    submit_assignment_score(assignment2["id"], assessor2, score2)
    return get_success_data(api_client.get_submission(submission_id, BOARD))


def score_portfolio_with_agreeing_reads(
    submission_id: str, assessor1: dict, assessor2: dict, score: float
) -> dict:
    """Both reads equal `score` -> final_score == score, submission SCORED."""
    return score_portfolio_with_read_pair(submission_id, assessor1, assessor2, score, score)


def adjudicate_submission(submission_id: str, adjudicator: dict, score: float) -> dict:
    """The read-3 adjudication on an ADJUDICATION_REQUIRED submission; the
    adjudicator's score becomes final_score. Returns the SCORED submission."""
    assignment = create_live_assignment(submission_id, adjudicator)
    submit_assignment_score(assignment["id"], adjudicator, score)
    return get_success_data(api_client.get_submission(submission_id, BOARD))


def create_booking_for_assessment(
    cycle_id: str,
    candidate: dict,
    center_id: str,
    slot_start_at: str = factories.STANDARD_SLOT_START,
) -> dict:
    """Book a slot for the candidate (requires an IN_PROGRESS ASSESSMENT
    attempt in the cycle). Returns the BOOKED booking."""
    return get_success_data(
        api_client.create_booking(
            factories.create_booking_payload(center_id, cycle_id, slot_start_at),
            make_candidate_headers(candidate["id"]),
        )
    )


def complete_booking(
    booking_id: str,
    earned_score: float,
    completion_clock: str = factories.STANDARD_COMPLETION_CLOCK,
) -> dict:
    """Advance the clock to completion_clock (>= slot_start_at, before the
    +120 minute slot end so no NO_SHOW sweep fires) and complete the session.
    The matching ASSESSMENT attempt transitions to SCORED with final_score :=
    earned_score, and certification aggregation recomputes."""
    set_logical_clock(completion_clock)
    return get_success_data(
        api_client.transition_booking(
            booking_id,
            factories.booking_transition_payload("COMPLETED", earned_score=earned_score),
            SCORING_ADMIN,
        )
    )


def score_assessment_component(
    cycle_id: str,
    candidate: dict,
    center_id: str,
    component_code: str = factories.STANDARD_ASSESSMENT_COMPONENT,
    earned_score: float = 3.00,
    slot_start_at: str = factories.STANDARD_SLOT_START,
    completion_clock: str = factories.STANDARD_COMPLETION_CLOCK,
) -> dict:
    """Full ASSESSMENT path: create attempt -> book -> advance clock ->
    complete with earned_score. Returns {"submission": ..., "booking": ...}."""
    submission = create_submission(cycle_id, candidate, component_code)
    booking = create_booking_for_assessment(cycle_id, candidate, center_id, slot_start_at)
    booking = complete_booking(booking["id"], earned_score, completion_clock)
    submission = get_success_data(api_client.get_submission(submission["id"], BOARD))
    return {"submission": submission, "booking": booking}


# ---------------------------------------------------------------------------
# Tier 4: certification / retake / renewal / stipend composites
# ---------------------------------------------------------------------------
def get_certification_for(candidate_id: str, cycle_id: str) -> dict:
    """Reverse-reach the single Certification of a (candidate, cycle) pair."""
    rows = get_success_data(
        api_client.list_certifications(
            BOARD, params={"candidate_id": candidate_id, "cycle_id": cycle_id}
        )
    )
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one certification for ({candidate_id}, {cycle_id}), got {rows}"
    )
    return rows[0]


def retake_submission(submission_id: str, candidate: dict) -> dict:
    """Open the next attempt of a SCORED submission. Returns the new attempt
    (IN_PROGRESS, attempt_number incremented, prior_submission_id linked)."""
    return get_success_data(
        api_client.retake_submission(submission_id, make_candidate_headers(candidate["id"]))
    )


def create_fully_scored_scenario(
    scores: Optional[Dict[str, float]] = None,
    candidate_overrides: Optional[dict] = None,
    cycle_overrides: Optional[dict] = None,
    programs: Optional[List[dict]] = None,
    num_assessors: int = 2,
    clock: Optional[str] = factories.STANDARD_WORK_CLOCK,
    slot_start_at: str = factories.STANDARD_SLOT_START,
    completion_clock: str = factories.STANDARD_COMPLETION_CLOCK,
) -> dict:
    """The standard end-to-end pipeline: open cycle, ELIGIBLE candidate, two
    ACTIVE assessors, center, optional incentive programs created BEFORE the
    final component is scored (so stipend auto-proposal fires on CERTIFIED),
    then every component of the cycle scored — ASSESSMENT via booking
    completion, PORTFOLIO via agreeing read pairs.

    Default scores (CKA 3.00, P1 2.50, P2 1.50, P3 2.00 on the standard
    0.40/0.20/0.20/0.20 cycle) produce weighted_total_final 2.40 >= 1.75, so
    the certification is decided CERTIFIED at completion_clock.

    Returns a dict: cycle, candidate, benchmark, assessors, center, programs,
    submissions (component_code -> SCORED attempt), certification.
    """
    if scores is None:
        scores = {"CKA": 3.00, "P1": 2.50, "P2": 1.50, "P3": 2.00}
    candidate_overrides = candidate_overrides or {}
    cycle_overrides = cycle_overrides or {}

    cycle = create_open_cycle(clock=clock, **cycle_overrides)
    candidate = create_eligible_candidate(**candidate_overrides)
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=num_assessors)
    center = create_assessment_center()
    created_programs = [
        get_success_data(api_client.create_incentive_program(p, INCENTIVE_ADMIN))
        for p in (programs or [])
    ]

    submissions: Dict[str, dict] = {}
    component_kinds = {c["code"]: c["kind"] for c in cycle["components"]}
    for component_code, score in scores.items():
        if component_kinds[component_code] == "ASSESSMENT":
            result = score_assessment_component(
                cycle["id"], candidate, center["id"],
                component_code=component_code, earned_score=score,
                slot_start_at=slot_start_at, completion_clock=completion_clock,
            )
            submissions[component_code] = result["submission"]
        else:
            submission = create_portfolio_submission_in_state(
                cycle["id"], candidate, component_code, state="SCORING"
            )
            submissions[component_code] = score_portfolio_with_agreeing_reads(
                submission["id"], assessors[0], assessors[1], score
            )

    certification = get_certification_for(candidate["id"], cycle["id"])
    return {
        "cycle": cycle,
        "candidate": candidate,
        "benchmark": benchmark,
        "assessors": assessors,
        "center": center,
        "programs": created_programs,
        "submissions": submissions,
        "certification": certification,
    }


def create_certified_scenario(**kwargs) -> dict:
    """create_fully_scored_scenario specialized to a CERTIFIED outcome; the
    default arguments land at weighted_total_final 2.40 >= threshold 1.75."""
    scenario = create_fully_scored_scenario(**kwargs)
    assert scenario["certification"]["status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {scenario['certification']['status']} "
        f"(total {scenario['certification'].get('weighted_total_final')})"
    )
    return scenario


def create_proposed_stipend_scenario(
    program_overrides: Optional[dict] = None, **scenario_kwargs
) -> dict:
    """A certified scenario with exactly one OPEN incentive program in place
    before the decision, so exactly one PROPOSED stipend auto-proposes.
    Returns the scenario dict augmented with "program" and "stipend"."""
    program_payload = factories.create_incentive_program_payload(**(program_overrides or {}))
    scenario = create_certified_scenario(programs=[program_payload], **scenario_kwargs)
    program = scenario["programs"][0]
    stipends = get_success_data(
        api_client.list_certification_stipends(scenario["certification"]["id"], INCENTIVE_ADMIN)
    )
    assert len(stipends) == 1, f"expected exactly one auto-proposed stipend, got {len(stipends)}"
    scenario["program"] = program
    scenario["stipend"] = stipends[0]
    return scenario


def create_renewal(
    certification_id: str,
    candidate: dict,
    evidence_items=None,
    total_hours: float = 45.0,
) -> dict:
    """File a renewal application as the owning candidate."""
    return get_success_data(
        api_client.create_renewal(
            certification_id,
            factories.create_renewal_payload(evidence_items, total_hours),
            make_candidate_headers(candidate["id"]),
        )
    )


def review_renewal(renewal_id: str, decision: str = "APPROVE", note=None) -> dict:
    """Board review of a renewal application."""
    return get_success_data(
        api_client.review_renewal(
            renewal_id, factories.review_renewal_payload(decision, note), BOARD
        )
    )
