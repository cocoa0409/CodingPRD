"""Temperature telemetry: post readings (activation + severe-excursion cascade)
and list them (PRD 2.10, 3.5)."""
from flask import Blueprint

import calc
import cascade
from envelope import ok
from errors import ApiError
from serializers import ser_reading
from state import DB, new_id, next_seq, now, touch
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("readings", __name__)


def _active_placement_for_chiller(chiller_id):
    for p in DB["placements"].values():
        if p["chiller_id"] == chiller_id and p["status"] == "ACTIVE":
            return p
    return None


@bp.post("/cold-chain/chillers/<cid>/temperature-readings")
def post_reading(cid):
    uid, role = auth()
    v = fields(body(), [
        ("recorded_at", "dt", True, {"le_now": True}),
        ("temp_c", "num", True, {"min": -40.0, "max": 60.0}),
        ("duration_minutes", "int", True, {"min": 1, "max": 1440}),
    ])
    require_role(role, ["StoreOperator", "PlatformAdmin"])
    ch = DB["chillers"].get(cid)
    if ch is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Chiller %s not found" % cid)
    # tier 2 ownership: StoreOperator must own the chiller's ACTIVE placement store
    if role == "StoreOperator":
        pl = _active_placement_for_chiller(cid)
        if pl is None or pl["store_id"] != uid:
            raise ApiError("ERR_STORE_OWNERSHIP_MISMATCH", 403,
                           "StoreOperator may only post readings for their own store")
    # tier 4 state
    if ch["status"] not in ("INSTALLED", "ACTIVE", "NEEDS_REPAIR"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Readings require an INSTALLED, ACTIVE, or NEEDS_REPAIR chiller")
    temp = float(v["temp_c"])
    is_exc = temp < calc.CHILLER_TEMP_MIN_C or temp > calc.CHILLER_TEMP_MAX_C
    r = {
        "id": new_id(),
        "chiller_id": cid,
        "recorded_at": v["recorded_at"],
        "temp_c": v["temp_c"],
        "duration_minutes": v["duration_minutes"],
        "is_excursion": is_exc,
        "created_at": now(),
        "_seq": next_seq(),
    }
    DB["readings"].setdefault(cid, []).append(r)
    # automatic transition 1: first in-range reading activates an INSTALLED chiller
    if ch["status"] == "INSTALLED" and not is_exc:
        ch["status"] = "ACTIVE"
        touch(ch)
    # automatic transition 2: severe excursion degrades INSTALLED/ACTIVE chiller
    if (ch["status"] in ("INSTALLED", "ACTIVE")
            and calc.excursion_minutes_24h(ch) >= calc.EXCURSION_SEVERE_MINUTES):
        cascade.degrade_chiller(ch)
    return ok(ser_reading(r), "object", 201)


@bp.get("/cold-chain/chillers/<cid>/temperature-readings")
def list_readings(cid):
    auth()
    limit, offset = pagination()
    if cid not in DB["chillers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Chiller %s not found" % cid)
    items = list(DB["readings"].get(cid, []))
    items.sort(key=lambda r: (r["recorded_at"], r["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_reading(r) for r in sliced], "array", 200, meta)
