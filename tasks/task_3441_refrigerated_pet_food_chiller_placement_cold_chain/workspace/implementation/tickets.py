"""ServiceTicket lifecycle: manual open, list, dispatch (half-open window
calendar), resolve (doubles as the repair when chiller NEEDS_REPAIR). PRD 3.5."""
from flask import Blueprint, request

import cascade
from envelope import ok
from errors import ApiError
from serializers import ser_ticket
from state import DB, base_entity, touch
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("tickets", __name__)


def _get_ticket(tid):
    t = DB["tickets"].get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceTicket %s not found" % tid)
    return t


@bp.post("/cold-chain/service-tickets")
def create_ticket():
    uid, role = auth()
    v = fields(body(), [
        ("chiller_id", "str", True, {}),
        ("issue_summary", "str", True, {}),
    ])
    require_role(role, ["ServiceDispatcher", "StoreOperator"])
    if v["chiller_id"] not in DB["chillers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "chiller_id does not resolve")
    t = base_entity()
    t.update({
        "chiller_id": v["chiller_id"],
        "origin": "MANUAL",
        "issue_summary": v["issue_summary"],
        "status": "OPEN",
        "window_start": None,
        "window_end": None,
        "resolution_note": None,
    })
    DB["tickets"][t["id"]] = t
    return ok(ser_ticket(t), "object", 201)


@bp.get("/cold-chain/chillers/<cid>/service-tickets")
def list_tickets(cid):
    auth()
    limit, offset = pagination()
    if cid not in DB["chillers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Chiller %s not found" % cid)
    items = [t for t in DB["tickets"].values() if t["chiller_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_ticket(t) for t in sliced], "array", 200, meta)


@bp.post("/cold-chain/service-tickets/<tid>/dispatch")
def dispatch_ticket(tid):
    uid, role = auth()
    v = fields(body(), [
        ("window_start", "dt", True, {}),
        ("window_end", "dt", True, {}),
    ])
    require_role(role, ["ServiceDispatcher"])
    t = _get_ticket(tid)
    if t["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an OPEN ticket can be dispatched")
    if not v["window_end"] > v["window_start"]:
        raise ApiError("ERR_WINDOW_INVALID", 400,
                       "window_end must be strictly later than window_start")
    ws, we = v["window_start"], v["window_end"]
    # half-open [start, end): touching endpoints are NOT an overlap
    for o in DB["tickets"].values():
        if (o["id"] != t["id"] and o["chiller_id"] == t["chiller_id"]
                and o["status"] == "DISPATCHED"):
            if ws < o["window_end"] and o["window_start"] < we:
                raise ApiError("ERR_SERVICE_WINDOW_OVERLAP", 409,
                               "Window overlaps another DISPATCHED ticket on this chiller")
    t["window_start"] = ws
    t["window_end"] = we
    t["status"] = "DISPATCHED"
    touch(t)
    return ok(ser_ticket(t), "object", 200)


@bp.post("/cold-chain/service-tickets/<tid>/resolve")
def resolve_ticket(tid):
    uid, role = auth()
    v = fields(body(), [
        ("resolution_note", "str", True, {}),
    ])
    require_role(role, ["FieldTechnician"])
    t = _get_ticket(tid)
    if t["status"] not in ("OPEN", "DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN or DISPATCHED ticket can be resolved")
    t["status"] = "RESOLVED"
    t["resolution_note"] = v["resolution_note"]
    touch(t)
    # resolving a ticket on a NEEDS_REPAIR chiller performs the repair
    ch = DB["chillers"].get(t["chiller_id"])
    if ch is not None and ch["status"] == "NEEDS_REPAIR":
        cascade.repair_chiller(ch)
    return ok(ser_ticket(t), "object", 200)
