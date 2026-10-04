"""ReviewTicket endpoints: create/claim, list, claim, resolve, escalate."""
from datetime import timedelta
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from services_listings import publish_edit
from validation import require_fields, require_enum, get_or_404

bp = Blueprint("tickets", __name__)

QUEUES = {"EDIT_REVIEW", "REVIEW_MODERATION"}
PRIORITIES = {"LOW", "NORMAL", "HIGH", "CRITICAL"}
RESOLUTIONS = {"APPROVE", "REJECT", "NEEDS_INFO", "REMOVE", "RESTORE", "DISMISS"}
PRIORITY_LADDER = ["LOW", "NORMAL", "HIGH", "CRITICAL"]


def _make_ticket(queue, map_edit_id, review_flag_id, priority, claimed_by, status):
    now = clock.now()
    sla_hours = 24 if priority in ("HIGH", "CRITICAL") else 72
    rec = {
        "id": domain.new_id(),
        "map_edit_id": map_edit_id,
        "review_flag_id": review_flag_id,
        "queue": queue,
        "status": status,
        "claimed_by": claimed_by,
        "priority": priority,
        "resolution": None,
        "sla_due_at": clock.iso(now + timedelta(hours=sla_hours)),
        "created_at": clock.iso(now),
        "updated_at": clock.iso(now),
        "version": 1,
    }
    store.tickets[rec["id"]] = rec
    return rec


