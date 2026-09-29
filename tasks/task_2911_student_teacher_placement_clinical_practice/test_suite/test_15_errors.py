"""Every error the catalogue declares, raised from the state that owns it.

Each test drives one refusal and then proves two things: that the code returned
is the specific one the ladder assigns to that failure rather than a neighbouring
or generic code, and that the refused call left no trace — no row created, no
counter moved, no money on the ledger.
"""
from test_helpers import (
    ASSESSMENT_SCORER,
    CREDENTIAL_ANALYST,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_ASSESSMENT_ALREADY_EXISTS,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_ASSESSMENT_NOT_PASSED,
    ERR_ASSESSMENT_STATE_INVALID,
    ERR_CANDIDATE_CODE_TAKEN,
    ERR_COMPLETION_GATE_UNMET,
    ERR_CYCLE_NOT_FOUND,
    ERR_CYCLE_STATE_INVALID,
    ERR_DISTRICT_CODE_TAKEN,
    ERR_DISTRICT_NOT_FOUND,
    ERR_INVALID_WINDOW,
    ERR_LICENSURE_NOT_RECOMMENDED,
    ERR_NO_COMPLETER_RECORD,
    ERR_PLACEMENT_NOT_FOUND,
    ERR_READINESS_ITEM_NOT_FOUND,
    ERR_REQUEST_NOT_FOUND,
    ERR_RESCHEDULE_LIMIT_REACHED,
    ERR_REROUTE_LIMIT_REACHED,
    ERR_SCORE_PAYLOAD_INVALID,
    ERR_STIPEND_STATE_INVALID,
    ERR_SUBMISSION_WINDOW_CLOSED,
    ERR_SUPERVISOR_NOT_FOUND,
    ERR_TEACHER_DISQUALIFIED,
    ERR_TEACHER_NOT_FOUND,
    ERR_TEACHER_NOT_QUALIFIED,
    ERR_TERM_NOT_ENDED,
    NON_EXISTENT_UUID,
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    SETTLEMENT_CLOCK,
    SUBMISSION_CLOCK,
    SUPERVISION_LEAD,
    add_teacher,
    assert_agreement_ledger,
    assert_instant_equals,
    assert_placement_dimensions,
    assert_ratio_equals,
    complete_cycle,
    factories as f,
    open_assessment,
    open_request,
    read_agreement,
    read_assessment,
    read_candidate,
    read_cycle,
    read_placement,
    read_request,
    read_teacher,
    route,
    schedule_cycle,
    set_clock,
    setup_active_placement,
    setup_bench,
    setup_observed_placement,
    setup_proposed_placement,
    setup_ready_candidate,
    setup_scheduled_cycles,
    submit_assessment,
    validate_error,
    validate_page,
    validate_success,
)

TAKEN_CANDIDATE_CODE = "C-1001"
TAKEN_DISTRICT_CODE = "D-RIDGE"
INVERTED_WINDOW = {"window_start": "2027-01-31", "window_end": "2026-08-01"}
SECOND_WINDOW = {"window_opens_at": "2026-11-05T00:00:00Z",
                 "window_closes_at": "2026-11-30T00:00:00Z"}
EARLY_CLOSING_WINDOW = {"window_closes_at": "2026-11-10T00:00:00Z"}
FIRST_CYCLE = (1, "FORMATIVE", "2026-09-14T00:00:00Z", "2026-09-19T00:00:00Z")
LEGAL_SECOND_WINDOW = ("2026-10-05T00:00:00Z", "2026-10-10T00:00:00Z")
THIRD_WINDOW = ("2026-10-19T00:00:00Z", "2026-10-24T00:00:00Z")
FOURTH_WINDOW = ("2026-11-02T00:00:00Z", "2026-11-07T00:00:00Z")
OFF_GRID_SCORE = {"task_planning": 4.2}
SECOND_SITE = {"site_grid_x": 10, "site_grid_y": 11, "years_experience": 6}
FIRST_OBSERVATION = "2026-09-16T15:00:00Z"
SECOND_OBSERVATION = "2026-10-06T15:00:00Z"
PROVISIONAL_GROSS_CENTS = 181468


