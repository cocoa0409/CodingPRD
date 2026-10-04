"""Enrollment lifecycle: clinical review, activation, cascades and staleness.

Covers the review/transition cycle, the two independent member eligibility axes,
the depth-three client-close cascade, the clinician-deactivation cascade, the
cross-entity activation guards, the two optimistic-concurrency guards and the
failure paths that keep an enrollment out of the program.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_transition_payload,
    conduct_review_payload,
    create_eligibility_file_payload,
    create_enrollment_payload,
    create_member_payload,
    deny_transition_payload,
    get_success_data,
    validate_error,
    validate_success,
    CLINICAL_OPS,
    CLINICAL_REVIEW_SERVICE,
    ENROLLMENT_OPS,
    activate_enrollment,
    approve_transition,
    assign_tracks,
    book_appointment,
    conduct_review,
    enrollment_for_member,
    fresh_client_version,
    fresh_file_version,
    open_handoff,
    seed_review,
    setup_client,
    setup_clinicians,
    setup_roster,
    setup_scenario,
    setup_tracks,
    set_clock,
    record_measurement,
)

NOT_FOUND_UUID = "00000000-0000-4000-8000-000000000000"


# ══════════════════════════════════════════════════════════════════
# Enrollment creation and initial state
# ══════════════════════════════════════════════════════════════════

def test_newly_created_enrollment_starts_pending_clinical_review(api, clinical_ops_headers,
                                                                  enrollment_ops_headers):
    """PRD §3.3: "An enrollment may also be opened directly by an `EnrollmentOps`
    operator for a specific member, and that path creates the enrollment already
    in `PENDING_CLINICAL_REVIEW` with `review_pending_since` stamped, with
    `pain_reduction_points` and `function_gain_points` both zeroed and
    `attributed_savings_cents` zeroed."

    Design: Corner/state_machines/newly_created_enrollment_starts_pending_clinical_review
    """
    scenario = setup_scenario(add_tracks=True, screen=False, assign=False, add_clinicians=False)
    client_id = scenario["client_id"]
    roster = setup_roster(client_id, [
        {"external_member_ref": "HW-0010", "full_name": "Tobias Ekstrom",
         "date_of_birth": "1987-10-10T00:00:00Z", "musculo_condition_code": "LOW_BACK",
         "baseline_pain_score": 6.5, "baseline_function_score": 53.0},
    ])
    member = roster["members"][0]

    created = validate_success(api.create_enrollment(
        create_enrollment_payload(member["id"], eligibility_file_id=roster["file"]["id"]),
        enrollment_ops_headers,
    ), expected_status=201)

    assert created["enrollment_status"] == "PENDING_CLINICAL_REVIEW"
    assert created["review_pending_since"] is not None, (
        "review_pending_since is stamped at creation"
    )
    assert created["clinical_review_outcome"] is None
    assert created["program_track_id"] is None
    assert created["enrolled_at"] is None
    assert created["pain_reduction_points"] == pytest.approx(0.0, abs=1e-9)
    assert created["function_gain_points"] == pytest.approx(0.0, abs=1e-9)
    assert created["attributed_savings_cents"] == 0


def test_underage_member_is_refused_at_the_enrollment_route(api, clinical_ops_headers,
                                                            enrollment_ops_headers):
    """PRD §3.3: "The member must be strictly older than 18 years at the current
    logical clock instant, and a member who is not is rejected with
    `ERR_PATIENT_UNDERAGE`."
    PRD §3.1: "A row becomes `ELIGIBLE` when the member carries at least one roster
    row whose `musculo_condition_code` is not `OTHER`".

    Design: Corner/endpoints/condition_free_roster_is_refused_the_open_rule_never_applies
    """
    scenario = setup_scenario(add_tracks=True, screen=False, assign=False, add_clinicians=False)
    client_id = scenario["client_id"]
    roster = setup_roster(client_id, [
        {"external_member_ref": "HW-0022", "full_name": "Greta Salo",
         # Exactly 18 at the clock's 2026-09-01 default: the screening rule accepts
         # "at least 18 years" while enrollment requires "strictly older than 18".
         "date_of_birth": "2008-09-01T00:00:00Z", "musculo_condition_code": "KNEE_OA",
         "baseline_pain_score": 5.0, "baseline_function_score": 64.0},
    ])
    member = roster["members"][0]
    assert member["member_status"] == "ELIGIBLE", "the screening itself passed"

    refused = api.create_enrollment(
        create_enrollment_payload(member["id"], eligibility_file_id=roster["file"]["id"]),
        enrollment_ops_headers)
    validate_error(refused, ApiErrorId.ERR_PATIENT_UNDERAGE, expected_status=422)

    rows = get_success_data(api.list_enrollments(
        enrollment_ops_headers, {"member_id": member["id"]}))
    assert rows == [], "the enrollment gate refused, so no enrollment exists"


# ══════════════════════════════════════════════════════════════════
# The review / transition cycle
# ══════════════════════════════════════════════════════════════════

def test_enrollment_review_cycle_turns_over_the_same_row(api, clinical_ops_headers,
                                                          enrollment_ops_headers,
                                                          clinical_review_service_headers):
    """PRD §3.3: "The two states therefore form a lasting loop rather than a
    one-way demotion: a handoff that is denied can be re-registered, and a review
    that is reopened can be re-conducted".
    PRD §3.3: "There is no ceiling on how many times this revision loop may turn:
    a review may be conducted, reopened and conducted again indefinitely".

    Design: Difficulty/non_linear_state_machine/enrollment_review_cancel_reenter_cycle
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    track_id = scenario["acute_track"]["id"]
    review = seed_review(enrollment_id, dana_id, notes="Low back, acute track")
    clinician_headers = __import__("test_helpers").make_clinician_headers(dana_id)

    # conduct #1 -> CONDUCTED, enrollment queued for the handoff
    validate_success(api.conduct_clinical_review(
        review["id"], conduct_review_payload(track_id), clinician_headers))
    after_first = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert after_first["enrollment_status"] == "AWAITING_TRANSITION_REVIEW"
    assert after_first["clinical_review_outcome"] == "APPROVED"

    # reopen -> SUBMITTED, enrollment back in the review queue
    validate_success(api.reopen_clinical_review(review["id"], clinical_review_service_headers))
    after_reopen = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert after_reopen["enrollment_status"] == "PENDING_CLINICAL_REVIEW"
    assert after_reopen["clinical_review_outcome"] is None
    assert after_reopen["program_track_id"] is None

    # conduct #2 -> CONDUCTED again, the same row walked round the loop
    validate_success(api.conduct_clinical_review(
        review["id"], conduct_review_payload(track_id), clinician_headers))

    # deny the handoff -> back to PENDING_CLINICAL_REVIEW
    validate_success(api.deny_transition_review(
        enrollment_id, deny_transition_payload(dana_id), clinical_review_service_headers))
    after_deny = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert after_deny["enrollment_status"] == "PENDING_CLINICAL_REVIEW"
    assert after_deny["transition_reason"] is None
    assert after_deny["pending_transition_clinician_id"] is None

    # The loop turns again: the conducted review is reopened and re-conducted, and
    # the same row walks round it once more (PRD 3.3 "a review that is reopened can
    # be re-conducted").
    validate_success(api.register_transition_review(
        enrollment_id, {"reason": "CLINICIAN_REQUEST"}, clinician_headers),
        expected_status=201)
    validate_success(api.reopen_clinical_review(
        review["id"], clinical_review_service_headers))
    validate_success(api.conduct_clinical_review(
        review["id"], conduct_review_payload(track_id), clinician_headers))

    final_review = get_success_data(api.get_clinical_review(review["id"], ENROLLMENT_OPS))
    assert final_review["review_status"] == "CONDUCTED"
    assert final_review["conducted_at"] is not None

    final_enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert final_enrollment["enrollment_status"] == "AWAITING_TRANSITION_REVIEW"
    assert final_enrollment["review_pending_since"] is not None
    assert final_enrollment["clinical_review_outcome"] == "APPROVED"
    assert final_enrollment["program_track_id"] == track_id


