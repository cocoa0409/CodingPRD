"""State-machine corners: quarantine initial state, terminal rejection,
discontinue/sunset preconditions, stale training, overage boundary, verdict
gate."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    create_run,
    enroll_and_pass,
    get_success_data,
    make_active_formulation,
    make_certified_contractor,
    make_completed_run,
    make_contractor,
    make_contractor_headers,
    make_dealer,
    create_feedstock_lot_payload,
    make_order,
    make_plant,
    make_product_line,
    make_released_lot,
    make_supplier,
    make_training_module,
    make_under_review_claim,
    make_installed_registration,
    set_clock,
    stock_resin,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]
PM = TEST_USERS["product_manager_headers"]
PA = TEST_USERS["program_admin_headers"]
CA = TEST_USERS["claims_adjuster_headers"]


def test_feedstock_lot_starts_in_quarantine(api):
    """PRD §3.2: "Every lot enters `QUARANTINE`."
    PRD §2.10: "Feedstock enters the plant through quarantined lots and is
    only added to `resin_store` at release."

    Design: Corner/state_machines/feedstock_lot_starts_in_quarantine
    """
    plant = make_plant()
    supplier = make_supplier()
    payload = create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="WOOD_FLOUR", weight_lbs=500,
        received_date="2026-09-01",
    )
    lot = get_success_data(api.create_feedstock_lot(payload, QE))
    assert lot["status"] == "QUARANTINE"
    plant_after = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_after["resin_store"]["WOOD_FLOUR"] == 0


def test_rejected_lot_is_terminal_and_reject_twice_fails(api):
    """PRD §3.2: "`REJECTED` is terminal."
    PRD §3.2: "rejection triggers recomputation of the supplier's
    `reliability_score_bp`"
    PRD §3.1: "Reliability is reportage only: it is recomputed whenever one of
    the supplier's lots is rejected, as ten thousand minus the ratio of
    rejected lot count to total lot count expressed in basis points, computed
    with integer truncation."

    Design: Corner/state_machines/rejected_lot_is_terminal_and_reject_twice_fails
    """
    supplier = make_supplier()
    payload = create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="WOOD_FLOUR", weight_lbs=500,
        received_date="2026-09-01",
    )
    lot = get_success_data(api.create_feedstock_lot(payload, QE))
    get_success_data(api.reject_feedstock_lot(lot["id"], QE))
    resp = api.reject_feedstock_lot(lot["id"], QE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    supplier_after = get_success_data(api.get_supplier(supplier["id"], QE))
    # One rejected lot out of one total: 10000 - 10000 = 0; the second reject
    # must not recompute (it was rejected with ERR_INVALID_STATE).
    assert supplier_after["reliability_score_bp"] == 0


def test_discontinue_blocked_by_open_orders(api):
    """PRD §3.3: "Discontinuation is blocked while any shipment order in
    `REQUESTED` or `CONFIRMED` references the line (`ERR_LINE_HAS_OPEN_ORDERS`)"

    Design: Corner/state_machines/discontinue_blocked_by_open_orders
    """
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"], name="Vintage", color="Red")
    dealer = make_dealer(credit_limit_cents=1000000)
    make_order(dealer["id"], line["id"], 10, "2026-09-07")
    resp = api.discontinue_product_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_LINE_HAS_OPEN_ORDERS)
    line_after = get_success_data(api.get_product_line(line["id"], PM))
    assert line_after["status"] == "ACTIVE"


def test_sunset_blocked_by_remaining_finished_goods(api):
    """PRD §3.3: "Sunsetting requires both that no warranty claim in `FILED`,
    `SAMPLE_REQUESTED`, or `UNDER_REVIEW` references an install registration
    of the line (`ERR_LINE_HAS_OPEN_CLAIMS`) and that the line's
    finished-goods balance is zero (`ERR_LINE_STOCK_REMAINS`)."

    Design: Corner/state_machines/sunset_blocked_by_remaining_finished_goods
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Vintage", color="Red")
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    make_completed_run(plant["id"], line["id"], 100, "2026-03-01")
    get_success_data(api.discontinue_product_line(line["id"], PM))
    get_success_data(api.set_repair_support(line["id"], {"repair_support_only": True}, PM))
    resp = api.sunset_product_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_LINE_STOCK_REMAINS)
    line_after = get_success_data(api.get_product_line(line["id"], PM))
    assert line_after["status"] == "REPAIRED_SUPPORTED"


