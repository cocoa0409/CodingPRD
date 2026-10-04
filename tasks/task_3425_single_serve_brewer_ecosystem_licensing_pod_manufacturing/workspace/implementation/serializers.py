"""Resource serializers — produce the exact public representation of each
entity, computing computed-on-read fields against the logical clock."""
from store import db
from calc import (
    variety_velocity, is_slow_mover, household_metrics, descale_overdue,
)


def brand_out(b):
    return {
        "id": b["id"], "name": b["name"], "kind": b["kind"],
        "home_region": b["home_region"], "created_at": b["created_at"],
        "updated_at": b["updated_at"], "version": b["version"],
    }


def agreement_out(a):
    return {
        "id": a["id"], "brand_id": a["brand_id"],
        "territory_code": a["territory_code"],
        "effective_start": a["effective_start"],
        "effective_end": a["effective_end"],
        "royalty_tiers": [dict(t) for t in a["royalty_tiers"]],
        "quality_min_cup_score": a["quality_min_cup_score"],
        "exclusive": a["exclusive"],
        "amendment_of_id": a["amendment_of_id"],
        "status": a["status"], "created_at": a["created_at"],
        "updated_at": a["updated_at"], "version": a["version"],
    }


def audit_out(a):
    return {
        "id": a["id"], "agreement_id": a["agreement_id"],
        "audited_at": a["audited_at"], "cup_score": a["cup_score"],
        "defect_rate_ppm": a["defect_rate_ppm"], "result": a["result"],
        "created_at": a["created_at"],
    }


def variety_out(v):
    return {
        "id": v["id"], "brand_id": v["brand_id"], "name": v["name"],
        "roast_level": v["roast_level"], "flavor_family": v["flavor_family"],
        "material": v["material"],
        "wholesale_price_cents": v["wholesale_price_cents"],
        "margin_cents": v["margin_cents"],
        "education_notices_sent": v["education_notices_sent"],
        "velocity_units_90d": variety_velocity(v),
        "slow_mover": is_slow_mover(v),
        "status": v["status"], "created_at": v["created_at"],
        "updated_at": v["updated_at"], "version": v["version"],
    }


def model_out(m):
    return {
        "id": m["id"], "model_code": m["model_code"],
        "firmware_compat": m["firmware_compat"],
        "warranty_months": m["warranty_months"],
        "descale_interval_brews": m["descale_interval_brews"],
        "msrp_cents": m["msrp_cents"], "unit_cost_cents": m["unit_cost_cents"],
        "subsidy_cents": m["subsidy_cents"], "margin_cents": m["margin_cents"],
        "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
    }


def facility_out(f):
    total = sum(l["capacity_pods_per_day"] for l in db["lines"].values()
                if l["facility_id"] == f["id"])
    return {
        "id": f["id"], "name": f["name"], "kind": f["kind"],
        "region": f["region"], "total_capacity_pods_per_day": total,
        "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"],
    }


def line_out(l):
    return {
        "id": l["id"], "facility_id": l["facility_id"],
        "line_code": l["line_code"], "supported_roast": l["supported_roast"],
        "supports_flavored": l["supports_flavored"],
        "material_capability": l["material_capability"],
        "capacity_pods_per_day": l["capacity_pods_per_day"],
        "changeover_hours": l["changeover_hours"],
        "created_at": l["created_at"], "updated_at": l["updated_at"],
        "version": l["version"],
    }


def run_out(r):
    return {
        "id": r["id"], "line_id": r["line_id"], "variety_id": r["variety_id"],
        "window_start": r["window_start"], "window_end": r["window_end"],
        "planned_units": r["planned_units"], "actual_units": r["actual_units"],
        "status": r["status"], "created_at": r["created_at"],
        "updated_at": r["updated_at"], "version": r["version"],
    }


def household_out(h):
    out = {"id": h["id"], "region": h["region"], "size": h["size"]}
    out.update(household_metrics(h))
    out.update({
        "created_at": h["created_at"], "updated_at": h["updated_at"],
        "version": h["version"],
    })
    return out


def brewer_out(b):
    return {
        "id": b["id"], "household_id": b["household_id"],
        "model_id": b["model_id"], "serial_number": b["serial_number"],
        "registered_at": b["registered_at"], "brew_count": b["brew_count"],
        "last_brew_at": b["last_brew_at"],
        "last_descaled_brew_count": b["last_descaled_brew_count"],
        "descale_overdue": descale_overdue(b),
        "warranty_status": b["warranty_status"],
        "operational": b["operational"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def consumption_out(c):
    return {
        "id": c["id"], "household_id": c["household_id"],
        "period": c["period"], "pods_brewed": c["pods_brewed"],
        "created_at": c["created_at"],
    }


def event_out(e):
    return {
        "id": e["id"], "brewer_id": e["brewer_id"], "kind": e["kind"],
        "note": e.get("note"), "status": e["status"],
        "resolution": e["resolution"], "resolved_at": e["resolved_at"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def account_out(a):
    return {
        "id": a["id"], "name": a["name"], "region": a["region"],
        "shelf_slots_total": a["shelf_slots_total"],
        "productivity_floor_cents": a["productivity_floor_cents"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def plan_out(p):
    return {
        "id": p["id"], "account_id": p["account_id"], "period": p["period"],
        "slots": [dict(s) for s in p["slots"]],
        "productivity_cents": p["productivity_cents"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def statement_out(s):
    return {
        "id": s["id"], "agreement_id": s["agreement_id"],
        "period": s["period"], "sell_in_units": s["sell_in_units"],
        "sell_through_units": s["sell_through_units"],
        "unlicensed_share_pct": s["unlicensed_share_pct"],
        "provisional_royalty_cents": s["provisional_royalty_cents"],
        "final_royalty_cents": s["final_royalty_cents"],
        "dispute_count": s["dispute_count"], "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }
