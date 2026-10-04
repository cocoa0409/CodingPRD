"""Difficulty queue A: boundary precision — complaint score threshold and labor-year gate."""
from test_helpers import (
    adjudicate,
    create_complaint_payload,
    create_contractor_payload,
    file_claim_with_photos,
    get_remedy,
    get_success_data,
    set_clock,
    setup_active_registration,
)


def test_complaint_weighted_score_four_stays_active(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "a complaint aged 6 months or less weighs 3 points, one aged 7
    through 12 months weighs 2, one aged 13 through 24 months weighs 1, and one older
    than 24 months weighs nothing at all." PRD §3.7: "Otherwise, if the recomputed
    weighted score has reached 5 and the contractor is currently `ACTIVE`, the
    contractor is `SUSPENDED` and the suspension cascade fires."

    Design: Difficulty/boundary_precision_check/complaint_weighted_score_four_stays_active_five_suspends
    """
    set_clock("2026-09-01T00:00:00Z")
    ca = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Bound A", license_number="LIC-BA"), program_admin_headers))
    a1 = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=ca["id"], category="WORKMANSHIP"), claimant_headers))
    a2 = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=ca["id"], category="COMMUNICATION"), claimant_headers))
    set_clock("2027-07-15T00:00:00Z")
    get_success_data(api.substantiate_complaint(a1["id"], program_admin_headers))
    get_success_data(api.substantiate_complaint(a2["id"], program_admin_headers))
    anow = get_success_data(api.get_contractor(ca["id"], program_admin_headers))
    assert anow["complaint_score_24mo"] == 4
    assert anow["status"] == "ACTIVE"


def test_complaint_weighted_score_five_suspends(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "The sum of these weights over all substantiated complaints is the
    contractor's `complaint_score_24mo`." PRD §3.7: "Otherwise, if the recomputed
    weighted score has reached 5 and the contractor is currently `ACTIVE`, the
    contractor is `SUSPENDED` and the suspension cascade fires."

    Design: Difficulty/boundary_precision_check/complaint_weighted_score_four_stays_active_five_suspends
    """
    set_clock("2026-09-01T00:00:00Z")
    cb = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Bound B", license_number="LIC-BB"), program_admin_headers))
    b1 = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=cb["id"], category="WORKMANSHIP"), claimant_headers))
    set_clock("2027-06-01T00:00:00Z")
    b2 = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=cb["id"], category="PROPERTY_DAMAGE"), claimant_headers))
    set_clock("2027-08-01T00:00:00Z")
    get_success_data(api.substantiate_complaint(b1["id"], program_admin_headers))
    get_success_data(api.substantiate_complaint(b2["id"], program_admin_headers))
    bnow = get_success_data(api.get_contractor(cb["id"], program_admin_headers))
    assert bnow["complaint_score_24mo"] == 5
    assert bnow["status"] == "SUSPENDED"


def test_labor_coverage_day_729_still_covered(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 6: "For `QUALIFYING_SYSTEM` registrations, labor coverage also
    expires with age: each tier covers labor for a fixed number of years — 2 years
    for `BRONZE`, 5 for `SILVER`, 10 for `GOLD` — and the gate is strict, so at the
    boundary year the coverage is already gone; a claim filed in or after the tier's
    labor year count receives zero labor coverage." PRD §3.6 step 1: "The completed
    years of coverage is the whole number of years between the registration's
    `activated_at` and the claim's `filed_at` — the day difference divided by 365,
    rounded down to a whole number, stored on the allocation as `completed_years`."

    Design: Difficulty/boundary_precision_check/labor_coverage_day_729_covered_day_730_zero
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=50000,
                                  file_at="2028-09-08", description="edge A")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["completed_years"] == 1
    assert rem["labor_covered_cents"] == 50000


def test_labor_coverage_day_730_gate_closed(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 6: "...the gate is strict, so at the boundary year the coverage
    is already gone; a claim filed in or after the tier's labor year count receives
    zero labor coverage."

    Design: Difficulty/boundary_precision_check/labor_coverage_day_729_covered_day_730_zero
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=50000,
                                  file_at="2028-09-09", description="edge B")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["completed_years"] == 2
    assert rem["labor_covered_cents"] == 0
