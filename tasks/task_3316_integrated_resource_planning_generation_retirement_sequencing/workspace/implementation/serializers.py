"""Entity serializers: convert internal dicts to wire form.

Common fields per PRD §2.5:
  - Most entities carry id, created_at, updated_at, version.
  - Position, ReliabilitySnapshot, PlanDeviationReport carry only id and
    created_at (no updated_at, no version).
"""


def plan_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "plan_name": p["plan_name"],
        "cycle_year": p["cycle_year"],
        "planning_horizon_years": p["planning_horizon_years"],
        "status": p["status"],
        "comment_window_opens_on": p.get("comment_window_opens_on"),
        "comment_window_closes_on": p.get("comment_window_closes_on"),
        "submitted_on": p.get("submitted_on"),
        "approved_snapshot_id": p.get("approved_snapshot_id"),
        "preferred_portfolio_id": p.get("preferred_portfolio_id"),
        "reopen_count": p.get("reopen_count", 0),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def forecast_view(f: dict) -> dict:
    return {
        "id": f["id"],
        "plan_id": f["plan_id"],
        "scenario_tag": f["scenario_tag"],
        "forecast_year": f["forecast_year"],
        "residential_mw": f["residential_mw"],
        "commercial_mw": f["commercial_mw"],
        "industrial_mw": f["industrial_mw"],
        "electrification_mw": f["electrification_mw"],
        "total_peak_mw": f["total_peak_mw"],
        "effective_load_mw": f["effective_load_mw"],
        "locked": f["locked"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def resource_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "unit_name": r["unit_name"],
        "resource_type": r["resource_type"],
        "nameplate_mw": r["nameplate_mw"],
        "in_service_year": r["in_service_year"],
        "fuel_type": r["fuel_type"],
        "status": r["status"],
        "retirement_year": r.get("retirement_year"),
        "decision_year": r.get("decision_year"),
        "plan_id": r.get("plan_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def portfolio_view(pf: dict) -> dict:
    return {
        "id": pf["id"],
        "plan_id": pf["plan_id"],
        "portfolio_name": pf["portfolio_name"],
        "preferred_flag": pf["preferred_flag"],
        "status": pf["status"],
        "created_at": pf["created_at"],
        "updated_at": pf["updated_at"],
        "version": pf["version"],
    }


def candidate_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "candidate_name": c["candidate_name"],
        "resource_type": c["resource_type"],
        "nameplate_mw": c["nameplate_mw"],
        "online_year": c["online_year"],
        "capex_usd_per_kw": c["capex_usd_per_kw"],
        "fixed_om_usd_per_kw_year": c["fixed_om_usd_per_kw_year"],
        "fuel_type": c["fuel_type"],
        "build_lead_years": c["build_lead_years"],
        "global_sequence_index": c["global_sequence_index"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def position_view(pos: dict) -> dict:
    # Position: id + created_at only (no updated_at / version) per PRD §2.5.
    return {
        "id": pos["id"],
        "portfolio_id": pos["portfolio_id"],
        "candidate_id": pos["candidate_id"],
        "committed_mw": pos["committed_mw"],
        "selected": pos["selected"],
        "created_at": pos["created_at"],
    }


def snapshot_view(s: dict) -> dict:
    # ReliabilitySnapshot: id + created_at only.
    return {
        "id": s["id"],
        "portfolio_id": s["portfolio_id"],
        "forecast_year": s["forecast_year"],
        "scenario_tag": s["scenario_tag"],
        "fuel_price_usd_per_mmbtu": s["fuel_price_usd_per_mmbtu"],
        "variant": s.get("variant"),
        "accreditation_mode": s.get("accreditation_mode"),
        "capacity_margin_mw": s["capacity_margin_mw"],
        "accredited_supply_mw": s["accredited_supply_mw"],
        "load_mw": s["load_mw"],
        "meets_requirement": s["meets_requirement"],
        "retire_flagged": s.get("retire_flagged", False),
        "created_at": s["created_at"],
    }


def analysis_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "resource_id": a["resource_id"],
        "plan_id": a["plan_id"],
        "snapshot_id": a["snapshot_id"],
        "compliance_cost_usd": a["compliance_cost_usd"],
        "replacement_cost_usd": a["replacement_cost_usd"],
        "fixed_om_avoided_usd": a["fixed_om_avoided_usd"],
        "net_retirement_benefit_usd": a["net_retirement_benefit_usd"],
        "recommendation": a["recommendation"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def comment_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "plan_id": c["plan_id"],
        "commenter_name": c["commenter_name"],
        "commenter_email": c["commenter_email"],
        "body": c["body"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def intervenor_view(i: dict) -> dict:
    return {
        "id": i["id"],
        "legal_name": i["legal_name"],
        "party_type": i["party_type"],
        "standing_approved": i["standing_approved"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def testimony_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "plan_id": t["plan_id"],
        "intervenor_id": t["intervenor_id"],
        "topic": t["topic"],
        "body": t["body"],
        "volume_no": t["volume_no"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def sensitivity_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "plan_id": s["plan_id"],
        "snapshot_id": s["snapshot_id"],
        "dimension": s["dimension"],
        "delta_pct": s["delta_pct"],
        "scoring_variant": s.get("scoring_variant"),
        "adjusted_score_usd": s["adjusted_score_usd"],
        "base_score_usd": s["base_score_usd"],
        "robust_flag": s["robust_flag"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def commitment_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "plan_id": c["plan_id"],
        "candidate_id": c["candidate_id"],
        "committed_mw": c["committed_mw"],
        "solicitation_type": c["solicitation_type"],
        "created_by_user_id": c["created_by_user_id"],
        "condition_discharge_ids": list(c.get("condition_discharge_ids", [])),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def condition_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "plan_id": c["plan_id"],
        "description": c["description"],
        "required_procurement_mw": c["required_procurement_mw"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def deviation_report_view(r: dict) -> dict:
    # PlanDeviationReport: id + created_at only.
    return {
        "id": r["id"],
        "plan_id": r["plan_id"],
        "report_year": r["report_year"],
        "baseline_load_mw": r["baseline_load_mw"],
        "actual_load_mw": r["actual_load_mw"],
        "load_deviation_pct": r["load_deviation_pct"],
        "committed_procurement_mw": r["committed_procurement_mw"],
        "required_procurement_mw": r["required_procurement_mw"],
        "procurement_deviation_mw": r["procurement_deviation_mw"],
        "material_breach": r["material_breach"],
        "created_at": r["created_at"],
    }
