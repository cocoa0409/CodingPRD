"""Production runs, print layers endpoints.

Request-shape checks (the highest-precedence rung of the validation ladder),
authentication, role authorization and existence checks all live here; the
workflow rules they delegate to live in the service modules.
"""
from flask import request

from datetime import timedelta

import db
from errors import (
    ERR_ALREADY_COMMITTED, ERR_CAPACITY_EXCEEDED, ERR_COUNTERFEIT_OVERCOUNT,
    ERR_DESIGN_NOT_APPROVED, ERR_DESIGN_NOT_FOUND, ERR_EVENT_WINDOW_CLOSED,
    ERR_FORBIDDEN_ROLE, ERR_FULFILLMENT_ORDER_NOT_FOUND, ERR_GUARANTEE_FLOOR_BREACH,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INVENTORY_INSUFFICIENT,
    ERR_LICENSOR_MISMATCH, ERR_LICENSOR_NOT_FOUND, ERR_LICENSOR_PROJECT_NOT_FOUND,
    ERR_LISTING_UNVERIFIED, ERR_LOT_EXHAUSTED, ERR_NO_ACCRUED_ROYALTY, ERR_NOT_FOUND,
    ERR_PICK_REMARK_REUSED, ERR_PRINT_QUANTITY_EXCEEDED, ERR_PRINT_TYPECAST_MISMATCH,
    ERR_PRODUCTION_ALREADY_COMMITTED, ERR_PRODUCTION_ORDER_NOT_FOUND,
    ERR_RUSH_COMMITMENT_BREACH, ERR_SEGREGATION_OF_DUTIES, ERR_SETTLEMENT_NOOP,
    ERR_STALE_VERSION, ERR_UNAUTHENTICATED, ERR_UNBALANCED_ALLOCATION, fail)
from response import (authenticate, ok_array, ok_object, paginate, pagination,
                      require_roles)
from routing import (
    CAPACITY_TYPES, CARRIERS, CHANNELS, DECISIONS, DEFAULT_HOURS_TO_OUTCOME,
    DESTROY_MODES, DISTRESS_REASONS, EVENT_OUTCOMES, EVENT_WINDOW_HOURS,
    GARMENT_SKUS, PRINT_TYPES, RETIRE_REASONS, TRIGGER_TYPES,
    api, body, check_licensor_ownership, check_licensor_project, check_segregation,
    get_capacity, get_design, get_layer, get_licensor, get_order, get_report, get_run,
    licensor_projects, optional_string, require_enum, require_field, require_int,
    require_instant, require_number, require_order_version, require_version)
from services import fulfillment, ledger, pricing, production



@api.route("/production-orders", methods=["POST"])
def create_production_order():
    payload = body()
    licensor_id = require_field(payload, "licensor_id")
    design_id = require_field(payload, "design_id")
    team_code = require_field(payload, "team_code")
    if not isinstance(team_code, str) or not team_code.strip():
        fail(ERR_INVALID_REQUEST, "field 'team_code' must be a non-empty string")
    trigger_type = require_enum(payload, "trigger_type", TRIGGER_TYPES)
    expected_demand_qty = require_int(payload, "expected_demand_qty", positive=True)
    unit_cost_cents = require_int(payload, "unit_cost_cents", positive=True)
    event_outcome = require_enum(payload, "event_outcome", EVENT_OUTCOMES,
                                 optional=True, default="NO_OUTCOME")
    pennants_included = payload.get("pennants_included", True)
    if pennants_included is not None and not isinstance(pennants_included, bool):
        fail(ERR_INVALID_REQUEST, "field 'pennants_included' must be a boolean")
    win_probability_pct = require_number(payload, "win_probability_pct",
                                         optional=True, default=0.5, low=0, high=1)
    outcome_at = require_instant(payload, "outcome_at", optional=True, default=None)

    caller = authenticate()
    require_roles(caller, ("ProductionPlanner",))

    licensor = get_licensor(licensor_id)
    design = get_design(design_id)
    check_segregation(caller, design)
    if design.get("approval_state") != "APPROVED":
        fail(ERR_DESIGN_NOT_APPROVED, "the referenced design is not approved")
    check_licensor_project(licensor, trigger_type)

    hours = (db.hours_between(outcome_at, db.now()) if outcome_at is not None
             else DEFAULT_HOURS_TO_OUTCOME)
    tier = pricing.demand_tier(expected_demand_qty)

    run = {
        "licensor_id": licensor_id,
        "design_id": design_id,
        "team_code": team_code,
        "trigger_type": trigger_type,
        "event_outcome": event_outcome,
        "status": "PARALLEL_HOLD",
        "expected_demand_qty": expected_demand_qty,
        "unit_cost_cents": unit_cost_cents,
        "layer_ids": [],
        "base_units_printed": 0,
        "accessory_units_printed": 0,
        "hold_allocation_cents": 0,
        "committed_inventory_cents": 0,
        "pennants_included": bool(pennants_included),
        "retired_design_version": design.get("approved_version"),
        "observed_current_design_version": int(design.get("version", 0) or 0),
        "win_probability_pct": win_probability_pct,
        "outcome_at": db.fmt_iso(outcome_at),
        "capacity_commitment_units": 0,
        "rush_delivery_points": 0,
        "write_down_inventory_cents": 0,
        "destroyed_units": 0,
        "donated_units": 0,
        "committed_at": None,
        "retired_at": None,
        "retire_reason": None,
    }
    db.init_common(run)

    first_variant = pricing.is_first_of_team_trigger(run)
    committed = pricing.capacity_commitment_units(
        expected_demand_qty, win_probability_pct, hours, tier, first_variant)
    required = pricing.required_allocation_units(expected_demand_qty,
                                                 win_probability_pct, tier)
    if committed < required:
        fail(ERR_UNBALANCED_ALLOCATION,
             "the hot-market allocation falls below its floor; the run requires %s units"
             % required)

    run["capacity_commitment_units"] = int(committed)
    run["hold_allocation_cents"] = int(production.hold_allocation(run))
    run["rush_delivery_points"] = int(pricing.rush_delivery_points(run))
    db.store.production_orders[run["id"]] = run
    return ok_object(run, 201)


