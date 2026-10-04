"""Routes: land parcels, option contracts, takedowns."""

from flask import Blueprint, request

from db import db, iso3
from errors import ApiError
from helpers import (
    auth, require_role, body, idem_begin, require_fields, dt_field,
    fresh_row, touch, get_or_404, clock, dt_or_none,
)
from response import success_obj, success_list
import services as svc

bp = Blueprint("land", __name__)

ALL_ROLES = ["DIVISION_PRESIDENT", "LAND_MANAGER", "COMMUNITY_MANAGER", "SALES_AGENT", "TRADE_PARTNER"]


@bp.post("/land-parcels")
def create_land_parcel():
    role, _ = auth()
    ctx = idem_begin()
    require_role(role, ["LAND_MANAGER"])
    b = body()
    require_fields(b, [
        ("name", "string", None, False),
        ("market_code", "string", None, False),
        ("acres", "number", None, False),
    ])
    row = fresh_row()
    row.update({
        "name": b["name"],
        "market_code": b["market_code"],
        "acres": b["acres"],
    })
    db.land_parcels[row["id"]] = row
    return success_obj(svc.ser_land_parcel(row), status=201)


# ---------------------------------------------------------------------------
# Option contracts
# ---------------------------------------------------------------------------

@bp.post("/option-contracts")
def create_option_contract():
    role, _ = auth()
    ctx = idem_begin()
    require_role(role, ["LAND_MANAGER"])
    b = body()
    require_fields(b, [
        ("land_parcel_id", "string", None, False),
        ("option_fee_cents", "integer", None, False),
        ("earnest_money_cents", "integer", None, False),
        ("total_lots", "integer", None, False),
        ("lot_base_price_cents", "integer", None, False),
    ])
    get_or_404(db.land_parcels, b["land_parcel_id"])
    row = fresh_row()
    row.update({
        "land_parcel_id": b["land_parcel_id"],
        "option_fee_cents": b["option_fee_cents"],
        "earnest_money_cents": b["earnest_money_cents"],
        "total_lots": b["total_lots"],
        "lot_base_price_cents": b["lot_base_price_cents"],
        "state": "DRAFT",
        "executed_at": None,
        "lots_taken_down": 0,
    })
    db.option_contracts[row["id"]] = row
    return success_obj(svc.ser_option_contract(row), status=201)


@bp.get("/option-contracts")
def list_option_contracts():
    auth()
    svc.apply_lazy_defaults()
    items = list(db.option_contracts.values())
    parcel_id = request.args.get("land_parcel_id")
    if parcel_id is not None:
        items = [o for o in items if o["land_parcel_id"] == parcel_id]
    state = request.args.get("state")
    if state is not None:
        items = [o for o in items if o["state"] == state]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    return success_list([svc.ser_option_contract(o) for o in items])


@bp.get("/option-contracts/<cid>")
def get_option_contract(cid):
    auth()
    svc.apply_lazy_defaults()
    oc = get_or_404(db.option_contracts, cid)
    return success_obj(svc.ser_option_contract(oc))


@bp.post("/option-contracts/<cid>/execute")
def execute_option_contract(cid):
    role, _ = auth()
    ctx = idem_begin()
    oc = get_or_404(db.option_contracts, cid)
    require_role(role, ["LAND_MANAGER"])
    body()
    svc.apply_lazy_defaults()
    if oc["state"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not in DRAFT")
    oc["state"] = "ACTIVE"
    oc["executed_at"] = iso3(clock())
    touch(oc)
    return success_obj(svc.ser_option_contract(oc))


@bp.post("/option-contracts/<cid>/cure")
def cure_option_contract(cid):
    role, _ = auth()
    ctx = idem_begin()
    oc = get_or_404(db.option_contracts, cid)
    require_role(role, ["LAND_MANAGER"])
    body()
    svc.apply_lazy_defaults()
    if oc["state"] != "DEFAULTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not DEFAULTED")
    oc["state"] = "ACTIVE"
    touch(oc)
    return success_obj(svc.ser_option_contract(oc))


# ---------------------------------------------------------------------------
# Takedowns
# ---------------------------------------------------------------------------

@bp.post("/option-contracts/<cid>/takedowns")
def create_takedown(cid):
    role, _ = auth()
    ctx = idem_begin()
    oc = get_or_404(db.option_contracts, cid)
    require_role(role, ["LAND_MANAGER"])
    b = body()
    require_fields(b, [
        ("community_id", "string", None, False),
        ("lot_count", "integer", None, False),
        ("window_start", "datetime", None, False),
        ("window_end", "datetime", None, False),
        ("expected_contract_version", "integer", None, False),
    ])
    community = get_or_404(db.communities, b["community_id"])
    svc.apply_lazy_defaults()
    if b["expected_contract_version"] != oc["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_contract_version is stale")
    if oc["lots_taken_down"] + b["lot_count"] > oc["total_lots"]:
        raise ApiError(
            "ERR_CONTRACT_EXHAUSTED", 409,
            "Takedown would exceed total_lots",
        )
    row = fresh_row()
    row.update({
        "option_contract_id": oc["id"],
        "community_id": community["id"],
        "lot_count": b["lot_count"],
        "window_start": iso3(dt_field(b, "window_start")),
        "window_end": iso3(dt_field(b, "window_end")),
        "state": "SCHEDULED",
        "executed_at": None,
        "escalated_lot_price_cents": None,
        "credit_per_lot_cents": None,
        "net_due_per_lot_cents": None,
        "total_net_due_cents": None,
    })
    db.takedowns[row["id"]] = row
    touch(oc)
    return success_obj(svc.ser_takedown(row), status=201)


