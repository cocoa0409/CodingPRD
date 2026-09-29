"""The technician roster."""

from flask import Blueprint

import auth
import envelope
import serialize
import store
import validate

bp = Blueprint("technicians", __name__)

CERTIFICATION_LEVELS = ("RECOVERY_ONLY", "RECOVERY_AND_EVAL")
TECHNICIAN_STATUSES = ("ACTIVE", "INACTIVE")


@bp.post("/eye-bank/technicians")
def create_technician():
    auth.authenticate(("EyeBankCoordinator",))
    body = auth.body_dict()

    full_name = validate.req_str(body, "full_name", 1, 80)
    level = validate.req_enum(body, "certification_level", CERTIFICATION_LEVELS)
    expires_at = validate.req_dt(body, "certification_expires_at")

    row = store.base_row()
    row.update(
        {
            "full_name": full_name,
            "certification_level": level,
            "certification_expires_at": expires_at,
            "status": "ACTIVE",
            "open_dispatch_count": 0,
        }
    )
    store.DB["technicians"][row["id"]] = row
    return envelope.ok(serialize.technician(row), 201)


@bp.get("/eye-bank/technicians/<technician_id>")
def get_technician(technician_id):
    auth.authenticate(
        (
            "EyeBankCoordinator",
            "MedicalDirector",
            "RecoveryTechnician",
            "EvaluationTechnician",
        )
    )
    row = validate.lookup("technicians", technician_id)
    return envelope.ok(serialize.technician(row))


@bp.post("/eye-bank/technicians/<technician_id>/status")
def set_technician_status(technician_id):
    auth.authenticate(("EyeBankCoordinator",))
    row = validate.lookup("technicians", technician_id)
    body = auth.body_dict()
    status = validate.req_enum(body, "status", TECHNICIAN_STATUSES)
    row["status"] = status
    store.touch(row)
    return envelope.ok(serialize.technician(row))


@bp.get("/eye-bank/technicians/<technician_id>/tissue-evaluations")
def list_technician_evaluations(technician_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "EvaluationTechnician"))
    validate.lookup("technicians", technician_id)
    rows = [
        e
        for e in store.DB["evaluations"].values()
        if e["evaluator_technician_id"] == technician_id
    ]
    rows = store.sort_desc(rows, lambda r: r["performed_at"])
    return envelope.nested_list(rows, serialize.evaluation)
