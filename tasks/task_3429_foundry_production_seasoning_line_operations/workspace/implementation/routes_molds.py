"""Mold endpoints: preparation, shakeout, sand reclamation (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
from authz import authenticate, authorize
from errors import err
from validate import parse_body, validate, validate_no_fields

bp = Blueprint("molds", __name__)


@bp.route("/foundry/molds", methods=["POST"])
def create_mold():
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    vals = validate(
        parse_body(),
        [
            {"name": "production_order_id", "kind": "string"},
            {"name": "new_sand_pct", "kind": "number"},
            {"name": "reclaimed_sand_pct", "kind": "number"},
            {"name": "moisture_pct", "kind": "number"},
            {"name": "clay_pct", "kind": "number"},
            {"name": "sand_weight_lbs", "kind": "number", "gt": 0},
        ],
    )
    order = domain.get_or_404("orders", vals["production_order_id"])
    if order["state"] not in ("MOLDING", "POURING"):
        raise err("ERR_INVALID_STATE_TRANSITION", "order is not in MOLDING or POURING")
    _idx, _tier, posture = domain.order_derived(order)
    if posture == "FROZEN":
        raise err("ERR_ORDER_FROZEN", "order posture is FROZEN")
    if domain.permit_type_in_breach("SAND_RECLAMATION"):
        raise err("ERR_EMISSIONS_PERMIT_BREACH", "SAND_RECLAMATION permit is in BREACH")
    if abs(vals["new_sand_pct"] + vals["reclaimed_sand_pct"] - Decimal("100")) > Decimal("0.01"):
        raise err("ERR_SAND_MIX_VIOLATION", "new_sand_pct + reclaimed_sand_pct must equal 100.0")
    if vals["reclaimed_sand_pct"] > Decimal("85.0"):
        raise err("ERR_SAND_MIX_VIOLATION", "reclaimed_sand_pct must be <= 85.0")
    if not (Decimal("3.0") <= vals["moisture_pct"] <= Decimal("4.5")):
        raise err("ERR_SAND_MIX_VIOLATION", "moisture_pct must be within [3.0, 4.5]")
    if not (Decimal("8.0") <= vals["clay_pct"] <= Decimal("12.0")):
        raise err("ERR_SAND_MIX_VIOLATION", "clay_pct must be within [8.0, 12.0]")

    ent = store.make_entity()
    ent.update(
        {
            "production_order_id": order["id"],
            "new_sand_pct": vals["new_sand_pct"],
            "reclaimed_sand_pct": vals["reclaimed_sand_pct"],
            "moisture_pct": vals["moisture_pct"],
            "clay_pct": vals["clay_pct"],
            "sand_weight_lbs": vals["sand_weight_lbs"],
            "state": "PREPARED",
            "reclaimed_sand_lbs": None,
            "dust_collected_lbs": None,
            "reclaim_loss_lbs": None,
            "_reclaimed_at": None,
        }
    )
    store.db["molds"][ent["id"]] = ent
    return envelope.success(serialize.mold(ent), status=201)


@bp.route("/foundry/molds/<mid>/shakeout", methods=["POST"])
def shakeout_mold(mid):
    _uid, role = authenticate()
    authorize(role, ["MeltOperator"])
    validate_no_fields()
    mold = domain.get_or_404("molds", mid)
    if mold["state"] != "POURED":
        raise err("ERR_INVALID_STATE_TRANSITION", "mold is not POURED")
    if domain.permit_type_in_breach("DUST_CONTROL"):
        raise err("ERR_EMISSIONS_PERMIT_BREACH", "DUST_CONTROL permit is in BREACH")
    mold["state"] = "SHAKEOUT_DONE"
    for u in store.db["units"].values():
        if u["mold_id"] == mold["id"] and u["state"] == "POURED":
            u["state"] = "SHAKEOUT_DONE"
            store.touch(u)
    store.touch(mold)
    return envelope.success(serialize.mold(mold))


@bp.route("/foundry/molds/<mid>/reclaim", methods=["POST"])
def reclaim_mold(mid):
    uid, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    vals = validate(
        parse_body(),
        [
            {"name": "reclaimed_sand_lbs", "kind": "number", "ge": 0},
            {"name": "dust_collected_lbs", "kind": "number", "ge": 0},
        ],
    )
    mold = domain.get_or_404("molds", mid)
    if mold["state"] != "SHAKEOUT_DONE":
        raise err("ERR_INVALID_STATE_TRANSITION", "mold is not SHAKEOUT_DONE")
    sand = calc.D(mold["sand_weight_lbs"])
    if vals["reclaimed_sand_lbs"] + vals["dust_collected_lbs"] > sand:
        raise err("ERR_SAND_LOSS_EXCEEDED", "reclaimed + dust exceeds sand_weight_lbs")
    loss = sand - vals["reclaimed_sand_lbs"] - vals["dust_collected_lbs"]
    if loss > calc.SAND_LOSS_MAX_PCT * sand:
        raise err("ERR_SAND_LOSS_EXCEEDED", "reclaim loss exceeds 12% of sand_weight_lbs")

    mold["reclaimed_sand_lbs"] = vals["reclaimed_sand_lbs"]
    mold["dust_collected_lbs"] = vals["dust_collected_lbs"]
    mold["reclaim_loss_lbs"] = loss
    mold["state"] = "SAND_RECLAIMED"
    mold["_reclaimed_at"] = store.now()
    store.touch(mold)

    rate = domain.current_sand_rate()
    if rate is not None:
        for p in domain.permits_of_type("SAND_RECLAMATION"):
            limit = calc.D(p["limit_value"])
            if rate < limit - calc.SAND_RATE_BREACH_MARGIN:
                domain.breach_permit(p, uid, hold_melts=True)
            elif rate < limit and p["status"] == "ACTIVE":
                p["status"] = "WARNING"
                store.touch(p)
    return envelope.success(serialize.mold(mold))
