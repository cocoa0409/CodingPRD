"""Difficulty queue A: dual-variant calculations — proration schedules and complaint metrics."""
from test_helpers import (
    adjudicate,
    create_complaint_payload,
    file_claim_with_photos,
    get_remedy,
    get_success_data,
    make_certified_contractor,
    set_clock,
    setup_active_registration,
    validate_success,
)


def test_material_prorate_standard_schedule_at_year6(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 1: "The schedule applied is recorded as `schedule_used`: it is
    the tier's own schedule — `STANDARD` for `BRONZE`, `ENHANCED` for `SILVER`,
    `ENHANCED_PLUS` for `GOLD` — unless the registration's `coverage_class` is
    `MIXED_MANUFACTURER`, in which case the `STANDARD` schedule is forced regardless
    of tier." PRD §3.6 step 2: "Under `STANDARD`, coverage is 100 percent in the first
    year and decays by 10 points for each year beyond the first, never falling below
    20 percent."

    Design: Difficulty/dual_variant_calc/material_prorate_standard_vs_enhanced_diverge_at_year6
    """
    ctx = setup_active_registration(tier="BRONZE", line_cents=100000)
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=50000,
                                  file_at="2032-09-10", description="leak")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["schedule_used"] == "STANDARD"
    assert rem["material_pct"] == 50
    assert rem["material_covered_cents"] == 200000
    assert rem["completed_years"] == 6


def test_material_prorate_enhanced_schedule_at_year6(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 2: "Under `ENHANCED`, coverage holds at 100 percent through the
    fifth year and decays by 5 points for each year beyond the fifth, never falling
    below 50 percent." PRD §3.6 step 5: "`material_covered_cents` is the determination
    share applied to the prorated material pool, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/material_prorate_standard_vs_enhanced_diverge_at_year6
    """
    ctx = setup_active_registration(tier="SILVER", line_cents=100000)
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=50000,
                                  file_at="2032-09-10", description="leak")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["schedule_used"] == "ENHANCED"
    assert rem["material_pct"] == 95
    assert rem["material_covered_cents"] == 380000
    assert rem["completed_years"] == 6


def test_complaint_score_weighted_vs_lifetime_diverge_after_decay(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "The lifetime count asks \"has this contractor ever been a persistent
    problem?\": `lifetime_substantiated_count` is the plain count of all substantiated
    complaints with no time window, so a contractor whose complaints are all ancient
    has a weighted score of 0 yet still accrues toward the lifetime threshold."
    PRD §3.7: "Two thresholds then act, lifetime first: if the
    `lifetime_substantiated_count` has reached 8, the contractor is `REVOKED` —
    terminal — and the revocation cascade fires."

    Design: Difficulty/dual_variant_calc/complaint_score_weighted_vs_lifetime_diverge_after_decay
    """
    from test_helpers import create_contractor_payload

    set_clock("2026-09-01T00:00:00Z")
    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Risky Co", license_number="LIC-R"), program_admin_headers))
    cid = contractor["id"]
    old_ids = []
    for _ in range(7):
        c = get_success_data(api.create_complaint(
            create_complaint_payload(contractor_id=cid, category="WORKMANSHIP"), claimant_headers))
        old_ids.append(c["id"])
    for cmp_id in old_ids:
        get_success_data(api.substantiate_complaint(cmp_id, program_admin_headers))
    set_clock("2028-10-01T00:00:00Z")
    cmp8 = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=cid, category="PROPERTY_DAMAGE"), claimant_headers))
    set_clock("2028-10-15T00:00:00Z")
    get_success_data(api.substantiate_complaint(cmp8["id"], program_admin_headers))
    cnow = get_success_data(api.get_contractor(cid, program_admin_headers))
    assert cnow["complaint_score_24mo"] == 3
    assert cnow["lifetime_substantiated_count"] == 8
    assert cnow["status"] == "REVOKED"


def test_complaint_weighted_score_decays_to_zero_and_reinstates(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "Whenever the logical clock advances, the server re-evaluates every
    `SUSPENDED` contractor whose `lifetime_substantiated_count` is still below 8: the
    weighted score is recomputed at the new clock, and if it has decayed below 5 the
    contractor returns to `ACTIVE`." PRD §3.7: "a complaint aged 6 months or less
    weighs 3 points, one aged 7 through 12 months weighs 2, one aged 13 through 24
    months weighs 1, and one older than 24 months weighs nothing at all."

    Design: Difficulty/dual_variant_calc/complaint_score_weighted_vs_lifetime_diverge_after_decay
    """
    from test_helpers import create_contractor_payload

    set_clock("2026-09-01T00:00:00Z")
    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Decay Co", license_number="LIC-DC"), program_admin_headers))
    cid = contractor["id"]
    ids = []
    for _ in range(7):
        c = get_success_data(api.create_complaint(
            create_complaint_payload(contractor_id=cid, category="WORKMANSHIP"), claimant_headers))
        ids.append(c["id"])
    for cmp_id in ids:
        get_success_data(api.substantiate_complaint(cmp_id, program_admin_headers))
    mid = get_success_data(api.get_contractor(cid, program_admin_headers))
    assert mid["status"] == "SUSPENDED"
    assert mid["lifetime_substantiated_count"] == 7
    set_clock("2028-10-01T00:00:00Z")
    after = get_success_data(api.get_contractor(cid, program_admin_headers))
    assert after["complaint_score_24mo"] == 0
    assert after["status"] == "ACTIVE"
    assert after["lifetime_substantiated_count"] == 7
