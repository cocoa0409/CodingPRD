"""Composite setup helpers.

Multi-step API sequences that place the system in the state a test needs. Every
helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server is restarted against an empty database before each test.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    author_layers_payload,
    create_fulfillment_order_payload,
    create_licensor_payload,
    create_print_capacity_payload,
    create_production_order_payload,
    reserve_capacity_payload,
)
from .test_users import TEST_USERS, make_licensing_ops_headers

CLOCK_START = "2026-09-01T00:00:00Z"
CLOCK_PLUS_1H = "2026-09-01T01:00:00Z"
CLOCK_PLUS_48H = "2026-09-03T00:00:00Z"
CLOCK_PAST_WINDOW = "2026-09-04T00:00:00Z"

ADMIN = TEST_USERS["platform_admin_headers"]
DESIGN_OPS = TEST_USERS["design_ops_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
PRINTER = TEST_USERS["print_operator_headers"]
FULFILLMENT = TEST_USERS["fulfillment_coordinator_headers"]
ENFORCEMENT = TEST_USERS["enforcement_agent_headers"]
AUDIT = TEST_USERS["audit_only_headers"]


def _ok(resp, what):
    assert 200 <= resp.status_code < 300, (
        f"Setup failed: {what} -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(api, utc=CLOCK_START):
    resp = api.set_clock(utc, ADMIN)
    _ok(resp, f"set clock to {utc}")
    return resp


# ---------------------------------------------------------------------------
# Licensors
# ---------------------------------------------------------------------------

def create_licensor(api, **overrides):
    resp = api.create_licensor(create_licensor_payload(**overrides), ADMIN)
    data = _ok(resp, "create licensor")
    assert data.get("id"), f"Setup failed: licensor has no id -> {resp.text}"
    return data


def get_licensor(api, licensor_id, headers=None):
    return _ok(api.get_licensor(licensor_id, headers or ADMIN), "read licensor")


# ---------------------------------------------------------------------------
# Designs
# ---------------------------------------------------------------------------

def create_design(api, licensor, approve=True, **overrides):
    """Author a design for `licensor` (a licensor dict). When `approve` is true
    the licensor decision is recorded by the licensor's own operator identity."""
    payload = {
        "licensor_id": licensor["id"],
        "team_code": "ATL",
        "garment_sku": "TRACTOR",
        "design_name": "Test Design",
    }
    payload.update(overrides)
    resp = api.create_design(payload, DESIGN_OPS)
    design = _ok(resp, "create design")
    if approve:
        design = approve_design(api, licensor, design)
    return design


def approve_design(api, licensor, design, decision="APPROVE", **extra):
    payload = {"decision": decision, "expected_design_version": design["version"]}
    payload.update(extra)
    resp = api.licensor_decision(
        design["id"], payload, make_licensing_ops_headers(licensor["id"]),
    )
    return _ok(resp, "record licensor decision")


def reject_design(api, licensor, design, reason="Mark placement off brand"):
    return approve_design(
        api, licensor, design, decision="REJECT", rejection_reason=reason,
    )


def get_design(api, design_id, headers=None):
    return _ok(api.get_design(design_id, headers or DESIGN_OPS), "read design")


# ---------------------------------------------------------------------------
# Production runs, layers and press work
# ---------------------------------------------------------------------------

def create_run(api, licensor, design, **overrides):
    payload = create_production_order_payload(licensor["id"], design["id"])
    payload.update({
        "team_code": design["team_code"],
        "trigger_type": "STANDARD",
        "expected_demand_qty": 20000,
        "unit_cost_cents": 900,
    })
    payload.update(overrides)
    resp = api.create_production_order(payload, PLANNER)
    return _ok(resp, "create production order")


def author_layers(api, run, layers, destroy_mode=None):
    # A layer prints its run's pinned artwork (PRD 3.3: the run names the
    # `design_id` its layers print), so the fixture states it explicitly.
    entries = []
    for layer in layers:
        entry = dict(layer)
        entry.setdefault("design_id", run.get("design_id"))
        entries.append(entry)
    payload = author_layers_payload(run["version"], entries)
    if destroy_mode is not None:
        payload["destroy_mode"] = destroy_mode
    resp = api.author_layers(run["id"], payload, PLANNER)
    return _ok(resp, "author layers")


def get_run(api, production_order_id, headers=None):
    return _ok(
        api.get_production_order(production_order_id, headers or PLANNER),
        "read production order",
    )


