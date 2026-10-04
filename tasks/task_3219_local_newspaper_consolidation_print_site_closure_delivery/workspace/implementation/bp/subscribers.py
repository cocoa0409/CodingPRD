"""Subscriber contracts and retention actions."""
from datetime import timedelta

from flask import Blueprint, request

from core import DB, fail, _parse_iso
from helpers import ok_list, ok_object, create, sort_by_created
from guards import body, identity, path_one, require_row
from models import touch, bump
import calcs as C
import recompute as R

bp = Blueprint("subscribers", __name__)

READ_SUB = ["CustomerService", "Subscriber", "Auditor", "PlatformAdmin"]
READ_SUB_LIST = ["CustomerService", "Auditor", "PlatformAdmin"]


def _subscriber_ownership(sub, role, uid):
    if role == "Subscriber" and sub.get("id") != uid:
        fail("ERR_UNAUTHORIZED")


@bp.post("/regional-news-ops/delivery-stops/<stop_id>/subscribers")
def create_subscriber(stop_id):
    data = body()
    identity(["CustomerService"])
    stop = path_one("delivery_stops", stop_id)
    if stop.get("status") == "terminated":
        fail("ERR_INVALID_STATE")
    sub = create("subscribers", data,
                 ["subscriber_ref", "remaining_print_issues", "paid_through_utc",
                  "print_issue_value_cents"],
                 system={"delivery_stop_id": stop["id"]})
    if not str(sub.get("subscriber_ref") or ""):
        DB.col("subscribers").pop(sub["id"], None)
        fail("ERR_INVALID_REQUEST", "subscriber_ref must not be empty.")
    if int(sub.get("remaining_print_issues") or 0) < 0:
        DB.col("subscribers").pop(sub["id"], None)
        fail("ERR_INVALID_REQUEST", "remaining_print_issues must be non-negative.")
    hub = C.hub_for_stop(stop)
    if hub is not None:
        for other in DB.all("subscribers"):
            if other.get("subscriber_ref") == sub["subscriber_ref"] and \
                    other.get("id") != sub["id"] and \
                    C.hub_for_subscriber(other) is not None and \
                    C.hub_for_subscriber(other)["id"] == hub["id"]:
                DB.col("subscribers").pop(sub["id"], None)
                fail("ERR_DUPLICATE_HUB_CODE")
    sub["status"] = "active"
    sub["offer_status"] = "none"
    sub["delivery_status"] = "none"
    market = C.market_of_subscriber(sub)
    sub["migration_credit_cents"] = C.migration_credit(sub, market)
    sub["churn_retention_credit_cents"] = C.churn_retention_credit(sub)
    sub["offer_recommendation"] = C.offer_recommendation(sub)
    return ok_object(sub, 201)


@bp.get("/regional-news-ops/delivery-stops/<stop_id>/subscribers")
def list_stop_subscribers(stop_id):
    identity(READ_SUB_LIST)
    stop = path_one("delivery_stops", stop_id)
    return ok_list(sort_by_created(C.subscribers_of_stop(stop["id"])), None, None)


@bp.get("/regional-news-ops/subscribers/<subscriber_id>")
def get_subscriber(subscriber_id):
    role, uid = identity(READ_SUB)
    sub = path_one("subscribers", subscriber_id)
    _subscriber_ownership(sub, role, uid)
    return ok_object(sub)


@bp.get("/regional-news-ops/subscribers")
def list_subscribers():
    identity(READ_SUB_LIST)
    rows = DB.all("subscribers")
    stop_id = request.args.get("delivery_stop_id")
    status = request.args.get("status")
    if stop_id:
        rows = [s for s in rows if s.get("delivery_stop_id") == stop_id]
    if status:
        rows = [s for s in rows if s.get("status") == status]
    return ok_list(sort_by_created(rows), request.args.get("limit"),
                   request.args.get("offset"))


