"""RoutingUpdate endpoints + routing-window conflict logic."""
from datetime import timedelta
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from validation import require_fields, require_enum, get_or_404

bp = Blueprint("routing", __name__)

KINDS = {"CLOSURE", "CONSTRUCTION", "TURN_RESTRICTION"}
READ_ROLES = {"PlatformAdmin", "RoutingEngineer", "Moderator"}
BUFFER = timedelta(hours=24)
CONFLICT_STATUSES = {"VALIDATED", "SCHEDULED", "ACTIVE"}


def activate_update(u):
    """SCHEDULED -> ACTIVE with routing_version bump and supersede cascade."""
    u["status"] = "ACTIVE"
    domain.touch(u)
    rg = store.regions.get(u["region_id"])
    if rg is not None:
        rg["routing_version"] += 1
        domain.touch(rg)
    sup_id = u.get("supersedes_id")
    if sup_id and sup_id in store.routing:
        sup = store.routing[sup_id]
        if sup["status"] in ("PROPOSED", "VALIDATED", "SCHEDULED"):
            sup["status"] = "CANCELLED"
            sup["cancel_note"] = "superseded by %s" % u["id"]
            domain.touch(sup)


@bp.post("/v1/routing-updates")
def create_update():
    require_roles({"RoutingEngineer", "PlatformAdmin"})
    data = body()
    require_fields(data, ["region_id", "segment_ref", "kind", "effective_start",
                          "effective_end", "expected_region_version"])
    region = store.regions.get(data["region_id"])
    if region is None:
        raise_err("ERR_NOT_FOUND", "region not found")
    kind = require_enum(data, "kind", KINDS)
    supersedes_id = data.get("supersedes_id")
    if supersedes_id is not None and supersedes_id not in store.routing:
        raise_err("ERR_NOT_FOUND", "supersedes_id not found")
    try:
        es = clock.parse(data["effective_start"])
        ee = clock.parse(data["effective_end"])
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", "malformed effective datetimes")
    if data["expected_region_version"] != region["version"]:
        raise_err("ERR_STALE_VERSION", "region version advanced")
    now = clock.iso(clock.now())
    rec = {
        "id": domain.new_id(),
        "region_id": region["id"],
        "segment_ref": data["segment_ref"],
        "kind": kind,
        "status": "PROPOSED",
        "effective_start": clock.iso(es),
        "effective_end": clock.iso(ee),
        "restriction_detail": data.get("restriction_detail"),
        "supersedes_id": supersedes_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.routing[rec["id"]] = rec
    domain.touch(region)
    return envelope(domain.routing_view(rec), status=201)


@bp.get("/v1/routing-updates")
def list_updates():
    require_roles(READ_ROLES)
    items = list(store.routing.values())
    for f in ("region_id", "segment_ref", "kind", "status", "supersedes_id"):
        v = request.args.get(f)
        if v is not None:
            items = [u for u in items if u.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.routing_view(u) for u in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/routing-updates/<uid>")
def get_update(uid):
    require_roles(READ_ROLES)
    u = get_or_404(store.routing, uid)
    return envelope(domain.routing_view(u))


@bp.post("/v1/routing-updates/<uid>/validate")
def validate(uid):
    require_roles({"RoutingEngineer"})
    u = get_or_404(store.routing, uid)
    if u["status"] != "PROPOSED":
        raise_err("ERR_INVALID_STATE", "only PROPOSED updates can be validated")
    region = store.regions.get(u["region_id"])
    domain.recompute_region(region)
    if region["posture"] == "FROZEN":
        raise_err("ERR_REGION_FROZEN", "region frozen")
    es = clock.parse(u["effective_start"])
    ee = clock.parse(u["effective_end"])
    if not es < ee:
        raise_err("ERR_INVALID_REQUEST", "effective_start must precede effective_end")
    if u["kind"] in ("CLOSURE", "CONSTRUCTION"):
        for o in store.routing.values():
            if o["id"] == u["id"]:
                continue
            if o["segment_ref"] != u["segment_ref"]:
                continue
            if o["status"] not in CONFLICT_STATUSES:
                continue
            os_ = clock.parse(o["effective_start"])
            oe = clock.parse(o["effective_end"])
            # gap must be >= 24h on both sides; exactly 24h allowed
            gap_before = os_ - ee   # other starts after this ends
            gap_after = es - oe     # this starts after other ends
            if gap_before >= BUFFER or gap_after >= BUFFER:
                continue
            raise_err("ERR_ROUTING_WINDOW_CONFLICT",
                      "within 24h of another active window on the same segment")
    now = clock.now()
    u["status"] = "VALIDATED"
    if es > now:
        u["status"] = "SCHEDULED"
        domain.touch(u)
        region["routing_version"] += 1
        domain.touch(region)
    else:
        # VALIDATED -> ACTIVE in same request; activate handles bump + supersede
        domain.touch(u)
        activate_update(u)
    return envelope(domain.routing_view(u))


@bp.post("/v1/routing-updates/<uid>/activate")
def activate(uid):
    require_roles({"RoutingEngineer"})
    u = get_or_404(store.routing, uid)
    if u["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "only SCHEDULED updates can be activated")
    activate_update(u)
    return envelope(domain.routing_view(u))


@bp.post("/v1/routing-updates/<uid>/cancel")
def cancel(uid):
    require_roles({"RoutingEngineer"})
    u = get_or_404(store.routing, uid)
    if u["status"] == "PROPOSED":
        u["status"] = "CANCELLED"
        domain.touch(u)
        return envelope(domain.routing_view(u))
    if u["status"] == "VALIDATED":
        bump = True
    elif u["status"] == "SCHEDULED":
        if clock.now() >= clock.parse(u["effective_start"]):
            raise_err("ERR_INVALID_STATE", "cannot cancel a started SCHEDULED update")
        bump = True
    else:
        raise_err("ERR_INVALID_STATE", "update cannot be cancelled")
    u["status"] = "CANCELLED"
    domain.touch(u)
    rg = store.regions.get(u["region_id"])
    if rg is not None:
        rg["routing_version"] += 1
        domain.touch(rg)
    return envelope(domain.routing_view(u))
