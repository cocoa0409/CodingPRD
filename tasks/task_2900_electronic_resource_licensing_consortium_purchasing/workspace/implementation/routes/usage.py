"""Section 3.7 - COUNTER usage filings."""

from flask import Blueprint, request

import auth
import calc
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("usage", __name__)

READ_ROLES = (auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_VENDOR_REP)


@bp.post("/erm/subscriptions/<subscription_id>/usage-reports")
def create_usage_report(subscription_id):
    auth.require_roles(auth.ROLE_VENDOR_REP)
    subscription = auth.get_subscription(subscription_id)
    data = shape.body()
    if shape.present(data, "member_id"):
        auth.get_member(data["member_id"])
    product = store.products[subscription["product_id"]]
    auth.require_vendor_scope(product)

    member_id = shape.req_string(data, "member_id")
    period_month = shape.req_month(data, "period_month")
    full_text_requests = shape.req_int(data, "full_text_requests", minimum=0)
    searches = shape.req_int(data, "searches", minimum=0)
    denials = shape.req_int(data, "denials", minimum=0)

    # priority 19 - the month must lie inside the closed term interval
    if not (calc.month_of(subscription["term_start"]) <= period_month
            <= calc.month_of(subscription["term_end"])):
        raise ApiError("ERR_USAGE_PERIOD_OUT_OF_TERM")

    # priority 25 - one row per (subscription, member, month)
    for existing in store.usage_reports.values():
        if existing["subscription_id"] == subscription["id"] \
                and existing["member_id"] == member_id \
                and existing["period_month"] == period_month:
            raise ApiError("ERR_DUPLICATE_USAGE_REPORT")

    row = store.new_row({
        "subscription_id": subscription["id"],
        "member_id": member_id,
        "period_month": period_month,
        "full_text_requests": full_text_requests,
        "searches": searches,
        "denials": denials,
    }, versioned=False)
    store.usage_reports[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/usage-reports/<usage_report_id>")
def read_usage_report(usage_report_id):
    auth.require_roles(*READ_ROLES)
    row = auth.get_usage_report(usage_report_id)
    return envelope.object_response(store.serialize(row))


@bp.get("/erm/usage-reports")
def list_usage_reports():
    auth.require_roles(*READ_ROLES)
    rows = list(store.usage_reports.values())
    for field in ("subscription_id", "member_id", "period_month"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return envelope.paged(rows)