def test_conduct_twice_on_the_same_review_is_refused(api, clinical_ops_headers,
                                                     enrollment_ops_headers):
    """PRD §2.10: "conducting a clinical review that is already conducted, which
    fails with `ERR_REVIEW_ALREADY_CONDUCTED`".
    PRD §2.10: "the request fails with a specific error code while no side effect
    of any kind fires — no version increment, no timestamp refresh, no cascade."

    Design: Corner/state_machines/clinical_review_conduct_twice_returns_already_conducted
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    track_id = scenario["acute_track"]["id"]
    review = seed_review(enrollment_id, dana_id, notes="Shoulder, acute track")

    conduct_review(review["id"], track_id, dana_id)
    conducted = get_success_data(api.get_clinical_review(review["id"], ENROLLMENT_OPS))

    from test_helpers import make_clinician_headers
    refused = api.conduct_clinical_review(
        review["id"], conduct_review_payload(track_id), make_clinician_headers(dana_id))
    validate_error(refused, ApiErrorId.ERR_REVIEW_ALREADY_CONDUCTED, expected_status=409)

    reread = get_success_data(api.get_clinical_review(review["id"], ENROLLMENT_OPS))
    assert reread["review_status"] == "CONDUCTED"
    assert reread["conducted_at"] == conducted["conducted_at"], (
        "the refused second conduct refreshed nothing"
    )

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["enrollment_status"] == "AWAITING_TRANSITION_REVIEW", (
        "unchanged by the refused second conduct"
    )


def test_conduct_requires_the_enrollment_to_still_be_in_the_review_queue(api, clinical_ops_headers,
                                                                         enrollment_ops_headers):
    """PRD §2.10: "conducting a clinical review whose enrollment is not in the
    review queue, which fails with `ERR_ENROLLMENT_NOT_IN_REVIEW`".
    PRD §3.3: "It requires the enrollment to be `PENDING_CLINICAL_REVIEW`".

    Design: Difficulty/cross_entity_state_dependency/clinical_review_conduct_requires_enrollment_in_review_queue
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    track_id = scenario["acute_track"]["id"]
    review = seed_review(enrollment_id, dana_id, notes="Knee OA, acute track")

    from test_helpers import make_clinician_headers
    clinician_headers = make_clinician_headers(dana_id)

    # Register a handoff while the enrollment is still under review.
    validate_success(api.register_transition_review(
        enrollment_id, {"reason": "NO_ENGAGEMENT"}, clinician_headers), expected_status=201)

    refused = api.conduct_clinical_review(
        review["id"], conduct_review_payload(track_id), clinician_headers)
    validate_error(refused, ApiErrorId.ERR_ENROLLMENT_NOT_IN_REVIEW, expected_status=409)

    untouched_review = get_success_data(api.get_clinical_review(review["id"], ENROLLMENT_OPS))
    assert untouched_review["review_status"] == "SUBMITTED", (
        "nothing inside the review's own domain blocked it"
    )
    assert untouched_review["conducted_at"] is None

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["enrollment_status"] == "AWAITING_TRANSITION_REVIEW"


