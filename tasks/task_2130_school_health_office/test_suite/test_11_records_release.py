"""Releasing health records: redaction levels, the consent-decision-handover walk,
the package count and the segregated, time-boxed release."""

import pytest

from test_helpers import *  # noqa: F401,F403


def test_a_denied_request_records_the_decider_and_zeroes_the_package(api, admin_headers):
    """PRD §3.9: "`GRANT` moves `CONSENT_PENDING` to `AWAITING_DECISION`, stamping
    `consent_granted_at` with the logical clock and setting `expires_at` to 30 days after that
    instant."
    PRD §3.9: "A `decision` of `DENY` sets `decided_by_user_id`, moves the request to `DENIED` and
    zeroes `release_package_item_count`."

    Design: Corner/state_machines/disclosure_deny_branch_zeroes_package_and_records_decider
    """
    school = create_school(name="Ellis Elementary", building_code="ELL33")
    student = create_student(school["id"], full_name="Eli Brandt", grade_level=7,
                             date_of_birth="2013-06-06T00:00:00Z", privacy_hold=False)
    request = create_disclosure(student["id"], requester_type="EXTERNAL_PROVIDER",
                               requester_reference="Northside Pediatrics", scope=["VISITS"],
                               purpose_code="TREATMENT")
    assert request["redaction_level"] == "NONE"
    submit_disclosure(request["id"])
    consented = consent_disclosure(request["id"], student["id"])
    assert consented["consent_granted_at"].startswith("2026-08-01T00:00:00")
    assert consented["expires_at"].startswith("2026-08-31T00:00:00")

    resp = api.decide_disclosure_request(request["id"], {"decision": "DENY"},
                                         TEST_USERS["physician_alt_headers"])
    data = validate_success(resp, 200)
    assert_disclosure_request(data)
    assert data["status"] == "DENIED"
    assert data["decided_by_user_id"] == PHYSICIAN_USER_ID_ALT
    assert data["release_package_item_count"] == 0
    assert data.get("released_at") is None


