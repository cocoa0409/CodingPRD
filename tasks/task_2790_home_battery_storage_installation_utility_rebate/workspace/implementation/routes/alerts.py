"""Monitoring alerts and the warranty-claim review cycle."""

from flask import Blueprint, request

import shape
import store
from common import ALERT_CODES, SEVERITIES
from envelope import collection, created, ok
from errors import ApiError
from security import guard, path_ref, ref

bp = Blueprint("alerts", __name__)

READ_ROLES = ("ManufacturerWarrantyAgent", "CertifiedInstaller", "Homeowner")


def _alert_state_error(alert, action):
    return ApiError(
        "ERR_ALERT_STATE_INVALID",
        "An alert in %s cannot be %s." % (alert["status"], action),
    )


def _require_active_warranty(alert):
    system = store.get("battery_systems", alert["battery_system_id"])
    if system is None or system["warranty_status"] != "ACTIVE":
        raise ApiError(
            "ERR_WARRANTY_NOT_ACTIVE",
            "The bank's manufacturer warranty is not active.",
        )
    return system


@bp.route("/monitoring-alerts", methods=["POST"])
@guard("ManufacturerWarrantyAgent", "CertifiedInstaller")
def create_alert(actor):
    payload = shape.body()
    system_id = payload.fk("battery_system_id")
    ref("battery_system", system_id)
    alert_code = payload.enum("alert_code", ALERT_CODES)
    severity = payload.enum("severity", SEVERITIES)
    firmware = payload.firmware("reported_firmware_version", required=False)

    record = store.insert(
        "alerts",
        {
            "battery_system_id": system_id,
            "alert_code": alert_code,
            "severity": severity,
            "reported_firmware_version": firmware,
            "status": "OPEN",
            "acknowledged_by_user_id": None,
            "claimed_component": None,
            "claim_round_count": 0,
            "resolution_notes": None,
        },
    )
    return created(store.view(record))


@bp.route("/monitoring-alerts/<alert_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_alert(actor, alert_id):
    record = path_ref(actor, "alert", alert_id)
    return ok(store.view(record))


@bp.route("/monitoring-alerts", methods=["GET"])
@guard(*READ_ROLES)
def list_alerts(actor):
    records = store.where(
        "alerts",
        battery_system_id=request.args.get("battery_system_id"),
        alert_code=request.args.get("alert_code"),
        severity=request.args.get("severity"),
        status=request.args.get("status"),
    )
    return collection(records)


@bp.route("/monitoring-alerts/<alert_id>/acknowledge", methods=["POST"])
@guard("CertifiedInstaller")
def acknowledge_alert(actor, alert_id):
    alert = path_ref(actor, "alert", alert_id)
    if alert["status"] != "OPEN":
        raise _alert_state_error(alert, "acknowledged")
    alert["status"] = "ACKNOWLEDGED"
    alert["acknowledged_by_user_id"] = actor.user_id
    store.touch(alert)
    return ok(store.view(alert))


@bp.route("/monitoring-alerts/<alert_id>/file-claim", methods=["POST"])
@guard("CertifiedInstaller")
def file_claim(actor, alert_id):
    alert = path_ref(actor, "alert", alert_id)
    payload = shape.body()
    claimed_component = payload.str_("claimed_component")
    notes = payload.str_("resolution_notes", required=False, allow_empty=True)

    if alert["status"] not in ("ACKNOWLEDGED", "INFO_REQUESTED"):
        raise _alert_state_error(alert, "filed as a warranty claim")
    _require_active_warranty(alert)

    alert["status"] = "UNDER_REVIEW"
    alert["claimed_component"] = claimed_component
    alert["claim_round_count"] += 1
    if notes is not None:
        alert["resolution_notes"] = notes
    store.touch(alert)
    return ok(store.view(alert))


@bp.route("/monitoring-alerts/<alert_id>/review-claim", methods=["POST"])
@guard("ManufacturerWarrantyAgent")
def review_claim(actor, alert_id):
    alert = path_ref(actor, "alert", alert_id)
    payload = shape.body()
    decision = payload.enum("decision", ("APPROVE", "DENY", "REQUEST_INFO"))
    notes = payload.str_("resolution_notes", required=False, allow_empty=True)

    if alert["status"] != "UNDER_REVIEW":
        raise _alert_state_error(alert, "adjudicated")

    if decision == "APPROVE":
        alert["status"] = "CLAIM_APPROVED"
    elif decision == "DENY":
        alert["status"] = "CLAIM_DENIED"
    else:
        alert["status"] = "INFO_REQUESTED"
    alert["resolution_notes"] = notes
    store.touch(alert)
    return ok(store.view(alert))
