"""Disclosure schedule (PRD §3.5), surveillance posture derivation, issuer
delinquency flag, rating review_pending, and obligation creation."""
import timeutil
from constants import DISCLOSURE_DUE_DAYS
from store import db, new_entity, touch

OPEN_OBLIGATION_STATES = ("PENDING", "OVERDUE", "DELINQUENT", "DEFAULTED")
REVIEW_OPEN_STATES = ("PENDING", "IN_REVIEW", "ESCALATED")


def first_period_fiscal_year_end(issuer, published_at):
    """First occurrence of the issuer's MM-DD (at 00:00:00Z) STRICTLY AFTER
    published_at; rolls forward one calendar year otherwise (PRD §3.5)."""
    candidate = timeutil.mm_dd_in_year(issuer["fiscal_year_end"], published_at.year)
    if candidate <= published_at:
        candidate = timeutil.plus_one_year(candidate)
    return candidate


def create_obligation(rating, period_index, fiscal_year_end):
    """Append a PENDING DisclosureObligation; due_at = fye + 210 days."""
    ent = new_entity()
    ent.update(
        rating_id=rating["id"],
        period_index=period_index,
        fiscal_year_end=fiscal_year_end,
        due_at=timeutil.add_days(fiscal_year_end, DISCLOSURE_DUE_DAYS),
        submitted_at=None,
        status="PENDING",
    )
    db.obligations[ent["id"]] = ent
    return ent


def create_first_obligation(rating, issuer):
    """Period 1 at publication."""
    fye = first_period_fiscal_year_end(issuer, rating["published_at"])
    return create_obligation(rating, 1, fye)


def create_next_obligation(rating, previous):
    """Period n+1: fiscal_year_end advances by exactly one calendar year."""
    fye = timeutil.plus_one_year(previous["fiscal_year_end"])
    return create_obligation(rating, previous["period_index"] + 1, fye)


def obligations_of(rating_id):
    items = [o for o in db.obligations.values() if o["rating_id"] == rating_id]
    items.sort(key=lambda o: (o["period_index"], o["_seq"]))
    return items


def derive_posture(rating_id):
    """Posture from the rating's obligations in open states (PRD §3.5):
    DELINQUENT if any DELINQUENT, else GRACE if any OVERDUE, else CURRENT.
    DEFAULTED is not part of the derivation (the rating is withdrawn at the
    DEFAULTED hop, freezing posture)."""
    states = [
        o["status"]
        for o in db.obligations.values()
        if o["rating_id"] == rating_id and o["status"] in ("PENDING", "OVERDUE", "DELINQUENT")
    ]
    if "DELINQUENT" in states:
        return "DELINQUENT"
    if "OVERDUE" in states:
        return "GRACE"
    return "CURRENT"


def recompute_posture(rating):
    """Posture evolves only while the rating is PUBLISHED; otherwise frozen."""
    if rating["status"] == "PUBLISHED":
        rating["surveillance_posture"] = derive_posture(rating["id"])


def recompute_delinquent_flag(issuer_id):
    """True while any obligation of any of the issuer's ratings is DEFAULTED;
    clears when all such obligations have been cured to SUBMITTED_LATE."""
    rating_ids = [r["id"] for r in db.ratings.values() if r["issuer_id"] == issuer_id]
    flag = any(
        o["rating_id"] in rating_ids and o["status"] == "DEFAULTED"
        for o in db.obligations.values()
    )
    issuer = db.issuers.get(issuer_id)
    if issuer is not None and issuer["delinquent_flag"] != flag:
        issuer["delinquent_flag"] = flag
        touch(issuer)


def recompute_review_pending(rating):
    """True while any CriteriaReviewItem for the rating is PENDING,
    IN_REVIEW, or ESCALATED."""
    pending = any(
        item["rating_id"] == rating["id"] and item["status"] in REVIEW_OPEN_STATES
        for item in db.review_items.values()
    )
    rating["review_pending"] = pending


def last_obligation(rating_id):
    items = obligations_of(rating_id)
    return items[-1] if items else None
