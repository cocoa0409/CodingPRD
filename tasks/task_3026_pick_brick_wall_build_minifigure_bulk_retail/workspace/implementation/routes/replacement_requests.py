"""Replacement requests: the trailing ceiling, the sourcing fork and the awards."""

from flask import Blueprint

from db import DEFAULT_WINDOW_DAYS, db, now
from errors import fail
from middleware import require, require_owner
from response import envelope, paginate
from services.core import (
    get_element,
    get_member,
    get_request,
    get_store,
    new_record,
    touch,
)
from services.replacement import (
    budget_exhausted,
    claim_points,
    completion_points,
    expiry_instant,
)
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("replacement_requests", __name__)


@bp.route("/stores/replacement-requests", methods=["POST"])
def file_request():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "store_id", "member_id", "element_id", "quantity_missing")

    store = get_store(payload["store_id"])
    member = get_member(payload["member_id"])
    element = get_element(payload["element_id"])

    quantity = int(payload["quantity_missing"])
    if quantity < 1:
        fail("ERR_CONSTRAINT_VIOLATION", "quantity_missing must be at least 1.")
    window_days = int(payload.get("window_days", DEFAULT_WINDOW_DAYS))
    if window_days < 1:
        fail("ERR_CONSTRAINT_VIOLATION", "window_days must be at least 1.")

    expected = payload.get("expected_member_version")
    if expected is None:
        fail("ERR_CONSTRAINT_VIOLATION",
             "expected_member_version is required when filing a replacement request.")
    if int(expected) != member["version"]:
        fail("ERR_MEMBER_STALE_VERSION",
             "expected_member_version no longer matches the member's version.")

    if store["stage"] == "FROZEN":
        fail("ERR_STORE_FROZEN", "A frozen store admits no replacement filing.")

    # This endpoint inverts two rungs: the personal ceiling is consulted before
    # the element-sourcing readiness.
    if budget_exhausted(member["id"]):
        fail("ERR_REPLACEMENT_LIMIT_REACHED",
             "The member's trailing-90-day filing ceiling is exhausted.")

    approved_at = now()
    if element["sourcing_mode"] == "SURPLUS" and member["stage"] == "ACTIVE":
        stage = "PROSPECT"
        expires = expiry_instant(approved_at, window_days)
    else:
        stage = "DENIED"
        expires = None

    record = new_record({
        "store_id": store["id"],
        "member_id": member["id"],
        "element_id": element["id"],
        "quantity_missing": quantity,
        "proof_of_purchase_supplied": bool(payload.get("proof_of_purchase_supplied", False)),
        "window_days": window_days,
        "window_expires_utc": expires,
        "earned_points": 0,
        "stage": stage,
    })
    db().replacement_requests[record["id"]] = record
    touch(member)
    return envelope(out(record), status=201)


@bp.route("/stores/replacement-requests", methods=["GET"])
def list_requests():
    require("StoreAssociate", "Member")
    params = list_params()
    items = [r for r in db().replacement_requests.values()
             if matches(r, params, "member_id", "store_id", "element_id", "stage")]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/replacement-requests/<request_id>", methods=["GET"])
def read_request(request_id):
    require("StoreAssociate", "Member")
    return envelope(out(get_request(request_id)))


@bp.route("/stores/replacement-requests/<request_id>/claim", methods=["POST"])
def claim_request(request_id):
    require_owner(get_request(request_id)["member_id"])
    require("Member")
    record = get_request(request_id)

    if record["stage"] != "PROSPECT":
        fail("ERR_INVALID_STATE", "Only a prospect may be claimed.")

    member = get_member(record["member_id"])
    if member["stage"] == "SUSPENDED":
        fail("ERR_MEMBER_FROZEN", "A suspended member may not claim a prospect.")

    # A claim landing exactly on the expiry instant is refused.
    if now() >= record["window_expires_utc"]:
        fail("ERR_WINDOW_EXPIRED",
             "The resolution window for this prospect has closed.")

    element = get_element(record["element_id"])
    record["stage"] = "CLAIMED"
    record["earned_points"] = claim_points(record, element)
    touch(record)
    member["points_balance"] += record["earned_points"]
    touch(member)
    return envelope(out(record))


@bp.route("/stores/replacement-requests/<request_id>/complete", methods=["POST"])
def complete_request(request_id):
    require("StoreAssociate")
    record = get_request(request_id)

    if record["stage"] != "PROSPECT":
        fail("ERR_INVALID_STATE",
             "Only a request still awaiting resolution may be completed.")

    member = get_member(record["member_id"])
    record["stage"] = "COMPLETED"
    record["earned_points"] = completion_points(record)
    touch(record)
    member["points_balance"] += record["earned_points"]
    touch(member)
    return envelope(out(record))