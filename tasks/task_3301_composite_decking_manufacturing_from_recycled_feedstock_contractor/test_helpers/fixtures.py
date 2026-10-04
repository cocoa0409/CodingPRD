"""Composite setup helpers for the composite-decking API.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before each test, so the
database is empty). Setup calls use get_success_data() so failures surface
as clear "Setup failed" messages.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allocation_commitment_payload,
    create_collection_program_payload,
    create_color_chip_request_payload,
    create_contractor_payload,
    create_dealer_payload,
    create_feedstock_lot_payload,
    create_formulation_payload,
    create_install_registration_payload,
    create_lead_referral_payload,
    create_plant_payload,
    create_price_book_payload,
    create_product_line_payload,
    create_shipment_order_payload,
    create_stocking_commitment_payload,
    create_supplier_payload,
    create_training_module_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_contractor_headers, make_dealer_headers

OPS = TEST_USERS["ops_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]
PM = TEST_USERS["product_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]
PA = TEST_USERS["program_admin_headers"]
CA = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


# ---------------------------------------------------------------------------
# Tier 1/2: base entity builders
# ---------------------------------------------------------------------------

def make_plant(**overrides):
    """Create a plant; returns the plant dict."""
    return get_success_data(api_client.create_plant(create_plant_payload(**overrides), OPS))


def make_supplier(**overrides):
    return get_success_data(api_client.create_supplier(create_supplier_payload(**overrides), QE))


def make_collection_program(supplier_id, **overrides):
    payload = create_collection_program_payload(supplier_id=supplier_id, **overrides)
    return get_success_data(api_client.create_collection_program(payload, CM))


def make_active_formulation(lines=None, **overrides):
    """Create a formulation and activate it."""
    kwargs = dict(overrides)
    if lines is not None:
        kwargs["lines"] = lines
    form = get_success_data(api_client.create_formulation(create_formulation_payload(**kwargs), PE))
    return get_success_data(api_client.activate_formulation(form["id"], PE))


def make_product_line(formulation_id, **overrides):
    payload = create_product_line_payload(formulation_id=formulation_id, **overrides)
    return get_success_data(api_client.create_product_line(payload, PM))


def make_dealer(**overrides):
    return get_success_data(api_client.create_dealer(create_dealer_payload(**overrides), CM))


def make_price_book(base_prices=None, **overrides):
    payload = create_price_book_payload(**overrides)
    if base_prices is not None:
        payload["base_prices"] = base_prices
    return get_success_data(api_client.create_price_book(payload, CM))


# ---------------------------------------------------------------------------
# Tier 2: feedstock release
# ---------------------------------------------------------------------------

def make_released_lot(supplier_id, material, weight_lbs, disposition="PRODUCTION", **overrides):
    """Register a feedstock lot and release it. Returns the released lot."""
    payload = create_feedstock_lot_payload(
        supplier_id=supplier_id, material=material, weight_lbs=weight_lbs, **overrides
    )
    if material in ("PCR_FILM", "REPRO_PE", "VIRGIN_PE") and "melt_flow_index" not in payload:
        payload["melt_flow_index"] = 0.7
    lot = get_success_data(api_client.create_feedstock_lot(payload, QE))
    return get_success_data(
        api_client.release_feedstock_lot(lot["id"], {"release_disposition": disposition}, QE)
    )


def stock_resin(plant, supplier_id, materials=("VIRGIN_PE", "WOOD_FLOUR"), weight_lbs=3000):
    """Release `weight_lbs` of each listed material into the plant's resin store."""
    for material in materials:
        make_released_lot(supplier_id, material, weight_lbs)


# ---------------------------------------------------------------------------
# Tier 3: production runs
# ---------------------------------------------------------------------------

def create_run(plant_id, product_line_id, planned_lf, production_date,
               run_kind="SELLABLE", reservation_id=None, lines_payload=None):
    """Create a production run, threading the current plant version for OCC."""
    plant = get_success_data(api_client.get_plant(plant_id, OPS))
    payload = {
        "product_line_id": product_line_id,
        "planned_lf": planned_lf,
        "production_date": production_date,
        "run_kind": run_kind,
        "expected_plant_version": plant["version"],
    }
    if reservation_id is not None:
        payload["reservation_id"] = reservation_id
    return get_success_data(api_client.create_production_run(plant_id, payload, OPS))