def print_layer(api, print_layer_id, printed_qty):
    return _ok(
        api.print_layer(print_layer_id, {"printed_qty": printed_qty}, PRINTER),
        "print layer",
    )


def print_failure(api, print_layer_id, failed_qty):
    return _ok(
        api.print_failure(print_layer_id, {"failed_qty": failed_qty}, PRINTER),
        "record print failure",
    )


def retire_run(api, production_order_id, retire_reason="DEMAND_COLLAPSE",
               destroy_mode="DESTROY"):
    payload = {"retire_reason": retire_reason}
    if destroy_mode is not None:
        payload["destroy_mode"] = destroy_mode
    resp = api.retire_production_order(production_order_id, payload, PLANNER)
    return _ok(resp, "retire production order")


def committed_run(api, base_qty=2000, base_print_type="BASE",
                  extra_layers=None, **run_overrides):
    """Licensor + approved design + a run committed by authoring its layers.

    Returns a dict with licensor, design, run and layer_ids. The BASE layer is
    always submitted first so the layer sequencing rules are satisfied.
    """
    licensor_overrides = run_overrides.pop("licensor_overrides", None) or {}
    design_overrides = run_overrides.pop("design_overrides", None) or {}
    licensor = create_licensor(api, **licensor_overrides)
    design = create_design(api, licensor, **design_overrides)
    run = create_run(api, licensor, design, **run_overrides)
    layers = [{"print_type": base_print_type, "quantity": base_qty}]
    layers.extend(extra_layers or [])
    committed = author_layers(api, run, layers)
    return {
        "licensor": licensor,
        "design": design,
        "run": committed,
        "layer_ids": committed["layer_ids"],
        "base_layer_id": committed["layer_ids"][0],
    }


def printed_run(api, printed_qty=20, base_qty=None, **kwargs):
    """A committed run whose BASE layer has already been printed."""
    setup = committed_run(
        api, base_qty=base_qty if base_qty is not None else printed_qty, **kwargs,
    )
    print_layer(api, setup["base_layer_id"], printed_qty)
    setup["run"] = get_run(api, setup["run"]["id"])
    return setup


# ---------------------------------------------------------------------------
# Fulfillment orders and the disposal rails
# ---------------------------------------------------------------------------

def create_order(api, run, **overrides):
    payload = create_fulfillment_order_payload(run["id"])
    payload.update(overrides)
    resp = api.create_fulfillment_order(payload, FULFILLMENT)
    return _ok(resp, "create fulfillment order")


def get_order(api, fulfillment_order_id, headers=None):
    return _ok(
        api.get_fulfillment_order(fulfillment_order_id, headers or FULFILLMENT),
        "read fulfillment order",
    )


def pick_order(api, order, run_id, quantity, remark):
    version = get_run(api, run_id)["version"]
    resp = api.pick(
        order["id"],
        {
            "expected_production_order_version": version,
            "quantity": quantity,
            "pick_remark": remark,
        },
        FULFILLMENT,
    )
    return _ok(resp, "pick fulfillment order")


def ship_order(api, order, quantity, carrier="GROUND", sla_hours=48):
    resp = api.ship(
        order["id"],
        {"quantity": quantity, "carrier": carrier, "sla_hours": sla_hours},
        FULFILLMENT,
    )
    return _ok(resp, "ship fulfillment order")


def deliver_order(api, order):
    resp = api.deliver(order["id"], {}, FULFILLMENT)
    return _ok(resp, "deliver fulfillment order")


def deliver_flow(api, run_id, order, quantity, remark="pick-1"):
    """Pick, ship and deliver one order in full; returns the delivered order."""
    pick_order(api, order, run_id, quantity, remark)
    ship_order(api, order, quantity)
    return deliver_order(api, order)


# ---------------------------------------------------------------------------
# Capacity windows
# ---------------------------------------------------------------------------

def create_capacity(api, **overrides):
    resp = api.create_print_capacity(create_print_capacity_payload(**overrides),
                                     FULFILLMENT)
    return _ok(resp, "create capacity window")


def get_capacity(api, print_capacity_id, headers=None):
    return _ok(
        api.get_print_capacity(print_capacity_id, headers or FULFILLMENT),
        "read capacity window",
    )


def reserve_capacity(api, print_capacity_id, **overrides):
    payload = reserve_capacity_payload(print_capacity_id, **overrides)
    resp = api.reserve_capacity(payload, FULFILLMENT)
    return _ok(resp, "reserve capacity")