"""Brewers: registration into households, reads, and brew telemetry."""
from flask import Blueprint, request

from store import db, get_clock
from helpers import (
    ApiError, body, created, find, fmt_dt, init_common, list_ok, ok,
    require_roles, touch, v_int, v_str,
)
from calc import eval_brewer_lazy
from serializers import brewer_out

bp = Blueprint("brewers", __name__)


@bp.post("/households/<rid>/brewers")
@require_roles("PlatformAdmin")
def create_brewer(rid):
    hh = find("households", rid)
    b = body()
    raw_model = b.get("model_id")
    if isinstance(raw_model, str) and raw_model not in db["models"]:
        raise ApiError("ERR_NOT_FOUND", 404, "BrewerModel not found: %s" % raw_model)
    model_id = v_str(b, "model_id")
    serial = v_str(b, "serial_number")
    ts = fmt_dt(get_clock())
    brewer = init_common({
        "household_id": hh["id"],
        "model_id": model_id,
        "serial_number": serial,
        "registered_at": ts,
        "brew_count": 0,
        "last_brew_at": ts,
        "last_descaled_brew_count": 0,
        "warranty_status": "IN_WARRANTY",
        "operational": "ACTIVE",
    })
    db["brewers"][brewer["id"]] = brewer
    return created(brewer_out(brewer))


@bp.get("/brewers/<rid>")
@require_roles("PlatformAdmin", "SupportAgent")
def get_brewer(rid):
    brewer = find("brewers", rid)
    eval_brewer_lazy(brewer, persist=False)
    return ok(brewer_out(brewer))


@bp.get("/brewers")
@require_roles("PlatformAdmin", "SupportAgent")
def list_brewers():
    items = list(db["brewers"].values())
    for br in items:
        eval_brewer_lazy(br, persist=False)
    f_hh = request.args.get("household_id")
    f_model = request.args.get("model_id")
    f_op = request.args.get("operational")
    f_war = request.args.get("warranty_status")
    if f_hh is not None:
        items = [b for b in items if b["household_id"] == f_hh]
    if f_model is not None:
        items = [b for b in items if b["model_id"] == f_model]
    if f_op is not None:
        items = [b for b in items if b["operational"] == f_op]
    if f_war is not None:
        items = [b for b in items if b["warranty_status"] == f_war]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    return list_ok(items, brewer_out)


@bp.post("/brewers/<rid>/record-brews")
@require_roles("PlatformAdmin")
def record_brews(rid):
    brewer = find("brewers", rid)
    eval_brewer_lazy(brewer, persist=True)
    b = body()
    raw_variety = b.get("variety_id")
    if isinstance(raw_variety, str) and raw_variety not in db["varieties"]:
        raise ApiError("ERR_NOT_FOUND", 404, "PodVariety not found: %s" % raw_variety)
    brews = v_int(b, "brews", minv=1, maxv=10000)
    variety_id = v_str(b, "variety_id")
    variety = db["varieties"][variety_id]
    if variety["status"] == "DELISTED":
        raise ApiError("ERR_VARIETY_NOT_ACTIVE", 409,
                       "A DELISTED variety can no longer be recorded")
    model = db["models"].get(brewer["model_id"])
    brand = db["brands"].get(variety["brand_id"])
    if model is not None and model["firmware_compat"] == "RESTRICTIVE" \
            and brand is not None and brand["kind"] == "UNLICENSED_COMPATIBLE":
        raise ApiError("ERR_POD_BLOCKED", 422,
                       "RESTRICTIVE firmware refuses UNLICENSED_COMPATIBLE pods")
    if brewer["operational"] == "DECOMMISSIONED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A decommissioned brewer records nothing")
    brewer["brew_count"] += brews
    brewer["last_brew_at"] = fmt_dt(get_clock())
    if brewer["operational"] == "DORMANT":
        brewer["operational"] = "ACTIVE"
    touch(brewer)
    return ok(brewer_out(brewer))
