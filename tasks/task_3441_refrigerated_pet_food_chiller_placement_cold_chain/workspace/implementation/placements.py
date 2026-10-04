"""Placements: install (heavily gated), list/get, evaluate-performance,
retire (REMOVE / RELOCATE). PRD 3.4 and 3.6; validation tiers per 2.7."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import cascade
from envelope import ok
from errors import ApiError
from serializers import ser_placement
from state import DB, base_entity, now, touch
from validate import auth, body, fields, page, pagination, require_role

bp = Blueprint("placements", __name__)


def _get_placement(pid):
    p = DB["placements"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Placement %s not found" % pid)
    return p


def _latest_eval(store_id):
    evs = [e for e in DB["evaluations"].values() if e["store_id"] == store_id]
    if not evs:
        return None
    evs.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return evs[-1]


def _active_placement_at(store_id):
    for p in DB["placements"].values():
        if p["store_id"] == store_id and p["status"] == "ACTIVE":
            return p
    return None


def _eval_stale(ev):
    return (ev is not None
            and now() - ev["created_at"] > timedelta(days=calc.EVALUATION_STALENESS_DAYS))


def _new_placement(store, chiller, agreement, evaluation):
    """Placement born ACTIVE / PENDING / OK with plan fields from the governing
    evaluation's forecast and a snapshot install quote (PRD 3.4)."""
    velocity = evaluation["forecast_weekly_units"]
    quote = calc.install_quote(chiller["model"], agreement["allocated_sqft"],
                               store["distance_miles_from_plant"])
    p = base_entity()
    p.update({
        "store_id": store["id"],
        "chiller_id": chiller["id"],
        "agreement_id": agreement["id"],
        "status": "ACTIVE",
        "performance_status": "PENDING",
        "operational_status": "OK",
        "underperforming_streak": 0,
        "standing_deliveries_per_week": calc.delivery_tier(velocity),
        "safety_stock_units": calc.safety_stock_units(velocity, chiller["capacity_units"]),
        "installed_quote_cents": quote,
        "last_reported_weekly_units": None,
        "payback_actuals_months": None,
        "retired_reason": None,
        "relocated_to_placement_id": None,
    })
    DB["placements"][p["id"]] = p
    return p


