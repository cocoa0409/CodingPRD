"""Profit pool distribution endpoints."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, request

import db
import helpers
from errors import (
    err_validation, err_invalid_state, err_commercial_terms,
    err_pool_period_overlap, err_window_not_satisfied, err_stale_version,
    err_pool_sum_mismatch, err_unauthorized,
)
from middleware import get_auth, require_roles
from response import ok_object

bp = Blueprint("pools", __name__)

MIN_ACTIVE_DAYS = 14


def pool_view(p):
    return {
        "id": p["id"],
        "period_start": p["period_start"],
        "period_end": p["period_end"],
        "pool_cents": p["pool_cents"],
        "share_mode": p["share_mode"],
        "status": p["status"],
        "eligible_store_count": p["eligible_store_count"],
        "remainder_cents": p["remainder_cents"],
        "share_lines": p["share_lines"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _floor_div(a, b):
    return int(Decimal(a) / Decimal(b)) if b else 0


def _count_active_days(store, ps_dt, pe_dt):
    """Count whole calendar days d in [period_start, period_end) the store held
    ACTIVE for the entire day, derived from the current activated_at/suspended_at
    epochs."""
    if store["status"] not in ("ACTIVE", "SUSPENDED"):
        return 0
    activated_dt = store.get("_activated_at_dt")
    if activated_dt is None:
        return 0
    suspended_dt = store.get("_suspended_at_dt") if store["status"] == "SUSPENDED" else None
    from datetime import datetime as _dt, time as _t, timezone as _tz
    count = 0
    d = ps_dt.date()
    end_d = pe_dt.date()
    while d < end_d:
        day_start = _dt.combine(d, _t.min, tzinfo=_tz.utc)
        day_end = day_start + timedelta(days=1)
        active_all_day = activated_dt <= day_start and (suspended_dt is None or suspended_dt >= day_end)
        if active_all_day:
            count += 1
        d += timedelta(days=1)
    return count


@bp.post("/bookshop/pool-distributions")
def create_pool():
    require_roles(["FinanceOps"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    period_start = body.get("period_start")
    period_end = body.get("period_end")
    pool_cents = body.get("pool_cents")
    share_mode = body.get("share_mode")

    ps = helpers.parse_dt(period_start)
    pe = helpers.parse_dt(period_end)
    if not isinstance(pool_cents, int) or isinstance(pool_cents, bool):
        raise err_validation("pool_cents must be an integer")
    if share_mode not in ("EQUAL_SPLIT", "SALES_WEIGHTED"):
        raise err_validation("share_mode must be EQUAL_SPLIT or SALES_WEIGHTED")
    if pe <= ps:
        raise err_validation("period_end must be after period_start")

    if pool_cents <= 0:
        raise err_commercial_terms("pool_cents must be > 0")

    for other in db.DB.pools.values():
        if other["status"] == "VOID":
            continue
        if ps < other["_pe_dt"] and pe > other["_ps_dt"]:
            raise err_pool_period_overlap()

    p = helpers.base_resource()
    p.update({
        "period_start": period_start,
        "period_end": period_end,
        "pool_cents": pool_cents,
        "share_mode": share_mode,
        "status": "DRAFT",
        "eligible_store_count": 0,
        "remainder_cents": 0,
        "share_lines": [],
        "_ps_dt": ps,
        "_pe_dt": pe,
    })
    db.DB.pools[p["id"]] = p
    return ok_object(pool_view(p), 201)


@bp.post("/bookshop/pool-distributions/<pid>/actions")
def pool_actions(pid):
    user_id, role = get_auth()
    p = helpers.get_or_404(db.DB.pools, pid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("calculate", "recalculate", "approve", "distribute", "void"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)
    if role != "FinanceOps":
        raise err_unauthorized()

    if action == "calculate":
        if p["status"] != "DRAFT":
            raise err_invalid_state("distribution must be DRAFT to calculate")
        now = db.get_clock()
        if p["_pe_dt"] > now:
            raise err_window_not_satisfied("period not fully elapsed")

        candidates = [s for s in db.DB.stores.values()
                      if s.get("pool_opt_in") and s["status"] != "DEACTIVATED"]
        candidates.sort(key=lambda s: (s["created_at"], s["id"]))
        elig = {}
        for s in candidates:
            days = _count_active_days(s, p["_ps_dt"], p["_pe_dt"])
            elig[s["id"]] = days >= MIN_ACTIVE_DAYS
        eligible_stores = [s for s in candidates if elig[s["id"]]]
        eligible_count = len(eligible_stores)

        weights = {}
        if p["share_mode"] == "SALES_WEIGHTED":
            for s in eligible_stores:
                w = sum(o["gross_cents"] for o in db.DB.orders.values()
                        if o.get("attributed_store_id") == s["id"]
                        and o["fulfillment_status"] == "DELIVERED"
                        and o.get("delivered_at") is not None
                        and p["_ps_dt"] <= helpers.parse_dt(o["delivered_at"]) < p["_pe_dt"])
                weights[s["id"]] = w
            total_weight = sum(weights.values())
        else:
            total_weight = 0

        shares = {}
        remainder = 0
        if eligible_count == 0:
            for s in candidates:
                shares[s["id"]] = 0
        elif p["share_mode"] == "EQUAL_SPLIT" or total_weight == 0:
            raw = p["pool_cents"] // eligible_count
            for s in candidates:
                shares[s["id"]] = raw if elig[s["id"]] else 0
            remainder = p["pool_cents"] - raw * eligible_count
            # Remainder to eligible store with earliest created_at
            if eligible_stores:
                shares[eligible_stores[0]["id"]] += remainder
        else:
            for s in candidates:
                if elig[s["id"]]:
                    shares[s["id"]] = int(
                        (Decimal(p["pool_cents"]) * Decimal(weights[s["id"]])
                         / Decimal(total_weight)).to_integral_value(rounding=ROUND_FLOOR))
                else:
                    shares[s["id"]] = 0
            remainder = p["pool_cents"] - sum(shares.values())
            # Remainder to eligible store with largest weight; ties by created_at ASC.
            best = None
            for s in eligible_stores:
                if best is None or weights[s["id"]] > weights[best["id"]]:
                    best = s
            if best is not None:
                shares[best["id"]] += remainder

        p["share_lines"] = [
            {"store_id": s["id"], "eligible": elig[s["id"]], "share_cents": shares[s["id"]]}
            for s in candidates
        ]
        p["eligible_store_count"] = eligible_count
        p["remainder_cents"] = remainder
        p["status"] = "CALCULATED"
        helpers.touch(p)
    elif action == "recalculate":
        if p["status"] != "CALCULATED":
            raise err_invalid_state("distribution must be CALCULATED to recalculate")
        p["share_lines"] = []
        p["eligible_store_count"] = 0
        p["remainder_cents"] = 0
        p["status"] = "DRAFT"
        helpers.touch(p)
    elif action == "approve":
        if p["status"] != "CALCULATED":
            raise err_invalid_state("distribution must be CALCULATED to approve")
        edv = body.get("expected_distribution_version")
        if edv is None:
            raise err_validation("expected_distribution_version is required")
        if not isinstance(edv, int) or isinstance(edv, bool):
            raise err_validation("expected_distribution_version must be an integer")
        if edv != p["version"]:
            raise err_stale_version()
        if sum(l["share_cents"] for l in p["share_lines"]) != p["pool_cents"]:
            raise err_pool_sum_mismatch()
        p["status"] = "APPROVED"
        helpers.touch(p)
    elif action == "distribute":
        if p["status"] != "APPROVED":
            raise err_invalid_state("distribution must be APPROVED to distribute")
        lines = [l for l in p["share_lines"] if l["eligible"] and l["share_cents"] > 0]
        lines.sort(key=lambda l: (db.DB.stores[l["store_id"]]["created_at"], l["store_id"]))
        for l in lines:
            e = helpers.ledger_resource()
            e.update({
                "affiliate_store_id": l["store_id"],
                "affiliate_partner_id": None,
                "order_id": None,
                "pool_distribution_id": p["id"],
                "kind": "POOL_DISTRIBUTION",
                "amount_cents": l["share_cents"],
                "reversed": False,
            })
            db.DB.ledger[e["id"]] = e
            helpers.reconcile_affiliate(store_id=l["store_id"])
        helpers.payout_sweep_all()
        p["status"] = "DISTRIBUTED"
        helpers.touch(p)
    elif action == "void":
        if p["status"] != "DRAFT":
            raise err_invalid_state("distribution must be DRAFT to void")
        p["status"] = "VOID"
        helpers.touch(p)
    return ok_object(pool_view(p))
