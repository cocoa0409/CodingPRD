"""Trade programs: create and administrative PATCH."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record, bump
from envelope import ok_object
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from helpers import get_body, check_unknown, as_str, as_int, as_bool, as_enum, as_list_enum
import domain
import serializers

bp = Blueprint("trade_programs", __name__)

CREDENTIAL_TYPES = {"HSE", "INDUSTRY_CERT", "DRIVER_LICENSE"}


def get_program_or_404(program_id):
    t = STORE.trade_programs.get(program_id)
    if t is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Trade program not found")
    return t


@bp.route("/jc/trade-programs", methods=["POST"])
def create_program():
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    body = get_body()
    check_unknown(
        body,
        {"center_id", "trade_code", "capacity", "required_credential_types", "supports_remediation"},
    )
    center_id = as_str(body, "center_id", required=True)
    trade_code = as_str(body, "trade_code", required=True)
    capacity = as_int(body, "capacity", required=True, lo=1)
    required = as_list_enum(body, "required_credential_types", CREDENTIAL_TYPES)
    if required is None:
        required = []
    supports = as_bool(body, "supports_remediation")
    if supports is None:
        supports = False
    if center_id not in STORE.centers:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Center not found")
    rec = new_record()
    rec.update(
        {
            "center_id": center_id,
            "trade_code": trade_code,
            "capacity": capacity,
            "required_credential_types": required,
            "supports_remediation": supports,
            "_closed": False,
        }
    )
    STORE.trade_programs[rec["id"]] = rec
    return ok_object(serializers.trade_program_view(rec), status=201)


@bp.route("/jc/trade-programs/<program_id>", methods=["PATCH"])
def patch_program(program_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    t = get_program_or_404(program_id)
    body = get_body()
    check_unknown(body, {"capacity", "status"})
    capacity = as_int(body, "capacity", lo=1) if "capacity" in body else None
    status = as_enum(body, "status", ["OPEN", "FULL", "CLOSED"]) if "status" in body else None
    if capacity is not None:
        enrolled = domain.program_enrolled_count(t["id"])
        if capacity < enrolled:
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                ERR_INVALID_REQUEST[1],
                "capacity may not be lowered below the current enrolled_count",
            )
    if status is not None:
        current = domain.program_status(t)
        if status != "CLOSED" or current == "CLOSED":
            raise ApiError(
                ERR_INVALID_STATE[0],
                ERR_INVALID_STATE[1],
                "Only a transition to CLOSED is defined for a trade program",
            )
    if capacity is not None:
        t["capacity"] = capacity
    if status == "CLOSED":
        t["_closed"] = True
    bump(t)
    return ok_object(serializers.trade_program_view(t), status=200)
