"""Entity serializers: internal dicts -> API JSON representations.

Append-only records (verification, safety review, exclusion window, delay
event) expose only id + created_at, never updated_at/version (PRD §2.5).
"""
from util import fmt_ts, num_out


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def _append_only(e):
    return {"id": e["id"], "created_at": fmt_ts(e["created_at"])}


def ser_customer(c):
    d = _common(c)
    d.update({
        "org_name": c["org_name"],
        "contact_email": c["contact_email"],
        "default_rebookings": c["default_rebookings"],
    })
    return d


def ser_mission(m):
    d = _common(m)
    d.update({
        "mission_name": m["mission_name"],
        "target_orbit": m["target_orbit"],
        "window_open_utc": fmt_ts(m["window_open_utc"]),
        "window_close_utc": fmt_ts(m["window_close_utc"]),
        "mass_capacity_kg": num_out(m["mass_capacity_kg"]),
        "volume_capacity_m3": num_out(m["volume_capacity_m3"]),
        "committed_mass_kg": num_out(m["committed_mass_kg"]),
        "committed_volume_m3": num_out(m["committed_volume_m3"]),
        "firm_mass_kg": num_out(m["firm_mass_kg"]),
        "integration_revenue_cents": m["integration_revenue_cents"],
        "revenue_estimate_cents": m["revenue_estimate_cents"],
        "status": m["status"],
    })
    return d


def ser_dispenser_port(p):
    d = _common(p)
    d.update({
        "mission_id": p["mission_id"],
        "port_code": p["port_code"],
        "stack_position": p["stack_position"],
        "max_mass_kg": num_out(p["max_mass_kg"]),
        "supported_interface_classes": list(p["supported_interface_classes"]),
    })
    return d


def ser_contract(c):
    d = _common(c)
    d.update({
        "customer_id": c["customer_id"],
        "target_mission_id": c["target_mission_id"],
        "pricing_mode": c["pricing_mode"],
        "window_open_utc": fmt_ts(c["window_open_utc"]),
        "window_close_utc": fmt_ts(c["window_close_utc"]),
        "rebookings_remaining": c["rebookings_remaining"],
        "quoted_price_cents": c["quoted_price_cents"],
        "total_rebooking_fees_cents": c["total_rebooking_fees_cents"],
        "rebook_eligible": c["rebook_eligible"],
        "status": c["status"],
    })
    return d


def ser_payload(p):
    d = _common(p)
    d.update({
        "contract_id": p["contract_id"],
        "payload_name": p["payload_name"],
        "mass_kg": num_out(p["mass_kg"]),
        "volume_m3": num_out(p["volume_m3"]),
        "interface_class": p["interface_class"],
        "required_orbit": p["required_orbit"],
        "status": p["status"],
    })
    return d


def ser_assignment(a):
    d = _common(a)
    d.update({
        "mission_id": a["mission_id"],
        "payload_id": a["payload_id"],
        "dispenser_port_id": a["dispenser_port_id"],
        "integration_fee_cents": a["integration_fee_cents"],
        "status": a["status"],
    })
    return d


def ser_verification(v):
    d = _append_only(v)
    d.update({
        "assignment_id": v["assignment_id"],
        "check_type": v["check_type"],
        "outcome": v["outcome"],
        "notes": v["notes"],
        "created_by_user_id": v["created_by_user_id"],
    })
    return d


def ser_safety_review(r):
    d = _append_only(r)
    d.update({
        "assignment_id": r["assignment_id"],
        "decision": r["decision"],
        "rationale": r["rationale"],
        "created_by_user_id": r["created_by_user_id"],
    })
    return d


def ser_license(lic):
    d = _common(lic)
    d.update({
        "subject_type": lic["subject_type"],
        "mission_id": lic["mission_id"],
        "customer_id": lic["customer_id"],
        "kind": lic["kind"],
        "debris_score": lic["debris_score"],
        "spectrum_score": lic["spectrum_score"],
        "operator_history_score": lic["operator_history_score"],
        "composite_score": lic["composite_score"],
        "valid_until": fmt_ts(lic["valid_until"]),
        "status": lic["status"],
    })
    return d


def ser_range_slot(s):
    d = _common(s)
    d.update({
        "mission_id": s["mission_id"],
        "range_code": s["range_code"],
        "window_open_utc": fmt_ts(s["window_open_utc"]),
        "window_close_utc": fmt_ts(s["window_close_utc"]),
        "status": s["status"],
    })
    return d


def ser_exclusion_window(w):
    d = _append_only(w)
    d.update({
        "scope_type": w["scope_type"],
        "scope_value": w["scope_value"],
        "kind": w["kind"],
        "start_utc": fmt_ts(w["start_utc"]),
        "end_utc": fmt_ts(w["end_utc"]),
    })
    return d


def ser_delay_event(ev):
    d = _append_only(ev)
    d.update({
        "mission_id": ev["mission_id"],
        "previous_window_open_utc": fmt_ts(ev["previous_window_open_utc"]),
        "previous_window_close_utc": fmt_ts(ev["previous_window_close_utc"]),
        "new_window_open_utc": fmt_ts(ev["new_window_open_utc"]),
        "new_window_close_utc": fmt_ts(ev["new_window_close_utc"]),
        "reason_code": ev["reason_code"],
        "slot_released": ev["slot_released"],
        "assignments_removed_count": ev["assignments_removed_count"],
    })
    return d


def ser_separation_event(ev):
    d = _common(ev)
    d.update({
        "mission_id": ev["mission_id"],
        "assignment_id": ev["assignment_id"],
        "sequence_index": ev["sequence_index"],
        "offset_seconds": ev["offset_seconds"],
        "status": ev["status"],
    })
    return d


def ser_anomaly(a):
    d = _common(a)
    d.update({
        "mission_id": a["mission_id"],
        "category": a["category"],
        "severity": a["severity"],
        "status": a["status"],
        "disposition": a["disposition"],
        "resolution_notes": a["resolution_notes"],
    })
    return d
