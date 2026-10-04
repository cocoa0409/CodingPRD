"""Renewal events and true-up: proration variant selection, rounding order,
bounds enforcement, and seat-count invariants through a true-up cycle."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    contract_admin_headers, seat_admin_headers, auditor_headers,
    create_and_activate_contract, create_recruiter, list_seats, get_seat,
    assign_seat, assign_first_seat, setup_assigned_seat, current_contract_version,
    set_clock, propose_event, approve_event, apply_event, apply_true_up,
    propose_and_approve, suspend_contract_via_event, create_renewal_event_payload,
)


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/proration_remaining_on_lite_vs_elapsed_on_corp
# ---------------------------------------------------------------------------

def test_proration_remaining_on_lite_vs_elapsed_on_corp():
    """PRD section 3.9: "The variant selection depends on the contract's
    `product_tier`: `RECRUITER_LITE` and `RECRUITER_PRO` contracts use the
    REMAINING variant, while `RECRUITER_CORP` contracts use the ELAPSED
    variant."
    PRD section 3.9: "Under the REMAINING variant, `proration_credit_cents`
    is the absolute value of `seats_delta` multiplied by the per-seat period
    cost, multiplied by `days_remaining`, divided by 30, with the final
    result rounded half-up to integer cents. Under the ELAPSED variant, the
    same formula applies with `days_elapsed` in place of `days_remaining`."

    Design: Difficulty/dual_variant_calc/proration_remaining_on_lite_vs_elapsed_on_corp
    """
    lite = create_and_activate_contract(seats=2, product_tier="RECRUITER_LITE",
                                        seat_cap=10, contract_number="C-LITE-1")
    corp = create_and_activate_contract(seats=2, product_tier="RECRUITER_CORP",
                                        seat_cap=10, contract_number="C-CORP-1")

    set_clock("2026-09-11T00:00:00Z")

    ev_lite = approve_event(propose_event(lite["id"], "TRUE_UP", seats_delta=-1)["id"])
    ev_corp = approve_event(propose_event(corp["id"], "TRUE_UP", seats_delta=-1)["id"])

    # REMAINING (LITE): 1 * 3000 * 20/30 = 2000
    assert ev_lite["proration_credit_cents"] == 2000
    # ELAPSED (CORP): 1 * 15000 * 10/30 = 5000
    assert ev_corp["proration_credit_cents"] == 5000
    assert ev_lite["proration_credit_cents"] != ev_corp["proration_credit_cents"]


def test_proration_remaining_variant_applies_to_pro():
    """PRD section 3.9: "The variant selection depends on the contract's
    `product_tier`: `RECRUITER_LITE` and `RECRUITER_PRO` contracts use the
    REMAINING variant, while `RECRUITER_CORP` contracts use the ELAPSED
    variant."
    PRD section 3.9: "Under the REMAINING variant, `proration_credit_cents`
    is the absolute value of `seats_delta` multiplied by the per-seat period
    cost, multiplied by `days_remaining`, divided by 30, with the final
    result rounded half-up to integer cents."

    Design: Difficulty/dual_variant_calc/proration_remaining_on_lite_vs_elapsed_on_corp
    """
    pro = create_and_activate_contract(seats=2, product_tier="RECRUITER_PRO",
                                       seat_cap=10, contract_number="C-PRO-1")
    set_clock("2026-09-11T00:00:00Z")

    ev_pro = approve_event(propose_event(pro["id"], "TRUE_UP", seats_delta=-1)["id"])
    # REMAINING (PRO): 1 * 10000 * 20/30 = 6666.666... -> 6667 half-up
    assert ev_pro["proration_credit_cents"] == 6667


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/proration_rounding_order_per_seat_then_multiply
# ---------------------------------------------------------------------------

def test_proration_rounding_half_up_at_final_step():
    """PRD section 3.9: "Under the REMAINING variant, `proration_credit_cents`
    is the absolute value of `seats_delta` multiplied by the per-seat period
    cost, multiplied by `days_remaining`, divided by 30, with the final
    result rounded half-up to integer cents."
    PRD section 2.6: "Where a formula requires division (budget pacing,
    proration), each intermediate step uses integer floor division unless the
    rule explicitly states round-half-up; the proration credit is rounded
    half-up to integer cents as its final step."

    Design: Difficulty/combinatorial_formula/proration_rounding_order_per_seat_then_multiply
    """
    lite = create_and_activate_contract(seats=3, product_tier="RECRUITER_LITE",
                                        seat_cap=10, contract_number="C-LITE-2")
    set_clock("2026-09-24T00:00:00Z")

    event = approve_event(propose_event(lite["id"], "TRUE_UP", seats_delta=-2)["id"])
    # 2 * 3000 * 7/30 = 1400 exactly
    assert event["proration_credit_cents"] == 1400


def test_proration_pro_seats_delta_two_at_day_eleven():
    """PRD section 3.9: "Under the REMAINING variant, `proration_credit_cents`
    is the absolute value of `seats_delta` multiplied by the per-seat period
    cost, multiplied by `days_remaining`, divided by 30, with the final
    result rounded half-up to integer cents."

    Design: Difficulty/combinatorial_formula/proration_rounding_order_per_seat_then_multiply
    """
    pro = create_and_activate_contract(seats=3, product_tier="RECRUITER_PRO",
                                       seat_cap=10, contract_number="C-LITE-2B")
    set_clock("2026-09-11T00:00:00Z")

    event = approve_event(propose_event(pro["id"], "TRUE_UP", seats_delta=-2)["id"])
    # 2 * 10000 * 20/30 = 13333.333... -> 13333
    assert event["proration_credit_cents"] == 13333


# ---------------------------------------------------------------------------
# Corner/validations/trueup_bounds_violation_rejected
# ---------------------------------------------------------------------------

def test_trueup_below_assigned_rejected():
    """PRD section 3.9: "Approval of a `TRUE_UP` event enforces the bounds:
    `seats_purchased` plus `seats_delta` must be at least `seats_assigned`
    and at least 1, and must not exceed `seat_cap`; a violation is rejected
    with `ERR_TRUEUP_BOUNDS`."

    Design: Corner/validations/trueup_bounds_violation_rejected
    """
    ctx = setup_assigned_seat(seats=1, contract_number="C-VAL-2")
    cid = ctx["contract"]["id"]
    event = propose_event(cid, "TRUE_UP", seats_delta=-1)
    resp = api_client.approve_renewal_event(event["id"], auditor_headers())
    validate_error(resp, ApiErrorId.ERR_TRUEUP_BOUNDS)


def test_trueup_above_seat_cap_rejected():
    """PRD section 3.9: "Approval of a `TRUE_UP` event enforces the bounds:
    `seats_purchased` plus `seats_delta` must be at least `seats_assigned`
    and at least 1, and must not exceed `seat_cap`; a violation is rejected
    with `ERR_TRUEUP_BOUNDS`."

    Design: Corner/validations/trueup_bounds_violation_rejected
    """
    contract = create_and_activate_contract(seats=1, seat_cap=3,
                                            contract_number="C-VAL-2B")
    event = propose_event(contract["id"], "TRUE_UP", seats_delta=5)
    resp = api_client.approve_renewal_event(event["id"], auditor_headers())
    validate_error(resp, ApiErrorId.ERR_TRUEUP_BOUNDS)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/stale_contract_state_beats_trueup_bounds
# ---------------------------------------------------------------------------

def test_suspended_contract_approve_rejected_invalid_state():
    """PRD section 3.9: "Approval moves it to `APPROVED` provided the
    contract is in `ACTIVE` or `RENEWAL_PENDING`; for `TRUE_UP` events the
    contract's `true_up_allowed` must also be true."
    PRD section 2.10: "entity state preconditions for the requested
    transition, else `ERR_INVALID_STATE`"

    Design: Difficulty/priority_pair_validation_conflict/stale_contract_state_beats_trueup_bounds
    """
    contract = create_and_activate_contract(seats=2, seat_cap=5,
                                            contract_number="C-PRI-2")
    cid = contract["id"]
    r1 = create_recruiter(cid, email="r8a@x.com", full_name="R 8a")
    r2 = create_recruiter(cid, email="r8b@x.com", full_name="R 8b")
    seats = list_seats(cid)
    assign_seat(cid, seats[0]["id"], r1["id"])
    assign_seat(cid, seats[1]["id"], r2["id"])

    # Propose the bounds-violating TRUE_UP before suspension.
    ev_tu = propose_event(cid, "TRUE_UP", seats_delta=-2)
    # Suspend the contract through the SUSPENSION event machinery.
    suspend_contract_via_event(cid)

    resp = api_client.approve_renewal_event(ev_tu["id"], auditor_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_active_contract_approve_rejected_trueup_bounds():
    """PRD section 3.9: "Approval moves it to `APPROVED` provided the
    contract is in `ACTIVE` or `RENEWAL_PENDING`; for `TRUE_UP` events the
    contract's `true_up_allowed` must also be true."
    PRD section 3.9: "Approval of a `TRUE_UP` event enforces the bounds:
    `seats_purchased` plus `seats_delta` must be at least `seats_assigned`
    and at least 1, and must not exceed `seat_cap`; a violation is rejected
    with `ERR_TRUEUP_BOUNDS`."

    Design: Difficulty/priority_pair_validation_conflict/stale_contract_state_beats_trueup_bounds
    """
    contract = create_and_activate_contract(seats=2, seat_cap=5,
                                            contract_number="C-PRI-2B")
    cid = contract["id"]
    r1 = create_recruiter(cid, email="r8c@x.com", full_name="R 8c")
    r2 = create_recruiter(cid, email="r8d@x.com", full_name="R 8d")
    seats = list_seats(cid)
    assign_seat(cid, seats[0]["id"], r1["id"])
    assign_seat(cid, seats[1]["id"], r2["id"])

    # Same bounds violation, but the contract is ACTIVE: bounds error surfaces.
    ev_tu = propose_event(cid, "TRUE_UP", seats_delta=-2)
    resp = api_client.approve_renewal_event(ev_tu["id"], auditor_headers())
    validate_error(resp, ApiErrorId.ERR_TRUEUP_BOUNDS)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/seat_count_invariant_through_trueup_cycle
# ---------------------------------------------------------------------------

def _count_seats_by_status(cid):
    counts = {}
    for status in ("UNASSIGNED", "ASSIGNED", "SUSPENDED", "REVOKED"):
        _, meta = validate_paginated(
            api_client.list_seats(cid, auditor_headers(), params={"seat_status": status})
        )
        counts[status] = meta["total_count"]
    return counts


def test_seat_count_invariant_through_trueup_cycle():
    """PRD section 3.9: "Applying a `TRUE_UP` event leaves the contract in
    `ACTIVE` but mutates its seat inventory: `seats_purchased` increases by
    `seats_delta` (which may be negative); when `seats_delta` is positive,
    that many new `Seat` rows are created in `UNASSIGNED` status under the
    contract; when `seats_delta` is negative, that many `UNASSIGNED` seats —
    chosen oldest-first by `created_at` — are moved to `REVOKED` (with the
    ledger and pool closure cascade described in §2.8 and §3.3); and the
    contract's `version` increments by 1."
    PRD section 3.2: "Negative true-up never revokes an `ASSIGNED` seat —
    only `UNASSIGNED` ones; the expiration cascade revokes both."

    Design: Difficulty/compensating_invariant/seat_count_invariant_through_trueup_cycle
    """
    contract = create_and_activate_contract(seats=1, seat_cap=10,
                                            contract_number="C-INV-2")
    cid = contract["id"]
    recruiter = create_recruiter(cid, email="r14@x.com", full_name="R 14")
    assign_first_seat(cid, recruiter["id"])

    apply_true_up(cid, 2)
    mid = get_success_data(api_client.get_contract(cid, contract_admin_headers()))
    assert mid["seats_purchased"] == 3

    apply_true_up(cid, -2)
    end = get_success_data(api_client.get_contract(cid, contract_admin_headers()))
    assert end["seats_purchased"] == 1
    assert end["seats_assigned"] == 1

    counts = _count_seats_by_status(cid)
    assert counts["ASSIGNED"] == 1
    assert counts["UNASSIGNED"] == 0
    assert counts["REVOKED"] == 2
    assert counts["ASSIGNED"] + counts["UNASSIGNED"] == end["seats_purchased"]


def test_positive_trueup_creates_unassigned_seats():
    """PRD section 3.9: "Applying a `TRUE_UP` event leaves the contract in
    `ACTIVE` but mutates its seat inventory: `seats_purchased` increases by
    `seats_delta` (which may be negative); when `seats_delta` is positive,
    that many new `Seat` rows are created in `UNASSIGNED` status under the
    contract; when `seats_delta` is negative, that many `UNASSIGNED` seats —
    chosen oldest-first by `created_at` — are moved to `REVOKED` (with the
    ledger and pool closure cascade described in §2.8 and §3.3); and the
    contract's `version` increments by 1."

    Design: Difficulty/compensating_invariant/seat_count_invariant_through_trueup_cycle
    """
    contract = create_and_activate_contract(seats=1, seat_cap=10,
                                            contract_number="C-INV-2C")
    cid = contract["id"]
    version_before = current_contract_version(cid)

    apply_true_up(cid, 2)

    after = get_success_data(api_client.get_contract(cid, contract_admin_headers()))
    assert after["seats_purchased"] == 3
    assert after["contract_status"] == "ACTIVE"
    assert after["version"] == version_before + 2  # +1 propose, +1 apply

    counts = _count_seats_by_status(cid)
    assert counts["UNASSIGNED"] == 3
    assert counts["ASSIGNED"] == 0
