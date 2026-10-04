"""Application intake gates: duplicate rule, half-open open-period window,
announcement state gate, area of consideration, special-authority eligibility
documents, and list pagination.
"""
from test_helpers import (
    HR, ApiErrorId,
    api_client, create_announcement, create_classified_position,
    make_applicant_headers, register_applicant, set_clock,
    setup_open_announcement, submit_application, submit_application_payload,
    upload_document, verify_document, validate_error, validate_paginated,
    validate_success,
)


def test_duplicate_application_rejected(api):
    """PRD §3.4: "One application per applicant per announcement: a repeat
    pairing fails with `ERR_DUPLICATE_APPLICATION` (HTTP 409)."

    Design: Corner/validations/duplicate_application_rejected
    """
    ctx = setup_open_announcement()
    announcement = ctx["announcement"]
    ann = register_applicant()
    first = submit_application(announcement, ann)
    assert first["status"] == "RECEIVED"

    resp = api_client.submit_application(
        announcement["id"],
        submit_application_payload(ann["id"], claimed_experience_months=31),
        make_applicant_headers(ann["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)

    # Uniqueness is per (announcement, applicant): another applicant succeeds.
    bob = register_applicant()
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(bob["id"]),
        make_applicant_headers(bob["id"]))
    validate_success(resp, 201)


def test_open_period_half_open_bounds(api):
    """PRD §2.9: "applications are accepted while the logical clock is at or
    after `open_at` and strictly before `close_at`, so a submission landing at
    exactly `open_at` succeeds and one landing at exactly `close_at` is rejected
    with `ERR_OUTSIDE_OPEN_PERIOD`".

    Design: Corner/validations/open_period_half_open_bounds
    """
    ctx = setup_open_announcement(apply_clock=None)
    announcement = ctx["announcement"]

    early = register_applicant()
    set_clock("2026-09-05T00:00:00Z")  # exactly open_at: left-closed bound
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(early["id"]),
        make_applicant_headers(early["id"]))
    validate_success(resp, 201)

    late = register_applicant()
    set_clock("2026-09-20T00:00:00Z")  # exactly close_at: right-open bound
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(late["id"]),
        make_applicant_headers(late["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_OPEN_PERIOD)


def test_apply_to_draft_announcement_rejected(api):
    """PRD §3.4: "The announcement must be `OPEN`; otherwise the rejection is
    `ERR_ANNOUNCEMENT_NOT_OPEN` (HTTP 409)."

    Design: Corner/validations/apply_to_draft_or_closed_announcement_rejected
    """
    _series, position = create_classified_position()
    announcement = create_announcement(position["id"])  # stays DRAFT
    set_clock("2026-09-10T00:00:00Z")  # inside the declared window

    applicant = register_applicant()
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(applicant["id"]),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_ANNOUNCEMENT_NOT_OPEN)


def test_agency_only_area_of_consideration_enforced(api):
    """PRD §3.4: "The area of consideration must admit the applicant, else
    `ERR_OUTSIDE_AREA_OF_CONSIDERATION` (HTTP 422): `ALL_US_CITIZENS` requires
    `is_us_citizen`; `STATUS_CANDIDATES` additionally requires
    `is_current_federal_employee` or a verified preference; `AGENCY_ONLY`
    additionally requires the applicant's `agency_code` to equal the position's
    `org_code`."

    Design: Corner/validations/agency_only_area_of_consideration_enforced
    """
    ctx = setup_open_announcement(
        announcement_overrides={"area_of_consideration": "AGENCY_ONLY"})
    assert ctx["position"]["org_code"] == "OPM1"
    announcement = ctx["announcement"]

    outsider = register_applicant(agency_code="DOJ9")
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(outsider["id"]),
        make_applicant_headers(outsider["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_AREA_OF_CONSIDERATION)

    insider = register_applicant(agency_code="OPM1")
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(insider["id"]),
        make_applicant_headers(insider["id"]))
    validate_success(resp, 201)


def test_schedule_a_requires_verified_document(api):
    """PRD §3.4: "Finally, non-`COMPETITIVE` authorities demand a verified
    eligibility document of the mapped type at application time, else
    `ERR_ELIGIBILITY_DOC_REQUIRED` (HTTP 422): `VEOA` requires a verified
    `DD214`, `SCHEDULE_A` a verified `SCHEDULE_A_CERT`, and
    `NONCOMPETITIVE_SPOUSE` a verified `MILITARY_SPOUSE_ORDERS`, while
    `DIRECT_HIRE` demands nothing beyond the preference-verification rules of
    §3.3."

    Design: Corner/validations/schedule_a_requires_verified_document
    """
    ctx = setup_open_announcement(
        announcement_overrides={
            "hiring_authority": "SCHEDULE_A",
            "assessment_method": "UNRANKED",
        })
    announcement = ctx["announcement"]

    ann = register_applicant()  # no documents at all
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(ann["id"]),
        make_applicant_headers(ann["id"]))
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_DOC_REQUIRED)

    jay = register_applicant()
    document = upload_document(jay, "SCHEDULE_A_CERT")  # uploaded, not verified
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(jay["id"]),
        make_applicant_headers(jay["id"]))
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_DOC_REQUIRED)

    verify_document(document["id"])
    resp = api_client.submit_application(
        announcement["id"], submit_application_payload(jay["id"]),
        make_applicant_headers(jay["id"]))
    validate_success(resp, 201)


def test_applications_list_pagination(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope." and "every list
    endpoint returns its resources sorted by `created_at` in ascending order."

    Design: Corner/entities/applications_list_pagination
    """
    ctx = setup_open_announcement(apply_clock=None)
    announcement = ctx["announcement"]

    # Distinct submission instants make the created_at ordering deterministic.
    application_ids = []
    for day in ("2026-09-10T00:00:00Z", "2026-09-11T00:00:00Z", "2026-09-12T00:00:00Z"):
        set_clock(day)
        applicant = register_applicant()
        application = submit_application(announcement, applicant)
        application_ids.append(application["id"])

    resp = api_client.list_announcement_applications(
        announcement["id"], HR, params={"limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert [a["id"] for a in page1] == application_ids[:2]

    resp = api_client.list_announcement_applications(
        announcement["id"], HR, params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert [a["id"] for a in page2] == application_ids[2:]

    ids_page1 = {a["id"] for a in page1}
    ids_page2 = {a["id"] for a in page2}
    assert ids_page1.isdisjoint(ids_page2)
    assert ids_page1 | ids_page2 == set(application_ids)
