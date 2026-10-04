"""Entity serializers."""
from decimal import Decimal, ROUND_HALF_UP


def _f(v):
    """Render numeric output as float (2dp-normalized where stored that way)."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def project_view(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "technology": p["technology"],
        "target_capacity_mw": _f(p["target_capacity_mw"]),
        "resource_class": p["resource_class"],
        "energy_community_eligible": p["energy_community_eligible"],
        "domestic_content_certified": p["domestic_content_certified"],
        "availability_guarantee_pct": _f(p["availability_guarantee_pct"]),
        "status": p["status"],
        "cod_date": p["cod_date"],
        "measured_availability_pct": _f(p["measured_availability_pct"]) if p["measured_availability_pct"] is not None else None,
        "availability_ld_usd": _f(p["availability_ld_usd"]),
        "tax_credit_anchored": p["tax_credit_anchored"],
        "total_itc_credits_usd": _f(p["total_itc_credits_usd"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def sci_view(s):
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "parcel_id": s["parcel_id"],
        "instrument_type": s["instrument_type"],
        "start_date": s["start_date"],
        "end_date": s["end_date"],
        "exercise_price_usd": _f(s["exercise_price_usd"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ir_view(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "cluster_id": r["cluster_id"],
        "requested_capacity_mw": _f(r["requested_capacity_mw"]),
        "queue_position": r["queue_position"],
        "status": r["status"],
        "upgrade_allocated": r["upgrade_allocated"],
        "upgrade_cost_share_usd": _f(r["upgrade_cost_share_usd"]),
        "last_upgrade_total_usd": _f(r["last_upgrade_total_usd"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def study_view(s):
    return {
        "id": s["id"],
        "request_id": s["request_id"],
        "phase": s["phase"],
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "status": s["status"],
        "rework_count": s["rework_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def offtake_view(o):
    return {
        "id": o["id"],
        "project_id": o["project_id"],
        "buyer_type": o["buyer_type"],
        "base_price_usd_mwh": _f(o["base_price_usd_mwh"]),
        "escalator_pct": _f(o["escalator_pct"]),
        "term_years": o["term_years"],
        "delivery_start_date": o["delivery_start_date"],
        "status": o["status"],
        "counter_count": o["counter_count"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def sa_view(s):
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "equipment_type": s["equipment_type"],
        "supplier_name": s["supplier_name"],
        "total_contract_usd": _f(s["total_contract_usd"]),
        "domestic_content_certified": s["domestic_content_certified"],
        "status": s["status"],
        "amendment_count": s["amendment_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def po_view(o):
    return {
        "id": o["id"],
        "supply_agreement_id": o["supply_agreement_id"],
        "order_amount_usd": _f(o["order_amount_usd"]),
        "safe_harbor_method": o["safe_harbor_method"],
        "eligible_cost_basis_usd": _f(o["eligible_cost_basis_usd"]),
        "deposit_paid_usd": _f(o["deposit_paid_usd"]),
        "safe_harbor_qualified": o["safe_harbor_qualified"],
        "physical_work_evidence_uri": o["physical_work_evidence_uri"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def milestone_view(m):
    return {
        "id": m["id"],
        "project_id": m["project_id"],
        "milestone_type": m["milestone_type"],
        "sequence_no": m["sequence_no"],
        "planned_date": m["planned_date"],
        "evidence_uri": m["evidence_uri"],
        "work_date": m["work_date"],
        "submitted_by_user_id": m["submitted_by_user_id"],
        "certified_by_user_id": m["certified_by_user_id"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def tcq_view(t):
    return {
        "id": t["id"],
        "project_id": t["project_id"],
        "status": t["status"],
        "continuity_variant": t["continuity_variant"],
        "safe_harbor_established_date": t["safe_harbor_established_date"],
        "lapse_date": t["lapse_date"],
        "lapse_count": t["lapse_count"],
        "credit_rate_pct": _f(t["credit_rate_pct"]),
        "qualified_credit_usd": _f(t["qualified_credit_usd"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def partnership_view(p, computed):
    return {
        "id": p["id"],
        "project_id": p["project_id"],
        "investor_name": p["investor_name"],
        "commitment_usd": _f(p["commitment_usd"]),
        "target_irr_pct": _f(p["target_irr_pct"]),
        "investor_pre_flip_share_pct": _f(p["investor_pre_flip_share_pct"]),
        "investor_post_flip_share_pct": _f(p["investor_post_flip_share_pct"]),
        "flip_date": p["flip_date"],
        "investor_irr_pct": _f(computed["investor_irr_pct"]),
        "contributed_usd": _f(computed["contributed_usd"]),
        "retained_cash_usd": _f(computed["retained_cash_usd"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ledger_view(e):
    return {
        "id": e["id"],
        "partnership_id": e["partnership_id"],
        "entry_type": e["entry_type"],
        "amount_usd": _f(e["amount_usd"]),
        "period_end_date": e["period_end_date"],
        "created_at": e["created_at"],
    }


def df_view(f):
    return {
        "id": f["id"],
        "project_id": f["project_id"],
        "commitment_usd": _f(f["commitment_usd"]),
        "drawn_usd": _f(f["drawn_usd"]),
        "interest_rate_pct": _f(f["interest_rate_pct"]),
        "projected_cfads_usd": _f(f["projected_cfads_usd"]),
        "min_dscr": _f(f["min_dscr"]),
        "term_debt_usd": _f(f["term_debt_usd"]),
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }
