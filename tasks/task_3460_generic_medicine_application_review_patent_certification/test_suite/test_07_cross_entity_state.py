"""Queue A: cross_entity_state_dependency — gates keyed on another entity."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_applicant, make_reference_product, make_application, add_be_study,
    make_facility, schedule_inspection, record_outcome, submit_application,
    setup_submitted, approve_application, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_approval_requires_latest_inspection_passed():
    """PRD section 3.6: "For each such facility, only its latest-recorded
    non-`CANCELLED` outcome counts — outcomes are committed sequentially so
    ties cannot arise, and `created_at` is the fallback ordering key, never
    the resource `id`." PRD section 3.6: "Clearance demands that every
    facility's latest outcome be `PASSED` or `WAIVED`, and additionally that
    every foreign facility have at least one `PASSED` inspection for this
    application — a waiver never clears a foreign site." A FAILED latest
    outcome blocks; a later PASSED inspection on the same facility lifts the
    gate.

    Design: Difficulty/cross_entity_state_dependency/approval_requires_latest_inspection_passed
    """
    applicant = make_applicant(legal_name="Gate Generics")
    rld = make_reference_product(brand_name="Gatex")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"])
    facility = make_facility(applicant["id"], facility_name="Gate Plant")
    insp1 = schedule_inspection(facility["id"], app["id"],
                                scheduled_start_date="2026-09-05",
                                scheduled_end_date="2026-09-07")
    record_outcome(insp1["id"], "FAILED")
    submit_application(app["id"], applicant["id"])

    resp = api_client.approval_decision(app["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLEARANCE_FAILED)
    assert resp.status_code == 422

    insp2 = schedule_inspection(facility["id"], app["id"],
                                scheduled_start_date="2026-09-10",
                                scheduled_end_date="2026-09-12")
    record_outcome(insp2["id"], "PASSED")
    decided = validate_success(api_client.approval_decision(
        app["id"], {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided["status"] == "APPROVED", (
        "the gate reads the LATEST non-CANCELLED outcome per facility")


def test_supplement_creation_requires_approved_application():
    """PRD section 3.9: "Once an application stands `APPROVED`, its sponsor
    reports changes through `Supplement` records; filing one against an
    application in any other state fails with
    `ERR_APPLICATION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/supplement_creation_requires_approved_application
    """
    ctx = setup_submitted(with_facility=True)
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    headers = make_applicant_headers(ac_id)
    payload = {"change_type": "LABELING", "pathway": "CBE_30"}

    resp = api_client.create_supplement(app_id, payload, headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_APPROVED)
    assert resp.status_code == 409, "parent still RECEIVED: supplement refused"

    approve_application(app_id)
    supp = validate_success(api_client.create_supplement(app_id, payload, headers), 201)
    assert supp["review_status"] == "SUBMITTED", (
        "the supplement's creatable state is a pure function of the parent state")
