"""Job seeker endpoints, alert subscriptions and the on-demand match view."""

from flask import Blueprint

import auth
import validations as V
from db import iso, store
from models import (
    alert_subscription_view,
    application_view,
    create,
    job_posting_view,
    new_id,
    seeker_view,
    touch,
)
from response import array, ok, page_meta, paginate
from services import calc

bp = Blueprint("job_seekers", __name__)

APPLICATION_STATUSES = ("STARTED", "COMPLETED", "RESPONDED", "CLOSED")


@bp.post("/job-seekers")
def create_seeker():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin",))
    data = V.body()
    V.require_fields(data, ["email", "full_name"])
    email = V.require_string(data, "email")
    full_name = V.require_string(data, "full_name")
    location = V.optional_string(data, "location")

    for existing in store.job_seekers.values():
        if existing["email"].casefold() == email.casefold():
            from errors import ERR_INVALID_REQUEST, fail
            fail(ERR_INVALID_REQUEST, "A job seeker with that email already exists.")

    seeker = create(
        "job_seekers",
        email=email,
        full_name=full_name,
        location=location,
        status="ACTIVE",
    )
    return ok(seeker_view(seeker), 201)


@bp.get("/job-seekers/<seeker_id>")
def get_seeker(seeker_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "JobSeeker", "Employer"))
    # Reads of a seeker account are not ownership-narrowed (PRD 2.1).
    seeker = V.get("job_seeker", seeker_id)
    return ok(seeker_view(seeker))


@bp.get("/job-seekers/<seeker_id>/alert-subscriptions")
def list_seeker_subscriptions(seeker_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "JobSeeker"))
    V.reject_unknown_query({"limit", "offset"})
    seeker = V.get("job_seeker", seeker_id)
    if role == "JobSeeker":
        auth.require_ownership(actor_id, role, "alert subscriptions", "JobSeeker", seeker["id"])
    limit, offset = V.pagination()
    items = [
        sub for sub in store.job_alert_subscriptions.values()
        if sub["job_seeker_id"] == seeker["id"]
    ]
    items = V.sort_newest(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array([alert_subscription_view(row) for row in page], 200,
                 page_meta(limit, offset, total))


@bp.get("/job-seekers/<seeker_id>/matches")
def list_seeker_matches(seeker_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "JobSeeker"))
    V.reject_unknown_query({"keywords", "location", "limit", "offset"})
    seeker = V.get("job_seeker", seeker_id)
    if role == "JobSeeker":
        auth.require_ownership(actor_id, role, "matches", "JobSeeker", seeker["id"])

    keywords = V.str_filter("keywords")
    location = V.str_filter("location")
    limit, offset = V.pagination()

    scored = calc.ranked_matches(keywords, location)
    total = len(scored)
    payload = []
    for score, posting in scored[offset:offset + limit]:
        entry = job_posting_view(posting)
        entry["relevance_score"] = score
        payload.append(entry)
    return array(payload, 200, page_meta(limit, offset, total))


@bp.get("/job-seekers/<seeker_id>/applications")
def list_seeker_applications(seeker_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "JobSeeker"))
    V.reject_unknown_query({"status", "limit", "offset"})
    seeker = V.get("job_seeker", seeker_id)
    if role == "JobSeeker":
        auth.require_ownership(actor_id, role, "applications", "JobSeeker", seeker["id"])
    status = V.enum_filter("status", APPLICATION_STATUSES)
    limit, offset = V.pagination()

    items = [
        app for app in store.applications.values()
        if app["job_seeker_id"] == seeker["id"]
        and (status is None or app["status"] == status)
    ]
    items = V.sort_newest(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array([application_view(row) for row in page], 200,
                 page_meta(limit, offset, total))


@bp.post("/job-alert-subscriptions")
def create_subscription():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("JobSeeker", "PlatformAdmin"))
    data = V.body()
    V.require_fields(data, ["job_seeker_id", "keywords", "location"])
    seeker_id = V.require_string(data, "job_seeker_id")
    keywords = V.optional_string(data, "keywords")
    location = V.optional_string(data, "location")
    seeker = V.get("job_seeker", seeker_id)
    if role == "JobSeeker":
        auth.require_ownership(actor_id, role, "alert subscription", "JobSeeker", seeker["id"])
    subscription = create(
        "job_alert_subscriptions",
        job_seeker_id=seeker["id"],
        keywords=keywords if keywords is not None else "",
        location=location if location is not None else "",
        status="ACTIVE",
        last_notified_at=None,
        notified_posting_ids=[],
    )
    return ok(alert_subscription_view(subscription), 201)


@bp.post("/alerts/dispatch")
def dispatch_alerts():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin",))
    data = V.body()
    subscription_id = data.get("subscription_id")
    if subscription_id is not None:
        if not isinstance(subscription_id, str) or subscription_id == "":
            from errors import ERR_INVALID_REQUEST, fail
            fail(ERR_INVALID_REQUEST, "subscription_id must be a non-empty string.")

    if subscription_id is None:
        targets = V.sort_newest(list(store.job_alert_subscriptions.values()))
    else:
        target = store.job_alert_subscriptions.get(subscription_id)
        if target is None:
            from errors import ERR_INVALID_REQUEST, fail
            fail(ERR_INVALID_REQUEST, "subscription_id does not resolve to a subscription.")
        targets = [target]

    delivered_ids = []
    subscription_ids = []
    for subscription in targets:
        already = set(subscription["notified_posting_ids"])
        scored = calc.ranked_matches(subscription["keywords"], subscription["location"])
        fresh = [posting for _, posting in scored if posting["id"] not in already]
        if not fresh:
            continue
        for posting in fresh:
            subscription["notified_posting_ids"].append(posting["id"])
            delivered_ids.append(posting["id"])
        subscription["last_notified_at"] = iso(store.clock)
        touch(subscription)
        subscription_ids.append(subscription["id"])

    return ok({
        "delivered_count": len(delivered_ids),
        "subscription_ids": subscription_ids,
        "job_posting_ids": delivered_ids,
        "delivery_id": new_id(),
    })