@api.route("/production-orders", methods=["GET"])
def list_production_orders():
    caller = authenticate()
    require_roles(caller, ("ProductionPlanner", "FulfillmentCoordinator", "AuditOnly"))
    limit, offset = pagination()
    items = db.created_order(list(db.store.production_orders.values()))
    for arg, field in (("licensor_id", "licensor_id"), ("design_id", "design_id"),
                       ("status", "status"), ("team_code", "team_code")):
        value = request.args.get(arg)
        if value:
            items = [r for r in items if r.get(field) == value]
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


@api.route("/production-orders/<production_order_id>", methods=["GET"])
def read_production_order(production_order_id):
    caller = authenticate()
    require_roles(caller, ("ProductionPlanner", "FulfillmentCoordinator", "AuditOnly"))
    return ok_object(get_run(production_order_id))


def _validate_layer_payload(layers):
    """Request shape: every layer carries a valid print type and a strictly
    positive quantity.  The artwork a layer prints is the artwork its run pins
    (PRD 3.3), so a layer may name it through `design_id` or leave it to the run;
    only a mistyped identifier is a shape failure."""
    if not isinstance(layers, list) or not layers:
        fail(ERR_INVALID_REQUEST, "field 'layers' must be a non-empty array")
    checked = []
    for entry in layers:
        if not isinstance(entry, dict):
            fail(ERR_INVALID_REQUEST, "each layer must be an object")
        design_id = entry.get("design_id")
        if design_id is not None and not isinstance(design_id, str):
            fail(ERR_INVALID_REQUEST, "field 'design_id' must be a string")
        print_type = require_enum(entry, "print_type", PRINT_TYPES)
        quantity = require_int(entry, "quantity", positive=True)
        checked.append({"design_id": design_id, "print_type": print_type,
                        "quantity": quantity})
    return checked


