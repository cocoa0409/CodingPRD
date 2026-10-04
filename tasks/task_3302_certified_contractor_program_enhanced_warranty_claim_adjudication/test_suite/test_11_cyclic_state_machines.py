"""Difficulty queue A: cyclic state machines — certification suspend/reinstate, claim reopen cycle."""
from test_helpers import (
    ApiErrorId,
    adjudicate,
    create_complaint_payload,
    file_claim_with_photos,
    get_remedy,
    get_success_data,
    make_certified_contractor,
    make_inspector_headers,
    set_clock,
    setup_active_registration,
    suspend_contractor_via_complaints,
    validate_success,
)


def test_certification_suspend_via_complaint_cascade(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "The suspension cascade moves every `ACTIVE` certification of the
    contractor to `SUSPENDED` — each with its `version` incremented..."
    PRD §2.4: "Cascaded transitions count as mutations: when a complaint cascade
    suspends a certification, that certification's `version` increments and its
    `updated_at` refreshes even though no client wrote to it directly."

    Design: Difficulty/non_linear_state_machine/certification_suspend_reinstate_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor, cert = ctx["contractor"], ctx["certification"]
    v_active = cert["version"]
    suspend_contractor_via_complaints(contractor["id"])
    cnow = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert cnow["status"] == "SUSPENDED"
    assert cnow["complaint_score_24mo"] == 5
    cert_now = get_success_data(api.get_certification(cert["id"], program_admin_headers))
    assert cert_now["status"] == "SUSPENDED"
    assert cert_now["version"] == v_active + 1


def test_certification_reinstate_after_contractor_auto_reinstate(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "Whenever the logical clock advances, the server re-evaluates every
    `SUSPENDED` contractor whose `lifetime_substantiated_count` is still below 8: the
    weighted score is recomputed at the new clock, and if it has decayed below 5 the
    contractor returns to `ACTIVE`." PRD §3.2: "A `SUSPENDED` certification returns to
    `ACTIVE` only through an individual reinstatement by a `ProgramAdmin`, which
    requires the contractor to be `ACTIVE` (else `ERR_CONTRACTOR_SUSPENDED`) and the
    contractor's `insurance_expiry` to be strictly later than the current clock date
    (else `ERR_INSURANCE_EXPIRED`); reinstatement increments the certification's
    `version`."

    Design: Difficulty/non_linear_state_machine/certification_suspend_reinstate_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor, cert = ctx["contractor"], ctx["certification"]
    v_active = cert["version"]
    suspend_contractor_via_complaints(contractor["id"])
    # clock at 2027-08-01: weights are 2 (filed 2026-09-01) + 3 (filed 2027-06-01) = 5.
    # reinstate while the contractor is SUSPENDED must fail.
    bad = api.reinstate_certification(cert["id"], program_admin_headers)
    from test_helpers import validate_error
    validate_error(bad, ApiErrorId.ERR_CONTRACTOR_SUSPENDED)
    # advance clock so the weighted score decays below 5 (ages 16 and 7 months at
    # 2028-01-01 -> weights 1 + 2 = 3) and the contractor auto-reinstates.
    set_clock("2028-01-01T00:00:00Z")
    cnow = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert cnow["status"] == "ACTIVE"
    reinstated = validate_success(api.reinstate_certification(cert["id"], program_admin_headers))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == v_active + 2


def test_claim_resolve_reopen_cycle_first_pass_no_inspection(api, program_admin_headers, claimant_headers):
    """PRD §3.6: "Any other determination resolves the claim: it moves to `RESOLVED`..."
    PRD §3.6: "Reopening unwinds a resolution. A `ProgramAdmin` may reopen a `RESOLVED`
    claim — the call carries a free-text `reason` — provided the claim still has a
    remedy allocation in `ACTIVE` status. Reopening moves that allocation to
    `REVERSED`... returns the claim to `EVIDENCE_REVIEW`, and increments the claim's
    `version`."

    Design: Difficulty/non_linear_state_machine/claim_resolve_reopen_cycle_with_inspection_fork
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=50000,
                                  file_at="2027-09-10", description="shingle failure")
    claim, cv1 = info["claim"], info["version"]
    resolved = adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv1)
    assert resolved["status"] == "RESOLVED"
    rem1 = get_remedy(claim["id"])[0]
    assert rem1["status"] == "ACTIVE"
    assert rem1["material_covered_cents"] == 100000  # year 1, STANDARD 100%

    reopened = validate_success(api.reopen_claim(claim["id"], {"reason": "new damage found"}, program_admin_headers))
    assert reopened["status"] == "EVIDENCE_REVIEW"
    rem_after = get_remedy(claim["id"])[0]
    assert rem_after["status"] == "REVERSED"


def test_claim_resolve_reopen_cycle_second_pass_inspection_fork(api, program_admin_headers, claimant_headers):
    """PRD §3.5: "The first such request moves the claim from `EVIDENCE_REVIEW` to
    `INSPECTION_REQUESTED` and creates an inspection order in `REQUESTED` status,
    linked to the claim through the order's `claim_id`." PRD §3.5: "When the last
    outstanding order of a claim completes — that is, when no linked order remains in
    `REQUESTED` or `SCHEDULED` — the claim automatically advances from
    `INSPECTION_REQUESTED` to `INSPECTION_COMPLETED`, incrementing the claim's
    `version`." PRD §3.6: "Any other determination resolves the claim: it moves to
    `RESOLVED`, and the system computes and persists a remedy allocation in `ACTIVE`
    status..."

    Design: Difficulty/non_linear_state_machine/claim_resolve_reopen_cycle_with_inspection_fork
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=50000,
                                  file_at="2027-09-10", description="shingle failure")
    claim, cv1 = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv1)
    reopened = validate_success(api.reopen_claim(claim["id"], {"reason": "new damage found"}, program_admin_headers))
    assert reopened["status"] == "EVIDENCE_REVIEW"

    order = get_success_data(api.request_inspection(claim["id"], program_admin_headers))
    get_success_data(api.schedule_inspection_order(
        order["id"], {"inspector_id": "INSP-1", "service_date": "2027-09-15"}, program_admin_headers))
    get_success_data(api.complete_inspection_order(
        order["id"], {"findings": "confirmed shingle defect", "confirms_defect": True},
        make_inspector_headers("INSP-1")))
    claim_now = get_success_data(api.get_warranty_claim(claim["id"], program_admin_headers))
    assert claim_now["status"] == "INSPECTION_COMPLETED"

    resolved2 = adjudicate(claim["id"], "MANUFACTURER_DEFECT", claim_now["version"])
    assert resolved2["status"] == "RESOLVED"
    remedies = get_remedy(claim["id"])
    assert len(remedies) == 1
    assert remedies[0]["status"] == "ACTIVE"
