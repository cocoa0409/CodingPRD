"""Chiller fleet: batch registration (serial minting + capacity headroom),
fleet list/get, decommission (PRD 3.3)."""
from flask import Blueprint, request

import calc
from envelope import ok
from errors import ApiError
from serializers import ser_chiller
from state import DB, base_entity, touch
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("chillers", __name__)


def _get_chiller(cid):
    c = DB["chillers"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Chiller %s not found" % cid)
    return c


def _next_free_seq(prefix):
    """Next sequence for the prefix: 1 + max numeric suffix in use, else 1."""
    dash = prefix + "-"
    best = 0
    for c in DB["chillers"].values():
        s = c["serial_no"]
        if s.startswith(dash) and s[len(dash):].isdigit():
            best = max(best, int(s[len(dash):]))
    return best + 1


@bp.post("/cold-chain/chillers")
def create_chillers():
    uid, role = auth()
    v = fields(body(), [
        ("model", "enum", True, {"values": ["STANDARD", "COMPACT"]}),
        ("serial_prefix", "str", True, {}),
        ("quantity", "int", True, {"min": 1}),
        ("serial_start_seq", "int", False, {"min": 1}),
    ])
    require_role(role, ["ProductionPlanner"])
    prefix = v["serial_prefix"]
    qty = v["quantity"]
    start = v["serial_start_seq"] if "serial_start_seq" in v else _next_free_seq(prefix)
    serials = ["%s-%04d" % (prefix, start + i) for i in range(qty)]
    existing = {c["serial_no"] for c in DB["chillers"].values()}
    # state tier: serial uniqueness (atomic whole-batch rejection)
    if any(s in existing for s in serials):
        raise ApiError("ERR_SERIAL_NOT_UNIQUE", 409,
                       "Batch would mint a serial_no already in the fleet")
    # constraint tier: manufacturing headroom (atomic whole-batch rejection)
    if qty > calc.headroom():
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422,
                       "Batch quantity exceeds manufacturing headroom")
    made = []
    for s in serials:
        c = base_entity()
        c.update({
            "model": v["model"],
            "serial_no": s,
            "capacity_units": calc.CHILLER_CAPACITY[v["model"]],
            "footprint_sqft": calc.CHILLER_FOOTPRINT[v["model"]],
            "status": "IN_STOCK",
            "last_repair_at": None,
        })
        DB["chillers"][c["id"]] = c
        made.append(c)
    return ok([ser_chiller(c) for c in made], "array", 201)


@bp.get("/cold-chain/chillers")
def list_chillers():
    auth()
    limit, offset = pagination()
    items = list(DB["chillers"].values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    model = request.args.get("model")
    if model is not None:
        items = [c for c in items if c["model"] == model]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_chiller(c) for c in sliced], "array", 200, meta)


@bp.get("/cold-chain/chillers/<cid>")
def get_chiller(cid):
    auth()
    return ok(ser_chiller(_get_chiller(cid)), "object", 200)


@bp.post("/cold-chain/chillers/<cid>/decommission")
def decommission_chiller(cid):
    uid, role = auth()
    fields(body(), [])
    require_role(role, ["PlatformAdmin"])
    c = _get_chiller(cid)
    if c["status"] != "IN_STOCK":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_STOCK chiller can be decommissioned")
    c["status"] = "DECOMMISSIONED"
    touch(c)
    return ok(ser_chiller(c), "object", 200)
