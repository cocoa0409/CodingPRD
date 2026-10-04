"""Endpoint corners: board-lot reverse reachability, support-stock exclusion
from fg_store, chip fulfilment support-stock constant, run-start date gate."""
from test_helpers import (
    ApiErrorId,
    create_run,
    get_success_data,
    make_active_formulation,
    make_color_chip_request,
    make_completed_run,
    make_dealer,
    make_plant,
    make_product_line,
    make_supplier,
    set_clock,
    stock_resin,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]


def test_board_lots_reverse_reachable_from_run(api):
    """PRD §3.5: "Completion creates exactly one board lot with `lf` equal to
    `actual_lf`, `produced_at` stamped with the completion datetime, and
    `support_tagged` true whenever the run's `run_kind` is anything other than
    `SELLABLE`; the lot's id is recorded on the run as `board_lot_id`, and the
    lot carries the run's `product_line_id`, pinned `formulation_revision`,
    and `plant_id`."
    PRD §3.5: "For `SELLABLE` runs the actual footage is added to the plant's
    `fg_store` under the product line"

    Design: Corner/endpoints/board_lots_reverse_reachable_from_run
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"])
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    run, lot = make_completed_run(plant["id"], line["id"], 150, "2026-03-01")

    lots = get_success_data(api.list_run_board_lots(run["id"], OPS))
    assert len(lots) == 1
    assert lots[0]["id"] == lot["id"]
    assert lots[0]["lf"] == 150
    assert lots[0]["disposition"] == "AVAILABLE"
    plant_after = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_after["fg_store"][line["id"]] == 150


def test_support_stock_run_excluded_from_fg_store(api):
    """PRD §3.5: "Lots from `SUPPORT_STOCK` and `NULL_SLOT` runs never enter
    `fg_store`; support stock is tracked only on the lot itself."

    Design: Corner/endpoints/support_stock_run_excluded_from_fg_store
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Vintage", color="Red")
    get_success_data(api.discontinue_product_line(line["id"], PM))
    get_success_data(api.set_repair_support(line["id"], {"repair_support_only": True}, PM))
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)

    run, lot = make_completed_run(plant["id"], line["id"], 100, "2026-03-01",
                                  run_kind="SUPPORT_STOCK")
    assert lot["support_tagged"] is True
    plant_after = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_after["fg_store"].get(line["id"], 0) == 0


def test_chip_fulfillment_uses_chip_lf_constant(api):
    """PRD §3.11: "Fulfilment, performed by an `OpsManager`, draws on support
    stock: a completed `SUPPORT_STOCK` production run for the request's
    product line must exist with `actual_lf` of at least two linear feet per
    chip requested — each chip consumes 2 linear feet — otherwise the
    fulfilment is rejected with `ERR_CHIP_STOCK_SHORT` (HTTP 409)."

    Design: Corner/endpoints/chip_fulfillment_uses_chip_lf_constant
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Vintage", color="Red")
    get_success_data(api.discontinue_product_line(line["id"], PM))
    get_success_data(api.set_repair_support(line["id"], {"repair_support_only": True}, PM))
    dealer = make_dealer(credit_limit_cents=1000000)
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    make_completed_run(plant["id"], line["id"], 99, "2026-03-01", run_kind="SUPPORT_STOCK")

    chip = make_color_chip_request(dealer["id"], line["id"], 50)
    resp = api.fulfill_color_chip_request(chip["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_CHIP_STOCK_SHORT)
    chip_after = get_success_data(api.get_color_chip_request(chip["id"], DSR))
    assert chip_after["status"] == "REQUESTED"


def test_run_start_on_wrong_date_rejected(api):
    """PRD §3.5: "The run's `production_date` must equal the logical clock
    date (`ERR_RUN_NOT_TODAY`)."

    Design: Corner/endpoints/run_start_on_wrong_date_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    run = create_run(plant["id"], line["id"], 100, "2026-03-02", run_kind="NULL_SLOT")
    resp = api.start_production_run(plant["id"], run["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_TODAY)
    run_after = get_success_data(api.get_production_run(plant["id"], run["id"], OPS))
    assert run_after["status"] == "PLANNED"
