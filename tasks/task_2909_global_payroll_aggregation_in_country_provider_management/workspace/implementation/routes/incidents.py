"""Service-level incidents and the provider scoring they drive."""
from decimal import Decimal

from flask import Blueprint, g

import serial
import services
import store
import validate as v
from auth import require
from common import (
    ALL_ROLES,
    GLOBAL_PAYROLL_OPS,
    INCIDENT_STATUSES,
    INCIDENT_TYPES,
    PAYROLL_CONTROLLER,
    SEVERITIES,
    ApiError,
    now,
)
from response import created, object_response, page_response
from store import new_row, touch

bp = Blueprint("incidents", __name__)


def _rescore(incident):
    engagement = store.get_engagement(incident["engagement_id"])
    services.recompute_provider_score(store.provider_of_engagement(engagement))


@bp.post("/payroll/sla-incidents")
@require(GLOBAL_PAYROLL_OPS, PAYROLL_CONTROLLER)
def create_incident():
    body = v.json_body()
    engagement_id = v.req_id(body, "engagement_id")
    incident_type = v.req_enum(body, "incident_type", INCIDENT_TYPES)
    severity = v.req_enum(body, "severity", SEVERITIES)
    occurred_at = v.req_instant(body, "occurred_at")
    cycle_id = v.opt_id(body, "cycle_id")
    note = v.opt_str(body, "note", 1, None)

    engagement = store.get_engagement(engagement_id)
    cycle = store.get_cycle(cycle_id) if cycle_id is not None else None

    if occurred_at > now():
        raise ApiError(
            "ERR_INCIDENT_FUTURE_DATED",
            "occurred_at may not be later than the current logical clock.",
        )
    if cycle is not None and cycle["engagement_id"] != engagement_id:
        raise ApiError(
            "ERR_CYCLE_ENGAGEMENT_MISMATCH",
            "The named cycle belongs to another engagement.",
        )

    row = new_row(
        {
            "engagement_id": engagement_id,
            "cycle_id": cycle_id,
            "incident_type": incident_type,
            "severity": severity,
            "occurred_at": occurred_at,
            "note": note,
            "status": "OPEN",
            "escalation_level": 0,
            "weight_points": Decimal("0.00"),
            "remediation_ref": None,
        }
    )
    store.incidents[row["id"]] = row
    return created(serial.incident(row))


@bp.get("/payroll/sla-incidents/<ident>")
@require(*ALL_ROLES)
def read_incident(ident):
    return object_response(serial.incident(store.get_incident(ident)))


@bp.get("/payroll/sla-incidents")
@require(*ALL_ROLES)
def list_incidents():
    limit, offset = v.pagination()
    status = v.query_enum("status", INCIDENT_STATUSES)
    severity = v.query_enum("severity", SEVERITIES)
    engagement_id = v.query_value("engagement_id")
    cycle_id = v.query_value("cycle_id")

    rows = list(store.incidents.values())
    if engagement_id is not None:
        rows = [r for r in rows if r["engagement_id"] == engagement_id]
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_response(store.ordered(rows), serial.incident, limit, offset)


@bp.post("/payroll/sla-incidents/<ident>/confirm")
@require(PAYROLL_CONTROLLER)
def confirm_incident(ident):
    incident = store.get_incident(ident)
    if incident["status"] != "OPEN":
        raise ApiError(
            "ERR_INCIDENT_INVALID_STATE", "Only an OPEN incident can be confirmed."
        )
    incident["status"] = "CONFIRMED"
    incident["weight_points"] = services.INCIDENT_BASE_WEIGHTS[incident["severity"]]
    touch(incident)
    _rescore(incident)
    return object_response(serial.incident(incident))


@bp.post("/payroll/sla-incidents/<ident>/escalate")
@require(PAYROLL_CONTROLLER)
def escalate_incident(ident):
    body = v.json_body(required=False)
    v.opt_str(body, "escalation_note", 1, None)

    incident = store.get_incident(ident)
    if incident["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INCIDENT_INVALID_STATE", "Only a CONFIRMED incident can be escalated."
        )
    incident["status"] = "ESCALATED"
    incident["escalation_level"] = 1
    incident["weight_points"] = services.escalated_weight(incident["severity"])
    touch(incident)
    _rescore(incident)
    return object_response(serial.incident(incident))


@bp.post("/payroll/sla-incidents/<ident>/remediate")
@require(PAYROLL_CONTROLLER)
def remediate_incident(ident):
    body = v.json_body()
    remediation_ref = v.req_str(body, "remediation_ref", 1, 60)

    incident = store.get_incident(ident)
    if incident["status"] not in ("CONFIRMED", "ESCALATED"):
        raise ApiError(
            "ERR_INCIDENT_INVALID_STATE",
            "Remediation is only available from CONFIRMED or ESCALATED.",
        )
    incident["status"] = "REMEDIATED"
    incident["weight_points"] = Decimal("0.00")
    incident["remediation_ref"] = remediation_ref
    touch(incident)
    _rescore(incident)
    return object_response(serial.incident(incident))
