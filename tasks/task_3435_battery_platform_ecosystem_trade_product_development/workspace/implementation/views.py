"""Serializers. Common fields (id, created_at, updated_at, version) on every
entity; computed fields derived via services at read time; optional fields
rendered as null until set. Datetimes are stored as aware datetimes and
rendered with fmt_ts (3 fractional digits, Z)."""
import db
from helpers import fmt_ts
from services import (
    account_active_count,
    account_asset_limit,
    adopted_count,
    partner_active_allocation,
    partner_has_suspended,
    platform_current_generation,
    tool_best_runtime,
    tool_regulatory_count,
)


def _ts(dt):
    return fmt_ts(dt) if dt is not None else None


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def view_platform(p):
    out = {
        "code": p["code"],
        "interface_key": p["interface_key"],
        "chemistry_family": p["chemistry_family"],
        "backward_commitment_years": p["backward_commitment_years"],
        "forward_commitment_generations": p["forward_commitment_generations"],
        "sunset_announce_date": _ts(p.get("sunset_announce_date")),
        "sunset_date": _ts(p.get("sunset_date")),
        "status": p["status"],
        "current_generation": platform_current_generation(p["id"]),
    }
    out.update(_common(p))
    return out


def view_pack(p, extra=None):
    out = {
        "platform_id": p["platform_id"],
        "sku": p["sku"],
        "pack_generation": p["pack_generation"],
        "cell_supplier_code": p["cell_supplier_code"],
        "cell_format": p["cell_format"],
        "rated_capacity_wh": p["rated_capacity_wh"],
        "max_charge_rate_w": p["max_charge_rate_w"],
        "replacement_price_cents": p["replacement_price_cents"],
        "warranty_days": p["warranty_days"],
        "free_replacement_days": p["free_replacement_days"],
        "certification_status": p["certification_status"],
        "submitted_by_user_id": p.get("submitted_by_user_id"),
        "safety_hold": p["safety_hold"],
    }
    if extra:
        out.update(extra)  # charger_compatible / charge_estimate_minutes
    out.update(_common(p))
    return out


def view_charger(c):
    out = {
        "platform_id": c["platform_id"],
        "model_code": c["model_code"],
        "charger_generation": c["charger_generation"],
        "max_charge_rate_w": c["max_charge_rate_w"],
    }
    out.update(_common(c))
    return out


def view_tool(t):
    out = {
        "platform_id": t["platform_id"],
        "model_code": t["model_code"],
        "trade": t["trade"],
        "category": t["category"],
        "tier": t["tier"],
        "corded_conversion": t["corded_conversion"],
        "avg_power_draw_w": t["avg_power_draw_w"],
        "runtime_target_min": t.get("runtime_target_min"),
        "min_pack_generation": t["min_pack_generation"],
        "max_pack_generation": t["max_pack_generation"],
        "replacement_price_cents": t["replacement_price_cents"],
        "warranty_days": t["warranty_days"],
        "free_replacement_days": t["free_replacement_days"],
        "torque_min_nm": t["torque_min_nm"],
        "torque_max_nm": t["torque_max_nm"],
        "stage": t["stage"],
        "adopted_field_research_count": adopted_count(t["id"], "FIELD_RESEARCH"),
        "adopted_jobsite_observation_count": adopted_count(t["id"], "JOBSITE_OBSERVATION"),
        "regulatory_compatible_pack_count": tool_regulatory_count(t),
        "best_runtime_min": tool_best_runtime(t),
    }
    out.update(_common(t))
    return out


def view_insight(i):
    out = {
        "tool_model_id": i["tool_model_id"],
        "kind": i["kind"],
        "summary": i["summary"],
        "severity": i["severity"],
        "status": i["status"],
        "submitted_by_user_id": i["submitted_by_user_id"],
    }
    out.update(_common(i))
    return out


def view_center(c):
    out = {
        "code": c["code"],
        "region": c["region"],
        "capabilities": list(c["capabilities"]),
        "daily_capacity": c["daily_capacity"],
    }
    out.update(_common(c))
    return out


def view_account(a):
    out = {
        "org_name": a["org_name"],
        "tier": a["tier"],
        "asset_limit": account_asset_limit(a),
        "active_asset_count": account_active_count(a["id"]),
    }
    out.update(_common(a))
    return out


def view_asset(a):
    out = {
        "account_id": a["account_id"],
        "subject_type": a["subject_type"],
        "tool_model_id": a.get("tool_model_id"),
        "battery_pack_id": a.get("battery_pack_id"),
        "serial_number": a["serial_number"],
        "manufactured_at": _ts(a["manufactured_at"]),
        "first_paired_at": _ts(a["first_paired_at"]),
        "status": a["status"],
        "custom_torque_limit_nm": a.get("custom_torque_limit_nm"),
        "anti_theft_lock_enabled": a["anti_theft_lock_enabled"],
        "is_replacement_unit": a["is_replacement_unit"],
    }
    out.update(_common(a))
    return out


def view_claim(c):
    out = {
        "tracked_asset_id": c["tracked_asset_id"],
        "claim_type": c["claim_type"],
        "fault_code": c["fault_code"],
        "service_date": c["service_date"],
        "service_center_id": c["service_center_id"],
        "adjudication_status": c["adjudication_status"],
        "fulfillment_status": c["fulfillment_status"],
        "age_basis": c.get("age_basis"),
        "age_days": c.get("age_days"),
        "coverage": c.get("coverage"),
        "credit_cents": c.get("credit_cents"),
        "decided_by_user_id": c.get("decided_by_user_id"),
    }
    out.update(_common(c))
    return out


def view_partner(p):
    out = {
        "name": p["name"],
        "channel_type": p["channel_type"],
        "region": p["region"],
        "has_suspended_listings": partner_has_suspended(p["id"]),
        "active_allocation_total": partner_active_allocation(p["id"]),
    }
    out.update(_common(p))
    return out


def view_listing(l):
    partner = db.STORE["partners"].get(l["channel_partner_id"])
    out = {
        "channel_partner_id": l["channel_partner_id"],
        "tool_model_id": l.get("tool_model_id"),
        "battery_pack_id": l.get("battery_pack_id"),
        "charger_id": l.get("charger_id"),
        "wholesale_price_cents": l["wholesale_price_cents"],
        "allocation_qty": l["allocation_qty"],
        "status": l["status"],
        "requires_relist_ack": l["requires_relist_ack"],
        "superseded_by_listing_id": l.get("superseded_by_listing_id"),
        "channel_partner_version": partner["version"] if partner else None,
    }
    out.update(_common(l))
    return out


def view_case(c):
    out = {
        "battery_pack_id": c["battery_pack_id"],
        "reported_serial": c["reported_serial"],
        "detection_method": c["detection_method"],
        "status": c["status"],
        "evidence_score": c.get("evidence_score"),
        "created_by_user_id": c["created_by_user_id"],
        "resolved_by_user_id": c.get("resolved_by_user_id"),
    }
    out.update(_common(c))
    return out


def view_bulletin(b):
    out = {
        "platform_id": b["platform_id"],
        "battery_pack_ids": list(b["battery_pack_ids"]),
        "severity": b["severity"],
        "title": b["title"],
        "effective_from": _ts(b["effective_from"]),
        "effective_to": _ts(b.get("effective_to")),
        "supersedes_bulletin_id": b.get("supersedes_bulletin_id"),
        "status": b["status"],
    }
    out.update(_common(b))
    return out
