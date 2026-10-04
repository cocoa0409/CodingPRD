"""Referrals: the ESCALATION_PENDING creation gate, the submission cascade
that refers the case and moots open rounds, the 30-day first-submission
window, the return-for-info resubmission cycle, and agency actor rules."""

from test_helpers import (
    COORDINATOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_instant,
    assert_referral,
    create_assigned_case,
    create_draft_referral,
    escalate_case,
    make_ombudsman_headers,
    open_round,
    read_case,
    read_ombudsman,
    referral_payload,
    referral_state_payload,
    respond_as_employer,
    set_clock,
    setup_basic_world,
    setup_escalated_case_with_referral,
    submit_referral,
    transition_case,
    transition_referral,
    validate_error,
    validate_success,
)


def test_referral_create_on_assigned_case_returns_invalid_state(api: ApiClient):
    """PRD §3.7: "The assigned ombudsman then drafts a referral, naming the `case_id` — which must be in `ESCALATION_PENDING` — the federal enforcement `agency` (`DOL_VETS`, `DOJ_CIVIL_RIGHTS`, or `OPM`), and a narrative `summary`."
    PRD §2.7: "Sixth, state gates: the target entity must be in a state from which the requested transition exists, and cross-entity state gates apply, failing with `ERR_INVALID_STATE`, `ERR_ROUND_NOT_OPEN`, or `ERR_OMBUDSMAN_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/referral_submit_requires_case_escalation_pending
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    assert read_case(api, case["id"])["status"] == "ASSIGNED"

    response = api.create_referral(
        referral_payload(case["id"], summary="Premature referral attempt."),
        make_ombudsman_headers(world["ombudsman"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    referrals = validate_success(api.list_case_referrals(case["id"], make_ombudsman_headers(world["ombudsman"]["id"])))
    assert referrals == [], "the rejected draft persisted nothing"


def test_referral_create_after_escalation_returns_draft(api: ApiClient):
    """PRD §3.7: "The assigned ombudsman then drafts a referral, naming the `case_id` — which must be in `ESCALATION_PENDING` — the federal enforcement `agency` (`DOL_VETS`, `DOJ_CIVIL_RIGHTS`, or `OPM`), and a narrative `summary`. The draft is born in `DRAFT` status with `created_by_ombudsman_id` stamped from the drafter's `X-User-ID`, an audit string rather than an entity reference."

    Design: Difficulty/cross_entity_state_dependency/referral_submit_requires_case_escalation_pending
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    escalate_case(api, case["id"], world["employer"]["id"], world["ombudsman"]["id"])

    referral = create_draft_referral(api, case["id"], world["ombudsman"]["id"],
                                     summary="Timely referral after escalation.")
    assert_referral(referral)
    assert referral["status"] == "DRAFT"
    assert referral["created_by_ombudsman_id"] == world["ombudsman"]["id"]

    referrals = validate_success(api.list_case_referrals(case["id"], make_ombudsman_headers(world["ombudsman"]["id"])))
    assert len(referrals) == 1 and referrals[0]["id"] == referral["id"]


def _setup_escalated_case_with_open_round(api: ApiClient) -> dict:
    """Assigned case with one DECLINED round behind it and a second round still
    PROPOSED; the case is escalated and a DRAFT referral exists."""
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    round_one = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Reinstate with back pay.")
    respond_as_employer(api, round_one["id"], world["employer"]["id"], "DECLINE")
    round_two = open_round(api, case["id"], world["ombudsman"]["id"],
                           proposal_text="Reinstate, seniority intact.")
    transition_case(api, case["id"], "ESCALATION_PENDING",
                    make_ombudsman_headers(world["ombudsman"]["id"]), reason="Employer stonewalling")
    referral = create_draft_referral(api, case["id"], world["ombudsman"]["id"])
    return {"world": world, "case": case, "round_two": round_two, "referral": referral}


