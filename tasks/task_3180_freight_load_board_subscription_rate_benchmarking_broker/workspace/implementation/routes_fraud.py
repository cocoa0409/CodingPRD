from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    get_alert,
    get_broker,
    get_carrier,
    new_resource,
    paginate,
    parse_limit_offset,
    require_enum,
    require_fields,
    sorted_by_created,
    suspend_broker,
    suspend_carrier,
    touch,
)
from util import ALERT_TYPES

bp = Blueprint("fraud", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps")


@bp.post("/fraud-alerts")
def create_alert():
    _, role = get_context()
    require_role(role, ("ComplianceAnalyst",))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["alert_type", "evidence_note"])
    require_enum(body["alert_type"], ALERT_TYPES, "alert_type")
    target_broker = body.get("target_broker_org_id")
    target_carrier = body.get("target_carrier_org_id")
    if target_broker is None and target_carrier is None:
        raise APIError("ERR_INVALID_REQUEST", 400, "At least one target org is required")
    if target_broker is not None:
        get_broker(db, target_broker)
    if target_carrier is not None:
        get_carrier(db, target_carrier)
    alert = new_resource(db, {
        "alert_type": body["alert_type"],
        "target_broker_org_id": target_broker,
        "target_carrier_org_id": target_carrier,
        "evidence_note": body["evidence_note"],
        "status": "OPEN",
    })
    db.fraud_alerts[alert["id"]] = alert
    return success(alert, 201)


@bp.get("/fraud-alerts")
def list_alerts():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = list(db.fraud_alerts.values())
    for f in ("target_broker_org_id", "target_carrier_org_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/fraud-alerts/<alert_id>")
def get_alert_route(alert_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(get_alert(db, alert_id))


@bp.post("/fraud-alerts/<alert_id>/confirm")
def confirm_alert(alert_id):
    _, role = get_context()
    require_role(role, ("ComplianceAnalyst",))
    alert = get_alert(db, alert_id)
    if alert["status"] != "OPEN":
        raise APIError("ERR_INVALID_STATE", 409, "Alert is not OPEN")
    alert["status"] = "CONFIRMED"
    touch(db, alert)
    if alert.get("target_broker_org_id"):
        org = db.broker_orgs.get(alert["target_broker_org_id"])
        if org is not None and org["status"] == "ACTIVE":
            suspend_broker(db, org, fraud=True)
    if alert.get("target_carrier_org_id"):
        org = db.carrier_orgs.get(alert["target_carrier_org_id"])
        if org is not None and org["status"] == "ACTIVE":
            suspend_carrier(db, org, fraud=True)
    return success(alert)


@bp.post("/fraud-alerts/<alert_id>/dismiss")
def dismiss_alert(alert_id):
    _, role = get_context()
    require_role(role, ("ComplianceAnalyst",))
    alert = get_alert(db, alert_id)
    if alert["status"] != "OPEN":
        raise APIError("ERR_INVALID_STATE", 409, "Alert is not OPEN")
    alert["status"] = "DISMISSED"
    touch(db, alert)
    return success(alert)
