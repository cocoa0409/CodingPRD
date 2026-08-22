"""EquipmentUnit endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CONTRACTOR, ROLE_CX_AUTHORITY, ROLE_PLATFORM_ADMIN, authenticate,
    body_json, db, fail, new_row, ok, ok_list, paginate, public, q, sorted_rows, touch,
    v_enum, v_int, v_string,
)
from finders import get_equipment, get_project

bp = Blueprint("equipment", __name__)

ALLOWED_INSTALL_TRANSITIONS = {
    "NOT_INSTALLED": {"INSTALLED", "REMOVED"},
    "INSTALLED": {"STARTED_UP", "REMOVED"},
    "STARTED_UP": {"REMOVED"},
    "REMOVED": set(),
}


@bp.post("/equipment-units")
def create_equipment():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_CX_AUTHORITY])
    body = body_json()
    project_id = v_string(body, "project_id")
    tag = v_string(body, "tag")
    system_type = v_enum(body, "system_type", calc.SYSTEM_TYPES)
    criticality = v_enum(body, "criticality", calc.CRITICALITIES)
    contract_value_cents = v_int(body, "contract_value_cents", minimum=1)
    weight_units = v_int(body, "weight_units", minimum=1)

    get_project(project_id)

    row = new_row(db.equipment, {
        "project_id": project_id,
        "tag": tag,
        "system_type": system_type,
        "criticality": criticality,
        "contract_value_cents": contract_value_cents,
        "weight_units": weight_units,
        "install_status": "NOT_INSTALLED",
        "verification_status": "UNVERIFIED",
        "blocking_issue_count": 0,
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/equipment-units")
def list_equipment():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.equipment.values()))
    project_id = q("project_id")
    install_status = q("install_status")
    verification_status = q("verification_status")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if install_status is not None:
        rows = [r for r in rows if r["install_status"] == install_status]
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/equipment-units/<equipment_id>")
def read_equipment(equipment_id):
    authenticate(ALL_ROLES)
    return ok(public(get_equipment(equipment_id)))


@bp.post("/equipment-units/<equipment_id>/install-status")
def set_install_status(equipment_id):
    authenticate([ROLE_CONTRACTOR])
    equipment_row = get_equipment(equipment_id)
    body = body_json()
    target = v_enum(body, "install_status", calc.INSTALL_STATUSES)

    current = equipment_row["install_status"]
    if target not in ALLOWED_INSTALL_TRANSITIONS[current]:
        fail("ERR_INVALID_STATE",
             "install_status cannot move from %s to %s." % (current, target))

    equipment_row["install_status"] = target
    touch(equipment_row)

    if target == "REMOVED":
        services.cancel_scheduled_tests(equipment_row["id"], {"SCHEDULED", "IN_PROGRESS"})

    services.reconcile()
    return ok(public(equipment_row))