@bp.post("/cold-chain/placements")
def create_placement():
    uid, role = auth()
    v = fields(body(), [
        ("store_id", "str", True, {}),
        ("agreement_id", "str", True, {}),
        ("chiller_id", "str", True, {}),
        ("expected_agreement_version", "int", True, {}),
    ])
    require_role(role, ["PlacementManager"])
    # tier 3 existence, body field order: store_id, agreement_id, chiller_id
    store = DB["stores"].get(v["store_id"])
    if store is None:
        raise ApiError("ERR_NOT_FOUND", 404, "store_id does not resolve")
    agr = DB["agreements"].get(v["agreement_id"])
    if agr is None:
        raise ApiError("ERR_NOT_FOUND", 404, "agreement_id does not resolve")
    ch = DB["chillers"].get(v["chiller_id"])
    if ch is None:
        raise ApiError("ERR_NOT_FOUND", 404, "chiller_id does not resolve")
    # tier 4 state (PRD 3.4 gate order), then OCC in the same tier
    if agr["status"] != "SIGNED":
        raise ApiError("ERR_AGREEMENT_NOT_SIGNED", 409, "Agreement is not SIGNED")
    if ch["status"] != "IN_STOCK":
        raise ApiError("ERR_CHILLER_NOT_IN_STOCK", 409, "Chiller is not IN_STOCK")
    if _active_placement_at(store["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_PLACEMENT", 409,
                       "Store already has an ACTIVE placement")
    if v["expected_agreement_version"] != agr["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_agreement_version does not match current version")
    # tier 6 temporal: latest evaluation freshness (90 days, boundary inclusive)
    ev = _latest_eval(store["id"])
    if _eval_stale(ev):
        raise ApiError("ERR_EVALUATION_STALE", 422,
                       "Latest site evaluation is older than 90 days")
    # tier 7 constraint: chiller footprint fits the negotiated allocation
    if calc.CHILLER_FOOTPRINT[ch["model"]] > agr["allocated_sqft"]:
        raise ApiError("ERR_STORE_FOOTPRINT_INSUFFICIENT", 422,
                       "Chiller footprint exceeds the agreement's allocated_sqft")
    # tier 8 referential: placement store must equal the agreement's store
    if agr["store_id"] != store["id"]:
        raise ApiError("ERR_AGREEMENT_STORE_MISMATCH", 422,
                       "Agreement does not belong to the named store")
    # tier 9 fiscal: capex ceiling, then payback eligibility
    quote = calc.install_quote(ch["model"], agr["allocated_sqft"],
                               store["distance_miles_from_plant"])
    if quote > agr["max_capex_cents"]:
        raise ApiError("ERR_CAPEX_BUDGET_EXCEEDED", 422,
                       "Install quote exceeds the agreement's max_capex_cents")
    if ev is None or ev["verdict"] != "ELIGIBLE":
        raise ApiError("ERR_PAYBACK_INELIGIBLE", 422,
                       "Latest site evaluation is not ELIGIBLE")
    # effects: placement created; chiller IN_STOCK -> INSTALLED; agreement -> ACTIVE
    p = _new_placement(store, ch, agr, ev)
    ch["status"] = "INSTALLED"
    touch(ch)
    agr["status"] = "ACTIVE"
    touch(agr)
    return ok(ser_placement(p), "object", 201)


@bp.get("/cold-chain/placements")
def list_placements():
    auth()
    limit, offset = pagination()
    items = list(DB["placements"].values())
    for f in ("store_id", "chiller_id", "agreement_id", "status",
              "relocated_to_placement_id"):
        val = request.args.get(f)
        if val is not None:
            items = [p for p in items if p.get(f) == val]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    sliced, meta = page(items, limit, offset)
    return ok([ser_placement(p) for p in sliced], "array", 200, meta)


@bp.get("/cold-chain/placements/<pid>")
def get_placement(pid):
    auth()
    return ok(ser_placement(_get_placement(pid)), "object", 200)


@bp.post("/cold-chain/placements/<pid>/evaluate-performance")
def evaluate_performance(pid):
    uid, role = auth()
    v = fields(body(), [
        ("trailing_weekly_units", "int", True, {"min": 0}),
    ])
    require_role(role, ["PlacementManager"])
    p = _get_placement(pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_NOT_ACTIVE", 409, "Placement is not ACTIVE")
    tw = v["trailing_weekly_units"]
    # underperformance tracker (floor 40, boundary inclusive)
    if tw >= calc.VELOCITY_FLOOR_UNITS_PER_WEEK:
        p["performance_status"] = "PERFORMING"
        p["underperforming_streak"] = 0
    else:
        p["performance_status"] = "UNDERPERFORMING"
        p["underperforming_streak"] += 1
    p["last_reported_weekly_units"] = tw
    ch = DB["chillers"].get(p["chiller_id"])
    capacity = ch["capacity_units"] if ch is not None else 0
    p["standing_deliveries_per_week"] = calc.delivery_tier(tw)
    p["safety_stock_units"] = calc.safety_stock_units(tw, capacity)
    pb = calc.payback_months(tw, p["installed_quote_cents"])
    p["payback_actuals_months"] = float(pb) if pb is not None else None
    touch(p)
    return ok(ser_placement(p), "object", 200)


@bp.post("/cold-chain/placements/<pid>/retire")
def retire_placement_endpoint(pid):
    uid, role = auth()
    v = fields(body(), [
        ("mode", "enum", True, {"values": ["REMOVE", "RELOCATE"]}),
        ("removal_reason", "enum", False,
         {"values": ["UNDERPERFORMANCE_REMOVAL", "AGREEMENT_TERMINATION", "RELOCATION"]}),
        ("target_store_id", "str", False, {}),
        ("target_agreement_id", "str", False, {}),
    ])
    require_role(role, ["PlacementManager"])
    p = _get_placement(pid)
    mode = v["mode"]
    # tier 3 existence of supplied target references (RELOCATE only), field order
    tstore = None
    tagr = None
    if mode == "RELOCATE":
        if "target_store_id" in v:
            tstore = DB["stores"].get(v["target_store_id"])
            if tstore is None:
                raise ApiError("ERR_NOT_FOUND", 404, "target_store_id does not resolve")
        if "target_agreement_id" in v:
            tagr = DB["agreements"].get(v["target_agreement_id"])
            if tagr is None:
                raise ApiError("ERR_NOT_FOUND", 404, "target_agreement_id does not resolve")
    # tier 4 state
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_NOT_ACTIVE", 409, "Placement is not ACTIVE")
    if mode == "REMOVE":
        if v.get("removal_reason") == "UNDERPERFORMANCE_REMOVAL":
            if not (p["performance_status"] == "UNDERPERFORMING"
                    and p["underperforming_streak"]
                    >= calc.UNDERPERFORMING_STREAK_REMOVAL_MIN):
                raise ApiError("ERR_UNDERPERFORMANCE_STREAK_INSUFFICIENT", 409,
                               "UNDERPERFORMANCE_REMOVAL requires UNDERPERFORMING "
                               "status with streak >= 2")
    else:
        if tagr is not None and tagr["status"] != "SIGNED":
            raise ApiError("ERR_AGREEMENT_NOT_SIGNED", 409,
                           "Target agreement is not SIGNED")
    ch = DB["chillers"].get(p["chiller_id"])
    tev = None
    if mode == "RELOCATE" and tstore is not None:
        tev = _latest_eval(tstore["id"])
        # tier 6 temporal: target evaluation freshness
        if _eval_stale(tev):
            raise ApiError("ERR_EVALUATION_STALE", 422,
                           "Target store's latest site evaluation is stale")
        # tier 7 constraint: chiller footprint fits target allocation
        if (tagr is not None and ch is not None
                and calc.CHILLER_FOOTPRINT[ch["model"]] > tagr["allocated_sqft"]):
            raise ApiError("ERR_STORE_FOOTPRINT_INSUFFICIENT", 422,
                           "Chiller footprint exceeds the target allocated_sqft")
    # tier 8 referential
    if mode == "REMOVE":
        if "removal_reason" not in v:
            raise ApiError("ERR_RETIRE_TARGET_INVALID", 422,
                           "removal_reason is required for mode REMOVE")
    else:
        if "target_store_id" not in v or "target_agreement_id" not in v:
            raise ApiError("ERR_RETIRE_TARGET_INVALID", 422,
                           "target_store_id and target_agreement_id are required "
                           "for mode RELOCATE")
        if v["target_store_id"] == p["store_id"]:
            raise ApiError("ERR_RETIRE_TARGET_INVALID", 422,
                           "Target store must differ from the current store")
        if tagr["store_id"] != tstore["id"]:
            raise ApiError("ERR_AGREEMENT_STORE_MISMATCH", 422,
                           "Target agreement does not belong to the target store")
        # tier 9 fiscal: capex ceiling then payback eligibility at the target
        quote = calc.install_quote(ch["model"], tagr["allocated_sqft"],
                                   tstore["distance_miles_from_plant"])
        if quote > tagr["max_capex_cents"]:
            raise ApiError("ERR_CAPEX_BUDGET_EXCEEDED", 422,
                           "Install quote exceeds the target max_capex_cents")
        if tev is None or tev["verdict"] != "ELIGIBLE":
            raise ApiError("ERR_PAYBACK_INELIGIBLE", 422,
                           "Target store's latest site evaluation is not ELIGIBLE")
    # effects
    if mode == "REMOVE":
        cascade.retire_placement(p, v["removal_reason"])
    else:
        # RELOCATE: successor placement at target under the same chiller; the
        # chiller passes through IN_STOCK logically with a single net version +1
        newp = _new_placement(tstore, ch, tagr, tev)
        p["status"] = "RETIRED"
        p["retired_reason"] = "RELOCATION"
        p["relocated_to_placement_id"] = newp["id"]
        touch(p)
        ch["status"] = "INSTALLED"
        touch(ch)
        cascade.cancel_open_tickets(ch["id"])
        tagr["status"] = "ACTIVE"
        touch(tagr)
    return ok(ser_placement(p), "object", 200)
