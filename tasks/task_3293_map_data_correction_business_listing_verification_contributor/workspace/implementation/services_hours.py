"""Hours observation endpoints + hours_conflict_winner calculation."""
from datetime import timedelta
from flask import Blueprint

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body
from validation import require_fields, require_enum, get_or_404, valid_time

bp = Blueprint("hours", __name__)

SOURCES = {"OWNER", "CONTRIBUTOR", "WEB_CRAWL", "IMAGERY", "THIRD_PARTY_FEED"}
SOURCE_PRIORITY = {"OWNER": 5, "THIRD_PARTY_FEED": 4, "WEB_CRAWL": 3,
                   "IMAGERY": 2, "CONTRIBUTOR": 1}

CREATE_ROLES = {"Contributor", "BusinessOwner", "PlatformAdmin", "Moderator"}
READ_ROLES = {"PlatformAdmin", "Contributor", "BusinessOwner", "Moderator", "PolicyAnalyst"}


def _recompute_corroboration(listing_id, day_mask):
    group = [h for h in store.hours.values()
             if h["listing_id"] == listing_id and h["day_mask"] == day_mask]
    for h in group:
        h["corroboration_count"] = sum(
            1 for o in group
            if o["id"] != h["id"]
            and o["open_time"] == h["open_time"]
            and o["close_time"] == h["close_time"])


@bp.post("/v1/hours-observations")
def create_observation():
    role, uid = require_roles(CREATE_ROLES)
    data = body()
    require_fields(data, ["listing_id", "source", "day_mask", "open_time", "close_time"])
    l = store.listings.get(data["listing_id"])
    if l is None:
        raise_err("ERR_NOT_FOUND", "listing not found")
    source = require_enum(data, "source", SOURCES)
    day_mask = data["day_mask"]
    if not isinstance(day_mask, str) or len(day_mask) != 7:
        raise_err("ERR_INVALID_REQUEST", "day_mask must be 7 characters")
    if not valid_time(data["open_time"]) or not valid_time(data["close_time"]):
        raise_err("ERR_INVALID_REQUEST", "open_time/close_time must be HH:MM")
    rec = {
        "id": domain.new_id(),
        "listing_id": l["id"],
        "source": source,
        "day_mask": day_mask,
        "open_time": data["open_time"],
        "close_time": data["close_time"],
        "recorded_at": clock.iso(clock.now()),
        "corroboration_count": 0,
        "accepted": False,
        "created_at": clock.iso(clock.now()),
    }
    # Internal author tracking: a CONTRIBUTOR-source observation's priority
    # promotion depends on its author's level (PRD §3.7). Hidden from views.
    if source == "CONTRIBUTOR" and role in ("Contributor", "BusinessOwner"):
        rec["_contributor_id"] = uid
    store.hours[rec["id"]] = rec
    _recompute_corroboration(l["id"], day_mask)
    return envelope(domain.hours_view(rec), status=201)


@bp.get("/v1/hours-observations/<hid>")
def get_observation(hid):
    require_roles(READ_ROLES)
    h = get_or_404(store.hours, hid)
    return envelope(domain.hours_view(h))


def resolve(listing, day_mask):
    """hours_conflict_winner: rewrite accepted flags for listing+day_mask."""
    group = [h for h in store.hours.values()
             if h["listing_id"] == listing["id"] and h["day_mask"] == day_mask]
    if not group:
        return {"accepted_observation_id": None, "accepted_count": 0}

    now = clock.now()

    def score(h):
        pri = SOURCE_PRIORITY[h["source"]]
        if h["source"] == "CONTRIBUTOR":
            # Promote to 3 when the observation's author is EXPERT/MASTER.
            cid = h.get("_contributor_id")
            if cid and cid in store.contributors:
                c = store.contributors[cid]
                domain.recompute_points(c)
                if c["level"] in ("EXPERT", "MASTER"):
                    pri = 3
        age_days = int((now - clock.parse(h["recorded_at"])).total_seconds() // 86400)
        recency = max(0, 30 - age_days)
        corro = min(h["corroboration_count"], 5) * 10
        return pri * 100 + recency + corro

    best = None
    best_key = None
    for h in group:
        s = score(h)
        # tie-break: later recorded_at wins; final: earlier created_at wins
        key = (s, clock.parse(h["recorded_at"]),
               tuple(-ord(c) for c in (h["created_at"] + h["id"])))
        # simpler: use (score, recorded_at) and break final ties by created_at asc
        key = (s, clock.parse(h["recorded_at"]).timestamp())
        if best is None or key > best_key \
                or (key == best_key and h["created_at"] < best["created_at"]):
            best = h
            best_key = key
    for h in group:
        h["accepted"] = (h["id"] == best["id"])
    return {"accepted_observation_id": best["id"], "accepted_count": 1}
