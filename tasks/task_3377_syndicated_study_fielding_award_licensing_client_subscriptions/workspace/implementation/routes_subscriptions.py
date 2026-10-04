"""Subscription endpoints: TRIAL create, list/get with ClientUser scoping,
and the lifecycle state machine (closed-interval window semantics)."""
from flask import Blueprint, g

from db import clock, store
from envelope import filter_params, ok_object, paginated
from errors import fail
from middleware import require
from records import new_record, ser_subscription, touch
from validation import Body

bp = Blueprint("subscriptions", __name__, url_prefix="/research")


@bp.post("/subscriptions")
@require("ClientUser", "StudyAdmin")
def create_subscription():
    b = Body()
    client_id = b.str_("client_id")
    study_id = b.str_("study_id")
    tier = b.enum_("tier", ("DIAGNOSTIC", "BENCHMARK"))
    starts_at = b.dt_("starts_at")
    ends_at = b.dt_("ends_at")
    # ownership (priority 2)
    if g.role == "ClientUser" and client_id is not None and client_id != g.user_id:
        fail("ERR_FORBIDDEN", "ClientUser may create subscriptions only for its own client_id")
    # existence (priority 3)
    if client_id is not None and client_id not in store.clients:
        fail("ERR_NOT_FOUND", "client_id does not reference an existing client")
    if study_id is not None and study_id not in store.studies:
        fail("ERR_NOT_FOUND", "study_id does not reference an existing study")
    # syntactic (priority 11): window must be strictly increasing
    b.finalize()
    if ends_at <= starts_at:
        fail("ERR_INVALID_REQUEST", "ends_at must be strictly later than starts_at")
    rec = new_record()
    rec.update({
        "client_id": client_id,
        "study_id": study_id,
        "tier": tier,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "TRIAL",
    })
    store.subscriptions[rec["id"]] = rec
    return ok_object(ser_subscription(rec), 201)


@bp.get("/subscriptions")
@require("StudyAdmin", "ClientUser")
def list_subscriptions():
    items = list(store.subscriptions.values())
    if g.role == "ClientUser":
        items = [s for s in items if s["client_id"] == g.user_id]
    items = filter_params(items, ("client_id", "study_id", "status"))
    return paginated(items, ser_subscription)


@bp.get("/subscriptions/<sid>")
@require("StudyAdmin", "ClientUser")
def get_subscription(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        fail("ERR_NOT_FOUND", "Subscription not found")
    if g.role == "ClientUser" and sub["client_id"] != g.user_id:
        fail("ERR_FORBIDDEN", "ClientUser may read only its own subscriptions")
    return ok_object(ser_subscription(sub))


@bp.post("/subscriptions/<sid>/state")
@require("ClientUser", "StudyAdmin")
def subscription_state(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        fail("ERR_NOT_FOUND", "Subscription not found")
    if g.role == "ClientUser" and sub["client_id"] != g.user_id:
        fail("ERR_FORBIDDEN", "ClientUser may administer only its own subscriptions")
    b = Body()
    to = b.str_("to_status")
    b.finalize()
    cur = sub["status"]
    now = clock.now()
    if to == "ACTIVE":
        if cur != "TRIAL":
            fail("ERR_INVALID_STATE", "Cannot transition subscription from %s to ACTIVE" % cur)
        # temporal gate: clock inside the closed window
        if not (sub["starts_at"] <= now <= sub["ends_at"]):
            fail("ERR_SUBSCRIPTION_WINDOW_INVALID", "Logical clock is outside the subscription window")
        # closed-interval overlap: adjacency counts as conflict
        for o in store.subscriptions.values():
            if (
                o["id"] != sub["id"]
                and o["client_id"] == sub["client_id"]
                and o["study_id"] == sub["study_id"]
                and o["status"] == "ACTIVE"
                and sub["starts_at"] <= o["ends_at"]
                and o["starts_at"] <= sub["ends_at"]
            ):
                fail("ERR_SUBSCRIPTION_OVERLAP", "Another ACTIVE subscription overlaps this window")
        sub["status"] = "ACTIVE"
    elif to == "CANCELLED":
        if cur not in ("TRIAL", "ACTIVE"):
            fail("ERR_INVALID_STATE", "Cannot transition subscription from %s to CANCELLED" % cur)
        sub["status"] = "CANCELLED"
    elif to == "EXPIRED":
        if cur != "ACTIVE":
            fail("ERR_INVALID_STATE", "Cannot transition subscription from %s to EXPIRED" % cur)
        if now <= sub["ends_at"]:
            fail("ERR_SUBSCRIPTION_WINDOW_INVALID", "Expiry requires the logical clock to be after ends_at")
        sub["status"] = "EXPIRED"
    else:
        fail("ERR_INVALID_STATE", "Subscription transition to %r is not defined" % to)
    touch(sub)
    return ok_object(ser_subscription(sub), 200)
