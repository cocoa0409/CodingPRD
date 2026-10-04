"""Public entity shapes, including computed-on-read fields (PRD 2.5, 2.11)."""
from services.core import (
    curtailed_capacity_tpd,
    hedge_coverage_ratio,
    lazy_expire_contract,
    lazy_expire_hedge,
    lazy_expire_permit,
    open_hedged_tonnes,
    potline_restart_class,
    smelter_posture,
    take_or_pay_exposed,
)
from services.pricing import (
    forward_cost_per_mwh,
    interruptible_hours_used,
    month_to_date_settlement,
    settled_cost_per_mwh,
    transfer_price,
)
from util import fmt_iso, fmt_wall, num, round4_dec


def _common(rec):
    return {
        "created_at": fmt_wall(rec["created_at"]),
        "updated_at": fmt_wall(rec["updated_at"]),
        "version": rec["version"],
    }


def smelter_json(s):
    out = {
        "id": s["id"],
        "name": s["name"],
        "region_code": s["region_code"],
        "rated_capacity_tpd": s["rated_capacity_tpd"],
        "labor_headcount": s["labor_headcount"],
        "operating_posture": smelter_posture(s["id"]),
        "open_hedged_tonnes": num(open_hedged_tonnes(s["id"])),
        "curtailed_capacity_tpd": num(curtailed_capacity_tpd(s["id"])),
        "hedge_coverage_ratio": float(round4_dec(hedge_coverage_ratio(s))),
    }
    out.update(_common(s))
    return out


def potline_json(p):
    out = {
        "id": p["id"],
        "smelter_id": p["smelter_id"],
        "line_code": p["line_code"],
        "capacity_tpd": p["capacity_tpd"],
        "amperage_ka": p["amperage_ka"],
        "operating_status": p["operating_status"],
        "curtailment_depth_pct": p["curtailment_depth_pct"],
        "curtailed_since": fmt_iso(p["curtailed_since"]),
        "last_full_shutdown_at": fmt_iso(p["last_full_shutdown_at"]),
        "active_decision_id": p["active_decision_id"],
        "restart_cost_class": potline_restart_class(p),
    }
    out.update(_common(p))
    return out


def contract_json(c):
    lazy_expire_contract(c)
    fwd = forward_cost_per_mwh(c)
    stl = settled_cost_per_mwh(c)
    mtd = month_to_date_settlement(c)
    out = {
        "id": c["id"],
        "smelter_id": c["smelter_id"],
        "supplier_name": c["supplier_name"],
        "window_start": fmt_iso(c["window_start"]),
        "window_end": fmt_iso(c["window_end"]),
        "components": c["components"],
        "take_or_pay_pct": c["take_or_pay_pct"],
        "status": c["status"],
        "interruptible_hours_used": num(interruptible_hours_used(c)),
        "forward_cost_per_mwh": float(fwd) if fwd is not None else None,
        "settled_cost_per_mwh": float(stl) if stl is not None else None,
        "month_to_date_settlement_usd": num(mtd) if mtd is not None else None,
        "take_or_pay_exposed": take_or_pay_exposed(c),
    }
    out.update(_common(c))
    return out


def price_observation_json(o):
    return {
        "id": o["id"],
        "instrument": o["instrument"],
        "region_code": o["region_code"],
        "observed_at": fmt_iso(o["observed_at"]),
        "price_usd": o["price_usd"],
        "created_at": fmt_wall(o["created_at"]),
    }


def interrupt_event_json(e):
    return {
        "id": e["id"],
        "contract_id": e["contract_id"],
        "start_at": fmt_iso(e["start_at"]),
        "end_at": fmt_iso(e["end_at"]),
        "mw_reduced": e["mw_reduced"],
        "hours": e["hours"],
        "created_at": fmt_wall(e["created_at"]),
    }


def hedge_json(h):
    lazy_expire_hedge(h)
    out = {
        "id": h["id"],
        "smelter_id": h["smelter_id"],
        "instrument": h["instrument"],
        "volume_tonnes": h["volume_tonnes"],
        "strike_price_usd": h["strike_price_usd"],
        "delivery_month": h["delivery_month"],
        "status": h["status"],
        "closed_price_usd": h["closed_price_usd"],
        "realized_pnl_usd": (
            float(h["realized_pnl_usd"]) if h["realized_pnl_usd"] is not None else None
        ),
    }
    out.update(_common(h))
    return out


def agreement_json(a):
    tp = transfer_price(a)
    out = {
        "id": a["id"],
        "smelter_id": a["smelter_id"],
        "refinery_name": a["refinery_name"],
        "pricing_model": a["pricing_model"],
        "base_cost_per_tonne": a["base_cost_per_tonne"],
        "markup_pct": a["markup_pct"],
        "market_discount_pct": a["market_discount_pct"],
        "monthly_volume_tonnes": a["monthly_volume_tonnes"],
        "current_transfer_price": float(tp) if tp is not None else None,
    }
    out.update(_common(a))
    return out


def decision_json(d):
    out = {
        "id": d["id"],
        "potline_id": d["potline_id"],
        "trigger_type": d["trigger_type"],
        "depth_pct": d["depth_pct"],
        "planned_start": fmt_iso(d["planned_start"]),
        "planned_end": fmt_iso(d["planned_end"]),
        "status": d["status"],
        "economics_snapshot": d["economics_snapshot"],
        "proposed_by_user_id": d["proposed_by_user_id"],
        "economic_reviewed_by_user_id": d["economic_reviewed_by_user_id"],
        "approved_by_user_id": d["approved_by_user_id"],
        "approved_at": fmt_iso(d["approved_at"]),
        "executed_at": fmt_iso(d["executed_at"]),
    }
    out.update(_common(d))
    return out


def restart_plan_json(r):
    out = {
        "id": r["id"],
        "potline_id": r["potline_id"],
        "planned_restart_at": fmt_iso(r["planned_restart_at"]),
        "status": r["status"],
        "restart_cost_class": r["restart_cost_class"],
        "estimated_cost_usd": num(r["estimated_cost_usd"]),
        "actual_cost_usd": (
            num(r["actual_cost_usd"]) if r["actual_cost_usd"] is not None else None
        ),
    }
    out.update(_common(r))
    return out


def permit_json(p):
    lazy_expire_permit(p)
    out = {
        "id": p["id"],
        "smelter_id": p["smelter_id"],
        "permit_type": p["permit_type"],
        "valid_from": fmt_iso(p["valid_from"]),
        "valid_to": fmt_iso(p["valid_to"]),
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def labor_agreement_json(a):
    out = {
        "id": a["id"],
        "smelter_id": a["smelter_id"],
        "union_name": a["union_name"],
        "notice_period_days": a["notice_period_days"],
        "severance_weeks_per_year": a["severance_weeks_per_year"],
        "community_impact_clause": a["community_impact_clause"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def production_plan_json(p):
    out = {
        "id": p["id"],
        "smelter_id": p["smelter_id"],
        "period_month": p["period_month"],
        "allocations": p["allocations"],
        "status": p["status"],
        "total_tonnes": num(p["total_tonnes"]),
        "total_margin_usd": float(p["total_margin_usd"]),
    }
    out.update(_common(p))
    return out
