"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (the server is restarted before each test, so each test starts
against an empty database and the logical clock at its startup default of
2026-09-01T00:00:00Z, PRD §2.4). Setup calls use the lenient
get_success_data() validator so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import assert_placement, assert_product_lot
from .constants import CLOCK_START_ISO
from .factories import (
    STORE_ALPHA,
    create_agreement_payload,
    create_chiller_batch_payload,
    create_placement_payload,
    create_product_lot_payload,
    create_reading_payload,
    create_release_payload,
    create_shipment_payload,
    create_site_evaluation_payload,
    create_store_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["placement_manager_headers"]
DISPATCHER = TEST_USERS["service_dispatcher_headers"]
TECH = TEST_USERS["field_technician_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


# --- Primitive steps -------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (forward-only, PRD §2.4)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def create_store(payload: dict = None, **overrides) -> dict:
    body = payload if payload is not None else create_store_payload(**overrides)
    resp = api_client.create_store(body, ADMIN)
    assert resp.status_code == 201, f"setup: create store failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_site_evaluation(store_id: str, **overrides) -> dict:
    resp = api_client.create_site_evaluation(store_id, create_site_evaluation_payload(**overrides), PM)
    assert resp.status_code == 201, f"setup: create site evaluation failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_agreement(store_id: str, **overrides) -> dict:
    resp = api_client.create_placement_agreement(store_id, create_agreement_payload(**overrides), PM)
    assert resp.status_code == 201, f"setup: create agreement failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def sign_agreement(agreement_id: str) -> dict:
    resp = api_client.sign_agreement(agreement_id, PM)
    assert resp.status_code == 200, f"setup: sign agreement failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_chiller_batch(model: str = "STANDARD", serial_prefix: str = "FP", quantity: int = 1,
                         serial_start_seq: int = None) -> list:
    payload = create_chiller_batch_payload(model=model, serial_prefix=serial_prefix, quantity=quantity)
    if serial_start_seq is not None:
        payload["serial_start_seq"] = serial_start_seq
    resp = api_client.create_chillers(payload, PLANNER)
    assert resp.status_code == 201, f"setup: create chillers failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_chiller(**batch_overrides) -> dict:
    """Register a batch of one chiller; return the single chiller row."""
    return create_chiller_batch(**batch_overrides)[0]


def install_placement(store_id: str, agreement: dict, chiller_id: str,
                      expected_agreement_version: int = None) -> dict:
    version = agreement["version"] if expected_agreement_version is None else expected_agreement_version
    payload = create_placement_payload(store_id, agreement["id"], chiller_id, version)
    resp = api_client.create_placement(payload, PM)
    assert resp.status_code == 201, f"setup: install placement failed: {resp.status_code} {resp.text}"
    placement = get_success_data(resp)
    assert_placement(placement)
    return placement


def post_reading(chiller_id: str, recorded_at: str, temp_c: float, duration_minutes: int,
                 headers=None) -> dict:
    resp = api_client.post_temperature_reading(
        chiller_id,
        create_reading_payload(recorded_at=recorded_at, temp_c=temp_c, duration_minutes=duration_minutes),
        headers or ADMIN,
    )
    assert resp.status_code == 201, f"setup: post reading failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def evaluate_performance(placement_id: str, trailing_weekly_units) -> dict:
    resp = api_client.evaluate_performance(placement_id, {"trailing_weekly_units": trailing_weekly_units}, PM)
    assert resp.status_code == 200, f"setup: evaluate-performance failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_chiller(chiller_id: str) -> dict:
    resp = api_client.get_chiller(chiller_id, ADMIN)
    assert resp.status_code == 200, f"setup: get chiller failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_placement(placement_id: str) -> dict:
    resp = api_client.get_placement(placement_id, PM)
    assert resp.status_code == 200, f"setup: get placement failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_product_lot(lot_id: str) -> dict:
    resp = api_client.get_product_lot(lot_id, PLANNER)
    assert resp.status_code == 200, f"setup: get lot failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def list_service_tickets(chiller_id: str, params=None) -> list:
    resp = api_client.list_service_tickets(chiller_id, DISPATCHER, params=params)
    assert resp.status_code == 200, f"setup: list tickets failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


# --- Composite fixtures ----------------------------------------------------

def setup_store_with_eligible_evaluation(store_payload: dict = None, **eval_overrides):
    """Store + a DEMOGRAPHIC_LED/STANDARD evaluation (default forecast 200/wk,
    allocated_sqft 16 — ELIGIBLE under the PRD §3.1 verdict gate).

    Returns (store, evaluation).
    """
    store = create_store(payload=store_payload) if store_payload is not None else create_store()
    evaluation = create_site_evaluation(store["id"], **eval_overrides)
    return store, evaluation


def setup_signed_agreement(store_payload: dict = None, eval_overrides: dict = None,
                           agreement_overrides: dict = None):
    """Store + evaluation + a SIGNED agreement.

    Returns (store, evaluation, agreement) with the agreement carrying its
    post-sign version.
    """
    store, evaluation = setup_store_with_eligible_evaluation(
        store_payload=store_payload, **(eval_overrides or {})
    )
    agreement = create_agreement(store["id"], **(agreement_overrides or {}))
    agreement = sign_agreement(agreement["id"])
    return store, evaluation, agreement


def setup_active_placement(store_payload: dict = None, eval_overrides: dict = None,
                           agreement_overrides: dict = None, chiller_model: str = "STANDARD",
                           chiller_prefix: str = "FP") -> dict:
    """Full install path: store + evaluation + SIGNED agreement + IN_STOCK
    chiller + ACTIVE placement (PRD §3.4).

    Returns a context dict: store, evaluation, agreement (post-install ACTIVE),
    chiller (post-install INSTALLED), placement.
    """
    store, evaluation, agreement = setup_signed_agreement(
        store_payload=store_payload,
        eval_overrides=eval_overrides,
        agreement_overrides=agreement_overrides,
    )
    chiller = create_chiller(model=chiller_model, serial_prefix=chiller_prefix)
    placement = install_placement(store["id"], agreement, chiller["id"])
    return {
        "store": store,
        "evaluation": evaluation,
        "agreement": agreement,
        "chiller": get_chiller(chiller["id"]),
        "placement": placement,
    }


def setup_activated_placement(clock_to: str = "2026-09-02T08:00:00Z",
                              reading_recorded_at: str = "2026-09-02T07:30:00Z",
                              **placement_kwargs) -> dict:
    """Active placement whose chiller has been activated by a first in-range
    reading (INSTALLED -> ACTIVE, PRD §3.5). Advances the logical clock to
    `clock_to` and posts an in-range reading recorded at `reading_recorded_at`.
    """
    ctx = setup_active_placement(**placement_kwargs)
    set_clock(clock_to)
    post_reading(ctx["chiller"]["id"], reading_recorded_at, 2.5, 15)
    ctx["chiller"] = get_chiller(ctx["chiller"]["id"])
    assert ctx["chiller"]["status"] == "ACTIVE", "setup: chiller should be ACTIVE after first in-range reading"
    return ctx


def trigger_severe_excursion(ctx: dict, clock_to: str = "2026-09-02T10:00:00Z",
                             recorded_at: str = "2026-09-02T09:45:00Z",
                             temp_c: float = 6.0, duration_minutes: int = 130) -> dict:
    """Post a single reading that pushes the excursion accumulator to >= 120
    (PRD §2.10 severe threshold, boundary inclusive). Returns the updated
    chiller. Caller must ensure the clock and recorded_at are consistent.
    """
    set_clock(clock_to)
    post_reading(ctx["chiller"]["id"], recorded_at, temp_c, duration_minutes)
    chiller = get_chiller(ctx["chiller"]["id"])
    ctx["chiller"] = chiller
    return chiller


def setup_suspended_placement(**kwargs) -> dict:
    """Activated placement driven into the severe-excursion cascade:
    chiller NEEDS_REPAIR, placement operational SUSPENDED, one AUTO_EXCURSION
    ticket minted (PRD §3.5). Returns ctx with 'auto_ticket' added.
    """
    ctx = setup_activated_placement(**kwargs)
    trigger_severe_excursion(ctx)
    assert ctx["chiller"]["status"] == "NEEDS_REPAIR"
    tickets = list_service_tickets(ctx["chiller"]["id"])
    auto = [t for t in tickets if t["origin"] == "AUTO_EXCURSION"]
    assert len(auto) == 1, "setup: expected exactly one AUTO_EXCURSION ticket"
    ctx["auto_ticket"] = auto[0]
    ctx["placement"] = get_placement(ctx["placement"]["id"])
    assert ctx["placement"]["operational_status"] == "SUSPENDED"
    return ctx


def setup_underperforming_streak(ctx: dict, evaluations) -> dict:
    """Drive the placement through the given trailing-velocity reports in order
    (PRD §3.6 streak semantics). Returns the final placement snapshot.
    """
    placement = ctx["placement"]
    for units in evaluations:
        placement = evaluate_performance(placement["id"], units)
    ctx["placement"] = placement
    return placement


def create_released_lot(quantity_units: int = 500, sku: str = "BEEF-5LB",
                        produced_at: str = CLOCK_START_ISO) -> dict:
    """Register a lot (QUARANTINE) and release it with qc_passed true.

    produced_at must be <= the current logical time (PRD §3.7); the default is
    the clock startup instant, which is always valid.
    """
    resp = api_client.create_product_lot(
        create_product_lot_payload(sku=sku, produced_at=produced_at, quantity_units=quantity_units),
        PLANNER,
    )
    assert resp.status_code == 201, f"setup: create lot failed: {resp.status_code} {resp.text}"
    lot = get_success_data(resp)
    assert_product_lot(lot)
    resp = api_client.release_product_lot(lot["id"], create_release_payload(qc_passed=True), PLANNER)
    assert resp.status_code == 200, f"setup: release lot failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_shipment(ctx: dict, lot: dict, quantity_units: int) -> dict:
    """Dispatch a shipment to the context's store (departs immediately)."""
    resp = api_client.create_shipment(
        create_shipment_payload(ctx["store"]["id"], lot["id"], quantity_units), LOGISTICS
    )
    assert resp.status_code == 201, f"setup: create shipment failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def deliver_shipment(shipment_id: str, accepted_units: int, rejected_units: int) -> dict:
    resp = api_client.deliver_shipment(
        shipment_id, {"accepted_units": accepted_units, "rejected_units": rejected_units}, LOGISTICS
    )
    assert resp.status_code == 200, f"setup: deliver shipment failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_delivered_inventory(ctx: dict, lot: dict, quantity_units: int,
                               accepted_units: int = None, rejected_units: int = 0) -> dict:
    """Ship and fully reconcile a delivery, producing a SELLABLE inventory
    position at the context's store. Returns the DELIVERED shipment.
    """
    if accepted_units is None:
        accepted_units = quantity_units
    shipment = create_shipment(ctx, lot, quantity_units)
    return deliver_shipment(shipment["id"], accepted_units, rejected_units)
