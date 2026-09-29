"""Manufacturer bulletins, fleet-wide corrective actions and risk scoring."""

from flask import Blueprint, g

import calc
import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    invalid,
    ERR_ACTION_STATE_INVALID,
    ERR_BULLETIN_STATE_INVALID,
    ERR_PART_NOT_RECEIVED,
    ERR_RECALL_NOT_DEFERRABLE,
)
from reply import computed, made, saved

bp = Blueprint("bulletins", __name__)

SEVERITIES = ("ADVISORY", "MANDATORY", "RECALL")
RETIREABLE = ("ISSUED", "ACKNOWLEDGED")
CANCELLABLE_ACTIONS = ("PENDING", "IN_WORK", "DEFERRED")


@bp.post("/park-ops/bulletins")
@require_roles("ParkOpsAdmin")
def publish_bulletin():
    data = validate.body()
    superseded = fetch.fk("bulletins", data.get("supersedes_bulletin_id"))
    bulletin_ref = validate.str_field(data, "bulletin_ref")
    manufacturer = validate.str_field(data, "manufacturer")
    model_code = validate.str_field(data, "model_code")
    severity = validate.enum_field(data, "severity", SEVERITIES)
    issued_date = validate.date_field(data, "issued_date")
    deadline = validate.date_field(data, "compliance_deadline_date")
    if deadline < issued_date:
        invalid("compliance_deadline_date must be the same as or later than "
                "issued_date.")
    for existing in store.rows("bulletins"):
        if existing["bulletin_ref"] == bulletin_ref:
            invalid("bulletin_ref must be unique across all bulletins.")
    row = store.create(
        "bulletins",
        bulletin_ref=bulletin_ref,
        manufacturer=manufacturer,
        model_code=model_code,
        severity=severity,
        issued_date=issued_date.isoformat(),
        compliance_deadline_date=deadline.isoformat(),
        supersedes_bulletin_id=superseded["id"] if superseded else None,
        status="ISSUED",
        acknowledged_at=None,
        acknowledged_by_user_id=None,
    )
    if superseded is not None and superseded["status"] in RETIREABLE:
        superseded["status"] = "SUPERSEDED"
        for action in derive.actions_of(superseded["id"]):
            if action["status"] in CANCELLABLE_ACTIONS:
                action["status"] = "CANCELLED"
    return made(derive.ser_bulletin, row)


@bp.get("/park-ops/bulletins/<bulletin_id>")
@require_roles(*ALL_ROLES)
def read_bulletin(bulletin_id):
    return computed(derive.ser_bulletin(fetch.bulletin(bulletin_id)))


@bp.get("/park-ops/bulletins")
@require_roles(*ALL_ROLES)
def list_bulletins():
    return list_response(
        store.rows("bulletins"),
        derive.ser_bulletin,
        filters=(("manufacturer", "str"), ("model_code", "str"),
                 ("severity", "str"), ("status", "str"),
                 ("supersedes_bulletin_id", "str")),
        order=("issued_date", "created_at"),
    )


@bp.get("/park-ops/bulletins/<bulletin_id>/risk")
@require_roles(*ALL_ROLES)
def bulletin_risk(bulletin_id):
    return computed(calc.bulletin_risk(fetch.bulletin(bulletin_id)))


@bp.post("/park-ops/bulletins/<bulletin_id>/acknowledge")
@require_roles("MaintenanceManager")
def acknowledge_bulletin(bulletin_id):
    bulletin = fetch.bulletin(bulletin_id)
    validate.body()
    if bulletin["status"] != "ISSUED":
        fail(ERR_BULLETIN_STATE_INVALID,
             "Only an ISSUED bulletin may be acknowledged.")
    bulletin["status"] = "ACKNOWLEDGED"
    bulletin["acknowledged_at"] = store.now_iso()
    bulletin["acknowledged_by_user_id"] = g.user_id
    fleet = [a for a in store.rows("attractions")
             if a["manufacturer"] == bulletin["manufacturer"]
             and a["model_code"] == bulletin["model_code"]]
    fleet = sorted(fleet, key=lambda a: (a["created_at"], a["_seq"]))
    for attraction in fleet:
        store.create(
            "bulletin_actions",
            bulletin_id=bulletin["id"],
            attraction_id=attraction["id"],
            status="PENDING",
            deferral_reason=None,
            deferred_until_date=None,
            verified_by_user_id=None,
            verified_at=None,
        )
    return saved(derive.ser_bulletin, bulletin)


@bp.get("/park-ops/bulletin-actions/<action_id>")
@require_roles(*ALL_ROLES)
def read_action(action_id):
    return computed(derive.ser_bulletin_action(
        fetch.bulletin_action(action_id)))


@bp.get("/park-ops/bulletin-actions")
@require_roles(*ALL_ROLES)
def list_actions():
    return list_response(
        store.rows("bulletin_actions"),
        derive.ser_bulletin_action,
        filters=(("bulletin_id", "str"), ("attraction_id", "str"),
                 ("status", "str")),
        order=("created_at",),
    )


@bp.post("/park-ops/bulletin-actions/<action_id>/start")
@require_roles("MaintenanceTechnician")
def start_action(action_id):
    action = fetch.bulletin_action(action_id)
    validate.body()
    bulletin = store.db.bulletins.get(action["bulletin_id"])
    if action["status"] != "PENDING" or bulletin["status"] != "ACKNOWLEDGED":
        fail(ERR_ACTION_STATE_INVALID,
             "Corrective work may only start on a PENDING action of an "
             "ACKNOWLEDGED bulletin.")
    action["status"] = "IN_WORK"
    return saved(derive.ser_bulletin_action, action)


@bp.post("/park-ops/bulletin-actions/<action_id>/verify")
@require_roles("QualifiedInspector")
def verify_action(action_id):
    action = fetch.bulletin_action(action_id)
    validate.body()
    if action["status"] != "IN_WORK":
        fail(ERR_ACTION_STATE_INVALID,
             "Only an IN_WORK action may be verified.")
    if not derive.required_part_received(action):
        fail(ERR_PART_NOT_RECEIVED,
             "The part this action depends on has not been received.")
    action["status"] = "VERIFIED"
    action["verified_by_user_id"] = g.user_id
    action["verified_at"] = store.now_iso()
    bulletin = store.db.bulletins.get(action["bulletin_id"])
    total = derive.action_total_count(bulletin)
    if (bulletin["status"] == "ACKNOWLEDGED" and total >= 1
            and derive.action_verified_count(bulletin) == total):
        bulletin["status"] = "COMPLETED"
    return saved(derive.ser_bulletin_action, action)


@bp.post("/park-ops/bulletin-actions/<action_id>/defer")
@require_roles("MaintenanceManager")
def defer_action(action_id):
    action = fetch.bulletin_action(action_id)
    data = validate.body()
    reason = validate.str_field(data, "deferral_reason", allow_empty=True)
    until = validate.date_field(data, "deferred_until_date")
    bulletin = store.db.bulletins.get(action["bulletin_id"])
    deadline = store.date_of(bulletin["compliance_deadline_date"])
    if deadline is not None and until > deadline:
        invalid("deferred_until_date must be no later than the bulletin's "
                "compliance_deadline_date.")
    if action["status"] != "PENDING":
        fail(ERR_ACTION_STATE_INVALID,
             "Only a PENDING action may be deferred.")
    if bulletin["severity"] == "RECALL":
        fail(ERR_RECALL_NOT_DEFERRABLE,
             "An action belonging to a RECALL bulletin may not be deferred.")
    action["status"] = "DEFERRED"
    action["deferral_reason"] = reason
    action["deferred_until_date"] = until.isoformat()
    return saved(derive.ser_bulletin_action, action)
