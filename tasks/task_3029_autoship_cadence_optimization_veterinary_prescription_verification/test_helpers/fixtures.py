"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints:
the runner restarts the server before each test, so the database is always empty
when a test begins.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data

from .api_client import api_client
from .api_errors import ApiErrorId
from .factories import (
    create_item_payload,
    create_pet_payload,
    create_plan_payload,
    create_prescription_payload,
    create_product_payload,
    create_site_payload,
    create_veterinarian_payload,
)
from .test_users import (
    TEST_USERS,
    make_clinic_contact_headers,
    make_customer_headers,
)


# ---------------------------------------------------------------------------
# Elementary building blocks
# ---------------------------------------------------------------------------

def set_clock(current_utc: str = "2026-09-01T00:00:00Z"):
    """Advance the logical clock. Returns the raw response."""
    return api_client.set_clock(current_utc, TEST_USERS["platform_admin_headers"])


def create_product(**overrides) -> dict:
    payload = create_product_payload(**overrides)
    resp = api_client.create_product(payload, TEST_USERS["platform_admin_headers"])
    data = get_success_data(resp)
    assert data["unit_price_cents"] == payload["unit_price_cents"], "Setup failed: product price"
    return data


def create_pet(**overrides) -> dict:
    payload = create_pet_payload(**overrides)
    resp = api_client.create_pet(payload, TEST_USERS["customer_headers"])
    return get_success_data(resp)


def create_veterinarian(**overrides) -> dict:
    payload = create_veterinarian_payload(**overrides)
    resp = api_client.create_veterinarian(payload, TEST_USERS["pharmacy_technician_headers"])
    return get_success_data(resp)


def create_site(**overrides) -> dict:
    payload = create_site_payload(**overrides)
    resp = api_client.create_site(payload, TEST_USERS["compliance_officer_headers"])
    return get_success_data(resp)


def create_plan(pet: dict, **overrides) -> dict:
    payload = create_plan_payload(pet["id"], **overrides)
    resp = api_client.create_plan(payload, make_customer_headers(pet["id"]))
    return get_success_data(resp)


def add_item(plan: dict, pet: dict, product: dict, cadence_days: int = 28,
             default_quantity: int = 1, expected_status: int = 201) -> dict:
    payload = create_item_payload(product["id"], cadence_days=cadence_days,
                                 default_quantity=default_quantity)
    resp = api_client.add_item(plan["id"], payload, make_customer_headers(pet["id"]))
    return get_success_data(resp, expected_status)


def read_plan(plan: dict, pet: dict) -> dict:
    resp = api_client.get_plan(plan["id"], make_customer_headers(pet["id"]))
    return get_success_data(resp)


def plan_version(plan: dict, pet: dict) -> int:
    return read_plan(plan, pet)["version"]


def read_item(plan: dict, pet: dict, item: dict) -> dict:
    resp = api_client.get_item(plan["id"], item["id"], make_customer_headers(pet["id"]))
    return get_success_data(resp)


def compose(plan: dict, pet: dict, promotion_code: Optional[str] = None,
            override_code: Optional[str] = None, expected_plan_version: Optional[int] = None):
    """Compose against the plan, reading the current version unless one is supplied.

    Returns the raw response so tests can assert on either the success payload or
    the error envelope.
    """
    version = expected_plan_version
    if version is None:
        version = plan_version(plan, pet)
    payload = {"expected_plan_version": version}
    if promotion_code is not None:
        payload["promotion_code"] = promotion_code
    if override_code is not None:
        payload["override_code"] = override_code
    return api_client.compose_order(plan["id"], payload, make_customer_headers(pet["id"]))


def compose_ok(plan: dict, pet: dict, **kwargs) -> dict:
    return get_success_data(compose(plan, pet, **kwargs), 201)


def create_shipment(order: dict) -> dict:
    resp = api_client.create_shipment({"order_id": order["id"]},
                                     TEST_USERS["pharmacy_technician_headers"])
    return get_success_data(resp, 201)


def ship_order(order: dict):
    return api_client.ship_order(order["id"], TEST_USERS["pharmacy_technician_headers"])


def ship_order_ok(order: dict) -> dict:
    return get_success_data(ship_order(order), 200)


def deliver_order(order: dict) -> dict:
    resp = api_client.deliver_order(order["id"], TEST_USERS["pharmacy_technician_headers"])
    return get_success_data(resp, 200)


def cancel_order(order: dict, reason: str = "CUSTOMER_REQUEST", as_pet: Optional[dict] = None):
    headers = (make_customer_headers(as_pet["id"]) if as_pet is not None
               else TEST_USERS["pharmacy_technician_headers"])
    return api_client.cancel_order(order["id"], {"cancellation_reason": reason}, headers)


