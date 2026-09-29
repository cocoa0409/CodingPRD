from flask import Blueprint

import calc
import db
import middleware as mw
import response
from errors import ApiError
from routes.institutions import find_institution

bp = Blueprint("limits", __name__)

METRICS = ("BROKERED_TO_TOTAL_DEPOSITS", "LISTING_TO_TOTAL_DEPOSITS",
           "WHOLESALE_TO_TOTAL_LIABILITIES", "SINGLE_BROKER_TO_TOTAL_DEPOSITS")
READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


@bp.post("/institutions/<institution_id>/concentration-limits")
def create_limit(institution_id):
    mw.auth("SystemAdmin", "TreasuryController")
    institution = find_institution(institution_id)
    data = mw.body()
    metric = mw.req_enum(data, "metric", METRICS)
    warning = mw.req_int(data, "warning_threshold_bps", minimum=0)
    breach = mw.req_int(data, "breach_threshold_bps", minimum=0)

    if warning > 10000 or breach > 10000 or warning >= breach:
        raise ApiError("ERR_THRESHOLD_ORDER_INVALID")

    for existing in calc.active_limits(institution_id):
        if existing["metric"] != metric:
            continue
        existing["status"] = "RETIRED"
        existing["current_value_bps"] = 0
        existing["breach_state"] = "WITHIN"
        db.bump(existing)

    record = {
        "institution_id": institution_id,
        "metric": metric,
        "warning_threshold_bps": warning,
        "breach_threshold_bps": breach,
        "current_value_bps": 0,
        "breach_state": "WITHIN",
        "status": "ACTIVE",
    }
    db.stamp_new(record)
    db.concentration_limits[record["id"]] = record
    calc.recompute_institution(institution)
    return response.created(db.public(record))


@bp.get("/institutions/<institution_id>/concentration-limits")
def list_limits(institution_id):
    mw.auth(*READ_ROLES)
    find_institution(institution_id)
    limit, offset = mw.page()
    rows = [r for r in db.concentration_limits.values()
            if r["institution_id"] == institution_id]
    for field in ("status", "metric"):
        wanted = mw.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = db.by_created(rows)
    return response.listing(db.public_list(rows), limit, offset)
