"""Feedback items: submission, triage scoring and the roadmap decision."""
from flask import Blueprint

from constants import (
    FEEDBACK_CATEGORIES,
    FEEDBACK_STATES,
    ROLE_DEVELOPER,
    ROLE_DEVREL_MANAGER,
    ROLE_PLATFORM_ADMIN,
)
from db import new_id, store
from errors import ApiError
from middleware import (
    acting_user,
    endpoint,
    lookup,
    require_not_revoked,
    require_owner,
)
from response import (
    array_response,
    enum_filter,
    object_response,
    pagination,
    string_filter,
)
from serializers import feedback_item_out
from services import feedback
from services.common import top_active_tier
from validation import body

bp = Blueprint("feedback", __name__)


def _item(item_id):
    return lookup(store.feedback_items, item_id, "ERR_FEEDBACK_ITEM_NOT_FOUND")


@bp.post("/feedback-items")
@endpoint([ROLE_DEVELOPER])
def create_feedback_item():
    payload = body()
    developer_id = payload.string("developer_id", min_len=1)
    product_id = payload.string("api_product_id", min_len=1)
    category = payload.string("category", choices=FEEDBACK_CATEGORIES)
    text = payload.string("body", min_len=10, max_len=2000)

    developer = lookup(store.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")
    product = lookup(store.api_products, product_id, "ERR_API_PRODUCT_NOT_FOUND")

    require_owner(developer["id"])
    require_not_revoked()

    item = {
        "id": new_id(),
        "developer_id": developer["id"],
        "api_product_id": product["id"],
        "category": category,
        "body": text,
        "state": "SUBMITTED",
        "author_top_tier": None,
        "raw_impact": None,
        "priority_score": None,
        "triaged_by_user_id": None,
        "decision_note": None,
        "triaged_at": None,
    }
    store.stamp_new(item)
    store.feedback_items[item["id"]] = item
    return object_response(feedback_item_out(item), 201)


@bp.get("/feedback-items/<item_id>")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def read_feedback_item(item_id):
    item = _item(item_id)
    require_owner(item["developer_id"])
    return object_response(feedback_item_out(item))


@bp.get("/feedback-items")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def list_feedback_items():
    limit, offset = pagination()
    developer_id = string_filter("developer_id")
    product_id = string_filter("api_product_id")
    state = enum_filter("state", FEEDBACK_STATES)

    records = store.ordered(store.feedback_items)
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if product_id is not None:
        records = [r for r in records if r["api_product_id"] == product_id]
    if state is not None:
        records = [r for r in records if r["state"] == state]

    total = len(records)
    page = records[offset : offset + limit]
    return array_response([feedback_item_out(r) for r in page], total, limit, offset)


@bp.post("/feedback-items/<item_id>/triage")
@endpoint([ROLE_DEVREL_MANAGER])
def triage_feedback_item(item_id):
    payload = body()
    note = payload.string("decision_note", required=False)

    item = _item(item_id)

    if item["state"] != "SUBMITTED":
        raise ApiError(
            "ERR_FEEDBACK_STATE_INVALID",
            "Only a SUBMITTED item may be triaged; state is %s." % item["state"],
        )

    developer = store.developers[item["developer_id"]]
    product = store.api_products[item["api_product_id"]]

    item["state"] = "TRIAGED"
    item["triaged_by_user_id"] = acting_user()
    item["triaged_at"] = store.now()
    if note is not None:
        item["decision_note"] = note
    item["author_top_tier"] = top_active_tier(developer["id"])
    item["raw_impact"] = feedback.raw_impact_for(item, developer)

    # ledger-wide recomputation across every counted item of the product
    feedback.rescore_product(product, exclude_item_id=item["id"])
    store.touch(item)
    return object_response(feedback_item_out(item))


@bp.post("/feedback-items/<item_id>/roadmap-decision")
@endpoint([ROLE_DEVREL_MANAGER])
def decide_feedback_item(item_id):
    payload = body()
    decision = payload.string("decision", choices=["ACCEPT", "DECLINE"])
    note = payload.string("decision_note", required=False)

    item = _item(item_id)

    if item["state"] != "TRIAGED":
        raise ApiError(
            "ERR_FEEDBACK_STATE_INVALID",
            "Only a TRIAGED item may receive a roadmap decision; state is %s."
            % item["state"],
        )

    product = store.api_products[item["api_product_id"]]

    if note is not None:
        item["decision_note"] = note

    if decision == "ACCEPT":
        item["state"] = "ROADMAP_ACCEPTED"
        store.touch(item)
    else:
        item["state"] = "DECLINED"
        item["priority_score"] = None
        feedback.rescore_product(product, exclude_item_id=item["id"])
        store.touch(item)

    return object_response(feedback_item_out(item))
