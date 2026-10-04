"""Pricing pipeline: tier boundaries, delivery fee, and dual-variant scores."""
from test_helpers import (
    create_completed_assessment,
    create_customer,
    create_order,
    create_product_models,
    create_store,
    set_clock,
    setup_delivered_order,
    setup_store_with_catalog,
    validate_success,
)
from test_helpers.fixtures import ADMIN, GATEWAY


def _seed_two_price_catalog(store_id):
    create_product_models([
        {"sku": "MAT-150", "name": "M150", "category": "MATTRESS",
         "price_cents": 150000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
        {"sku": "MAT-500", "name": "M500", "category": "MATTRESS",
         "price_cents": 500000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
        {"sku": "MAT-200", "name": "M200", "category": "MATTRESS",
         "price_cents": 200000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
        {"sku": "BED-99", "name": "Sheets99", "category": "BEDDING",
         "price_cents": 99999, "replacement_part_price_cents": 0,
         "warranty_months": 24},
        # PRD requires a candidate in each of the four required categories
        # before an assessment can complete.
        {"sku": "BASE-1", "name": "Base1", "category": "ADJUSTABLE_BASE",
         "price_cents": 180000, "replacement_part_price_cents": 0,
         "warranty_months": 120},
        {"sku": "CHAM-1", "name": "Cham1", "category": "AIR_CHAMBER",
         "price_cents": 40000, "replacement_part_price_cents": 0,
         "warranty_months": 60},
        {"sku": "PUMP-1", "name": "Pump1", "category": "PUMP",
         "price_cents": 30000, "replacement_part_price_cents": 0,
         "warranty_months": 36},
    ])


def test_order_totals_tier_boundaries_and_delivery_fee(api):
    """PRD §3.3: "Third, the discount tier is selected on the subtotal before
    any discount is applied: a subtotal of at least 1000000 cents earns 0.15,
    a subtotal of at least 500000 but below 1000000 earns 0.10, and anything
    below 500000 earns no discount; `discount_cents` is the subtotal
    multiplied by the selected rate, rounded half-up once. Fourth,
    `delivery_fee_cents` is 0 when the pre-discount subtotal is at least
    200000 cents and 9900 otherwise."

    Design: Corner/calculations/order_totals_tier_boundary_and_delivery_fee_threshold
    """
    set_clock()
    store = create_store()
    _seed_two_price_catalog(store["id"])
    customer = create_customer(store["id"], email="o@x.com")
    fa = create_completed_assessment(customer["id"], store["id"])

    order_lo = create_order(customer["id"], fa["id"],
                            [{"sku": "MAT-150", "qty": 1}])
    assert order_lo["subtotal_cents"] == 150000
    assert order_lo["discount_cents"] == 0
    assert order_lo["delivery_fee_cents"] == 9900
    assert order_lo["total_due_cents"] == 159900

    order_hi = create_order(customer["id"], fa["id"],
                            [{"sku": "MAT-500", "qty": 1}])
    assert order_hi["subtotal_cents"] == 500000
    assert order_hi["discount_cents"] == 50000, (
        "tier 1 is inclusive at exactly 500000 subtotal")
    assert order_hi["delivery_fee_cents"] == 0
    assert order_hi["total_due_cents"] == 450000

    order_eq = create_order(customer["id"], fa["id"],
                            [{"sku": "MAT-200", "qty": 1}])
    assert order_eq["subtotal_cents"] == 200000
    assert order_eq["delivery_fee_cents"] == 0, (
        "free-delivery threshold is inclusive at 200000")
    assert order_eq["discount_cents"] == 0
    assert order_eq["total_due_cents"] == 200000

    order_below = create_order(customer["id"], fa["id"],
                               [{"sku": "MAT-150", "qty": 1},
                                {"sku": "BED-99", "qty": 1}])
    assert order_below["subtotal_cents"] == 249999
    assert order_below["discount_cents"] == 0
    assert order_below["delivery_fee_cents"] == 0
    assert order_below["total_due_cents"] == 249999


def test_delivery_fee_keys_on_pre_discount_subtotal(api):
    """PRD §3.3: "Fourth, `delivery_fee_cents` is 0 when the pre-discount
    subtotal is at least 200000 cents and 9900 otherwise. Fifth,
    `total_due_cents` is the subtotal minus the discount plus the delivery
    fee."

    Design: Corner/calculations/order_totals_tier_boundary_and_delivery_fee_threshold
    """
    set_clock()
    store = create_store()
    _seed_two_price_catalog(store["id"])
    customer = create_customer(store["id"], email="o2@x.com")
    fa = create_completed_assessment(customer["id"], store["id"])
    # Subtotal 500000: discount 50000 would pull a post-discount figure to
    # 450000; both sides of 200000 remain fee-free either way, so use the
    # boundary pair instead: 150000 pays the fee, 200000 does not.
    low = create_order(customer["id"], fa["id"], [{"sku": "MAT-150", "qty": 1}])
    high = create_order(customer["id"], fa["id"], [{"sku": "MAT-200", "qty": 1}])
    assert low["delivery_fee_cents"] == 9900
    assert high["delivery_fee_cents"] == 0


def test_sleep_score_provisional_vs_final_diverge_on_same_night(api):
    """PRD §3.6: "The `provisional_score` weights rest at 0.6 and duration at
    0.4, ignoring heart rate, and rounds half-up to an integer. When the
    logical clock is set to a time at or past noon UTC on the day after
    `night_date`, the night finalizes: `status` moves from `PROVISIONAL` to
    `FINAL`, `final_score` is computed with weights 0.5 rest, 0.3 duration,
    and 0.2 heart, rounded half-up and clamped between 0 and 100 — the same
    inputs generally yield a different number than the provisional variant —
    and the device's `final_nights_count` increments by 1."

    Design: Difficulty/dual_variant_calc/sleep_score_provisional_vs_final_diverge_on_same_night
    """
    ctx = setup_delivered_order(email="a@x.com", serial_number="SN-B1")
    device = ctx["device"]
    resp = api.ingest_sleep_night(device["id"], {
        "night_date": "2026-09-01", "minutes_asleep": 420,
        "restlessness_events": 10, "avg_heart_rate": 64}, GATEWAY)
    night = validate_success(resp, expected_status=201)
    # rest = 100-2*10 = 80; duration = round_half_up(420*100/480) = 88 (87.5)
    assert night["provisional_score"] == 83, (
        f"provisional 0.6*80+0.4*88 = 83, got {night['provisional_score']}")
    set_clock("2026-09-02T12:00:00Z")
    final = validate_success(api.get_sleep_night(night["id"], ADMIN))
    # heart = 100-|64-60| = 96; final = round(0.5*80+0.3*88+0.2*96) = 86
    assert final["status"] == "FINAL"
    assert final["final_score"] == 86, (
        f"final 0.5*80+0.3*88+0.2*96 = 86, got {final['final_score']}")
    assert final["provisional_score"] == 83
    assert final["final_score"] != final["provisional_score"]


def test_sleep_night_finalizes_only_after_noon_next_day(api):
    """PRD §3.6: "When the logical clock is set to a time at or past noon UTC
    on the day after `night_date`, the night finalizes: `status` moves from
    `PROVISIONAL` to `FINAL`, `final_score` is computed with weights 0.5 rest,
    0.3 duration, and 0.2 heart, rounded half-up and clamped between 0 and 100
    — the same inputs generally yield a different number than the provisional
    variant — and the device's `final_nights_count` increments by 1."

    Design: Corner/state_machines/sleep_night_finalizes_only_after_noon_next_day
    """
    ctx = setup_delivered_order(email="n@x.com", serial_number="SN-N1")
    device = ctx["device"]
    resp = api.ingest_sleep_night(device["id"], {
        "night_date": "2026-09-01", "minutes_asleep": 420,
        "restlessness_events": 10, "avg_heart_rate": 64}, GATEWAY)
    night = validate_success(resp, expected_status=201)

    set_clock("2026-09-02T11:59:59Z")
    before = validate_success(api.get_sleep_night(night["id"], ADMIN))
    assert before["status"] == "PROVISIONAL"
    assert before.get("final_score") is None

    set_clock("2026-09-02T12:00:00Z")
    after = validate_success(api.get_sleep_night(night["id"], ADMIN))
    assert after["status"] == "FINAL"
    assert after["final_score"] == 86
    dev = validate_success(api.get_device(device["id"], ADMIN))
    assert dev["final_nights_count"] == 1, (
        f"final_nights_count must increment exactly once, got "
        f"{dev['final_nights_count']}")

    set_clock("2026-09-03T00:00:00Z")
    dev2 = validate_success(api.get_device(device["id"], ADMIN))
    assert dev2["final_nights_count"] == 1, "no double finalize"
