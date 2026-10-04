"""Contract close-out: the automatic 98% fulfillment and the two payment
variants (provisional at receiving vs storage-adjusted final at settlement),
including the pinned shrink-then-downgrade evaluation order."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    deliver_lot,
    make_active_contract,
    record_reading,
    set_clock,
    set_posture_quarantined,
    set_posture_watch,
    setup_procurement,
    validate_error,
    validate_success,
)

GRM = TEST_USERS["grower_relations_manager_headers"]


def test_contract_auto_fulfills_at_exactly_98_percent_of_volume(api):
    """PRD §3.1: "immediately after a newly received contracted lot is
    counted, if the contract's `delivered_volume_cwt` has reached at least 98
    percent of its `contracted_volume_cwt` — the threshold computed as 0.98
    times the contracted volume, rounded half-up to one decimal place — the
    contract transitions automatically to `FULFILLED`."
    PRD §3.1: "Final settlement writes `settlement_amount_cents` on the
    contract and `final_payment_cents` on every contracted lot."

    Design: Corner/state_machines/contract_auto_fulfills_at_exactly_98_percent_of_volume
    """
    world = setup_procurement(
        api=api,
        contract_overrides={"contracted_acres": 1, "expected_yield_cwt_per_acre": 400},
    )
    contract = world["contract"]
    assert contract["contracted_volume_cwt"] == 400.0

    lot = deliver_lot(
        contract["id"], world["facility"]["id"], world["grower"]["id"],
        api=api, gross_weight_cwt=402.0, tare_weight_cwt=10.0,
    )
    assert lot["net_weight_cwt"] == 392.0, "392.0 is exactly 98.0% of 400.0"

    settled = validate_success(api.get_crop_contract(contract["id"], GRM))
    assert settled["status"] == "FULFILLED", (
        f"the auto-transition is inclusive at 98%, got {settled['status']}"
    )
    # Zero storage days: storage_loss_pct 0 -> final equals provisional.
    assert settled["settlement_amount_cents"] == 1058400, (
        f"392.0 x 2500 x 1.08 = 1058400, got {settled['settlement_amount_cents']}"
    )
    reread_lot = validate_success(api.get_potato_lot(lot["id"], GRM))
    assert reread_lot["final_payment_cents"] == 1058400
    assert reread_lot["provisional_payment_cents"] == 1058400


def test_lot_settlement_provisional_vs_storage_adjusted_final(api):
    """PRD §3.1: "The raw loss percentage is those days multiplied by a daily
    loss of 0.02 percentage points, multiplied further by the posture factor
    of the lot's facility **at settlement time**: 1.0 for `NORMAL`, 1.5 for
    `WATCH`, and 3.0 for `QUARANTINED`."
    PRD §3.1: "This final settlement is the second of two payment variants:
    the provisional payment computed at receiving (§3.2) uses the
    receiving-time grade and the full `net_weight_cwt` with no shrinkage and
    no downgrade, so the two diverge whenever a lot's storage loss is greater
    than zero."
    PRD §3.2: "the lot's `net_weight_cwt` multiplied by the contract's
    `base_price_per_cwt_cents` and by the grade multiplier — 1.08 for `A`,
    1.03 for `B`, 0.88 for `C`, 0.00 for `REJECT` — with the single per-lot
    product rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/lot_settlement_provisional_vs_storage_adjusted_final
    """
    world = setup_procurement(api=api)
    lot = deliver_lot(
        world["contract"]["id"], world["facility"]["id"], world["grower"]["id"], api=api
    )
    assert lot["provisional_payment_cents"] == 2700000, (
        f"receiving variant: 1000.0 cwt x 2500 x 1.08 = 2700000, got {lot['provisional_payment_cents']}"
    )
    assert lot["final_payment_cents"] is None

    set_posture_watch(world["facility"]["id"], api=api)  # sprout 2.5 -> WATCH
    set_clock("2026-10-01T00:00:00Z", api=api)  # 30 storage days

    contract = validate_success(api.declare_shortfall(world["contract"]["id"], GRM))
    assert contract["status"] == "SHORTFALL_DECLARED"
    # WATCH factor 1.5: 30 x 0.02 x 1.5 = 0.9% loss -> shrinkage 9.0 cwt ->
    # final net 991.0 cwt at grade A: 991.0 x 2500 x 1.08 = 2675700.
    assert contract["settlement_amount_cents"] == 2675700, (
        f"final variant pays 991.0 cwt at grade A = 2675700, got {contract['settlement_amount_cents']}"
    )

    settled_lot = validate_success(api.get_potato_lot(lot["id"], GRM))
    assert settled_lot["final_payment_cents"] == 2675700
    assert settled_lot["provisional_payment_cents"] == 2700000, (
        "the provisional figure stays on the lot; the variants diverge by 24300 cents"
    )
    assert contract["settlement_amount_cents"] != settled_lot["provisional_payment_cents"]


def test_lot_settlement_normal_posture_partial_loss_diverges(api):
    """PRD §3.1: "The lot's days in storage are the whole days elapsed between
    its `created_at` and the settlement clock — the elapsed seconds divided by
    86,400 and rounded down, never less than zero."
    PRD §3.1: "The raw loss percentage is those days multiplied by a daily
    loss of 0.02 percentage points, multiplied further by the posture factor
    of the lot's facility **at settlement time**: 1.0 for `NORMAL`, 1.5 for
    `WATCH`, and 3.0 for `QUARANTINED`. The raw figure is capped at a maximum
    loss of 15.0 percent, and the resulting `storage_loss_pct` is rounded
    half-up to two decimal places."
    PRD §3.1: "The contract's `settlement_amount_cents` is then the plain sum
    of the per-lot `final_payment_cents` values, which are already rounded; no
    second rounding is applied to the sum."

    Design: Difficulty/dual_variant_calc/lot_settlement_provisional_vs_storage_adjusted_final
    """
    world = setup_procurement(api=api)
    lot = deliver_lot(
        world["contract"]["id"], world["facility"]["id"], world["grower"]["id"], api=api
    )
    # No reading: the facility stays NORMAL (factor 1.0). 15 storage days.
    set_clock("2026-09-16T00:00:00Z", api=api)

    contract = validate_success(api.declare_shortfall(world["contract"]["id"], GRM))
    # 15 x 0.02 x 1.0 = 0.30% -> shrinkage 3.0 cwt -> 997.0 x 2500 x 1.08.
    assert contract["settlement_amount_cents"] == 2691900, (
        f"NORMAL 15-day loss pays 997.0 cwt at grade A = 2691900, got {contract['settlement_amount_cents']}"
    )
    settled_lot = validate_success(api.get_potato_lot(lot["id"], GRM))
    assert settled_lot["final_payment_cents"] == 2691900
    assert settled_lot["provisional_payment_cents"] == 2700000
    assert contract["settlement_amount_cents"] != settled_lot["provisional_payment_cents"], (
        "any storage loss greater than zero makes the two variants diverge"
    )


def test_final_settlement_quarantine_loss_downgrades_grade(api):
    """PRD §3.1: "The evaluation order is pinned to break the circular
    dependency between grade and shrinkage."
    PRD §3.1: "If the lot's `storage_loss_pct` exceeds 10.0 percent, the grade
    is downgraded one tier: `A` becomes `B`, `B` becomes `C`, `C` stays `C`,
    and `REJECT` stays `REJECT`."
    PRD §3.1: "The lot's `final_payment_cents` is the final net hundredweight
    multiplied by the contract's `base_price_per_cwt_cents` and by the grade
    multiplier of the final grade — 1.08 for `A`, 1.03 for `B`, 0.88 for `C`,
    and 0.00 for `REJECT` — rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/final_settlement_pinned_evaluation_order_shrink_then_downgrade
    """
    world = setup_procurement(api=api)
    lot = deliver_lot(
        world["contract"]["id"], world["facility"]["id"], world["grower"]["id"], api=api
    )
    assert lot["grade"] == "A"
    set_posture_quarantined(world["facility"]["id"], api=api)  # disease 7.0 -> QUARANTINED
    set_clock("2027-03-20T00:00:00Z", api=api)  # 200 storage days

    contract = validate_success(api.declare_shortfall(world["contract"]["id"], GRM))
    # 200 x 0.02 x 3.0 = 12.0% loss (under the 15.0 cap) -> shrinkage 120.0
    # -> 880.0 cwt; 12.0 > 10.0 downgrades A -> B; 880.0 x 2500 x 1.03.
    assert contract["settlement_amount_cents"] == 2266000, (
        f"pinned order (shrink first, downgrade at >10%, price last) yields 2266000, "
        f"got {contract['settlement_amount_cents']}"
    )
    settled_lot = validate_success(api.get_potato_lot(lot["id"], GRM))
    assert settled_lot["final_payment_cents"] == 2266000
    assert contract["settlement_amount_cents"] != 2376000, "880.0 cwt priced at A would be 2376000"
    assert contract["settlement_amount_cents"] != 2700000, "the provisional figure was 2700000"


def test_final_settlement_loss_exactly_10_percent_does_not_downgrade(api):
    """PRD §3.1: "If the lot's `storage_loss_pct` exceeds 10.0 percent, the
    grade is downgraded one tier: `A` becomes `B`, `B` becomes `C`, `C` stays
    `C`, and `REJECT` stays `REJECT`."
    PRD §3.2: "Grading is computed at receiving and is read-only."

    Design: Difficulty/combinatorial_formula/final_settlement_pinned_evaluation_order_shrink_then_downgrade
    """
    world = setup_procurement(api=api)
    lot = deliver_lot(
        world["contract"]["id"], world["facility"]["id"], world["grower"]["id"], api=api
    )
    # NORMAL posture, 500 storage days: 500 x 0.02 x 1.0 = exactly 10.0% loss.
    set_clock("2028-01-14T00:00:00Z", api=api)

    contract = validate_success(api.declare_shortfall(world["contract"]["id"], GRM))
    # 10.0 does not EXCEED 10.0 -> no downgrade; shrinkage 100.0 ->
    # 900.0 cwt at grade A: 900.0 x 2500 x 1.08 = 2430000.
    assert contract["settlement_amount_cents"] == 2430000, (
        f"at exactly 10.0% the grade holds and payment is 2430000, got {contract['settlement_amount_cents']}"
    )
    settled_lot = validate_success(api.get_potato_lot(lot["id"], GRM))
    assert settled_lot["final_payment_cents"] == 2430000
    assert settled_lot["grade"] == "A", "the receiving-time grade field itself is never rewritten"
