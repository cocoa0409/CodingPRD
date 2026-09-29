"""Service lines on a plan."""
from flask import Blueprint, request

import domain as D
from auth import STAFF_READ, endpoint
from envelope import paginate, single
from errors import fail
from helpers import get_ifsp, get_line, ser_line
from services import compute
from store import db, flush, new_row, ordered, set_field
from validate import Field, parse_body, v_enum, v_id, v_int, v_str

bp = Blueprint("ifsp_services", __name__)


@bp.route("/ei/ifsp-services", methods=["POST"])
@endpoint(["ProgramAdmin"])
def create_line():
    payload = parse_body([
        Field("ifsp_id", v_id()),
        Field("service_type", v_enum(D.SERVICE_TYPES)),
        Field("setting_code", v_enum(D.SETTING_CODES)),
        Field("frequency_per_month", v_int(1, 30)),
        Field("units_per_session", v_int(1, 8)),
        Field("unit_rate_cents", v_int(1, 100000)),
        Field("planned_units_total", v_int(1, 4000)),
        Field("natural_environment_justification", v_str(20), required=False),
    ])
    if (payload["setting_code"] in D.NON_NATURAL_SETTINGS
            and not payload["natural_environment_justification"]):
        fail("ERR_INVALID_REQUEST",
             "A service line delivered in a CLINIC or PROGRAM_OFFICE must "
             "carry a natural_environment_justification.")
    plan = get_ifsp(payload["ifsp_id"])
    if plan["status"] not in D.IFSP_AMENDABLE:
        fail("ERR_IFSP_STATE_INVALID",
             "A plan in status '%s' accepts no further service "
             "lines." % plan["status"])
    line = new_row({
        "ifsp_id": plan["id"],
        "service_type": payload["service_type"],
        "setting_code": payload["setting_code"],
        "natural_environment_justification":
            payload["natural_environment_justification"],
        "frequency_per_month": payload["frequency_per_month"],
        "units_per_session": payload["units_per_session"],
        "unit_rate_cents": payload["unit_rate_cents"],
        "planned_units_total": payload["planned_units_total"],
        "family_fee_exempt":
            payload["service_type"] in D.FEE_EXEMPT_SERVICE_TYPES,
        "declined_by_family": False,
        "units_committed": 0,
        "units_pool_remaining": payload["planned_units_total"],
        "units_delivered": 0,
        "makeup_owed_units": 0,
        "status": "PLANNED",
    })
    db.ifsp_services[line["id"]] = line
    compute.recompute_ifsp_counts(plan)
    if plan["status"] == "DRAFT":
        set_field(plan, "status", "PENDING_CONSENT")
    elif plan["status"] == "ACTIVE":
        set_field(plan, "status", "AMENDMENT_PENDING")
    referral = compute.referral_of_ifsp(plan)
    if referral is not None:
        compute.recompute_case_weight(referral)
        compute.recompute_service_gap(referral)
        compute.recompute_coordinator(
            db.coordinators.get(referral["coordinator_id"]))
    flush()
    return single(ser_line(line), 201)


@bp.route("/ei/ifsp-services/<service_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_line(service_id):
    return single(ser_line(get_line(service_id)))


@bp.route("/ei/ifsp-services", methods=["GET"])
@endpoint(STAFF_READ)
def list_lines():
    rows = ordered(db.ifsp_services)
    ifsp_id = request.args.get("ifsp_id")
    status = request.args.get("status")
    if ifsp_id is not None:
        rows = [r for r in rows if r["ifsp_id"] == ifsp_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_line)
