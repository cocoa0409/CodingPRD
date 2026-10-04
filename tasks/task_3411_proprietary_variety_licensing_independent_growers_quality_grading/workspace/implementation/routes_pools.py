"""PoolPeriod endpoints: open, get, close (provisional), settle (final)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import constants
import store
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POOL_HAS_UNGRADED_LOTS,
    ERR_POOL_WINDOW_OVERLAP,
)
from helpers import (
    as_bool,
    as_dt,
    as_enum,
    as_pos_int,
    body,
    dump,
    req_field,
    require_roles,
    success,
)

bp = Blueprint("pool_periods", __name__)

ANY_ROLE = constants.ROLES


def get_pool_or_404(pool_id):
    p = store.db["pool_periods"].get(pool_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "No pool period with the given id")
    return p


def grower_of_lot(lot):
    planting = store.db["plantings"][lot["planting_id"]]
    agreement = store.db["agreements"][planting["agreement_id"]]
    return agreement["grower_id"]


def pool_blocking_ungraded(pool):
    """In-window lots of the pool's berry type that are neither CERTIFIED nor REJECTED."""
    for lot in store.db["harvest_lots"].values():
        if lot["received_at"] is None:
            continue
        if not (pool["week_start"] <= lot["received_at"] < pool["week_end"]):
            continue
        planting = store.db["plantings"][lot["planting_id"]]
        plant_lot = store.db["plant_lots"][planting["plant_lot_id"]]
        variety = store.db["varieties"][plant_lot["variety_id"]]
        if variety["berry_type"] != pool["berry_type"]:
            continue
        if lot["grade_status"] != "CERTIFIED" and lot["lot_status"] != "REJECTED":
            return True
    return False


@bp.route("/licensing/pool-periods", methods=["POST"])
@require_roles("SettlementOfficer")
def create_pool():
    b = body()
    berry_type = as_enum(req_field(b, "berry_type"), "berry_type", constants.BERRY_TYPES)
    week_start = as_dt(req_field(b, "week_start"), "week_start")
    week_end = as_dt(req_field(b, "week_end"), "week_end")
    is_shoulder_week = as_bool(req_field(b, "is_shoulder_week"), "is_shoulder_week")
    if week_end <= week_start:
        raise err(ERR_INVALID_REQUEST, "week_end must be after week_start")
    # Half-open overlap on same berry_type; pure adjacency allowed
    for p in store.db["pool_periods"].values():
        if (
            p["berry_type"] == berry_type
            and p["week_start"] < week_end
            and week_start < p["week_end"]
        ):
            raise err(ERR_POOL_WINDOW_OVERLAP, "Pool window overlaps an existing pool")
    rec = store.init_record({
        "berry_type": berry_type,
        "week_start": week_start,
        "week_end": week_end,
        "is_shoulder_week": is_shoulder_week,
        "status": "OPEN",
        "estimated_price_cents_per_kg": None,
        "actual_price_cents_per_kg": None,
        "total_net_kg": None,
        "total_weighted_kg": None,
        "gross_pool_revenue_cents": None,
        "marketing_fee_cents": None,
        "net_pool_revenue_cents": None,
        "pool_distributable_cents": None,
        "provisional_pool_rate": None,
        "final_pool_rate": None,
        "closed_at": None,
        "settled_at": None,
    })
    store.db["pool_periods"][rec["id"]] = rec
    return success(dump(rec), code=201)