def test_each_unknown_path_id_answers_with_its_own_not_found_code(api):
    """Nine reads, nine entity-specific 404s, and never a generic one.

    PRD §2.6 rung 5: "Every id embedded in the URL path exists, validated left to
    right; the first missing resource decides the error, which is that entity's
    own 404 code — `ERR_CANDIDATE_NOT_FOUND`, `ERR_READINESS_ITEM_NOT_FOUND`,
    `ERR_DISTRICT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TEACHER_NOT_FOUND`,
    `ERR_SUPERVISOR_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_PLACEMENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` or
    `ERR_ASSESSMENT_NOT_FOUND` (all 404).

    Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found_codes
    """
    reads = (
        (api.get_district(NON_EXISTENT_UUID, PROGRAM_ADMIN),
         ERR_DISTRICT_NOT_FOUND),
        (api.get_agreement(NON_EXISTENT_UUID, PROGRAM_ADMIN),
         ERR_AGREEMENT_NOT_FOUND),
        (api.get_teacher(NON_EXISTENT_UUID, SUPERVISION_LEAD),
         ERR_TEACHER_NOT_FOUND),
        (api.get_supervisor(NON_EXISTENT_UUID, SUPERVISION_LEAD),
         ERR_SUPERVISOR_NOT_FOUND),
        (api.get_placement_request(NON_EXISTENT_UUID, PLACEMENT_COORDINATOR),
         ERR_REQUEST_NOT_FOUND),
        (api.get_placement(NON_EXISTENT_UUID, PLACEMENT_COORDINATOR),
         ERR_PLACEMENT_NOT_FOUND),
        (api.get_observation_cycle(NON_EXISTENT_UUID, SUPERVISION_LEAD),
         ERR_CYCLE_NOT_FOUND),
        (api.get_performance_assessment(NON_EXISTENT_UUID, ASSESSMENT_SCORER),
         ERR_ASSESSMENT_NOT_FOUND),
        (api.get_readiness_item(NON_EXISTENT_UUID, CREDENTIAL_ANALYST),
         ERR_READINESS_ITEM_NOT_FOUND),
    )

    for response, error_id in reads:
        error = validate_error(response, error_id, 404)
        assert error["message"], f"{error_id} carries a human-readable message"


def test_a_second_candidate_cannot_take_a_used_candidate_code(api):
    """Every other field differs and the code alone decides the answer.

    PRD §3.1: "The `candidate_code` is a non-empty string of 1 to 32 characters
    and must be unique, case-sensitively, across every candidate on file; a
    collision is refused with `ERR_CANDIDATE_CODE_TAKEN`."

    Design: Corner/errors/a_duplicate_candidate_code_is_rejected
    """
    first = validate_success(api.create_candidate(
        f.candidate_payload(candidate_code=TAKEN_CANDIDATE_CODE,
                            full_name="Ana Diaz"), PROGRAM_ADMIN), 201)

    validate_error(api.create_candidate(
        f.candidate_payload(candidate_code=TAKEN_CANDIDATE_CODE,
                            full_name="Ben Okafor", program_track="ELEMENTARY",
                            home_grid_x=7, home_grid_y=7), PROGRAM_ADMIN),
        ERR_CANDIDATE_CODE_TAKEN, 409)

    rows, meta = validate_page(api.list_candidates(PROGRAM_ADMIN))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["full_name"] == "Ana Diaz"