@api.route("/production-orders/<production_order_id>/layers", methods=["POST"])
def author_layers(production_order_id):
    payload = body()
    layers = _validate_layer_payload(payload.get("layers"))
    destroy_mode = require_enum(payload, "destroy_mode", DESTROY_MODES, optional=True)

    caller = authenticate()
    require_roles(caller, ("ProductionPlanner",))

    run = get_run(production_order_id)
    design = get_design(run.get("design_id"))
    licensor = db.store.licensors.get(run.get("licensor_id"))
    for entry in layers:
        if entry["design_id"] is not None:
            get_design(entry["design_id"])

    # The optimistic-concurrency guard is the sixth rung and the commit-sequencing
    # rule the ninth, so a stale version is reported before the sequencing
    # refusal (PRD 2.10).
    require_version(payload, "expected_production_order_version", run.get("version", 0))
    if not production.can_accept_commit(run):
        fail(ERR_ALREADY_COMMITTED,
             "the run has already left PARALLEL_HOLD without an intervening revert")
    check_segregation(caller, design)

    if design.get("approval_state") != "APPROVED":
        fail(ERR_DESIGN_NOT_APPROVED, "the referenced design is not approved")
    if run.get("retired_design_version") != design.get("approved_version"):
        fail(ERR_PRINT_TYPECAST_MISMATCH,
             "the run's pinned design version differs from the design's approved version")

    # Sequencing: a BASE layer must be committed before any EMBROIDER or
    # HEAT_PRESS layer; a PENNANT layer needs pennants_included true.
    submitted = [entry["print_type"] for entry in layers]
    has_base = "BASE" in submitted
    for print_type in submitted:
        if print_type in ("EMBROIDER", "HEAT_PRESS") and not has_base:
            fail(ERR_PRINT_TYPECAST_MISMATCH,
                 "a BASE layer must be committed before %s layers" % print_type)
        if print_type == "PENNANT" and not run.get("pennants_included", True):
            fail(ERR_PRINT_TYPECAST_MISMATCH,
                 "PENNANT layers are excluded on this run")

    # Commit sequencing: only the earliest-created run of a (team_code,
    # trigger_type) group may commit once a sibling has committed.
    siblings = [r for r in db.store.production_orders.values()
                if r.get("team_code") == run.get("team_code")
                and r.get("trigger_type") == run.get("trigger_type")]
    committed_siblings = [r for r in siblings if r.get("status") in ("COMMITTED", "PRINTING")]
    if committed_siblings:
        ordered = db.created_order(siblings)
        if ordered and ordered[0]["id"] != run["id"]:
            fail(ERR_PRODUCTION_ALREADY_COMMITTED,
                 "an earlier-created run with the same team_code and trigger_type "
                 "has already committed")

    created = []
    for entry in layers:
        layer = {
            "production_order_id": run["id"],
            "design_id": entry["design_id"] or run.get("design_id"),
            "print_type": entry["print_type"],
            "quantity": int(entry["quantity"]),
            "printed_qty": 0,
            "committed_qty": 0,
            "failed_qty": 0,
            "layer_state": "PENDING_PRINT",
            "design_version_checked": None,
        }
        db.init_common(layer)
        db.store.print_layers[layer["id"]] = layer
        created.append(layer)
        run["layer_ids"].append(layer["id"])

    run["observed_current_design_version"] = int(design.get("version", 0) or 0)
    production.refresh_printed_totals(run)

    if destroy_mode != "SHORTFALL":
        production.mark_committed(run, design, licensor)
    else:
        db.touch(run)
    db.store.reopened_runs.discard(run["id"])
    return ok_object(run, 200)


@api.route("/production-orders/<production_order_id>/retire", methods=["POST"])
def retire_production_order(production_order_id):
    payload = body()
    retire_reason = require_enum(payload, "retire_reason", RETIRE_REASONS)
    destroy_mode = require_enum(payload, "destroy_mode", DESTROY_MODES, optional=True)

    caller = authenticate()
    require_roles(caller, ("ProductionPlanner",))

    run = get_run(production_order_id)
    design = db.store.designs.get(run.get("design_id"))
    licensor = db.store.licensors.get(run.get("licensor_id"))

    status = run.get("status")
    if status not in ("PARALLEL_HOLD", "COMMITTED", "PRINTING"):
        fail(ERR_INVALID_STATE, "the run is not in a state that permits retirement")

    # Aggregate capacity: the run's picked, destroyed, donated and returned units,
    # counted across all channels, must not exceed its printable pool.
    if fulfillment.aggregate_ceiling_breached(run, 0):
        fail(ERR_CAPACITY_EXCEEDED,
             "the run's aggregated units would pass its printable pool")

    production.retire_run(run, retire_reason, destroy_mode, design, licensor, status)
    return ok_object(run, 200)



@api.route("/print-layers", methods=["GET"])
def list_print_layers():
    caller = authenticate()
    require_roles(caller, ("PrintOperator", "ProductionPlanner", "AuditOnly"))
    limit, offset = pagination()
    items = db.created_order(list(db.store.print_layers.values()))
    for arg, field in (("production_order_id", "production_order_id"),
                       ("design_id", "design_id"), ("layer_state", "layer_state")):
        value = request.args.get(arg)
        if value:
            items = [l for l in items if l.get(field) == value]
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


@api.route("/print-layers/<print_layer_id>", methods=["GET"])
def read_print_layer(print_layer_id):
    caller = authenticate()
    require_roles(caller, ("PrintOperator", "ProductionPlanner", "AuditOnly"))
    return ok_object(get_layer(print_layer_id))


