"""Entity serializers. Internal records store datetimes as aware datetimes and
money as Decimals; serializers render ISO-8601 strings and JSON numbers.

Directive and RecognitionSnapshot carry only id + created_at (PRD 2.5).
"""
from calc import committed_parts_cost
from money import num
from storage import DB
from timeutil import fmt_iso


def _common(e):
    return {
        "created_at": fmt_iso(e["created_at"]),
        "updated_at": fmt_iso(e["updated_at"]),
        "version": e["version"],
    }


def operator_json(o):
    out = {
        "id": o["id"],
        "name": o["name"],
        "iata_code": o["iata_code"],
        "credit_rating": o["credit_rating"],
    }
    out.update(_common(o))
    return out


def engine_json(e):
    out = {
        "id": e["id"],
        "operator_id": e["operator_id"],
        "esn": e["esn"],
        "engine_model": e["engine_model"],
        "base_severity_tier": e["base_severity_tier"],
        "cumulative_flight_hours": num(e["cumulative_flight_hours"]),
        "cumulative_cycles": e["cumulative_cycles"],
        "llp_remaining_cycles": e["llp_remaining_cycles"],
        "agreement_id": e["agreement_id"],
        "assumed_annual_hours": num(e["assumed_annual_hours"]),
        "assumed_cycles_per_month": e["assumed_cycles_per_month"],
        "enrolled_at": fmt_iso(e["enrolled_at"]),
        "status": e["status"],
        "projected_next_removal_date": fmt_iso(e["projected_next_removal_date"]),
    }
    out.update(_common(e))
    return out


def agreement_json(a):
    enrolled = sum(1 for e in DB["engines"].values() if e["agreement_id"] == a["id"])
    out = {
        "id": a["id"],
        "contract_ref": a["contract_ref"],
        "base_rate_per_fh_usd": num(a["base_rate_per_fh_usd"]),
        "escalation_pct": num(a["escalation_pct"]),
        "escalation_anchor_date": fmt_iso(a["escalation_anchor_date"]),
        "start_date": fmt_iso(a["start_date"]),
        "end_date": fmt_iso(a["end_date"]),
        "allowed_sourcing_classes": list(a["allowed_sourcing_classes"]),
        "max_workscope_cost_usd": num(a["max_workscope_cost_usd"]),
        "status": a["status"],
        "billed_to_date_usd": num(a["billed_to_date_usd"]),
        "enrolled_engine_count": enrolled,
    }
    out.update(_common(a))
    return out


def report_json(r):
    out = {
        "id": r["id"],
        "engine_id": r["engine_id"],
        "period": r["period"],
        "flight_hours": num(r["flight_hours"]),
        "cycles": r["cycles"],
        "observed_severity": r["observed_severity"],
        "status": r["status"],
        "verified_at": fmt_iso(r["verified_at"]),
    }
    out.update(_common(r))
    return out


def statement_json(s):
    out = {
        "id": s["id"],
        "agreement_id": s["agreement_id"],
        "period": s["period"],
        "status": s["status"],
        "line_items": s["line_items"],
        "provisional_total_usd": num(s["provisional_total_usd"]),
        "final_total_usd": num(s["final_total_usd"]),
        "adjustment_usd": num(s["adjustment_usd"]),
    }
    out.update(_common(s))
    return out


def visit_json(v):
    out = {
        "id": v["id"],
        "engine_id": v["engine_id"],
        "planned_induction_date": fmt_iso(v["planned_induction_date"]),
        "forecast_induction_date": fmt_iso(v["forecast_induction_date"]),
        "forecast_method": v["forecast_method"],
        "actual_induction_date": fmt_iso(v["actual_induction_date"]),
        "completion_date": fmt_iso(v["completion_date"]),
        "status": v["status"],
        "projected_cost_usd": num(v["projected_cost_usd"]),
        "committed_parts_cost_usd": num(committed_parts_cost(v)),
    }
    out.update(_common(v))
    return out


def _item_json(it):
    return {
        "item_code": it["item_code"],
        "item_type": it["item_type"],
        "estimated_cost_usd": num(it["estimated_cost_usd"]),
        "restores_cycles": it["restores_cycles"],
        "directive_ref": it["directive_ref"],
    }


def workscope_json(w):
    out = {
        "id": w["id"],
        "shop_visit_id": w["shop_visit_id"],
        "scope_version": w["scope_version"],
        "status": w["status"],
        "items": [_item_json(it) for it in w["items"]],
        "total_cost_usd": num(w["total_cost_usd"]),
        "restores_llp_cycles": w["restores_llp_cycles"],
        "decided_at": fmt_iso(w["decided_at"]),
    }
    out.update(_common(w))
    return out


def requisition_json(r):
    out = {
        "id": r["id"],
        "workscope_id": r["workscope_id"],
        "part_number": r["part_number"],
        "quantity": r["quantity"],
        "list_price_usd": num(r["list_price_usd"]),
        "requested_class": r["requested_class"],
        "required_by_date": fmt_iso(r["required_by_date"]),
        "sourced_class": r["sourced_class"],
        "unit_cost_usd": num(r["unit_cost_usd"]),
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def spare_json(s):
    out = {
        "id": s["id"],
        "spare_serial": s["spare_serial"],
        "engine_model": s["engine_model"],
        "daily_lease_rate_usd": num(s["daily_lease_rate_usd"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def lease_json(l):
    out = {
        "id": l["id"],
        "spare_engine_id": l["spare_engine_id"],
        "shop_visit_id": l["shop_visit_id"],
        "start_date": fmt_iso(l["start_date"]),
        "end_date": fmt_iso(l["end_date"]),
        "status": l["status"],
        "lease_cost_usd": num(l["lease_cost_usd"]),
        "deposit_usd": num(l["deposit_usd"]),
    }
    out.update(_common(l))
    return out


def directive_json(d):
    return {
        "id": d["id"],
        "directive_ref": d["directive_ref"],
        "directive_type": d["directive_type"],
        "applicability_model": d["applicability_model"],
        "mandatory": d["mandatory"],
        "compliance_cycles": d["compliance_cycles"],
        "compliance_date": fmt_iso(d["compliance_date"]),
        "estimated_cost_usd": num(d["estimated_cost_usd"]),
        "created_at": fmt_iso(d["created_at"]),
    }


def snapshot_json(s):
    return {
        "id": s["id"],
        "agreement_id": s["agreement_id"],
        "lifetime_revenue_projection_usd": num(s["lifetime_revenue_projection_usd"]),
        "lifetime_cost_projection_usd": num(s["lifetime_cost_projection_usd"]),
        "cost_to_date_usd": num(s["cost_to_date_usd"]),
        "recognition_pct": num(s["recognition_pct"]),
        "recognized_revenue_projected_usd": num(s["recognized_revenue_projected_usd"]),
        "recognized_revenue_actual_usd": num(s["recognized_revenue_actual_usd"]),
        "onerous_loss_accrual_usd": num(s["onerous_loss_accrual_usd"]),
        "created_at": fmt_iso(s["created_at"]),
    }