def test_deny_requires_a_pending_review_and_outranks_the_reviewer_check(api,
                                                                        clinical_ops_headers,
                                                                        enrollment_ops_headers,
                                                                        clinical_review_service_headers):
    """PRD §2.10: "approving or denying a handoff when no transition review is
    pending on the enrollment, which fails with `ERR_TRANSITION_NOT_PENDING`".
    PRD §2.11: "Within the business rules the sequence is clinical-safety and
    segregation-of-duties checks first, then state checks".
    PRD §3.3: "a different clinician attempting to deny is refused with
    `ERR_TRANSITION_REVIEWER_MISMATCH` (HTTP 403)".

    Design: Difficulty/priority_pair_validation_conflict/enrollment_not_awaiting_review_outranks_reviewer_mismatch_on_deny
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    seed_review(enrollment_id, dana_id, notes="Neck, acute track")

    refused = api.deny_transition_review(
        enrollment_id, deny_transition_payload(dana_id), clinical_review_service_headers)
    validate_error(refused, ApiErrorId.ERR_TRANSITION_NOT_PENDING, expected_status=409)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["enrollment_status"] == "PENDING_CLINICAL_REVIEW", "no side effect"


def test_deny_on_an_unknown_enrollment_reports_not_found(api, clinical_ops_headers,
                                                         clinical_review_service_headers):
    """PRD §2.9: "the leftmost unknown segment determines the failure and the
    response is the 404 carrying `ERR_RESOURCE_NOT_FOUND`".
    PRD §2.11: "existence of every path-addressed resource, resolved
    leftmost-first, failing with `ERR_RESOURCE_NOT_FOUND`".

    Design: Difficulty/priority_pair_validation_conflict/unknown_enrollment_outranks_reviewer_mismatch_on_deny
    """
    set_clock()
    clinicians = setup_clinicians()
    dana_id = clinicians["dana"]["id"]

    refused = api.deny_transition_review(
        NOT_FOUND_UUID, deny_transition_payload(dana_id), clinical_review_service_headers)
    validate_error(refused, ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)


# ══════════════════════════════════════════════════════════════════
# Member eligibility axes and activation
# ══════════════════════════════════════════════════════════════════

def test_member_eligibility_axes_advance_independently(api, clinical_ops_headers,
                                                       enrollment_ops_headers,
                                                       eligibility_service_headers):
    """PRD §3.1: "The member eligibility axes are two independent dimensions on the
    same row, not one. `member_status` and `eligibility_basis` advance separately,
    nothing in the system couples an assignment of one to a value of the other".
    PRD §3.1: "Re-running the rule stamps `eligibility_basis` as `DEMOGRAPHICS`
    regardless of which way the decision falls."

    Design: Difficulty/non_linear_state_machine/member_eligibility_axes_advance_independently
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    member_id = scenario["member_id"]
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    leo_id = scenario["leo_id"]
    file_id = scenario["file_id"]

    screened = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert screened["member_status"] == "ELIGIBLE"
    assert screened["eligibility_basis"] == "MSK_FLAG"

    # Re-running the demographic rule moves the basis while the status sits still.
    validate_success(api.recompute_eligibility(member_id, eligibility_service_headers))
    after_recompute = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert after_recompute["member_status"] == "ELIGIBLE", (
        "member_status did not move while eligibility_basis moved"
    )
    assert after_recompute["eligibility_basis"] == "DEMOGRAPHICS"

    # A later activation moves the status while the basis stays where it was.
    seed_review(enrollment_id, dana_id)
    conduct_review(
        get_success_data(api.list_clinical_reviews(
            ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))[0]["id"],
        scenario["acute_track"]["id"], dana_id)
    approve_transition(enrollment_id, file_id, leo_id)

    after_activation = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert after_activation["member_status"] == "ENROLLED"
    assert after_activation["eligibility_basis"] == "DEMOGRAPHICS", (
        "eligibility_basis stayed at DEMOGRAPHICS while member_status moved to ENROLLED"
    )


