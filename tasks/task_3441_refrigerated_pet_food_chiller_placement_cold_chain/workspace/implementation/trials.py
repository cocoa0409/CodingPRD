"""TrialCampaign: launch (closed-interval overlap BEFORE the 14-day gap rule,
gap boundary inclusive) and list with lazy COMPLETED (PRD 3.8)."""
from flask import Blueprint

import calc
import cascade
from envelope import ok
from errors import ApiError
from serializers import ser_campaign
from state import DB, base_entity
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("trials", __name__)


@bp.post("/cold-chain/stores/<sid>/trial-campaigns")
def create_campaign(sid):
    uid, role = auth()
    v = fields(body(), [
        ("name", "str", True, {}),
        ("start_date", "dt", True, {}),
        ("end_date", "dt", True, {}),
    ])
    if v["end_date"] < v["start_date"]:
        raise ApiError("ERR_VALIDATION", 400, "end_date must be on or after start_date")
    require_role(role, ["PlacementManager"])
    if sid not in DB["stores"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Store %s not found" % sid)
    # tier 4 state: the store must host at least one ACTIVE placement
    if not any(p["store_id"] == sid and p["status"] == "ACTIVE"
               for p in DB["placements"].values()):
        raise ApiError("ERR_PLACEMENT_NOT_ACTIVE", 409,
                       "Store has no ACTIVE placement")
    others = [c for c in DB["campaigns"].values() if c["store_id"] == sid]
    for c in others:
        cascade.materialize_campaign(c)
    # tier 6 temporal, intra-tier order: overlap first, then the 14-day gap
    s1, e1 = v["start_date"], v["end_date"]
    for c in others:
        if s1 <= c["end_date"] and c["start_date"] <= e1:
            raise ApiError("ERR_TRIAL_WINDOW_OVERLAP", 409,
                           "Trial window overlaps another campaign at this store")
    for c in others:
        if s1 > c["end_date"]:
            if (s1 - c["end_date"]).days < calc.TRIAL_MIN_GAP_DAYS:
                raise ApiError("ERR_TRIAL_GAP_VIOLATION", 422,
                               "Trial starts fewer than 14 days after a prior end_date")
        elif c["start_date"] > e1:
            if (c["start_date"] - e1).days < calc.TRIAL_MIN_GAP_DAYS:
                raise ApiError("ERR_TRIAL_GAP_VIOLATION", 422,
                               "Trial ends fewer than 14 days before another start_date")
    camp = base_entity()
    camp.update({
        "store_id": sid,
        "name": v["name"],
        "start_date": s1,
        "end_date": e1,
        "status": "ACTIVE",
    })
    DB["campaigns"][camp["id"]] = camp
    return ok(ser_campaign(camp), "object", 201)


@bp.get("/cold-chain/stores/<sid>/trial-campaigns")
def list_campaigns(sid):
    auth()
    limit, offset = pagination()
    if sid not in DB["stores"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Store %s not found" % sid)
    items = [c for c in DB["campaigns"].values() if c["store_id"] == sid]
    for c in items:
        cascade.materialize_campaign(c)
    items.sort(key=lambda c: (c["start_date"], c["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_campaign(c) for c in sliced], "array", 200, meta)