def test_a_second_district_cannot_take_a_used_district_code(api):
    """A different name and a different state do not free the code.

    PRD §3.3: "a `district_code` of 1 to 32 characters that must be unique across
    all districts (a collision is refused with `ERR_DISTRICT_CODE_TAKEN`)"

    Design: Corner/errors/a_duplicate_district_code_is_rejected
    """
    validate_success(api.create_district(
        f.district_payload(district_code=TAKEN_DISTRICT_CODE,
                           name="Ridgeview ISD", state_code="TX"),
        PROGRAM_ADMIN), 201)

    validate_error(api.create_district(
        f.district_payload(district_code=TAKEN_DISTRICT_CODE,
                           name="Ridgeview Charter Network", state_code="NM"),
        PROGRAM_ADMIN), ERR_DISTRICT_CODE_TAKEN, 409)

    rows, meta = validate_page(api.list_districts(PROGRAM_ADMIN))
    assert meta["total_count"] == 1
    assert rows[0]["state_code"] == "TX"


def test_an_agreement_window_that_runs_backwards_is_refused(api):
    """Two well-formed dates in the wrong order are a 422, not a 400.

    PRD §2.6 rung 8: "Interval inputs are well formed: an agreement's
    `window_start` is strictly earlier than its `window_end` ... — otherwise
    `ERR_INVALID_WINDOW` (422)."

    Design: Corner/errors/an_inverted_agreement_window_is_rejected
    """
    district = validate_success(
        api.create_district(f.district_payload(), PROGRAM_ADMIN), 201)

    validate_error(api.create_agreement(
        f.agreement_payload(district["id"], **INVERTED_WINDOW), PROGRAM_ADMIN),
        ERR_INVALID_WINDOW, 422)

    _rows, meta = validate_page(api.list_agreements(PROGRAM_ADMIN))
    assert meta["total_count"] == 0


def test_a_placement_may_own_only_one_performance_assessment(api):
    """The second window is legal in itself and still has nowhere to live.

    PRD §2.6 rung 11: "A placement has at most one performance assessment —
    otherwise `ERR_ASSESSMENT_ALREADY_EXISTS` (409)."

    Design: Corner/errors/a_second_assessment_for_one_placement_is_rejected
    """
    scenario = setup_active_placement(api)
    scenario.assessment = open_assessment(api, scenario.placement_id)

    validate_error(api.create_performance_assessment(
        f.assessment_payload(scenario.placement_id, **SECOND_WINDOW),
        ASSESSMENT_SCORER), ERR_ASSESSMENT_ALREADY_EXISTS, 409)

    _rows, meta = validate_page(api.list_performance_assessments(
        ASSESSMENT_SCORER, {"placement_id": scenario.placement_id}))
    assert meta["total_count"] == 1
    survivor = read_assessment(api, scenario.assessment_id)
    assert_instant_equals(survivor["window_opens_at"], "2026-11-01T00:00:00Z",
                          "window_opens_at")
    assert survivor["status"] == "OPEN"


def test_rescheduling_a_cycle_that_is_still_scheduled_is_rejected(api):
    """The proposed window is legal; the cycle is simply not MISSED yet.

    PRD §2.6 rung 20: "The observation cycle is `SCHEDULED` for a completion and
    `MISSED` for a reschedule; a `CANCELLED_HOLD` cycle admits neither —
    otherwise `ERR_CYCLE_STATE_INVALID` (409)."

    Design: Corner/errors/rescheduling_a_still_scheduled_cycle_is_rejected
    """
    scenario = setup_active_placement(api)
    cycle = schedule_cycle(api, scenario.placement_id, *FIRST_CYCLE)

    validate_error(api.reschedule_observation_cycle(
        cycle["id"], f.cycle_reschedule_payload(*LEGAL_SECOND_WINDOW),
        SUPERVISION_LEAD), ERR_CYCLE_STATE_INVALID, 409)

    refused = read_cycle(api, cycle["id"])
    assert refused["status"] == "SCHEDULED"
    assert refused["reschedule_count"] == 0
    assert_instant_equals(refused["window_start"], FIRST_CYCLE[2],
                          "window_start")
    assert_instant_equals(refused["window_end"], FIRST_CYCLE[3], "window_end")