def test_certification_rejected_with_stale_module_version(api):
    """PRD §3.8: "Second, when any module was re-versioned after the
    contractor passed it, at least one pass must have been recorded against
    the module's current `version_no`; stale passes are rejected with
    `ERR_STALE_TRAINING` (HTTP 409), so re-versioned modules must be
    re-passed."

    Design: Corner/state_machines/certification_rejected_with_stale_module_version
    """
    contractor = make_contractor()
    module = make_training_module()
    enroll_and_pass(contractor["id"], module["id"])
    get_success_data(api.reversion_training_module(module["id"], {"duration_hours": 5.0}, PA))
    resp = api.certify_contractor(contractor["id"], PA)
    validate_error(resp, ApiErrorId.ERR_STALE_TRAINING)
    contractor_after = get_success_data(api.get_contractor(contractor["id"], PA))
    assert contractor_after["status"] == "IN_TRAINING"
    module_after = get_success_data(api.get_training_module(module["id"], PA))
    assert module_after["version_no"] == 2


def test_run_complete_overage_boundary(api):
    """PRD §3.5: "Completing a run — transitioning `RUNNING → COMPLETED` —
    requires the `actual_lf` produced, which must be at least 1 and at most
    110 percent of `planned_lf`; an overage beyond that ceiling is rejected
    with `ERR_OVERAGE_LIMIT` (HTTP 409)."

    Design: Corner/state_machines/run_complete_overage_boundary
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=4500)

    run1 = create_run(plant["id"], line["id"], 1000, "2026-03-01", run_kind="SELLABLE")
    get_success_data(api.start_production_run(plant["id"], run1["id"], OPS))

    run2 = create_run(plant["id"], line["id"], 1000, "2026-03-02", run_kind="SELLABLE")
    set_clock("2026-03-02T00:00:00Z")
    get_success_data(api.start_production_run(plant["id"], run2["id"], OPS))

    # 1100 == exactly 110% of 1000: allowed.
    completed1 = get_success_data(
        api.complete_production_run(plant["id"], run1["id"], {"actual_lf": 1100}, OPS))
    assert completed1["status"] == "COMPLETED"
    assert completed1["actual_lf"] == 1100

    # 1101 > 110%: rejected.
    resp = api.complete_production_run(plant["id"], run2["id"], {"actual_lf": 1101}, OPS)
    validate_error(resp, ApiErrorId.ERR_OVERAGE_LIMIT)
    run2_after = get_success_data(api.get_production_run(plant["id"], run2["id"], OPS))
    assert run2_after["status"] == "RUNNING"


def test_claim_approval_blocked_by_contradicting_verdict(api):
    """PRD §3.10: "Approval requires the lab verdict to be `CONFIRMS_DEFECT` —
    any other verdict blocks approval with `ERR_VERDICT_BLOCKS_APPROVAL`
    (HTTP 409)"
    PRD §3.10: "Denial records the `denial_reason` and closes the claim."

    Design: Corner/state_machines/claim_approval_blocked_by_contradicting_verdict
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Enhance", color="Brown",
                             profile="SQUARE", emboss="SMOOTH", board_length_ft=12)
    dealer = make_dealer(credit_limit_cents=1000000)
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    _run, lot = make_completed_run(plant["id"], line["id"], 200, "2026-03-01")
    contractor, _module = make_certified_contractor()
    reg = make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                      "2026-03-02", lot["id"])
    get_success_data(api.activate_warranty(reg["id"], make_contractor_headers(contractor["id"])))
    claim, _sample = make_under_review_claim(reg["id"], category="STRUCTURAL",
                                             lab_verdict="CONTRADICTS_CLAIM")

    resp = api.adjudicate_claim(claim["id"], {"decision": "APPROVE", "adjudication": "CREDIT"}, CA)
    validate_error(resp, ApiErrorId.ERR_VERDICT_BLOCKS_APPROVAL)

    denied = get_success_data(api.adjudicate_claim(
        claim["id"], {"decision": "DENY", "denial_reason": "lab contradicts"}, CA))
    assert denied["status"] == "DENIED"