def _event_window_open(run):
    """The event window opens at committed_at and closes 48 hours later."""
    committed_at = db.parse_iso(run.get("committed_at"))
    if committed_at is None:
        return True
    return db.now() <= committed_at + timedelta(hours=EVENT_WINDOW_HOURS)


def _typecast_ok(run, layer):
    """BASE layers first; pennant layers only when pennants_included is true."""
    if layer.get("print_type") == "PENNANT" and not run.get("pennants_included", True):
        return False
    if layer.get("print_type") in ("EMBROIDER", "HEAT_PRESS"):
        for layer_id in run.get("layer_ids") or []:
            other = db.store.print_layers.get(layer_id)
            if other is None:
                continue
            if other.get("print_type") == "BASE" and other.get("committed_qty", 0) > 0:
                return True
        return False
    return True


@api.route("/print-layers/<print_layer_id>/print", methods=["POST"])
def print_layer(print_layer_id):
    payload = body()
    printed_qty = require_int(payload, "printed_qty", positive=True)

    caller = authenticate()
    require_roles(caller, ("PrintOperator",))

    layer = get_layer(print_layer_id)
    run = get_run(layer.get("production_order_id"))
    design = db.store.designs.get(run.get("design_id"))

    if run.get("status") not in ("COMMITTED", "PRINTING"):
        fail(ERR_INVALID_STATE, "the run is not in a state that permits printing")
    if int(layer.get("printed_qty", 0) or 0) + printed_qty > int(layer.get("quantity", 0) or 0):
        fail(ERR_PRINT_QUANTITY_EXCEEDED,
             "printed_qty would exceed the layer's authorized quantity")
    if not _typecast_ok(run, layer):
        fail(ERR_PRINT_TYPECAST_MISMATCH,
             "the layer's print type is out of sequence on this run")
    if run.get("status") == "PRINTING" and not _event_window_open(run):
        fail(ERR_EVENT_WINDOW_CLOSED, "the run's event window has closed")

    layer["printed_qty"] = int(layer.get("printed_qty", 0) or 0) + printed_qty
    layer["committed_qty"] = int(layer["printed_qty"]) - int(layer.get("failed_qty", 0) or 0)
    layer["layer_state"] = "PRINTED"
    layer["design_version_checked"] = (int(design.get("version", 0) or 0)
                                       if design else None)
    db.touch(layer)

    production.refresh_printed_totals(run)
    if run.get("status") == "COMMITTED":
        run["status"] = "PRINTING"
    db.touch(run)
    if design is not None:
        db.touch(design)
    return ok_object(layer, 200)


@api.route("/print-layers/<print_layer_id>/print-failure", methods=["POST"])
def print_failure(print_layer_id):
    payload = body()
    failed_qty = require_int(payload, "failed_qty", positive=True)

    caller = authenticate()
    require_roles(caller, ("PrintOperator",))

    layer = get_layer(print_layer_id)
    run = get_run(layer.get("production_order_id"))
    design = db.store.designs.get(run.get("design_id"))
    licensor = db.store.licensors.get(run.get("licensor_id"))

    if run.get("status") not in ("COMMITTED", "PRINTING"):
        fail(ERR_INVALID_STATE, "the run is not in a state that permits a print failure")

    was_printed = layer.get("layer_state") == "PRINTED"
    # A failure recorded on an already-printed layer is a printing mutation, so
    # the run's event window gates it before anything is written (PRD 3.6); a
    # request arriving after the window closes leaves the layer untouched.
    if was_printed and not _event_window_open(run):
        fail(ERR_EVENT_WINDOW_CLOSED, "the run's event window has closed")
    layer["failed_qty"] = int(layer.get("failed_qty", 0) or 0) + failed_qty
    layer["committed_qty"] = max(0, int(layer.get("printed_qty", 0) or 0)
                                 - int(layer["failed_qty"]))
    layer["layer_state"] = "PRINT_FAILED"
    layer["design_version_checked"] = (int(design.get("version", 0) or 0)
                                       if design else None)
    db.touch(layer)

    if was_printed:
        production.cascade_layer_failure(run, layer, design, licensor)
    else:
        production.refresh_printed_totals(run)
        db.touch(run)

    # The reopen rail: a failure that drives committed_qty to exactly zero
    # returns the run from PRINTING to COMMITTED and restarts the event window.
    if run.get("status") == "PRINTING" and int(layer.get("committed_qty", 0) or 0) == 0:
        production.reopen_run(run, design, licensor)
    return ok_object(layer, 200)