def make_completed_run(plant_id, product_line_id, planned_lf, production_date,
                       run_kind="SELLABLE", actual_lf=None, clock_date=None,
                       reservation_id=None):
    """Create, start and complete a run. Returns (run, board_lot)."""
    if clock_date is not None:
        set_clock(f"{clock_date}T00:00:00Z")
    run = create_run(plant_id, product_line_id, planned_lf, production_date,
                     run_kind=run_kind, reservation_id=reservation_id)
    if clock_date is None or clock_date != production_date:
        set_clock(f"{production_date}T00:00:00Z")
    get_success_data(api_client.start_production_run(plant_id, run["id"], OPS))
    run = get_success_data(api_client.complete_production_run(
        plant_id, run["id"], {"actual_lf": actual_lf if actual_lf is not None else planned_lf}, OPS
    ))
    lots = get_success_data(api_client.list_run_board_lots(run["id"], OPS))
    assert len(lots) == 1, f"Setup failed: expected one board lot, got {len(lots)}"
    return run, lots[0]


# ---------------------------------------------------------------------------
# Tier 2/3: orders
# ---------------------------------------------------------------------------

def make_order(dealer_id, product_line_id, lf, ship_week_start):
    """Place a ship-later order as the dealer. Returns the order dict."""
    payload = create_shipment_order_payload(
        dealer_id=dealer_id, product_line_id=product_line_id,
        lf=lf, ship_week_start=ship_week_start,
    )
    return get_success_data(
        api_client.create_shipment_order(payload, make_dealer_headers(dealer_id))
    )


def confirm_order(order_id):
    return get_success_data(api_client.confirm_shipment_order(order_id, DSR))


def ship_order(order_id):
    return get_success_data(api_client.ship_shipment_order(order_id, DSR))


def deliver_order(order_id, dealer_id):
    return get_success_data(
        api_client.deliver_shipment_order(order_id, make_dealer_headers(dealer_id))
    )


def make_shipped_order(dealer_id, product_line_id, lf, ship_week_start, ship_date=None):
    """Create -> confirm -> ship an order. If ship_date given, clock is set to it."""
    order = make_order(dealer_id, product_line_id, lf, ship_week_start)
    confirm_order(order["id"])
    if ship_date is not None:
        set_clock(f"{ship_date}T00:00:00Z")
    return ship_order(order["id"])


def make_delivered_order(dealer_id, product_line_id, lf, ship_week_start, ship_date=None):
    order = make_shipped_order(dealer_id, product_line_id, lf, ship_week_start, ship_date)
    return deliver_order(order["id"], dealer_id)


# ---------------------------------------------------------------------------
# Tier 2: stocking commitments / allocations
# ---------------------------------------------------------------------------

def make_stocking_commitment(dealer_id, territory_code, product_line_id,
                             committed_lf, season_year):
    payload = create_stocking_commitment_payload(
        dealer_id=dealer_id, territory_code=territory_code,
        product_line_id=product_line_id, committed_lf=committed_lf,
        season_year=season_year,
    )
    return get_success_data(api_client.create_stocking_commitment(payload, CM))


def make_allocation_commitment(plant_id, dealer_id, product_line_id, reserved_lf, price_book_id):
    plant = get_success_data(api_client.get_plant(plant_id, OPS))
    payload = create_allocation_commitment_payload(
        dealer_id=dealer_id, product_line_id=product_line_id,
        reserved_lf=reserved_lf, price_book_id=price_book_id,
        expected_plant_version=plant["version"],
    )
    return get_success_data(api_client.create_allocation_commitment(plant_id, payload, DSR))


# ---------------------------------------------------------------------------
# Tier 2/3: contractor program
# ---------------------------------------------------------------------------

def make_contractor(name="Pro A", email="a@build.example"):
    return get_success_data(
        api_client.create_contractor(create_contractor_payload(name=name, email=email), PA)
    )


def make_training_module(title="Install Basics", version_no=1, duration_hours=4.0,
                         required_for_tier="SILVER"):
    payload = create_training_module_payload(
        title=title, version_no=version_no, duration_hours=duration_hours,
        required_for_tier=required_for_tier,
    )
    return get_success_data(api_client.create_training_module(payload, PA))


def enroll_and_pass(contractor_id, module_id):
    """Enrol (as the contractor) and record a pass. Returns the record."""
    record = get_success_data(api_client.create_training_record(
        {"contractor_id": contractor_id, "module_id": module_id},
        make_contractor_headers(contractor_id),
    ))
    return get_success_data(api_client.pass_training_record(record["id"], PA))


def make_certified_contractor(name="Pro A", email="a@build.example"):
    """Contractor + one SILVER module passed + certified. Returns (contractor, module)."""
    contractor = make_contractor(name=name, email=email)
    module = make_training_module()
    enroll_and_pass(contractor["id"], module["id"])
    contractor = get_success_data(api_client.certify_contractor(contractor["id"], PA))
    return contractor, module


# ---------------------------------------------------------------------------
# Tier 3: registrations / claims
# ---------------------------------------------------------------------------

def make_registration(contractor_id, dealer_id, product_line_id, install_date,
                      board_lot_id, registered_date=None):
    # `registered_date` back-dates the registration so historical installs
    # (used by warranty-window and claim-proration scenarios) satisfy the
    # 60-day registration window regardless of the current logical clock.
    # When omitted the server stamps the logical clock at creation.
    payload = create_install_registration_payload(
        contractor_id=contractor_id, dealer_id=dealer_id,
        product_line_id=product_line_id, install_date=install_date,
        board_lot_id=board_lot_id,
    )
    if registered_date is not None:
        payload["registered_date"] = registered_date
    return get_success_data(
        api_client.create_install_registration(payload, make_contractor_headers(contractor_id))
    )


def make_installed_registration(contractor_id, dealer_id, product_line_id,
                                install_date, board_lot_id, registered_date=None):
    reg = make_registration(contractor_id, dealer_id, product_line_id,
                            install_date, board_lot_id, registered_date)
    return get_success_data(
        api_client.mark_registration_installed(reg["id"], make_contractor_headers(contractor_id))
    )


def make_enhanced_registration(contractor_id, dealer_id, product_line_id,
                               install_date, board_lot_id, registered_date=None):
    reg = make_installed_registration(contractor_id, dealer_id, product_line_id,
                                      install_date, board_lot_id, registered_date)
    return get_success_data(
        api_client.activate_warranty(reg["id"], make_contractor_headers(contractor_id))
    )


def make_claim(registration_id, category="STRUCTURAL", filed_date=None):
    payload = create_warranty_claim_payload(
        install_registration_id=registration_id, category=category,
    )
    if filed_date is not None:
        payload["filed_date"] = filed_date
    return get_success_data(api_client.create_warranty_claim(payload, CA))


def make_under_review_claim(registration_id, category="STRUCTURAL",
                            lab_verdict="CONFIRMS_DEFECT", filed_date=None):
    """File a claim, request a sample, receive it, review it. Returns (claim, sample)."""
    claim = make_claim(registration_id, category, filed_date=filed_date)
    get_success_data(api_client.request_claim_sample(claim["id"], CA))
    samples = get_success_data(api_client.list_claim_samples(claim["id"], CA))
    assert len(samples) == 1, f"Setup failed: expected one sample, got {len(samples)}"
    sample = samples[0]
    get_success_data(api_client.receive_claim_sample(sample["id"], CA))
    sample = get_success_data(
        api_client.review_claim_sample(sample["id"], {"lab_verdict": lab_verdict}, CA)
    )
    claim = get_success_data(api_client.get_warranty_claim(claim["id"], CA))
    return claim, sample


# ---------------------------------------------------------------------------
# Tier 2: merchandising
# ---------------------------------------------------------------------------

def make_color_chip_request(dealer_id, product_line_id, quantity):
    payload = create_color_chip_request_payload(
        dealer_id=dealer_id, product_line_id=product_line_id, quantity=quantity,
    )
    return get_success_data(
        api_client.create_color_chip_request(payload, make_dealer_headers(dealer_id))
    )


def make_lead(dealer_id, **overrides):
    payload = create_lead_referral_payload(submitted_by_dealer_id=dealer_id, **overrides)
    return get_success_data(
        api_client.create_lead_referral(payload, make_dealer_headers(dealer_id))
    )
