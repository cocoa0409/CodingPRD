"""ImporterFirm onboarding and Laboratory registration (PRD section 3.2)."""
from flask import Blueprint

import db
import serialize
import services
from auth import require_roles
from envelope import ok, json_body
from errors import ApiError

bp = Blueprint("importers", __name__)


@bp.post("/registry/importers")
@require_roles("PlatformAdmin")
def create_importer(caller_id, caller_role):
    body = json_body()
    account_code = body.get("account_code")
    # Tier 9: uniqueness.
    if isinstance(account_code, str) and account_code:
        for m in db.importers.values():
            if m["account_code"] == account_code:
                raise ApiError("ERR_DUPLICATE_ACCOUNT_CODE")
    # Tier 12: request shape.
    firm_name = body.get("firm_name")
    if not isinstance(firm_name, str) or not firm_name:
        raise ApiError("ERR_INVALID_REQUEST", "firm_name is required")
    if not isinstance(account_code, str) or not account_code:
        raise ApiError("ERR_INVALID_REQUEST", "account_code is required")

    m = db.new_common()
    m.update(
        {
            "firm_name": firm_name,
            "account_code": account_code,
            "standing": "GOOD_STANDING",
            "refusal_count": 0,
            "terminal_entry_count": 0,
        }
    )
    db.importers[m["id"]] = m
    return ok(serialize.importer(m), 201)


@bp.post("/registry/laboratories")
@require_roles("PlatformAdmin")
def create_laboratory(caller_id, caller_role):
    body = json_body()
    lab_code = body.get("lab_code")
    # Tier 9: uniqueness.
    if isinstance(lab_code, str) and lab_code:
        for lab in db.laboratories.values():
            if lab["lab_code"] == lab_code:
                raise ApiError("ERR_DUPLICATE_LAB_CODE")
    # Tier 12: request shape.
    capacity = body.get("daily_sample_capacity")
    if not isinstance(lab_code, str) or not lab_code:
        raise ApiError("ERR_INVALID_REQUEST", "lab_code is required")
    if not services.is_int(capacity) or capacity <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "daily_sample_capacity must be an integer greater than 0"
        )

    lab = db.new_common()
    lab.update({"lab_code": lab_code, "daily_sample_capacity": capacity})
    db.laboratories[lab["id"]] = lab
    return ok(serialize.laboratory(lab), 201)
