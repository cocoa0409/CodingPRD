"""Entity serializers. Datetimes serialize as ISO 8601 UTC with three
fractional digits (PRD 2.2); date-typed inputs echo their raw YYYY-MM-DD
string; the audit's scheduled_for echoes its raw input string. Internal
fields (``_seq``, ``_scheduled_dt``, ``_start``/``_end``, ``_week_start``,
``_carton_seq``) never leave the server. Cartons and forecasts carry only
``id`` + ``created_at`` system fields (PRD 2.4).
"""
from clock import iso_ms
from domain import derive_certification_status


def _ts(dt):
    return iso_ms(dt) if dt is not None else None


def farm_out(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "region": f["region"],
        "pasture_sqft": f["pasture_sqft"],
        "barn_sqft": f["barn_sqft"],
        "nest_box_count": f["nest_box_count"],
        "declared_bird_count": f["declared_bird_count"],
        "status": f["status"],
        "certification_status": derive_certification_status(f),
        "effective_bird_capacity": f["effective_bird_capacity"],
        "last_passed_audit_at": _ts(f["last_passed_audit_at"]),
        "removal_reason": f["removal_reason"],
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def contract_out(c):
    return {
        "id": c["id"],
        "farm_id": c["farm_id"],
        "commodity_base_cents_per_dozen": c["commodity_base_cents_per_dozen"],
        "premium_cents_per_dozen": c["premium_cents_per_dozen"],
        "start_date": c["start_date"],
        "end_date": c["end_date"],
        "status": c["status"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def audit_out(a):
    return {
        "id": a["id"],
        "farm_id": a["farm_id"],
        "audit_type": a["audit_type"],
        "scheduled_for": a["scheduled_for"],
        "status": a["status"],
        "auditor_user_id": a["auditor_user_id"],
        "non_conformities_count": a["non_conformities_count"],
        "completed_at": _ts(a["completed_at"]),
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def ca_out(ca):
    return {
        "id": ca["id"],
        "audit_id": ca["audit_id"],
        "severity": ca["severity"],
        "description": ca["description"],
        "status": ca["status"],
        "due_at": _ts(ca["due_at"]),
        "evidence_notes": ca["evidence_notes"],
        "verified_by_user_id": ca["verified_by_user_id"],
        "closed_at": _ts(ca["closed_at"]),
        "created_at": _ts(ca["created_at"]),
        "updated_at": _ts(ca["updated_at"]),
        "version": ca["version"],
    }


def incident_out(i):
    return {
        "id": i["id"],
        "farm_id": i["farm_id"],
        "severity": i["severity"],
        "incident_type": i["incident_type"],
        "description": i["description"],
        "status": i["status"],
        "disposition": i["disposition"],
        "resolved_at": _ts(i["resolved_at"]),
        "created_at": _ts(i["created_at"]),
        "updated_at": _ts(i["updated_at"]),
        "version": i["version"],
    }


def stop_out(s):
    return {
        "stop_sequence": s["stop_sequence"],
        "farm_id": s["farm_id"],
        "planned_cases": s["planned_cases"],
        "collected_cases": s["collected_cases"],
        "status": s["status"],
    }


def route_out(r):
    return {
        "id": r["id"],
        "route_date": r["route_date"],
        "driver_name": r["driver_name"],
        "capacity_cases": r["capacity_cases"],
        "status": r["status"],
        "stops": [stop_out(s) for s in r["stops"]],
        "committed_cases": r["committed_cases"],
        "available_cases": r["available_cases"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def lot_out(lot):
    return {
        "id": lot["id"],
        "farm_id": lot["farm_id"],
        "route_id": lot["route_id"],
        "stop_sequence": lot["stop_sequence"],
        "lot_code": lot["lot_code"],
        "laid_start_date": lot["laid_start_date"],
        "laid_end_date": lot["laid_end_date"],
        "received_cases": lot["received_cases"],
        "received_dozens": lot["received_dozens"],
        "quality_score": lot["quality_score"],
        "grade": lot["grade"],
        "status": lot["status"],
        "remaining_dozens": lot["remaining_dozens"],
        "packed_dozens": lot["packed_dozens"],
        "destroyed_dozens": lot["destroyed_dozens"],
        "graded_at": _ts(lot["graded_at"]),
        "created_at": _ts(lot["created_at"]),
        "updated_at": _ts(lot["updated_at"]),
        "version": lot["version"],
    }


def carton_out(c):
    # Immutable record: only id + created_at system fields (PRD 2.4).
    return {
        "id": c["id"],
        "carton_code": c["carton_code"],
        "lot_id": c["lot_id"],
        "pack_size": c["pack_size"],
        "dozens": c["dozens"],
        "source_farm_id": c["source_farm_id"],
        "source_farm_name": c["source_farm_name"],
        "packed_at": _ts(c["packed_at"]),
        "created_at": _ts(c["created_at"]),
    }


def retailer_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "banner": r["banner"],
        "terms_net_days": r["terms_net_days"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def commitment_out(cm):
    return {
        "id": cm["id"],
        "farm_id": cm["farm_id"],
        "retailer_id": cm["retailer_id"],
        "week_start": cm["week_start"],
        "committed_dozens": cm["committed_dozens"],
        "status": cm["status"],
        "delivered_dozens": cm["delivered_dozens"],
        "fill_rate": cm["fill_rate"],
        "created_at": _ts(cm["created_at"]),
        "updated_at": _ts(cm["updated_at"]),
        "version": cm["version"],
    }


def forecast_out(f):
    # Immutable record: only id + created_at system fields (PRD 2.4).
    return {
        "id": f["id"],
        "farm_id": f["farm_id"],
        "week_start": f["week_start"],
        "season": f["season"],
        "weather_severity": f["weather_severity"],
        "optimistic_dozens": f["optimistic_dozens"],
        "conservative_dozens": f["conservative_dozens"],
        "created_at": _ts(f["created_at"]),
    }


def settlement_out(s):
    return {
        "id": s["id"],
        "week_start": s["week_start"],
        "status": s["status"],
        "lines": [dict(line) for line in s["lines"]],
        "provisional_total_cents": s["provisional_total_cents"],
        "final_total_cents": s["final_total_cents"],
        "actual_commodity_base_cents_per_dozen": s["actual_commodity_base_cents_per_dozen"],
        "finalized_at": _ts(s["finalized_at"]),
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }
