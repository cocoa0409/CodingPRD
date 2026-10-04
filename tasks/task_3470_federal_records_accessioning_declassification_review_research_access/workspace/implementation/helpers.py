"""Domain helpers shared by route modules: entity loading (rung 3/4), the
lazy card-expiry transition (PRD §2.4/§3.7), mutation stamping (PRD §2.5),
the §2.8 posture recompute + posture-flip cascade, the §3.7 late-return
suspension cascade, and the demand-counter touch with priority recompute.
"""
import calcs
from errors import err
from store import DB, parse_dt, ts3


# --- rung 3/4 existence -------------------------------------------------------
def get_or_404(table, error_id, entity_id):
    e = getattr(DB, table).get(entity_id)
    if e is None:
        raise err(error_id, "%s not found: %s" % (table, entity_id))
    return e


def get_agency(rid):
    return get_or_404("agencies", "ERR_AGENCY_NOT_FOUND", rid)


def get_schedule(rid):
    return get_or_404("schedules", "ERR_SCHEDULE_NOT_FOUND", rid)


def get_transfer(rid):
    return get_or_404("transfers", "ERR_TRANSFER_NOT_FOUND", rid)


def get_collection(rid):
    return get_or_404("collections", "ERR_COLLECTION_NOT_FOUND", rid)


def get_review(rid):
    return get_or_404("reviews", "ERR_REVIEW_NOT_FOUND", rid)


def get_referral(rid):
    return get_or_404("referrals", "ERR_REFERRAL_NOT_FOUND", rid)


def get_pull(rid):
    return get_or_404("pulls", "ERR_PULL_REQUEST_NOT_FOUND", rid)


def get_repro(rid):
    return get_or_404("repros", "ERR_REPRODUCTION_NOT_FOUND", rid)


def get_foia(rid):
    return get_or_404("foias", "ERR_FOIA_NOT_FOUND", rid)


def get_restriction(rid):
    return get_or_404("restrictions", "ERR_RESTRICTION_NOT_FOUND", rid)


# --- mutation stamping (PRD §2.5) ---------------------------------------------
def bump(entity):
    entity["version"] += 1
    entity["updated_at"] = ts3(DB.now())


# --- lazy card expiry (PRD §2.4 / §3.7) ---------------------------------------
def lazy_expire(r):
    """On any load: an ACTIVE registration whose card_expires_at has been
    reached (inclusive boundary) is persisted EXPIRED before anything else
    that depends on status is evaluated."""
    if r["status"] == "ACTIVE" and r.get("card_expires_at"):
        if DB.now() >= parse_dt(r["card_expires_at"]):
            r["status"] = "EXPIRED"
            bump(r)


def load_researcher(rid):
    r = DB.researchers.get(rid)
    if r is None:
        raise err("ERR_RESEARCHER_NOT_FOUND", "researcher not found: %s" % rid)
    lazy_expire(r)
    return r


def require_active_researcher(r):
    """Rung 9 (after lazy expiry has run on load)."""
    if r["status"] != "ACTIVE":
        raise err("ERR_RESEARCHER_NOT_ACTIVE", "researcher registration is not ACTIVE")


# --- §2.8 restriction posture + posture-flip cascade --------------------------
def live_restrictions(collection_id):
    return [r for r in DB.restrictions.values() if r["collection_id"] == collection_id]


def recompute_posture(collection):
    """Recompute restriction_posture; on a flip INTO PUBLIC, close every FOIA
    request of this collection still in RECEIVED or IN_REVIEW."""
    old = collection["restriction_posture"]
    new = calcs.restriction_posture(collection, live_restrictions(collection["id"]))
    collection["restriction_posture"] = new
    if new == "PUBLIC" and old != "PUBLIC":
        for f in DB.foias.values():
            if f["collection_id"] == collection["id"] and f["status"] in (
                "RECEIVED",
                "IN_REVIEW",
            ):
                f["status"] = "CLOSED"
                f["close_reason"] = "RECORDS_MADE_PUBLIC"
                bump(f)
    return new


# --- demand-counter touch: priority recompute while QUEUED --------------------
def touch_collection(collection):
    """Called after pull_count_total / repro_pages_fulfilled /
    foia_release_count mutations: recompute digitization_priority on the spot
    while the collection is QUEUED, then advance the collection's version."""
    if collection["digitization_status"] == "QUEUED":
        collection["digitization_priority"] = calcs.digitization_priority(
            collection, DB.now()
        )
    bump(collection)


# --- §3.7 late-return suspension cascade --------------------------------------
def suspend_researcher(researcher):
    """researcher must already have gone through load_researcher (lazy expiry
    applied). Suspension is terminal; the cascade cancels the researcher's
    pending work in the same transaction."""
    if researcher["status"] in ("ACTIVE", "EXPIRED"):
        researcher["status"] = "SUSPENDED"
        researcher["suspension_reason"] = "LATE_RETURN"
        bump(researcher)
    rid = researcher["id"]
    for p in DB.pulls.values():
        if p["researcher_id"] == rid and p["status"] == "REQUESTED":
            p["status"] = "CANCELLED"
            bump(p)
    for rp in DB.repros.values():
        if rp["researcher_id"] == rid and rp["status"] == "QUOTED":
            rp["status"] = "CANCELLED"
            bump(rp)
