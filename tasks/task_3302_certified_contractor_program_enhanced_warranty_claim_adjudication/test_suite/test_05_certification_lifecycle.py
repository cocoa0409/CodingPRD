"""Certification lifecycle: initial state, training credit windows, OCC renew."""
from test_helpers import (
    ApiErrorId,
    add_training_credits,
    create_certification_payload,
    create_contractor_payload,
    create_training_course_payload,
    get_success_data,
    make_certified_contractor,
    make_contractor_headers,
    set_clock,
    validate_error,
    validate_success,
)


def test_certification_initial_state_pending_verification(api, program_admin_headers):
    """PRD §3.2: "A new certification begins in `PENDING_VERIFICATION`."

    Design: Corner/state_machines/certification_initial_state_pending_verification
    """
    set_clock("2026-09-01T00:00:00Z")
    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Init Co", license_number="LIC-IN"), program_admin_headers))
    resp = api.create_certification(
        create_certification_payload(contractor_id=contractor["id"], tier="BRONZE"),
        make_contractor_headers(contractor["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING_VERIFICATION"


def test_training_credit_expired_excluded_from_total_on_renew(api, program_admin_headers):
    """PRD §3.1: "an enrollment counts when its `completed_at` date, advanced by the
    course's `validity_months`, is on or after the evaluation date — the boundary
    month still counts, because the comparison is inclusive."
    PRD §3.2: "...creditable training at or above the tier minimum, surfacing
    `ERR_CONTRACTOR_SUSPENDED`, `ERR_INSURANCE_EXPIRED`, `ERR_LICENSE_EXPIRED`, or
    `ERR_INSUFFICIENT_TRAINING_CREDITS` as applicable."

    Design: Corner/calculations/training_credit_expired_excluded_from_total_on_renew
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE", validity_months=12)
    contractor, cert = ctx["contractor"], ctx["certification"]
    cert_v = cert["version"]
    set_clock("2028-08-01T00:00:00Z")
    resp = api.renew_certification(cert["id"], {"expected_certification_version": cert_v},
                                   make_contractor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TRAINING_CREDITS)


def test_training_credit_validity_boundary_inclusive(api, program_admin_headers):
    """PRD §3.1: "an enrollment counts when its `completed_at` date, advanced by the
    course's `validity_months`, is on or after the evaluation date — the boundary
    month still counts, because the comparison is inclusive."
    PRD §3.2: "A successful renewal extends `valid_until` by a further 24 months —
    measured from the prior `valid_until`, not from the renewal date — and increments
    the certification's `version`."

    Design: Corner/calculations/training_credit_validity_boundary_inclusive
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE", validity_months=12)
    contractor, cert = ctx["contractor"], ctx["certification"]
    cert_v = cert["version"]
    assert cert["valid_until"] == "2028-09-01"
    set_clock("2027-09-01T00:00:00Z")
    resp = api.renew_certification(cert["id"], {"expected_certification_version": cert_v},
                                   make_contractor_headers(contractor["id"]))
    data = validate_success(resp)
    assert data["valid_until"] == "2030-09-01"
    assert data["status"] == "ACTIVE"


def test_occ_stale_certification_version_renew_returns_412(api, program_admin_headers):
    """PRD §2.7: "Renewing a certification requires `expected_certification_version`
    matching the certification's current `version`; a mismatch is rejected with
    `ERR_STALE_CERTIFICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_certification_version_renew_returns_412
    """
    set_clock("2026-09-01T00:00:00Z")
    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="OCC3 Co", license_number="LIC-O3"), program_admin_headers))
    add_training_credits(contractor["id"], 4, validity_months=36)
    ch = make_contractor_headers(contractor["id"])
    cert = get_success_data(api.create_certification(
        create_certification_payload(contractor_id=contractor["id"], tier="BRONZE"), ch))
    stale_v = cert["version"]
    get_success_data(api.verify_certification(cert["id"], {"decision": "APPROVE"}, program_admin_headers))
    resp = api.renew_certification(cert["id"], {"expected_certification_version": stale_v}, ch)
    validate_error(resp, ApiErrorId.ERR_STALE_CERTIFICATION_VERSION)
