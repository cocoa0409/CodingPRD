"""Entity serializers. Decimal quantities serialize as JSON numbers; timestamps
as ISO-8601 UTC with three fractional digits. OffsetRetirement is the single
exception to the common-fields convention (PRD 2.4): id + created_at only, no
updated_at, no version. Internal keys (leading underscore) never leak."""
from decimal import Decimal

from util import fmt_dt


def num(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def _common(ent):
    return {
        "id": ent["id"],
        "created_at": fmt_dt(ent["created_at"]),
        "updated_at": fmt_dt(ent["updated_at"]),
        "version": ent["version"],
    }


def serialize_collection(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "pattern_code": c["pattern_code"],
        "backing_type": c["backing_type"],
        "lifecycle_boundary": c["lifecycle_boundary"],
        "claim_intent": c["claim_intent"],
        "status": c["status"],
    })
    return out


def serialize_batch(b):
    out = _common(b)
    out.update({
        "collection_id": b["collection_id"],
        "dye_lot_code": b["dye_lot_code"],
        "production_date": fmt_dt(b["production_date"]),
        "produced_m2": num(b["produced_m2"]),
        "mfg_intensity_kgco2e_per_m2": num(b["mfg_intensity_kgco2e_per_m2"]),
        "delta_e": num(b["delta_e"]),
        "feedstock_mix": [
            {"lot_id": e["lot_id"], "quantity_kg": num(e["quantity_kg"])}
            for e in b["feedstock_mix"]
        ],
        "allocated_mass_kg": num(b["allocated_mass_kg"]),
        "available_m2": num(b["available_m2"]),
        "recycled_content_pct": (
            num(b["recycled_content_pct"]) if b["recycled_content_pct"] is not None else None
        ),
        "embodied_carbon_kg_per_m2": (
            num(b["embodied_carbon_kg_per_m2"])
            if b["embodied_carbon_kg_per_m2"] is not None
            else None
        ),
        "status": b["status"],
    })
    return out


def serialize_lot(lot):
    out = _common(lot)
    out.update({
        "supplier_name": lot["supplier_name"],
        "source_type": lot["source_type"],
        "quantity_kg": num(lot["quantity_kg"]),
        "carbon_factor_kgco2e_per_kg": num(lot["carbon_factor_kgco2e_per_kg"]),
        "origin_takeback_id": lot["origin_takeback_id"],
        "supplier_reliability_pct": num(lot["supplier_reliability_pct"]),
        "available_kg": num(lot["available_kg"]),
        "allocated_kg": num(lot["allocated_kg"]),
        "status": lot["status"],
    })
    return out


def serialize_site(s):
    out = _common(s)
    out.update({
        "created_by": s["created_by"],
        "contractor_name": s["contractor_name"],
        "address": s["address"],
        "install_window_start": fmt_dt(s["install_window_start"]),
        "install_window_end": fmt_dt(s["install_window_end"]),
        "installation_system": s["installation_system"],
        "adhesive_free_certified": s["adhesive_free_certified"],
        "cert_expires_on": fmt_dt(s["cert_expires_on"]),
        "annual_replacement_budget_cents": s["annual_replacement_budget_cents"],
        "spent_replacement_cents": s["spent_replacement_cents"],
        "status": s["status"],
    })
    return out


def serialize_zone(z):
    out = _common(z)
    out.update({
        "site_id": z["site_id"],
        "batch_id": z["batch_id"],
        "zone_code": z["zone_code"],
        "area_m2": num(z["area_m2"]),
        "status": z["status"],
    })
    return out


def serialize_order(o):
    out = _common(o)
    out.update({
        "site_id": o["site_id"],
        "zone_id": o["zone_id"],
        "reason": o["reason"],
        "new_zone_code": o["new_zone_code"],
        "matched_batch_id": o["matched_batch_id"],
        "quoted_cost_cents": o["quoted_cost_cents"],
        "status": o["status"],
        "created_by": o["created_by"],
    })
    return out


