"""Calculation corners: recipe-draw remainder to wood flour, contractor tier
GOLD boundary, stale-quarantine sweep."""
from test_helpers import (
    enroll_and_pass,
    get_success_data,
    make_active_formulation,
    make_certified_contractor,
    make_completed_run,
    make_contractor,
    make_contractor_headers,
    make_dealer,
    create_feedstock_lot_payload,
    make_installed_registration,
    make_plant,
    make_product_line,
    make_released_lot,
    make_supplier,
    make_training_module,
    create_run,
    set_clock,
    stock_resin,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]
PA = TEST_USERS["program_admin_headers"]


def test_recipe_draw_remainder_to_wood_flour(api):
    """PRD §3.5: "Each formulation line other than `WOOD_FLOUR` draws its
    `weight_fraction_bp` share of that total, truncated down to a whole pound
    per material; `WOOD_FLOUR` absorbs the remainder, so the wood draw equals
    the total mass minus the sum of the other draws."
    PRD §3.5: "the run's total mass is the ceiling of `planned_lf` multiplied
    by 2.0."

    Design: Corner/calculations/recipe_draw_remainder_to_wood_flour
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation(lines=[
        {"material": "VIRGIN_PE", "weight_fraction_bp": 3333},
        {"material": "WOOD_FLOUR", "weight_fraction_bp": 6667},
    ])
    line = make_product_line(form["id"])
    supplier = make_supplier()
    make_released_lot(supplier["id"], "VIRGIN_PE", 1000)
    make_released_lot(supplier["id"], "WOOD_FLOUR", 1000)

    run = create_run(plant["id"], line["id"], 333, "2026-03-01", run_kind="SELLABLE")
    get_success_data(api.start_production_run(plant["id"], run["id"], OPS))

    plant_after = get_success_data(api.get_plant(plant["id"], OPS))
    # total = 666; PE draw floor(666*3333/10000) = 221; WF draw = 666-221 = 445.
    assert plant_after["resin_store"]["VIRGIN_PE"] == 779
    assert plant_after["resin_store"]["WOOD_FLOUR"] == 555


def test_contractor_tier_score_boundary_gold(api):
    """PRD §3.8: "the score is the contractor's `completed_project_count`
    multiplied by 100 plus the `enhanced_warranty_count` multiplied by 250. A
    score of at least 3000 earns `PLATINUM`, a score of at least 1000 earns
    `GOLD`, and anything below earns `SILVER`; the boundaries are inclusive,
    so a score of exactly 3000 is `PLATINUM` and exactly 1000 is `GOLD`."

    Design: Corner/calculations/contractor_tier_score_boundary_gold
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
    # Ten completed projects inside the trailing 12 months: score 1000 -> GOLD
    # on the reinstatement recompute.
    day = 2
    for _ in range(10):
        make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                    f"2026-03-{day:02d}", lot["id"])
        day += 1
    get_success_data(api.suspend_contractor(contractor["id"], PA))
    reinstated = get_success_data(api.reinstate_contractor(contractor["id"], PA))
    assert reinstated["status"] == "CERTIFIED"
    assert reinstated["tier"] == "GOLD", (
        f"score 10*100 == 1000 must land GOLD (>= boundary); got {reinstated['tier']}"
    )


def test_stale_quarantine_sweep_at_review(api):
    """PRD §3.12: "Feedstock lots still `QUARANTINE` whose `received_date` is
    more than 14 days before the review date auto-transition to `REJECTED`"

    Design: Corner/calculations/stale_quarantine_sweep_at_review
    """
    set_clock("2026-02-13T00:00:00Z")
    plant = make_plant()
    supplier = make_supplier()
    lot_a = get_success_data(api.create_feedstock_lot(create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="WOOD_FLOUR", weight_lbs=100,
        received_date="2026-02-13", certificate_ref="A",
    ), QE))
    lot_b = get_success_data(api.create_feedstock_lot(create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="WOOD_FLOUR", weight_lbs=100,
        received_date="2026-02-14", certificate_ref="B",
    ), QE))
    set_clock("2026-02-28T00:00:00Z")
    reviewed = get_success_data(api.run_capacity_review(plant["id"], OPS))
    assert reviewed["season_posture"] == "PRE_SEASON"

    lot_a_after = get_success_data(api.get_feedstock_lot(lot_a["id"], QE))
    lot_b_after = get_success_data(api.get_feedstock_lot(lot_b["id"], QE))
    assert lot_a_after["status"] == "REJECTED"  # 15 days before review: more than 14
    assert lot_b_after["status"] == "QUARANTINE"  # exactly 14: not "more than 14"