@bp.post("/v1/review-tickets")
def create_ticket():
    role, uid = require_roles({"Moderator"})
    data = body()
    require_fields(data, ["queue"])
    queue = require_enum(data, "queue", QUEUES)
    priority = data.get("priority", "NORMAL")
    if priority not in PRIORITIES:
        raise_err("ERR_INVALID_REQUEST", "invalid priority")

    if queue == "EDIT_REVIEW":
        require_fields(data, ["map_edit_id"])
        e = store.edits.get(data["map_edit_id"])
        if e is None:
            raise_err("ERR_NOT_FOUND", "map edit not found")
        if e.get("review_ticket_id"):
            raise_err("ERR_EDIT_ALREADY_ASSIGNED", "edit already assigned a ticket")
        if e["status"] not in ("QUEUED", "IN_REVIEW"):
            raise_err("ERR_INVALID_STATE", "edit not available for review")
        ticket = _make_ticket(queue, e["id"], None, priority, uid, "CLAIMED")
        e["status"] = "IN_REVIEW"
        e["review_ticket_id"] = ticket["id"]
        domain.touch(e)
        return envelope(domain.ticket_view(ticket), status=201)

    # REVIEW_MODERATION
    require_fields(data, ["review_flag_id"])
    f = store.flags.get(data["review_flag_id"])
    if f is None:
        raise_err("ERR_NOT_FOUND", "review flag not found")
    if f["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "flag not OPEN")
    r = store.reviews.get(f["review_id"])
    if r is None or r["status"] != "FLAGGED":
        raise_err("ERR_INVALID_STATE", "review not FLAGGED")
    ticket = _make_ticket(queue, None, f["id"], priority, uid, "CLAIMED")
    r["status"] = "UNDER_MODERATION"
    domain.touch(r)
    l = store.listings.get(r["listing_id"])
    if l is not None:
        domain.recompute_listing(l)
    return envelope(domain.ticket_view(ticket), status=201)


@bp.get("/v1/review-tickets")
def list_tickets():
    require_roles({"PlatformAdmin", "Moderator"})
    items = list(store.tickets.values())
    for f in ("queue", "status", "claimed_by", "priority", "map_edit_id", "review_flag_id"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.ticket_view(t) for t in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/review-tickets/<tid>")
def get_ticket(tid):
    require_roles({"PlatformAdmin", "Moderator"})
    t = get_or_404(store.tickets, tid)
    return envelope(domain.ticket_view(t))


@bp.post("/v1/review-tickets/<tid>/claim")
def claim_ticket(tid):
    role, uid = require_roles({"Moderator"})
    t = get_or_404(store.tickets, tid)
    if t["status"] not in ("OPEN", "ESCALATED"):
        raise_err("ERR_INVALID_STATE", "ticket not claimable")
    t["status"] = "CLAIMED"
    t["claimed_by"] = uid
    domain.touch(t)
    return envelope(domain.ticket_view(t))


@bp.post("/v1/review-tickets/<tid>/resolve")
def resolve_ticket(tid):
    role, uid = require_roles({"Moderator"})
    t = get_or_404(store.tickets, tid)
    data = body()
    require_fields(data, ["resolution"])
    resolution = require_enum(data, "resolution", RESOLUTIONS)
    if t["status"] != "CLAIMED":
        raise_err("ERR_INVALID_STATE", "ticket not CLAIMED")
    if t["claimed_by"] != uid:
        raise_err("ERR_NOT_TICKET_OWNER", "only the claiming moderator may resolve")

    if t["queue"] == "EDIT_REVIEW":
        if resolution not in ("APPROVE", "REJECT", "NEEDS_INFO"):
            raise_err("ERR_INVALID_REQUEST", "invalid resolution for EDIT_REVIEW")
        e = store.edits.get(t["map_edit_id"])
        if resolution == "APPROVE":
            publish_edit(e)
        elif resolution == "REJECT":
            reason = data.get("rejection_reason", "POLICY")
            if reason not in ("POLICY", "INSUFFICIENT_EVIDENCE"):
                raise_err("ERR_INVALID_REQUEST", "invalid rejection_reason")
            e["status"] = "REJECTED"
            e["rejection_reason"] = reason
            domain.touch(e)
            c = store.contributors.get(e["contributor_id"])
            if c is not None:
                domain.recompute_contributor(c, demote=True)
        else:  # NEEDS_INFO
            e["status"] = "NEEDS_MORE_INFO"
            domain.touch(e)
    else:  # REVIEW_MODERATION
        if resolution not in ("REMOVE", "RESTORE", "DISMISS"):
            raise_err("ERR_INVALID_REQUEST", "invalid resolution for REVIEW_MODERATION")
        f = store.flags.get(t["review_flag_id"])
        r = store.reviews.get(f["review_id"]) if f else None
        if resolution == "REMOVE":
            f["status"] = "UPHELD"
            r["status"] = "REMOVED"
            domain.touch(r)
            gid = r.get("_review_grant_id")
            if gid and gid in store.grants:
                store.grants[gid]["status"] = "REVOKED"
            c = store.contributors.get(r["contributor_id"])
            if c is not None:
                domain.recompute_contributor(c, demote=True)
        elif resolution == "RESTORE":
            f["status"] = "DISMISSED"
            r["status"] = "PUBLISHED"
            domain.touch(r)
        else:  # DISMISS
            f["status"] = "DISMISSED"
            r["status"] = "PUBLISHED"
            domain.touch(r)
        if r is not None:
            from routes_reviews import recompute_flag_count
            recompute_flag_count(r)
            domain.touch(r)
            l = store.listings.get(r["listing_id"])
            if l is not None:
                domain.recompute_listing(l)

    t["status"] = "RESOLVED"
    t["resolution"] = resolution
    domain.touch(t)
    return envelope(domain.ticket_view(t))


@bp.post("/v1/review-tickets/<tid>/escalate")
def escalate_ticket(tid):
    role, uid = require_roles({"Moderator"})
    t = get_or_404(store.tickets, tid)
    if t["status"] != "CLAIMED":
        raise_err("ERR_INVALID_STATE", "only CLAIMED tickets can be escalated")
    idx = PRIORITY_LADDER.index(t["priority"])
    if idx < len(PRIORITY_LADDER) - 1:
        t["priority"] = PRIORITY_LADDER[idx + 1]
    t["status"] = "ESCALATED"
    domain.touch(t)
    return envelope(domain.ticket_view(t))
