"""Entity construction, serialization, and cross-entity side effects."""
import uuid
from datetime import timedelta
from db import store, clock, fmt_iso
import calculations as calc

COMMON_ENTITIES = (
    "families", "parents", "children", "devices", "connections", "content_items",
    "alerts", "escalation_cases", "screen_time_windows", "filter_rules",
    "bypass_events", "access_grants", "districts", "district_links",
)


def new_entity():
    now = clock.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": fmt_iso(now),
        "updated_at": fmt_iso(now),
        "version": 1,
    }


def touch(entity):
    entity["updated_at"] = fmt_iso(clock.now())
    entity["version"] = int(entity.get("version", 1)) + 1


def bump(entity):
    """Timestamp-only refresh for computed-field updates (no version increment)."""
    entity["updated_at"] = fmt_iso(clock.now())


# ---------------------------------------------------------------- serializers

def ser_family(f):
    return {
        "id": f["id"],
        "family_name": f["family_name"],
        "primary_contact_email": f["primary_contact_email"],
        "subscription_tier": f["subscription_tier"],
        "analysis_variant": f["analysis_variant"],
        "account_status": f["account_status"],
        "device_limit": f["device_limit"],
        "device_count": f["device_count"],
        "open_escalation_count": f["open_escalation_count"],
        "last_proration_charge_cents": f["last_proration_charge_cents"],
        "billing_period_start": f["billing_period_start"],
        "billing_period_end": f["billing_period_end"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_parent(p):
    return {
        "id": p["id"],
        "family_account_id": p["family_account_id"],
        "display_name": p["display_name"],
        "email": p["email"],
        "is_primary": p["is_primary"],
        "member_status": p["member_status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_child(c):
    return {
        "id": c["id"],
        "family_account_id": c["family_account_id"],
        "display_name": c["display_name"],
        "birth_year": c["birth_year"],
        "age_band": c["age_band"],
        "monitoring_sensitivity": c["monitoring_sensitivity"],
        "profile_status": c["profile_status"],
        "open_alert_count": c["open_alert_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_device(d):
    return {
        "id": d["id"],
        "child_profile_id": d["child_profile_id"],
        "platform": d["platform"],
        "nickname": d["nickname"],
        "pairing_status": d["pairing_status"],
        "device_posture": d["device_posture"],
        "bypass_strike_count": d["bypass_strike_count"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_connection(c):
    # credential_token is write-only; never serialized
    return {
        "id": c["id"],
        "child_profile_id": c["child_profile_id"],
        "service_type": c["service_type"],
        "external_handle": c["external_handle"],
        "consent_status": c["consent_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_content_item(ci, include_raw=True):
    out = {
        "id": ci["id"],
        "service_connection_id": ci["service_connection_id"],
        "occurred_at": ci["occurred_at"],
        "direction": ci["direction"],
        "thread_depth": ci["thread_depth"],
        "signals": ci["signals"],
        "analysis_variant_used": ci["analysis_variant_used"],
        "risk_score": ci["risk_score"],
        "severity": ci["severity"],
        "alert_created": ci["alert_created"],
        "alert_id": ci["alert_id"],
        "created_at": ci["created_at"],
        "updated_at": ci["updated_at"],
        "version": ci["version"],
    }
    if include_raw:
        out["raw_text"] = ci["raw_text"]
    return out


def ser_alert(a):
    return {
        "id": a["id"],
        "child_profile_id": a["child_profile_id"],
        "content_item_id": a["content_item_id"],
        "category": a["category"],
        "severity": a["severity"],
        "excerpt_text": a["excerpt_text"],
        "alert_status": a["alert_status"],
        "escalation_case_id": a["escalation_case_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_case(c):
    return {
        "id": c["id"],
        "alert_id": c["alert_id"],
        "child_profile_id": c["child_profile_id"],
        "case_status": c["case_status"],
        "crisis_resource_codes": c["crisis_resource_codes"],
        "legal_report_due_at": c["legal_report_due_at"],
        "legal_report_filed_at": c["legal_report_filed_at"],
        "overdue": c["overdue"],
        "district_link_id": c["district_link_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_window(w):
    return {
        "id": w["id"],
        "device_id": w["device_id"],
        "weekday": w["weekday"],
        "start_minute": w["start_minute"],
        "end_minute": w["end_minute"],
        "window_kind": w["window_kind"],
        "window_status": w["window_status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_filter_rule(r):
    return {
        "id": r["id"],
        "child_profile_id": r["child_profile_id"],
        "rule_kind": r["rule_kind"],
        "target": r["target"],
        "rule_status": r["rule_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_bypass_event(e):
    return {
        "id": e["id"],
        "device_id": e["device_id"],
        "bypass_kind": e["bypass_kind"],
        "detected_at": e["detected_at"],
        "counted_in_strikes": e["counted_in_strikes"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_grant(g):
    return {
        "id": g["id"],
        "device_id": g["device_id"],
        "start_at": g["start_at"],
        "end_at": g["end_at"],
        "reason": g["reason"],
        "grant_status": g["grant_status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_district(d):
    return {
        "id": d["id"],
        "district_name": d["district_name"],
        "contact_email": d["contact_email"],
        "jurisdiction": d["jurisdiction"],
        "district_status": d["district_status"],
        "open_obligation_count": d["open_obligation_count"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_district_link(l):
    return {
        "id": l["id"],
        "district_id": l["district_id"],
        "child_profile_id": l["child_profile_id"],
        "link_status": l["link_status"],
        "pending_legal_report": l["pending_legal_report"],
        "consented_at": l["consented_at"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


# ------------------------------------------------------------- recompute ops

def family_of_child(child_id):
    child = store.children.get(child_id)
    if not child:
        return None
    return store.families.get(child.get("family_account_id"))


def family_of_device(device_id):
    device = store.devices.get(device_id)
    if not device:
        return None
    return family_of_child(device.get("child_profile_id"))


def recompute_device_count(family):
    count = 0
    for d in store.devices.values():
        if d.get("pairing_status") != "PAIRED":
            continue
        child = store.children.get(d.get("child_profile_id"))
        if child and child.get("family_account_id") == family["id"]:
            count += 1
    family["device_count"] = count
    bump(family)


def recompute_open_alert_count(child):
    count = 0
    for a in store.alerts.values():
        if a.get("child_profile_id") == child["id"] and a.get("alert_status") in (
                "DELIVERED", "ACKNOWLEDGED", "REOPENED"):
            count += 1
    child["open_alert_count"] = count
    bump(child)


def recompute_open_escalation_count(family):
    count = 0
    for c in store.escalation_cases.values():
        if c.get("case_status") == "CLOSED":
            continue
        child = store.children.get(c.get("child_profile_id"))
        if child and child.get("family_account_id") == family["id"]:
            count += 1
    family["open_escalation_count"] = count
    bump(family)


def recompute_district_obligations(district):
    count = 0
    for l in store.district_links.values():
        if l.get("district_id") == district["id"] and l.get("pending_legal_report"):
            count += 1
    district["open_obligation_count"] = count
    bump(district)


def recompute_case_overdue(case):
    due = case.get("legal_report_due_at")
    filed = case.get("legal_report_filed_at")
    if due and not filed:
        from db import parse_iso
        case["overdue"] = clock.now() > parse_iso(due)
    else:
        case["overdue"] = False
    bump(case)


def grant_status_for(grant, now):
    """Derive grant status from clock; CANCELLED is sticky."""
    if grant.get("grant_status") == "CANCELLED":
        return "CANCELLED"
    from db import parse_iso
    start = parse_iso(grant["start_at"])
    end = parse_iso(grant["end_at"])
    if now > end:
        return "EXPIRED"
    if start <= now <= end:
        return "ACTIVE"
    return "SCHEDULED"


def recompute_grant(grant):
    new_status = grant_status_for(grant, clock.now())
    if new_status != grant.get("grant_status"):
        grant["grant_status"] = new_status
        bump(grant)


def recompute_device_posture(device):
    """Recompute strikes and posture; LOCKDOWN entry cancels grants."""
    events = [e for e in store.bypass_events.values() if e.get("device_id") == device["id"]]
    count = calc.count_strikes(events, clock.now())
    device["bypass_strike_count"] = count
    new_posture = calc.posture_for(count)
    old_posture = device.get("device_posture")
    if new_posture != old_posture:
        device["device_posture"] = new_posture
        if new_posture == "LOCKDOWN":
            for g in store.access_grants.values():
                if g.get("device_id") == device["id"] and g.get("grant_status") in (
                        "SCHEDULED", "ACTIVE"):
                    g["grant_status"] = "CANCELLED"
                    bump(g)
    bump(device)


def clock_advanced():
    """Re-evaluate all time-dependent derivations after a clock set."""
    for device in store.devices.values():
        recompute_device_posture(device)
    for grant in store.access_grants.values():
        recompute_grant(grant)
    for case in store.escalation_cases.values():
        recompute_case_overdue(case)


def paginate(items, limit, offset, sort_key=None, descending=False):
    if sort_key is not None:
        items = sorted(items, key=sort_key, reverse=descending)
    else:
        items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    return items[offset:offset + limit], total
