"""Isolate lot receipt, QC disposition, dual-variant landed costing, FIFO
batch costing, and price-parity computation (PRD sections 3.2, 3.4, 3.5)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    create_ingredient_lot_payload, qc_decision_payload,
    create_bare_supplier, create_qualified_supplier,
    create_qualified_active_supplier, create_received_lot, release_lot,
    reject_lot, create_released_lot, create_owned_line,
    create_pilot_product_with_label, create_active_product_with_label,
    transition_product, set_clock, setup_production_scenario,
    schedule_run, start_run, complete_run, get_run_batch,
    fetch_supplier, fetch_lot,
    assert_ingredient_lot,
)

_PM = TEST_USERS["procurement_manager_headers"]
_QM = TEST_USERS["quality_manager_headers"]


def test_lot_receipt_initializes_remaining_and_provisional_cost(api):
    """PRD section 3.2: "A new lot lands in `QUARANTINE` with `remaining_kg`
    initialized to the full `quantity_kg` and the supplier's `open_lot_count`
    incremented by one." and "the agreement's `base_price_per_kg_cents` is
    multiplied by one plus the lot's `market_index_pct`, the product is
    rounded half-up to a whole cent, the rounded figure is clamped so that it
    never falls below `price_floor_cents` and never rises above
    `price_cap_cents` ... and finally a flat freight estimate of 40 cents per
    kilogram is added on top." (500 x 1.0 = 500 inside [400, 540], + 40 = 540.)

    Design: Corner/entities/cn_ent_lot_create_initializes_remaining_and_provisional
    """
    supplier = create_qualified_active_supplier(supplier_code="SUP-K-1")
    resp = api.create_ingredient_lot(
        create_ingredient_lot_payload(supplier["id"], lot_code="LOT-K-1",
                                      quantity_kg=500),
        _PM)
    lot = validate_success(resp, 201)
    assert_ingredient_lot(lot)
    assert lot["provisional_unit_cost_cents"] == 540
    assert lot["remaining_kg"] == 500
    assert lot["qc_status"] == "QUARANTINE"
    assert lot["final_unit_cost_cents"] is None
    assert fetch_supplier(supplier["id"])["open_lot_count"] == 1


def test_lot_receipt_requires_active_agreement(api):
    """PRD section 3.2: "Receipt is refused when the supplier's agreement is
    anything other than `ACTIVE` — `ERR_AGREEMENT_NOT_ACTIVE`".

    Design: Corner/validations/cn_val_lot_receipt_requires_active_agreement
    """
    supplier = create_qualified_supplier(supplier_code="SUP-K-31")
    resp = api.create_ingredient_lot(
        create_ingredient_lot_payload(supplier["id"], lot_code="LOT-K-31",
                                      quantity_kg=10),
        _PM)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_overreceipt_tolerance_110_percent_inclusive_boundary(api):
    """PRD section 3.2: receipt "is refused when the cumulative kilograms
    across the supplier's lots that have not been rejected, including the
    arriving lot, would exceed 110 percent of the agreement's
    `committed_volume_kg` (`ERR_VOLUME_TOLERANCE_EXCEEDED`)." Against a
    committed 100 kg, 110 kg is exactly at the bound (accepted) and one more
    kilogram breaches it.

    Design: Corner/validations/cn_val_volume_tolerance_boundary
    """
    supplier = create_qualified_active_supplier(
        supplier_code="SUP-K-30", committed_volume_kg=100)
    resp_ok = api.create_ingredient_lot(
        create_ingredient_lot_payload(supplier["id"], lot_code="LOT-K-30A",
                                      quantity_kg=110),
        _PM)
    lot = validate_success(resp_ok, 201)
    assert lot["quantity_kg"] == 110
    resp_bad = api.create_ingredient_lot(
        create_ingredient_lot_payload(supplier["id"], lot_code="LOT-K-30B",
                                      quantity_kg=1,
                                      received_at="2026-09-02T00:00:00Z"),
        _PM)
    validate_error(resp_bad, ApiErrorId.ERR_VOLUME_TOLERANCE_EXCEEDED)


def test_lot_release_twice_is_not_idempotent(api):
    """PRD section 3.2: the QualityManager's "`decision` either releases or
    rejects a quarantined lot" — a lot already RELEASED no longer sits in
    QUARANTINE, so per PRD section 2.8 the repeat is `ERR_INVALID_STATE`
    (409). The first release's final cost and the supplier's delivered volume
    are retained exactly once ("Releasing adds the lot's `quantity_kg` to the
    supplier's `delivered_volume_kg`").

    Design: Corner/state_machines/cn_sm_lot_release_twice_returns_409
    """
    supplier = create_qualified_active_supplier(supplier_code="SUP-K-1")
    lot = create_released_lot(supplier["id"], lot_code="LOT-K-1",
                              quantity_kg=500)
    assert lot["final_unit_cost_cents"] == 535
    resp = api.qc_decision(
        lot["id"],
        qc_decision_payload("RELEASED", invoiced_unit_cost_cents=999,
                            actual_freight_cents_per_kg=99),
        _QM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = fetch_lot(lot["id"])
    assert after["final_unit_cost_cents"] == 535
    assert fetch_supplier(supplier["id"])["delivered_volume_kg"] == 500


def test_lot_provisional_cost_clamps_indexed_base_to_cap(api):
    """PRD section 3.2: "Receipt also stamps a `provisional_unit_cost_cents`":
    base 500 indexed by market_index_pct 0.10 gives 550, "clamped so that it
    never falls below `price_floor_cents` and never rises above
    `price_cap_cents`" (cap 540), "and finally a flat freight estimate of 40
    cents per kilogram is added on top" -> 580. The final cost is "null until
    this moment" (release).

    Design: Difficulty/dual_variant_calc/dvc_lot_landed_cost_provisional_vs_final
    """
    set_clock()
    supplier = create_qualified_active_supplier(supplier_code="SUP-LC-1")
    resp = api.create_ingredient_lot(
        create_ingredient_lot_payload(supplier["id"], lot_code="LOT-LC-1",
                                      quantity_kg=100, market_index_pct=0.10),
        _PM)
    lot = validate_success(resp, 201)
    assert lot["provisional_unit_cost_cents"] == 580
    assert lot["final_unit_cost_cents"] is None


def test_lot_final_cost_uses_invoice_and_actual_freight(api):
    """PRD section 3.2: "On release the lot's `final_unit_cost_cents`, null
    until this moment, is computed by clamping the invoiced unit cost between
    the same floor and cap (inclusive) and adding the actual freight per
    kilogram" — clamp(520, 400, 540) + 35 = 555 — while the provisional
    variant stays stored at 580 beside it, "and the two differ whenever the
    indexed estimate or the freight estimate diverged from the invoice".

    Design: Difficulty/dual_variant_calc/dvc_lot_landed_cost_provisional_vs_final
    """
    set_clock()
    supplier = create_qualified_active_supplier(supplier_code="SUP-LC-1")
    lot = create_received_lot(supplier["id"], lot_code="LOT-LC-1",
                              quantity_kg=100, market_index_pct=0.10)
    resp = api.qc_decision(
        lot["id"],
        qc_decision_payload("RELEASED", invoiced_unit_cost_cents=520,
                            actual_freight_cents_per_kg=35),
        _QM)
    released = validate_success(resp)
    assert released["qc_status"] == "RELEASED"
    assert released["final_unit_cost_cents"] == 555
    assert released["provisional_unit_cost_cents"] == 580
    assert released["provisional_unit_cost_cents"] != (
        released["final_unit_cost_cents"])


def test_batch_cost_rounds_per_lot_before_summing(api):
    """PRD section 3.5: "Each consumed lot contributes its
    `final_unit_cost_cents` multiplied by the kilograms taken from it, rounded
    half-up to a whole cent per lot; those per-lot amounts are then summed
    into the run's total cost." and "the run's `unit_cost_cents_per_case` is
    the total cost divided by `cases_produced`, rounded half-up to a whole
    cent". FIFO consumes oldest first by received_at: 50 kg x 550 + 35 kg x
    483 = 27500 + 16905 = 44405; round_half_up(44405 / 10) = 4441 (a
    half-even rounding would give 4440).

    Design: Corner/calculations/cn_calc_batch_cost_half_up_boundary
    """
    set_clock()
    supplier = create_qualified_active_supplier(supplier_code="SUP-K-11")
    lot_a = create_received_lot(supplier["id"], lot_code="LOT-K-A",
                                quantity_kg=50,
                                received_at="2026-09-01T00:00:00Z")
    release_lot(lot_a["id"], invoiced_unit_cost_cents=510,
                actual_freight_cents_per_kg=40)
    lot_b = create_received_lot(supplier["id"], lot_code="LOT-K-B",
                                quantity_kg=100,
                                received_at="2026-09-02T00:00:00Z")
    release_lot(lot_b["id"], invoiced_unit_cost_cents=448,
                actual_freight_cents_per_kg=35)
    line = create_owned_line(line_code="LINE-K-1")
    product, label = create_active_product_with_label(
        {"product_code": "PROD-K-11"})
    ctx = {"line": line, "product": product, "label": label}
    run = schedule_run(ctx)
    start_run(run["id"])
    run = complete_run(run["id"], 100)
    assert run["consumed_lot_ids"] == [lot_a["id"], lot_b["id"]]
    assert fetch_lot(lot_a["id"])["qc_status"] == "DEPLETED"
    assert fetch_lot(lot_b["id"])["remaining_kg"] == 65
    batch = get_run_batch(run["id"])
    assert batch["unit_cost_cents_per_case"] == 4441


def test_parity_counts_only_released_matching_lots(api):
    """PRD section 3.4: "The computation considers only released, non-depleted
    isolate lots of the matching isolate type — lots in `RELEASED` status with
    `remaining_kg` above zero, whose supplier's `isolate_type` equals the
    product's." A QUARANTINE lot and a REJECTED lot move neither numerator nor
    weight, so only the 555-cent released lot counts: 555 x 1.35 + 110 = 859.

    Design: Corner/calculations/cn_calc_parity_input_set_filtering
    """
    set_clock()
    supplier = create_qualified_active_supplier(supplier_code="SUP-K-12")
    lot_r = create_received_lot(supplier["id"], lot_code="LOT-K-R",
                                quantity_kg=200)
    release_lot(lot_r["id"], invoiced_unit_cost_cents=520,
                actual_freight_cents_per_kg=35)
    create_received_lot(supplier["id"], lot_code="LOT-K-Q", quantity_kg=100)
    lot_x = create_received_lot(supplier["id"], lot_code="LOT-K-X",
                                quantity_kg=50)
    reject_lot(lot_x["id"])
    product, _label = create_pilot_product_with_label(
        {"product_code": "PROD-K-12"})
    product = transition_product(product["id"], "ACTIVE")
    assert product["unit_cost_per_kg_cents"] == 859
    assert product["price_parity_index"] == pytest.approx(0.9337, abs=1e-9)
    assert product["parity_goal_met"] is True


def test_parity_unit_cost_weights_two_lots_by_remaining_kg(api):
    """PRD section 3.4: "a weighted average lot cost per kilogram is formed —
    each lot's `final_unit_cost_cents` weighted by its `remaining_kg`, divided
    by the total remaining kilograms, held as an exact rational value — then
    marked up by 35 percent for extrusion processing and increased by 110
    cents of packaging per kilogram, with the result rounded half-up to a
    whole cent and stored as `unit_cost_per_kg_cents`." (555 x 200 + 475 x
    100) / 300 = 528.333...; x 1.35 + 110 = 823.25 -> 823.

    Design: Difficulty/combinatorial_formula/cf_price_parity_nested_inputs
    """
    set_clock()
    supplier = create_qualified_active_supplier(supplier_code="SUP-PAR-1")
    lot_a = create_received_lot(supplier["id"], lot_code="LOT-PAR-A",
                                quantity_kg=200)
    release_lot(lot_a["id"], invoiced_unit_cost_cents=520,
                actual_freight_cents_per_kg=35)
    lot_b = create_received_lot(supplier["id"], lot_code="LOT-PAR-B",
                                quantity_kg=100,
                                received_at="2026-09-02T00:00:00Z",
                                moisture_pct=6.2, protein_content_pct=83.0)
    release_lot(lot_b["id"], invoiced_unit_cost_cents=440,
                actual_freight_cents_per_kg=35)
    product, _label = create_pilot_product_with_label(
        {"product_code": "PROD-PAR-1"})
    product = transition_product(product["id"], "ACTIVE")
    assert product["status"] == "ACTIVE"
    assert product["unit_cost_per_kg_cents"] == 823


def test_parity_index_divides_by_reference_and_sets_goal(api):
    """PRD section 3.4: "Dividing that unit cost by the animal-protein
    reference price of 920 cents per kilogram and rounding half-up to four
    decimal places yields the `price_parity_index`; `parity_goal_met` is true
    when the index is at most 1.05". 823 / 920 = 0.89456... -> 0.8946, which
    meets the goal.

    Design: Difficulty/combinatorial_formula/cf_price_parity_nested_inputs
    """
    set_clock()
    supplier = create_qualified_active_supplier(supplier_code="SUP-PAR-1")
    lot_a = create_received_lot(supplier["id"], lot_code="LOT-PAR-A",
                                quantity_kg=200)
    release_lot(lot_a["id"], invoiced_unit_cost_cents=520,
                actual_freight_cents_per_kg=35)
    lot_b = create_received_lot(supplier["id"], lot_code="LOT-PAR-B",
                                quantity_kg=100,
                                received_at="2026-09-02T00:00:00Z",
                                moisture_pct=6.2, protein_content_pct=83.0)
    release_lot(lot_b["id"], invoiced_unit_cost_cents=440,
                actual_freight_cents_per_kg=35)
    product, _label = create_pilot_product_with_label(
        {"product_code": "PROD-PAR-1"})
    product = transition_product(product["id"], "ACTIVE")
    assert product["price_parity_index"] == pytest.approx(0.8946, abs=1e-9)
    assert product["parity_goal_met"] is True
