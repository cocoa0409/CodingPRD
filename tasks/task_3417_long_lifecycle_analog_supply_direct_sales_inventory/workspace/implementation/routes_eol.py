# End-of-life program routes (PRD 3.7): notices and rescission.
from datetime import timedelta

from flask import Blueprint

import constants as C
from auth import require_roles
from envelope import success
from errors import (
    ApiError,
    ERR_EOL_NOTICE_ACTIVE_EXISTS,
    ERR_EOL_WINDOW_INVALID,
    ERR_INVALID_STATE,
)
from lookups import get_eol_notice, get_part
from serialize import eol_notice_public
from store import store
from validate import (
    as_datetime,
    as_str,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("eol", __name__)

_CREATE_ALLOWED = {"notice_date", "last_order_date", "last_ship_date", "reason"}


@bp.post("/parts/<part_id>/eol-notices")
def create_eol_notice(part_id):
    require_roles("SupplyPlanner")
    part = get_part(part_id)
    body = get_body(required=True)
    require_fields(body, ["notice_date", "last_order_date", "last_ship_date"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    notice_date = as_datetime(body["notice_date"], "notice_date")
    last_order_date = as_datetime(body["last_order_date"], "last_order_date")
    last_ship_date = as_datetime(body["last_ship_date"], "last_ship_date")
    reason = None
    if "reason" in body:
        reason = as_str(body["reason"], "reason")

    # Row 5: DISCONTINUED is terminal; no further notices may drive it.
    if part["lifecycle_status"] == "DISCONTINUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Part is DISCONTINUED")

    # Row 7: a second ANNOUNCED notice whose closed window
    # [notice_date, last_ship_date] intersects an existing ANNOUNCED notice's
    # closed window conflicts; closed intervals, so touching endpoints count.
    for existing in store.eol_notices.values():
        if existing["part_id"] != part["id"] or existing["status"] != "ANNOUNCED":
            continue
        if notice_date <= existing["last_ship_date"] and existing["notice_date"] <= last_ship_date:
            raise ApiError(ERR_EOL_NOTICE_ACTIVE_EXISTS, 409, "Part already has an ANNOUNCED notice with an intersecting window")

    # Row 8: window shape — minimum separations (inclusive bounds).
    if last_order_date < notice_date + timedelta(days=C.EOL_NOTICE_MIN_DAYS):
        raise ApiError(ERR_EOL_WINDOW_INVALID, 422, "last_order_date must be at least %d days after notice_date" % C.EOL_NOTICE_MIN_DAYS)
    if last_ship_date < last_order_date + timedelta(days=C.LAST_SHIP_MIN_DAYS_AFTER_ORDER):
        raise ApiError(ERR_EOL_WINDOW_INVALID, 422, "last_ship_date must be at least %d days after last_order_date" % C.LAST_SHIP_MIN_DAYS_AFTER_ORDER)

    notice = {
        "part_id": part["id"],
        "notice_date": notice_date,
        "last_order_date": last_order_date,
        "last_ship_date": last_ship_date,
        "reason": reason,
        "status": "ANNOUNCED",
    }
    notice.update(store.stamp())
    store.eol_notices[notice["id"]] = notice
    # Side effect: drive the part to EOL_ANNOUNCED (from ACTIVE or NRND; a part
    # already further along the EOL path keeps its lifecycle). The design-win
    # at_risk cascade is derived from the part's lifecycle at read time.
    if part["lifecycle_status"] in ("ACTIVE", "NRND"):
        part["lifecycle_status"] = "EOL_ANNOUNCED"
        store.touch(part)
    return success(eol_notice_public(notice), 201)


@bp.post("/eol-notices/<notice_id>/rescind")
def rescind_eol_notice(notice_id):
    require_roles("SupplyPlanner")
    notice = get_eol_notice(notice_id)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    part = store.parts.get(notice["part_id"])
    if notice["status"] != "ANNOUNCED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ANNOUNCED notice can be rescinded")
    if part is None or part["lifecycle_status"] != "EOL_ANNOUNCED":
        raise ApiError(ERR_INVALID_STATE, 409, "The part has already advanced beyond EOL_ANNOUNCED")
    notice["status"] = "RESCINDED"
    store.touch(notice)
    # Rescission always restores ACTIVE.
    part["lifecycle_status"] = "ACTIVE"
    store.touch(part)
    return success(eol_notice_public(notice))