def test_the_third_reschedule_of_one_cycle_is_rejected(api):
    """Two lapses may be forgiven; the third is refused on the counter alone.

    PRD §2.6 rung 37: "`reschedule_count` is strictly below 2 — otherwise
    `ERR_RESCHEDULE_LIMIT_REACHED` (409)."

    Design: Corner/errors/the_third_reschedule_of_one_cycle_is_rejected
    """
    scenario = setup_active_placement(api)
    cycle = schedule_cycle(api, scenario.placement_id, *FIRST_CYCLE)
    set_clock(api, "2026-09-20T00:00:00Z")
    validate_success(api.reschedule_observation_cycle(
        cycle["id"], f.cycle_reschedule_payload(*LEGAL_SECOND_WINDOW),
        SUPERVISION_LEAD))
    set_clock(api, "2026-10-11T00:00:00Z")
    validate_success(api.reschedule_observation_cycle(
        cycle["id"], f.cycle_reschedule_payload(*THIRD_WINDOW),
        SUPERVISION_LEAD))
    set_clock(api, "2026-10-25T00:00:00Z")
    before = read_cycle(api, cycle["id"])
    assert before["status"] == "MISSED", "the third lapse is genuine"
    assert before["reschedule_count"] == 2

    validate_error(api.reschedule_observation_cycle(
        cycle["id"], f.cycle_reschedule_payload(*FOURTH_WINDOW),
        SUPERVISION_LEAD), ERR_RESCHEDULE_LIMIT_REACHED, 409)

    refused = read_cycle(api, cycle["id"])
    assert refused["status"] == "MISSED"
    assert refused["reschedule_count"] == 2
    assert_instant_equals(refused["window_start"], THIRD_WINDOW[0],
                          "window_start")
    assert_instant_equals(refused["window_end"], THIRD_WINDOW[1], "window_end")
    assert_ratio_equals(
        read_placement(api, scenario.placement_id)["observation_compliance_ratio"],
        0.0)


def test_the_third_reroute_of_one_request_is_rejected(api):
    """The counter answers before the empty-pool check ever runs.

    PRD §2.6 rung 36: "`reroute_count` is strictly below 2 — otherwise
    `ERR_REROUTE_LIMIT_REACHED` (409)."  PRD §3.5: "it requires `reroute_count`
    to be strictly below 2 — a third attempt is refused with
    `ERR_REROUTE_LIMIT_REACHED` ... When `exclude_current_teacher` is true the
    voided placement's `cooperating_teacher_id` is appended to
    `excluded_cooperating_teacher_ids`; when it is false or omitted, that teacher
    may win again."

    Design: Corner/errors/the_third_reroute_of_one_request_is_rejected
    """
    scenario = setup_bench(api)
    add_teacher(api, scenario, **SECOND_SITE)
    setup_ready_candidate(api, scenario=scenario)
    scenario.request = open_request(api, scenario.candidate_id,
                                   preferred_district_id=scenario.district_id)
    scenario.placement = route(api, scenario.request_id)
    for _attempt in (1, 2):
        version = read_request(api, scenario.request_id)["version"]
        scenario.placement = validate_success(api.reroute_request(
            scenario.request_id,
            f.reroute_payload(version, exclude_current_teacher=False),
            PLACEMENT_COORDINATOR), 201)
    before = read_request(api, scenario.request_id)
    assert before["reroute_count"] == 2
    assert before["routing_round"] == 1, "a reroute never advances the round"
    assert before["status"] == "ROUTED"

    validate_error(api.reroute_request(
        scenario.request_id, f.reroute_payload(before["version"],
                                               exclude_current_teacher=False),
        PLACEMENT_COORDINATOR), ERR_REROUTE_LIMIT_REACHED, 409)

    rows, meta = validate_page(api.list_placements(
        PLACEMENT_COORDINATOR, {"request_id": scenario.request_id}))
    assert meta["total_count"] == 3
    voided = [row for row in rows if row["placement_status"] == "VOIDED"]
    assert len(voided) == 2
    assert all(row["voided_reason"] == "REROUTED" for row in voided)
    assert [row["placement_status"] for row in rows].count("PROPOSED") == 1
    after = read_request(api, scenario.request_id)
    assert after["current_placement_id"] == scenario.placement_id
    assert after["reroute_count"] == 2
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0)


