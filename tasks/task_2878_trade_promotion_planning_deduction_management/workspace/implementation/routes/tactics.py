"""Tactic lines: creation, the trade-calendar contention rules and rate
maintenance (PRD 3.3 / 3.4)."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request

import calc
from db import clock_dt, db, new_row, touch
from errors import ApiError, bad_request
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    PREFIX,
    created_asc,
    get_promotion,
    get_tactic,
    page,
)
from routes.promotions import check_week_window
from validators import (
    authenticate,
    body_fields,
    get_date,
    get_enum,
    get_int,
    get_money,
    get_rate,
    get_string,
    no_body,
    pagination,
    query_enum,
    query_value,
)

bp = Blueprint("tactics", __name__)

KAM = "KeyAccountManager"
TACTIC_TYPES = ("TPR", "DISPLAY", "FEATURE")
TACTIC_STATUSES = ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")


# --------------------------------------------------------------------------
# contention helpers
# --------------------------------------------------------------------------

def _candidates(tactic_type, exclude_id):
    """Lines whose status is PLANNED, ACTIVE or COMPLETED, of one type,
    annotated with the customer and brand of their owning promotion."""
    out = []
    for line in db.tactics.values():
        if line["id"] == exclude_id:
            continue
        if line["tactic_type"] != tactic_type:
            continue
        if line["status"] not in calc.LIVE_TACTIC_STATUSES:
            continue
        promo = db.promotions.get(line["promotion_id"])
        if promo is None:
            continue
        out.append((line, promo))
    return out


def check_display_exclusivity(promo, start, end, exclude_id):
    """Rung 73: no overlapping DISPLAY line on the same customer and brand."""
    for line, other in _candidates("DISPLAY", exclude_id):
        if other["customer_id"] != promo["customer_id"]:
            continue
        if other["brand_id"] != promo["brand_id"]:
            continue
        if start < line["window_end"] and line["window_start"] < end:
            raise ApiError("ERR_DISPLAY_WINDOW_CONFLICT")


def check_feature_cooldown(promo, start, end, exclude_id):
    """Rung 74: a seven day gap from every other FEATURE line on the brand,
    across all customers."""
    gap = timedelta(days=calc.FEATURE_COOLDOWN_DAYS)
    for line, other in _candidates("FEATURE", exclude_id):
        if other["brand_id"] != promo["brand_id"]:
            continue
        after = start >= line["window_end"] + gap
        before = end + gap <= line["window_start"]
        if not (after or before):
            raise ApiError("ERR_FEATURE_COOLDOWN_CONFLICT")


def check_tpr_capacity(promo, start, end, exclude_id):
    """Rung 80: at most two TPR lines cover any single day for one
    customer and brand, counted across promotions."""
    peers = []
    for line, other in _candidates("TPR", exclude_id):
        if other["customer_id"] != promo["customer_id"]:
            continue
        if other["brand_id"] != promo["brand_id"]:
            continue
        peers.append(line)
    day = start
    while day < end:
        covering = 1
        for line in peers:
            if line["window_start"] <= day < line["window_end"]:
                covering += 1
        if covering > calc.TPR_CONCURRENCY_CAP:
            raise ApiError("ERR_TPR_CAPACITY_EXCEEDED")
        day = day + timedelta(days=1)


def check_type_money(tactic_type, rate, fee):
    """Rung 81: the type carries exactly the right money field."""
    if tactic_type == "TPR":
        if rate is None or fee is not None:
            raise ApiError("ERR_TACTIC_TYPE_RATE_MISMATCH")
    else:
        if fee is None or rate is not None:
            raise ApiError("ERR_TACTIC_TYPE_RATE_MISMATCH")


def check_containment(promo, start, end):
    """Rung 71."""
    if start < promo["window_start"] or end > promo["window_end"]:
        raise ApiError("ERR_TACTIC_WINDOW_OUTSIDE_PROMOTION")


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/promotions/<promotion_id>/tactics")
def create_tactic(promotion_id):
    authenticate([KAM])
    data = body_fields(
        required=["tactic_type", "planned_units", "window_start", "window_end"],
        optional=["rate_per_case", "fixed_fee"],
    )
    tactic_type = get_enum(data, "tactic_type", TACTIC_TYPES)
    planned_units = get_int(data, "planned_units", minimum=0)
    window_start = get_date(data, "window_start")
    window_end = get_date(data, "window_end")
    rate = get_rate(data, "rate_per_case", required=False, strictly_positive=True)
    fee = get_money(data, "fixed_fee", required=False, strictly_positive=True)

    promo = get_promotion(promotion_id)
    # rung 43
    if promo["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rungs 70 - 81
    check_week_window(window_start, window_end)
    check_containment(promo, window_start, window_end)
    if tactic_type == "DISPLAY":
        check_display_exclusivity(promo, window_start, window_end, None)
    if tactic_type == "FEATURE":
        check_feature_cooldown(promo, window_start, window_end, None)
    if tactic_type == "TPR":
        check_tpr_capacity(promo, window_start, window_end, None)
    check_type_money(tactic_type, rate, fee)

    row = new_row()
    row.update({
        "promotion_id": promotion_id,
        "tactic_type": tactic_type,
        "rate_per_case": rate,
        "fixed_fee": fee,
        "planned_units": planned_units,
        "window_start": window_start,
        "window_end": window_end,
        "status": "PLANNED",
        "effective_from_period": None,
        "cancel_reason": None,
    })
    db.tactics[row["id"]] = row
    touch(promo)
    return created_response(calc.tactic_out(row))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get(PREFIX + "/promotions/<promotion_id>/tactics")
def list_promotion_tactics(promotion_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination(["tactic_type", "status"])
    tactic_type = query_enum("tactic_type", TACTIC_TYPES)
    status = query_enum("status", TACTIC_STATUSES)
    get_promotion(promotion_id)
    rows = calc.tactics_of_promotion(promotion_id)
    if tactic_type is not None:
        rows = [r for r in rows if r["tactic_type"] == tactic_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(created_asc(rows), limit, offset, calc.tactic_out)


@bp.get(PREFIX + "/tactics")
def list_tactics():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["promotion_id", "tactic_type", "status"])
    promotion_id = query_value("promotion_id")
    tactic_type = query_enum("tactic_type", TACTIC_TYPES)
    status = query_enum("status", TACTIC_STATUSES)
    rows = list(db.tactics.values())
    if promotion_id is not None:
        get_promotion(promotion_id)
        rows = [r for r in rows if r["promotion_id"] == promotion_id]
    if tactic_type is not None:
        rows = [r for r in rows if r["tactic_type"] == tactic_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(created_asc(rows), limit, offset, calc.tactic_out)


@bp.get(PREFIX + "/tactics/<tactic_id>")
def read_tactic(tactic_id):
    authenticate(ALL_ROLES)
    no_body()
    return object_response(calc.tactic_out(get_tactic(tactic_id)))


# --------------------------------------------------------------------------
# rate maintenance
# --------------------------------------------------------------------------

@bp.patch(PREFIX + "/tactics/<tactic_id>")
def patch_tactic(tactic_id):
    authenticate([KAM])
    data = body_fields(
        required=["expected_promotion_version"],
        optional=["rate_per_case", "fixed_fee", "planned_units",
                  "window_start", "window_end"],
    )
    expected = get_int(data, "expected_promotion_version", minimum=0)
    rate = get_rate(data, "rate_per_case", required=False, strictly_positive=True)
    fee = get_money(data, "fixed_fee", required=False, strictly_positive=True)
    planned_units = get_int(data, "planned_units", required=False, minimum=0)
    window_start = get_date(data, "window_start", required=False)
    window_end = get_date(data, "window_end", required=False)

    tactic = get_tactic(tactic_id)
    promo = db.promotions.get(tactic["promotion_id"])
    # rung 31
    if promo is None or expected != promo["version"]:
        raise ApiError("ERR_STALE_PROMOTION_VERSION")
    # rung 43
    if promo["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rung 44
    if tactic["status"] != "PLANNED":
        raise ApiError("ERR_TACTIC_STATE_INVALID")

    new_start = window_start if window_start is not None else tactic["window_start"]
    new_end = window_end if window_end is not None else tactic["window_end"]
    new_rate = rate if rate is not None else tactic["rate_per_case"]
    new_fee = fee if fee is not None else tactic["fixed_fee"]
    new_units = planned_units if planned_units is not None else tactic["planned_units"]

    # rungs 70 - 81 against the patched state
    check_week_window(new_start, new_end)
    check_containment(promo, new_start, new_end)
    if tactic["tactic_type"] == "DISPLAY":
        check_display_exclusivity(promo, new_start, new_end, tactic["id"])
    if tactic["tactic_type"] == "FEATURE":
        check_feature_cooldown(promo, new_start, new_end, tactic["id"])
    money_changed = (
        (rate is not None and rate != tactic["rate_per_case"])
        or (fee is not None and fee != tactic["fixed_fee"])
    )
    # rung 75 - rate maintenance is forward only
    if money_changed:
        boundary = datetime(new_start.year, new_start.month, new_start.day,
                            tzinfo=timezone.utc)
        if boundary <= clock_dt():
            raise ApiError("ERR_RATE_CHANGE_NOT_FUTURE")
    if tactic["tactic_type"] == "TPR":
        check_tpr_capacity(promo, new_start, new_end, tactic["id"])
    check_type_money(tactic["tactic_type"], new_rate, new_fee)

    tactic["window_start"] = new_start
    tactic["window_end"] = new_end
    tactic["rate_per_case"] = new_rate
    tactic["fixed_fee"] = new_fee
    tactic["planned_units"] = new_units
    if money_changed:
        tactic["effective_from_period"] = new_start
    touch(tactic)
    touch(promo)
    return object_response(calc.tactic_out(tactic))


@bp.post(PREFIX + "/tactics/<tactic_id>/cancel")
def cancel_tactic(tactic_id):
    authenticate([KAM])
    data = body_fields(optional=["cancel_reason"])
    reason = get_string(data, "cancel_reason", required=False, min_len=1)
    tactic = get_tactic(tactic_id)
    promo = db.promotions.get(tactic["promotion_id"])
    # rung 43
    if promo is None or promo["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rung 44
    if tactic["status"] != "PLANNED":
        raise ApiError("ERR_TACTIC_STATE_INVALID")
    tactic["status"] = "CANCELLED"
    tactic["cancel_reason"] = reason
    touch(tactic)
    touch(promo)
    return object_response(calc.tactic_out(tactic))