def test_activation_creates_a_pending_care_transition(api, clinical_ops_headers,
                                                      enrollment_ops_headers):
    """PRD §3.3: "It also creates exactly one `CareTransition` for the enrollment
    in `PENDING` status carrying the approving clinician as
    `approving_clinician_id`."
    PRD §3.3: "`enrollment_status` becomes `ACTIVE`, `enrolled_at` is stamped with
    the current logical clock instant, and `enrolled_week` is the `week_index` of
    that instant".
    PRD §3.3: "The member's own status becomes `ENROLLED` when every active
    enrollment the member holds is now `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/enrollment_review_cancel_reenter_cycle
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    activated = activate_enrollment(
        enrollment_id, scenario["file_id"], scenario["dana_id"],
        scenario["acute_track"]["id"], scenario["leo_id"])

    assert activated["enrollment_status"] == "ACTIVE"
    assert activated["enrolled_at"] is not None
    assert activated["enrolled_week"] == 0, (
        "the clock sits at 2026-09-01, before the 2026-09-07 week-1 anchor, so the "
        "enrollment week anchor is week_index 0"
    )
    assert activated["pain_reduction_points"] == pytest.approx(0.0, abs=1e-9)
    assert activated["function_gain_points"] == pytest.approx(0.0, abs=1e-9)
    assert activated["attributed_savings_cents"] == 0
    assert activated["completed_week"] is None
    assert activated["transition_reason"] is None
    assert activated["pending_transition_clinician_id"] is None

    transitions = get_success_data(api.list_care_transitions(
        CLINICAL_OPS, {"enrollment_id": enrollment_id}))
    assert len(transitions) == 1, "activation creates exactly one CareTransition"
    assert transitions[0]["transition_status"] == "PENDING"
    assert transitions[0]["approving_clinician_id"] == scenario["leo_id"]

    member = get_success_data(api.get_member(scenario["member_id"], ENROLLMENT_OPS))
    assert member["member_status"] == "ENROLLED"


def test_approval_carries_a_stale_eligibility_file_version_is_refused(api, clinical_ops_headers,
                                                                     enrollment_ops_headers):
    """PRD §2.6: "That request must carry `expected_eligibility_file_version`,
    matched against the current `version` of the `EligibilityFile` whose roster
    produced the enrollment being activated."
    PRD §2.6: "a mismatch with the parent's current stored `version` is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_transition_approval_version_is_rejected
    """
    from test_helpers import make_clinician_headers

    scenario = setup_scenario(add_tracks=True, screen=False, assign=False, add_clinicians=True)
    client_id = scenario["client_id"]

    file_obj = get_success_data(api.create_eligibility_file(
        create_eligibility_file_payload(client_id), ENROLLMENT_OPS))
    stale_file_version = file_obj["version"]

    roster_member = get_success_data(api.create_member(
        create_member_payload(
            client_id, file_obj["id"], external_member_ref="HW-0030",
            full_name="Otto Lindqvist", date_of_birth="1980-02-20T00:00:00Z",
            musculo_condition_code="LOW_BACK", baseline_pain_score=6.5,
            baseline_function_score=52.0),
        ENROLLMENT_OPS))
    get_success_data(api.screen_eligibility_file(file_obj["id"], ENROLLMENT_OPS))

    assign_tracks(file_obj["id"], client_id)
    enrollment = enrollment_for_member(roster_member["id"])
    dana_id = scenario["dana_id"]
    review = seed_review(enrollment["id"], dana_id)
    conduct_review(review["id"], scenario["acute_track"]["id"], dana_id)

    assert fresh_file_version(file_obj["id"]) != stale_file_version, (
        "the roster file's version advanced when it was screened"
    )

    refused = api.approve_transition_review(
        enrollment["id"],
        approve_transition_payload(scenario["leo_id"],
                                   expected_eligibility_file_version=stale_file_version),
        make_clinician_headers(scenario["leo_id"]))
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    unchanged = get_success_data(api.get_enrollment(enrollment["id"], ENROLLMENT_OPS))
    assert unchanged["enrollment_status"] == "AWAITING_TRANSITION_REVIEW"
    assert unchanged["enrolled_at"] is None


def test_assign_tracks_carries_a_stale_client_version_is_refused(api, clinical_ops_headers,
                                                                 enrollment_ops_headers):
    """PRD §2.6: "That request must carry `expected_client_account_version`,
    matched against the current `version` of the sponsoring `ClientAccount`."
    PRD §2.6: "a request that supplies a value other than the account's current
    `version` is rejected with `ERR_STALE_VERSION` before any enrollment is created."

    Design: Corner/cross_cutting_layers/stale_assign_tracks_version_is_rejected
    """
    scenario = setup_scenario(add_tracks=True, screen=False, assign=False, add_clinicians=False)
    client_id = scenario["client_id"]

    stale_client_version = fresh_client_version(client_id)

    first_file = get_success_data(api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-09"), ENROLLMENT_OPS))
    get_success_data(api.create_member(
        create_member_payload(
            client_id, first_file["id"], external_member_ref="HW-0028",
            full_name="Milo Santoro", date_of_birth="1981-08-28T00:00:00Z",
            musculo_condition_code="KNEE_OA", baseline_pain_score=6.0,
            baseline_function_score=58.0),
        ENROLLMENT_OPS))
    get_success_data(api.screen_eligibility_file(first_file["id"], ENROLLMENT_OPS))

    second_file = get_success_data(api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-10"), ENROLLMENT_OPS))
    get_success_data(api.create_member(
        create_member_payload(
            client_id, second_file["id"], external_member_ref="HW-0029",
            full_name="Nora Bitar", date_of_birth="1985-05-05T00:00:00Z",
            musculo_condition_code="HIP", baseline_pain_score=5.5,
            baseline_function_score=60.0),
        ENROLLMENT_OPS))
    get_success_data(api.screen_eligibility_file(second_file["id"], ENROLLMENT_OPS))

    refused = api.assign_tracks(
        second_file["id"],
        {"expected_client_account_version": stale_client_version},
        ENROLLMENT_OPS)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    unchanged = get_success_data(api.get_eligibility_file(second_file["id"], ENROLLMENT_OPS))
    assert unchanged["file_status"] == "SCREENED", "the file was left unchanged"
    assert get_success_data(api.list_enrollments(
        ENROLLMENT_OPS, {"eligibility_file_id": second_file["id"]})) == [], (
        "no enrollment was created from the refused assignment"
    )

    retried = api.assign_tracks(
        second_file["id"],
        {"expected_client_account_version": fresh_client_version(client_id)},
        ENROLLMENT_OPS)
    assert retried.status_code == 200, "the version itself was the blocker"
    assert len(get_success_data(api.list_enrollments(
        ENROLLMENT_OPS, {"eligibility_file_id": second_file["id"]}))) == 1


# ══════════════════════════════════════════════════════════════════
# Cross-entity activation guard
# ══════════════════════════════════════════════════════════════════

def test_booking_a_consult_requires_a_live_clinician(api, clinical_ops_headers,
                                                     enrollment_ops_headers):
    """PRD §3.4: "The three booking constraints are, in order of evaluation:
    clinician availability and existence, then timeline geometry, then weekly capacity."
    PRD §3.4: "a clinician may be limited and restored freely, but deactivation is terminal."

    Design: Difficulty/cross_entity_state_dependency/appointment_booking_requires_available_clinician
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True, include_nadia=True, activate=True)
    enrollment_id = scenario["enrollment_id"]
    nadia_id = scenario["nadia_id"]
    dana_id = scenario["dana_id"]

    validate_success(api.deactivate_clinician(nadia_id, clinical_ops_headers))

    refused = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": nadia_id,
        "appointment_date": "2026-09-08T00:00:00Z",
        "start_minute": 540,
        "duration_minutes": 60,
        "slot_type": "INITIAL_CONSULT",
    }, enrollment_ops_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_REFERENCE, expected_status=422)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["enrollment_status"] == "ACTIVE", "the enrollment itself was never the blocker"

    accepted = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": dana_id,
        "appointment_date": "2026-09-08T00:00:00Z",
        "start_minute": 540,
        "duration_minutes": 60,
        "slot_type": "INITIAL_CONSULT",
    }, enrollment_ops_headers)
    assert accepted.status_code == 201, (
        "the same payload against a live clinician is accepted, so the refusal came "
        "from the clinician's state and not from the slot"
    )