def test_scoring_an_assessment_that_was_never_submitted_is_rejected(api):
    """A perfectly formed rubric cannot be applied to an OPEN assessment.

    PRD §2.6 rung 21: "The performance assessment is `OPEN` or `RETURNED` for a
    submission and `SUBMITTED` for a scoring decision — otherwise
    `ERR_ASSESSMENT_STATE_INVALID` (409)."

    Design: Corner/errors/scoring_an_unsubmitted_assessment_is_rejected
    """
    scenario = setup_active_placement(api)
    scenario.assessment = open_assessment(api, scenario.placement_id)

    validate_error(api.score_assessment(
        scenario.assessment_id, f.assessment_score_payload(), ASSESSMENT_SCORER),
        ERR_ASSESSMENT_STATE_INVALID, 409)

    assessment = read_assessment(api, scenario.assessment_id)
    assert assessment["status"] == "OPEN"
    assert assessment["attempt_no"] == 0
    assert assessment["total_score"] == 0
    assert read_placement(api, scenario.placement_id)["placement_status"] == (
        "ACTIVE"), "a refused scoring attempt has no clinical side effect"


def test_a_rubric_score_off_the_half_point_grid_is_rejected(api):
    """4.2 is inside the range and off the grid, so the code is semantic.

    PRD §2.6 rung 39: "A scoring decision carries all four rubric dimension
    scores as multiples of 0.5 inside the range 1.0 through 5.0, and a return
    decision carries `returned_feedback` and no scores — otherwise
    `ERR_SCORE_PAYLOAD_INVALID` (422)."

    Design: Corner/errors/a_rubric_score_off_the_half_point_grid_is_rejected
    """
    scenario = setup_observed_placement(api)
    scenario.assessment = open_assessment(api, scenario.placement_id)
    set_clock(api, SUBMISSION_CLOCK)
    scenario.assessment = submit_assessment(api, scenario.assessment_id,
                                            scenario.candidate_id)

    validate_error(api.score_assessment(
        scenario.assessment_id, f.assessment_score_payload(**OFF_GRID_SCORE),
        ASSESSMENT_SCORER), ERR_SCORE_PAYLOAD_INVALID, 422)

    assessment = read_assessment(api, scenario.assessment_id)
    assert assessment["status"] == "SUBMITTED"
    assert assessment["attempt_no"] == 1
    assert assessment["total_score"] == 0
    placement = read_placement(api, scenario.placement_id)
    assert placement["placement_status"] == "ACTIVE"
    assert_ratio_equals(placement["observation_compliance_ratio"], 1.0)


def test_submitting_after_the_window_closes_is_rejected(api):
    """A perfect compliance record does not reopen a closed window.

    PRD §2.6 rung 34: "The submission instant is inside the assessment's
    closed-closed window from `window_opens_at` through `window_closes_at`,
    including any resubmission grace extension already applied — otherwise
    `ERR_SUBMISSION_WINDOW_CLOSED` (422)."

    Design: Corner/errors/submitting_after_the_window_closes_is_rejected
    """
    scenario = setup_observed_placement(api)
    scenario.assessment = open_assessment(api, scenario.placement_id,
                                          **EARLY_CLOSING_WINDOW)

    validate_error(api.submit_assessment(
        scenario.assessment_id, f.assessment_submit_payload(),
        scenario.candidate_headers), ERR_SUBMISSION_WINDOW_CLOSED, 422)

    assert_ratio_equals(
        read_placement(api, scenario.placement_id)["observation_compliance_ratio"],
        1.0)
    assessment = read_assessment(api, scenario.assessment_id)
    assert assessment["status"] == "OPEN"
    assert assessment["attempt_no"] == 0
    assert assessment["submitted_at"] is None


