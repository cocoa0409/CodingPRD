from decimal import Decimal

from flask import Blueprint, request

import auth
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("questionnaires", __name__)


@bp.post("/soc/customer-questionnaires")
def create_questionnaire():
    auth.authenticate({"AccountExecutive"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    distribution = v.fk(body, "report_distribution_id", "report_distributions")
    v.req_id(body, "engagement_id")
    v.req_id(body, "report_distribution_id")
    customer_name = v.req_str(body, "customer_name", 1, 200)
    criteria_items = v.req_int(body, "criteria_item_count", minv=0)
    post_period_items = v.req_int(body, "post_period_item_count", minv=0)
    cuec_items = v.req_int(body, "cuec_item_count", minv=0)

    row = store.new_row(
        "customer_questionnaires",
        {
            "engagement_id": engagement["id"],
            "report_distribution_id": distribution["id"],
            "customer_name": customer_name,
            "criteria_item_count": criteria_items,
            "post_period_item_count": post_period_items,
            "cuec_item_count": cuec_items,
            "item_count": criteria_items + post_period_items + cuec_items,
            "as_of_date": None,
            "deflected_by_report_count": 0,
            "deflected_by_bridge_count": 0,
            "deflected_by_cuec_count": 0,
            "manual_response_count": 0,
            "deflection_ratio": 0.0,
            "bridge_letter_id_used": None,
            "status": "RECEIVED",
        },
    )
    return ok(store.public(row), 201)


@bp.get("/soc/customer-questionnaires/<customer_questionnaire_id>")
def read_questionnaire(customer_questionnaire_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("customer_questionnaires", customer_questionnaire_id)
    return ok(store.public(row))


@bp.get("/soc/customer-questionnaires")
def list_questionnaires():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("customer_questionnaires")
    for key in ("engagement_id", "report_distribution_id", "bridge_letter_id_used", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/customer-questionnaires/<customer_questionnaire_id>/deflect")
def deflect(customer_questionnaire_id):
    auth.authenticate({"AccountExecutive"})
    row = store.get_or_404("customer_questionnaires", customer_questionnaire_id)
    body = auth.body()
    as_of = v.req_dt(body, "as_of_date")

    engagement = DB["engagements"][row["engagement_id"]]
    distribution = DB["report_distributions"][row["report_distribution_id"]]

    if row["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    if distribution["status"] != "DELIVERED":
        raise ApiError("ERR_REPORT_NOT_DELIVERED")

    services.refresh_coverage(engagement)

    by_report = min(row["criteria_item_count"], engagement["covered_criteria_count_attestation"])

    candidates = []
    for letter in DB["bridge_letters"].values():
        if letter["engagement_id"] != engagement["id"] or letter["status"] != "ISSUED":
            continue
        start = store.parse_iso(letter["coverage_start"])
        end = store.parse_iso(letter["as_of_date"])
        if start <= as_of <= end:
            candidates.append(letter)
    chosen = None
    if candidates:
        candidates.sort(key=lambda b: (b["created_at"], b["_seq"]))
        candidates.sort(key=lambda b: store.parse_iso(b["as_of_date"]), reverse=True)
        chosen = candidates[0]
    by_bridge = row["post_period_item_count"] if chosen is not None else 0

    articulated = sum(
        1
        for c in DB["cuecs"].values()
        if c["engagement_id"] == engagement["id"] and c["articulation_status"] == "ARTICULATED"
    )
    by_cuec = min(row["cuec_item_count"], articulated)

    item_count = row["item_count"]
    manual = item_count - by_report - by_bridge - by_cuec
    if item_count == 0:
        ratio = 0.0
    else:
        ratio = store.num4(
            Decimal(item_count - manual) / Decimal(item_count)
        )

    row["as_of_date"] = store.fmt_iso(as_of)
    row["deflected_by_report_count"] = by_report
    row["deflected_by_bridge_count"] = by_bridge
    row["deflected_by_cuec_count"] = by_cuec
    row["manual_response_count"] = manual
    row["deflection_ratio"] = ratio
    row["bridge_letter_id_used"] = chosen["id"] if chosen is not None else None

    if manual == 0 and item_count > 0:
        row["status"] = "DEFLECTED"
    elif manual == item_count:
        row["status"] = "MANUAL_RESPONSE"
    else:
        row["status"] = "PARTIALLY_DEFLECTED"
    store.touch(row)
    return ok(store.public(row))