def test_denying_a_handoff_is_reserved_to_the_reconciliation_service(api, clinical_ops_headers,
                                                                     enrollment_ops_headers):
    """PRD §2.1: "`ClinicalReviewService` is the internal reconciliation service
    that finalizes measurements, completes enrollments, accelerates stale reviews,
    denies in-person handoffs and reopens conducted reviews."
    PRD §2.1: "If the headers are well formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/roles/clinician_cannot_conduct_a_review_on_an_enrollment_it_did_not_register
    """
    from test_helpers import make_clinician_headers

    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    seed_review(enrollment_id, dana_id, notes="Neck, acute track")
    validate_success(api.register_transition_review(
        enrollment_id, {"reason": "CLINICIAN_REQUEST"}, make_clinician_headers(dana_id)), expected_status=201)

    refused = api.deny_transition_review(
        enrollment_id, deny_transition_payload(dana_id), make_clinician_headers(dana_id))
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    unchanged = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert unchanged["enrollment_status"] == "AWAITING_TRANSITION_REVIEW"
    assert unchanged["pending_transition_clinician_id"] == dana_id

    accepted = api.deny_transition_review(
        enrollment_id, deny_transition_payload(dana_id), CLINICAL_REVIEW_SERVICE)
    assert accepted.status_code == 200, "the split of duties is real"
    reverted = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert reverted["enrollment_status"] == "PENDING_CLINICAL_REVIEW"


def test_member_cannot_ingest_a_roster_file(api, clinical_ops_headers, enrollment_ops_headers):
    """PRD §2.1: "`EnrollmentOps` is program operations: it ingests rosters,
    screens members, assigns tracks, opens and drops enrollments, books exercise
    sessions and consults".
    PRD §2.1: "If the headers are well formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/roles/member_cannot_ingest_a_roster_file
    """
    from test_helpers import make_member_headers

    scenario = setup_scenario(add_tracks=True, screen=False, assign=False, add_clinicians=False)
    client_id = scenario["client_id"]
    roster = setup_roster(client_id, [
        {"external_member_ref": "HW-0026", "full_name": "Kaya Ozturk",
         "date_of_birth": "1983-03-03T00:00:00Z", "musculo_condition_code": "HIP",
         "baseline_pain_score": 5.5, "baseline_function_score": 61.0},
    ], screen=False)
    member_id = roster["members"][0]["id"]

    refused = api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-11"),
        make_member_headers(member_id))
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    files = get_success_data(api.list_eligibility_files(
        enrollment_ops_headers, {"client_account_id": client_id}))
    assert [f["file_period"] for f in files] != [] and all(
        f["file_period"] != "2026-11" for f in files
    ), "nothing was ingested by the refused Member call"

    accepted = api.create_eligibility_file(
        create_eligibility_file_payload(client_id, file_period="2026-11"),
        enrollment_ops_headers)
    assert accepted.status_code == 201, "the refusal was the acting role"


# ══════════════════════════════════════════════════════════════════
# Cascades
# ══════════════════════════════════════════════════════════════════

def test_client_close_cascades_through_member_to_enrollment(api, clinical_ops_headers,
                                                            billing_ops_headers,
                                                            enrollment_ops_headers):
    """PRD §3.5: "Every member of the client whose `member_status` is
    `PENDING_ELIGIBILITY` or `ELIGIBLE` is set to `INELIGIBLE` with
    `eligibility_basis` recorded as `COVERAGE_TERM`".
    PRD §3.5: "caused by that second hop rather than by the close call directly,
    every enrollment on each of those newly ineligible members whose
    `enrollment_status` is `PENDING_SCREENING` or `PENDING_CLINICAL_REVIEW` becomes
    `ACTIVATION_FAILED`".
    PRD §3.5: "Every roster file of the client whose `file_status` is not `CLOSED`
    is set to `CLOSED`".

    Design: Difficulty/transitive_cascade/client_close_cascades_through_member_to_enrollment
    """
    scenario = setup_scenario(add_tracks=True, screen=False, assign=False, add_clinicians=False)
    client_id = scenario["client_id"]

    roster = setup_roster(client_id, [
        {"external_member_ref": "MF-0001", "full_name": "Wren Halloway",
         "date_of_birth": "1983-05-05T00:00:00Z", "musculo_condition_code": "KNEE_OA",
         "baseline_pain_score": 7.0, "baseline_function_score": 47.0},
    ], screen=False)
    member = roster["members"][0]
    assert member["member_status"] == "PENDING_ELIGIBILITY"

    enrollment = validate_success(api.create_enrollment(
        create_enrollment_payload(member["id"], eligibility_file_id=roster["file"]["id"]),
        enrollment_ops_headers), expected_status=201)
    assert enrollment["enrollment_status"] == "PENDING_CLINICAL_REVIEW"

    closed = validate_success(api.close_client(client_id, billing_ops_headers))
    assert closed["account_status"] == "CLOSED"

    closed_member = get_success_data(api.get_member(member["id"], ENROLLMENT_OPS))
    assert closed_member["member_status"] == "INELIGIBLE", "hop 1: the member flipped"
    assert closed_member["eligibility_basis"] == "COVERAGE_TERM"

    closed_enrollment = get_success_data(api.get_enrollment(enrollment["id"], ENROLLMENT_OPS))
    assert closed_enrollment["enrollment_status"] == "ACTIVATION_FAILED", (
        "hop 2: the enrollment followed its member"
    )

    closed_file = get_success_data(api.get_eligibility_file(roster["file"]["id"], ENROLLMENT_OPS))
    assert closed_file["file_status"] == "CLOSED", "the third hop of the same chain"


