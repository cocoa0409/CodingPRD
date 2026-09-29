"""Service coordinator roster and caseload reporting."""
from flask import Blueprint

import domain as D
from auth import STAFF_READ, endpoint
from envelope import single
from helpers import get_coordinator, ser_coordinator
from services import compute
from store import db, flush, new_row, q2
from validate import (Field, parse_body, v_enum, v_list, v_num, v_str, v_token)

bp = Blueprint("coordinators", __name__)


@bp.route("/ei/service-coordinators", methods=["POST"])
@endpoint(["ProgramAdmin"])
def create_coordinator():
    payload = parse_body([
        Field("full_name", v_str()),
        Field("county_code", v_token()),
        Field("language_codes", v_list(v_token(), min_items=1)),
        Field("max_weighted_caseload_points", v_num(1.00, 40.00)),
        Field("status", v_enum(D.COORDINATOR_STATUSES), required=False,
              default="ACTIVE"),
    ])
    coordinator = new_row({
        "full_name": payload["full_name"],
        "county_code": payload["county_code"],
        "language_codes": payload["language_codes"],
        "max_weighted_caseload_points": q2(payload["max_weighted_caseload_points"]),
        "weighted_caseload_points": 0.00,
        "active_case_count": 0,
        "utilization_ratio": 0.0,
        "status": payload["status"],
    })
    db.coordinators[coordinator["id"]] = coordinator
    flush()
    return single(ser_coordinator(coordinator), 201)


@bp.route("/ei/service-coordinators/<coordinator_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_coordinator(coordinator_id):
    return single(ser_coordinator(get_coordinator(coordinator_id)))


@bp.route("/ei/service-coordinators/<coordinator_id>/caseload-summary",
          methods=["GET"])
@endpoint(STAFF_READ)
def caseload_summary(coordinator_id):
    coordinator = get_coordinator(coordinator_id)
    return single({
        "coordinator_id": coordinator["id"],
        "active_case_count": coordinator["active_case_count"],
        "weighted_caseload_points": coordinator["weighted_caseload_points"],
        "max_weighted_caseload_points": coordinator["max_weighted_caseload_points"],
        "utilization_ratio": coordinator["utilization_ratio"],
        "caseload_posture": compute.caseload_posture(coordinator),
        "headroom_points": compute.headroom_points(coordinator),
    })
