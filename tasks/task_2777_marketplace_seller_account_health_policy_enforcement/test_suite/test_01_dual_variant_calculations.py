"""Two calculations that each carry two defensible variants: the order defect
rate's provisional and settled readings, and the rolling and claim-exposure
reserve bases.
"""

from test_helpers import (
    INVESTIGATOR,
    assert_cents,
    assert_funds,
    assert_immutable_evidence_fields,
    assert_posture,
    assert_rate,
    credit,
    evaluate,
    file_snapshot,
    file_violation,
    open_hold,
    open_investigation,
    publish_rule,
    read_seller,
    register_seller,
    set_clock,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"


def _seller_with_two_windows(api):
    """Two non-overlapping windows inside the ninety-day lookback."""
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Northwind Retail LLC", email="ops@northwind-retail.example",
        tax_id_hash="TAX-NW-0001", payout_bank_token="BANK-NW-0001",
        address_fingerprint="ADDR-NW-0001",
    )
    file_snapshot(
        api, seller["id"], "2026-06-01T00:00:00.000Z", "2026-07-01T00:00:00.000Z",
        order_volume=1500, delivered_or_refunded_volume=1400, defect_claims_pending=5,
        defect_claims_substantiated=16, late_shipments=56, pre_fulfillment_cancellations=22,
        shipments_total=1450, shipments_with_valid_tracking=1300, source="PLATFORM_PIPELINE",
    )
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=1600, delivered_or_refunded_volume=1550, defect_claims_pending=18,
        defect_claims_substantiated=22, late_shipments=80, pre_fulfillment_cancellations=45,
        shipments_total=1580, shipments_with_valid_tracking=1371, source="PLATFORM_PIPELINE",
    )
    return seller


def test_provisional_and_settled_defect_readings_diverge_on_one_evaluation(api):
    """PRD §3.4: "The **provisional** reading, stored as `odr_provisional`, looks
    only at the latest snapshot in the input set — the one with the greatest
    `window_end`, ties broken by `created_at` ascending — and asks how many
    claims were opened against it: add that snapshot's `defect_claims_pending` to
    its `defect_claims_substantiated`, divide by that same snapshot's
    `order_volume`, and round half-up to four decimals."

    Design: Difficulty/dual_variant_calc/odr_provisional_vs_final_diverge_on_two_snapshot_window
    """
    seller = _seller_with_two_windows(api)

    evaluation = validate_success(api.create_health_evaluation(seller["id"], INVESTIGATOR), 201)

    assert_immutable_evidence_fields(evaluation)
    assert evaluation["input_snapshot_count"] == 2
    assert evaluation["input_window_start"] == "2026-06-01T00:00:00.000Z"
    assert evaluation["input_window_end"] == "2026-08-01T00:00:00.000Z"
    # (18 + 22) / 1600 reads the latest snapshot only.
    assert_rate(evaluation["odr_provisional"], "0.0250", "odr_provisional")
    # (16 + 22) / (1400 + 1550) counts proven claims across the whole input set.
    assert_rate(evaluation["odr_final"], "0.0129", "odr_final")
    assert_rate(evaluation["odr_variant_delta"], "0.0121", "odr_variant_delta")
    assert evaluation["odr_provisional"] != evaluation["odr_final"]


def test_only_the_settled_defect_reading_decides_the_breach_and_the_tier(api):
    """PRD §3.4: "`odr_final` is the value that decides whether the order defect
    rate has breached, the value that feeds the health score, and therefore the
    value behind the tier."

    Design: Difficulty/dual_variant_calc/odr_provisional_vs_final_diverge_on_two_snapshot_window
    """
    seller = _seller_with_two_windows(api)

    evaluation = validate_success(api.create_health_evaluation(seller["id"], INVESTIGATOR), 201)

    # odr_final 0.0129 breaches, late 0.0439 breaches, tracking 0.8815 breaches,
    # cancellation 0.0216 does not.
    assert evaluation["breached_metrics"] == [
        "ORDER_DEFECT_RATE", "LATE_SHIPMENT_RATE", "VALID_TRACKING_RATE",
    ]
    assert evaluation["metric_tier"] == "BREACHING"
    # No rule in the catalogue is both a shipping-performance rule and
    # account-scoped, so the automatic violation pool is empty.
    assert evaluation["auto_violation_id"] is None

    stored = read_seller(api, seller["id"])
    assert stored["metric_tier"] == "BREACHING"
    assert_posture(stored, disbursement_state="NORMAL")