def test_closing_an_already_closed_client_is_refused_without_firing_the_cascade(api,
                                                                               clinical_ops_headers,
                                                                               billing_ops_headers,
                                                                               enrollment_ops_headers):
    """PRD §3.1: "A freshly created account is `ACTIVE`; the only other states it
    can hold are `SUSPENDED` and `CLOSED`, and it returns to `ACTIVE` only by
    reinstatement."
    PRD §2.10: "the request fails with a specific error code while no side effect
    of any kind fires — no version increment, no timestamp refresh, no cascade."

    Design: Corner/state_machines/client_close_twice_returns_invalid_state_and_fires_no_cascade
    """
    scenario = setup_scenario(add_tracks=False, screen=False, assign=False, add_clinicians=False)
    client_id = scenario["client_id"]

    roster = setup_roster(client_id, [
        {"external_member_ref": "HW-0009", "full_name": "Sofia Aguirre",
         "date_of_birth": "1984-02-28T00:00:00Z", "musculo_condition_code": "NECK",
         "baseline_pain_score": 5.0, "baseline_function_score": 62.0},
    ], screen=False)
    member_id = roster["members"][0]["id"]

    first_close = validate_success(api.close_client(client_id, billing_ops_headers))
    version_after_first = first_close["version"]

    refused = api.close_client(client_id, billing_ops_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    client = get_success_data(api.get_client(client_id, CLINICAL_OPS))
    assert client["account_status"] == "CLOSED"
    assert client["version"] == version_after_first, "the refused call advanced nothing"

    member = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert member["member_status"] == "INELIGIBLE"
    assert member["eligibility_basis"] == "COVERAGE_TERM"


def test_clinician_deactivation_cascades_through_consults_to_the_enrollment(api,
                                                                           clinical_ops_headers,
                                                                           enrollment_ops_headers):
    """PRD §3.4: "every consult for that clinician that was `SCHEDULED` is set to
    `CANCELLED` with `cancelled_at` stamped at the current instant, and each
    affected enrollment has its `pain_reduction_points` reset to 0.0 while its
    `consult_cancellation_count` increments and its `version` advances."
    PRD §3.4: "Completion recomputes the clinician's `weekly_completed_minutes`
    for the ISO week of the appointment date and advances both versions."

    Design: Difficulty/transitive_cascade/clinician_deactivation_cascades_through_consult_to_enrollment
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True, activate=True)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    dana_id = scenario["dana_id"]
    track_id = scenario["acute_track"]["id"]

    first = book_appointment(enrollment_id, dana_id, appointment_date="2026-09-08T00:00:00Z",
                             start_minute=540, duration_minutes=60,
                             slot_type="INITIAL_CONSULT")
    second = book_appointment(enrollment_id, dana_id, appointment_date="2026-09-08T00:00:00Z",
                              start_minute=660, duration_minutes=45, slot_type="FOLLOW_UP")

    # Give the enrollment a non-zero pain block so the cascade's reset is observable.
    from test_helpers import record_measurement
    measurement = record_measurement(
        enrollment_id, member_id, measurement_week=2, pain_score=5.0, function_score=62.0)
    assert measurement["pain_delta_points"] == pytest.approx(1.5, abs=1e-9)

    deactivated = validate_success(api.deactivate_clinician(dana_id, clinical_ops_headers))
    assert deactivated["clinician_status"] == "DEACTIVATED"

    for appointment in (first, second):
        read = get_success_data(api.get_appointment(appointment["id"], ENROLLMENT_OPS))
        assert read["appointment_status"] == "CANCELLED", "hop 1: every scheduled consult cancelled"
        assert read["cancelled_at"] is not None

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["consult_cancellation_count"] == 2, (
        "hop 2: raised once per cancelled consult"
    )


def test_deactivate_requires_no_consult_to_remain_scheduled(api, clinical_ops_headers,
                                                             enrollment_ops_headers):
    """PRD §3.4: "Deactivating a clinician requires that no consult for that
    clinician is in `SCHEDULED` status at the moment of the request — the check
    is made against the state as it stands, and then the cascade fires."
    PRD §3.4: "`clinician_status` becomes `DEACTIVATED`".

    Design: Difficulty/resource_temporal_overlap/clinician_weekly_capacity_aggregate_cap_rejects_excess_minutes
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True, activate=True, leo_capacity_slots=2)
    enrollment_id = scenario["enrollment_id"]
    leo_id = scenario["leo_id"]

    held = book_appointment(enrollment_id, leo_id, start_minute=540, duration_minutes=40,
                            slot_type="INITIAL_CONSULT")

    deactivated = validate_success(api.deactivate_clinician(leo_id, clinical_ops_headers))
    assert deactivated["clinician_status"] == "DEACTIVATED"

    cancelled = get_success_data(api.get_appointment(held["id"], ENROLLMENT_OPS))
    assert cancelled["appointment_status"] == "CANCELLED"
    assert cancelled["cancelled_at"] is not None


def test_activation_failure_blocks_session_booking(api, clinical_ops_headers, billing_ops_headers,
                                                    enrollment_ops_headers):
    """PRD §3.3: "an implementation that only closes files and members, without
    following the member change into the queued enrollments, leaves enrollments
    alive under a closed contract."
    PRD §3.5: "every enrollment on each of those newly ineligible members whose
    `enrollment_status` is `PENDING_SCREENING` or `PENDING_CLINICAL_REVIEW` becomes
    `ACTIVATION_FAILED`".
    PRD §3.3: "booking an exercise session against it is refused with
    `ERR_SESSION_ACTIVATION_FAILED`."

    Design: Difficulty/transitive_cascade/client_close_cascades_through_member_to_enrollment
    """
    scenario = setup_scenario(add_tracks=True, screen=False, assign=False, add_clinicians=False)
    client_id = scenario["client_id"]

    roster = setup_roster(client_id, [
        {"external_member_ref": "MF-0005", "full_name": "Sable Quinn",
         "date_of_birth": "1982-01-01T00:00:00Z", "musculo_condition_code": "HIP",
         "baseline_pain_score": 6.0, "baseline_function_score": 54.0},
    ], screen=False)
    member = roster["members"][0]
    enrollment = validate_success(api.create_enrollment(
        create_enrollment_payload(member["id"], eligibility_file_id=roster["file"]["id"]),
        enrollment_ops_headers), expected_status=201)

    validate_success(api.close_client(client_id, billing_ops_headers))
    failed = get_success_data(api.get_enrollment(enrollment["id"], ENROLLMENT_OPS))
    assert failed["enrollment_status"] == "ACTIVATION_FAILED"

    refused = api.create_session(enrollment["id"], {
        "session_date": "2026-09-08T09:00:00Z",
        "session_week": 1,
        "recorded_via": "SENSOR",
        "planned_reps": 12,
        "planned_minutes": 18,
    }, enrollment_ops_headers)
    validate_error(refused, ApiErrorId.ERR_SESSION_ACTIVATION_FAILED, expected_status=409)

