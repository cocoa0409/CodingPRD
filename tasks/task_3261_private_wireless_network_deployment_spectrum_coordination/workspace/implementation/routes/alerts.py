"""MonitoringAlert endpoints."""

from datetime import datetime, timezone

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, paged, parse_iso,
                     req_enum, stamp, touch)
from services import calc
from validate import get_alert, get_site, get_site_mutable

bp = Blueprint("alerts", __name__)

READ = ("NetworkArchitect", "RFEngineer", "FieldTechnician")
ALERT_CLASSES = ("OUTAGE", "DEGRADATION", "INTERFERENCE", "CAPACITY", "SECURITY")
SEVERITIES = ("INFO", "MINOR", "MAJOR", "CRITICAL")
ALERT_TERMINAL = ("RESOLVED", "FALSE_ALARM")
OPEN_REMEDIATION = ("PROPOSED", "APPROVED", "IN_PROGRESS", "VERIFYING")


@bp.post("/sites/<sid>/alerts")
def create_alert(sid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    body = get_body()
    aclass = req_enum(body, "alert_class", ALERT_CLASSES)
    severity = req_enum(body, "severity", SEVERITIES)
    a = new_resource(common=False)
    a.update({
        "site_id": sid,
        "alert_class": aclass,
        "severity": severity,
        "raised_at_utc": stamp(),
        "resolved_at_utc": None,
        "sla_credit_applied_cents": 0,
        "status": "OPEN",
    })
    DB.alerts[a["id"]] = a
    return ok_object(a, 201)


@bp.get("/sites/<sid>/alerts")
def list_alerts_for_site(sid):
    require_roles(*READ)
    get_site(sid)
    items = [a for a in DB.alerts.values() if a["site_id"] == sid]
    items = apply_filters(items, [("status", "status"), ("severity", "severity"), ("alert_class", "alert_class")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/alerts/<aid>")
def get_one_alert(sid, aid):
    require_roles(*READ)
    get_site(sid)
    return ok_object(get_alert(aid, sid))


@bp.post("/sites/<sid>/alerts/<aid>/acknowledge")
def acknowledge_alert(sid, aid):
    require_roles("FieldTechnician")
    site = get_site_mutable(sid)
    a = get_alert(aid, sid)
    if a["status"] in ALERT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Alert is in a terminal state")
    if a["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Alert must be OPEN to acknowledge")
    a["status"] = "ACKNOWLEDGED"
    if a["severity"] in ("MAJOR", "CRITICAL") and site["status"] == "OPERATIONAL":
        site["status"] = "REMEDIATION_REQUIRED"
        site["posture"] = "REMEDIATING"
        touch(site)
    return ok_object(a)


@bp.post("/sites/<sid>/alerts/<aid>/mitigate")
def mitigate_alert(sid, aid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    a = get_alert(aid, sid)
    if a["status"] in ALERT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Alert is in a terminal state")
    if a["status"] != "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", "Alert must be ACKNOWLEDGED to mitigate")
    a["status"] = "MITIGATING"
    return ok_object(a)


@bp.post("/sites/<sid>/alerts/<aid>/resolve")
def resolve_alert(sid, aid):
    require_roles("FieldTechnician")
    site = get_site_mutable(sid)
    a = get_alert(aid, sid)
    if a["status"] in ALERT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Alert is in a terminal state")
    if a["status"] != "MITIGATING":
        raise err("ERR_INVALID_STATE", "Alert must be MITIGATING to resolve")
    if any(r["triggered_by_alert_id"] == aid and r["status"] in OPEN_REMEDIATION
           for r in DB.remediations.values()):
        raise err("ERR_REMEDIATION_OPEN",
                  "A CoverageRemediation referencing this alert is still open")
    a["resolved_at_utc"] = stamp()
    a["status"] = "RESOLVED"
    if a["alert_class"] == "OUTAGE" and a["severity"] == "CRITICAL":
        raised = parse_iso(a["raised_at_utc"], "raised_at_utc")
        resolved = parse_iso(a["resolved_at_utc"], "resolved_at_utc")
        minutes = int((resolved - raised).total_seconds() // 60)
        key = (site["enterprise_id"], resolved.year, resolved.month)
        DB.outage_minutes[key] += minutes
        contract = next((c for c in DB.contracts.values()
                         if c["enterprise_id"] == site["enterprise_id"]
                         and c["status"] in ("ACTIVE", "BREACHED")), None)
        if contract is not None and \
                DB.outage_minutes[key] > contract["contracted_max_outage_minutes_per_month"]:
            # The cumulative monthly total now exceeds the outage budget: the
            # contract flips ACTIVE -> BREACHED on the crossing event, and an
            # SLA credit is applied per breach event, summed across events.
            contract["status"] = "BREACHED"
            touch(contract)
            credit = calc.sla_credit_cents(contract["sla_tier"])
            a["sla_credit_applied_cents"] = credit
            ent = DB.enterprises.get(site["enterprise_id"])
            if ent is not None:
                ent["sla_credit_balance_cents"] = ent.get("sla_credit_balance_cents", 0) + credit
                touch(ent)
    return ok_object(a)


@bp.post("/sites/<sid>/alerts/<aid>/mark-false-alarm")
def mark_false_alarm(sid, aid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    a = get_alert(aid, sid)
    if a["status"] in ALERT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Alert is in a terminal state")
    if a["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise err("ERR_INVALID_STATE", "Alert must be OPEN or ACKNOWLEDGED to mark false alarm")
    a["status"] = "FALSE_ALARM"
    return ok_object(a)


@bp.get("/alerts/<aid>")
def get_alert_flat(aid):
    require_roles(*READ)
    return ok_object(get_alert(aid))


@bp.get("/alerts")
def list_alerts_flat():
    require_roles(*READ)
    items = list(DB.alerts.values())
    items = apply_filters(items, [("site_id", "site_id"), ("status", "status"),
                                  ("severity", "severity"), ("alert_class", "alert_class")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)
