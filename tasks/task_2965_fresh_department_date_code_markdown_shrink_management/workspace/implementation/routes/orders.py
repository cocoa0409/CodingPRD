"""Order recommendations from shrink history, and the logical clock."""
from flask import Blueprint

import calc
from db import db, newest_first
from errors import ApiError
from middleware import (ROLE_ADMIN, ROLE_AUDITOR, ROLE_CLERK, ROLE_MANAGER,
                        ROLE_PARTNER, actor, authenticate)
from records import item_by_id, new_record, recommendation_by_id, touch
from response import ok, created, public
from routes.common import (RECOMMENDATION_METHODS, RECOMMENDATION_STATUSES,
                           listing, matches)
from util import fmt_instant
from validate import (field_date, field_enum, field_instant, field_int,
                      field_string, json_body, query_enum, query_string)

bp = Blueprint("orders", __name__)

READ_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_AUDITOR)


@bp.get("/fresh/order-recommendations/<recommendation_id>")
def get_recommendation(recommendation_id):
    authenticate(*READ_ROLES)
    return ok(public(recommendation_by_id(recommendation_id)))


@bp.get("/fresh/order-recommendations")
def list_recommendations():
    authenticate(*READ_ROLES)
    item_id = query_string("item_id")
    supersedes = query_string("supersedes_recommendation_id")
    status = query_enum("status", RECOMMENDATION_STATUSES)
    method = query_enum("method", RECOMMENDATION_METHODS)
    rows = [
        r for r in db.recommendations.values()
        if matches(r, "item_id", item_id)
        and matches(r, "supersedes_recommendation_id", supersedes)
        and matches(r, "status", status)
        and matches(r, "method", method)
    ]
    return listing(rows)


@bp.post("/fresh/order-recommendations")
def create_recommendation():
    authenticate(ROLE_MANAGER)
    body = json_body()
    item_id = field_string(body, "item_id", required=True, max_len=200)
    start_date = field_date(body, "window_start_date", required=True)
    end_date = field_date(body, "window_end_date", required=True)
    expected_version = field_int(body, "expected_item_version", required=True,
                                 minimum=0)
    method = field_enum(body, "method", RECOMMENDATION_METHODS,
                        default="CHRONOLOGICAL_ACTUAL")
    item = item_by_id(item_id)
    if item["version"] != expected_version:
        raise ApiError("ERR_STALE_ITEM_VERSION",
                       "expected_item_version does not match the item")
    if end_date < start_date or (end_date - start_date).days + 1 > 31:
        raise ApiError(
            "ERR_RECOMMENDATION_WINDOW_INVALID",
            "The history window must be ordered and at most 31 days long",
        )
    figures = calc.order_feedback(item, start_date, end_date, method)
    superseded = None
    candidates = [
        r for r in db.recommendations.values()
        if r["item_id"] == item["id"]
        and r["window_start_date"] == start_date.isoformat()
        and r["window_end_date"] == end_date.isoformat()
        and r["status"] == "ISSUED"
    ]
    if candidates:
        superseded = newest_first(candidates)[0]
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
    record = new_record(db.recommendations, {
        "item_id": item["id"],
        "supersedes_recommendation_id": superseded["id"] if superseded
        else None,
        "window_start_date": start_date.isoformat(),
        "window_end_date": end_date.isoformat(),
        "method": method,
        "received_units": figures["received_units"],
        "shrink_units": figures["shrink_units"],
        "shrink_rate_pct": figures["shrink_rate_pct"],
        "open_units": figures["open_units"],
        "recommended_order_units": figures["recommended_order_units"],
        "issued_by_user_id": None,
        "status": "DRAFT",
    })
    touch(item)
    return created(public(record))


@bp.post("/fresh/order-recommendations/<recommendation_id>/issue")
def issue(recommendation_id):
    authenticate(ROLE_MANAGER)
    json_body()
    record = recommendation_by_id(recommendation_id)
    if record["status"] != "DRAFT":
        raise ApiError("ERR_RECOMMENDATION_NOT_ISSUABLE",
                       "Only a DRAFT recommendation may be issued")
    if record["received_units"] <= 0:
        raise ApiError("ERR_INSUFFICIENT_SHRINK_HISTORY",
                       "The recommendation rests on no received units")
    record["status"] = "ISSUED"
    record["issued_by_user_id"] = actor()
    touch(record)
    return ok(public(record))


# --- the logical clock -----------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK, ROLE_AUDITOR,
                 ROLE_PARTNER)
    body = json_body()
    moment = field_instant(body, "current_utc", required=True)
    db.clock = moment
    return ok({"current_utc": fmt_instant(moment)})
