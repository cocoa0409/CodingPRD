"""Routes: value-based incentive pools and allocations."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import (
    err_allocation_not_payable,
    err_contract_not_active,
    err_invalid,
    err_no_effective,
    err_no_eligible,
    err_not_found,
    err_ownership,
    err_pool_not_scoring,
    err_practice_not_affiliated,
    err_transition,
)
from middleware import get_context, require_roles
from response import created, new_entity, ok, paginate, parse_pagination, touch
from services import practice_has_effective_enrollment, round_half_up_6dp
from validate import (
    body_json,
    optional_number,
    require_int,
    require_number,
    require_period,
    require_str,
)

bp = Blueprint("incentives", __name__)


# ---------------------------------------------------------------------------
# ValueBasedIncentivePool
# ---------------------------------------------------------------------------

@bp.route("/api/incentive-pools", methods=["POST"])
def create_pool():
    require_roles("PayerContractingOfficer")
    data = body_json()
    payer_contract_id = require_str(data, "payer_contract_id")
    period = require_period(data, "period")
    pool_amount_cents = require_int(data, "pool_amount_cents")
    if pool_amount_cents <= 0:
        raise err_invalid("pool_amount_cents must be > 0")
    quality_threshold = optional_number(data, "quality_threshold", 60)
    contract = store.payer_contracts.get(payer_contract_id)
    if contract is None:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    if contract["status"] != "ACTIVE":
        raise err_contract_not_active()
    if not contract["value_based_pool_eligible"]:
        raise err_invalid("Contract is not value_based_pool_eligible")
    p = new_entity()
    p.update(
        payer_contract_id=payer_contract_id,
        period=period,
        pool_amount_cents=pool_amount_cents,
        quality_threshold=quality_threshold,
        allocated_total_cents=0,
        status="OPEN",
    )
    store.pools[p["id"]] = p
    return created(p)


@bp.route("/api/incentive-pools", methods=["GET"])
def list_pools():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.pools.values())
    cid = request.args.get("payer_contract_id")
    if cid is not None:
        items = [p for p in items if p["payer_contract_id"] == cid]
    per = request.args.get("period")
    if per is not None:
        items = [p for p in items if p["period"] == per]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/incentive-pools/<pid>", methods=["GET"])
def get_pool(pid):
    get_context()
    p = store.pools.get(pid)
    if p is None:
        raise err_not_found("POOL", "Pool not found")
    return ok(p)


@bp.route("/api/incentive-pools/<pid>/close-entries", methods=["POST"])
def close_entries(pid):
    require_roles("GroupFinancialController")
    p = store.pools.get(pid)
    if p is None:
        raise err_not_found("POOL", "Pool not found")
    if p["status"] != "OPEN":
        raise err_transition("Pool is not OPEN")
    p["status"] = "SCORING"
    touch(p)
    return ok(p)


@bp.route("/api/incentive-pools/<pid>/allocate", methods=["POST"])
def allocate_pool(pid):
    require_roles("GroupFinancialController")
    p = store.pools.get(pid)
    if p is None:
        raise err_not_found("POOL", "Pool not found")
    if p["status"] != "SCORING":
        raise err_pool_not_scoring()
    threshold = Decimal(str(p["quality_threshold"]))
    entered = [
        a
        for a in store.allocations.values()
        if a["pool_id"] == p["id"] and a["status"] == "ENTERED"
    ]
    eligible = [
        a for a in entered if Decimal(str(a["quality_score"])) >= threshold
    ]
    if not eligible:
        raise err_no_eligible()
    # weights
    weights = {}
    for a in eligible:
        practice = store.practices.get(a["practice_id"])
        market = store.markets.get(practice["market_id"]) if practice else None
        mw = Decimal(str(market["market_weight"])) if market else Decimal("1")
        w = round_half_up_6dp(
            Decimal(str(a["quality_score"])) * Decimal(a["attributed_lives"]) * mw
        )
        weights[a["id"]] = w
    total_weight = sum(weights.values())
    pool_amt = p["pool_amount_cents"]
    # floor shares and fractional parts
    raw = {}
    floors = {}
    fracs = {}
    for a in eligible:
        raw_a = (Decimal(pool_amt) * weights[a["id"]]) / total_weight
        raw[a["id"]] = raw_a
        floor_a = int(raw_a.to_integral_value(rounding="ROUND_FLOOR"))
        floors[a["id"]] = floor_a
        fracs[a["id"]] = raw_a - Decimal(floor_a)
    remainder = pool_amt - sum(floors.values())
    # waterfall ordering: frac DESC, quality_score DESC, created_at ASC
    order = sorted(
        eligible,
        key=lambda a: (
            -float(fracs[a["id"]]),
            -float(a["quality_score"]),
            a["created_at"],
            a["id"],
        ),
    )
    shares = {a["id"]: floors[a["id"]] for a in eligible}
    idx = 0
    while remainder > 0 and order:
        target = order[idx % len(order)]
        shares[target["id"]] += 1
        remainder -= 1
        idx += 1
    allocated_total = 0
    for a in entered:
        if a in eligible:
            a["weight"] = float(weights[a["id"]])
            a["share_cents"] = shares[a["id"]]
            a["status"] = "SCORED"
            allocated_total += shares[a["id"]]
        else:
            a["weight"] = None
            a["share_cents"] = 0
            a["status"] = "INELIGIBLE"
        touch(a)
    p["allocated_total_cents"] = allocated_total
    p["status"] = "ALLOCATED"
    touch(p)
    return ok(p)


@bp.route("/api/incentive-pools/<pid>/distribute", methods=["POST"])
def distribute_pool(pid):
    require_roles("GroupFinancialController")
    p = store.pools.get(pid)
    if p is None:
        raise err_not_found("POOL", "Pool not found")
    if p["status"] != "ALLOCATED":
        raise err_transition("Pool is not ALLOCATED")
    for a in store.allocations.values():
        if a["pool_id"] == p["id"] and a["status"] == "SCORED":
            a["status"] = "PAYABLE"
            touch(a)
    p["status"] = "DISTRIBUTED"
    touch(p)
    return ok(p)


@bp.route("/api/incentive-pools/<pid>/void", methods=["POST"])
def void_pool(pid):
    require_roles("GroupFinancialController")
    p = store.pools.get(pid)
    if p is None:
        raise err_not_found("POOL", "Pool not found")
    if p["status"] != "DISTRIBUTED":
        raise err_transition("Pool is not DISTRIBUTED")
    for a in store.allocations.values():
        if a["pool_id"] == p["id"] and a["status"] == "PAYABLE":
            a["status"] = "VOIDED"
            touch(a)
    p["status"] = "VOIDED"
    touch(p)
    return ok(p)


# ---------------------------------------------------------------------------
# IncentiveAllocation
# ---------------------------------------------------------------------------

@bp.route("/api/incentive-allocations", methods=["POST"])
def create_allocation():
    user_id, _role = require_roles("PracticeExecutive")
    data = body_json()
    pool_id = require_str(data, "pool_id")
    practice_id = require_str(data, "practice_id")
    quality_score = require_number(data, "quality_score")
    if quality_score < 0 or quality_score > 100:
        raise err_invalid("quality_score must be in [0, 100]")
    attributed_lives = require_int(data, "attributed_lives")
    if attributed_lives <= 0:
        raise err_invalid("attributed_lives must be > 0")
    if user_id != practice_id:
        raise err_ownership()
    pool = store.pools.get(pool_id)
    if pool is None:
        raise err_not_found("POOL", "Pool not found")
    practice = store.practices.get(practice_id)
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if pool["status"] != "OPEN":
        raise err_transition("Pool is not OPEN")
    if practice["status"] != "AFFILIATED":
        raise err_practice_not_affiliated()
    if not practice_has_effective_enrollment(practice_id, pool["payer_contract_id"]):
        raise err_no_effective()
    a = new_entity()
    a.update(
        pool_id=pool_id,
        practice_id=practice_id,
        quality_score=quality_score,
        attributed_lives=attributed_lives,
        weight=None,
        share_cents=None,
        status="ENTERED",
    )
    store.allocations[a["id"]] = a
    return created(a)


@bp.route("/api/incentive-allocations", methods=["GET"])
def list_allocations():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.allocations.values())
    pl = request.args.get("pool_id")
    if pl is not None:
        items = [a for a in items if a["pool_id"] == pl]
    pid = request.args.get("practice_id")
    if pid is not None:
        items = [a for a in items if a["practice_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/incentive-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    get_context()
    a = store.allocations.get(aid)
    if a is None:
        raise err_not_found("ALLOCATION", "Allocation not found")
    return ok(a)


@bp.route("/api/incentive-allocations/<aid>/pay", methods=["POST"])
def pay_allocation(aid):
    require_roles("GroupFinancialController")
    a = store.allocations.get(aid)
    if a is None:
        raise err_not_found("ALLOCATION", "Allocation not found")
    if a["status"] != "PAYABLE":
        raise err_allocation_not_payable()
    a["status"] = "PAID"
    touch(a)
    return ok(a)