def test_a_partial_redaction_withholds_mental_health_visits_and_controlled_orders(api, admin_headers):
    """PRD §3.9: "Otherwise, if the `purpose_code` is `ENROLLMENT` or `RESEARCH`, or if
    `MEDICATIONS` appears in the `scope` while the `requester_type` is `AGENCY`, the level is
    `PARTIAL`."
    PRD §3.9: "Where the redaction level is `PARTIAL`, two withholdings then apply to those counts:
    encounters whose `complaint_code` is `MENTAL_HEALTH` are subtracted from the visits count, and
    orders whose `is_controlled` flag is true — that is, orders for `METHYLPHENIDATE` — are
    subtracted from the medications count."
    PRD §3.9: "On success `released_by_user_id` is set to the acting identifier, `released_at` is
    stamped with the clock, the request becomes `RELEASED`, and the package is finally counted."

    Design: Corner/calculations/disclosure_partial_redaction_withholds_mental_health_and_controlled_rows
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Sable Elementary", "building_code": "SBL47"},
        student_overrides={"full_name": "Sam Okoro", "grade_level": 8,
                           "date_of_birth": "2012-03-13T00:00:00Z", "privacy_hold": False})
    school_id, nurse_id, student_id = base["school"]["id"], base["nurse"]["id"], base["student"]["id"]
    set_clock(MONDAY_0900)
    for complaint, note in (("MENTAL_HEALTH", "Counselling handoff arranged"),
                            ("ILLNESS", "Afebrile, cleared")):
        visit = open_visit(student_id, school_id, nurse_id, complaint_code=complaint)
        assess_visit(visit["id"], nurse_id, note)
        dispose_visit(visit["id"], nurse_id, "RETURN_TO_CLASS")
        close_visit(visit["id"], nurse_id)

    controlled = create_order(student_id, nurse_id, medication_code="METHYLPHENIDATE",
                              route="ORAL", dose_amount=10, dose_unit="MG", max_doses_per_day=1)
    grant_order_consent(controlled["id"], student_id)
    plain = create_order(student_id, nurse_id)
    grant_order_consent(plain["id"], student_id)
    assert validate_success(api.get_medication_authorization(
        controlled["id"], admin_headers))["is_controlled"] is True
    assert validate_success(api.get_medication_authorization(
        plain["id"], admin_headers))["is_controlled"] is False

    request = create_approved_disclosure(
        student_id, requester_type="SCHOOL_STAFF",
        requester_reference="District enrolment office",
        scope=["VISITS", "MEDICATIONS"], purpose_code="ENROLLMENT")
    assert request["redaction_level"] == "PARTIAL"

    released = validate_success(api.release_disclosure_request(
        request["id"], TEST_USERS["records_officer_alt_headers"]))
    assert released["status"] == "RELEASED"
    assert released["release_package_item_count"] == 2, \
        "one non-mental-health visit plus one non-controlled order"
    assert released["decided_by_user_id"] == PHYSICIAN_USER_ID
    assert released["released_by_user_id"] == RECORDS_OFFICER_USER_ID_ALT
    assert released["released_at"].startswith("2026-08-03T09:00:00")


def test_submitting_a_draft_request_moves_it_to_consent_pending(api, admin_headers):
    """PRD §3.9: "Submission by the records officer moves `DRAFT` to `CONSENT_PENDING` and
    recomputes the redaction level."
    PRD §3.9: "The request opens at `DRAFT` with `release_package_item_count` at 0 and a
    `redaction_level` computed immediately."

    Design: Corner/endpoints/disclosure_submit_action_advances_request_to_consent_pending
    """
    school = create_school(name="Cairn Elementary", building_code="CRN57")
    student = create_student(school["id"], full_name="Cara Volk", grade_level=6,
                             date_of_birth="2014-01-01T00:00:00Z", privacy_hold=False)
    request = create_disclosure(student["id"], requester_type="AGENCY",
                               requester_reference="State health survey",
                               scope=["SCREENINGS"], purpose_code="RESEARCH")
    assert request["status"] == "DRAFT"
    assert request["redaction_level"] == "PARTIAL", "a RESEARCH purpose code forces PARTIAL"
    assert request["release_package_item_count"] == 0

    resp = api.submit_disclosure_request(request["id"], TEST_USERS["records_officer_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "CONSENT_PENDING"
    assert data["redaction_level"] == "PARTIAL"
    assert data.get("consent_granted_at") is None
    assert data.get("expires_at") is None


def test_the_releasing_officer_must_differ_from_the_deciding_operator(api, admin_headers):
    """PRD §3.9: "Only a records officer whose `X-User-ID` differs from the stored
    `decided_by_user_id` may release an `APPROVED` request, and only while the clock is strictly
    before `expires_at` — a release attempted exactly at the expiry instant is refused with
    `ERR_DISCLOSURE_CONSENT_EXPIRED`."
    PRD §2.9: "All three violations return the same code, `ERR_SEGREGATION_OF_DUTIES` (HTTP 403),
    and that check sits at ladder position 22 — guarding dose preparation, the dose outcome step,
    screening follow-up and disclosure release."

    Design: Corner/rbac/releasing_officer_cannot_reuse_the_deciding_operator_id
    """
    school = create_school(name="Hollow Elementary", building_code="HLW68")
    student = create_student(school["id"], full_name="Hal Reyes", grade_level=9,
                             date_of_birth="2011-04-04T00:00:00Z", privacy_hold=False)
    request = create_approved_disclosure(
        student["id"], physician_user_id="op-77", requester_type="EXTERNAL_PROVIDER",
        requester_reference="Harborview Clinic", scope=["VISITS"], purpose_code="TREATMENT")
    assert request["status"] == "APPROVED"
    assert request["decided_by_user_id"] == "op-77"

    same_operator = api.release_disclosure_request(request["id"], make_records_officer_headers("op-77"))
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    held = validate_success(api.get_disclosure_request(
        request["id"], TEST_USERS["records_officer_headers"]))
    assert held["status"] == "APPROVED"
    assert held.get("released_at") is None

    released = validate_success(api.release_disclosure_request(
        request["id"], TEST_USERS["records_officer_alt_headers"]))
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == RECORDS_OFFICER_USER_ID_ALT
    assert released["release_package_item_count"] == 0, "the child has no CLOSED encounter"


def test_releasing_a_request_still_in_draft_is_refused(api, admin_headers):
    """PRD §3.9: "The request then walks `DRAFT` → `CONSENT_PENDING` → `AWAITING_DECISION` →
    `APPROVED` → `RELEASED`."
    PRD §2.7: "The disclosure check guards submit, guardian-consent, decide and release."

    Design: Corner/errors/error_disclosure_invalid_state_on_release_of_a_draft_request
    """
    school = create_school(name="Orchard Elementary", building_code="ORC79")
    student = create_student(school["id"], full_name="Ora Lindqvist", grade_level=5,
                             date_of_birth="2015-06-26T00:00:00Z", privacy_hold=False)
    request = create_disclosure(student["id"], requester_type="EXTERNAL_PROVIDER",
                               requester_reference="Orchard Clinic",
                               scope=["VISITS", "SCREENINGS"], purpose_code="TREATMENT")

    resp = api.release_disclosure_request(request["id"], TEST_USERS["records_officer_alt_headers"])
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_disclosure_request(
        request["id"], TEST_USERS["records_officer_headers"]))
    assert unchanged["status"] == "DRAFT"
    assert unchanged.get("released_at") is None
    assert unchanged.get("released_by_user_id") is None
    assert unchanged["release_package_item_count"] == 0


def test_a_privacy_hold_blocks_the_physician_from_approving_the_release(api, admin_headers):
    """PRD §3.9: "If the student's `privacy_hold` is true and the `requester_type` is anything
    other than `GUARDIAN`, the level is `FULL`."
    PRD §3.9: "Approval requires the computed `redaction_level` not to be `FULL` — a fully redacted
    request cannot be approved, and the refusal is `ERR_PRIVACY_HOLD_BLOCKS_RELEASE` (HTTP 403) at
    ladder position 29 — and requires the clock to be strictly before `expires_at`, failing which
    the refusal is `ERR_DISCLOSURE_CONSENT_EXPIRED` (HTTP 409) at position 38."

    Design: Corner/errors/error_privacy_hold_blocks_release_on_the_physician_decision
    """
    school = create_school(name="Cedar Elementary", building_code="CDR93")
    student = create_student(school["id"], full_name="Cy Almeida", grade_level=8,
                             date_of_birth="2012-05-05T00:00:00Z", privacy_hold=True)
    request = create_disclosure(student["id"], requester_type="EXTERNAL_PROVIDER",
                               requester_reference="Cedar Family Practice",
                               scope=["VISITS", "MEDICATIONS"], purpose_code="TREATMENT")
    assert request["redaction_level"] == "FULL"
    submit_disclosure(request["id"])
    awaiting = consent_disclosure(request["id"], student["id"])
    assert awaiting["status"] == "AWAITING_DECISION"

    resp = api.decide_disclosure_request(request["id"], {"decision": "APPROVE"},
                                         TEST_USERS["physician_headers"])
    validate_error(resp, ApiErrorId.ERR_PRIVACY_HOLD_BLOCKS_RELEASE.value, 403)

    unchanged = validate_success(api.get_disclosure_request(
        request["id"], TEST_USERS["records_officer_headers"]))
    assert unchanged["status"] == "AWAITING_DECISION"
    assert unchanged.get("decided_by_user_id") is None
    assert unchanged["release_package_item_count"] == 0


def test_a_release_attempted_exactly_at_the_expiry_instant_is_refused(api, admin_headers):
    """PRD §3.9: "Only a records officer whose `X-User-ID` differs from the stored
    `decided_by_user_id` may release an `APPROVED` request, and only while the clock is strictly
    before `expires_at` — a release attempted exactly at the expiry instant is refused with
    `ERR_DISCLOSURE_CONSENT_EXPIRED`."
    PRD §3.9: "`GRANT` moves `CONSENT_PENDING` to `AWAITING_DECISION`, stamping
    `consent_granted_at` with the logical clock and setting `expires_at` to 30 days after that
    instant."

    Design: Corner/errors/error_disclosure_consent_expired_at_exactly_thirty_days
    """
    school = create_school(name="Dawnbrook Elementary", building_code="DWN94")
    student = create_student(school["id"], full_name="Dov Ellery", grade_level=6,
                             date_of_birth="2014-02-02T00:00:00Z", privacy_hold=False)
    request = create_approved_disclosure(
        student["id"], requester_type="EXTERNAL_PROVIDER",
        requester_reference="Dawn Pediatrics", scope=["VISITS"], purpose_code="TREATMENT")
    assert request["consent_granted_at"].startswith("2026-08-01T00:00:00")
    assert request["expires_at"].startswith("2026-08-31T00:00:00")
    assert request["status"] == "APPROVED"

    set_clock("2026-08-31T00:00:00Z")
    resp = api.release_disclosure_request(request["id"], TEST_USERS["records_officer_alt_headers"])
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_CONSENT_EXPIRED.value, 409)

    unchanged = validate_success(api.get_disclosure_request(
        request["id"], TEST_USERS["records_officer_headers"]))
    assert unchanged["status"] == "APPROVED"
    assert unchanged.get("released_at") is None
    assert unchanged["release_package_item_count"] == 0
