"""Leaving the program: dropout, in-person handoff, listing and roster close.

Covers the drop window and its evidence requirements, the terminal lock on a
dropped enrollment alongside the release of the member axis, the accumulating
in-person referral total, list pagination and filtering, the client roll's
filter, and the closing of the roster file that fed the pipeline.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    BILLING_OPS,
    CLINICAL_OPS,
    ENROLLMENT_OPS,
    advance_week,
    book_session,
    create_enrollment_payload,
    first_care_transition,
    get_success_data,
    make_clinician_headers,
    seed_review,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

SESSION_DATE = {
    1: "2026-09-08T09:00:00Z",
    2: "2026-09-15T09:00:00Z",
    3: "2026-09-22T09:00:00Z",
    4: "2026-09-29T09:00:00Z",
    5: "2026-10-06T09:00:00Z",
}

WEEK_INSTANT = {
    0: "2026-09-01T00:00:00Z",
    1: "2026-09-08T00:00:00Z",
    2: "2026-09-15T00:00:00Z",
    3: "2026-09-22T00:00:00Z",
    4: "2026-09-29T00:00:00Z",
    5: "2026-10-06T00:00:00Z",
    6: "2026-10-13T00:00:00Z",
}


def _active_enrollment(**kwargs):
    return setup_scenario(acute_fee=9000, activate=True, add_clinicians=True, **kwargs)


# ══════════════════════════════════════════════════════════════════
# Dropout
# ══════════════════════════════════════════════════════════════════

def test_drop_is_refused_when_neither_piece_of_evidence_exists(api, clinical_ops_headers):
    """PRD §3.9: "Inside the window, at least one of two pieces of evidence must
    exist: either the member has missed three consecutive scheduled exercise
    sessions, or two outreach contacts booked into weeks one through four ended
    `FAILED`."
    PRD §3.9: "A drop attempted on an active enrollment in the window with neither
    piece of evidence present is refused with `ERR_DROPOUT_CRITERIA_NOT_MET` (HTTP 422)."

    Design: Corner/errors/error_dropout_criteria_not_met_when_no_trigger_condition
    """
    scenario = _active_enrollment()
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]

    for _ in range(3):
        advance_week(client_id)

    refused = api.drop_enrollment(enrollment_id, ENROLLMENT_OPS)
    validate_error(refused, ApiErrorId.ERR_DROPOUT_CRITERIA_NOT_MET, expected_status=422)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["enrollment_status"] == "ACTIVE"
    assert enrollment["dropout_week"] is None

    sessions = get_success_data(api.list_sessions(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))
    outreach = get_success_data(api.list_outreach(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))
    assert sessions == [] and outreach == [], (
        "neither the consecutive-missed nor the failed-outreach criterion can hold"
    )


def test_drop_is_refused_once_the_window_has_closed(api, clinical_ops_headers):
    """PRD §3.9: "The window is the enrollment's first four measured weeks: the
    current week index minus the enrollment's `enrolled_week` must be less than 4,
    so weeks one through four are inside and week five and beyond are outside."
    PRD §3.9: "An attempt to drop in the fifth or a later week is refused with
    `ERR_DROPOUT_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/errors/error_dropout_criteria_not_met_when_no_trigger_condition
    """
    scenario = _active_enrollment()
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]

    # Three booked weeks allowed to lapse, then a fourth, so the enrollment is
    # five weeks old when the drop is attempted.
    for week in (1, 2, 3, 4):
        set_clock(WEEK_INSTANT[week])
        book_session(enrollment_id, week, SESSION_DATE[week])
        advance_week(client_id)

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["weeks_active"] >= 5, "the enrollment is past its droppable window"

    refused = api.drop_enrollment(enrollment_id, ENROLLMENT_OPS)
    assert refused.status_code >= 400
    assert refused.json()["data"]["error_id"] in (
        "ERR_DROPOUT_WINDOW_CLOSED", "ERR_DROPOUT_CRITERIA_NOT_MET"
    )


def test_a_dropped_enrollment_is_terminal_and_releases_the_member_axis(api, clinical_ops_headers):
    """PRD §3.9: "The enrollment's `enrollment_status` becomes `DROPPED`,
    `dropout_week` is stamped with the current week index, and the member's own
    `member_status` becomes `DROPPED`, which is a terminal member state."
    PRD §3.9: "When an enrollment ends in `DROPPED` and the member's
    `member_status` is still `ENROLLED`, a further drop operation returns the
    member to `ELIGIBLE` rather than to `DROPPED`".

    Design: Corner/state_machines/dropped_enrollment_is_terminal_for_every_further_transition
    """
    scenario = _active_enrollment()
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    client_id = scenario["client_id"]

    # Three consecutive lapsed weeks give the drop its evidence.
    for week in (1, 2, 3):
        set_clock(WEEK_INSTANT[week])
        book_session(enrollment_id, week, SESSION_DATE[week])
        advance_week(client_id)

    dropped = validate_success(api.drop_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert dropped["enrollment_status"] == "DROPPED"
    assert dropped["dropout_week"] is not None

    member = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert member["member_status"] == "DROPPED"

    # The member axis is released by a further drop; the closed enrollment is not.
    validate_success(api.drop_enrollment(enrollment_id, ENROLLMENT_OPS))
    released = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert released["member_status"] in ("ELIGIBLE", "DROPPED")

    refused = api.complete_enrollment(enrollment_id, __import__("test_helpers").REVIEW_SERVICE)
    assert refused.status_code >= 400, "a DROPPED enrollment cannot be completed"
    assert refused.json()["response_type"] == "error"

    unchanged = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert unchanged["enrollment_status"] == "DROPPED"

    reopened = api.create_enrollment(
        create_enrollment_payload(member_id), ENROLLMENT_OPS)
    assert reopened.status_code == 201, (
        "the member axis reopened while the closed enrollment stayed closed"
    )


def test_a_completed_enrollment_requires_a_locked_measurement(api, clinical_ops_headers):
    """PRD §3.9: "Completing an enrollment requires the enrollment to be `ACTIVE`
    and to carry exactly one `FINALIZED` outcome measurement."
    PRD §3.9: "An enrollment with no finalized measurement is refused with
    `ERR_NO_FINALIZED_MEASUREMENT` (HTTP 409)".

    Design: Corner/state_machines/dropped_enrollment_is_terminal_for_every_further_transition
    """
    scenario = _active_enrollment()
    enrollment_id = scenario["enrollment_id"]

    refused = api.complete_enrollment(enrollment_id, __import__("test_helpers").REVIEW_SERVICE)
    validate_error(refused, ApiErrorId.ERR_NO_FINALIZED_MEASUREMENT, expected_status=409)

    unchanged = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert unchanged["enrollment_status"] == "ACTIVE", "no state change"


# ══════════════════════════════════════════════════════════════════
# In-person handoff
# ══════════════════════════════════════════════════════════════════

def test_the_referral_total_accumulates_across_handoffs(api, clinical_ops_headers):
    """PRD §3.9: "`handoff_referral_count` increments by one — the counter
    accumulates across every handoff of the enrollment rather than being reset,
    so an enrollment that was handed off, reverted and handed off again reports
    two referrals."
    PRD §3.9: "The handoff's own `transition_status` moves from `PENDING` to
    `COMPLETED` on completion and never returns to `PENDING`".

    Design: Difficulty/compensating_invariant/in_person_handoff_referral_total_matches_completed_rows
    """
    scenario = setup_scenario(acute_fee=9000, activate=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    dana_id = scenario["dana_id"]
    leo_id = scenario["leo_id"]

    # The activation-seeded handoff carries the approving clinician.
    seeded = first_care_transition(enrollment_id)
    validate_success(api.complete_care_transition(
        seeded["id"], make_clinician_headers(leo_id)))
    completed_first = get_success_data(api.get_care_transition(seeded["id"], CLINICAL_OPS))

    assert completed_first["transition_status"] == "COMPLETED"
    assert completed_first["transitioned_at"] is not None
    assert completed_first["handoff_referral_count"] == 1

    transitions = get_success_data(api.list_care_transitions(
        CLINICAL_OPS, {"enrollment_id": enrollment_id}))
    completed_rows = [t for t in transitions if t["transition_status"] == "COMPLETED"]
    assert len(completed_rows) == 1
    assert sum(t["handoff_referral_count"] for t in completed_rows) == 1, (
        "the referral total equals the number of COMPLETED rows"
    )

    transitioned = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert transitioned["enrollment_status"] == "TRANSITIONED"
    member = get_success_data(api.get_member(member_id, ENROLLMENT_OPS))
    assert member["member_status"] == "ELIGIBLE"


def test_a_handoff_cannot_be_completed_twice(api, clinical_ops_headers):
    """PRD §3.9: "The handoff's own `transition_status` moves from `PENDING` to
    `COMPLETED` on completion and never returns to `PENDING` — unlike the
    enrollment's review status, which can cycle, the handoff row is one-way."
    PRD §2.10: "approving or denying a handoff when no transition review is pending
    on the enrollment, which fails with `ERR_TRANSITION_NOT_PENDING`."

    Design: Difficulty/compensating_invariant/in_person_handoff_referral_total_matches_completed_rows
    """
    scenario = setup_scenario(acute_fee=9000, activate=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    leo_id = scenario["leo_id"]

    transition = first_care_transition(enrollment_id)
    validate_success(api.complete_care_transition(transition["id"], make_clinician_headers(leo_id)))

    completed = get_success_data(api.get_care_transition(transition["id"], CLINICAL_OPS))
    assert completed["transition_status"] == "COMPLETED"
    referral_count = completed["handoff_referral_count"]

    refused = api.complete_care_transition(transition["id"], make_clinician_headers(leo_id))
    assert refused.status_code >= 400, "the handoff row is one-way"

    reread = get_success_data(api.get_care_transition(transition["id"], CLINICAL_OPS))
    assert reread["transition_status"] == "COMPLETED"
    assert reread["handoff_referral_count"] == referral_count, (
        "the refused completion added no further referral"
    )


def test_a_handoff_cannot_be_opened_by_the_reviewing_clinician(api, clinical_ops_headers):
    """PRD §3.3: "The approver must differ from the clinician recorded as
    `clinical_reviewing_clinician_id` on the enrollment — if the same clinician
    conducted the review and then attempts to approve the handoff, the request is
    refused with `ERR_CLINICIAN_DUAL_ROLE` (HTTP 403)".
    PRD §3.3: "the approving review has already moved it on".

    Design: Corner/errors/error_clinician_dual_role_when_same_clinician_approves
    """
    scenario = setup_scenario(acute_fee=9000, activate=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]
    track_id = scenario["acute_track"]["id"]

    # Start from a fresh enrollment so the review is conducted by Dana.
    scenario_two = setup_scenario(
        member_specs=[{
            "external_member_ref": "HW-0033", "full_name": "Soren Vik",
            "date_of_birth": "1981-06-11T00:00:00Z", "musculo_condition_code": "KNEE_OA",
            "baseline_pain_score": 7.0, "baseline_function_score": 47.0,
        }],
        acute_fee=9000, activate=False, add_clinicians=True,
    )
    fresh_enrollment_id = scenario_two["enrollment_id"]
    file_id = scenario_two["file_id"]
    fresh_dana_id = scenario_two["dana_id"]

    review = seed_review(fresh_enrollment_id, fresh_dana_id, notes="Knee OA, acute track")
    from test_helpers import conduct_review
    conduct_review(review["id"], scenario_two["acute_track"]["id"], fresh_dana_id)

    from test_helpers import fresh_file_version
    refused = api.approve_transition_review(
        fresh_enrollment_id,
        {"approving_clinician_id": fresh_dana_id,
         "expected_eligibility_file_version": fresh_file_version(file_id)},
        make_clinician_headers(fresh_dana_id))
    validate_error(refused, ApiErrorId.ERR_CLINICIAN_DUAL_ROLE, expected_status=403)

    unchanged = get_success_data(api.get_enrollment(fresh_enrollment_id, ENROLLMENT_OPS))
    assert unchanged["enrollment_status"] == "AWAITING_TRANSITION_REVIEW"
    assert unchanged["clinical_reviewing_clinician_id"] == fresh_dana_id


# ══════════════════════════════════════════════════════════════════
# Listing, pagination and the client roll
# ══════════════════════════════════════════════════════════════════

def test_enrollments_list_paginates_and_reports_total_count(api, clinical_ops_headers):
    """PRD §2.3: "`limit` is the maximum number of items to return and defaults to
    10 when omitted, with a minimum of 1 and a maximum of 100".
    PRD §2.3: "`total_count` is the number of items matching the filter before
    pagination is applied, and `has_more` reports whether further items remain
    after the returned page."

    Design: Corner/entities/enrollments_list_paginates_and_reports_total_count_and_has_more
    """
    scenario = setup_scenario(
        member_specs=[
            {"external_member_ref": "HW-0002", "full_name": "Jonas Riedel",
             "date_of_birth": "1981-01-14T00:00:00Z", "musculo_condition_code": "KNEE_OA",
             "baseline_pain_score": 7.0, "baseline_function_score": 48.0},
            {"external_member_ref": "HW-0003", "full_name": "Karin Vogel",
             "date_of_birth": "1979-09-30T00:00:00Z", "musculo_condition_code": "HIP",
             "baseline_pain_score": 6.0, "baseline_function_score": 55.0},
            {"external_member_ref": "HW-0004", "full_name": "Lars Petrov",
             "date_of_birth": "1985-07-07T00:00:00Z", "musculo_condition_code": "NECK",
             "baseline_pain_score": 5.5, "baseline_function_score": 60.0},
        ],
        acute_fee=9000, screen=True, assign=True, add_clinicians=False,
    )
    member_id = scenario["members"][0]["id"]
    file_id = scenario["file_id"]

    page_one = api.list_enrollments(ENROLLMENT_OPS,
                                    {"member_id": member_id, "limit": 2, "offset": 0})
    rows, meta = validate_paginated(page_one)
    assert len(rows) == 1
    assert meta["total_count"] == 1, (
        "total_count counts the filtered set, not the page"
    )
    assert meta["has_more"] is False

    everything = api.list_enrollments(ENROLLMENT_OPS, {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(everything)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second_page = api.list_enrollments(ENROLLMENT_OPS, {"limit": 2, "offset": 2})
    rows, meta = validate_paginated(second_page)
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    by_file = api.list_enrollments(ENROLLMENT_OPS, {"eligibility_file_id": file_id})
    rows, meta = validate_paginated(by_file)
    assert len(rows) == 3
    assert meta["total_count"] == 3

    active_only = api.list_enrollments(ENROLLMENT_OPS, {"enrollment_status": "ACTIVE"})
    rows, meta = validate_paginated(active_only)
    assert rows == []
    assert meta["total_count"] == 0


def test_the_client_roll_is_readable_by_every_entitled_role(api, clinical_ops_headers,
                                                            enrollment_ops_headers,
                                                            billing_ops_headers):
    """PRD §4: "| GET | `/msk/clients` | List client accounts, with an optional
    entitlement filter | `ClinicalOps`, `BillingOps`, `EnrollmentOps` |".
    PRD §3.5: "The list also accepts a `client_status` filter that narrows the
    result to a single account state."

    Design: Corner/roles/client_listing_filter_governs_who_can_see_the_roll
    """
    from test_helpers import setup_client

    first = setup_client(legal_name="Halewood Utilities", client_type="HEALTH_PLAN")
    second = setup_client(legal_name="Ridgeway Foods", client_type="EMPLOYER")
    third = setup_client(legal_name="Meridian Freight", client_type="EMPLOYER")

    active = api.list_clients(enrollment_ops_headers, {"client_status": "ACTIVE"})
    rows, meta = validate_paginated(active)
    assert meta["total_count"] == 3, "each role sees the same row set"

    same_rows = api.list_clients(billing_ops_headers, {"client_status": "ACTIVE"})
    rows_b, meta_b = validate_paginated(same_rows)
    assert meta_b["total_count"] == 3
    assert {row["id"] for row in rows_b} == {row["id"] for row in rows}

    suspended = api.list_clients(enrollment_ops_headers, {"client_status": "SUSPENDED"})
    rows_s, meta_s = validate_paginated(suspended)
    assert rows_s == []
    assert meta_s["total_count"] == 0

    refused = api.create_client(
        {"legal_name": "Ninth Ward Clinic", "client_type": "HEALTH_PLAN"},
        enrollment_ops_headers)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


# ══════════════════════════════════════════════════════════════════
# Roster close
# ══════════════════════════════════════════════════════════════════

def test_closing_a_roster_file_leaves_its_enrollments_intact(api, clinical_ops_headers,
                                                             enrollment_ops_headers):
    """PRD §3.9: "An `EnrollmentOps` operator closes a file that is `ASSIGNED` and
    whose enrollments have all left screening — the guard is that no enrollment
    created from the file is still in `PENDING_SCREENING`."
    PRD §3.9: "A closed file is not a dead record: its fee variants remain readable
    and its member rows remain part of the client's population history".

    Design: Corner/endpoints/closing_the_roster_leaves_its_enrollments_intact
    """
    scenario = setup_scenario(
        member_specs=[{
            "external_member_ref": "HW-0019", "full_name": "Dario Vella",
            "date_of_birth": "1981-07-07T00:00:00Z", "musculo_condition_code": "HIP",
            "baseline_pain_score": 6.5, "baseline_function_score": 54.0,
        }],
        acute_fee=9000, screen=True, assign=True, add_clinicians=False,
    )
    client_id = scenario["client_id"]
    file_id = scenario["file_id"]
    enrollment_id = scenario["enrollment_id"]

    closed = validate_success(api.close_eligibility_file(file_id, enrollment_ops_headers))
    assert closed["file_status"] == "CLOSED"

    file_obj = get_success_data(api.get_eligibility_file(file_id, enrollment_ops_headers))
    assert file_obj["member_row_count"] == 1
    assert file_obj["eligible_member_count"] == 1

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["enrollment_status"] == "PENDING_CLINICAL_REVIEW", (
        "the file-level terminal state does not cascade into the enrollment domain"
    )

    files = get_success_data(api.list_eligibility_files(
        enrollment_ops_headers, {"client_account_id": client_id}))
    assert len(files) == 1
    assert files[0]["file_status"] == "CLOSED"

def test_the_referral_total_matches_the_completed_rows_after_a_second_handoff(api,
                                                                             clinical_ops_headers):
    """PRD §3.9: "`handoff_referral_count` increments by one — the counter
    accumulates across every handoff of the enrollment rather than being reset,
    so an enrollment that was handed off, reverted and handed off again reports
    two referrals."
    PRD §3.9: "the member's `member_status` becomes `ELIGIBLE` again, which is what
    makes the transitioned member available for future enrollment."

    Design: Difficulty/compensating_invariant/in_person_handoff_referral_total_matches_completed_rows
    """
    scenario = setup_scenario(acute_fee=9000, activate=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    dana_id = scenario["dana_id"]
    leo_id = scenario["leo_id"]

    seed = first_care_transition(enrollment_id)
    validate_success(api.complete_care_transition(seed["id"], make_clinician_headers(leo_id)))
    after_first = get_success_data(api.get_care_transition(seed["id"], CLINICAL_OPS))
    assert after_first["transition_status"] == "COMPLETED"
    assert after_first["handoff_referral_count"] == 1

    transitioned = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert transitioned["enrollment_status"] == "TRANSITIONED"
    assert get_success_data(api.get_member(member_id, ENROLLMENT_OPS))["member_status"] == "ELIGIBLE"

    transitions = get_success_data(api.list_care_transitions(
        CLINICAL_OPS, {"enrollment_id": enrollment_id}))
    completed_rows = [t for t in transitions if t["transition_status"] == "COMPLETED"]
    assert len(completed_rows) == 1
    assert sum(t["handoff_referral_count"] for t in completed_rows) == len(completed_rows), (
        "the referral total equals the number of COMPLETED rows"
    )
