"""Title curative work and the blocking chain (PRD section 3.4)."""

from flask import Blueprint

import access
import calc
import cascades
import serializers as ser
import validation as v
from auth import (
    LAND_AGENT,
    PORTFOLIO_MANAGER,
    TITLE_COUNSEL,
    acting_user_id,
    require,
)
from envelope import ok, ok_list
from errors import (
    ERR_CURATIVE_BLOCKED_PREDECESSOR,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WAIVER_LIMIT_REACHED,
    fail,
)
from store import db, insert, now, ordered, touch

bp = Blueprint("curative", __name__, url_prefix="/land-origination")

READERS = (LAND_AGENT, TITLE_COUNSEL, PORTFOLIO_MANAGER)
ITEM_TYPES = ("MINERAL_SEVERANCE", "MORTGAGE_SUBORDINATION",
              "ACCESS_EASEMENT_GAP", "TAX_LIEN", "HEIRSHIP_GAP")
SEVERITIES = ("BLOCKING", "MATERIAL", "ADVISORY")


@bp.get("/title-curative-items/<item_id>")
@require(*READERS)
def get_item(item_id):
    return ok(ser.curative_item(access.curative_item(item_id)))


@bp.get("/title-curative-items")
@require(*READERS)
def list_items():
    limit, offset = v.pagination()
    rows = ordered(db.curative_items.values())
    rows = v.apply_filters(rows, [
        ("parcel_id", v.query_str("parcel_id")),
        ("blocks_item_id", v.query_str("blocks_item_id")),
        ("severity", v.query_str("severity")),
        ("status", v.query_str("status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.curative_item, page), limit, offset, total)


@bp.post("/title-curative-items")
@require(TITLE_COUNSEL)
def create_item():
    body = v.json_body()
    # Rung 4 then rung 7, both ahead of the rung-14 shape pass.
    parcel_id = v.lookup_fk(body, "parcel_id")
    parcel = access.parcel(parcel_id) if parcel_id else None
    predecessor = None
    blocks_item_id = v.lookup_fk(body, "blocks_item_id")
    if blocks_item_id is not None:
        predecessor = access.curative_item(blocks_item_id)

    v.req_fk(body, "parcel_id")
    v.opt_fk(body, "blocks_item_id")
    item_type = v.req_enum(body, "item_type", ITEM_TYPES)
    severity = v.req_enum(body, "severity", SEVERITIES)
    cost = v.req_int(body, "curative_cost_cents", lo=0)

    blocked = predecessor is not None and \
        predecessor["status"] in ("BLOCKED", "OPEN")
    row = insert("curative_items", {
        "parcel_id": parcel["id"],
        "blocks_item_id": predecessor["id"] if predecessor else None,
        "item_type": item_type,
        "severity": severity,
        "curative_cost_cents": cost,
        "created_by_user_id": acting_user_id(),
        "cleared_by_user_id": None,
        "cleared_at": None,
        "waiver_note": None,
        "status": "BLOCKED" if blocked else "OPEN",
    })

    # The counters fold into the screening recompute's single version bump.
    cascades.recount_curative_counters(parcel)
    cascades.recompute_parcel_screening(parcel)
    cascades.reevaluate_parcel_qualification(parcel)
    cascades.sync_landowner_posture(db.landowners.get(parcel["landowner_id"]))
    return ok(ser.curative_item(row), 201)


def _promote_successors(item):
    for successor in ordered([i for i in db.curative_items.values()
                              if i["blocks_item_id"] == item["id"]]):
        if successor["status"] == "BLOCKED":
            successor["status"] = "OPEN"
            touch(successor)


def _resolve(item, parcel):
    _promote_successors(item)
    cascades.recount_curative_counters(parcel)
    cascades.recompute_parcel_screening(parcel)
    cascades.reevaluate_parcel_qualification(parcel)
    cascades.sync_landowner_posture(db.landowners.get(parcel["landowner_id"]))


@bp.post("/title-curative-items/<item_id>/clear")
@require(TITLE_COUNSEL)
def clear_item(item_id):
    row = access.curative_item(item_id)
    parcel = db.parcels.get(row["parcel_id"])

    if row["status"] in ("CLEARED", "WAIVED"):
        fail(ERR_INVALID_STATE)
    if parcel is None or parcel["status"] == "DISQUALIFIED":
        fail(ERR_INVALID_STATE)
    if acting_user_id() == row["created_by_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES)
    if row["status"] == "BLOCKED":
        fail(ERR_CURATIVE_BLOCKED_PREDECESSOR)

    row["status"] = "CLEARED"
    row["cleared_at"] = now()
    row["cleared_by_user_id"] = acting_user_id()
    touch(row)
    _resolve(row, parcel)
    return ok(ser.curative_item(row))


@bp.post("/title-curative-items/<item_id>/waive")
@require(TITLE_COUNSEL)
def waive_item(item_id):
    row = access.curative_item(item_id)
    body = v.json_body()
    waiver_note = v.req_str(body, "waiver_note", min_len=1)
    parcel = db.parcels.get(row["parcel_id"])

    if row["status"] in ("CLEARED", "WAIVED"):
        fail(ERR_INVALID_STATE)
    if parcel is None:
        fail(ERR_INVALID_STATE)
    if acting_user_id() == row["created_by_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES)
    if row["status"] == "BLOCKED":
        fail(ERR_CURATIVE_BLOCKED_PREDECESSOR)
    if row["severity"] == "BLOCKING" and \
            int(parcel["waived_blocking_count"]) >= calc.MAX_WAIVED_BLOCKING_PER_PARCEL:
        fail(ERR_WAIVER_LIMIT_REACHED)

    row["status"] = "WAIVED"
    row["waiver_note"] = waiver_note
    row["cleared_at"] = now()
    row["cleared_by_user_id"] = acting_user_id()
    touch(row)
    _resolve(row, parcel)
    return ok(ser.curative_item(row))