def test_referral_submit_refers_case_and_drops_caseload(api: ApiClient):
    """PRD §3.7: "Submitting cascades through the case: the case moves `ESCALATION_PENDING → REFERRED`, any of its rounds still `PROPOSED` are closed as `CLOSED_MOOT` with a system `AUDIT` note appended to the case for each round so closed, and the assigned ombudsman's caseload drops by 1."
    PRD §3.7: "The first submission stamps `submitted_at`."

    Design: Difficulty/transitive_cascade/referral_submit_refers_case_and_moots_round
    """
    setup = _setup_escalated_case_with_open_round(api)
    referral, case, world = setup["referral"], setup["case"], setup["world"]

    submitted = submit_referral(api, referral["id"])
    assert submitted["status"] == "SUBMITTED"
    assert_instant(submitted["submitted_at"], "2026-09-01T00:00:00Z", "submitted_at")

    referred = read_case(api, case["id"])
    assert referred["status"] == "REFERRED", "link 1: the submission moves the case to REFERRED"
    assert read_ombudsman(api, world["ombudsman"]["id"])["active_caseload"] == 0, \
        "the assigned ombudsman's caseload drops by 1"


def test_referral_submit_moots_open_round_with_audit_note(api: ApiClient, coordinator_headers: dict):
    """PRD §3.7: "Submitting cascades through the case: the case moves `ESCALATION_PENDING → REFERRED`, any of its rounds still `PROPOSED` are closed as `CLOSED_MOOT` with a system `AUDIT` note appended to the case for each round so closed, and the assigned ombudsman's caseload drops by 1."

    Design: Difficulty/transitive_cascade/referral_submit_refers_case_and_moots_round
    """
    setup = _setup_escalated_case_with_open_round(api)
    referral, case, round_two = setup["referral"], setup["case"], setup["round_two"]

    submit_referral(api, referral["id"])

    rounds = {r["id"]: r for r in validate_success(api.list_case_rounds(case["id"], coordinator_headers))}
    assert rounds[round_two["id"]]["status"] == "CLOSED_MOOT", "link 2: the still-PROPOSED round is mooted"

    notes = validate_success(api.list_case_notes(case["id"], coordinator_headers))
    audit_notes = [note for note in notes if note["note_type"] == "AUDIT"]
    assert len(audit_notes) == 1, "one system AUDIT note is appended for the mooted round"


def test_referral_return_resubmit_cycle_ignores_window(api: ApiClient, agency_reviewer_headers: dict):
    """PRD §3.7: "An `AgencyReviewer` either acknowledges the referral into `ACKNOWLEDGED` — terminal — or returns it for more information into `RETURNED_FOR_INFO`, storing the agency's `info_request_note`. A returned referral is resubmitted by a coordinator, `RETURNED_FOR_INFO → SUBMITTED`, now requiring the case to be `REFERRED`; the 30-day window does not re-apply to resubmissions."
    PRD §3.7: "The first submission stamps `submitted_at`."

    Design: Corner/state_machines/referral_return_resubmit_cycle_ignores_window
    """
    world = setup_basic_world(api)
    bundle = setup_escalated_case_with_referral(api, world["employer"], world["member"], world["ombudsman"])
    referral = bundle["referral"]

    submit_referral(api, referral["id"])
    returned = transition_referral(api, referral["id"], "RETURNED_FOR_INFO", agency_reviewer_headers,
                                   info_request_note="Attach the member's orders.")
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["info_request_note"] == "Attach the member's orders."

    set_clock(api, "2026-10-11T00:00:00Z")
    resubmitted = submit_referral(api, referral["id"])
    assert resubmitted["status"] == "SUBMITTED", \
        "resubmission 40 days after escalation is not window-checked"
    assert_instant(resubmitted["submitted_at"], "2026-09-01T00:00:00Z",
                   "submitted_at keeps the first-submission instant")

    acknowledged = transition_referral(api, referral["id"], "ACKNOWLEDGED", agency_reviewer_headers)
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert read_case(api, bundle["case"]["id"])["status"] == "REFERRED"


