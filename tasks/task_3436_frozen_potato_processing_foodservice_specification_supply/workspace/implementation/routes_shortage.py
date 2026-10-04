"""Shortage event endpoints (declare, execute-allocation) and the read-only
byproduct batch surface."""

import domain
from db import store
from errors import ApiError
from flask import Blueprint, request
from middleware import ANY_ROLES, require_roles
from response import list_response, sort_default, success_object
from util import body_json, req_enum, req_int, req_number
from constants import RESPONSE_MODES, VARIETIES

bp = Blueprint("shortage", __name__)


@bp.route("/potato-ops/shortage-events", methods=["POST"])
@require_roles("GrowerRelationsManager")
def create_shortage_event():
    body = body_json()
    scope_variety = req_enum(body, "scope_variety", VARIETIES)
    deficit = req_number(body, "declared_deficit_cwt")
    if deficit <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'declared_deficit_cwt': must be > 0", 400
        )
    available = req_int(body, "available_week_cases")
    if available < 1 or available > 100000:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'available_week_cases': must be between 1 and 100000",
            400,
        )
    mode = req_enum(body, "response_mode", RESPONSE_MODES)
    e = domain.new_entity()
    e.update({
        "scope_variety": scope_variety,
        "declared_deficit_cwt": deficit,
        "available_week_cases": available,
        "response_mode": mode,
        "status": "OPEN",
        "allocation_results": None,
    })
    store.shortage_events[e["id"]] = e
    return success_object(domain.shortage_event_view(e), 201)


@bp.route("/potato-ops/shortage-events/<eid>/execute-allocation", methods=["POST"])
@require_roles("GrowerRelationsManager")
def execute_allocation(eid):
    event = domain.get_shortage_event_or_404(eid)
    if event["status"] != "OPEN":
        raise ApiError(
            "ERR_SHORTAGE_EVENT_NOT_OPEN",
            "execute-allocation requires the shortage event OPEN",
            409,
        )
    domain.execute_allocation(event)
    return success_object(domain.shortage_event_view(event), 200)


@bp.route("/potato-ops/byproduct-batches", methods=["GET"])
@require_roles(*ANY_ROLES)
def list_batches():
    items = list(store.batches.values())
    source_run_id = request.args.get("source_run_id")
    source_lot_id = request.args.get("source_lot_id")
    routing = request.args.get("routing")
    if source_run_id is not None:
        items = [b for b in items if b["source_run_id"] == source_run_id]
    if source_lot_id is not None:
        items = [b for b in items if b["source_lot_id"] == source_lot_id]
    if routing is not None:
        items = [b for b in items if b["routing"] == routing]
    return list_response(sort_default(items), domain.batch_view)


@bp.route("/potato-ops/byproduct-batches/<bid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_batch(bid):
    return success_object(domain.batch_view(domain.get_batch_or_404(bid)), 200)
