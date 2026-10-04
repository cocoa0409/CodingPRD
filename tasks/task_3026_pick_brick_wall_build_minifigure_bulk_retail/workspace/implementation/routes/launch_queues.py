"""Launch queues: joining, the door check, the grant batch and the purchase."""

from flask import Blueprint

from db import EXCLUSIVE_PURCHASE_POINTS, db, launch_arrival
from errors import fail
from middleware import require, require_owner
from response import envelope, paginate
from services.core import (
    get_launch,
    get_member,
    get_queue,
    new_record,
    recompute_remaining,
    recompute_soft_hold,
    touch,
)
from services.launch import run_grant_batch, wave_units
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("launch_queues", __name__)


@bp.route("/stores/launch-queues", methods=["POST"])
def join_queue():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "member_id", "launch_id", "priority_class")

    member = get_member(payload["member_id"])
    launch = get_launch(payload["launch_id"])

    requested = int(payload.get("requested_units", 1))
    if requested < 1:
        fail("ERR_CONSTRAINT_VIOLATION", "requested_units must be at least 1.")

    # The store's own posture is consulted before the requester's ceiling, so a
    # join that trips both hears about the frozen store.
    store = db().stores.get(member["home_store_id"])
    if store is not None and store["stage"] == "FROZEN":
        fail("ERR_STORE_FROZEN", "A frozen store admits no launch queue join.")

    if member["stage"] == "SUSPENDED":
        fail("ERR_MEMBER_FROZEN", "A suspended member may not join a launch queue.")

    if launch["stage"] not in ("VIP_EARLY", "STAGED_OPEN"):
        fail("ERR_LAUNCH_NOT_OPEN",
             "The launch is still scheduled or has already closed.")

    # Two ceilings guard the per-customer limit and they are not conflated: on
    # a join the member's wave total, including the new request, may not exceed
    # the limit; on a purchase the row's own units may not.
    if wave_units(member["id"], launch["id"]) + requested > launch["per_customer_limit"]:
        fail("ERR_PURCHASE_LIMIT_EXCEEDED",
             "The request would exceed the launch's per-customer limit.")

    # The priority class is not taken on trust.
    priority_class = payload["priority_class"]
    if priority_class not in ("VIP_EARLY", "GENERAL"):
        fail("ERR_CONSTRAINT_VIOLATION",
             "priority_class must be VIP_EARLY or GENERAL.")
    if member["tier"] != "VIP":
        priority_class = "GENERAL"

    sequence = launch_arrival(launch["id"]).next()
    queue = new_record({
        "store_id": (store or {}).get("id", member["home_store_id"]),
        "member_id": member["id"],
        "launch_id": launch["id"],
        "priority_class": priority_class,
        "requested_units": requested,
        "sequence": sequence,
        "wait_mark": sequence,
        "status": "WAITING",
        "granted_units": 0,
        "id_check_state": "IDENTITY_UNVERIFIED",
        "batch_index": 0,
    })
    db().launch_queues[queue["id"]] = queue
    recompute_soft_hold(launch)
    return envelope(out(queue), status=201)


@bp.route("/stores/launch-queues", methods=["GET"])
def list_queues():
    require("StoreAssociate", "Member")
    params = list_params()
    items = [q for q in db().launch_queues.values()
             if matches(q, params, "store_id", "launch_id", "member_id", "status")]
    items.sort(key=lambda q: (q["created_at"], q["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/launch-queues/<queue_id>", methods=["GET"])
def read_queue(queue_id):
    require("StoreAssociate", "Member")
    return envelope(out(get_queue(queue_id)))


@bp.route("/stores/launch-queues/<queue_id>/verify-identity", methods=["POST"])
def verify_identity(queue_id):
    require("StoreAssociate")
    payload = body()
    queue = get_queue(queue_id)

    expected = payload.get("expected_queue_version")
    if expected is not None and int(expected) != queue["version"]:
        fail("ERR_STALE_VERSION",
             "expected_queue_version no longer matches the queue row's version.")

    result = payload.get("check_result")
    if result is None:
        fail("ERR_CONSTRAINT_VIOLATION", "check_result is required.")

    queue["id_check_state"] = ("IDENTITY_VERIFIED" if result == "PASS"
                               else "IDENTITY_ESCALATED")
    touch(queue)
    return envelope(out(queue))


@bp.route("/stores/launch-queues/grant", methods=["POST"])
def grant_batch():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "launch_id")
    launch = get_launch(payload["launch_id"])

    expected = payload.get("expected_theme_launch_version")
    if expected is None:
        fail("ERR_CONSTRAINT_VIOLATION",
             "expected_theme_launch_version is required for a grant batch.")
    if int(expected) != launch["version"]:
        fail("ERR_STALE_VERSION",
             "expected_theme_launch_version no longer matches the launch's version.")

    eligible = payload.get("eligible_queue_ids")
    restrict = set(eligible) if eligible else None

    granted = run_grant_batch(launch, restrict)
    recompute_remaining(launch)
    return envelope(out(granted), response_type="array")


@bp.route("/stores/launch-queues/<queue_id>/purchase", methods=["POST"])
def purchase(queue_id):
    payload = body()
    queue = get_queue(queue_id)
    require_owner(queue["member_id"])
    require("Member")

    expected = payload.get("expected_queue_version")
    if expected is not None and int(expected) != queue["version"]:
        fail("ERR_STALE_VERSION",
             "expected_queue_version no longer matches the queue row's version.")

    if queue["status"] != "GRANTED":
        fail("ERR_INVALID_STATE", "Only a granted queue row may be purchased.")

    launch = get_launch(queue["launch_id"])
    member = get_member(queue["member_id"])

    if member["stage"] == "SUSPENDED":
        fail("ERR_MEMBER_FROZEN", "A suspended member may not transact.")
    if queue["requested_units"] > launch["per_customer_limit"]:
        fail("ERR_PURCHASE_LIMIT_EXCEEDED",
             "The row's units exceed the launch's per-customer limit.")
    if queue["id_check_state"] != "IDENTITY_VERIFIED":
        fail("ERR_QUEUE_NOT_READY",
             "The queue row has not been identity-verified.")

    queue["status"] = "PURCHASED"
    touch(queue)
    member["points_balance"] += queue["requested_units"] * EXCLUSIVE_PURCHASE_POINTS
    touch(member)
    recompute_remaining(launch)
    return envelope(out(queue))