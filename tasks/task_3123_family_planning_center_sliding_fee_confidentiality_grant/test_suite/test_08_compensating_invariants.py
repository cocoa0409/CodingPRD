"""Depth tests: compensating invariants on stock pools and claim accounting."""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_tx_clinic, setup_assessed_encounter, setup_submitted_claim,
    create_stock_lot, create_device_reservation,
    set_clock, get_stock_lot, get_claim,
    assert_claim_receivable_identity, assert_lot_available_units,
    TEST_USERS, FPL_INCOME_H1_PCT_174, FPL_INCOME_H1_PCT_265,
    LARC_START, LARC_END,
)

CLINICIAN = TEST_USERS["clinician_headers"]
SUPPLY = TEST_USERS["supply_coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_reserve_then_release_restores_available_units_exactly(api):
    """PRD §3.6: "On success, the lot's `reserved_out` increments by 1 and
    `on_hand` is unchanged — the unit is earmarked but still on the shelf."
    PRD §3.6: "Release happens either automatically on encounter cancellation
    or manually when a `SupplyCoordinator` releases a specific reservation;
    in both cases the lot's `reserved_out` decrements by 1 and `on_hand` is
    unchanged."

    Reserve (forward) then release (compensating) leaves on_hand 3 and
    reserved_out 0 — available units restored to 3 exactly.

    Design: Difficulty/compensating_invariant/stock_reserve_release_conserves_available_units
    """
    clinic = setup_tx_clinic(service_code="LARC_INSERTION",
                             full_fee_cents=50000, telehealth_eligible=False)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        service_code="LARC_INSERTION", enc_start=LARC_START, enc_end=LARC_END,
        external_ref="Q1",
    )
    lot = create_stock_lot(clinic["affiliate"]["id"], device_code="IMPLANT",
                           lot_number="LOT-Q", unit_cost_cents=40000,
                           on_hand=3, expires_on="2027-01-01")
    reservation = create_device_reservation(ctx["encounter"]["id"], lot["id"])
    assert_lot_available_units(get_stock_lot(lot["id"]), 2)

    released = validate_success(
        api_client.release_device_reservation(reservation["id"], SUPPLY)
    )
    assert released["status"] == "RELEASED"
    lot_after = get_stock_lot(lot["id"])
    assert lot_after["on_hand"] == 3
    assert lot_after["reserved_out"] == 0
    assert_lot_available_units(lot_after, 3)


def test_fulfill_drops_physical_total_while_available_stays_constant(api):
    """PRD §3.5: "each reservation moves to `FULFILLED`, and the parent stock
    lot loses the unit from both pools — `on_hand` is decremented by 1
    **and** `reserved_out` is decremented by 1, so the physical unit leaves
    stock while the reservation placeholder is released."

    Completing the encounter fulfills the reservation: on_hand 3 -> 2 and
    reserved_out 1 -> 0; available stays at 2 while the physical total
    (on_hand + reserved_out) drops by exactly 1.

    Design: Difficulty/compensating_invariant/stock_reserve_release_conserves_available_units
    """
    clinic = setup_tx_clinic(service_code="LARC_INSERTION",
                             full_fee_cents=50000, telehealth_eligible=False)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        service_code="LARC_INSERTION", enc_start=LARC_START, enc_end=LARC_END,
        external_ref="Q2",
    )
    lot = create_stock_lot(clinic["affiliate"]["id"], device_code="IMPLANT",
                           lot_number="LOT-Q2", unit_cost_cents=40000,
                           on_hand=3, expires_on="2027-01-01")
    reservation = create_device_reservation(ctx["encounter"]["id"], lot["id"])
    assert_lot_available_units(get_stock_lot(lot["id"]), 2)

    set_clock("2026-09-15T12:00:00Z")
    validate_success(api_client.start_encounter(ctx["encounter"]["id"],
                                                CLINICIAN))
    validate_success(api_client.complete_encounter(ctx["encounter"]["id"],
                                                   CLINICIAN))

    res_after = validate_success(
        api_client.get_device_reservation(reservation["id"], SUPPLY)
    )
    assert res_after["status"] == "FULFILLED"
    lot_after = get_stock_lot(lot["id"])
    assert lot_after["on_hand"] == 2, (
        f"physical unit left stock, got on_hand {lot_after['on_hand']}"
    )
    assert lot_after["reserved_out"] == 0
    assert_lot_available_units(lot_after, 2)
    assert (lot_after["on_hand"] + lot_after["reserved_out"]) == 2, (
        "physical total dropped by exactly 1 (3 -> 2)"
    )


def test_adjudicate_then_recoup_conserves_receivable_identity(api):
    """PRD §3.7: "its `net_receivable_cents` is computed as `billed_cents`
    minus `paid_cents` plus `recouped_cents`".
    PRD §3.7: "A successful recoupment adds to `recouped_cents` and
    recomputes `net_receivable_cents` — the compensating invariant that
    conserves `paid_cents` minus `recouped_cents` against `billed_cents`."

    Adjudicate 10000 (net 0) then recoup 4000: recouped 4000 and
    net_receivable 4000, with billed == paid - recouped + net at each step.

    Design: Difficulty/compensating_invariant/claim_payment_recoupment_conserves_receivable_identity
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-CI",
    )
    claim_id = ctx["claim"]["id"]

    paid = validate_success(
        api_client.adjudicate_claim(claim_id, {"amount_cents": 10000}, BILLING)
    )
    assert paid["paid_cents"] == 10000
    assert paid["recouped_cents"] == 0
    assert paid["net_receivable_cents"] == 0
    assert_claim_receivable_identity(paid)

    recouped = validate_success(
        api_client.recoup_claim(claim_id, {"amount_cents": 4000}, BILLING)
    )
    assert recouped["recouped_cents"] == 4000
    assert recouped["net_receivable_cents"] == 4000, (
        f"identity: 10000 == 10000 - 4000 + 4000, got net "
        f"{recouped['net_receivable_cents']}"
    )
    assert_claim_receivable_identity(recouped)


def test_over_recoupment_rejected_and_identity_survives_rejection(api):
    """PRD §3.7: "The recoupment is capped at `paid_cents` minus
    `recouped_cents`; a larger amount is rejected with
    `ERR_RECOUPMENT_EXCEEDS_PAID` (HTTP 422)."

    After adjudicating 10000 and recouping 4000, a further recoup of 6001
    exceeds the 6000 cap and is rejected; the identity
    billed == paid - recouped + net still holds afterwards.

    Design: Difficulty/compensating_invariant/claim_payment_recoupment_conserves_receivable_identity
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H1_PCT_174,
        insurance_policy_id="POL-CI2",
    )
    claim_id = ctx["claim"]["id"]
    validate_success(
        api_client.adjudicate_claim(claim_id, {"amount_cents": 10000}, BILLING)
    )
    validate_success(
        api_client.recoup_claim(claim_id, {"amount_cents": 4000}, BILLING)
    )

    res = api_client.recoup_claim(claim_id, {"amount_cents": 6001}, BILLING)
    validate_error(res, "ERR_RECOUPMENT_EXCEEDS_PAID", expected_status=422)

    claim = get_claim(claim_id)
    assert claim["paid_cents"] == 10000
    assert claim["recouped_cents"] == 4000, (
        "rejection does not drift recouped_cents"
    )
    assert claim["net_receivable_cents"] == 4000
    assert_claim_receivable_identity(claim)
