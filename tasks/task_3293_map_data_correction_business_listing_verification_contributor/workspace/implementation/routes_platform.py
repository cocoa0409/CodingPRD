"""Platform plumbing: logical clock and system sweeps."""
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body
from validation import require_fields

bp = Blueprint("platform", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    require_roles({"PlatformAdmin"})
    data = body()
    require_fields(data, ["to_iso8601"])
    try:
        cur = clock.set_now(data["to_iso8601"])
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", "malformed to_iso8601")
    return envelope({"current_utc": clock.iso(cur)})


@bp.post("/v1/verification-attempts/sweep-expired")
def sweep_expired_attempts():
    require_roles({"PlatformAdmin"})
    now = clock.now()
    count = 0
    for a in store.attempts.values():
        if a["status"] == "ISSUED" and clock.parse(a["expires_at"]) <= now:
            a["status"] = "EXPIRED"
            domain.touch(a)
            count += 1
    return envelope({"expired_count": count})


@bp.post("/v1/business-listings/sweep-reverify")
def sweep_reverify():
    require_roles({"PlatformAdmin"})
    from services_listings import do_require_reverify
    now = clock.now()
    count = 0
    for l in store.listings.values():
        if l["status"] == "VERIFIED" and l.get("reverify_due_at") \
                and clock.parse(l["reverify_due_at"]) <= now:
            do_require_reverify(l)
            count += 1
    return envelope({"transitioned_count": count})


@bp.post("/v1/routing-updates/sweep-activation")
def sweep_activation():
    require_roles({"PlatformAdmin"})
    from routes_routing import activate_update
    now = clock.now()
    count = 0
    for u in list(store.routing.values()):
        if u["status"] == "SCHEDULED" and clock.parse(u["effective_start"]) <= now:
            activate_update(u)
            count += 1
    return envelope({"activated_count": count})


@bp.post("/v1/routing-updates/sweep-expired")
def sweep_routing_expired():
    require_roles({"PlatformAdmin"})
    now = clock.now()
    count = 0
    for u in store.routing.values():
        if u["status"] == "ACTIVE" and clock.parse(u["effective_end"]) <= now:
            u["status"] = "EXPIRED"
            domain.touch(u)
            rg = store.regions.get(u["region_id"])
            if rg is not None:
                rg["routing_version"] += 1
                domain.touch(rg)
            count += 1
    return envelope({"expired_count": count})


@bp.post("/v1/reviews/sweep-fake-detection")
def sweep_fake_detection():
    require_roles({"PlatformAdmin"})
    from routes_reviews import compute_fake_probability, auto_flag
    count = 0
    for r in list(store.reviews.values()):
        if r["status"] != "PUBLISHED":
            continue
        prob = compute_fake_probability(r)
        r["fake_probability"] = prob
        domain.touch(r)
        if prob >= 0.80:
            auto_flag(r)
            count += 1
    return envelope({"flagged_count": count})
