"""Difficulty queue A: compensating invariants — lead pool and liability ledger conservation."""
from test_helpers import (
    adjudicate,
    assign_lead,
    create_distributor_payload,
    file_claim_with_photos,
    get_remedy,
    get_success_data,
    make_certified_contractor,
    make_distributor_headers,
    set_clock,
    setup_active_registration,
    validate_success,
)


def test_lead_pool_conserved_across_assign(api, program_admin_headers):
    """PRD §3.8: "The pool's remaining capacity, `lead_pool_available`, is computed as
    `lead_pool_total` minus the number of the distributor's lead assignments
    currently in `ASSIGNED` status; it is recomputed every time an assignment is
    created or returned."

    Design: Difficulty/compensating_invariant/lead_pool_conserved_across_assign_and_return
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE", territory_codes=["T1", "T2"])
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist Pool", territory_codes=["T1", "T2"], lead_pool_total=2),
        program_admin_headers))
    d0 = get_success_data(api.get_distributor(dist["id"], program_admin_headers))
    assert d0["lead_pool_available"] == 2
    assign_lead(dist["id"], contractor["id"], territory_code="T1")
    d1 = get_success_data(api.get_distributor(dist["id"], program_admin_headers))
    assert d1["lead_pool_available"] == 1


def test_lead_pool_conserved_across_assign_and_return(api, program_admin_headers):
    """PRD §3.8: "Returning a lead is the distributor's call: the owning `Distributor`
    returns an assignment, moving it from `ASSIGNED` to `RETURNED` — terminal — and
    the pool's `lead_pool_available` is recomputed, rising by 1."

    Design: Difficulty/compensating_invariant/lead_pool_conserved_across_assign_and_return
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE", territory_codes=["T1", "T2"])
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist Pool", territory_codes=["T1", "T2"], lead_pool_total=2),
        program_admin_headers))
    lead = assign_lead(dist["id"], contractor["id"], territory_code="T1")
    validate_success(api.return_lead_assignment(lead["id"], make_distributor_headers(dist["id"])))
    d2 = get_success_data(api.get_distributor(dist["id"], program_admin_headers))
    assert d2["lead_pool_available"] == 2


def test_contractor_liability_conserved_across_adjudicate_and_reopen(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 7: "`contractor_liability_cents` is the complement of the
    determination share (one minus the share) applied to the sum of the total
    installed material cost and the `claim_labor_cost_cents`, then multiplied by that
    factor, rounded half up to a whole cent." PRD §3.6: "Reopening moves that
    allocation to `REVERSED`, subtracts the allocation's `contractor_liability_cents`
    from the contractor's `outstanding_liability_cents`, refunds the workmanship
    penalty by subtracting the recorded `workmanship_delta_applied` from the score (a
    negative delta thus raises the score, which is capped at its ceiling of 100)..."

    Design: Difficulty/compensating_invariant/contractor_liability_conserved_across_adjudicate_and_reopen
    """
    ctx = setup_active_registration(tier="BRONZE")
    contractor, reg = ctx["contractor"], ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=10000,
                                  file_at="2027-09-10", description="bad flashing")
    claim, cv = info["claim"], info["version"]
    c0 = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert c0["outstanding_liability_cents"] == 0

    adjudicate(claim["id"], "INSTALLATION_ERROR", cv)
    c1 = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert c1["outstanding_liability_cents"] == 110000
    assert c1["workmanship_score"] == 90

    validate_success(api.reopen_claim(claim["id"], {"reason": "disputed finding"}, program_admin_headers))
    c2 = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert c2["outstanding_liability_cents"] == 0
    assert c2["workmanship_score"] == 100


def test_contractor_liability_reopen_refund_capped_at_100(api, program_admin_headers, claimant_headers):
    """PRD §3.6: "Reopening moves that allocation to `REVERSED`, subtracts the
    allocation's `contractor_liability_cents` from the contractor's
    `outstanding_liability_cents`, refunds the workmanship penalty by subtracting the
    recorded `workmanship_delta_applied` from the score (a negative delta thus raises
    the score, which is capped at its ceiling of 100)..."

    Design: Difficulty/compensating_invariant/contractor_liability_conserved_across_adjudicate_and_reopen
    """
    ctx = setup_active_registration(tier="BRONZE")
    contractor, reg = ctx["contractor"], ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=10000,
                                  file_at="2027-09-10", description="bad flashing")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "INSTALLATION_ERROR", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["workmanship_delta_applied"] == -10
    validate_success(api.reopen_claim(claim["id"], {"reason": "refund"}, program_admin_headers))
    c = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert c["workmanship_score"] == 100
    rem2 = get_remedy(claim["id"])[0]
    assert rem2["status"] == "REVERSED"
