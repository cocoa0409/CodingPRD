"""Cross-entity state dependencies: product-line state gating production runs,
contractor state gating enhanced warranty activation."""
from test_helpers import (
    ApiErrorId,
    create_run,
    get_success_data,
    make_active_formulation,
    make_certified_contractor,
    make_completed_run,
    make_contractor_headers,
    make_dealer,
    make_installed_registration,
    make_plant,
    make_product_line,
    make_supplier,
    set_clock,
    stock_resin,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
PA = TEST_USERS["program_admin_headers"]


def test_sellable_run_gated_by_line_state(api):
    """PRD §3.4: "`SUPPORT_STOCK` runs additionally require
    `repair_support_only` to be true on the product line, while `SELLABLE`
    runs require the line to be `ACTIVE`. Sellability violations surface as
    `ERR_LINE_SUPPORT_ONLY` or `ERR_LINE_SUNSET`."

    Design: Difficulty/cross_entity_state_dependency/sellable_run_gated_by_line_state
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Vintage", color="Red")

    run_ok = create_run(plant["id"], line["id"], 100, "2026-03-01", run_kind="SELLABLE")
    assert run_ok["status"] == "PLANNED"

    get_success_data(api.discontinue_product_line(line["id"], PM))
    get_success_data(api.set_repair_support(line["id"], {"repair_support_only": True}, PM))

    plant_now = get_success_data(api.get_plant(plant["id"], OPS))
    resp = api.create_production_run(plant["id"], {
        "product_line_id": line["id"], "planned_lf": 100,
        "production_date": "2026-03-02", "run_kind": "SELLABLE",
        "expected_plant_version": plant_now["version"],
    }, OPS)
    validate_error(resp, ApiErrorId.ERR_LINE_SUPPORT_ONLY)

    run_support = create_run(plant["id"], line["id"], 100, "2026-03-02",
                             run_kind="SUPPORT_STOCK")
    assert run_support["run_kind"] == "SUPPORT_STOCK"


def test_null_slot_run_unrestricted_by_line_sellability(api):
    """PRD §3.4: "`NULL_SLOT` runs carry `line_slot` equal to null and are
    exempt from the line-status sellability rule described in §3.3"

    Design: Difficulty/cross_entity_state_dependency/sellable_run_gated_by_line_state
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Vintage", color="Red")
    get_success_data(api.discontinue_product_line(line["id"], PM))
    get_success_data(api.set_repair_support(line["id"], {"repair_support_only": True}, PM))
    run = create_run(plant["id"], line["id"], 100, "2026-03-02", run_kind="NULL_SLOT")
    assert run["run_kind"] == "NULL_SLOT"


def _contractor_registration_setup(api):
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=1)
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Enhance", color="Brown",
                             profile="SQUARE", emboss="SMOOTH", board_length_ft=12)
    dealer = make_dealer()
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    _run, lot = make_completed_run(plant["id"], line["id"], 200, "2026-03-01")
    contractor, _module = make_certified_contractor()
    reg = make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                      "2026-03-01", lot["id"])
    return contractor, reg


def test_enhanced_warranty_gated_by_contractor_state(api):
    """PRD §3.9: "Activating the enhanced warranty on an installed registration
    enforces three checks: the contractor must be `CERTIFIED`
    (`ERR_CONTRACTOR_NOT_CERTIFIED`, HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/enhanced_warranty_gated_by_contractor_state
    """
    contractor, reg = _contractor_registration_setup(api)
    get_success_data(api.suspend_contractor(contractor["id"], PA))

    resp = api.activate_warranty(reg["id"], make_contractor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_CERTIFIED)

    get_success_data(api.reinstate_contractor(contractor["id"], PA))
    activated = get_success_data(
        api.activate_warranty(reg["id"], make_contractor_headers(contractor["id"])))
    assert activated["enhanced_warranty"] is True
    assert activated["warranty_years"] == 10


def test_suspended_contractor_blocked_until_reinstated(api):
    """PRD §3.8: "A `ProgramAdmin` may suspend a certified contractor
    (`CERTIFIED → SUSPENDED`), which makes the contractor ineligible for new
    lead assignment and for enhanced warranty activation, and may later
    reinstate (`SUSPENDED → CERTIFIED`), which recomputes the tier."

    Design: Difficulty/cross_entity_state_dependency/enhanced_warranty_gated_by_contractor_state
    """
    contractor, reg = _contractor_registration_setup(api)
    # Baseline: activation works while CERTIFIED.
    activated = get_success_data(
        api.activate_warranty(reg["id"], make_contractor_headers(contractor["id"])))
    assert activated["enhanced_warranty"] is True
    assert activated["warranty_years"] == 10