def test_clawing_back_a_stipend_that_was_never_paid_is_rejected(api):
    """CLAWED_BACK has exactly one predecessor, and ACCRUED is not it.

    PRD §2.6 rung 18: "The requested `stipend_status` move is one the money
    dimension declares — `ACCRUED` to `APPROVED`, `APPROVED` to `PAID`, `ACCRUED`
    or `APPROVED` to `VOIDED`, `PAID` to `CLAWED_BACK` — otherwise
    `ERR_STIPEND_STATE_INVALID` (409)."

    Design: Corner/errors/clawing_back_an_accrued_stipend_is_rejected
    """
    scenario = setup_active_placement(api)

    validate_error(api.transition_stipend(
        scenario.placement_id,
        f.stipend_transition_payload("CLAWED_BACK",
                                     note="A clawback before any payment."),
        PROGRAM_ADMIN), ERR_STIPEND_STATE_INVALID, 409)

    placement = read_placement(api, scenario.placement_id)
    assert placement["stipend_status"] == "ACCRUED"
    assert placement["stipend_gross_cents"] == PROVISIONAL_GROSS_CENTS
    assert placement["weeks_credited"] == 14
    assert read_agreement(api, scenario.agreement_id)[
        "stipend_committed_cents"] == PROVISIONAL_GROSS_CENTS


def test_confirming_a_placement_whose_teacher_was_disqualified_is_rejected(api):
    """The proposal survives the disqualification and can never be activated.

    PRD §2.6 rung 26: "The cooperating teacher's `qualification_status` is
    `QUALIFIED` — neither `PENDING_TRAINING` nor `DISQUALIFIED` — at confirmation
    time; otherwise `ERR_TEACHER_NOT_QUALIFIED` (422)."

    Design: Corner/errors/confirming_with_a_disqualified_teacher_is_rejected
    """
    scenario = setup_proposed_placement(api)
    validate_success(api.disqualify_teacher(
        scenario.teacher_id,
        f.disqualify_payload("Substantiated supervision complaint."),
        SUPERVISION_LEAD))

    validate_error(api.confirm_placement(scenario.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_TEACHER_NOT_QUALIFIED, 422)

    teacher = read_teacher(api, scenario.teacher_id)
    assert teacher["qualification_status"] == "DISQUALIFIED"
    assert teacher["active_placement_count"] == 1, (
        "the PROPOSED placement was not voided by the disqualification")
    assert_placement_dimensions(read_placement(api, scenario.placement_id),
                                "PROPOSED", "NOT_ACCRUED")
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0)


def test_approving_a_stipend_for_a_disqualified_teacher_is_rejected(api):
    """The money edge itself is legal; the teacher check stops it.

    PRD §2.6 rung 27: "A stipend is not approved or paid for a cooperating
    teacher whose `qualification_status` is `DISQUALIFIED` — otherwise
    `ERR_TEACHER_DISQUALIFIED` (422)."

    Design: Corner/errors/approving_a_stipend_for_a_disqualified_teacher_is_rejected
    """
    scenario = setup_active_placement(api)
    validate_success(api.disqualify_teacher(
        scenario.teacher_id,
        f.disqualify_payload("Site safety finding after the term started."),
        PROGRAM_ADMIN))

    validate_error(api.transition_stipend(
        scenario.placement_id,
        f.stipend_transition_payload("APPROVED",
                                     note="Routine mid-term approval."),
        PROGRAM_ADMIN), ERR_TEACHER_DISQUALIFIED, 422)

    placement = read_placement(api, scenario.placement_id)
    assert placement["stipend_status"] == "ACCRUED", "never ERR_STIPEND_STATE_INVALID"
    assert placement["stipend_gross_cents"] == PROVISIONAL_GROSS_CENTS
    assert placement["placement_status"] == "ACTIVE"
    assert read_agreement(api, scenario.agreement_id)[
        "stipend_committed_cents"] == PROVISIONAL_GROSS_CENTS