@bp.get("/option-contracts/<cid>/takedowns")
def list_contract_takedowns(cid):
    auth()
    get_or_404(db.option_contracts, cid)
    svc.apply_lazy_defaults()
    items = [t for t in db.takedowns.values() if t["option_contract_id"] == cid]
    community_id = request.args.get("community_id")
    if community_id is not None:
        items = [t for t in items if t["community_id"] == community_id]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return success_list([svc.ser_takedown(t) for t in items])


@bp.get("/takedowns")
def list_takedowns():
    auth()
    svc.apply_lazy_defaults()
    items = list(db.takedowns.values())
    community_id = request.args.get("community_id")
    if community_id is not None:
        items = [t for t in items if t["community_id"] == community_id]
    contract_id = request.args.get("option_contract_id")
    if contract_id is not None:
        items = [t for t in items if t["option_contract_id"] == contract_id]
    state = request.args.get("state")
    if state is not None:
        items = [t for t in items if t["state"] == state]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return success_list([svc.ser_takedown(t) for t in items])


@bp.get("/takedowns/<tid>")
def get_takedown(tid):
    auth()
    svc.apply_lazy_defaults()
    td = get_or_404(db.takedowns, tid)
    return success_obj(svc.ser_takedown(td))


@bp.post("/takedowns/<tid>/execute")
def execute_takedown(tid):
    role, _ = auth()
    ctx = idem_begin()
    td = get_or_404(db.takedowns, tid)
    require_role(role, ["LAND_MANAGER"])
    body()
    # 6: takedown state
    if td["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Takedown is not SCHEDULED")
    # 7: contract ACTIVE. Lazy defaulting must not cascade the contract to
    # DEFAULTED *before* the window check runs: PRD §3.2 pins the execute
    # attempt that arrives after the window to return
    # ERR_TAKEDOWN_WINDOW_EXPIRED (flipping the takedown -- and per the lazy
    # cascade its contract -- as a side effect of the attempt). An
    # already-DEFAULTED contract observed on entry (e.g. defaulted by an
    # earlier read of a sibling takedown) still trips the referential gate.
    oc = db.option_contracts[td["option_contract_id"]]
    if oc["state"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, "Contract is not ACTIVE")
    # 8: temporal window
    now = clock()
    if now < dt_or_none(td["window_start"]):
        raise ApiError(
            "ERR_TAKEDOWN_WINDOW_NOT_OPEN", 409,
            "Takedown window has not opened",
        )
    if now > dt_or_none(td["window_end"]):
        td["state"] = "DEFAULTED"
        touch(td)
        if oc["state"] == "ACTIVE":
            oc["state"] = "DEFAULTED"
            touch(oc)
        raise ApiError(
            "ERR_TAKEDOWN_WINDOW_EXPIRED", 409,
            "Takedown window has expired",
        )
    # Takedown is SCHEDULED and inside its window; any unrelated expired
    # takedowns may now lazily default (including the contract cascade).
    svc.apply_lazy_defaults()
    if oc["state"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, "Contract is not ACTIVE")
    # 10: lot exhaustion
    if oc["lots_taken_down"] + td["lot_count"] > oc["total_lots"]:
        raise ApiError(
            "ERR_CONTRACT_EXHAUSTED", 409,
            "Takedown would exceed total_lots",
        )

    # ---- takedown_pricing (pinned order) ----
    contract_exec = dt_or_none(oc["executed_at"])
    days = (now - contract_exec).days
    full_quarters = days // svc.QUARTER_DAYS
    base = oc["lot_base_price_cents"]
    escalated = base + svc.round_half_up_int(
        svc.Decimal(base) * svc.ESCALATION_RATE * full_quarters
    )
    cumulative_lots = oc["lots_taken_down"] + td["lot_count"]
    if cumulative_lots < 20:
        credit_pct = svc.Decimal("0.00")
    elif cumulative_lots < 40:
        credit_pct = svc.Decimal("0.02")
    else:
        credit_pct = svc.Decimal("0.03")
    credit_per_lot = svc.round_half_up_int(credit_pct * escalated)
    net_per_lot = escalated - credit_per_lot
    total_net = net_per_lot * td["lot_count"]

    td["state"] = "EXECUTED"
    td["executed_at"] = iso3(now)
    td["escalated_lot_price_cents"] = escalated
    td["credit_per_lot_cents"] = credit_per_lot
    td["net_due_per_lot_cents"] = net_per_lot
    td["total_net_due_cents"] = total_net
    touch(td)

    # Create lots
    for _ in range(td["lot_count"]):
        lot = fresh_row()
        lot.update({
            "community_id": td["community_id"],
            "source_takedown_id": td["id"],
            "state": "BANKED",
        })
        db.lots[lot["id"]] = lot

    oc["lots_taken_down"] += td["lot_count"]
    if oc["lots_taken_down"] == oc["total_lots"]:
        oc["state"] = "EXHAUSTED"
    touch(oc)

    return success_obj(svc.ser_takedown(td))
