"""Two-stage kit accounting: the capacity-based reservation booked at issuance
versus the measurement-based settlement booked at certification, plus the ledger
appends and program totals that record the divergence between them."""

from test_helpers import (
    assert_certificate,
    assert_kit,
    assert_ledger_sequence,
    assert_program_balances,
    certify_destruction_for,
    read_kit,
    read_ledger_entries,
    read_program,
    setup_certifiable_shipment,
)


def test_01_issuance_reserves_the_capacity_based_provisional_cost(api):
    """The provisional figure prices the kit from catalogue capacity alone: the
    1450-cent ONE_QUART base plus a transport component of 100 capacity units at
    4 g each, priced at 38 cents/kg, giving 15.2 cents rounded half up to 15, for
    1465 cents in total.

    PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."

    Design: Difficulty/dual_variant_calc/kit_cost_provisional_vs_final_divergence_on_manufacturer_program
    """
    ctx = setup_certifiable_shipment(api)

    kit = read_kit(api, ctx["kit"]["id"])
    assert_kit(
        kit,
        container_size="ONE_QUART",
        required_units=69,
        capacity_units=100,
        provisional_cost_cents=1465,
    )


def test_02_certification_settles_from_the_measured_shipment_weight(api):
    """The final figure re-prices the identical kit from measured facts: the same
    1450-cent base, a transport component from the 1520 g the technician observed
    (57.76 cents rounded half up to 58), a destruction component of 69 units at the
    3-cent MANUFACTURER rate (207), and no surcharge, giving 1715 cents.

    PRD 3.8: "The transport component takes the shipment's `observed_gross_weight_grams`, multiplies by the transport rate of 38 cents per kilogram, divides by 1000 to convert grams to kilograms, and rounds half up to a whole cent; note that this uses the weight the technician measured, not the capacity-based estimate the reservation used."
    PRD 3.8: "The destruction component multiplies the certificate's `destroyed_units` by the sponsor's per-unit destruction rate — 3 cents per unit when the sponsor's `sponsor_type` is `MANUFACTURER` and 2.5 cents per unit when it is `HEALTH_PLAN` — and rounds half up to a whole cent."

    Design: Difficulty/dual_variant_calc/kit_cost_provisional_vs_final_divergence_on_manufacturer_program
    """
    ctx = setup_certifiable_shipment(api)

    certificate = certify_destruction_for(api, ctx, destroyed_units=69)

    assert_certificate(
        certificate,
        destroyed_units=69,
        final_kit_cost_cents=1715,
        rebate_pct_applied=0.00,
        status="ISSUED",
    )


def test_03_the_first_settlement_keys_the_rebate_tier_at_zero(api):
    """The rebate basis is the program's `committed_cents` before this certificate's
    appends (0) plus the capped pre-rebate amount (1715), which lands in the lowest
    tier, so no rebate is deducted and `final_kit_cost_cents` stays at 1715.

    PRD 3.8: "The tiers are: a basis from 0 through 14999 cents inclusive gives 0; a basis from 15000 through 29999 cents inclusive gives 0.03; and a basis from 30000 through 100000000 cents inclusive gives 0.06."

    Design: Difficulty/dual_variant_calc/kit_cost_provisional_vs_final_divergence_on_manufacturer_program
    """
    ctx = setup_certifiable_shipment(api)

    certificate = certify_destruction_for(api, ctx, destroyed_units=69)

    assert certificate["rebate_pct_applied"] == 0.00
    assert certificate["final_kit_cost_cents"] == 1715


def test_04_program_totals_expose_the_two_hundred_fifty_cent_reconciliation_delta(api):
    """Both accounting totals are populated from the one settled kit, and the gap
    between them is exactly the 250 cents by which the measured settlement exceeded
    the capacity-based reservation.

    PRD 3.2: "Beyond the reserved/committed/available triple a program maintains five derived counters that a sponsor uses to reconcile: `kits_issued_count`, the number of kits under this program's enrollments whose status is anything other than `VOIDED`; `kits_settled_count`, the number of destruction certificates in status `ISSUED` against this program's kits; `provisional_total_cents`, the sum of `provisional_cost_cents` over this program's kits that carry an `ISSUED` certificate; and `final_total_cents`, the sum of `final_kit_cost_cents` over this program's `ISSUED` certificates."

    Design: Difficulty/dual_variant_calc/kit_cost_provisional_vs_final_divergence_on_manufacturer_program
    """
    ctx = setup_certifiable_shipment(api)
    certify_destruction_for(api, ctx, destroyed_units=69)

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert program["provisional_total_cents"] == 1465
    assert program["final_total_cents"] == 1715
    assert program["final_total_cents"] - program["provisional_total_cents"] == 250
    assert program["kits_settled_count"] == 1


def test_05_settlement_releases_the_reservation_and_commits_the_final_figure(api):
    """Settlement moves the money from reserved to committed: `reserved_cents` falls
    back to 0 and `committed_cents` holds the final 1715, leaving 498285 available
    against the 500000 ceiling.

    PRD 2.9: "On the program side, `reserved_cents` is the sum of `RESERVATION` amounts less the sum of `RESERVATION_RELEASE` amounts over that program's entries, and `committed_cents` is the sum of `COMMITMENT` amounts less the sum of `COMMITMENT_REVERSAL` amounts."
    PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."

    Design: Difficulty/dual_variant_calc/kit_cost_provisional_vs_final_divergence_on_manufacturer_program
    """
    ctx = setup_certifiable_shipment(api)
    certify_destruction_for(api, ctx, destroyed_units=69)

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program,
        reserved_cents=0,
        committed_cents=1715,
        available_cents=498285,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )


def test_06_the_ledger_records_reservation_release_then_commitment(api):
    """The kit's whole money history is three appends in `sequence_no` order: the
    reservation at issuance, then the release and the commitment that certification
    writes in that pinned order.

    PRD 3.8: "Two ledger entries are appended in a pinned order that must not be swapped: first a `RESERVATION_RELEASE` for the negation of the kit's `provisional_cost_cents`, then, at the immediately following `sequence_no`, a `COMMITMENT` for the positive `final_kit_cost_cents`."

    Design: Difficulty/dual_variant_calc/kit_cost_provisional_vs_final_divergence_on_manufacturer_program
    """
    ctx = setup_certifiable_shipment(api)
    certify_destruction_for(api, ctx, destroyed_units=69)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_sequence(
        entries,
        [
            (1, "RESERVATION", 1465),
            (2, "RESERVATION_RELEASE", -1465),
            (3, "COMMITMENT", 1715),
        ],
    )