def test_scheduling_a_cycle_under_a_suspended_agreement_is_rejected(api):
    """Suspension freezes new clinical work and leaves the running term alone.

    PRD §2.6 rung 15: "The partnership agreement backing the placement is
    `ACTIVE` both when a placement is confirmed and whenever new clinical work is
    scheduled against an already-active placement — otherwise
    `ERR_AGREEMENT_NOT_ACTIVE` (409). Applies to placement confirmation,
    observation-cycle scheduling and performance-assessment creation. A suspended
    or terminated agreement leaves running placements in place but freezes
    further scheduling under it."

    Design: Corner/errors/scheduling_a_cycle_under_a_suspended_agreement_is_rejected
    """
    scenario = setup_active_placement(api)
    validate_success(api.suspend_agreement(
        scenario.agreement_id,
        f.suspend_payload("District-wide audit of clinical sites."),
        PROGRAM_ADMIN))

    validate_error(api.create_observation_cycle(
        f.observation_cycle_payload(scenario.placement_id), SUPERVISION_LEAD),
        ERR_AGREEMENT_NOT_ACTIVE, 409)

    agreement = read_agreement(api, scenario.agreement_id)
    assert agreement["status"] == "SUSPENDED", "never ERR_AGREEMENT_EXPIRED"
    assert agreement["seats_committed"] == 1
    assert_placement_dimensions(read_placement(api, scenario.placement_id),
                                "ACTIVE", "ACCRUED")
    _rows, meta = validate_page(api.list_observation_cycles(
        SUPERVISION_LEAD, {"placement_id": scenario.placement_id}))
    assert meta["total_count"] == 0


def test_completing_a_placement_before_the_term_ends_is_rejected(api):
    """The calendar gate answers first, with the clock still in August.

    PRD §2.6 rung 40: "The current logical-clock date is on or after the
    placement's `end_date` before the placement may be completed — otherwise
    `ERR_TERM_NOT_ENDED` (422)."

    Design: Corner/errors/completing_before_the_term_end_date_is_rejected
    """
    scenario = setup_active_placement(api)

    validate_error(api.complete_placement(
        scenario.placement_id, f.complete_placement_payload(),
        PLACEMENT_COORDINATOR), ERR_TERM_NOT_ENDED, 422)

    placement = read_placement(api, scenario.placement_id)
    assert placement["placement_status"] == "ACTIVE"
    assert placement["stipend_variant"] == "PROVISIONAL"
    assert placement["completed_at"] is None
    assert read_request(api, scenario.request_id)["status"] == "MATCHED", (
        "the request is not CLOSED by a refused completion")


def test_completing_with_an_incomplete_observation_record_is_rejected(api):
    """The calendar is satisfied and the observation record is not.

    PRD §2.6 rung 41: "The placement's `observation_compliance_ratio` is exactly
    1.0 and its `summative_completed_count` is at least 1 at completion time —
    otherwise `ERR_COMPLETION_GATE_UNMET` (422)."

    Design: Corner/errors/completing_with_an_incomplete_observation_record_is_rejected
    """
    scenario = setup_active_placement(api)
    setup_scheduled_cycles(api, scenario)
    complete_cycle(api, scenario.cycles[0]["id"], scenario.supervisor_id,
                   FIRST_OBSERVATION)
    complete_cycle(api, scenario.cycles[1]["id"], scenario.supervisor_id,
                   SECOND_OBSERVATION)
    set_clock(api, SETTLEMENT_CLOCK)

    validate_error(api.complete_placement(
        scenario.placement_id, f.complete_placement_payload(),
        PLACEMENT_COORDINATOR), ERR_COMPLETION_GATE_UNMET, 422)

    assert read_cycle(api, scenario.cycles[2]["id"])["status"] == "MISSED"
    placement = read_placement(api, scenario.placement_id)
    assert_ratio_equals(placement["observation_compliance_ratio"], 0.6667)
    assert placement["summative_completed_count"] == 0
    assert placement["placement_status"] == "ACTIVE"
    assert placement["stipend_variant"] == "PROVISIONAL"


