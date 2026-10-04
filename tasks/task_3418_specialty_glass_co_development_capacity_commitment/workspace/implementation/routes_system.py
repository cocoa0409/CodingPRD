"""System endpoints: the logical clock setter and the operations checkpoint."""
from flask import Blueprint

import cascades
import clock
import store
from response import success_object
from validation import (
    ROLE_PLATFORM_ADMIN,
    ROLE_CAPACITY_PLANNER,
    authenticate,
    get_body,
    req_field,
    as_datetime,
)

bp = Blueprint("system", __name__)


@bp.route("/glass/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate({ROLE_PLATFORM_ADMIN})
    body = get_body()
    raw = req_field(body, "to_iso8601")
    dt = as_datetime(raw, "to_iso8601")
    clock.set_current(dt)
    return success_object({"current_utc": raw})


@bp.route("/glass/ops/checkpoint", methods=["POST"])
def ops_checkpoint():
    authenticate({ROLE_PLATFORM_ADMIN, ROLE_CAPACITY_PLANNER})
    get_body()
    now = clock.now()
    completed = 0
    cancelled = 0
    expired = 0
    exhausted = 0
    breached = 0
    # Sweep 1: complete every RUNNING campaign whose end_date has been reached.
    for camp in list(store.campaigns.values()):
        if camp["status"] == "RUNNING" and now >= camp["end_date"]:
            camp["status"] = "COMPLETED"
            cascades.finalize_campaign(camp)
            store.touch(camp)
            completed += 1
    # Sweep 2: cancel every still-SCHEDULED campaign whose end_date has been
    # reached, with the full cancellation cascade.
    for camp in list(store.campaigns.values()):
        if camp["status"] == "SCHEDULED" and now >= camp["end_date"]:
            cascades.cancel_campaigns_batched([camp])
            cancelled += 1
    # Sweep 3: expire every ACTIVE license whose expiry_date has passed.
    for lic in list(store.licenses.values()):
        if lic["license_status"] == "ACTIVE" and now > lic["expiry_date"]:
            lic["license_status"] = "EXPIRED"
            store.touch(lic)
            expired += 1
    # Sweep 4: commitments whose fulfilled units have reached committed units.
    for c in list(store.commitments.values()):
        if c["status"] in ("SECURED", "BREACH_WATCH") and (
            c["fulfilled_units"] >= c["committed_units"]
        ):
            c["status"] = "EXHAUSTED"
            store.touch(c)
            exhausted += 1
    # Sweep 5: BREACH_WATCH commitments past their breach deadline.
    for c in list(store.commitments.values()):
        if (
            c["status"] == "BREACH_WATCH"
            and c["breach_deadline"] is not None
            and now > c["breach_deadline"]
        ):
            c["status"] = "BREACHED"
            store.touch(c)
            breached += 1
    return success_object(
        {
            "campaigns_completed": completed,
            "campaigns_cancelled": cancelled,
            "licenses_expired": expired,
            "commitments_exhausted": exhausted,
            "commitments_breached": breached,
        }
    )