@bp.route("/licensing/pool-periods/<poolPeriodId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_pool(poolPeriodId):
    return success(dump(get_pool_or_404(poolPeriodId)))


@bp.route("/licensing/pool-periods/<poolPeriodId>/close", methods=["POST"])
@require_roles("SettlementOfficer")
def close_pool(poolPeriodId):
    pool = get_pool_or_404(poolPeriodId)
    b = body()
    estimated = as_pos_int(req_field(b, "estimated_price_cents_per_kg"), "estimated_price_cents_per_kg")
    if pool["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Pool is not OPEN")
    if pool_blocking_ungraded(pool):
        raise err(ERR_POOL_HAS_UNGRADED_LOTS, "An in-window lot is neither CERTIFIED nor REJECTED")
    lots = calc.pool_included_lots(pool)
    rate = calc.run_pool_pipeline(pool, lots, estimated)
    pool["estimated_price_cents_per_kg"] = estimated
    pool["provisional_pool_rate"] = rate
    # Stamp included lots with provisional gross (per-lot rounding first)
    for lot in lots:
        lot["pool_period_id"] = pool["id"]
        lot["lot_gross_provisional_cents"] = calc.lot_gross_cents(lot, rate)
        store.touch(lot)
    # One PROVISIONAL statement per grower with >= 1 included lot
    by_grower = {}
    for lot in lots:
        by_grower.setdefault(grower_of_lot(lot), []).append(lot)
    for grower_id, glots in by_grower.items():
        provisional_gross = sum(l["lot_gross_provisional_cents"] for l in glots)
        deduction = sum(
            calc.rhu_int(Decimal(l["lot_gross_provisional_cents"]) * constants.COLD_CHAIN_BREACH_DEDUCTION_PCT)
            for l in glots
            if l["cold_chain_compliant"] is False
        )
        rec = store.init_record({
            "pool_period_id": pool["id"],
            "grower_id": grower_id,
            "status": "PROVISIONAL",
            "provisional_net_cents": provisional_gross - deduction,
            "gross_cents": None,
            "royalty_offset_cents": None,
            "cold_chain_deduction_cents": None,
            "recall_credit_cents": None,
            "net_cents": None,
            "issued_at": None,
            "dispute_deadline": None,
            "dispute_reason": None,
            "dispute_count": 0,
            "resolution": None,
            "adjustment_total_cents": 0,
            "paid_at": None,
        })
        store.db["settlement_statements"][rec["id"]] = rec
    pool["status"] = "CLOSED"
    pool["closed_at"] = store.clock_now()
    store.touch(pool)
    return success(dump(pool))


@bp.route("/licensing/pool-periods/<poolPeriodId>/settle", methods=["POST"])
@require_roles("SettlementOfficer")
def settle_pool(poolPeriodId):
    pool = get_pool_or_404(poolPeriodId)
    b = body()
    actual = as_pos_int(req_field(b, "actual_price_cents_per_kg"), "actual_price_cents_per_kg")
    if pool["status"] != "CLOSED":
        raise err(ERR_INVALID_STATE, "Pool is not CLOSED")
    lots = calc.pool_included_lots(pool)
    rate = calc.run_pool_pipeline(pool, lots, actual)
    pool["actual_price_cents_per_kg"] = actual
    pool["final_pool_rate"] = rate
    # Final per-lot gross, then remainder reconciliation (pool zero-sum invariant)
    for lot in lots:
        lot["lot_gross_final_cents"] = calc.lot_gross_cents(lot, rate)
    if lots:
        remainder = pool["pool_distributable_cents"] - sum(l["lot_gross_final_cents"] for l in lots)
        # Largest weighted kg; ties: earliest received_at, then earliest created_at
        target = max(
            lots,
            key=lambda l: (
                l["net_kg"] * constants.GRADE_WEIGHT[l["grade"]],
                -l["received_at"].timestamp(),
                -l["created_at"].timestamp(),
            ),
        )
        target["lot_gross_final_cents"] += remainder
    for lot in lots:
        lot["lot_status"] = "SETTLED"
        store.touch(lot)
    # Issue statements with final amounts
    by_grower = {}
    for lot in lots:
        by_grower.setdefault(grower_of_lot(lot), []).append(lot)
    now = store.clock_now()
    for stmt in store.db["settlement_statements"].values():
        if stmt["pool_period_id"] != pool["id"] or stmt["status"] != "PROVISIONAL":
            continue
        glots = by_grower.get(stmt["grower_id"], [])
        gross = sum(l["lot_gross_final_cents"] for l in glots)
        deduction = sum(
            calc.rhu_int(Decimal(l["lot_gross_final_cents"]) * constants.COLD_CHAIN_BREACH_DEDUCTION_PCT)
            for l in glots
            if l["cold_chain_compliant"] is False
        )
        # Royalty offset: grower's plant lots depleted inside the pooling window
        royalty_offset = 0
        for pl in store.db["plant_lots"].values():
            if pl["depleted_at"] is None or not (pool["week_start"] <= pl["depleted_at"] < pool["week_end"]):
                continue
            ag = store.db["agreements"].get(pl["agreement_id"])
            if ag is not None and ag["grower_id"] == stmt["grower_id"] and pl["royalty_adjustment_cents"] is not None:
                royalty_offset += pl["royalty_adjustment_cents"]
        # Recall credit: grower's plantings recalled inside the pooling window
        recall_credit = 0
        for p in store.db["plantings"].values():
            if p["recalled_at"] is None or not (pool["week_start"] <= p["recalled_at"] < pool["week_end"]):
                continue
            ag = store.db["agreements"].get(p["agreement_id"])
            if ag is not None and ag["grower_id"] == stmt["grower_id"] and p["recall_compensation_cents"]:
                recall_credit += p["recall_compensation_cents"]
        stmt["gross_cents"] = gross
        stmt["royalty_offset_cents"] = royalty_offset
        stmt["cold_chain_deduction_cents"] = deduction
        stmt["recall_credit_cents"] = recall_credit
        stmt["net_cents"] = gross - royalty_offset - deduction + recall_credit
        stmt["status"] = "ISSUED"
        stmt["issued_at"] = now
        stmt["dispute_deadline"] = now + timedelta(days=constants.DISPUTE_WINDOW_DAYS)
        store.touch(stmt)
    pool["status"] = "SETTLED"
    pool["settled_at"] = now
    store.touch(pool)
    return success(dump(pool))
