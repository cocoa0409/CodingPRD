"""Prescriber and prescriber-scoped opt-out endpoints."""

from flask import Blueprint, request

from db import db
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_prescriber_not_active,
    err_duplicate_opt_out,
)
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.common import body_json, check_str, check_str_opt, check_enum, mint, touch

bp = Blueprint("prescribers", __name__)

SPECIALTIES = {"CARDIOLOGY", "ONCOLOGY", "ENDOCRINOLOGY", "PRIMARY_CARE"}
PRESCRIBER_STATUSES = {"ACTIVE", "INACTIVE"}


def _get_prescriber(pid):
    prescriber = db.prescribers.get(pid)
    if prescriber is None:
        raise err_not_found("Prescriber not found")
    return prescriber


@bp.route("/prescribers", methods=["POST"])
def create_prescriber():
    require_role(["PlatformAdmin"])
    data = body_json()
    for f in ("full_name", "npi", "state_code", "specialty"):
        if f not in data or data[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")
    prescriber = mint(db.prescribers, {
        "full_name": check_str(data, "full_name"),
        "npi": check_str(data, "npi"),
        "state_code": check_str(data, "state_code"),
        "specialty": check_enum(data, "specialty", SPECIALTIES),
        "status": "ACTIVE",
    })
    return success_object(prescriber, status=201)


@bp.route("/prescribers", methods=["GET"])
def list_prescribers():
    require_role(ALL_ROLES)
    limit, offset = get_pagination()
    state_code = request.args.get("state_code")
    specialty = request.args.get("specialty")
    status = request.args.get("status")
    if specialty is not None and specialty not in SPECIALTIES:
        raise err_invalid_request("Invalid specialty filter")
    if status is not None and status not in PRESCRIBER_STATUSES:
        raise err_invalid_request("Invalid status filter")
    items = sorted(db.prescribers.values(), key=lambda p: p["created_at"])
    if state_code is not None:
        items = [p for p in items if p["state_code"] == state_code]
    if specialty is not None:
        items = [p for p in items if p["specialty"] == specialty]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/prescribers/<pid>", methods=["GET"])
def get_prescriber(pid):
    require_role(ALL_ROLES)
    return success_object(_get_prescriber(pid))


@bp.route("/prescribers/<pid>/deactivate", methods=["POST"])
def deactivate_prescriber(pid):
    require_role(["PlatformAdmin"])
    prescriber = _get_prescriber(pid)
    if prescriber["status"] != "ACTIVE":
        raise err_invalid_state("Prescriber must be ACTIVE to deactivate")
    prescriber["status"] = "INACTIVE"
    touch(prescriber)
    return success_object(prescriber)


@bp.route("/prescribers/<pid>/reactivate", methods=["POST"])
def reactivate_prescriber(pid):
    require_role(["PlatformAdmin"])
    prescriber = _get_prescriber(pid)
    if prescriber["status"] != "INACTIVE":
        raise err_invalid_state("Prescriber must be INACTIVE to reactivate")
    prescriber["status"] = "ACTIVE"
    touch(prescriber)
    return success_object(prescriber)


@bp.route("/prescribers/<pid>/opt-outs", methods=["POST"])
def create_opt_out(pid):
    require_role(["PrivacyOfficer"])
    prescriber = _get_prescriber(pid)
    data = body_json()
    reason = check_str_opt(data, "reason")
    if prescriber["status"] != "ACTIVE":
        raise err_prescriber_not_active()
    for oo in db.opt_outs.values():
        if oo["prescriber_id"] == pid and oo["status"] in ("SUBMITTED", "VERIFIED", "ACTIVE"):
            raise err_duplicate_opt_out()
    opt_out = mint(db.opt_outs, {
        "prescriber_id": pid,
        "reason": reason,
        "status": "SUBMITTED",
    })
    return success_object(opt_out, status=201)


@bp.route("/prescribers/<pid>/opt-outs", methods=["GET"])
def list_prescriber_opt_outs(pid):
    require_role(ALL_ROLES)
    _get_prescriber(pid)
    limit, offset = get_pagination()
    items = sorted(
        (o for o in db.opt_outs.values() if o["prescriber_id"] == pid),
        key=lambda o: o["created_at"],
    )
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)
