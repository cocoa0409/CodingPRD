"""Error-catalog corners: resin shortfall, formulation-in-use, empty lead
selector pool, fade cooldown, out-of-warranty claims."""
from test_helpers import (
    ApiErrorId,
    create_run,
    get_success_data,
    make_active_formulation,
    make_certified_contractor,
    make_completed_run,
    make_contractor,
    make_dealer,
    make_enhanced_registration,
    make_lead,
    make_plant,
    make_product_line,
    make_supplier,
    set_clock,
    stock_resin,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
PE = TEST_USERS["process_engineer_headers"]
PM = TEST_USERS["product_manager_headers"]
PA = TEST_USERS["program_admin_headers"]
CA = TEST_USERS["claims_adjuster_headers"]


def test_error_resin_shortfall_triggerable(api):
    """PRD §3.5: "If any material's on-hand balance is below its draw, the
    start is rejected with `ERR_RESIN_SHORTFALL`."

    Design: Corner/errors/error_resin_shortfall_triggerable
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"])
    supplier = make_supplier()
    # 500 lbs each against a 1000-lf run (2000 lbs total draw, 1000 per side).
    stock_resin(plant, supplier["id"], weight_lbs=500)
    run = create_run(plant["id"], line["id"], 1000, "2026-03-01", run_kind="SELLABLE")
    plant_before = get_success_data(api.get_plant(plant["id"], OPS))
    resp = api.start_production_run(plant["id"], run["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_RESIN_SHORTFALL)
    run_after = get_success_data(api.get_production_run(plant["id"], run["id"], OPS))
    assert run_after["status"] == "PLANNED"
    plant_after = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_after["resin_store"] == plant_before["resin_store"]


def test_error_formulation_in_use_blocks_retire(api):
    """PRD §3.3: "Retirement moves the formulation `ACTIVE → RETIRED` and is
    blocked while any product line in `ACTIVE` status still references it
    (`ERR_FORMULATION_IN_USE`, HTTP 409)."

    Design: Corner/errors/error_formulation_in_use_blocks_retire
    """
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    resp = api.retire_formulation(form["id"], PE)
    validate_error(resp, ApiErrorId.ERR_FORMULATION_IN_USE)
    get_success_data(api.discontinue_product_line(line["id"], PM))
    retired = get_success_data(api.retire_formulation(form["id"], PE))
    assert retired["status"] == "RETIRED"


def test_error_no_eligible_contractor(api):
    """PRD §3.9: "an empty pool is rejected with `ERR_NO_ELIGIBLE_CONTRACTOR`
    (HTTP 409)."

    Design: Corner/errors/error_no_eligible_contractor
    """
    dealer = make_dealer(credit_limit_cents=1000000)
    make_contractor()  # still APPLIED, never certified
    lead = make_lead(dealer["id"])
    resp = api.assign_lead_referral(lead["id"], PA)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CONTRACTOR)
    lead_after = get_success_data(api.get_lead_referral(lead["id"], PA))
    assert lead_after["status"] == "OPEN"


def test_error_fade_cooldown_on_legacy_revision(api):
    """PRD §3.10: "for `FADING` claims, when the installed boards were produced
    on a legacy formulation revision — the lot's pinned `formulation_revision`
    is older than the formulation's current `active_revision` — the claim must
    be at least 180 days old, measured from install, before a sample may be
    requested, otherwise `ERR_FADE_COOLDOWN` (HTTP 409)"

    Design: Corner/errors/error_fade_cooldown_on_legacy_revision
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
    # Supersede revision 1 with revision 2 after the lot was produced.
    get_success_data(api.revise_formulation(form["id"], {"lines": [
        {"material": "VIRGIN_PE", "weight_fraction_bp": 4000},
        {"material": "WOOD_FLOUR", "weight_fraction_bp": 6000},
    ]}, PE))
    contractor, _module = make_certified_contractor()
    reg = make_enhanced_registration(contractor["id"], dealer["id"], line["id"],
                                     "2026-03-02", lot["id"])

    # 100 days after install: legacy-revision fade claim is inside the
    # 180-day weathering cooldown.
    set_clock("2026-06-10T00:00:00Z")
    claim = get_success_data(api.create_warranty_claim(
        {"install_registration_id": reg["id"], "category": "FADING"}, CA))
    resp = api.request_claim_sample(claim["id"], CA)
    validate_error(resp, ApiErrorId.ERR_FADE_COOLDOWN)
    claim_after = get_success_data(api.get_warranty_claim(claim["id"], CA))
    assert claim_after["status"] == "FILED"


def test_error_claim_out_of_warranty(api):
    """PRD §3.10: "the number of whole days between the registration's
    `install_date` and the claim's `filed_at` must not exceed the
    registration's `warranty_years` multiplied by 365, otherwise
    `ERR_CLAIM_OUT_OF_WARRANTY` (HTTP 409)."
    PRD §3.9: "Without activation a registration carries a five-year baseline
    warranty."

    Design: Corner/errors/error_claim_out_of_warranty
    """
    from test_helpers import make_installed_registration
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Enhance", color="Brown",
                             profile="SQUARE", emboss="SMOOTH", board_length_ft=12)
    dealer = make_dealer(credit_limit_cents=1000000)
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    _run, lot = make_completed_run(plant["id"], line["id"], 200, "2026-03-01")
    contractor = make_contractor()
    # Non-enhanced registration: five-year baseline warranty.
    reg = make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                      "2020-01-01", lot["id"])
    assert reg["warranty_years"] == 5
    set_clock("2026-08-01T00:00:00Z")
    claim = get_success_data(api.create_warranty_claim(
        {"install_registration_id": reg["id"], "category": "STRUCTURAL"}, CA))
    resp = api.request_claim_sample(claim["id"], CA)
    validate_error(resp, ApiErrorId.ERR_CLAIM_OUT_OF_WARRANTY)
