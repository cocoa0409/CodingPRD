"""The role model: exclusive operations, shared ones and identity-keyed rules.

Authorisation in this contract has four distinct layers, and each test isolates
one of them: the role list on an endpoint, the resource-owner rule for the two
entity-backed roles, authentication itself, and the segregation-of-duties rule
that keys on the acting user id rather than on the role. Every denial is paired
with the same call succeeding under the correct principal, so the test proves the
role was the only thing that differed.
"""
from test_helpers import (
    CREDENTIAL_ANALYST,
    DUAL_ROLE_USER_ID,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    SUBMISSION_CLOCK,
    SUPERVISION_LEAD,
    SUPERVISION_LEAD_USER_ID,
    UserRole,
    assert_caseload,
    assert_ratio_equals,
    factories as f,
    make_candidate_headers,
    make_headers,
    open_assessment,
    read_assessment,
    read_cycle,
    read_placement,
    read_supervisor,
    schedule_cycle,
    set_clock,
    setup_active_placement,
    setup_bench,
    setup_ready_candidate,
    validate_error,
    validate_page,
    validate_success,
)

BLANK_USER_ID = ""
FIRST_CYCLE = (1, "FORMATIVE", "2026-09-14T00:00:00Z", "2026-09-19T00:00:00Z")
SECOND_HOME = {"home_grid_y": 5}
SITE_WITHDRAWAL = {"removal_reason": "DISTRICT_REQUEST",
                   "removal_narrative": "The campus withdrew the offer."}
PROVISIONAL_GROSS_CENTS = 181468
REMOVAL_PENDING_POINTS = 4


def test_a_credential_analyst_cannot_open_a_placement_request(api):
    """The analyst who verified the evidence still cannot use it.

    PRD §2.6 rung 3: "The acting role appears in the target endpoint's
    authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every
    endpoint."  PRD §4 lists `POST /epp/placement-requests` as authorised for
    `PlacementCoordinator` alone.

    Design: Corner/rbac/a_credential_analyst_cannot_create_a_placement_request
    """
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario)
    payload = f.placement_request_payload(
        scenario.candidate_id, preferred_district_id=scenario.district_id)

    validate_error(api.create_placement_request(payload, CREDENTIAL_ANALYST),
                   ERR_UNAUTHORIZED, 403)

    _rows, meta = validate_page(api.list_placement_requests(
        PLACEMENT_COORDINATOR, {"candidate_id": scenario.candidate_id}))
    assert meta["total_count"] == 0
    allowed = validate_success(
        api.create_placement_request(payload, PLACEMENT_COORDINATOR), 201)
    assert allowed["candidate_id"] == scenario.candidate_id, (
        "the identical payload succeeds, so only the role differed")


def test_a_program_admin_may_open_the_assessment_window_but_not_score_it(api):
    """One role, two endpoints on the same row, two different answers.

    PRD §2.6 rung 3: "The acting role appears in the target endpoint's
    authorized-role list — otherwise `ERR_UNAUTHORIZED` (403)."  PRD §4 authorises
    `POST /epp/performance-assessments` for `AssessmentScorer`, `ProgramAdmin` but
    `POST /epp/performance-assessments/{assessment_id}/score` for
    `AssessmentScorer` alone.

    Design: Corner/rbac/a_program_admin_cannot_score_a_performance_assessment
    """
    scenario = setup_active_placement(api)
    scenario.assessment = validate_success(api.create_performance_assessment(
        f.assessment_payload(scenario.placement_id), PROGRAM_ADMIN), 201)

    validate_error(api.score_assessment(
        scenario.assessment_id, f.assessment_score_payload(), PROGRAM_ADMIN),
        ERR_UNAUTHORIZED, 403)

    assessment = read_assessment(api, scenario.assessment_id)
    assert assessment["status"] == "OPEN", "never ERR_ASSESSMENT_STATE_INVALID"
    assert assessment["total_score"] == 0


def test_a_candidate_cannot_submit_an_assessment_that_is_not_theirs(api):
    """The role is right, the identity is wrong, and rung 4 says so.

    PRD §2.6 rung 4: "For the entity-backed roles, the acting `X-User-ID` owns the
    resource: a `CandidateUser`'s id equals the owning placement's `candidate_id`
    when submitting an assessment, and a `UniversitySupervisorUser`'s id equals
    the cycle's `supervisor_id` when recording an observation — otherwise
    `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/rbac/a_candidate_user_cannot_submit_another_candidates_assessment
    """
    scenario = setup_active_placement(api)
    stranger = setup_ready_candidate(api, candidate=SECOND_HOME)
    scenario.assessment = open_assessment(api, scenario.placement_id)
    set_clock(api, SUBMISSION_CLOCK)

    validate_error(api.submit_assessment(
        scenario.assessment_id, f.assessment_submit_payload(),
        make_candidate_headers(stranger.candidate_id)),
        ERR_NOT_RESOURCE_OWNER, 403)

    assessment = read_assessment(api, scenario.assessment_id)
    assert assessment["status"] == "OPEN"
    assert assessment["attempt_no"] == 0
    assert assessment["submitted_at"] is None
    placement = read_placement(api, scenario.placement_id)
    assert placement["candidate_id"] == scenario.candidate_id
    assert placement["candidate_id"] != stranger.candidate_id


