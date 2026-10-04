"""Stores and the operator's logical clock.

  POST /op/stores                       enroll a retail store
  GET  /op/stores                       list stores
  POST /op/stores/{id}/transition       SUSPEND / REINSTATE
  POST /op/_clock/set_current_utc       drive the logical clock
"""

from flask import Blueprint, request

import db as store
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE, ROLE_DISTRIBUTOR,
    STRING, INTEGER, DATETIME,
    require_role, check_body, check_query_enums, require_action,
)
from services import cascade
from services import clock_service
from utils import parse_dt

bp = Blueprint("stores", __name__)

STORE_STATUSES = ("ACTIVE", "SUSPENDED")
STORE_ACTIONS = ("SUSPEND", "REINSTATE")


# --------------------------------------------------------------------------
# POST /op/_clock/set_current_utc
# --------------------------------------------------------------------------

@bp.route("/op/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("current_utc",),
        types={"current_utc": DATETIME},
    )
    value = parse_dt(body["current_utc"])
    if value is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 datetime.")
    clock_service.set_clock(value)
    from utils import to_iso
    return envelope.object_response({"current_utc": to_iso(value)})


# --------------------------------------------------------------------------
# POST /op/stores
# --------------------------------------------------------------------------

@bp.route("/op/stores", methods=["POST"])
def create_store():
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("name", "region_code", "daily_event_capacity", "event_space_capacity"),
        types={
            "name": STRING,
            "region_code": STRING,
            "daily_event_capacity": INTEGER,
            "event_space_capacity": INTEGER,
        },
    )
    row = store.insert_store(
        body["name"],
        body["region_code"],
        body["daily_event_capacity"],
        body["event_space_capacity"],
    )
    return envelope.object_response(models.store_view(row), status=201)


# --------------------------------------------------------------------------
# GET /op/stores
# --------------------------------------------------------------------------

@bp.route("/op/stores", methods=["GET"])
def list_stores():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE,
                           ROLE_DISTRIBUTOR))
    check_query_enums(request, {"status": STORE_STATUSES})
    rows = list(store.db.stores.values())
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.store_view(r) for r in rows], limit, offset)


# --------------------------------------------------------------------------
# POST /op/stores/{id}/transition
# --------------------------------------------------------------------------

@bp.route("/op/stores/<store_id>/transition", methods=["POST"])
def transition_store(store_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("action",),
        optional=("reason",),
        types={"action": STRING, "reason": STRING},
    )
    action = require_action(body, STORE_ACTIONS)

    row = store.db.stores.get(store_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Store %s does not exist." % store_id)

    if action == "SUSPEND":
        if row["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "Only an ACTIVE store may be suspended.")
        store.touch(row, status="SUSPENDED")
        cascade.suspend_store(row)
    else:  # REINSTATE
        if row["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE", "Only a SUSPENDED store may be reinstated.")
        # Reinstatement is not an undo: nothing is re-opened.
        store.touch(row, status="ACTIVE")

    return envelope.object_response(models.store_view(row))