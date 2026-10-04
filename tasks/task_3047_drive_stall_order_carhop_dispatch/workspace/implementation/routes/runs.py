"""DeliveryRun endpoints: staging (dispatch selector), departure, delivery, void (PRD 3.6)."""
from db import db, now
from errors import not_found, raise_error, invalid_request, invalid_state
from middleware import (
    require_auth,
    body_json,
    get_int,
    get_str,
    get_str_list,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import delivery_run as ser_run, order as ser_order
from services import (
    make_record,
    touch,
    get_location,
    get_run_nested,
    release_stall_if_current,
    maybe_complete_run,
)
from . import runs_bp

RUN_STATUSES = ["LOADED", "OUT", "COMPLETED", "VOIDED"]
RUN_READ_ROLES = ["ShiftManager", "Carhop", "PlatformAdmin"]


def _order_zone(order):
    """Zone covering an order: PATIO orders -> PATIO; stalls by stall_number parity."""
    stall = db.stalls.get(order["stall_id"]) if order["stall_id"] else None
    if stall is None:
        return None
    if order["channel"] == "PATIO" or stall["kind"] == "PATIO":
        return "PATIO"
    return "NORTH" if stall["stall_number"] % 2 == 0 else "SOUTH"


def _required_zone(selected):
    """Zone of the earliest-placed order (mixed trays) / majority zone."""
    first = selected[0]
    return _order_zone(first)


@runs_bp.route("/locations/<locationId>/delivery-runs", methods=["POST"])
def stage_run(locationId):
    require_auth(["ShiftManager"])
    loc = get_location(locationId)
    body = body_json()
    carhop_id = body.get("carhop_id")
    if carhop_id is not None and not isinstance(carhop_id, str):
        invalid_request("carhop_id must be a string")
    expected_carhop_version = get_int(body, "expected_carhop_version", required=True)
    order_ids = get_str_list(body, "order_ids")
    route_note = get_str(body, "route_note")

    # Candidate orders: READY, non-drive-thru, unstaged at this location.
    candidates = [
        o
        for o in db.orders.values()
        if o["location_id"] == loc["id"]
        and o["status"] == "READY"
        and o["channel"] != "DRIVE_THRU"
        and o["delivery_run_id"] is None
    ]
    if order_ids is not None:
        restricted = []
        for oid in order_ids:
            o = db.orders.get(oid)
            if o is None or o["location_id"] != loc["id"]:
                not_found("Order not found")
            restricted.append(o)
        candidates = [o for o in restricted if o["status"] == "READY"
                      and o["channel"] != "DRIVE_THRU" and o["delivery_run_id"] is None]
    candidates.sort(key=lambda o: (o["placed_at"] or o["created_at"], o["created_at"], o["id"]))

    carhop = None
    if carhop_id is not None:
        carhop = db.carhops.get(carhop_id)
        if carhop is None or carhop["location_id"] != loc["id"]:
            not_found("Carhop not found")
        # OCC on the explicitly selected carhop (PRD 2.8).
        if expected_carhop_version != carhop["version"]:
            raise_error("ERR_STALE_VERSION", "Stale carhop version; re-read the carhop")
        take = min(len(candidates), carhop["max_trays"])
        selected = candidates[:take]
        if not _carhop_eligible(carhop, selected):
            raise_error("ERR_NO_CARHOP_ELIGIBLE", "The selected carhop is not dispatch-eligible")
    else:
        selected = None
        eligible_carhops = sorted(
            [c for c in db.carhops.values() if c["location_id"] == loc["id"]],
            key=lambda c: (c["active_run_load"], c["created_at"], c["id"]),
        )
        for cand in eligible_carhops:
            take = min(len(candidates), cand["max_trays"])
            sel = candidates[:take]
            if _carhop_eligible(cand, sel):
                carhop = cand
                selected = sel
                break
        if carhop is None:
            raise_error("ERR_NO_CARHOP_ELIGIBLE", "No on-shift carhop fits zone and capacity")
        if expected_carhop_version != carhop["version"]:
            raise_error("ERR_STALE_VERSION", "Stale carhop version; re-read the carhop")

    rec = make_record()
    rec.update(
        {
            "location_id": loc["id"],
            "carhop_id": carhop["id"],
            "status": "LOADED",
            "order_count": len(selected),
            "staged_at": now(),
            "out_at": None,
            "route_note": route_note,
        }
    )
    db.delivery_runs[rec["id"]] = rec
    for pos, order in enumerate(selected, start=1):
        order["delivery_run_id"] = rec["id"]
        order["run_position"] = pos
        touch(order)
        # The delivering carhop is now known: attach it to the order's
        # RECORDED tip (captured before staging) so the outstanding-tip
        # counters and refund cascade have a carhop to settle against.
        for tip in db.tip_records.values():
            if (
                tip["order_id"] == order["id"]
                and tip["status"] == "RECORDED"
                and tip["carhop_id"] is None
            ):
                tip["carhop_id"] = carhop["id"]
                touch(tip)
                carhop["tips_outstanding_cents"] += tip["tip_cents"]
    carhop["active_run_load"] += len(selected)
    touch(carhop)
    return success_object(ser_run(rec), 201)


def _carhop_eligible(carhop, selected):
    if not carhop["on_shift"]:
        return False
    if carhop["active_run_load"] + len(selected) > carhop["max_trays"]:
        return False
    if len(selected) > 0:
        zone = _required_zone(selected)
        if zone is not None and carhop["zone"] != zone:
            return False
    return True


@runs_bp.route("/locations/<locationId>/delivery-runs", methods=["GET"])
def list_runs(locationId):
    require_auth(RUN_READ_ROLES)
    from flask import request

    get_location(locationId)
    status = request.args.get("status")
    carhop_id = request.args.get("carhop_id")
    if status is not None and status not in RUN_STATUSES:
        invalid_request("status must be a valid run status")
    runs = [r for r in db.delivery_runs.values() if r["location_id"] == locationId]
    if status is not None:
        runs = [r for r in runs if r["status"] == status]
    if carhop_id is not None:
        runs = [r for r in runs if r["carhop_id"] == carhop_id]
    runs = sort_by_created(runs)
    limit, offset = pagination_params()
    total = len(runs)
    page = runs[offset : offset + limit]
    return success_array([ser_run(r) for r in page], limit, offset, total)


@runs_bp.route("/locations/<locationId>/delivery-runs/<runId>", methods=["GET"])
def get_run(locationId, runId):
    require_auth(RUN_READ_ROLES)
    loc, run = get_run_nested(locationId, runId)
    return success_object(ser_run(run))


@runs_bp.route("/locations/<locationId>/delivery-runs/<runId>/depart", methods=["POST"])
def depart_run(locationId, runId):
    user_id, role = require_auth(["Carhop", "ShiftManager"])
    loc, run = get_run_nested(locationId, runId)
    if run["status"] != "LOADED":
        invalid_state("Run is not LOADED")
    if role == "Carhop" and run["carhop_id"] != user_id:
        raise_error("ERR_NOT_ASSIGNED_CARHOP", "This run is assigned to a different carhop")
    if run["order_count"] < 1:
        raise_error("ERR_EMPTY_RUN", "Cannot depart a run with no orders")
    run["status"] = "OUT"
    run["out_at"] = now()
    touch(run)
    for o in db.orders.values():
        if o.get("delivery_run_id") == run["id"] and o["status"] == "READY":
            o["status"] = "OUT_FOR_DELIVERY"
            touch(o)
    return success_object(ser_run(run))


@runs_bp.route("/locations/<locationId>/delivery-runs/<runId>/void", methods=["POST"])
def void_run(locationId, runId):
    require_auth(["ShiftManager"])
    loc, run = get_run_nested(locationId, runId)
    if run["status"] != "LOADED":
        invalid_state("Run is not LOADED")
    for o in db.orders.values():
        if o.get("delivery_run_id") == run["id"]:
            o["delivery_run_id"] = None
            o["run_position"] = None
            touch(o)
    run["status"] = "VOIDED"
    touch(run)
    carhop = db.carhops.get(run["carhop_id"])
    if carhop is not None:
        carhop["active_run_load"] -= run["order_count"]
        touch(carhop)
    return success_object(ser_run(run))


@runs_bp.route(
    "/locations/<locationId>/delivery-runs/<runId>/orders/<orderId>/deliver",
    methods=["POST"],
)
def deliver_order(locationId, runId, orderId):
    require_auth(["Carhop", "ShiftManager"])
    loc, run = get_run_nested(locationId, runId)
    order = db.orders.get(orderId)
    if order is None or order["location_id"] != loc["id"]:
        not_found("Order not found")
    if order["status"] != "OUT_FOR_DELIVERY":
        invalid_state("Order is not OUT_FOR_DELIVERY")
    if order.get("delivery_run_id") != run["id"]:
        not_found("Order is not on this run")
    if order["payment_status"] != "CAPTURED":
        raise_error("ERR_PAYMENT_NOT_CAPTURED", "Order payment has not been captured")
    for o in db.orders.values():
        if (
            o.get("delivery_run_id") == run["id"]
            and o["run_position"] is not None
            and order["run_position"] is not None
            and o["run_position"] < order["run_position"]
            and o["status"] not in ("DELIVERED", "CANCELLED")
        ):
            raise_error(
                "ERR_RUN_SEQUENCE_VIOLATION",
                "Orders must be delivered in run_position order",
            )
    order["status"] = "DELIVERED"
    order["delivered_at"] = now()
    elapsed = (order["delivered_at"] - order["placed_at"]).total_seconds()
    order["late_flag"] = elapsed > order["service_target_seconds"]
    release_stall_if_current(order)
    touch(order)
    maybe_complete_run(run)
    return success_object(ser_order(order))
