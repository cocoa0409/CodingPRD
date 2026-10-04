"""POST /reemployment/service-periods — record an immutable service period."""
from flask import Blueprint

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_str, req_enum, req_day, opt_day, opt_dt,
    get_member, get_employer, ser_service_period,
    ORDERS_TYPES, EXEMPT_ORDERS,
)
from store import db
from util import now, new_id, success

bp = Blueprint("service_periods", __name__)


@bp.route("/reemployment/service-periods", methods=["POST"])
def create_service_period():
    role, uid = require_role("ServiceMember", "ProgramCoordinator")
    body = body_json()
    member_id = req_str(body, "member_id")
    employer_id = req_str(body, "employer_id")
    start_date = req_day(body, "start_date")
    orders_type = req_enum(body, "orders_type", ORDERS_TYPES)
    end_date = opt_day(body, "end_date")
    notice_given_at = opt_dt(body, "notice_given_at")
    if end_date is not None and end_date <= start_date:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "end_date must be strictly after start_date",
        )
    # Body FKs resolve in declared input order: member_id before employer_id.
    get_member(member_id)
    get_employer(employer_id)
    if role == "ServiceMember":
        require_ownership(member_id == uid)
    # Half-open [start_date, end_date) overlap across the member's periods,
    # any employer; adjacency (end == start) allowed; ongoing = infinity.
    for p in db.service_periods.values():
        if p["member_id"] != member_id:
            continue
        s2, e2 = p["start_date"], p["end_date"]
        if (e2 is None or start_date < e2) and (end_date is None or s2 < end_date):
            raise ApiError(
                "ERR_SERVICE_PERIOD_OVERLAP", 422,
                "Service period overlaps an existing period of this member",
            )
    duration_days = None if end_date is None else (end_date - start_date).days
    pid = new_id()
    rec = {
        "id": pid, "member_id": member_id, "employer_id": employer_id,
        "start_date": start_date, "end_date": end_date,
        "orders_type": orders_type, "notice_given_at": notice_given_at,
        "duration_days": duration_days,
        "chargeable": orders_type not in EXEMPT_ORDERS,
        "created_at": now(), "_seq": db.next_seq(),
    }
    db.service_periods[pid] = rec
    return success(ser_service_period(rec), "object", 201)
