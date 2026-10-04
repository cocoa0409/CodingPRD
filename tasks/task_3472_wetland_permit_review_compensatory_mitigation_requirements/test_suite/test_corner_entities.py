"""Corner queue — entity conventions (PRD §2.4, §2.8, §3.1, §3.3).

Creation conventions, required-field and enum shape checks, server-computed
fields, per-resource 404s, and the applicant-filtered site list.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    JdStatus,
    NON_EXISTENT_UUID,
    assert_applicant,
    assert_application,
    assert_jd,
    confirm_case,
    create_applicant,
    create_applicant_payload,
    create_application,
    create_jd,
    create_site,
    create_site_payload,
    impact_line,
    setup_applicant_and_site,
    setup_case_opened,
    setup_site_with_issued_jd,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_corner_applicant_creation_conventions(api, system_admin_headers):
    """PRD §3.1: "The new applicant's `prior_violation_count` is initialized
    to 0".
    PRD §2.4: "Every resource carries an `id`, a server-minted UUID with no
    type prefix; a `created_at` timestamp; an `updated_at` timestamp; and a
    `version` integer."

    POST /wetland-permits/applicants returns 201 with the common fields
    populated and prior_violation_count 0.

    Design: Corner/entities/corner_applicant_creation_conventions
    """
    resp = api.create_applicant(create_applicant_payload(), system_admin_headers)
    data = validate_success(resp, 201)
    assert_applicant(data)
    assert data["prior_violation_count"] == 0
    assert isinstance(data["version"], int)


def test_corner_site_missing_watershed_rejected(api, system_admin_headers, reviewer_headers):
    """PRD §2.8: "Request shape: required fields present, enumerations valid,
    numbers in range, the `impacts` array non-empty with each line's resource
    type among the site's present types and a positive acreage, after-the-fact
    pathways carrying an `enforcement_case_id` whose case names the same
    responsible applicant, general pathways carrying a `general_permit_code`,
    `comment_period_days` within its allowed window, and
    `stewardship_entity_name` present where the mechanism demands it — any
    failure is `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "Registering a waters site ties the land to its owner: the
    payload names the owning `applicant_id`, a `site_name`, the two-letter
    `state_code` where the site sits, an eight-digit hydrologic unit
    `watershed_code`, the `total_acres` of the site (which must be greater
    than zero), and `resource_types_present`, a non-empty subset drawn from
    `EMERGENT_MARSH`, `FORESTED_WETLAND`, `OPEN_WATER`, and `STREAM`."

    Omitting watershed_code is rejected and nothing is persisted.

    Design: Corner/entities/corner_site_missing_watershed_rejected
    """
    applicant = create_applicant()
    payload = create_site_payload(applicant["id"])
    del payload["watershed_code"]
    resp = api.create_site(payload, system_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    data, meta = validate_paginated(
        api.list_sites(reviewer_headers, params={"applicant_id": applicant["id"]})
    )
    assert data == [], "no site is persisted after the rejected create"
    assert meta["total_count"] == 0


def test_corner_jd_created_in_draft(api):
    """PRD §3.1: "A new determination sits in `DRAFT`, and while it does both
    `issued_date` and `expiration_date` are null."

    Design: Corner/entities/corner_jd_created_in_draft
    """
    applicant, site = setup_applicant_and_site()
    jd = create_jd(site, rationale="Delineation under review")
    assert_jd(jd)
    assert jd["status"] == JdStatus.DRAFT.value
    assert jd["issued_date"] is None
    assert jd["expiration_date"] is None


def test_corner_application_computed_fields(api):
    """PRD §3.3: "At creation the system computes `total_impact_acres` as the
    sum of the impact lines' acreages, derives `is_after_the_fact` as true
    exactly for the two after-the-fact pathways, and derives
    `compensatory_mitigation_required` as true exactly when
    `total_impact_acres` is strictly greater than 0.10 acres."

    1.5 FORESTED_WETLAND + 0.5 STREAM acres on the INDIVIDUAL pathway:
    total 2.0, not after-the-fact, mitigation required, status DRAFT.

    Design: Corner/entities/corner_application_computed_fields
    """
    applicant, site, jd = setup_site_with_issued_jd()
    app = create_application(
        site, jd, applicant,
        impacts=[impact_line("FORESTED_WETLAND", 1.5), impact_line("STREAM", 0.5)],
    )
    assert_application(app)
    assert app["total_impact_acres"] == pytest.approx(2.0, abs=1e-6)
    assert app["is_after_the_fact"] is False
    assert app["compensatory_mitigation_required"] is True, "2.0 > 0.10"
    assert app["status"] == ApplicationStatus.DRAFT.value


def test_corner_applicant_violation_count_computed(api, system_admin_headers):
    """PRD §3.1: "The new applicant's `prior_violation_count` is initialized
    to 0; thereafter it is a computed value, counting the enforcement cases
    that name this applicant as `responsible_applicant_id` and whose
    `case_status` is anything other than `OPENED` — that is, cases that have
    matured past mere opening."

    An OPENED case leaves the count at 0; confirming it raises the count to 1.

    Design: Corner/entities/corner_applicant_violation_count_computed
    """
    applicant, site, case = setup_case_opened(1.0)
    got = validate_success(api.get_applicant(applicant["id"], system_admin_headers))
    assert got["prior_violation_count"] == 0, "OPENED cases do not count"

    confirm_case(case)
    got = validate_success(api.get_applicant(applicant["id"], system_admin_headers))
    assert got["prior_violation_count"] == 1, "VIOLATION_CONFIRMED counts"


def test_corner_get_missing_application_not_found(api, reviewer_headers):
    """PRD §2.8: "Path existence: every `{id}` segment of the URL must
    reference an existing entity, validated left-to-right, else the
    per-resource 404 — `ERR_APPLICANT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_JD_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_AA_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_BANK_NOT_FOUND`, `ERR_CREDIT_TXN_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`, chosen by resource
    type."

    Design: Corner/entities/corner_get_missing_application_not_found
    """
    resp = api.get_application(NON_EXISTENT_UUID, reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_corner_get_missing_bank_not_found(api, reviewer_headers):
    """PRD §2.8: "Path existence: every `{id}` segment of the URL must
    reference an existing entity, validated left-to-right, else the
    per-resource 404 — `ERR_APPLICANT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_JD_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_AA_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_BANK_NOT_FOUND`, `ERR_CREDIT_TXN_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`, chosen by resource
    type."

    Design: Corner/entities/corner_get_missing_bank_not_found
    """
    resp = api.get_mitigation_bank(NON_EXISTENT_UUID, reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_BANK_NOT_FOUND)


def test_corner_not_found_sweep_remaining_entities(api, system_admin_headers, reviewer_headers):
    """PRD §2.8: "Path existence: every `{id}` segment of the URL must
    reference an existing entity, validated left-to-right, else the
    per-resource 404 — `ERR_APPLICANT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_JD_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_AA_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_BANK_NOT_FOUND`, `ERR_CREDIT_TXN_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`, chosen by resource
    type."

    Every other single-resource GET maps an unknown id to its entity-specific
    404 error id.

    Design: Corner/entities/corner_not_found_sweep_remaining_entities
    """
    probes = [
        (lambda: api.get_applicant(NON_EXISTENT_UUID, system_admin_headers),
         ApiErrorId.ERR_APPLICANT_NOT_FOUND),
        (lambda: api.get_site(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_SITE_NOT_FOUND),
        (lambda: api.get_jd(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_JD_NOT_FOUND),
        (lambda: api.get_appeal(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_APPEAL_NOT_FOUND),
        (lambda: api.get_alternatives_analysis(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_AA_NOT_FOUND),
        (lambda: api.get_agency_comment(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_COMMENT_NOT_FOUND),
        (lambda: api.get_mitigation_plan(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_PLAN_NOT_FOUND),
        (lambda: api.get_credit_transaction(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_CREDIT_TXN_NOT_FOUND),
        (lambda: api.get_permit(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (lambda: api.get_monitoring_report(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_REPORT_NOT_FOUND),
        (lambda: api.get_enforcement_case(NON_EXISTENT_UUID, reviewer_headers),
         ApiErrorId.ERR_CASE_NOT_FOUND),
    ]
    for call, expected_error in probes:
        validate_error(call(), expected_error)


def test_corner_list_sites_filtered_by_applicant(api, reviewer_headers):
    """PRD §3.1: "The site roster can be listed with an optional
    `applicant_id` filter, and both sites and applicants are readable by
    every role."

    The filtered list contains exactly the matching applicant's site.

    Design: Corner/entities/corner_list_sites_filtered_by_applicant
    """
    ap_a = create_applicant(legal_name="Acme Dredging LLC", contact_email="a@acme.example")
    ap_b = create_applicant(legal_name="Blue Ridge Builders", contact_email="b@brb.example")
    site_a = create_site(ap_a, site_name="Acme Tract")
    create_site(
        ap_b, site_name="BRB Lot", state_code="MD", watershed_code="02070010",
        total_acres=9.0, resource_types_present=["EMERGENT_MARSH"],
    )

    data, meta = validate_paginated(
        api.list_sites(reviewer_headers, params={"applicant_id": ap_a["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == site_a["id"]


def test_corner_invalid_enum_rejected(api, system_admin_headers):
    """PRD §3.1: "Registering an applicant captures the `legal_name`, an
    `organization_type` of exactly one of `INDIVIDUAL`, `CORPORATION`,
    `GOVERNMENT`, or `NONPROFIT`, and a `contact_email`."
    PRD §2.8: "Request shape: required fields present, enumerations valid,
    numbers in range, the `impacts` array non-empty with each line's resource
    type among the site's present types and a positive acreage, after-the-fact
    pathways carrying an `enforcement_case_id` whose case names the same
    responsible applicant, general pathways carrying a `general_permit_code`,
    `comment_period_days` within its allowed window, and
    `stewardship_entity_name` present where the mechanism demands it — any
    failure is `ERR_INVALID_REQUEST` (HTTP 400)."

    An organization_type outside the declared enum is rejected.

    Design: Corner/entities/corner_invalid_enum_rejected
    """
    resp = api.create_applicant(
        create_applicant_payload(legal_name="Mystery Trust", organization_type="TRUST"),
        system_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
