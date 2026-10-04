"""Difficulty queue A: priority-pair validation conflicts."""
from test_helpers import (
    ApiErrorId,
    add_training_credits,
    assign_lead,
    create_certification_payload,
    create_contractor_payload,
    create_distributor_payload,
    create_lead_assignment_payload,
    create_training_course_payload,
    get_success_data,
    make_certified_contractor,
    make_contractor_headers,
    make_distributor_headers,
    set_clock,
    suspend_contractor_via_complaints,
    validate_error,
)


def test_lead_assign_suspended_contractor_beats_territory_overlap(api, program_admin_headers, claimant_headers):
    """PRD §2.8: "State-eligibility checks come next — that the requested transition
    exists from the entity's current state (`ERR_INVALID_STATE`), and the standing
    checks `ERR_CONTRACTOR_SUSPENDED`, `ERR_CERTIFICATION_NOT_ACTIVE`, and
    `ERR_REGISTRATION_NOT_ACTIVE` — followed by the two optimistic-concurrency
    rejections... and finally the business-constraint tier: training credit
    sufficiency, photo evidence sufficiency, inspection completeness,
    required-component presence, duplicate component types, catalog existence, tier
    and territory eligibility, territory window overlap, inspector capacity, and lead
    pool availability."

    Design: Difficulty/priority_pair_validation_conflict/lead_assign_suspended_contractor_beats_territory_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist P", territory_codes=["T1"], lead_pool_total=2),
        program_admin_headers))
    # existing ASSIGNED lead overlapping the attempted window; suspension cascade
    # returns it, so the overlap precondition is actually moot — the only rule that
    # can fire on the suspended-contractor call is the standing check.
    assign_lead(dist["id"], contractor["id"], territory_code="T1")
    suspend_contractor_via_complaints(contractor["id"])

    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=dist["id"],
            contractor_id=contractor["id"],
            territory_code="T1",
            start_date="2026-10-15",
            end_date="2026-12-01",
        ),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_SUSPENDED)


def test_lead_assign_suspended_contractor_rejected_even_with_fresh_window(api, program_admin_headers, claimant_headers):
    """PRD §3.8: "The assignment is refused with `ERR_TIER_REQUIREMENT_NOT_MET`
    (HTTP 422) unless all of the following hold: the contractor is `ACTIVE` (a
    non-active contractor surfaces `ERR_CONTRACTOR_SUSPENDED` instead)..."

    Design: Difficulty/priority_pair_validation_conflict/lead_assign_suspended_contractor_beats_territory_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist P2", territory_codes=["T1"], lead_pool_total=2),
        program_admin_headers))
    suspend_contractor_via_complaints(contractor["id"])
    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=dist["id"],
            contractor_id=contractor["id"],
            territory_code="T1",
            start_date="2028-01-01",
            end_date="2028-02-01",
        ),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_SUSPENDED)


def test_renew_insurance_expired_beats_credit_shortfall(api, program_admin_headers):
    """PRD §2.8: "Temporal compliance checks (`ERR_INSURANCE_EXPIRED`,
    `ERR_LICENSE_EXPIRED`) are evaluated after state checks, and finally the
    business-constraint tier: training credit sufficiency, photo evidence
    sufficiency, inspection completeness, required-component presence, duplicate
    component types, catalog existence, tier and territory eligibility, territory
    window overlap, inspector capacity, and lead pool availability."

    Design: Difficulty/priority_pair_validation_conflict/renew_insurance_expired_beats_credit_shortfall
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE", validity_months=12)
    contractor, cert = ctx["contractor"], ctx["certification"]
    cert_v = cert["version"]
    get_success_data(api.patch_contractor_compliance(
        contractor["id"], {"insurance_expiry": "2028-06-01"}, program_admin_headers))
    set_clock("2028-08-01T00:00:00Z")
    resp = api.renew_certification(
        cert["id"], {"expected_certification_version": cert_v},
        make_contractor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_INSURANCE_EXPIRED)


def test_renew_insurance_expired_fires_even_with_valid_credits(api, program_admin_headers):
    """PRD §3.2: "Renewal re-runs the same standing checks as approval at the current
    clock date: contractor `ACTIVE`, `insurance_expiry` strictly later than the clock
    date, `license_expiry` strictly later than the clock date, and creditable training
    at or above the tier minimum, surfacing `ERR_CONTRACTOR_SUSPENDED`,
    `ERR_INSURANCE_EXPIRED`, `ERR_LICENSE_EXPIRED`, or
    `ERR_INSUFFICIENT_TRAINING_CREDITS` as applicable."

    Design: Difficulty/priority_pair_validation_conflict/renew_insurance_expired_beats_credit_shortfall
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE", validity_months=36)
    contractor, cert = ctx["contractor"], ctx["certification"]
    cert_v = cert["version"]
    get_success_data(api.patch_contractor_compliance(
        contractor["id"], {"insurance_expiry": "2028-06-01"}, program_admin_headers))
    set_clock("2028-08-01T00:00:00Z")
    resp = api.renew_certification(
        cert["id"], {"expected_certification_version": cert_v},
        make_contractor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_INSURANCE_EXPIRED)
