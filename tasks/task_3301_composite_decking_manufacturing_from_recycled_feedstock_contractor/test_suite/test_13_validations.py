"""Validation corners: lot lab limits, formulation balance/collision,
duplicate commitment, season close timing, registration window."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_active_formulation,
    make_certified_contractor,
    make_completed_run,
    make_contractor_headers,
    make_dealer,
    create_feedstock_lot_payload,
    create_formulation_payload,
    make_installed_registration,
    make_plant,
    make_product_line,
    make_stocking_commitment,
    make_supplier,
    set_clock,
    stock_resin,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]
PM = TEST_USERS["product_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]


def test_wood_flour_moisture_limit_breach(api):
    """PRD §3.2: "`WOOD_FLOUR`: `moisture_pct` must be at most 8.0, and
    `contamination_ppm` must be at most 500."
    PRD §3.2: "a breach of any applicable limit is rejected with
    `ERR_LOT_LIMIT_EXCEEDED` (HTTP 422)"

    Design: Corner/validations/wood_flour_moisture_limit_breach
    """
    make_plant()
    supplier = make_supplier()
    lot_a = get_success_data(api.create_feedstock_lot(create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="WOOD_FLOUR", weight_lbs=100,
        received_date="2026-09-01", moisture_pct=8.1, certificate_ref="A",
    ), QE))
    lot_b = get_success_data(api.create_feedstock_lot(create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="WOOD_FLOUR", weight_lbs=100,
        received_date="2026-09-01", moisture_pct=8.0, certificate_ref="B",
    ), QE))

    resp_a = api.release_feedstock_lot(lot_a["id"], {"release_disposition": "PRODUCTION"}, QE)
    validate_error(resp_a, ApiErrorId.ERR_LOT_LIMIT_EXCEEDED)
    assert get_success_data(api.get_feedstock_lot(lot_a["id"], QE))["status"] == "QUARANTINE"

    released_b = get_success_data(
        api.release_feedstock_lot(lot_b["id"], {"release_disposition": "PRODUCTION"}, QE))
    assert released_b["status"] == "RELEASED"


def test_polymer_lot_requires_melt_flow_index(api):
    """PRD §3.2: "Polymer lots — `PCR_FILM`, `REPRO_PE`, and `VIRGIN_PE` —
    must also carry a `melt_flow_index`; the field is required for polymer
    lots and its absence on a polymer lot is itself a lab-limit breach."

    Design: Corner/validations/polymer_lot_requires_melt_flow_index
    """
    make_plant()
    supplier = make_supplier()
    payload = create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="PCR_FILM", weight_lbs=100,
        received_date="2026-09-01", moisture_pct=1.0, contamination_ppm=100,
    )
    assert "melt_flow_index" not in payload
    lot = get_success_data(api.create_feedstock_lot(payload, QE))
    resp = api.release_feedstock_lot(lot["id"], {"release_disposition": "PRODUCTION"}, QE)
    validate_error(resp, ApiErrorId.ERR_LOT_LIMIT_EXCEEDED)


def test_formulation_unbalanced_rejected(api):
    """PRD §3.3: "Activation, performed by a `ProcessEngineer`, requires the
    weight fractions across all lines to sum to exactly 10000 basis points; an
    unbalanced formulation is rejected with `ERR_FORMULA_UNBALANCED`
    (HTTP 422)."

    Design: Corner/validations/formulation_unbalanced_rejected
    """
    form = get_success_data(api.create_formulation(create_formulation_payload(lines=[
        {"material": "VIRGIN_PE", "weight_fraction_bp": 4999},
        {"material": "WOOD_FLOUR", "weight_fraction_bp": 5000},
    ]), PE))
    resp = api.activate_formulation(form["id"], PE)
    validate_error(resp, ApiErrorId.ERR_FORMULA_UNBALANCED)
    form_after = get_success_data(api.get_formulation(form["id"], PE))
    assert form_after["status"] == "DRAFT"


def test_formulation_revision_collision_rejected(api):
    """PRD §3.3: "The new set must again sum to exactly 10000 basis points,
    and its content hash must differ from every prior revision hash of the
    same formulation — a duplicate content hash is rejected with
    `ERR_REVISION_COLLISION` (HTTP 422)."

    Design: Corner/validations/formulation_revision_collision_rejected
    """
    form = make_active_formulation()
    get_success_data(api.revise_formulation(form["id"], {"lines": [
        {"material": "VIRGIN_PE", "weight_fraction_bp": 4000},
        {"material": "WOOD_FLOUR", "weight_fraction_bp": 6000},
    ]}, PE))
    resp = api.revise_formulation(form["id"], {"lines": [
        {"material": "VIRGIN_PE", "weight_fraction_bp": 5000},
        {"material": "WOOD_FLOUR", "weight_fraction_bp": 5000},
    ]}, PE)
    validate_error(resp, ApiErrorId.ERR_REVISION_COLLISION)
    form_after = get_success_data(api.get_formulation(form["id"], PE))
    assert form_after["active_revision"] == 2


def test_duplicate_open_commitment_rejected(api):
    """PRD §3.7: "At most one open stocking commitment may exist per
    dealer-and-territory pair; a second open commitment for the same pair is
    rejected with `ERR_DUPLICATE_COMMITMENT` (HTTP 409)."

    Design: Corner/validations/duplicate_open_commitment_rejected
    """
    dealer = make_dealer(credit_limit_cents=1000000)
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line1 = make_product_line(form["id"], name="L1")
    line2 = make_product_line(form["id"], name="L2", color="Brown",
                              profile="SQUARE", emboss="SMOOTH", board_length_ft=12)
    make_stocking_commitment(dealer["id"], "VA-N", line1["id"], 100, 2026)
    resp = api.create_stocking_commitment({
        "dealer_id": dealer["id"], "territory_code": "VA-N",
        "product_line_id": line2["id"], "committed_lf": 50, "season_year": 2026,
    }, CM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMMITMENT)


def test_close_season_before_year_end_rejected(api):
    """PRD §3.7: "Closing is only possible once the logical clock date is
    after December 31 of the `season_year` — the earliest close date is
    January 1 of the following year."

    Design: Corner/validations/close_season_before_year_end_rejected
    """
    set_clock("2026-12-31T00:00:00Z")
    dealer = make_dealer(credit_limit_cents=1000000)
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    sc = make_stocking_commitment(dealer["id"], "VA-N", line["id"], 100, 2026)
    resp = api.close_stocking_commitment_season(sc["id"], {}, CM)
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
    sc_after = get_success_data(api.get_stocking_commitment(sc["id"], CM))
    assert sc_after["status"] == "OPEN"


def test_registration_window_60_days(api):
    """PRD §3.9: "the registration's `registered_at` must fall within 60 days
    of the `install_date` (`ERR_REGISTRATION_WINDOW`, HTTP 409)"

    Design: Corner/validations/registration_window_60_days
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

    # Registered exactly 60 days after the 2026-01-01 install: inside the
    # window (the boundary is inclusive).
    r1 = make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                     "2026-01-01", lot["id"],
                                     registered_date="2026-03-02")
    activated = get_success_data(
        api.activate_warranty(r1["id"], make_contractor_headers(contractor["id"])))
    assert activated["enhanced_warranty"] is True

    # Registered 61 days after install: outside the window.
    r2 = make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                     "2026-01-01", lot["id"],
                                     registered_date="2026-03-03")
    resp = api.activate_warranty(r2["id"], make_contractor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW)
