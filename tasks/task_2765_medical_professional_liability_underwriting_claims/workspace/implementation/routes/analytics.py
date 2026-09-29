"""The severity trend computed read (PRD 3.9)."""
from flask import Blueprint

import constants as C
from auth import endpoint, specialty_class
from envelope import ok
from errors import ApiError
from routes import common
from val import parse_date
from services import actuarial

bp = Blueprint("analytics", __name__, url_prefix=C.API_PREFIX)


@bp.get("/analytics/severity-trend")
@endpoint(C.CARRIER_ROLES)
def severity_trend():
    specialty_class_id = common.arg("specialty_class_id")
    if specialty_class_id is None:
        raise ApiError("ERR_VALIDATION", "specialty_class_id is required.")
    venue_code = common.arg("venue_code")
    if venue_code is not None and venue_code not in C.VENUE_CODES:
        raise ApiError("ERR_VALIDATION", "venue_code must be a published venue.")
    from_report_date = common.arg("from_report_date")
    if from_report_date is not None:
        parse_date(from_report_date, "ERR_VALIDATION", "from_report_date")
    to_report_date = common.arg("to_report_date")
    if to_report_date is not None:
        parse_date(to_report_date, "ERR_VALIDATION", "to_report_date")

    specialty_class(specialty_class_id)
    return ok(
        actuarial.severity_trend(
            specialty_class_id, venue_code, from_report_date, to_report_date
        )
    )
