"""Centers and their nested trade-program / operator-contract listings."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record
from envelope import ok_object, ok_list
from errors import ApiError, ERR_NOT_FOUND
from helpers import get_body, check_unknown, as_str, as_int, pagination_params, paginate
import serializers

bp = Blueprint("centers", __name__)


def get_center_or_404(center_id):
    c = STORE.centers.get(center_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Center not found")
    return c


@bp.route("/jc/centers", methods=["POST"])
def create_center():
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    body = get_body()
    check_unknown(body, {"name", "region_code", "total_beds"})
    rec = new_record()
    rec.update(
        {
            "name": as_str(body, "name", required=True),
            "region_code": as_str(body, "region_code", required=True),
            "total_beds": as_int(body, "total_beds", required=True, lo=1),
        }
    )
    STORE.centers[rec["id"]] = rec
    return ok_object(serializers.center_view(rec), status=201)


@bp.route("/jc/centers/<center_id>", methods=["GET"])
def get_center(center_id):
    user_id, role = authenticate()
    require_role(
        role, {"OperatorAdmin", "AdmissionsCounselor", "EnrollmentManager", "ResidentialAdvisor"}
    )
    c = get_center_or_404(center_id)
    return ok_object(serializers.center_view(c))


@bp.route("/jc/centers/<center_id>/operator-contracts", methods=["GET"])
def list_center_contracts(center_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    c = get_center_or_404(center_id)
    limit, offset = pagination_params()
    items = [k for k in STORE.operator_contracts.values() if k["center_id"] == c["id"]]
    items.sort(key=lambda k: k["_seq"])
    page, meta = paginate([serializers.contract_view(k) for k in items], limit, offset)
    return ok_list(page, meta)


@bp.route("/jc/centers/<center_id>/trade-programs", methods=["GET"])
def list_center_programs(center_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin", "AdmissionsCounselor", "EnrollmentManager"})
    c = get_center_or_404(center_id)
    limit, offset = pagination_params()
    items = [t for t in STORE.trade_programs.values() if t["center_id"] == c["id"]]
    items.sort(key=lambda t: t["_seq"])
    page, meta = paginate([serializers.trade_program_view(t) for t in items], limit, offset)
    return ok_list(page, meta)
