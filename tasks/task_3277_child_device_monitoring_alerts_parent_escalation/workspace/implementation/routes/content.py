"""Content ingestion, content item read, and alert routes."""
from flask import Blueprint, request
from datetime import timedelta
from db import store, clock, parse_iso, fmt_iso
from errors import fail
from response import success_object, success_list, parse_pagination
from middleware import (authenticate, require_role, require_parent_scope,
                        require_school_scope_alert, require_school_scope_child,
                        family_id_of_connection)
import services as svc
import calculations as calc

bp = Blueprint("content", __name__)

CATEGORIES = {"BULLYING", "SELF_HARM", "EXPLICIT", "PREDATORY_CONTACT"}
DIRECTIONS = {"INBOUND", "OUTBOUND"}


@bp.post("/api/content-items")
def ingest_content():
    role, uid = authenticate()
    require_role(role, {"DeviceAgent"})
    body = request.get_json(silent=True) or {}
    conn_id = body.get("service_connection_id")
    if not isinstance(conn_id, str) or not conn_id:
        fail("ERR_INVALID_REQUEST", "service_connection_id is required")
    conn = store.connections.get(conn_id)
    if not conn:
        fail("ERR_NOT_FOUND", "ServiceConnection not found")
    child = store.children.get(conn["child_profile_id"])
    device_ids = {d["id"] for d in store.devices.values()
                  if d.get("child_profile_id") == conn["child_profile_id"]}
    if uid not in device_ids:
        fail("ERR_FORBIDDEN_ROLE", "DeviceAgent may only report for its own device")
    occurred = parse_iso(body.get("occurred_at"))
    if occurred is None:
        fail("ERR_INVALID_REQUEST", "occurred_at must be an ISO8601 timestamp")
    if occurred > clock.now():
        fail("ERR_INVALID_REQUEST", "occurred_at must not lie in the future")
    direction = body.get("direction")
    if direction not in DIRECTIONS:
        fail("ERR_INVALID_REQUEST", "invalid direction")
    thread_depth = body.get("thread_depth")
    if not isinstance(thread_depth, int) or isinstance(thread_depth, bool) or thread_depth < 1:
        fail("ERR_INVALID_REQUEST", "thread_depth must be an integer >= 1")
    signals = body.get("signals")
    if not isinstance(signals, list) or not signals:
        fail("ERR_INVALID_REQUEST", "signals must be a non-empty array")
    for s in signals:
        if not isinstance(s, dict):
            fail("ERR_INVALID_REQUEST", "signal entries must be objects")
        if s.get("category") not in CATEGORIES:
            fail("ERR_INVALID_REQUEST", "invalid signal category")
        w = s.get("weight")
        if not isinstance(w, int) or isinstance(w, bool) or w < 1 or w > 100:
            fail("ERR_INVALID_REQUEST", "signal weight must be an integer 1..100")
    raw_text = body.get("raw_text")
    if not isinstance(raw_text, str):
        fail("ERR_INVALID_REQUEST", "raw_text must be a string")

    family = store.families.get(child["family_account_id"]) if child else None
    if conn["consent_status"] != "ACTIVE":
        fail("ERR_CONNECTION_NOT_ACTIVE", "Connection is not ACTIVE")
    if family and family["account_status"] != "ACTIVE":
        fail("ERR_FAMILY_SUSPENDED", "Family is suspended")

    with store.lock:
        now = clock.now()
        variant = family["analysis_variant"]
        score = calc.risk_score(signals, thread_depth, variant)
        severity, category = calc.classify_severity(
            score, signals, child["age_band"], child["monitoring_sensitivity"])
        alert_created = severity in ("MODERATE", "HIGH", "SEVERE")

        ci = svc.new_entity()
        ci.update({
            "service_connection_id": conn["id"],
            "occurred_at": fmt_iso(occurred),
            "direction": direction,
            "thread_depth": thread_depth,
            "signals": [{"category": s["category"], "weight": s["weight"]} for s in signals],
            "raw_text": raw_text,
            "analysis_variant_used": variant,
            "risk_score": score,
            "severity": severity,
            "alert_created": alert_created,
            "alert_id": None,
        })
        store.content_items[ci["id"]] = ci

        alert = None
        case = None
        if alert_created:
            excerpt = calc.make_excerpt(raw_text, child["age_band"],
                                        child["monitoring_sensitivity"])
            alert = svc.new_entity()
            alert.update({
                "child_profile_id": child["id"],
                "content_item_id": ci["id"],
                "category": category,
                "severity": severity,
                "excerpt_text": excerpt,
                "alert_status": "DELIVERED",
                "escalation_case_id": None,
            })
            store.alerts[alert["id"]] = alert
            ci["alert_id"] = alert["id"]
            svc.bump(ci)
            svc.recompute_open_alert_count(child)

            if severity == "SEVERE":
                case = svc.new_entity()
                # legal reporting obligation
                qualifying = []
                for link in store.district_links.values():
                    if (link.get("child_profile_id") == child["id"]
                            and link.get("link_status") == "ACTIVE"):
                        district = store.districts.get(link.get("district_id"))
                        if district and district.get("jurisdiction") == "MANDATED_REPORTING":
                            qualifying.append(link)
                due_at = None
                link_id = None
                if qualifying:
                    qualifying.sort(key=lambda l: (l.get("consented_at") or "", l["id"]))
                    chosen = qualifying[0]
                    due_at = fmt_iso(parse_iso(case["created_at"]) + timedelta(hours=24))
                    link_id = chosen["id"]
                    chosen["pending_legal_report"] = True
                    svc.bump(chosen)
                    district = store.districts.get(chosen["district_id"])
                    if district:
                        svc.recompute_district_obligations(district)
                case.update({
                    "alert_id": alert["id"],
                    "child_profile_id": child["id"],
                    "case_status": "OPEN",
                    "crisis_resource_codes": calc.CRISIS_CODES.get(category, []),
                    "legal_report_due_at": due_at,
                    "legal_report_filed_at": None,
                    "overdue": False,
                    "district_link_id": link_id,
                })
                store.escalation_cases[case["id"]] = case
                alert["escalation_case_id"] = case["id"]
                svc.bump(alert)
                svc.recompute_open_escalation_count(family)
    return success_object(svc.ser_content_item(ci, include_raw=True), status=201)