def test_a_blank_user_id_header_is_treated_as_no_credential_at_all(api):
    """An empty string is absent, and absence is answered before anything else.

    PRD §2.6 rung 1: "Both `X-User-ID` and `X-User-Role` are present and
    non-empty; an empty string counts as absent — otherwise
    `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/rbac/a_blank_x_user_id_header_returns_unauthenticated
    """
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario)

    validate_error(api.get_candidate(
        scenario.candidate_id,
        make_headers(BLANK_USER_ID, UserRole.PROGRAM_ADMIN.value)),
        ERR_UNAUTHENTICATED, 401)

    named = validate_success(api.get_candidate(scenario.candidate_id,
                                               PROGRAM_ADMIN))
    assert named["id"] == scenario.candidate_id, (
        "the same read under the same role succeeds once the id is non-empty")


def test_the_removal_requester_cannot_decide_their_own_case(api):
    """Two roles, one human, and the rule keys on the human.

    PRD §2.6 rung 23: "Segregation of duties holds: the acting `X-User-ID` differs
    from `removal_requested_by_user_id` on a removal decision, and differs from
    the candidate's `recommended_by_user_id` on a state report — otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/rbac/the_removal_requester_cannot_decide_their_own_removal_case
    """
    scenario = setup_active_placement(api)
    validate_success(api.request_removal(
        scenario.placement_id, f.removal_request_payload(),
        make_headers(DUAL_ROLE_USER_ID, UserRole.PLACEMENT_COORDINATOR.value)))

    validate_error(api.decide_removal(
        scenario.placement_id, f.removal_decision_payload(),
        make_headers(DUAL_ROLE_USER_ID, UserRole.PROGRAM_ADMIN.value)),
        ERR_SEGREGATION_OF_DUTIES, 403)

    placement = read_placement(api, scenario.placement_id)
    assert placement["placement_status"] == "REMOVAL_PENDING", (
        "never ERR_UNAUTHORIZED: ProgramAdmin owns this endpoint")
    assert placement["removal_requested_by_user_id"] == DUAL_ROLE_USER_ID
    assert placement["removal_decided_by_user_id"] is None
    assert placement["stipend_status"] == "ACCRUED"
    assert placement["stipend_gross_cents"] == PROVISIONAL_GROSS_CENTS
    decided = validate_success(api.decide_removal(
        scenario.placement_id, f.removal_decision_payload(), PROGRAM_ADMIN))
    assert decided["placement_status"] == "REMOVED", (
        "a different principal decides the identical case")


def test_a_supervision_lead_shares_the_removal_request_operation(api):
    """A shared operation fires every cascade for either owner of it.

    PRD §3.8: "A `PlacementCoordinator` or a `SupervisionLead` may open a
    **removal case** against an `ACTIVE` placement ... The placement moves
    `ACTIVE → REMOVAL_PENDING` and records the reason, the narrative, the acting
    principal's role in `removal_requested_by_role` and the acting principal's
    identifier in `removal_requested_by_user_id`. The same three-hop cascade the
    assessment failure triggers runs here: every `SCHEDULED` cycle of the
    placement moves to `CANCELLED_HOLD` and `observation_compliance_ratio` is
    re-derived over what remains, and `supervisor_points` is re-scored at the
    `REMOVAL_PENDING` base of 3 with the supervisor's `caseload_points` re-derived
    upward. The money dimension is deliberately left alone."

    Design: Corner/rbac/supervision_lead_shares_the_removal_request_operation
    """
    scenario = setup_active_placement(api)
    cycle = schedule_cycle(api, scenario.placement_id, *FIRST_CYCLE)

    opened = validate_success(api.request_removal(
        scenario.placement_id, f.removal_request_payload(**SITE_WITHDRAWAL),
        SUPERVISION_LEAD))

    assert opened["placement_status"] == "REMOVAL_PENDING"
    assert opened["removal_requested_by_role"] == UserRole.SUPERVISION_LEAD.value
    assert opened["removal_requested_by_user_id"] == SUPERVISION_LEAD_USER_ID
    assert read_cycle(api, cycle["id"])["status"] == "CANCELLED_HOLD"
    placement = read_placement(api, scenario.placement_id)
    assert_ratio_equals(placement["observation_compliance_ratio"], 0.0)
    assert placement["supervisor_points"] == REMOVAL_PENDING_POINTS
    assert_caseload(read_supervisor(api, scenario.supervisor_id),
                    REMOVAL_PENDING_POINTS)
    assert placement["stipend_status"] == "ACCRUED", (
        "the money dimension waits for the decision")