def test_referral_window_exactly_30_days(api: ApiClient):
    """PRD §3.7: "Only a `ProgramCoordinator` submits: a `DRAFT → SUBMITTED` transition requires the case still in `ESCALATION_PENDING` and, on the first submission only, requires the logical clock to be no later than 30 days after `escalated_at` — submission at exactly the 30-day mark is inside the window, while a later first submission fails with `ERR_REFERRAL_WINDOW_PASSED` (HTTP 422)."

    Design: Corner/validations/referral_window_exactly_30_days
    """
    world = setup_basic_world(api)
    bundle_a = setup_escalated_case_with_referral(api, world["employer"], world["member"], world["ombudsman"],
                                                  agency="DOL_VETS")
    bundle_b = setup_escalated_case_with_referral(api, world["employer"], world["member"], world["ombudsman"],
                                                  agency="DOJ_CIVIL_RIGHTS")
    assert_instant(bundle_a["case"]["escalated_at"], "2026-09-01T00:00:00Z", "escalated_at")

    set_clock(api, "2026-10-01T00:00:00Z")
    submitted_a = submit_referral(api, bundle_a["referral"]["id"])
    assert submitted_a["status"] == "SUBMITTED", "exactly escalated_at + 30 days is inside the window"

    set_clock(api, "2026-10-01T00:00:01Z")
    late_b = api.transition_referral(bundle_b["referral"]["id"], referral_state_payload("SUBMITTED"),
                                     COORDINATOR_HEADERS)
    validate_error(late_b, ApiErrorId.ERR_REFERRAL_WINDOW_PASSED)
    assert late_b.status_code == 422

    referrals_b = validate_success(
        api.list_case_referrals(bundle_b["case"]["id"], make_ombudsman_headers(world["ombudsman"]["id"]))
    )
    assert referrals_b[0]["status"] == "DRAFT", "the late first submission leaves the referral in DRAFT"
    assert read_case(api, bundle_b["case"]["id"])["status"] == "ESCALATION_PENDING"


def test_agency_reviewer_cannot_submit_referral(
    api: ApiClient, agency_reviewer_headers: dict, coordinator_headers: dict
):
    """PRD §3.7: "Only a `ProgramCoordinator` submits: a `DRAFT → SUBMITTED` transition requires the case still in `ESCALATION_PENDING`"
    PRD §2.1: "A caller whose role is not in an endpoint's authorized list — or who violates a transition-level actor rule, such as an `AgencyReviewer` attempting a submission that belongs to a `ProgramCoordinator` — is rejected with `ERR_UNAUTHORIZED_ROLE`."
    PRD §3.7: "An `AgencyReviewer` either acknowledges the referral into `ACKNOWLEDGED` — terminal — or returns it for more information into `RETURNED_FOR_INFO`, storing the agency's `info_request_note`."

    Design: Corner/rbac/agency_reviewer_cannot_submit_referral
    """
    world = setup_basic_world(api)
    bundle = setup_escalated_case_with_referral(api, world["employer"], world["member"], world["ombudsman"],
                                                agency="OPM")
    referral = bundle["referral"]

    as_agency = api.transition_referral(referral["id"], referral_state_payload("SUBMITTED"), agency_reviewer_headers)
    validate_error(as_agency, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert as_agency.status_code == 403

    premature_ack = api.transition_referral(referral["id"], referral_state_payload("ACKNOWLEDGED"),
                                            agency_reviewer_headers)
    validate_error(premature_ack, ApiErrorId.ERR_INVALID_STATE)

    submitted = api.transition_referral(referral["id"], referral_state_payload("SUBMITTED"), coordinator_headers)
    assert validate_success(submitted)["status"] == "SUBMITTED"