@bp.post("/regional-news-ops/subscribers/<subscriber_id>/migrate-digital")
def migrate_digital(subscriber_id):
    data = body()
    role, uid = identity(["CustomerService", "Subscriber"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    sub = path_one("subscribers", subscriber_id)
    _subscriber_ownership(sub, role, uid)
    if sub.get("status") == "churned":
        fail("ERR_SUBSCRIBER_TERMINAL")
    if sub.get("status") != "active":
        fail("ERR_INVALID_STATE")
    sub["status"] = "migrated"
    sub["offer_status"] = "accepted"
    sub["migration_credit_cents"] = C.migration_credit(sub, C.market_of_subscriber(sub))
    touch(sub)
    return ok_object(sub)


@bp.post("/regional-news-ops/subscribers/<subscriber_id>/cancel")
def cancel_subscriber(subscriber_id):
    data = body()
    role, uid = identity(["CustomerService", "Subscriber"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    sub = path_one("subscribers", subscriber_id)
    _subscriber_ownership(sub, role, uid)
    if sub.get("status") == "churned":
        fail("ERR_SUBSCRIBER_TERMINAL")
    if sub.get("status") not in ("active", "churned_pending_retention", "migrated"):
        fail("ERR_INVALID_STATE")
    sub["status"] = "churned"
    sub["offer_status"] = "declined"
    sub["churn_retention_credit_cents"] = C.churn_retention_credit(sub)
    touch(sub)
    for action in DB.all("retention_actions"):
        if action.get("subscriber_contract_id") == sub["id"] and \
                action.get("status") == "open":
            action["status"] = "cancelled"
            touch(action)
    return ok_object(sub)


@bp.post("/regional-news-ops/subscribers/<subscriber_id>/refund")
def refund_subscriber(subscriber_id):
    data = body()
    identity(["CustomerService"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    sub = path_one("subscribers", subscriber_id)
    if sub.get("status") == "churned":
        fail("ERR_SUBSCRIBER_TERMINAL")
    if sub.get("status") != "active":
        fail("ERR_INVALID_STATE")
    paid_through = _parse_iso(sub.get("paid_through_utc")) if sub.get("paid_through_utc") \
        else None
    if paid_through is not None and DB.clock.now > paid_through:
        fail("ERR_REFUND_WINDOW_CLOSED")
    sub["status"] = "churned"
    sub["churn_retention_credit_cents"] = C.churn_retention_credit(sub)
    touch(sub)
    for action in DB.all("retention_actions"):
        if action.get("subscriber_contract_id") == sub["id"] and \
                action.get("status") == "open":
            action["status"] = "cancelled"
            touch(action)
    return ok_object(sub)


@bp.post("/regional-news-ops/subscribers/<subscriber_id>/accept-retention-offer")
def accept_retention_offer(subscriber_id):
    data = body()
    identity(["CustomerService"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    sub = path_one("subscribers", subscriber_id)
    if sub.get("status") != "churned_pending_retention":
        fail("ERR_INVALID_STATE")
    if sub.get("delivery_status") == "terminated":
        fail("ERR_INVALID_STATE")
    actions = [a for a in DB.all("retention_actions")
               if a.get("subscriber_contract_id") == sub["id"] and a.get("status") == "open"]
    if not actions:
        fail("ERR_INVALID_STATE")
    action = sorted(actions, key=lambda a: str(a.get("created_at")))[-1]
    expires = _parse_iso(action.get("cooling_off_expires_utc")) \
        if action.get("cooling_off_expires_utc") else None
    if expires is not None and not DB.clock.now < expires:
        fail("ERR_COOLOFF_EXPIRED")
    sub["status"] = "active"
    sub["offer_status"] = "accepted"
    touch(sub)
    action["status"] = "accepted"
    touch(action)
    return ok_object(sub)


# --------------------------------------------------------------------------
# RetentionAction
# --------------------------------------------------------------------------
@bp.get("/regional-news-ops/subscribers/<subscriber_id>/retention-actions")
def list_retention_actions(subscriber_id):
    identity(READ_SUB_LIST)
    sub = path_one("subscribers", subscriber_id)
    rows = [a for a in DB.all("retention_actions")
            if a.get("subscriber_contract_id") == sub["id"]]
    return ok_list(sort_by_created(rows), None, None)


@bp.post("/regional-news-ops/subscribers/<subscriber_id>/retention-actions")
def create_retention_action(subscriber_id):
    data = body()
    identity(["CustomerService"])
    sub = path_one("subscribers", subscriber_id)
    action = create("retention_actions", data,
                    ["retention_offer_code", "retention_credit_cents",
                     "eligibility_policy_id"], system={"subscriber_contract_id": sub["id"]})
    if int(action.get("retention_credit_cents") or 0) < 0:
        DB.col("retention_actions").pop(action["id"], None)
        fail("ERR_INVALID_REQUEST", "retention_credit_cents must be non-negative.")
    action["cooling_off_expires_utc"] = (DB.clock.now + timedelta(days=14)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")
    action["status"] = "open"
    touch(action)
    return ok_object(action, 201)


@bp.get("/regional-news-ops/retention-actions/<action_id>")
def get_retention_action(action_id):
    identity(READ_SUB_LIST)
    return ok_object(path_one("retention_actions", action_id))


@bp.post("/regional-news-ops/retention-actions/<action_id>/accept")
def accept_retention_action(action_id):
    data = body()
    identity(["CustomerService"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    action = path_one("retention_actions", action_id)
    if action.get("status") != "open":
        fail("ERR_RETENTION_ALREADY_SETTLED")
    expires = _parse_iso(action.get("cooling_off_expires_utc")) \
        if action.get("cooling_off_expires_utc") else None
    if expires is not None and not DB.clock.now < expires:
        fail("ERR_COOLOFF_EXPIRED")
    action["status"] = "accepted"
    touch(action)
    sub = DB.get("subscribers", action.get("subscriber_contract_id"))
    if sub is not None:
        if sub.get("status") == "churned_pending_retention":
            sub["status"] = "active"
            sub["offer_status"] = "accepted"
            touch(sub)
    return ok_object(action)