def _seller_priced_at_tier_two(api, legal_name, email, tax, bank, addr):
    """A seller whose snapshotted risk tier resolves to TIER_2 with 300000 cents
    available, 21 open defect claim units and one open investigation."""
    seller = register_seller(
        api, legal_name=legal_name, email=email, tax_id_hash=tax,
        payout_bank_token=bank, address_fingerprint=addr,
    )
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=2000, delivered_or_refunded_volume=2000, defect_claims_pending=21,
        defect_claims_substantiated=20, late_shipments=60, pre_fulfillment_cancellations=40,
        shipments_total=2000, shipments_with_valid_tracking=1980, source="PLATFORM_PIPELINE",
    )
    evaluation = evaluate(api, seller["id"])
    assert evaluation["metric_tier"] == "AT_RISK"
    credit(api, seller["id"], 300000, "PAYOUT-01")
    return seller


def test_rolling_reserve_is_a_share_of_the_available_balance(api):
    """PRD §3.9: "Under `ROLLING`, the reserve is a share of the balance actually
    sitting on the account: multiply `available_balance_cents` by the tier's
    rolling percentage — 10 percent at `TIER_1`, 20 percent at `TIER_2`, and 30
    percent at `TIER_3` — and round the product half-up to a whole number of
    cents."

    Design: Difficulty/dual_variant_calc/reserve_rolling_vs_claim_exposure_diverge_on_identical_seller_state
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-ACC-1", category="LISTING_ACCURACY", base_severity_weight=2.80,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _seller_priced_at_tier_two(
        api, "Alder Goods LLC", "ops@alder-goods.example", "TAX-AL-0001",
        "BANK-AL-0001", "ADDR-AL-0001",
    )
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-A-0001"
    )
    open_investigation(api, violation["id"])
    stored = read_seller(api, seller["id"])
    assert_posture(stored, enforcement_state="ACTIVE", disbursement_state="RESERVE_HELD",
                   severity_points_balance="0.00")
    assert stored["open_defect_claim_units"] == 21

    hold = open_hold(
        api, seller["id"], "2026-08-01T00:00:00.000Z", "2026-08-31T00:00:00.000Z",
        reserve_basis="ROLLING",
    )

    assert hold["risk_tier"] == "TIER_2"
    assert_cents(hold["held_amount_cents"], 60000, "held_amount_cents")
    assert_funds(read_seller(api, seller["id"]), available=240000, held=60000,
                 credited=300000, debited=0)


def test_claim_exposure_reserve_ignores_the_balance_and_diverges_from_rolling(api):
    """PRD §3.9: "Under `CLAIM_EXPOSURE`, the reserve is the money a wave of open
    defect claims could cost: multiply the seller's `open_defect_claim_units` by
    an assumed exposure of 9000 cents — ninety dollars — per claim, then by the
    tier's exposure multiplier of 1.00 at `TIER_1`, 1.25 at `TIER_2`, or 1.50 at
    `TIER_3`, and round the product half-up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/reserve_rolling_vs_claim_exposure_diverge_on_identical_seller_state
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-ACC-1", category="LISTING_ACCURACY", base_severity_weight=2.80,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller_a = _seller_priced_at_tier_two(
        api, "Alder Goods LLC", "ops@alder-goods.example", "TAX-AL-0001",
        "BANK-AL-0001", "ADDR-AL-0001",
    )
    seller_b = _seller_priced_at_tier_two(
        api, "Birch Depot LLC", "ops@birch-depot.example", "TAX-BI-0002",
        "BANK-BI-0002", "ADDR-BI-0002",
    )
    for seller in (seller_a, seller_b):
        violation = file_violation(api, seller["id"], rule["id"], reporter_type="BUYER")
        open_investigation(api, violation["id"])

    hold_a = open_hold(
        api, seller_a["id"], "2026-08-01T00:00:00.000Z", "2026-08-31T00:00:00.000Z",
        reserve_basis="ROLLING",
    )
    hold_b = open_hold(
        api, seller_b["id"], "2026-08-01T00:00:00.000Z", "2026-08-31T00:00:00.000Z",
        reserve_basis="CLAIM_EXPOSURE",
    )

    assert hold_b["risk_tier"] == "TIER_2"
    # 21 * 9000 * 1.25 = 236250, computed without reference to the balance.
    assert_cents(hold_b["held_amount_cents"], 236250, "held_amount_cents")
    assert hold_b["held_amount_cents"] - hold_a["held_amount_cents"] == 176250
    assert_funds(read_seller(api, seller_b["id"]), available=63750, held=236250,
                 credited=300000, debited=0)
    assert_funds(read_seller(api, seller_a["id"]), available=240000, held=60000)
