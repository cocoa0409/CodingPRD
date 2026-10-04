"""Resource resolution (layer 4) and small shared lookup helpers."""
from flask import request

from db import db
from errors import fail


# ---- layer-4 existence helpers (path ids first, then body ids) ------------
def publisher(c, pid):
    row = db.publishers.get(pid)
    if row is None:
        fail("ERR_PUBLISHER_NOT_FOUND", "No publisher exists with id %s." % pid)
    c.extra["publisher"] = row
    return row


def title(c, tid, publisher_id=None):
    row = db.titles.get(tid)
    if row is None:
        fail("ERR_TITLE_NOT_FOUND", "No title exists with id %s." % tid)
    if publisher_id is not None and row["publisher_id"] != publisher_id:
        fail("ERR_TITLE_NOT_FOUND",
             "Title %s is not owned by publisher %s." % (tid, publisher_id))
    c.extra["title"] = row
    return row


def region(c, code):
    row = db.regions.get(code)
    if row is None:
        fail("ERR_REGION_NOT_FOUND", "No region exists with code %s." % code)
    c.extra["region"] = row
    return row


def tier(c, code):
    row = db.tiers.get(code)
    if row is None:
        fail("ERR_TIER_NOT_FOUND", "No subscription tier exists with code %s." % code)
    c.extra["tier"] = row
    return row


def deal(c, did, title_id=None):
    row = db.deals.get(did)
    if row is None:
        fail("ERR_DEAL_NOT_FOUND", "No licensing deal exists with id %s." % did)
    if title_id is not None and row["title_id"] != title_id:
        fail("ERR_DEAL_NOT_FOUND",
             "Deal %s does not belong to title %s." % (did, title_id))
    c.extra["deal"] = row
    return row


def entry(c, eid, title_id=None):
    row = db.entries.get(eid)
    if row is None:
        fail("ERR_ENTRY_NOT_FOUND", "No catalog entry exists with id %s." % eid)
    if title_id is not None and row["title_id"] != title_id:
        fail("ERR_ENTRY_NOT_FOUND",
             "Entry %s does not belong to title %s." % (eid, title_id))
    c.extra["entry"] = row
    return row


def subscriber(c, sid):
    row = db.subscribers.get(sid)
    if row is None:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "No subscriber exists with id %s." % sid)
    c.extra["subscriber"] = row
    return row


def subscription(c, sid, subscriber_id=None):
    row = db.subscriptions.get(sid)
    if row is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND", "No subscription exists with id %s." % sid)
    if subscriber_id is not None and row["subscriber_id"] != subscriber_id:
        fail("ERR_SUBSCRIPTION_NOT_FOUND",
             "Subscription %s does not belong to subscriber %s." % (sid, subscriber_id))
    c.extra["subscription"] = row
    return row


def entitlement(c, eid):
    row = db.entitlements.get(eid)
    if row is None:
        fail("ERR_ENTRY_NOT_FOUND", "No entitlement exists with id %s." % eid)
    c.extra["entitlement"] = row
    return row


def purchase(c, pid):
    row = db.purchases.get(pid)
    if row is None:
        fail("ERR_ENTRY_NOT_FOUND", "No purchase exists with id %s." % pid)
    c.extra["purchase"] = row
    return row


def maintenance(c, mid):
    row = db.maintenances.get(mid)
    if row is None:
        fail("ERR_REGION_NOT_FOUND",
             "No catalog maintenance exists with id %s." % mid)
    c.extra["maintenance"] = row
    return row


def projection(c, pid):
    row = db.projections.get(pid)
    if row is None:
        fail("ERR_PROJECTION_NOT_FOUND",
             "No availability projection exists with id %s." % pid)
    c.extra["projection"] = row
    return row


def event(c, eid):
    row = db.events.get(eid)
    if row is None:
        fail("ERR_ENTRY_NOT_FOUND", "No engagement event exists with id %s." % eid)
    c.extra["event"] = row
    return row


# ---- ownership (step 2 remainder, evaluated inside the role layer) --------
def own_subscriber(c, row):
    """PRD 2.1: a Subscriber may only act on its own rows."""
    if c.actor_role == "Subscriber" and row.get("subscriber_id") != c.actor_id:
        fail("ERR_FORBIDDEN_ROLE",
             "Subscriber %s may not act on another subscriber's resource." % c.actor_id)
    return row


# ---- misc -----------------------------------------------------------------
def body_subscriber(c):
    return c.get("subscriber_id")


def query_paging():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = 10 if limit is None else int(limit)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
    try:
        offset = 0 if offset is None else int(offset)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must lie between 1 and 100 inclusive.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
    return limit, offset


TIER_ORDER = {"ESSENTIAL": 0, "PREMIUM": 1, "ULTIMATE": 2}


def page(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