def serialize_takeback(t):
    out = _common(t)
    out.update({
        "site_id": t["site_id"],
        "collection_id": t["collection_id"],
        "condition_grade": t["condition_grade"],
        "declared_area_m2": num(t["declared_area_m2"]),
        "pickup_window_start": fmt_dt(t["pickup_window_start"]),
        "pickup_window_end": fmt_dt(t["pickup_window_end"]),
        "collected_kg": num(t["collected_kg"]) if t["collected_kg"] is not None else None,
        "reuse_kg": num(t["reuse_kg"]) if t["reuse_kg"] is not None else None,
        "depolymerize_kg": num(t["depolymerize_kg"]) if t["depolymerize_kg"] is not None else None,
        "downcycle_kg": num(t["downcycle_kg"]) if t["downcycle_kg"] is not None else None,
        "landfill_kg": num(t["landfill_kg"]) if t["landfill_kg"] is not None else None,
        "credit_variant": t["credit_variant"],
        "credit_cents": t["credit_cents"],
        "credited_at": fmt_dt(t["credited_at"]),
        "status": t["status"],
        "created_by": t["created_by"],
    })
    return out


def serialize_report(r):
    out = _common(r)
    out.update({
        "collection_id": r["collection_id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "boundary": r["boundary"],
        "operational_kgco2e_per_m2": (
            num(r["operational_kgco2e_per_m2"])
            if r["operational_kgco2e_per_m2"] is not None
            else None
        ),
        "lifecycle_kgco2e_per_m2": (
            num(r["lifecycle_kgco2e_per_m2"])
            if r["lifecycle_kgco2e_per_m2"] is not None
            else None
        ),
        "submitted_by": r["submitted_by"],
        "verifier_org": r["verifier_org"],
        "verified_by": r["verified_by"],
        "status": r["status"],
    })
    return out


def serialize_claim(c):
    out = _common(c)
    out.update({
        "collection_id": c["collection_id"],
        "report_id": c["report_id"],
        "manufacturing_target_id": c["manufacturing_target_id"],
        "claim_type": c["claim_type"],
        "claimed_volume_m2": num(c["claimed_volume_m2"]),
        "boundary": c["boundary"],
        "required_offset_kgco2e": (
            num(c["required_offset_kgco2e"])
            if c["required_offset_kgco2e"] is not None
            else None
        ),
        "retired_kgco2e": num(c["retired_kgco2e"]),
        "offset_coverage": c["offset_coverage"],
        "created_by": c["created_by"],
        "reviewed_by": c["reviewed_by"],
        "status": c["status"],
    })
    return out


def serialize_offset(o):
    # Immutable event record: id + created_at only (PRD 2.4) — no updated_at,
    # no version.
    return {
        "id": o["id"],
        "created_at": fmt_dt(o["created_at"]),
        "claim_id": o["claim_id"],
        "registry": o["registry"],
        "vintage_year": o["vintage_year"],
        "quantity_kgco2e": num(o["quantity_kgco2e"]),
        "retired_at": fmt_dt(o["retired_at"]),
    }


def serialize_target(t):
    out = _common(t)
    out.update({
        "program_name": t["program_name"],
        "baseline_intensity_kgco2e_per_m2": num(t["baseline_intensity_kgco2e_per_m2"]),
        "target_reduction_pct": num(t["target_reduction_pct"]),
        "current_intensity_kgco2e_per_m2": num(t["current_intensity_kgco2e_per_m2"]),
        "posture": t["posture"],
        "readings_log": [
            {
                "period_end": fmt_dt(r["period_end"]),
                "intensity_kgco2e_per_m2": num(r["intensity_kgco2e_per_m2"]),
                "recorded_at": fmt_dt(r["recorded_at"]),
            }
            for r in t["readings_log"]
        ],
    })
    return out


def serialize_package(p):
    out = _common(p)
    out.update({
        "architect_firm": p["architect_firm"],
        "collection_id": p["collection_id"],
        "report_id": p["report_id"],
        "claim_id": p["claim_id"],
        "package_version": p["package_version"],
        "status": p["status"],
        "created_by": p["created_by"],
    })
    return out