def read_order(order: dict, as_pet: Optional[dict] = None) -> dict:
    headers = (make_customer_headers(as_pet["id"]) if as_pet is not None
               else TEST_USERS["pharmacy_technician_headers"])
    return get_success_data(api_client.get_order(order["id"], headers))


def read_shipment(shipment: dict) -> dict:
    return get_success_data(api_client.get_shipment(shipment["id"],
                                                   TEST_USERS["pharmacy_technician_headers"]))


def order_lines(order: dict, as_pet: Optional[dict] = None) -> list:
    headers = (make_customer_headers(as_pet["id"]) if as_pet is not None
               else TEST_USERS["pharmacy_technician_headers"])
    return get_success_data(api_client.list_order_lines(order["id"], headers))


def read_site(site: dict) -> dict:
    return get_success_data(api_client.get_site(site["id"],
                                               TEST_USERS["compliance_officer_headers"]))


def create_prescription(item: dict, vet: dict, **overrides) -> dict:
    payload = create_prescription_payload(item["id"], vet["id"], **overrides)
    resp = api_client.create_prescription(payload, TEST_USERS["pharmacy_technician_headers"])
    return get_success_data(resp, 201)


def run_callback_attempt(rx: dict, expected_status: int = 200):
    resp = api_client.record_clinic_contact(rx["id"], TEST_USERS["pharmacy_technician_headers"])
    return get_success_data(resp, expected_status)


def authorize(rx: dict, vet: dict, **overrides):
    """Authorise a prescription as the clinic contact acting for `vet`."""
    resp = api_client.authorize_prescription(rx["id"], overrides,
                                            make_clinic_contact_headers(vet["id"]))
    return resp


def verify_prescription(rx: dict, vet: dict) -> dict:
    """Walk a pending prescription through one callback and its authorisation."""
    run_callback_attempt(rx)
    return get_success_data(authorize(rx, vet), 200)


def verify_prescription_by_manager(rx: dict, vet: dict) -> dict:
    """Same walk, but the callback attempt is recorded by a manager handle."""
    get_success_data(api_client.record_clinic_contact(
        rx["id"], TEST_USERS["pharmacy_manager_headers"]))
    return get_success_data(authorize(rx, vet), 200)


def read_prescription(rx: dict) -> dict:
    return get_success_data(api_client.get_prescription(
        rx["id"], TEST_USERS["pharmacy_technician_headers"]))


def report_passing(pet: dict, refund_destination: str = "WALLET") -> dict:
    resp = api_client.report_passing(pet["id"], {"refund_destination": refund_destination},
                                    make_customer_headers(pet["id"]))
    return get_success_data(resp, 200)


def decide_review(review_id: str, outcome: str, operator_id: str = "cs-operator-1"):
    from prd_bench_local_runner.testing import build_user_headers
    resp = api_client.decide_review(review_id, {"outcome": outcome},
                                   build_user_headers(operator_id, "CustomerService"))
    return resp


# ---------------------------------------------------------------------------
# Tier 1/2 — plan + item hierarchies
# ---------------------------------------------------------------------------

def setup_pet_plan_and_item(product_overrides=None, cadence_days: int = 28,
                            default_quantity: int = 1, pet_overrides=None,
                            plan_overrides=None):
    """Clock → product → pet → plan → one item. Returns (pet, plan, product, item)."""
    set_clock()
    product = create_product(**(product_overrides or {}))
    pet = create_pet(**(pet_overrides or {}))
    plan = create_plan(pet, **(plan_overrides or {}))
    item = add_item(plan, pet, product, cadence_days=cadence_days,
                    default_quantity=default_quantity)
    return pet, plan, product, item


def setup_calibrated_item(product_overrides=None, cadence_days: int = 28,
                          pet_overrides=None):
    """A 40 kg dog with a 30-unit pack item: the item's equivalent duration is 30 days."""
    defaults = dict(sku="CAL-3001", product_name="Calibration pack",
                    medication_scope="OTC", cold_pack_required=False,
                    unit_dose_mg_per_kg=0.035, pack_size_units=30,
                    unit_price_cents=1610)
    defaults.update(product_overrides or {})
    pet_defaults = dict(pet_name="Rex", species="DOG", breed="Labrador",
                        weight_kg=40.0, owner_state="CA")
    pet_defaults.update(pet_overrides or {})
    return setup_pet_plan_and_item(product_overrides=defaults,
                                   cadence_days=cadence_days,
                                   pet_overrides=pet_defaults)


