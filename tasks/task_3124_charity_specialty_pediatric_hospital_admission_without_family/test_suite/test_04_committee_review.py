"""Committee review: rounds, votes, quorum, segregation of duties, OCC, and
the append-only review log."""
from test_helpers import (
    ApiErrorId,
    cast_vote,
    create_application,
    decide,
    get_application,
    make_intake_headers,
    make_reviewer_headers,
    open_review,
    set_clock,
    setup_application_with_accept_quorum,
    setup_hospital_with_program,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine
# ---------------------------------------------------------------------------

def test_application_review_info_request_cycle_rounds_increment(api, intake_headers,
                                                                reviewer1_headers):
    """PRD §3.3: "An `IntakeCoordinator` then supplies the requested information, returning the application to `PENDING_REVIEW`, incrementing `review_round` by 1, and appending a `RESUBMIT_INFO` event stamped with the new round number."

    Design: Difficulty/non_linear_state_machine/application_review_info_request_cycle_rounds_increment
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid Cycle")
    open_review(application["id"])
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    # Two full PENDING_REVIEW -> INFO_REQUESTED -> PENDING_REVIEW cycles.
    validate_success(api.request_info(application["id"], make_reviewer_headers("rcm-2")))
    validate_success(api.resubmit_info(application["id"], intake_headers))
    validate_success(api.request_info(application["id"], make_reviewer_headers("rcm-2")))
    validate_success(api.resubmit_info(application["id"], intake_headers))

    current = get_application(application["id"])
    assert current["review_round"] == 3
    assert current["status"] == "PENDING_REVIEW"

    events, _ = validate_paginated(api.list_reviews(application["id"], reviewer1_headers))
    actions = [event["action"] for event in events]
    assert actions == [
        "OPEN_ROUND", "CAST_VOTE_ACCEPT", "REQUEST_INFO",
        "RESUBMIT_INFO", "REQUEST_INFO", "RESUBMIT_INFO",
    ]


def test_application_review_cycle_resets_per_round_vote_tally(api, reviewer3_headers):
    """PRD §3.3: "Votes are scoped to the round: only votes cast under the application's current `review_round` count toward quorum."

    Design: Difficulty/non_linear_state_machine/application_review_info_request_cycle_rounds_increment
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid Cycle")
    open_review(application["id"])
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    validate_success(api.request_info(application["id"], make_reviewer_headers("rcm-2")))
    validate_success(api.resubmit_info(application["id"], make_intake_headers("ic-1")))
    validate_success(api.request_info(application["id"], make_reviewer_headers("rcm-2")))
    validate_success(api.resubmit_info(application["id"], make_intake_headers("ic-1")))

    # Round-1 accept weight 2 does not carry into round 3: no round-3 votes.
    current = get_application(application["id"])
    resp = api.decide_application(
        application["id"],
        {"decision": "ACCEPT",
         "decision_reason": "round-3 decide on stale round-1 votes only",
         "expected_application_version": current["version"]},
        reviewer3_headers,
    )
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency
# ---------------------------------------------------------------------------

def test_application_acceptance_gated_by_program_state_blocked(api, admin_headers,
                                                               reviewer3_headers):
    """PRD §3.3: "An `ACCEPT` additionally requires the hospital's `admissions_ytd` to be strictly below its `annual_capacity` — evaluated on the pre-increment value — otherwise `ERR_HOSPITAL_CAPACITY_REACHED` (HTTP 409), and requires the applied program to be `ACTIVE`, otherwise `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/application_acceptance_gated_by_program_state
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, _, application = setup_application_with_accept_quorum(
        patient_full_name="Kid Gate",
    )
    validate_success(api.suspend_program(program["id"], admin_headers))

    current = get_application(application["id"])
    resp = api.decide_application(
        application["id"],
        {"decision": "ACCEPT", "decision_reason": "blocked while suspended",
         "expected_application_version": current["version"]},
        reviewer3_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value, expected_status=409)
    still = get_application(application["id"])
    assert still["status"] == "PENDING_REVIEW"


def test_application_acceptance_unblocked_after_program_reactivation(api, admin_headers,
                                                                     reviewer3_headers):
    """PRD §3.1: "A `SUSPENDED` hospital may be reopened back to `OPEN`, but its programs stay `SUSPENDED` and must be reactivated one at a time; a program reactivation is only accepted while the parent hospital is `OPEN`, otherwise it is rejected with `ERR_HOSPITAL_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/application_acceptance_gated_by_program_state
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, program, _, application = setup_application_with_accept_quorum(
        patient_full_name="Kid Gate",
    )
    validate_success(api.suspend_program(program["id"], admin_headers))
    current = get_application(application["id"])
    validate_error(
        api.decide_application(
            application["id"],
            {"decision": "ACCEPT", "decision_reason": "blocked",
             "expected_application_version": current["version"]},
            reviewer3_headers,
        ),
        ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value, expected_status=409,
    )

    validate_success(api.reactivate_program(program["id"], admin_headers))
    accepted = decide(application["id"], decision="ACCEPT",
                      decision_reason="unblocked after reactivation", reviewer="rcm-3")
    assert accepted["status"] == "ACCEPTED"
    hospital_after = validate_success(api.get_hospital(hospital["id"], admin_headers))
    assert hospital_after["admissions_ytd"] == 1


# ---------------------------------------------------------------------------
# Difficulty/consistency (corner: consistency_model)
# ---------------------------------------------------------------------------

def test_acceptance_side_effects_visible_in_same_request_cycle_billing_and_ytd(
        api, billing_headers, admin_headers):
    """PRD §3.3: "A successful `ACCEPT` appends the deciding `CAST_VOTE_ACCEPT` event, increments the hospital's `admissions_ytd` by 1, records the `decision_reason`, auto-creates the application's `BillingAccount`, auto-creates a `CarePlan` when the program has `staged_care_required`, and converts the linked screening if `screening_id` is set."

    Design: Corner/consistency_model/acceptance_side_effects_visible_in_same_request_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, program, source, application = setup_application_with_accept_quorum(
        patient_full_name="Kid Immediate", condition_category="BURN",
        program_overrides={"category": "BURN", "staged_care_required": True},
    )
    decided = decide(application["id"], decision="ACCEPT", decision_reason="ok",
                     reviewer="rcm-3")
    assert decided["status"] == "ACCEPTED"

    accounts, _ = validate_paginated(
        api.get_application_billing_account(application["id"], billing_headers)
    )
    assert len(accounts) == 1
    assert accounts[0]["status"] == "OPEN"

    hospital_after = validate_success(api.get_hospital(hospital["id"], admin_headers))
    assert hospital_after["admissions_ytd"] == 1


def test_acceptance_side_effects_visible_in_same_request_cycle_care_plan(api, care_headers):
    """PRD §2.9: "State changes on a parent resource propagate to its children, and the propagation is immediate — the system's consistency model is immediate, not eventual."

    Design: Corner/consistency_model/acceptance_side_effects_visible_in_same_request_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_application_with_accept_quorum(
        patient_full_name="Kid Immediate", condition_category="BURN",
        program_overrides={"category": "BURN", "staged_care_required": True},
    )
    decide(application["id"], decision="ACCEPT", decision_reason="ok", reviewer="rcm-3")

    plans, _ = validate_paginated(
        api.get_application_care_plan(application["id"], care_headers)
    )
    assert len(plans) == 1
    assert plans[0]["clinical_status"] == "PLANNING"
    assert plans[0]["funding_status"] == "UNFUNDED"


# ---------------------------------------------------------------------------
# Corner/state_machines
# ---------------------------------------------------------------------------

def test_application_initial_state_is_submitted(api):
    """PRD §3.2: "New applications start in `SUBMITTED` with `review_round` at 1."

    Design: Corner/state_machines/application_initial_state_is_submitted
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid Init")
    assert application["status"] == "SUBMITTED"
    assert application["review_round"] == 1


def test_decide_from_submitted_without_open_review_rejected(api, reviewer1_headers):
    """PRD §3.3: "The decision itself is rendered by a committee member supplying a `decision`, a free-text `decision_reason`, and the OCC guard `expected_application_version` described in §2.7."

    Design: Corner/state_machines/decide_from_submitted_without_open_review_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid Early")
    resp = api.decide_application(
        application["id"],
        {"decision": "ACCEPT", "decision_reason": "too early",
         "expected_application_version": application["version"]},
        reviewer1_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    still = get_application(application["id"])
    assert still["status"] == "SUBMITTED"
    events, _ = validate_paginated(api.list_reviews(application["id"], reviewer1_headers))
    assert events == []


def test_terminal_application_lockdown_withdraw_after_denied(api, intake_headers,
                                                             admin_headers):
    """PRD §3.3: "A successful `DENY` appends the deciding `CAST_VOTE_DENY` event and records the `decision_reason`. Both outcomes are terminal."

    Design: Corner/state_machines/terminal_application_lockdown_withdraw_after_denied
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _, application = setup_submitted_application(
        patient_full_name="Kid Deny",
    )
    open_review(application["id"])
    cast_vote(application["id"], vote="DENY", vote_weight=2, reviewer="rcm-1")
    denied = decide(application["id"], decision="DENY", decision_reason="not a fit",
                    reviewer="rcm-2")
    assert denied["status"] == "DENIED"

    resp = api.withdraw_application(application["id"], intake_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = get_application(application["id"])
    assert after["status"] == "DENIED"
    assert after["decision_reason"] == "not a fit"
    hospital_after = validate_success(api.get_hospital(hospital["id"], admin_headers))
    assert hospital_after["admissions_ytd"] == 0


def test_segregation_of_duties_info_requester_cannot_decide(api, reviewer2_headers):
    """PRD §3.3: "Segregation of duties bars the member who most recently requested information on the current round from casting the deciding vote — if the acting member's `X-User-ID` equals the application's `info_requested_by`, the decision is rejected with `ERR_REVIEWER_CONFLICT` (HTTP 403)."

    Design: Corner/state_machines/segregation_of_duties_info_requester_cannot_decide
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid SoD")
    open_review(application["id"])
    validate_success(api.request_info(application["id"], reviewer2_headers))
    validate_success(api.resubmit_info(application["id"], make_intake_headers("ic-1")))
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(application["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-3")

    current = get_application(application["id"])
    assert current["info_requested_by"] == "rcm-2"
    resp = api.decide_application(
        application["id"],
        {"decision": "ACCEPT", "decision_reason": "info requester tries to decide",
         "expected_application_version": current["version"]},
        reviewer2_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICT.value, expected_status=403)


def test_segregation_of_duties_clean_member_decides(api, reviewer2_headers,
                                                    reviewer3_headers):
    """PRD §3.3: "The decision itself is rendered by a committee member supplying a `decision`, a free-text `decision_reason`, and the OCC guard `expected_application_version` described in §2.7."

    Design: Corner/state_machines/segregation_of_duties_info_requester_cannot_decide
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid SoD")
    open_review(application["id"])
    validate_success(api.request_info(application["id"], reviewer2_headers))
    validate_success(api.resubmit_info(application["id"], make_intake_headers("ic-1")))
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(application["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-3")

    # A different member with the same payload succeeds.
    accepted = decide(application["id"], decision="ACCEPT",
                      decision_reason="clean member decides", reviewer="rcm-3")
    assert accepted["status"] == "ACCEPTED"


def test_deny_quorum_two_but_not_with_mixed_votes(api, reviewer3_headers):
    """PRD §3.3: "Quorum is weighted and direction-locked: an `ACCEPT` decision requires the sum of `vote_weight` over this round's `CAST_VOTE_ACCEPT` events to be at least 3 with this round's deny weight at exactly 0, while a `DENY` decision requires this round's deny weight to be at least 2 with this round's accept weight at exactly 0; failing either yields `ERR_QUORUM_NOT_MET` (HTTP 409)."

    Design: Corner/state_machines/deny_quorum_two_but_not_with_mixed_votes
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, source, application = setup_submitted_application(
        patient_full_name="Kid Mixed",
    )
    program_id = application["program_id"]
    open_review(application["id"])
    cast_vote(application["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-1")
    cast_vote(application["id"], vote="DENY", vote_weight=2, reviewer="rcm-2")

    current = get_application(application["id"])
    resp = api.decide_application(
        application["id"],
        {"decision": "DENY", "decision_reason": "mixed round",
         "expected_application_version": current["version"]},
        reviewer3_headers,
    )
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value, expected_status=409)
    assert get_application(application["id"])["status"] == "PENDING_REVIEW"


def test_deny_quorum_exactly_two_clean_round_succeeds(api, reviewer3_headers):
    """PRD §3.3: "A successful `DENY` appends the deciding `CAST_VOTE_DENY` event and records the `decision_reason`."

    Design: Corner/state_machines/deny_quorum_two_but_not_with_mixed_votes
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid Clean")
    open_review(application["id"])
    cast_vote(application["id"], vote="DENY", vote_weight=2, reviewer="rcm-1")

    denied = decide(application["id"], decision="DENY", decision_reason="clean deny",
                    reviewer="rcm-3")
    assert denied["status"] == "DENIED"
    assert denied["decision_reason"] == "clean deny"


# ---------------------------------------------------------------------------
# Corner/endpoints
# ---------------------------------------------------------------------------

def test_vote_action_endpoint_appends_review_event(api):
    """PRD §3.3: "Each vote appends an `ApplicationReview` event whose `action` is `CAST_VOTE_ACCEPT` or `CAST_VOTE_DENY`, carrying the voter's `reviewer_user_id`, the current `round_number`, and a `vote_weight` — 1 for a regular member and 2 for the committee chair, defaulting to 1 when not supplied."

    Design: Corner/endpoints/vote_action_endpoint_appends_review_event
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid Vote")
    open_review(application["id"])

    resp = api.cast_vote(
        application["id"], {"vote": "ACCEPT", "vote_weight": 2},
        make_reviewer_headers("rcm-9"),
    )
    review = validate_success(resp)
    assert review["action"] == "CAST_VOTE_ACCEPT"
    assert review["vote_weight"] == 2
    assert review["reviewer_user_id"] == "rcm-9"
    assert review["round_number"] == 1

    after = get_application(application["id"])
    # +1 open-review, +1 vote.
    assert after["version"] == application["version"] + 2


def test_billing_account_reverse_reachability_returns_zero_or_one_row(api, billing_headers):
    """PRD §3.4: "The `BillingAccount` springs into existence automatically the moment an application is accepted — exactly one account per accepted application, created with `status` `OPEN` and all four balances (`total_charged_cents`, `insurance_paid_cents`, `charity_writeoff_cents`, `open_claim_cents`) at 0."

    Design: Corner/endpoints/billing_account_reverse_reachability_returns_zero_or_one_row
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid BA")

    before, _ = validate_paginated(
        api.get_application_billing_account(application["id"], billing_headers)
    )
    assert before == []

    open_review(application["id"])
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(application["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    decide(application["id"], decision="ACCEPT", decision_reason="ok", reviewer="rcm-3")

    after, _ = validate_paginated(
        api.get_application_billing_account(application["id"], billing_headers)
    )
    assert len(after) == 1
    assert after[0]["application_id"] == application["id"]
    assert after[0]["status"] == "OPEN"
    assert after[0]["family_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers
# ---------------------------------------------------------------------------

def test_occ_decide_correct_version_succeeds_after_cascade_bumps(api):
    """PRD §2.7: "The application-decision operation requires a non-optional `expected_application_version` field in the request body, carrying the `version` of the `PatientApplication` the committee member last observed."

    Design: Corner/cross_cutting_layers/occ_decide_correct_version_succeeds_after_cascade_bumps
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_application_with_accept_quorum(
        patient_full_name="Kid OCC2",
    )
    fresh = get_application(application["id"], reviewer="rcm-3")
    resp = api.decide_application(
        application["id"],
        {"decision": "ACCEPT", "decision_reason": "fresh view",
         "expected_application_version": fresh["version"]},
        make_reviewer_headers("rcm-3"),
    )
    accepted = validate_success(resp)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["version"] == fresh["version"] + 1