@bp.get("/api/content-items/<item_id>")
def get_content_item(item_id):
    role, _uid = authenticate()
    require_role(role, {"PlatformAdmin"})
    ci = store.content_items.get(item_id)
    if not ci:
        fail("ERR_NOT_FOUND", "ContentItem not found")
    return success_object(svc.ser_content_item(ci, include_raw=True))


# ------------------------------------------------------------------ alerts

ALERT_STATUSES = {"DELIVERED", "ACKNOWLEDGED", "RESOLVED", "REOPENED"}
ALERT_EDGES = {
    ("DELIVERED", "ACKNOWLEDGED"),
    ("ACKNOWLEDGED", "RESOLVED"),
    ("REOPENED", "ACKNOWLEDGED"),
    ("REOPENED", "RESOLVED"),
    ("RESOLVED", "REOPENED"),
}


@bp.get("/api/alerts/<alert_id>")
def get_alert(alert_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "SchoolAdmin", "PlatformAdmin"})
    a = store.alerts.get(alert_id)
    if not a:
        fail("ERR_NOT_FOUND", "Alert not found")
    if role == "Parent":
        child = store.children.get(a["child_profile_id"])
        require_parent_scope(uid, child["family_account_id"] if child else None)
    elif role == "SchoolAdmin":
        require_school_scope_alert(uid, a)
    return success_object(svc.ser_alert(a))


@bp.get("/api/alerts")
def list_alerts():
    role, uid = authenticate()
    require_role(role, {"Parent", "SchoolAdmin", "PlatformAdmin"})
    variant = request.args.get("variant", "IMMEDIATE")
    if variant not in ("IMMEDIATE", "DIGEST"):
        fail("ERR_INVALID_REQUEST", "variant must be IMMEDIATE or DIGEST")
    f_child = request.args.get("child_profile_id")
    f_content = request.args.get("content_item_id")
    f_status = request.args.get("alert_status")
    if f_status is not None and f_status not in ALERT_STATUSES:
        fail("ERR_INVALID_REQUEST", "invalid alert_status")

    if role == "Parent":
        fam_id = None
        from middleware import parent_family_id
        fam_id = parent_family_id(uid)
        if fam_id is None:
            fail("ERR_FORBIDDEN_ROLE", "Parent identity not recognized")
        if f_child:
            child = store.children.get(f_child)
            if child and child.get("family_account_id") != fam_id:
                fail("ERR_CROSS_FAMILY_ACCESS", "Child belongs to a different family")

    if role == "SchoolAdmin" and f_child:
        require_school_scope_child(uid, f_child)

    limit, offset = parse_pagination(request.args)

    items = []
    for a in store.alerts.values():
        if a.get("alert_status") not in ("DELIVERED", "ACKNOWLEDGED", "REOPENED"):
            continue
        if variant == "IMMEDIATE":
            if a.get("severity") not in ("MODERATE", "HIGH", "SEVERE"):
                continue
        else:  # DIGEST
            if a.get("severity") not in ("HIGH", "SEVERE"):
                continue
        if f_child and a.get("child_profile_id") != f_child:
            continue
        if f_content and a.get("content_item_id") != f_content:
            continue
        if f_status and a.get("alert_status") != f_status:
            continue
        if role == "Parent":
            child = store.children.get(a.get("child_profile_id"))
            if not child or child.get("family_account_id") != fam_id:
                continue
        elif role == "SchoolAdmin":
            if a.get("severity") not in ("HIGH", "SEVERE"):
                continue
            from middleware import school_admin_child_ids
            if a.get("child_profile_id") not in school_admin_child_ids(uid):
                continue
        items.append(a)

    page, total = svc.paginate(
        items, limit, offset,
        sort_key=lambda a: (a["created_at"], a["id"]), descending=True)
    return success_list([svc.ser_alert(a) for a in page], limit, offset, total)


@bp.post("/api/alerts/<alert_id>/state")
def alert_state(alert_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    a = store.alerts.get(alert_id)
    if not a:
        fail("ERR_NOT_FOUND", "Alert not found")
    child = store.children.get(a["child_profile_id"])
    require_parent_scope(uid, child["family_account_id"] if child else None)
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if to_status not in ALERT_STATUSES:
        fail("ERR_INVALID_REQUEST", "invalid to_status")
    current = a["alert_status"]
    if (current, to_status) not in ALERT_EDGES:
        fail("ERR_INVALID_STATE",
             "Transition %s -> %s not permitted" % (current, to_status))
    if to_status == "RESOLVED" and a.get("severity") == "SEVERE":
        case = store.escalation_cases.get(a.get("escalation_case_id"))
        if case and case.get("case_status") != "CLOSED":
            fail("ERR_ESCALATION_OPEN", "Linked escalation case is not CLOSED")
    with store.lock:
        a["alert_status"] = to_status
        svc.touch(a)
        if to_status == "ACKNOWLEDGED":
            case = store.escalation_cases.get(a.get("escalation_case_id"))
            if case and case.get("case_status") == "OPEN":
                case["case_status"] = "GUIDANCE_ISSUED"
                svc.touch(case)
        if child:
            svc.recompute_open_alert_count(child)
    return success_object(svc.ser_alert(a))
