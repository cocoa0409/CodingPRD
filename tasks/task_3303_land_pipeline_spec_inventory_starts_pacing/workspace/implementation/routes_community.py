"""Routes: communities, product series, pacing plans, homes, pacing summary."""

from flask import Blueprint, request

from db import db, iso3
from errors import ApiError
from helpers import (
    auth, require_role, body, idem_begin, require_fields, dt_field,
    opt_integer, fresh_row, touch, get_or_404, clock, dt_or_none,
)
from response import success_obj, success_list
import services as svc

bp = Blueprint("community", __name__)

PHASE_NEXT = {
    "OPEN_FOR_SALES": "SELLING_OUT",
    "SELLING_OUT": "CLOSE_OUT",
    "CLOSE_OUT": "CLOSED",
}

SERIES_CODES = ["EXPRESS", "CLASSIC", "VENTURE", "FREEDOM"]


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------

@bp.post("/communities")
def create_community():
    role, _ = auth()
    ctx = idem_begin()
    require_role(role, ["DIVISION_PRESIDENT"])
    b = body()
    require_fields(b, [
        ("name", "string", None, False),
        ("market_code", "string", None, False),
        ("absorption_target_per_month", "number", None, False),
        ("months_supply_target", "number", None, False),
    ])
    row = fresh_row()
    row.update({
        "name": b["name"],
        "market_code": b["market_code"],
        "absorption_target_per_month": b["absorption_target_per_month"],
        "months_supply_target": b["months_supply_target"],
        "phase": "PLANNING",
    })
    db.communities[row["id"]] = row
    return success_obj(svc.ser_community(row), status=201)


@bp.get("/communities/<cid>")
def get_community(cid):
    auth()
    c = get_or_404(db.communities, cid)
    return success_obj(svc.ser_community(c))


@bp.post("/communities/<cid>/open")
def open_community(cid):
    role, _ = auth()
    ctx = idem_begin()
    c = get_or_404(db.communities, cid)
    require_role(role, ["COMMUNITY_MANAGER"])
    body()
    if c["phase"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Community is not in PLANNING")
    c["phase"] = "OPEN_FOR_SALES"
    touch(c)
    return success_obj(svc.ser_community(c))


@bp.post("/communities/<cid>/advance-phase")
def advance_phase(cid):
    role, _ = auth()
    ctx = idem_begin()
    c = get_or_404(db.communities, cid)
    require_role(role, ["DIVISION_PRESIDENT"])
    body()
    nxt = PHASE_NEXT.get(c["phase"])
    if nxt is None:
        raise ApiError(
            "ERR_INVALID_PHASE_TRANSITION", 409,
            "Cannot advance phase from " + c["phase"],
        )
    c["phase"] = nxt
    touch(c)
    # Entering CLOSE_OUT raises the incentive cap; recompute home stacks.
    svc.refresh_community_home_pricing(c["id"])
    return success_obj(svc.ser_community(c))


# ---------------------------------------------------------------------------
# Product series
# ---------------------------------------------------------------------------

@bp.post("/communities/<cid>/product-series")
def create_product_series(cid):
    role, _ = auth()
    ctx = idem_begin()
    c = get_or_404(db.communities, cid)
    require_role(role, ["COMMUNITY_MANAGER"])
    b = body()
    require_fields(b, [
        ("series_code", "string", SERIES_CODES, False),
        ("min_price_cents", "integer", None, False),
        ("max_price_cents", "integer", None, False),
    ])
    for ps in db.product_series.values():
        if ps["community_id"] != cid:
            continue
        if b["min_price_cents"] <= ps["max_price_cents"] and ps["min_price_cents"] <= b["max_price_cents"]:
            raise ApiError(
                "ERR_SERIES_BAND_OVERLAP", 422,
                "Price band overlaps an existing series in this community",
            )
    row = fresh_row()
    row.update({
        "community_id": cid,
        "series_code": b["series_code"],
        "min_price_cents": b["min_price_cents"],
        "max_price_cents": b["max_price_cents"],
    })
    db.product_series[row["id"]] = row
    return success_obj(svc.ser_product_series(row), status=201)


@bp.get("/communities/<cid>/product-series")
def list_product_series(cid):
    auth()
    get_or_404(db.communities, cid)
    items = [p for p in db.product_series.values() if p["community_id"] == cid]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return success_list([svc.ser_product_series(p) for p in items])


@bp.get("/product-series/<pid>")
def get_product_series(pid):
    auth()
    ps = get_or_404(db.product_series, pid)
    return success_obj(svc.ser_product_series(ps))


# ---------------------------------------------------------------------------
# Pacing plans
# ---------------------------------------------------------------------------

@bp.post("/communities/<cid>/pacing-plans")
def create_pacing_plan(cid):
    role, _ = auth()
    ctx = idem_begin()
    c = get_or_404(db.communities, cid)
    require_role(role, ["DIVISION_PRESIDENT"])
    b = body()
    require_fields(b, [
        ("period_start", "datetime", None, False),
        ("period_end", "datetime", None, False),
        ("max_starts", "integer", None, False),
        ("expected_community_version", "integer", None, False),
    ])
    if b["expected_community_version"] != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_community_version is stale")
    # Supersede the currently PUBLISHED plan for this community.
    for p in db.pacing_plans.values():
        if p["community_id"] == cid and p["state"] == "PUBLISHED":
            p["state"] = "SUPERSEDED"
            touch(p)
    row = fresh_row()
    row.update({
        "community_id": cid,
        "period_start": iso3(dt_field(b, "period_start")),
        "period_end": iso3(dt_field(b, "period_end")),
        "max_starts": b["max_starts"],
        "state": "PUBLISHED",
    })
    db.pacing_plans[row["id"]] = row
    touch(c)
    return success_obj(svc.ser_pacing_plan(row), status=201)


@bp.get("/communities/<cid>/pacing-plans")
def list_pacing_plans(cid):
    auth()
    get_or_404(db.communities, cid)
    items = [p for p in db.pacing_plans.values() if p["community_id"] == cid]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return success_list([svc.ser_pacing_plan(p) for p in items])


# ---------------------------------------------------------------------------
# Lots
# ---------------------------------------------------------------------------

@bp.get("/communities/<cid>/lots")
def list_lots(cid):
    auth()
    get_or_404(db.communities, cid)
    items = [l for l in db.lots.values() if l["community_id"] == cid]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return success_list([svc.ser_lot(l) for l in items])


# ---------------------------------------------------------------------------
# Homes
# ---------------------------------------------------------------------------

@bp.post("/communities/<cid>/homes")
def create_home(cid):
    role, _ = auth()
    ctx = idem_begin()
    c = get_or_404(db.communities, cid)
    require_role(role, ["COMMUNITY_MANAGER"])
    b = body()
    require_fields(b, [
        ("lot_id", "string", None, False),
        ("product_series_id", "string", None, False),
        ("base_price_cents", "integer", None, False),
    ])
    lot_premium = opt_integer(b, "lot_premium_cents", 0)

    # 6: community phase gate
    if c["phase"] not in ("OPEN_FOR_SALES", "SELLING_OUT"):
        raise ApiError(
            "ERR_COMMUNITY_NOT_OPEN", 409,
            "Community phase does not allow starts",
        )

    # Referenced entities must exist
    lot = get_or_404(db.lots, b["lot_id"])
    ps = get_or_404(db.product_series, b["product_series_id"])

    # 7: business-referential
    if lot["community_id"] != cid or lot["state"] != "BANKED":
        raise ApiError("ERR_LOT_NOT_AVAILABLE", 409, "Lot is not BANKED in this community")
    plan = svc.current_published_plan(cid)
    if plan is None:
        raise ApiError(
            "ERR_NO_PUBLISHED_PACING_PLAN", 409,
            "No PUBLISHED pacing plan covers the clock",
        )

    # 9: price within series band (gross = base + premium)
    gross = b["base_price_cents"] + lot_premium
    if gross < ps["min_price_cents"] or gross > ps["max_price_cents"]:
        raise ApiError(
            "ERR_PRICE_OUT_OF_SERIES_BAND", 422,
            "Home gross price is outside its series band",
        )

    # 10: fiscal gates
    _, _, _, _, posture = svc.posture_of(cid)
    if posture == "OVERHELD":
        raise ApiError(
            "ERR_STARTS_BLOCKED_OVERHELD", 409,
            "Community posture is OVERHELD",
        )
    quota = max(0, plan["max_starts"] - svc.starts_this_period(cid))
    if quota <= 0:
        raise ApiError("ERR_STARTS_QUOTA_EXCEEDED", 409, "Pacing quota exhausted")
    commitment = svc.select_framing_commitment(cid)
    if commitment is None:
        raise ApiError(
            "ERR_NO_CAPACITY_REMAINING", 409,
            "No FRAMING commitment with remaining capacity",
        )

    # Create the home
    row = fresh_row()
    row.update({
        "community_id": cid,
        "lot_id": lot["id"],
        "product_series_id": ps["id"],
        "base_price_cents": b["base_price_cents"],
        "lot_premium_cents": lot_premium,
        "build_stage": "PERMITTED",
        "sales_status": "UNSOLD",
        "completed_at": None,
        "cycle_time_days": None,
        "capacity_commitment_id": commitment["id"],
    })
    row.update(svc.compute_home_pricing(row))
    db.homes[row["id"]] = row

    # Side effects
    lot["state"] = "CONSUMED"
    touch(lot)
    commitment["allocated_units"] += 1
    touch(commitment)
    touch(c)

    return success_obj(svc.ser_home(row), status=201)


@bp.get("/communities/<cid>/homes")
def list_community_homes(cid):
    auth()
    get_or_404(db.communities, cid)
    items = [h for h in db.homes.values() if h["community_id"] == cid]
    items.sort(key=lambda h: (h["created_at"], h["id"]))
    return success_list([svc.ser_home(h) for h in items])


@bp.get("/homes")
def list_homes():
    auth()
    items = list(db.homes.values())
    for param in ("lot_id", "community_id", "product_series_id", "sales_status"):
        v = request.args.get(param)
        if v is not None:
            items = [h for h in items if h.get(param) == v]
    items.sort(key=lambda h: (h["created_at"], h["id"]))
    for h in items:
        h.update(svc.compute_home_pricing(h))
    return success_list([svc.ser_home(h) for h in items])


@bp.get("/homes/<hid>")
def get_home(hid):
    auth()
    h = get_or_404(db.homes, hid)
    # Incentive status is computed from the clock; refresh the stored pricing
    # snapshot so reads reflect activations/expiries since the last write.
    h.update(svc.compute_home_pricing(h))
    return success_obj(svc.ser_home(h))


STAGE_NEXT = {
    "PERMITTED": "FOUNDATION",
    "FOUNDATION": "FRAME",
    "FRAME": "DRYWALL",
    "DRYWALL": "COMPLETE",
}


@bp.post("/homes/<hid>/advance-stage")
def advance_stage(hid):
    role, _ = auth()
    ctx = idem_begin()
    h = get_or_404(db.homes, hid)
    require_role(role, ["COMMUNITY_MANAGER"])
    body()
    nxt = STAGE_NEXT.get(h["build_stage"])
    if nxt is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Home build_stage cannot advance from " + h["build_stage"],
        )
    h["build_stage"] = nxt
    if nxt == "COMPLETE":
        now = clock()
        h["completed_at"] = iso3(now)
        created = dt_or_none(h["created_at"])
        h["cycle_time_days"] = int((now - created).total_seconds() // 86400)
        # Release the FRAMING capacity allocation back to the funding commitment
        cc_id = h.get("capacity_commitment_id")
        cc = db.capacity_commitments.get(cc_id) if cc_id else None
        if cc is not None and cc["allocated_units"] > 0:
            cc["allocated_units"] -= 1
            touch(cc)
    h.update(svc.compute_home_pricing(h))
    touch(h)
    return success_obj(svc.ser_home(h))


@bp.get("/homes/<hid>/sales-contracts")
def list_home_sales_contracts(hid):
    auth()
    get_or_404(db.homes, hid)
    items = [s for s in db.sales_contracts.values() if s["home_id"] == hid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return success_list([svc.ser_sales_contract(s) for s in items])


# ---------------------------------------------------------------------------
# Incentives (community-scoped list lives here)
# ---------------------------------------------------------------------------

@bp.get("/communities/<cid>/incentives")
def list_community_incentives(cid):
    auth()
    get_or_404(db.communities, cid)
    items = [i for i in db.incentives.values() if i["community_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if svc.incentive_status(i) == status]
    itype = request.args.get("type")
    if itype is not None:
        items = [i for i in items if i["type"] == itype]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    return success_list([svc.ser_incentive(i) for i in items])


# ---------------------------------------------------------------------------
# Capacity commitments (community-scoped list)
# ---------------------------------------------------------------------------

@bp.get("/communities/<cid>/capacity-commitments")
def list_community_commitments(cid):
    auth()
    get_or_404(db.communities, cid)
    items = [c for c in db.capacity_commitments.values() if c["community_id"] == cid]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return success_list([svc.ser_capacity_commitment(c) for c in items])


# ---------------------------------------------------------------------------
# Pacing summary
# ---------------------------------------------------------------------------

@bp.get("/communities/<cid>/pacing-summary")
def pacing_summary(cid):
    auth()
    c = get_or_404(db.communities, cid)
    standing, trailing, forward, mos, posture = svc.posture_of(cid)
    msr, halted = svc.starts_authorization(cid)
    # avg cycle time over COMPLETE/CLOSED homes
    times = [
        h["cycle_time_days"]
        for h in db.homes.values()
        if h["community_id"] == cid
        and h["build_stage"] in ("COMPLETE", "CLOSED")
        and h.get("cycle_time_days") is not None
    ]
    if times:
        from decimal import Decimal, ROUND_HALF_UP
        avg = Decimal(sum(times)) / Decimal(len(times))
        avg_cycle = float(avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        avg_cycle = 0.0
    data = {
        "trailing_absorption_rate": trailing,
        "forward_pace_rate": forward,
        "months_of_supply": mos,
        "posture": posture,
        "standing_spec_count": standing,
        "starts_this_period": svc.starts_this_period(cid),
        "max_starts_remaining": msr,
        "starts_halted": halted,
        "avg_cycle_time_days": avg_cycle,
    }
    return success_obj(data)