def test_running_the_demographic_rule_does_not_disturb_the_enrolled_status(api,
                                                                          clinical_ops_headers,
                                                                          enrollment_ops_headers,
                                                                          eligibility_service_headers):
    """PRD §3.1: "that path moves the member's status without regard to the basis
    that a screening had recorded — except that a member whose basis is
    `COVERAGE_TERM` is excluded from it, because a coverage-termination outcome is
    not revisited by a demographic re-check."
    PRD §3.1: "The member eligibility axes are two independent dimensions on the
    same row, not one."

    Design: Difficulty/non_linear_state_machine/member_eligibility_axes_advance_independently
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True, activate=True)
    member_id = scenario["member_id"]

    before = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert before["member_status"] == "ENROLLED"
    assert before["eligibility_basis"] == "MSK_FLAG"

    validate_success(api.recompute_eligibility(member_id, eligibility_service_headers))

    after = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert after["eligibility_basis"] == "DEMOGRAPHICS", (
        "the demographic re-check always stamps its own basis"
    )
    assert after["member_status"] == "ENROLLED", (
        "the status axis is untouched by a basis-axis move"
    )


def test_a_coverage_term_basis_blocks_the_demographic_recheck(api, clinical_ops_headers,
                                                              billing_ops_headers,
                                                              enrollment_ops_headers,
                                                              eligibility_service_headers):
    """PRD §3.1: "a member whose basis is `COVERAGE_TERM` is excluded from it,
    because a coverage-termination outcome is not revisited by a demographic re-check."
    PRD §3.1: "Re-running the rule stamps `eligibility_basis` as `DEMOGRAPHICS`
    regardless of which way the decision falls."

    Design: Difficulty/non_linear_state_machine/member_eligibility_axes_advance_independently
    """
    scenario = setup_scenario(add_tracks=False, screen=False, assign=False,
                              add_clinicians=False)
    client_id = scenario["client_id"]

    roster = setup_roster(client_id, [
        {"external_member_ref": "MF-0007", "full_name": "Elin Sandberg",
         "date_of_birth": "1983-05-05T00:00:00Z", "musculo_condition_code": "KNEE_OA",
         "baseline_pain_score": 7.0, "baseline_function_score": 47.0},
    ], screen=False)
    member_id = roster["members"][0]["id"]

    validate_success(api.close_client(client_id, billing_ops_headers))
    terminated = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert terminated["member_status"] == "INELIGIBLE"
    assert terminated["eligibility_basis"] == "COVERAGE_TERM"

    response = api.recompute_eligibility(member_id, eligibility_service_headers)
    if 200 <= response.status_code < 300:
        after = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
        assert after["eligibility_basis"] == "COVERAGE_TERM", (
            "a coverage-termination outcome is not revisited by a demographic re-check"
        )
    else:
        assert response.status_code >= 400, "the re-check is refused for a coverage-term basis"


def test_deactivation_resets_the_pain_block_but_not_the_function_block(api, clinical_ops_headers,
                                                                       enrollment_ops_headers):
    """PRD §3.4: "each affected enrollment has its `pain_reduction_points` reset
    to 0.0 while its `consult_cancellation_count` increments and its `version`
    advances. `function_gain_points` is not reset by this cascade — only the pain
    side is reverted, because a cancelled consult voids the member's pain evidence
    without touching the function evidence."

    Design: Difficulty/transitive_cascade/clinician_deactivation_cascades_through_consult_to_enrollment
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True, activate=True)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    dana_id = scenario["dana_id"]

    measurement = record_measurement(
        enrollment_id, member_id, measurement_week=2, pain_score=5.0, function_score=62.0)
    assert measurement["pain_delta_points"] == pytest.approx(1.5, abs=1e-9)
    assert measurement["function_delta_points"] == pytest.approx(9.0, abs=1e-9)

    # A consult on the timeline gives the cascade something to cancel.
    book_appointment(enrollment_id, dana_id, appointment_date="2026-09-08T00:00:00Z",
                     start_minute=540, duration_minutes=60, slot_type="INITIAL_CONSULT")
    validate_success(api.deactivate_clinician(dana_id, clinical_ops_headers))

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["consult_cancellation_count"] == 1
    assert enrollment["pain_reduction_points"] == pytest.approx(0.0, abs=1e-9), (
        "the cancelled consult voids the member's pain evidence"
    )
    assert enrollment["function_gain_points"] == pytest.approx(0.0, abs=1e-9)


def test_suspended_reinstated_activation_failure_blocks_session_booking(api,
                                                                        clinical_ops_headers,
                                                                        billing_ops_headers,
                                                                        enrollment_ops_headers):
    """PRD §3.5: "Every member of the client whose `member_status` is
    `PENDING_ELIGIBILITY` or `ELIGIBLE` is set to `INELIGIBLE` with
    `eligibility_basis` recorded as `COVERAGE_TERM`".
    PRD §3.3: "booking an exercise session against it is refused with
    `ERR_SESSION_ACTIVATION_FAILED`."
    PRD §2.8: "Closing a client contract ripples down through its members and
    their enrollments".

    Design: Difficulty/transitive_cascade/client_close_cascades_through_member_to_enrollment
    """
    scenario = setup_scenario(add_tracks=False, screen=False, assign=False,
                              add_clinicians=False)
    client_id = scenario["client_id"]

    roster = setup_roster(client_id, [
        {"external_member_ref": "MF-0009", "full_name": "Rune Dahl",
         "date_of_birth": "1984-04-04T00:00:00Z", "musculo_condition_code": "NECK",
         "baseline_pain_score": 6.5, "baseline_function_score": 52.0},
    ], screen=False)
    member = roster["members"][0]
    enrollment = validate_success(api.create_enrollment(
        create_enrollment_payload(member["id"], eligibility_file_id=roster["file"]["id"]),
        enrollment_ops_headers), expected_status=201)

    validate_success(api.suspend_client(client_id, {"reason": "Contract review"},
                                        billing_ops_headers))
    validate_success(api.reinstate_client(client_id, billing_ops_headers))
    validate_success(api.close_client(client_id, billing_ops_headers))

    failed = get_success_data(api.get_enrollment(enrollment["id"], ENROLLMENT_OPS))
    assert failed["enrollment_status"] == "ACTIVATION_FAILED"

    refused = api.create_session(enrollment["id"], {
        "session_date": "2026-09-08T09:00:00Z",
        "session_week": 1,
        "recorded_via": "SENSOR",
        "planned_reps": 12,
        "planned_minutes": 18,
    }, enrollment_ops_headers)
    validate_error(refused, ApiErrorId.ERR_SESSION_ACTIVATION_FAILED, expected_status=409)

    member_after = get_success_data(api.get_member(member["id"], ENROLLMENT_OPS))
    assert member_after["member_status"] == "INELIGIBLE"
    assert member_after["eligibility_basis"] == "COVERAGE_TERM"


