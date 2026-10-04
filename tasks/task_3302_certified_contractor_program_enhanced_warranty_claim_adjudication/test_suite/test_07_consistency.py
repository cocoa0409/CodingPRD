"""Consistency corner tests: immediate remedy visibility, dismiss side-effect absence."""
from test_helpers import (
    adjudicate,
    create_complaint_payload,
    file_claim_with_photos,
    get_remedy,
    get_success_data,
    set_clock,
    setup_active_registration,
    validate_success,
)


def test_remedy_visible_immediately_after_adjudicate(api, program_admin_headers, claimant_headers):
    """PRD §3.6: "The remedy allocation of a claim is retrievable as a list of zero or
    one element, exposing every computed figure..." PRD §3.6 step 3: "Each registration
    component line's `material_cost_cents` is multiplied by the schedule percentage
    and rounded half up to a whole cent per line; the pool `prorated_material_pool_cents`
    is the sum of those per-line rounded amounts." PRD §3.6 step 2: "Under `STANDARD`,
    coverage is 100 percent in the first year..."

    Design: Corner/consistency_model/remedy_visible_immediately_after_adjudicate
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=10000, file_at="2026-09-20", description="c")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    remedies = get_remedy(claim["id"])
    assert len(remedies) == 1
    rem = remedies[0]
    assert rem["status"] == "ACTIVE"
    assert rem["completed_years"] == 0
    assert rem["schedule_used"] == "STANDARD"
    assert rem["material_pct"] == 100
    assert rem["material_covered_cents"] == 100000
    assert rem["labor_covered_cents"] == 10000


def test_dismiss_complaint_leaves_scores_unchanged(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "Dismissal moves it to `DISMISSED` — terminal — with no effect on any
    score."

    Design: Corner/consistency_model/dismiss_complaint_leaves_scores_unchanged
    """
    from test_helpers import create_contractor_payload

    set_clock("2026-09-01T00:00:00Z")
    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Calm Co", license_number="LIC-CL"), program_admin_headers))
    complaint = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=contractor["id"], category="COMMUNICATION"), claimant_headers))
    resp = api.dismiss_complaint(complaint["id"], program_admin_headers)
    data = validate_success(resp)
    assert data["status"] == "DISMISSED"
    cnow = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert cnow["workmanship_score"] == 100
    assert cnow["complaint_score_24mo"] == 0
    assert cnow["lifetime_substantiated_count"] == 0
    assert cnow["status"] == "ACTIVE"
