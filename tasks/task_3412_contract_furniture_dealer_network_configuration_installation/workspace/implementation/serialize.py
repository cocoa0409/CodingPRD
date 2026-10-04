# Resource serializers: full field surface per scaffold entity tables.
import calc


def dealer(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "territory_codes": d["territory_codes"],
        "service_capability_level": d["service_capability_level"],
        "showroom_compliant": d["showroom_compliant"],
        "status": d["status"],
        "suspended_at": d["suspended_at"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def end_user(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "industry": e["industry"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def agreement(a):
    # Computed ledger fields are derived on read (PRD 3.2).
    cumulative = calc.agreement_cumulative_cents(a["id"])
    return {
        "id": a["id"],
        "end_user_id": a["end_user_id"],
        "effective_start": a["effective_start"],
        "effective_end": a["effective_end"],
        "tier1_discount_pct": a["tier1_discount_pct"],
        "tier2_discount_pct": a["tier2_discount_pct"],
        "tier3_discount_pct": a["tier3_discount_pct"],
        "status": a["status"],
        "cumulative_volume_cents": cumulative,
        "current_tier": calc.tier_for_basis(cumulative),
        "activated_at": a["activated_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def family(f):
    return {
        "id": f["id"],
        "family_code": f["family_code"],
        "name": f["name"],
        "category": f["category"],
        "base_lead_time_days": f["base_lead_time_days"],
        "lifecycle_status": f["lifecycle_status"],
        "last_order_date": f["last_order_date"],
        "discontinued_at": f["discontinued_at"],
        "parts_support_until": f["parts_support_until"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def configuration(c):
    return {
        "id": c["id"],
        "dealer_id": c["dealer_id"],
        "name": c["name"],
        "modules": c["modules"],
        "status": c["status"],
        "revision_number": c["revision_number"],
        "total_units": c["total_units"],
        "list_total_cents": c["list_total_cents"],
        "max_lead_time_days": c["max_lead_time_days"],
        "locked_at": c["locked_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def order(o):
    return {
        "id": o["id"],
        "dealer_id": o["dealer_id"],
        "volume_agreement_id": o["volume_agreement_id"],
        "configuration_id": o["configuration_id"],
        "configuration_revision": o["configuration_revision"],
        "territory_code": o["territory_code"],
        "requested_install_date": o["requested_install_date"],
        "status": o["status"],
        "pre_discount_total_cents": o["pre_discount_total_cents"],
        "provisional_tier": o["provisional_tier"],
        "provisional_total_cents": o["provisional_total_cents"],
        "final_tier": o["final_tier"],
        "final_total_cents": o["final_total_cents"],
        "submitted_at": o["submitted_at"],
        "acknowledged_at": o["acknowledged_at"],
        "cancelled_at": o["cancelled_at"],
        "cancel_reason": o["cancel_reason"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def phase(p):
    return {
        "id": p["id"],
        "project_order_id": p["project_order_id"],
        "floor_number": p["floor_number"],
        "phase_sequence": p["phase_sequence"],
        "building_zone_id": p["building_zone_id"],
        "planned_units": p["planned_units"],
        "logistics_status": p["logistics_status"],
        "install_status": p["install_status"],
        "plant_code": p["plant_code"],
        "production_date": p["production_date"],
        "delivered_at": p["delivered_at"],
        "install_started_at": p["install_started_at"],
        "actual_install_complete_date": p["actual_install_complete_date"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def window(w):
    return {
        "id": w["id"],
        "installation_phase_id": w["installation_phase_id"],
        "building_zone_id": w["building_zone_id"],
        "start_at": w["start_at"],
        "end_at": w["end_at"],
        "union_required": w["union_required"],
        "elevator_required": w["elevator_required"],
        "crew_size": w["crew_size"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def punch(t):
    return {
        "id": t["id"],
        "installation_phase_id": t["installation_phase_id"],
        "severity": t["severity"],
        "description": t["description"],
        "requires_part": t["requires_part"],
        "part_number": t["part_number"],
        "status": t["status"],
        "resolution_note": t["resolution_note"],
        "escalated": calc.punch_escalated(t),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def claim(c):
    return {
        "id": c["id"],
        "project_order_id": c["project_order_id"],
        "installation_phase_id": c["installation_phase_id"],
        "punch_ticket_id": c["punch_ticket_id"],
        "claim_type": c["claim_type"],
        "part_number": c["part_number"],
        "description": c["description"],
        "status": c["status"],
        "filed_date": c["filed_date"],
        "review_note": c["review_note"],
        "reviewed_at": c["reviewed_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
