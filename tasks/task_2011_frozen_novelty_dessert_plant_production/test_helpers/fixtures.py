"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: CustomerRep is entity-backed by Customer — every
ownership-gated call (contract submit, claim file/appeal/withdraw, complaint
withdraw) uses make_customer_rep_headers(customer["id"]). Segregation of
duties on the QA side uses distinct opaque user ids (qa_1, qa_2) per step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allocation_payload,
    create_changeover_payload,
    create_contract_payload,
    create_customer_payload,
    create_freezer_zone_payload,
    create_line_payload,
    create_mix_batch_payload,
    create_production_run_payload,
    create_product_payload,
    create_quality_complaint_payload,
    create_seasonal_build_plan_payload,
    create_shipment_payload,
    create_temp_abuse_claim_payload,
    create_tunnel_booking_payload,
    create_tunnel_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_rep_headers,
    make_line_operator_headers,
    make_qa_manager_headers,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
WH = TEST_USERS["warehouse_lead_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]

DEFAULT_CLOCK = "2026-08-10T08:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server logical clock (PRD §2.7)."""
    return get_success_data(api_client.set_clock(to_iso8601, PM))


def create_product(**overrides):
    payload = create_product_payload(**overrides)
    return get_success_data(api_client.create_product(payload, PM), 201)


def create_customer(**overrides):
    payload = create_customer_payload(**overrides)
    return get_success_data(api_client.create_customer(payload, PM), 201)


def create_line(**overrides):
    payload = create_line_payload(**overrides)
    return get_success_data(api_client.create_line(payload, PM), 201)


def create_tunnel(**overrides):
    payload = create_tunnel_payload(**overrides)
    return get_success_data(api_client.create_tunnel(payload, PM), 201)


def create_freezer_zone(**overrides):
    payload = create_freezer_zone_payload(**overrides)
    return get_success_data(api_client.create_freezer_zone(payload, PM), 201)


def create_mix_batch(product_id, **overrides):
    payload = create_mix_batch_payload(product_id, **overrides)
    return get_success_data(api_client.create_mix_batch(payload, PLANNER), 201)


def pasteurize_batch(batch_id, op_user="op_1"):
    return get_success_data(api_client.pasteurize_mix_batch(
        batch_id, make_line_operator_headers(op_user)))


def release_batch(batch_id, qa_user="qa_1"):
    return get_success_data(api_client.release_mix_batch(
        batch_id, make_qa_manager_headers(qa_user)))


def create_released_batch(product_id, batch_code="MB-1", litres=500,
                          op_user="op_1", qa_user="qa_1",
                          clock=DEFAULT_CLOCK):
    """Create a mix batch and walk it PLANNED -> PASTEURIZED -> RELEASED."""
    set_clock(clock)
    batch = create_mix_batch(product_id, batch_code=batch_code,
                             litres_produced=litres)
    pasteurize_batch(batch["id"], op_user)
    return release_batch(batch["id"], qa_user)


def create_run(product_id, line_id, **overrides):
    payload = create_production_run_payload(product_id, line_id, **overrides)
    return get_success_data(api_client.create_production_run(payload, PLANNER), 201)


def create_changeover(line_id, to_product_id, **overrides):
    payload = create_changeover_payload(line_id, to_product_id, **overrides)
    return get_success_data(api_client.create_changeover(payload, PLANNER), 201)


def complete_changeover(changeover_id, op_user="op_1"):
    return get_success_data(api_client.complete_changeover(
        changeover_id, make_line_operator_headers(op_user)))


def verify_changeover(changeover_id, outcome="PASS", qa_user="qa_1"):
    return get_success_data(api_client.verify_changeover(
        changeover_id, {"outcome": outcome}, make_qa_manager_headers(qa_user)))


def create_verified_changeover(line_id, to_product_id, op_user="op_1",
                               qa_user="qa_1"):
    """Open a changeover and walk it to VERIFIED (line returns to IDLE)."""
    ch = create_changeover(line_id, to_product_id)
    complete_changeover(ch["id"], op_user)
    return verify_changeover(ch["id"], "PASS", qa_user)


def create_booking(tunnel_id, run_id, **overrides):
    payload = create_tunnel_booking_payload(tunnel_id, run_id, **overrides)
    return get_success_data(api_client.create_tunnel_booking(payload, PLANNER), 201)


def get_lot_for_run(run_id):
    """Discover the lot created by a run's completion (PRD §3.7)."""
    resp = api_client.list_inventory_lots(PLANNER, params={"run_id": run_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) >= 1, \
        f"expected a lot for run {run_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — plant masters
# ---------------------------------------------------------------------------

def setup_plant(product_overrides=None, line_overrides=None,
                tunnel_overrides=None, zone_overrides=None):
    """Product + line + tunnel + zone. Returns (product, line, tunnel, zone)."""
    product = create_product(**(product_overrides or {}))
    line = create_line(**(line_overrides or {}))
    tunnel = create_tunnel(**(tunnel_overrides or {}))
    zone = create_freezer_zone(**(zone_overrides or {}))
    return product, line, tunnel, zone


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle — completed runs
# ---------------------------------------------------------------------------

def start_run(run_id, op_user="op_1"):
    return get_success_data(api_client.start_run(
        run_id, make_line_operator_headers(op_user)))


def complete_run(run_id, actual_units, mix_metered_litres, zone_id,
                 op_user="op_1"):
    """Trigger run completion. Returns the raw Response so capacity/mix
    failures can be asserted by callers; happy-path callers should use
    complete_run_ok."""
    return api_client.complete_run(
        run_id,
        {"actual_units": actual_units, "mix_metered_litres": mix_metered_litres,
         "zone_id": zone_id},
        make_line_operator_headers(op_user))


def complete_run_ok(run_id, actual_units, mix_metered_litres, zone_id,
                    op_user="op_1"):
    return get_success_data(complete_run(
        run_id, actual_units, mix_metered_litres, zone_id, op_user))


def setup_completed_run(product_overrides=None, product=None, run_code="R-1",
                        planned_units=2000, actual_units=2000,
                        mix_metered_litres=100.0, scheduled_start=None,
                        booking_window=("2026-08-10T13:00:00Z",
                                        "2026-08-10T14:00:00Z"),
                        clock=DEFAULT_CLOCK, line_overrides=None):
    """Full pipeline: masters -> released batch -> run -> verified changeover
    -> booking -> assign -> start -> complete.

    Pass either `product_overrides` (a fresh product is created) or an
    existing `product` entity (e.g. the co-pack product a contract pins).
    `line_overrides` is forwarded to the line factory in both branches.

    Returns dict(product, line, tunnel, zone, batch, run, lot).
    """
    if product is None:
        product, line, tunnel, zone = setup_plant(product_overrides,
                                                  line_overrides)
    else:
        line = create_line(**(line_overrides or {}))
        tunnel, zone = create_tunnel(), create_freezer_zone()
    batch = create_released_batch(product["id"], clock=clock)
    sched = scheduled_start or "2026-08-10T14:00:00Z"
    run = create_run(product["id"], line["id"], run_code=run_code,
                     planned_units=planned_units, scheduled_start=sched)
    create_verified_changeover(line["id"], product["id"])
    create_booking(tunnel["id"], run["id"], start_at=booking_window[0],
                   end_at=booking_window[1])
    get_success_data(api_client.assign_mix(
        run["id"], {"mix_batch_id": batch["id"]}, PLANNER))
    start_run(run["id"])
    complete_run_ok(run["id"], actual_units, mix_metered_litres, zone["id"])
    lot = get_lot_for_run(run["id"])
    return {
        "product": product, "line": line, "tunnel": tunnel, "zone": zone,
        "batch": batch, "run": run, "lot": lot,
    }


def setup_mix_assigned_run(run_code="R-1", clock=DEFAULT_CLOCK,
                           product_overrides=None,
                           scheduled_start="2026-08-10T14:00:00Z",
                           with_changeover=True, with_booking=True,
                           planned_units=None):
    """Run in MIX_ASSIGNED with (optionally) a VERIFIED changeover and a
    BOOKED tunnel booking. Returns dict of everything built."""
    product, line, tunnel, zone = setup_plant(product_overrides)
    batch = create_released_batch(product["id"], clock=clock)
    run_kwargs = {"run_code": run_code, "scheduled_start": scheduled_start}
    if planned_units is not None:
        run_kwargs["planned_units"] = planned_units
    run = create_run(product["id"], line["id"], **run_kwargs)
    changeover = None
    if with_changeover:
        changeover = create_verified_changeover(line["id"], product["id"])
    booking = None
    if with_booking:
        booking = create_booking(tunnel["id"], run["id"])
    get_success_data(api_client.assign_mix(
        run["id"], {"mix_batch_id": batch["id"]}, PLANNER))
    return {
        "product": product, "line": line, "tunnel": tunnel, "zone": zone,
        "batch": batch, "run": run, "changeover": changeover,
        "booking": booking,
    }


# ---------------------------------------------------------------------------
# Tier 4: shipments / claims / complaints
# ---------------------------------------------------------------------------

def create_shipment(customer_id, **overrides):
    payload = create_shipment_payload(customer_id, **overrides)
    return get_success_data(api_client.create_shipment(payload, WH), 201)


def allocate(shipment_id, lot_id, units):
    payload = create_allocation_payload(lot_id, units=units)
    return get_success_data(api_client.create_allocation(
        shipment_id, payload, WH), 201)


def setup_delivered_shipment(readings=None, dispatch_time="2026-08-12T08:00:00Z",
                             deliver_time="2026-08-12T13:00:00Z",
                             carrier_liability=False, shipment_code="SH-1",
                             allocation_units=500, customer_overrides=None):
    """Completed lot + shipment allocated/loaded/dispatched/read/delivered.

    Returns dict(base..., customer, shipment, allocation).
    """
    base = setup_completed_run()
    customer = create_customer(**(customer_overrides or {}))
    payload_overrides = {"shipment_code": shipment_code}
    if carrier_liability:
        payload_overrides["carrier_liability"] = True
    shipment = create_shipment(customer["id"], **payload_overrides)
    allocation = allocate(shipment["id"], base["lot"]["id"], allocation_units)
    get_success_data(api_client.load_shipment(shipment["id"], WH))
    set_clock(dispatch_time)
    get_success_data(api_client.dispatch_shipment(shipment["id"], WH))
    if readings is not None:
        get_success_data(api_client.append_temperature_readings(
            shipment["id"], {"readings": readings}, WH), 201)
    set_clock(deliver_time)
    get_success_data(api_client.deliver_shipment(shipment["id"], WH))
    base.update({"customer": customer, "shipment": shipment,
                 "allocation": allocation})
    return base


def file_claim(shipment_id, customer_id, claim_code="CL-1",
               declared_value_cents=50000):
    payload = create_temp_abuse_claim_payload(
        shipment_id, claim_code=claim_code,
        declared_value_cents=declared_value_cents)
    return get_success_data(api_client.create_temp_abuse_claim(
        payload, make_customer_rep_headers(customer_id)), 201)


def create_complaint(lot_id, complaint_code="QC-1", complaint_type="TEXTURE",
                     filed_by_customer_id=None, qa_user="qa_1"):
    payload = create_quality_complaint_payload(
        lot_id, complaint_code=complaint_code, complaint_type=complaint_type)
    if filed_by_customer_id is not None:
        headers = make_customer_rep_headers(filed_by_customer_id)
    else:
        headers = make_qa_manager_headers(qa_user)
    return get_success_data(api_client.create_quality_complaint(payload, headers),
                            201)


# ---------------------------------------------------------------------------
# Tier 5: contracts / build plans
# ---------------------------------------------------------------------------

def create_contract(customer_id, product_id, **overrides):
    payload = create_contract_payload(customer_id, product_id, **overrides)
    return get_success_data(api_client.create_contract(payload, PM), 201)


def setup_active_contract(committed_units=1000, unit_price_cents=100,
                          product_overrides=None, contract_code="CT-1",
                          activate_at="2026-08-05T00:00:00Z"):
    """Co-pack product + private-label customer + contract walked to ACTIVE.
    Returns dict(product, customer, contract)."""
    product_overrides = dict(product_overrides or {})
    product_overrides["co_pack_only"] = True
    product = create_product(**product_overrides)
    customer = create_customer(customer_code="PL-1", display_name="Big Retailer",
                               kind="PRIVATE_LABEL")
    contract = create_contract(customer["id"], product["id"],
                               contract_code=contract_code,
                               committed_units=committed_units,
                               unit_price_cents=unit_price_cents)
    get_success_data(api_client.submit_contract(
        contract["id"], make_customer_rep_headers(customer["id"])))
    get_success_data(api_client.approve_contract(contract["id"], PM))
    set_clock(activate_at)
    contract = get_success_data(api_client.get_contract(contract["id"], PM))
    assert contract["status"] == "ACTIVE", \
        f"contract should be ACTIVE after clock pass, got {contract['status']}"
    return {"product": product, "customer": customer, "contract": contract}


def create_build_plan(product_id, zone_id, **overrides):
    payload = create_seasonal_build_plan_payload(product_id, zone_id, **overrides)
    return get_success_data(api_client.create_seasonal_build_plan(payload, PLANNER),
                            201)