def test_completing_without_any_performance_assessment_is_rejected(api):
    """A flawless observation record still leaves the last gate unmet.

    PRD §2.6 rung 42: "The placement's performance assessment exists and is
    `PASSED` at completion time — otherwise `ERR_ASSESSMENT_NOT_PASSED` (422)."

    Design: Corner/errors/completing_without_a_passed_assessment_is_rejected
    """
    scenario = setup_observed_placement(api)
    set_clock(api, SETTLEMENT_CLOCK)

    validate_error(api.complete_placement(
        scenario.placement_id, f.complete_placement_payload(),
        PLACEMENT_COORDINATOR), ERR_ASSESSMENT_NOT_PASSED, 422)

    placement = read_placement(api, scenario.placement_id)
    assert_ratio_equals(placement["observation_compliance_ratio"], 1.0)
    assert placement["summative_completed_count"] == 1, "rung 41 was satisfied"
    _rows, meta = validate_page(api.list_performance_assessments(
        ASSESSMENT_SCORER, {"placement_id": scenario.placement_id}))
    assert meta["total_count"] == 0
    assert placement["placement_status"] == "ACTIVE"
    assert placement["stipend_variant"] == "PROVISIONAL"
    assert placement["settlement_date"] is None


def test_recommending_a_candidate_who_completed_nothing_is_rejected(api):
    """Being READY is not being a completer.

    PRD §2.6 rung 47: "A `RECOMMENDED` licensure decision requires at least one
    `COMPLETED` placement for the candidate, whose performance assessment is
    `PASSED`, and a `ROLLING` `readiness_status` of `READY` ... otherwise
    `ERR_NO_COMPLETER_RECORD` (422)."

    Design: Corner/errors/recommending_a_candidate_with_no_completed_placement_is_rejected
    """
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario)

    validate_error(api.recommend_licensure(
        scenario.candidate_id, f.licensure_payload(), PROGRAM_ADMIN),
        ERR_NO_COMPLETER_RECORD, 422)

    candidate = read_candidate(api, scenario.candidate_id)
    assert candidate["licensure_status"] == "PENDING"
    assert candidate["recommended_by_user_id"] is None
    assert candidate["recommended_at"] is None
    assert candidate["readiness_status"] == "READY"
    assert candidate["readiness_score"] == 90, (
        "readiness alone does not make a completer")
    _rows, meta = validate_page(api.list_placements(
        PLACEMENT_COORDINATOR, {"candidate_id": scenario.candidate_id}))
    assert meta["total_count"] == 0


def test_filing_a_state_report_before_the_recommendation_is_rejected(api):
    """No recommendation means no deadline, and no deadline means no report.

    PRD §2.6 rung 48: "A state report requires `licensure_status` equal to
    `RECOMMENDED`, `report_status` equal to `UNREPORTED` and a non-null
    `state_report_deadline` — otherwise `ERR_LICENSURE_NOT_RECOMMENDED` (422)."

    Design: Corner/errors/filing_a_state_report_before_the_recommendation_is_rejected
    """
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario)

    validate_error(api.file_state_report(
        scenario.candidate_id, f.state_report_payload("2026-2027-FALL"),
        PROGRAM_ADMIN), ERR_LICENSURE_NOT_RECOMMENDED, 422)

    candidate = read_candidate(api, scenario.candidate_id)
    assert candidate["report_status"] == "UNREPORTED"
    assert candidate["reported_by_user_id"] is None, (
        "never ERR_SEGREGATION_OF_DUTIES: recommended_by_user_id is null")
    assert candidate["reporting_cycle"] is None
    assert candidate["state_report_deadline"] is None
