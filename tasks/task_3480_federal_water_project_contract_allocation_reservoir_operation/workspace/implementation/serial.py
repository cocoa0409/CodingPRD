"""Entity serializers: internal records -> wire dictionaries (PRD section 2.5).

Datetimes serialize as ISO 8601 UTC with three fractional digits. MWh figures
serialize as JSON numbers (two-decimal precision is applied at computation).
HydrologyObservation carries only id + created_at (no updated_at / version).
"""
from store import DB, fmt_dt


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def _dt_or_none(value):
    return fmt_dt(value) if value is not None else None


def district_view(d):
    out = _base(d)
    out.update({
        "name": d["name"],
        "service_area_acres": d["service_area_acres"],
        "contact_email": d["contact_email"],
    })
    return out


def contract_view(c):
    out = _base(c)
    out.update({
        "district_id": c["district_id"],
        "contract_number": c["contract_number"],
        "priority_class": c["priority_class"],
        "max_annual_quantity_af": c["max_annual_quantity_af"],
        "repayment_obligation_cents": c["repayment_obligation_cents"],
        "repaid_credits_cents": c["repaid_credits_cents"],
        "status": c["status"],
    })
    return out


def water_year_view(y):
    out = _base(y)
    out.update({
        "label": y["label"],
        "season_start": fmt_dt(y["season_start"]),
        "season_end": fmt_dt(y["season_end"]),
        "status": y["status"],
        "current_announcement_id": y["current_announcement_id"],
    })
    return out


def observation_view(o):
    return {
        "id": o["id"],
        "created_at": fmt_dt(o["created_at"]),
        "water_year_id": o["water_year_id"],
        "observation_type": o["observation_type"],
        "value": o["value"],
        "observed_on": fmt_dt(o["observed_on"]),
    }


def announcement_view(a):
    out = _base(a)
    out.update({
        "water_year_id": a["water_year_id"],
        "sequence_number": a["sequence_number"],
        "status": a["status"],
        "declared_supply_af": a["declared_supply_af"],
        "shortage_tier": a["shortage_tier"],
        "allocation_basis": a["allocation_basis"],
        "published_at": _dt_or_none(a["published_at"]),
    })
    return out


def line_view(line):
    out = _base(line)
    out.update({
        "announcement_id": line["announcement_id"],
        "contract_id": line["contract_id"],
        "allocated_af": line["allocated_af"],
        "delivered_af": line["delivered_af"],
        "transfer_in_af": line["transfer_in_af"],
        "transfer_out_af": line["transfer_out_af"],
        "remaining_af": line["remaining_af"],
    })
    return out


def reservoir_view(r):
    open_count = sum(
        1 for i in DB["incidents"].values()
        if i["reservoir_id"] == r["id"] and i["status"] == "OPEN")
    total_obligation = sum(c["repayment_obligation_cents"] for c in DB["contracts"].values())
    repaid = sum(c["repaid_credits_cents"] for c in DB["contracts"].values())
    out = _base(r)
    out.update({
        "name": r["name"],
        "capacity_af": r["capacity_af"],
        "dead_pool_af": r["dead_pool_af"],
        "flood_control_max_storage_af": r["flood_control_max_storage_af"],
        "initial_storage_af": r["initial_storage_af"],
        "current_storage_af": r["current_storage_af"],
        "outlet_capacity_cfs": r["outlet_capacity_cfs"],
        "power_conversion_mwh_per_af": float(r["power_conversion_mwh_per_af"]),
        "compliance_posture": "COMPLIANCE_HOLD" if open_count > 0 else "NORMAL",
        "open_incident_count": open_count,
        "total_repayment_obligation_cents": total_obligation,
        "unrecovered_balance_cents": total_obligation - repaid,
    })
    return out


def release_view(ro):
    out = _base(ro)
    out.update({
        "reservoir_id": ro["reservoir_id"],
        "purpose": ro["purpose"],
        "release_cfs": ro["release_cfs"],
        "duration_days": ro["duration_days"],
        "scheduled_start": fmt_dt(ro["scheduled_start"]),
        "scheduled_end": fmt_dt(ro["scheduled_end"]),
        "volume_af": ro["volume_af"],
        "status": ro["status"],
        "executed_at": _dt_or_none(ro["executed_at"]),
    })
    return out


def constraint_view(c):
    out = _base(c)
    out.update({
        "reservoir_id": c["reservoir_id"],
        "species": c["species"],
        "requirement_type": c["requirement_type"],
        "required_min_cfs": c["required_min_cfs"],
        "max_release_cfs": c["max_release_cfs"],
        "enforce_start": fmt_dt(c["enforce_start"]),
        "enforce_end": fmt_dt(c["enforce_end"]),
    })
    return out


def incident_view(i):
    out = _base(i)
    out.update({
        "reservoir_id": i["reservoir_id"],
        "constraint_id": i["constraint_id"],
        "release_order_id": i["release_order_id"],
        "deficit_cfs": i["deficit_cfs"],
        "status": i["status"],
        "resolution": i["resolution"],
    })
    return out


def order_view(o):
    out = _base(o)
    out.update({
        "contract_id": o["contract_id"],
        "water_year_id": o["water_year_id"],
        "allocation_line_id": o["allocation_line_id"],
        "ordered_af": o["ordered_af"],
        "delivered_af": o["delivered_af"],
        "fulfillment_status": o["fulfillment_status"],
        "compliance_status": o["compliance_status"],
    })
    return out


def period_view(p):
    out = _base(p)
    out.update({
        "reservoir_id": p["reservoir_id"],
        "period_month": p["period_month"],
        "rate_cents_per_mwh": p["rate_cents_per_mwh"],
        "projected_mwh": float(p["projected_mwh"]),
        "projected_revenue_cents": p["projected_revenue_cents"],
        "settled_mwh": float(p["settled_mwh"]) if p["settled_mwh"] is not None else None,
        "settled_revenue_cents": p["settled_revenue_cents"],
        "status": p["status"],
    })
    return out


def transfer_view(t):
    out = _base(t)
    out.update({
        "from_contract_id": t["from_contract_id"],
        "to_contract_id": t["to_contract_id"],
        "water_year_id": t["water_year_id"],
        "quantity_af": t["quantity_af"],
        "price_cents": t["price_cents"],
        "status": t["status"],
        "revision_count": t["revision_count"],
        "objection_window_end": _dt_or_none(t["objection_window_end"]),
        "executed_at": _dt_or_none(t["executed_at"]),
    })
    return out


def review_view(rv):
    out = _base(rv)
    out.update({
        "transfer_request_id": rv["transfer_request_id"],
        "reviewer_district_id": rv["reviewer_district_id"],
        "claimed_impact_af": rv["claimed_impact_af"],
        "basis": rv["basis"],
        "status": rv["status"],
        "resolution_rationale": rv["resolution_rationale"],
    })
    return out


def agreement_view(a):
    out = _base(a)
    out.update({
        "name": a["name"],
        "tier_1_senior_pct": a["tier_1_senior_pct"],
        "tier_1_junior_pct": a["tier_1_junior_pct"],
        "tier_2_senior_pct": a["tier_2_senior_pct"],
        "tier_2_junior_pct": a["tier_2_junior_pct"],
        "quorum_district_count": a["quorum_district_count"],
        "signatory_district_ids": list(a["signatory_district_ids"]),
        "status": a["status"],
        "activated_water_year_label": a["activated_water_year_label"],
    })
    return out