def setup_plan_with_blackout(blackout_start: str, blackout_end: str,
                             cadence_days: int = 14, product_overrides=None,
                             pet_overrides=None, clock: str = "2026-09-01T00:00:00Z"):
    """A plan carrying a blackout interval and one item."""
    defaults = dict(sku="BO-3001", product_name="Blackout pack",
                    unit_dose_mg_per_kg=0.02, pack_size_units=10,
                    unit_price_cents=1200)
    defaults.update(product_overrides or {})
    set_clock(clock)
    product = create_product(**defaults)
    pet = create_pet(**(pet_overrides or {}))
    plan = create_plan(pet, blackout_start_date=blackout_start,
                       blackout_end_date=blackout_end)
    item = add_item(plan, pet, product, cadence_days=cadence_days)
    return pet, plan, product, item


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts through to dispatch
# ---------------------------------------------------------------------------

def setup_dispatched_order(product_overrides=None, pet_overrides=None,
                           cadence_days: int = 28, site_overrides=None,
                           clock: str = "2026-09-01T00:00:00Z"):
    """Clock → site → product → pet → plan → item → compose → shipment → ship.

    Returns a dict bundle with keys: site, product, pet, plan, item, order, shipment.
    """
    prod_defaults = dict(sku="DSP-3001", product_name="Dispatch pack",
                         medication_scope="OTC", cold_pack_required=False,
                         unit_dose_mg_per_kg=0.02, pack_size_units=10,
                         unit_price_cents=1000)
    prod_defaults.update(product_overrides or {})
    site_defaults = dict(site_code="DSP1", site_state="CA", licensed_states=["CA"],
                         cold_pack_capacity_units=200, csr_registered=True)
    site_defaults.update(site_overrides or {})

    set_clock(clock)
    site = create_site(**site_defaults)
    product = create_product(**prod_defaults)
    pet = create_pet(**(pet_overrides or {}))
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=cadence_days)
    order = compose_ok(plan, pet)
    shipment = create_shipment(order)
    order = ship_order_ok(order)
    return {"site": site, "product": product, "pet": pet, "plan": plan,
            "item": item, "order": order, "shipment": shipment}


def setup_shipped_order(site_overrides=None, product_overrides=None,
                        pet_overrides=None, clock: str = "2026-09-01T00:00:00Z"):
    """A bundle dispatched through one shipment, plus its single order line."""
    bundle = setup_dispatched_order(site_overrides=site_overrides,
                                    product_overrides=product_overrides,
                                    pet_overrides=pet_overrides, clock=clock)
    bundle["lines"] = order_lines(bundle["order"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 3 — prescription verification shortcuts
# ---------------------------------------------------------------------------

def setup_prescription_item(vet_overrides=None, product_overrides=None,
                            pet_overrides=None, prescription_overrides=None,
                            cadence_days: int = 28, clock: str = "2026-09-01T00:00:00Z"):
    """Clock → rx product → vet → pet → plan → item → prescription (PENDING)."""
    prod_defaults = dict(sku="RX-3001", product_name="Prescription pack",
                         medication_scope="PRESCRIPTION", cold_pack_required=False,
                         unit_dose_mg_per_kg=0.02, pack_size_units=10,
                         unit_price_cents=2500)
    prod_defaults.update(product_overrides or {})
    vet_defaults = dict(full_name="Dr Ana Ruiz", clinic_name="Bayview Animal Clinic",
                        clinic_phone="4155550101", vet_email="aruiz@bayviewvet.example",
                        license_number="VET-CA-9001", license_state="CA")
    vet_defaults.update(vet_overrides or {})
    pet_defaults = dict(pet_name="Cleo", species="CAT", breed="Maine Coon",
                        weight_kg=6.0, owner_state="CA")
    pet_defaults.update(pet_overrides or {})

    set_clock(clock)
    product = create_product(**prod_defaults)
    vet = create_veterinarian(**vet_defaults)
    pet = create_pet(**pet_defaults)
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=cadence_days)
    rx = create_prescription(item, vet, **(prescription_overrides or {}))
    return {"product": product, "vet": vet, "pet": pet, "plan": plan,
            "item": item, "rx": rx}


def setup_verified_prescription_item(vet_overrides=None, product_overrides=None,
                                     pet_overrides=None, prescription_overrides=None,
                                     cadence_days: int = 28,
                                     clock: str = "2026-09-01T00:00:00Z",
                                     with_site: bool = True):
    """A prescription-scope item whose prescription has reached VERIFIED."""
    bundle = setup_prescription_item(vet_overrides=vet_overrides,
                                     product_overrides=product_overrides,
                                     pet_overrides=pet_overrides,
                                     prescription_overrides=prescription_overrides,
                                     cadence_days=cadence_days, clock=clock)
    if with_site:
        bundle["site"] = create_site(site_code="RXS1", site_state="CA",
                                     licensed_states=["CA"],
                                     cold_pack_capacity_units=400,
                                     csr_registered=True)
    bundle["rx"] = verify_prescription(bundle["rx"], bundle["vet"])
    return bundle


def setup_prescription_with_callback_attempts(attempts: int = 2, **kwargs):
    """Bundle whose prescription has seen `attempts` recorded clinic contacts."""
    bundle = setup_prescription_item(**kwargs)
    for _ in range(attempts):
        run_callback_attempt(bundle["rx"])
    bundle["rx"] = read_prescription(bundle["rx"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 4/5 — cancellation, cold-pack ledgers and the compassionate path
# ---------------------------------------------------------------------------

def setup_cold_pack_capacity_plan(site_overrides=None, product_overrides=None,
                                  pet_overrides=None, default_quantity: int = 1,
                                  clock: str = "2026-09-01T00:00:00Z"):
    """An ACTIVE CA site plus one cold-pack item still awaiting composition."""
    prod_defaults = dict(sku="CP-3001", product_name="Cold pack item",
                         medication_scope="OTC", cold_pack_required=True,
                         unit_dose_mg_per_kg=0.02, pack_size_units=10,
                         unit_price_cents=1200)
    prod_defaults.update(product_overrides or {})
    site_defaults = dict(site_code="CP1", site_state="CA", licensed_states=["CA"],
                         cold_pack_capacity_units=300, csr_registered=True)
    site_defaults.update(site_overrides or {})

    set_clock(clock)
    site = create_site(**site_defaults)
    product = create_product(**prod_defaults)
    pet = create_pet(**(pet_overrides or {}))
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28,
                    default_quantity=default_quantity)
    return {"site": site, "product": product, "pet": pet, "plan": plan, "item": item}


def setup_canceled_cold_pack_order(site_overrides=None, product_overrides=None,
                                   pet_overrides=None, cancel_reason: str = "CUSTOMER_REQUEST",
                                   clock: str = "2026-09-01T00:00:00Z"):
    """A composed-then-cancelled cold-pack order whose refund path is live."""
    bundle = setup_cold_pack_capacity_plan(site_overrides=site_overrides,
                                           product_overrides=product_overrides,
                                           pet_overrides=pet_overrides, clock=clock)
    order = compose_ok(bundle["plan"], bundle["pet"])
    get_success_data(cancel_order(order, cancel_reason, as_pet=bundle["pet"]), 200)
    bundle["order"] = read_order(order, as_pet=bundle["pet"])
    return bundle


def setup_in_transit_order_for_passing(site_overrides=None, product_overrides=None,
                                       pet_overrides=None, clock: str = "2026-09-01T00:00:00Z"):
    """A dispatched order whose pet can then be reported as passed."""
    return setup_dispatched_order(product_overrides=product_overrides,
                                  pet_overrides=pet_overrides,
                                  site_overrides=site_overrides, clock=clock)


def setup_review_ready_order(cold_pack: bool = True, clock: str = "2026-09-01T00:00:00Z"):
    """A composed-then-cancelled order plus a reported passing, with the review OPEN.

    Returns a dict bundle with keys: site, product, pet, plan, item, order, review_id.
    """
    bundle = setup_cold_pack_capacity_plan(
        site_overrides=dict(site_code="RV1", cold_pack_capacity_units=300),
        product_overrides=dict(sku="RV-3001", product_name="Compassionate pack",
                               cold_pack_required=cold_pack, unit_price_cents=1193),
        clock=clock)
    order = compose_ok(bundle["plan"], bundle["pet"])
    get_success_data(cancel_order(order, "CUSTOMER_REQUEST", as_pet=bundle["pet"]), 200)
    pet_after = report_passing(bundle["pet"], "WALLET")
    bundle["order"] = read_order(order, as_pet=bundle["pet"])
    bundle["review_id"] = pet_after["compassionate_review_id"]
    return bundle


# ---------------------------------------------------------------------------
# Identity constants re-exported for convenience
# ---------------------------------------------------------------------------

MISSING_ORDER_ID = NON_EXISTENT_UUID
MISSING_PET_ID = NON_EXISTENT_UUID
ERR_INVALID_STATE = ApiErrorId.ERR_INVALID_STATE
ERR_RESOURCE_NOT_FOUND = ApiErrorId.ERR_RESOURCE_NOT_FOUND
ERR_PLAN_PAUSED = ApiErrorId.ERR_PLAN_PAUSED