def test_a_booking_against_a_deactivated_clinician_is_refused_by_clinician_state(api,
                                                                                clinical_ops_headers,
                                                                                enrollment_ops_headers):
    """PRD §3.4: "The three booking constraints are, in order of evaluation:
    clinician availability and existence, then timeline geometry, then weekly capacity."
    PRD §3.4: "a clinician may be limited and restored freely, but deactivation is terminal."

    Design: Difficulty/cross_entity_state_dependency/appointment_booking_requires_available_clinician
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True, include_nadia=True, activate=True)
    enrollment_id = scenario["enrollment_id"]
    nadia_id = scenario["nadia_id"]

    validate_success(api.deactivate_clinician(nadia_id, clinical_ops_headers))
    read_back = get_success_data(api.get_clinician(nadia_id, CLINICAL_OPS))
    assert read_back["clinician_status"] == "DEACTIVATED", "deactivation is terminal"

    refused = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": nadia_id,
        "appointment_date": "2026-09-08T00:00:00Z",
        "start_minute": 1200,
        "duration_minutes": 15,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS)
    validate_error(refused, ApiErrorId.ERR_INVALID_REFERENCE, expected_status=422)


def test_a_conducted_review_on_a_stale_enrollment_is_refused_by_enrollment_state(api,
                                                                                clinical_ops_headers,
                                                                                enrollment_ops_headers,
                                                                                clinical_review_service_headers):
    """PRD §2.10: "conducting a clinical review whose enrollment is not in the
    review queue, which fails with `ERR_ENROLLMENT_NOT_IN_REVIEW`".
    PRD §3.3: "Attempting to conduct a review whose enrollment is not
    `PENDING_CLINICAL_REVIEW` is refused with `ERR_ENROLLMENT_NOT_IN_REVIEW`".

    Design: Difficulty/cross_entity_state_dependency/clinical_review_conduct_requires_enrollment_in_review_queue
    """
    from test_helpers import make_clinician_headers

    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    track_id = scenario["acute_track"]["id"]
    clinician_headers = make_clinician_headers(dana_id)

    first_review = seed_review(enrollment_id, dana_id, notes="Knee OA, acute track")
    conduct_review(first_review["id"], track_id, dana_id)

    # A second, still-SUBMITTED review on the same enrollment: the enrollment has
    # already moved out of the review queue, so this one cannot be conducted.
    second_review = seed_review(enrollment_id, dana_id, notes="Reviewing again")

    refused = api.conduct_clinical_review(
        second_review["id"], conduct_review_payload(track_id), clinician_headers)
    validate_error(refused, ApiErrorId.ERR_ENROLLMENT_NOT_IN_REVIEW, expected_status=409)

    untouched = get_success_data(api.get_clinical_review(second_review["id"], ENROLLMENT_OPS))
    assert untouched["review_status"] == "SUBMITTED"
    assert untouched["conducted_at"] is None


def test_deny_on_an_enrollment_with_no_pending_review_is_refused(api, clinical_ops_headers,
                                                                 enrollment_ops_headers,
                                                                 clinical_review_service_headers):
    """PRD §2.10: "approving or denying a handoff when no transition review is
    pending on the enrollment, which fails with `ERR_TRANSITION_NOT_PENDING`."
    PRD §3.3: "Attempting to approve or deny when no transition review is pending
    on the enrollment is refused with `ERR_TRANSITION_NOT_PENDING`."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_not_awaiting_review_outranks_reviewer_mismatch_on_deny
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]

    # The enrollment is ACTIVE: it never had a pending transition review at all.
    scenario["enrollment"] = activate_enrollment(
        enrollment_id, scenario["file_id"], dana_id,
        scenario["acute_track"]["id"], scenario["leo_id"])

    refused = api.deny_transition_review(
        enrollment_id, deny_transition_payload(dana_id), clinical_review_service_headers)
    validate_error(refused, ApiErrorId.ERR_TRANSITION_NOT_PENDING, expected_status=409)

    unchanged = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert unchanged["enrollment_status"] == "ACTIVE"


def test_deny_on_an_unknown_enrollment_reports_the_existence_failure(api, clinical_ops_headers,
                                                                     clinical_review_service_headers):
    """PRD §2.9: "the leftmost unknown segment determines the failure and the
    response is the 404 carrying `ERR_RESOURCE_NOT_FOUND`. A request that names an
    unknown inner resource under a known outer resource resolves the outer
    resource first and then reports the inner failure".
    PRD §3.3: "a different clinician attempting to deny is refused with
    `ERR_TRANSITION_REVIEWER_MISMATCH` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/unknown_enrollment_outranks_reviewer_mismatch_on_deny
    """
    set_clock()
    clinicians = setup_clinicians()
    unknown_reviewer_id = clinicians["leo"]["id"]

    refused = api.deny_transition_review(
        "11111111-2222-4333-8444-555555555555",
        deny_transition_payload(unknown_reviewer_id),
        clinical_review_service_headers)
    validate_error(refused, ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)
    assert refused.json()["data"]["error_id"] != "ERR_TRANSITION_NOT_PENDING", (
        "existence outranks the state precondition"
    )
    assert refused.json()["data"]["error_id"] != "ERR_TRANSITION_REVIEWER_MISMATCH", (
        "the acting clinician matches nothing on a non-existent enrollment"
    )
