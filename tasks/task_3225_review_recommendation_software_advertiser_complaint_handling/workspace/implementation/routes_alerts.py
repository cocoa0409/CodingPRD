"""Routes: consumer alerts."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, fmt_ts
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str, req_enum, pub,
    ALERT_COOLDOWN_D,
)
from routes_core import ALL_ROLES
from routes_pages import get_page

bp = Blueprint("alerts", __name__)

ALERT_KINDS = ("SOLICITATION_EVIDENCE", "SUSPICIOUS_ACTIVITY", "MEDIA_ATTENTION")


def get_alert(alert_id):
    a = store.alerts.get(alert_id)
    if a is None:
        raise not_found("consumer alert not found")
    return a


@bp.post("/platform/business-pages/<pageId>/consumer-alerts")
@require_roles("SupportAdmin")
def place_alert(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    body = get_body()
    kind = req_enum(body, "kind", ALERT_KINDS)
    evidence_text = req_str(body, "evidence_text")
    case_id = body.get("case_id")
    if kind == "SOLICITATION_EVIDENCE":
        if not isinstance(case_id, str):
            raise err("ERR_ALERT_CONFLICT",
                      "SOLICITATION_EVIDENCE requires a case_id")
        case = store.cases.get(case_id)
        if case is None:
            raise not_found("case not found")
        if case["status"] != "CONFIRMED" or case["page_id"] != pageId:
            raise err("ERR_ALERT_CONFLICT",
                      "referenced case must be CONFIRMED on this page")
    elif case_id is not None:
        if not isinstance(case_id, str):
            raise err("ERR_INVALID_REQUEST", "case_id must be a string")
        if case_id not in store.cases:
            raise not_found("case not found")
    for a in store.alerts.values():
        if a["page_id"] == pageId and a["status"] == "ACTIVE" and a["kind"] == kind:
            raise err("ERR_ALERT_CONFLICT",
                      "an ACTIVE alert of the same kind already exists on the page")
    cooldown = store.now + timedelta(days=ALERT_COOLDOWN_D)
    alert = stamp_common({
        "page_id": pageId,
        "kind": kind,
        "case_id": case_id if kind == "SOLICITATION_EVIDENCE" else case_id,
        "evidence_text": evidence_text,
        "review_cooldown_until": fmt_ts(cooldown),
        "lifted_by_admin_id": None,
        "status": "ACTIVE",
        "_cooldown_dt": cooldown,
    })
    store.alerts[alert["id"]] = alert
    return ok(pub(alert), status=201)


@bp.get("/platform/consumer-alerts")
@require_roles(*ALL_ROLES)
def list_alerts(_actor_id, _actor_role):
    items = list(store.alerts.values())
    for f in ("page_id", "case_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    items, limit, offset, total = paginate([pub(a) for a in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/consumer-alerts/<alertId>")
@require_roles(*ALL_ROLES)
def get_one_alert(alertId, _actor_id, _actor_role):
    return ok(pub(get_alert(alertId)))


@bp.post("/platform/consumer-alerts/<alertId>/lift")
@require_roles("SupportAdmin")
def lift_alert(alertId, _actor_id, _actor_role):
    alert = get_alert(alertId)
    if alert["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "alert is not ACTIVE")
    if alert.get("case_id"):
        case = store.cases.get(alert["case_id"])
        if case is not None and case["status"] != "DISMISSED":
            raise err("ERR_ALERT_CASE_ACTIVE",
                      "referenced case must be DISMISSED before lifting")
    alert["status"] = "LIFTED"
    alert["lifted_by_admin_id"] = _actor_id
    touch(alert)
    return ok(pub(alert))
