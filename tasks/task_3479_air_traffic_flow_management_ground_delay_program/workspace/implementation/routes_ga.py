"""GAAccommodationRequest endpoints (PRD 3.7): request, adjudicate, list."""

from flask import Blueprint, request

from constants import GA_DECISIONS, PRIORITY_CLASSES, ROLE_FLOW_MANAGER, ROLE_OPERATOR, ROLES
from errors import ApiError
from ledger import recompute_fair_shares
from ops import (
    accommodate,
    accommodated_count,
    earliest_reserved_open_slot,
    reserved_slot_total,
)
from serialize import serialize_ga_request
from storage import DB, create_entity, touch
from util import body_json, paginate, req_dt, req_enum, req_str, success_object
from validation import (
    auth_context,
    check_window,
    get_ga_request,
    get_operator,
    get_tmi,
    require_roles,
    tmi_require_active,
)

bp = Blueprint("ga_requests", __name__)


@bp.route("/atfm/operators/<operator_id>/ga-requests", methods=["POST"])
def create_ga_request(operator_id):
    auth_context()
    require_roles(ROLE_OPERATOR)
    # Priority 3: the path operator must equal X-User-ID.
    if request.headers.get("X-User-ID") != operator_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "X-User-ID must equal the path operator id"
        )
    operator = get_operator(operator_id)
    body = body_json()
    tmi_id = req_str(body, "tmi_id")
    window_start = req_dt(body, "requested_window_start")
    window_end = req_dt(body, "requested_window_end")
    priority_class = req_enum(body, "priority_class", PRIORITY_CLASSES)
    tmi = get_tmi(tmi_id)
    # Priority 8: window well-formed.
    check_window(window_start, window_end)
    # Priority 10: the request window must lie entirely inside the program
    # window (program_start <= requested_start < requested_end <= program_end).
    if not (
        tmi["program_start"] <= window_start and window_end <= tmi["program_end"]
    ):
        raise ApiError(
            "ERR_GA_WINDOW_OUTSIDE_PROGRAM",
            "the requested window must lie entirely inside the program window",
        )
    # Priority 16: the target must be a GROUND_DELAY_PROGRAM.
    if tmi["tmi_type"] != "GROUND_DELAY_PROGRAM":
        raise ApiError(
            "ERR_TMI_TYPE_NOT_GDP",
            "GA accommodation targets only a GROUND_DELAY_PROGRAM",
        )
    # Priority 17: only GENERAL_AVIATION / UNSCHEDULED_CHARTER operators.
    if operator["operator_type"] not in ("GENERAL_AVIATION", "UNSCHEDULED_CHARTER"):
        raise ApiError(
            "ERR_OPERATOR_TYPE_INELIGIBLE",
            "GA accommodation is open to GENERAL_AVIATION and UNSCHEDULED_CHARTER only",
        )
    rec = create_entity(
        "ga_requests",
        {
            "operator_id": operator["id"],
            "tmi_id": tmi["id"],
            "requested_window_start": window_start,
            "requested_window_end": window_end,
            "priority_class": priority_class,
            "status": "REQUESTED",
            "accommodated_flight_id": None,
            "accommodated_slot_time": None,
        },
    )
    return success_object(serialize_ga_request(rec), 201)


@bp.route("/atfm/ga-requests/<request_id>/adjudicate", methods=["POST"])
def adjudicate_ga_request(request_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    ga_request = get_ga_request(request_id)
    body = body_json()
    decision = req_enum(body, "decision", GA_DECISIONS)
    tmi = get_tmi(ga_request["tmi_id"])
    # The program must be ACTIVE (PRD 3.7); then the request must be pending.
    tmi_require_active(tmi)
    if ga_request["status"] not in ("REQUESTED", "WAITLISTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only a REQUESTED or WAITLISTED GA request can be adjudicated",
        )
    if decision == "DENY":
        ga_request["status"] = "DENIED"
        touch(ga_request)
        return success_object(serialize_ga_request(ga_request))
    # ACCOMMODATE: quota predicate — accommodated_count < reserved_slots AND an
    # OPEN reserved slot exists inside the request window. Failure waitlists
    # the request instead of erroring.
    slot = None
    if accommodated_count(tmi["id"]) < reserved_slot_total(tmi):
        slot = earliest_reserved_open_slot(
            tmi["id"],
            ga_request["requested_window_start"],
            ga_request["requested_window_end"],
        )
    if slot is None:
        ga_request["status"] = "WAITLISTED"
        touch(ga_request)
        return success_object(serialize_ga_request(ga_request))
    accommodate(ga_request, slot)
    recompute_fair_shares(tmi["id"])
    return success_object(serialize_ga_request(ga_request))


@bp.route("/atfm/operators/<operator_id>/ga-requests", methods=["GET"])
def list_operator_ga_requests(operator_id):
    auth_context()
    require_roles(*ROLES)
    operator = get_operator(operator_id)
    status_filter = request.args.get("status")
    rows = [
        r
        for r in DB["ga_requests"].values()
        if r["operator_id"] == operator["id"]
        and (status_filter is None or r["status"] == status_filter)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate([serialize_ga_request(r) for r in rows])


@bp.route("/atfm/tmis/<tmi_id>/ga-requests", methods=["GET"])
def list_tmi_ga_requests(tmi_id):
    auth_context()
    require_roles(*ROLES)
    tmi = get_tmi(tmi_id)
    status_filter = request.args.get("status")
    rows = [
        r
        for r in DB["ga_requests"].values()
        if r["tmi_id"] == tmi["id"]
        and (status_filter is None or r["status"] == status_filter)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate([serialize_ga_request(r) for r in rows])
