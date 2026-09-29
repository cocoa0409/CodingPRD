"""Logical clock and operator sweeps."""

from db import lookup, rows, store, touch
from errors import ApiError
from middleware import route
from response import ok
from services import cascade

CLOCK_BODY = {"to_iso8601": {"type": "datetime", "required": True}}


@route("/_clock/set_current_utc", "POST", ["MethodologyAdmin"], body=CLOCK_BODY)
def set_clock(ctx):
    target = ctx.body["to_iso8601"]
    if target < store.clock:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    store.clock = target
    return ok({"current_utc": store.clock})


@route("/ops/transition-sweep", "POST", ["MethodologyAdmin"])
def transition_sweep(ctx):
    expired = []
    touched_orgs = set()
    for grant in rows("TransitionGrant"):
        if grant["status"] != "ACTIVE":
            continue
        if grant["grace_until"] is not None and grant["grace_until"] < store.now():
            grant["status"] = "EXPIRED"
            touch(grant)
            expired.append(grant["id"])
            touched_orgs.add(grant["organization_id"])
    for organization_id in touched_orgs:
        organization = lookup("Organization", organization_id)
        if organization is not None:
            cascade.refresh_active_grace(organization)
    return ok({"expired_grant_count": len(expired), "expired_grant_ids": expired})
