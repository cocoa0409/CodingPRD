"""The check-in kiosk and its two independent state dimensions (PRD 3.5)."""
from flask import Blueprint

import calc
import cascades
import db
from db import store
from errors import ApiError
from reqval import authenticate, read_body
from routes import common
from timeutil import parse_instant

bp = Blueprint("kiosk", __name__, url_prefix="/vendor-access")


def _next_badge_serial(facility):
    """facility.code + '-' + a four-digit zero-padded per-facility counter that
    starts at 0001 and is handed out in check-in order.
    """
    counter = store.badge_counters.get(facility["id"], 0) + 1
    store.badge_counters[facility["id"]] = counter
    return "%s-%04d" % (facility["code"], counter)


@bp.post("/kiosk-check-ins")
def check_in():
    user_id, role = authenticate(("VendorRepUser", "ORCoordinator"))
    body = read_body()
    case_rep_authorization_id = body.string("case_rep_authorization_id")

    auth = common.authorization(case_rep_authorization_id)
    rep = store.vendor_reps.get(auth["vendor_rep_id"])
    case = store.surgical_cases.get(auth["surgical_case_id"])
    common.require_rep_scope(role, user_id, auth["vendor_rep_id"])

    if rep["access_status"] == "REVOKED":
        raise ApiError("ERR_REP_ACCESS_REVOKED")
    if rep["access_status"] == "SUSPENDED":
        raise ApiError("ERR_REP_ACCESS_SUSPENDED")
    if auth["status"] != "APPROVED":
        raise ApiError("ERR_AUTHORIZATION_NOT_APPROVED")
    if calc.compute_credential_posture(rep) not in ("COMPLIANT", "EXPIRING_SOON"):
        raise ApiError("ERR_REP_CREDENTIALS_NOT_COMPLIANT")

    # The badge window test is inclusive at both ends.
    now = db.now()
    window_start = parse_instant(auth["badge_window_start_utc"])
    window_end = parse_instant(auth["badge_window_end_utc"])
    if window_start is None or window_end is None or now < window_start or now > window_end:
        raise ApiError("ERR_BADGE_WINDOW_NOT_OPEN")

    for existing in calc.check_ins_of_authorization(auth["id"]):
        if existing["badge_status"] == "ISSUED":
            raise ApiError("ERR_CHECK_IN_ALREADY_ACTIVE")

    facility = calc.case_facility(case)
    row = db.stamp_common(
        {
            "case_rep_authorization_id": auth["id"],
            "badge_serial": _next_badge_serial(facility),
            "badge_status": "ISSUED",
            "escort_status": "ESCORT_PENDING"
            if auth["escort_required"]
            else "ESCORT_NOT_REQUIRED",
            "issued_at_utc": db.now_str(),
            "valid_from_utc": auth["badge_window_start_utc"],
            "valid_until_utc": auth["badge_window_end_utc"],
            "escort_user_id": None,
            "escort_attached_at_utc": None,
            "checked_out_at_utc": None,
        }
    )
    store.check_ins[row["id"]] = row
    return common.created(row)


@bp.get("/kiosk-check-ins/<row_id>")
def read_check_in(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.check_in(row_id))


@bp.post("/kiosk-check-ins/<row_id>/attach-escort")
def attach_escort(row_id):
    authenticate(("ORCoordinator",))
    body = read_body()
    escort_user_id = body.string("escort_user_id")

    check_in_row = common.check_in(row_id)
    if check_in_row["badge_status"] != "ISSUED":
        raise ApiError("ERR_CHECK_IN_NOT_ACTIVE")
    if check_in_row["escort_status"] != "ESCORT_PENDING":
        raise ApiError("ERR_ESCORT_NOT_PENDING")

    check_in_row["escort_status"] = "ESCORT_ATTACHED"
    check_in_row["escort_user_id"] = escort_user_id
    check_in_row["escort_attached_at_utc"] = db.now_str()
    # badge_status is left exactly where it was, at ISSUED.
    cascades.mark(check_in_row)
    cascades.flush()
    return common.ok(check_in_row)


@bp.post("/kiosk-check-ins/<row_id>/check-out")
def check_out(row_id):
    user_id, role = authenticate(("VendorRepUser", "ORCoordinator"))
    read_body()

    check_in_row = common.check_in(row_id)
    auth = store.authorizations.get(check_in_row["case_rep_authorization_id"])
    rep = store.vendor_reps.get(auth["vendor_rep_id"]) if auth else None
    if auth is not None:
        common.require_rep_scope(role, user_id, auth["vendor_rep_id"])

    if rep is not None and rep["access_status"] == "REVOKED":
        raise ApiError("ERR_REP_ACCESS_REVOKED")
    if check_in_row["badge_status"] != "ISSUED":
        raise ApiError("ERR_CHECK_IN_NOT_ACTIVE")
    if check_in_row["escort_status"] == "ESCORT_PENDING":
        raise ApiError("ERR_ESCORT_REQUIRED")

    check_in_row["badge_status"] = "CHECKED_OUT"
    check_in_row["checked_out_at_utc"] = db.now_str()
    # The only point at which the two dimensions interact.
    if check_in_row["escort_status"] == "ESCORT_ATTACHED":
        check_in_row["escort_status"] = "ESCORT_RELEASED"
    cascades.mark(check_in_row)
    cascades.flush()
    return common.ok(check_in_row)
