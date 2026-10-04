"""Entity -> JSON-serializable dict (PRD §2.5 common fields).

All datetimes serialize via clock.iso (ISO 8601 UTC, three fractional
digits). 2dp Decimal scores/percentages serialize as JSON numbers.
QualificationRun is the sole exception to common fields: no updated_at,
no version.
"""

from clock import iso
from calculations import plant_load


def _dt(v):
    return iso(v) if v is not None else None


def _num(d):
    return float(d)


def brand_out(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "category_name": b["category_name"],
        "core_flag": b["core_flag"],
        "private_label_share_pct": b["private_label_share_pct"],
        "annual_net_revenue_cents": b["annual_net_revenue_cents"],
        "brand_status": b["brand_status"],
        "created_at": iso(b["created_at"]),
        "updated_at": iso(b["updated_at"]),
        "version": b["version"],
    }


def item_out(i):
    return {
        "id": i["id"],
        "brand_id": i["brand_id"],
        "primary_plant_id": i["primary_plant_id"],
        "sku_code": i["sku_code"],
        "annual_units": i["annual_units"],
        "unit_net_revenue_cents": i["unit_net_revenue_cents"],
        "unit_cost_cents": i["unit_cost_cents"],
        "units_on_hand": i["units_on_hand"],
        "salvageable": i["salvageable"],
        "item_status": i["item_status"],
        "sell_through_deadline": _dt(i["sell_through_deadline"]),
        "units_sold_cumulative": i["units_sold_cumulative"],
        "units_written_off_cumulative": i["units_written_off_cumulative"],
        "obsolescence_charge_cents": i["obsolescence_charge_cents"],
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def plant_out(p):
    committed, utilization = plant_load(p["id"])
    return {
        "id": p["id"],
        "name": p["name"],
        "quarterly_capacity_units": p["quarterly_capacity_units"],
        "plant_status": p["plant_status"],
        "closure_date": _dt(p["closure_date"]),
        "committed_units_per_quarter": committed,
        "utilization_pct": _num(utilization),
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def retailer_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "risk_rating": r["risk_rating"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def case_out(c):
    return {
        "id": c["id"],
        "item_id": c["item_id"],
        "proposer_user_id": c["proposer_user_id"],
        "volume_score": _num(c["volume_score"]),
        "margin_score": _num(c["margin_score"]),
        "shelf_resilience_score": _num(c["shelf_resilience_score"]),
        "backlash_resilience_score": _num(c["backlash_resilience_score"]),
        "composite_score": _num(c["composite_score"]),
        "recommendation": c["recommendation"],
        "case_status": c["case_status"],
        "decider_user_id": c["decider_user_id"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def divestiture_out(d):
    return {
        "id": d["id"],
        "brand_id": d["brand_id"],
        "acquirer_name": d["acquirer_name"],
        "headline_price_cents": d["headline_price_cents"],
        "expected_close_date": _dt(d["expected_close_date"]),
        "divestiture_status": d["divestiture_status"],
        "created_at": iso(d["created_at"]),
        "updated_at": iso(d["updated_at"]),
        "version": d["version"],
    }


def tsa_out(t):
    return {
        "id": t["id"],
        "divestiture_id": t["divestiture_id"],
        "monthly_fee_cents": t["monthly_fee_cents"],
        "start_date": _dt(t["start_date"]),
        "end_date": _dt(t["end_date"]),
        "tsa_status": t["tsa_status"],
        "terminated_at": _dt(t["terminated_at"]),
        "early_termination_penalty_cents": t["early_termination_penalty_cents"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def transfer_out(t):
    return {
        "id": t["id"],
        "item_id": t["item_id"],
        "source_plant_id": t["source_plant_id"],
        "target_plant_id": t["target_plant_id"],
        "transfer_status": t["transfer_status"],
        "consecutive_pass_count": t["consecutive_pass_count"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def run_out(r):
    # Immutable event record: no updated_at, no version (PRD §2.5).
    return {
        "id": r["id"],
        "transfer_id": r["transfer_id"],
        "run_date": _dt(r["run_date"]),
        "units_produced": r["units_produced"],
        "units_rejected": r["units_rejected"],
        "result": r["result"],
        "certifier_plant_id": r["certifier_plant_id"],
        "created_at": iso(r["created_at"]),
    }


def negotiation_out(n):
    return {
        "id": n["id"],
        "retailer_id": n["retailer_id"],
        "period_code": n["period_code"],
        "brand_terms": n["brand_terms"],
        "effective_from": _dt(n["effective_from"]),
        "effective_to": _dt(n["effective_to"]),
        "total_baseline_facings": n["total_baseline_facings"],
        "total_proposed_facings": n["total_proposed_facings"],
        "shelf_reduction_pct": _num(n["shelf_reduction_pct"]),
        "negotiation_status": n["negotiation_status"],
        "expires_at": _dt(n["expires_at"]),
        "created_at": iso(n["created_at"]),
        "updated_at": iso(n["updated_at"]),
        "version": n["version"],
    }


def cycle_out(c):
    return {
        "id": c["id"],
        "period_code": c["period_code"],
        "total_capital_cents": c["total_capital_cents"],
        "window_start": _dt(c["window_start"]),
        "window_end": _dt(c["window_end"]),
        "allocated_cents": c["allocated_cents"],
        "remaining_cents": c["total_capital_cents"] - c["allocated_cents"],
        "cycle_status": c["cycle_status"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def project_out(p):
    return {
        "id": p["id"],
        "brand_id": p["brand_id"],
        "funding_cycle_id": p["funding_cycle_id"],
        "title": p["title"],
        "requested_capital_cents": p["requested_capital_cents"],
        "expected_revenue_cents_year3": p["expected_revenue_cents_year3"],
        "strategic_fit_score": p["strategic_fit_score"],
        "priority_score": _num(p["priority_score"]),
        "project_status": p["project_status"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }
