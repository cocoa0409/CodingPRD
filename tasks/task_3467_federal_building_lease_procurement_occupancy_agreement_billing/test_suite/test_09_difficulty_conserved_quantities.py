"""Compensating invariants: an action followed by its compensation restores
the conserved quantity exactly."""
from test_helpers import (
    TEST_USERS, activate_oa, approve_alteration, create_agency,
    create_alteration, create_owned_building, create_owned_oa,
    estimate_alteration, generate_bill, make_agency_manager_headers, set_clock,
    setup_active_leased_oa, validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]


def test_oa_create_then_terminate_restores_space_inventory(api):
    """PRD §3.5: "an owned agreement reserves its space immediately — the
    building's `available_sf` drops by `assigned_sf` from the moment of
    creation (§2.9)."
    PRD §3.5: "From `ACTIVE`, the full terminal cascade runs: the owned
    building's `available_sf` is restored; every non-terminal alteration
    request on the agreement — those in `REQUESTED`, `ESTIMATED`, or
    `APPROVED` — is cancelled, and any such cancellation reverses a pending
    lump-sum charge from `PENDING` to `REVERSED`; and each completed amortized
    alteration's exact remaining `amortization_balance_cents` is accelerated,
    rounded half up, into the agreement's `terminal_writeoff_cents`."
    PRD §2.9: "Equivalently, committed square footage plus available square
    footage always equals `total_sf`, on both ownership variants."

    Create commits 20,000 of 50,000 sf; termination is the compensating action
    that returns available_sf to exactly 50,000 — the conservation invariant
    holds before, between, and after the pair.

    Design: Difficulty/compensating_invariant/oa_create_then_terminate_restores_space_inventory
    """
    agency = create_agency(name="Park Service")
    building = create_owned_building()
    set_clock("2026-10-01T00:00:00Z")

    oa = create_owned_oa(building, agency)
    activate_oa(oa, agency)
    mid = validate_success(api.get_building(building["id"], ADMIN), 200)
    assert mid["available_sf"] == 30000, "create committed 20,000 of 50,000"

    terminated = validate_success(api.terminate_oa(oa["id"], OFFICER), 200)
    assert terminated["status"] == "TERMINATED"

    end = validate_success(api.get_building(building["id"], ADMIN), 200)
    assert end["available_sf"] == 50000, (
        "terminate restored the full inventory: no drift")
    assert 0 + end["available_sf"] == end["total_sf"], (
        "committed + available == total_sf at the end")


def test_lump_sum_approve_then_cancel_nets_zero_billing(api):
    """PRD §2.11: "A lump-sum alteration that is cancelled before completion
    never enters any bill, so an approve-then-cancel pair leaves the
    agreement's billable pipeline exactly as it found it — net zero."
    PRD §3.6: "From `APPROVED`, it also reverses a pending lump-sum charge —
    `PENDING` to `REVERSED` — so the charge never reaches a bill."
    PRD §2.11: "its `receivable_outstanding_cents` always equals the sum of its
    bills' `total_cents` minus the sum of their `amount_paid_cents`, recomputed
    at every bill generation and every payment."

    The approved 12,000,000-cent lump sum is staged as PENDING; the
    compensating cancel flips it to REVERSED, so the next bill is the rent-only
    24,347,894 and the receivable ledger is identical to a world where the
    alteration never existed.

    Design: Difficulty/compensating_invariant/lump_sum_approve_then_cancel_nets_zero_billing
    """
    bundle = setup_active_leased_oa()  # 2027 stmt actual 460 recorded
    oa, agency = bundle["oa"], bundle["agency"]
    agency_h = make_agency_manager_headers(agency["id"])

    alt = create_alteration(oa, agency, title="Lobby refresh",
                            description="Cosmetic lobby work", scope_sf=1500)
    estimate_alteration(alt, estimated_cost_cents=12000000,
                        work_start_date="2028-03-01", work_end_date="2028-03-31")
    approved = approve_alteration(alt, agency, funding_method="LUMP_SUM")
    assert approved["lump_charge_status"] == "PENDING"

    cancelled = validate_success(api.cancel_alteration(alt["id"], agency_h), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["lump_charge_status"] == "REVERSED"

    bill = generate_bill(oa, "2028-05")
    assert bill["lump_sum_charges_cents"] == 0, (
        "the reversed charge never reaches a bill")
    assert bill["total_cents"] == 24347894, (
        "identical to the no-alteration rent-only bill")

    oa_after = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_after["receivable_outstanding_cents"] == 24347894, (
        "approve+cancel left zero net billing effect")
