"""Monthly family contact register (append-only)."""
from flask import Blueprint, request

import domain as D
from auth import STAFF_READ, endpoint, require_owner
from envelope import paginate, single
from errors import fail
from helpers import (get_contact_log, get_referral, not_future,
                     ser_contact_log)
from services import compute
from store import db, flush, month_of, new_row, ordered
from validate import Field, parse_body, v_date, v_enum, v_str

bp = Blueprint("contact_logs", __name__)


@bp.route("/ei/referrals/<referral_id>/contact-logs", methods=["POST"])
@endpoint(["ServiceCoordinator"])
def create_contact_log(referral_id):
    payload = parse_body([
        Field("contact_date", v_date()),
        Field("contact_method", v_enum(D.CONTACT_METHODS)),
        Field("contact_type", v_enum(D.CONTACT_TYPES)),
        Field("summary", v_str()),
    ])
    referral = get_referral(referral_id)
    require_owner(referral["coordinator_id"])
    if referral["status"] in D.REFERRAL_TERMINAL:
        fail("ERR_REFERRAL_STATE_INVALID",
             "A terminal case accepts no further contact entries.")
    not_future(payload["contact_date"], "contact_date")
    log = new_row({
        "referral_id": referral["id"],
        "contact_date": payload["contact_date"],
        "contact_month": month_of(payload["contact_date"]),
        "contact_method": payload["contact_method"],
        "contact_type": payload["contact_type"],
        "summary": payload["summary"],
        "qualifies_for_monthly_requirement":
            payload["contact_method"] in D.QUALIFYING_CONTACT_METHODS,
    }, versioned=False)
    db.contact_logs[log["id"]] = log
    compute.recompute_monthly_contact(referral)
    flush()
    return single(ser_contact_log(log), 201)


@bp.route("/ei/contact-logs", methods=["GET"])
@endpoint(STAFF_READ)
def list_contact_logs():
    rows = ordered(db.contact_logs)
    referral_id = request.args.get("referral_id")
    contact_method = request.args.get("contact_method")
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if contact_method is not None:
        rows = [r for r in rows if r["contact_method"] == contact_method]
    return paginate(rows, ser_contact_log)


@bp.route("/ei/contact-logs/<contact_log_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_contact_log(contact_log_id):
    return single(ser_contact_log(get_contact_log(contact_log_id)))
