"""Clock-driven evaluations, lookups and the separation cascade.

Sources: PRD 2.4, 2.5, 2.12, 3.1, 3.2, 3.6, 3.8; SCAFFOLD sections 1.2 / 1.2.1.
"""

from datetime import timedelta

from db import db, set_fields
from timeutil import parse_dt
from services import documents as docsvc
from services import scoring


# --- lookups ---------------------------------------------------------------
def client(identifier):
    return db.clients.get(identifier)


def seat(identifier):
    return db.seats.get(identifier)


def analyst(identifier):
    return db.analysts.get(identifier)


def inquiry(identifier):
    return db.inquiries.get(identifier)


def document(identifier):
    return db.documents.get(identifier)


def vendor(identifier):
    return db.vendors.get(identifier)


def inclusion(identifier):
    return db.inclusions.get(identifier)


def briefing(identifier):
    return db.briefings.get(identifier)


def relationship(identifier):
    return db.sales_relationships.get(identifier)


def event(identifier):
    return db.events.get(identifier)


def sponsorship(identifier):
    return db.sponsorships.get(identifier)


def account_of_seat(seat_obj):
    return db.clients.get(seat_obj.get("client_account_id"))


def account_of_inquiry(inquiry_obj):
    seat_obj = db.seats.get(inquiry_obj.get("seat_id"))
    if seat_obj is None:
        return None
    return db.clients.get(seat_obj.get("client_account_id"))


# --- clock-driven evaluations ---------------------------------------------
def evaluate_account(account):
    """ACTIVE -> RENEWAL_REVIEW once the clock reaches end - 90 days (inclusive)."""
    if account.get("contract_status") != "ACTIVE":
        return False
    end = parse_dt(account.get("contract_end_utc"))
    if end is None:
        return False
    if db.now() >= end - timedelta(days=90):
        account["contract_status"] = "RENEWAL_REVIEW"
        account["renewal_posture"] = scoring.posture_for(
            scoring.seat_weighted_score(account)
        )
        db.touch(account)
        return True
    return False


def evaluate_inquiry(inquiry_obj):
    """SCHEDULED -> IN_PREP once the clock reaches start - 24 hours (inclusive)."""
    if inquiry_obj.get("status") != "SCHEDULED":
        return False
    start = parse_dt(inquiry_obj.get("scheduled_start_utc"))
    if start is None:
        return False
    if db.now() >= start - timedelta(hours=24):
        inquiry_obj["status"] = "IN_PREP"
        db.touch(inquiry_obj)
        return True
    return False


def evaluate_document(document_obj):
    """EMBARGOED -> RELEASED once the clock reaches embargo_until (inclusive)."""
    if document_obj.get("embargo_status") != "EMBARGOED":
        return False
    until = parse_dt(document_obj.get("embargo_until"))
    if until is None:
        return False
    if db.now() >= until:
        document_obj["embargo_status"] = "RELEASED"
        db.touch(document_obj)
        return True
    return False


def evaluate_document_inclusions(document_obj):
    for inc in docsvc.inclusions_of(document_obj["id"]):
        docsvc.evaluate_inclusion_lapse(inc)


def evaluate_event(event_obj):
    """AGENDA_LOCKED -> COMPLETED once the clock is strictly past end_utc."""
    if event_obj.get("status") != "AGENDA_LOCKED":
        return False
    end = parse_dt(event_obj.get("end_utc"))
    if end is None:
        return False
    if db.now() > end:
        event_obj["status"] = "COMPLETED"
        db.touch(event_obj)
        return True
    return False


def refresh_account_state(account):
    """Evaluate clock transitions then re-derive the ledger and the scores."""
    if account is None:
        return None
    for inquiry_obj in scoring.inquiries_of(account["id"]):
        evaluate_inquiry(inquiry_obj)
    evaluate_account(account)
    scoring.refresh_account(account)
    return account


# --- derived counters ------------------------------------------------------
def open_inquiry_count(analyst_id):
    return sum(
        1
        for q in db.inquiries.values()
        if q.get("analyst_id") == analyst_id
        and q.get("status") in ("ROUTED", "SCHEDULED", "IN_PREP")
    )


def open_briefing_count(analyst_id):
    return sum(
        1
        for b in db.briefings.values()
        if b.get("analyst_id") == analyst_id
        and b.get("status") in ("REQUESTED", "SCREENED", "SCHEDULED")
    )


def refresh_analyst(analyst_obj):
    changed = set_fields(
        analyst_obj,
        open_inquiry_count=open_inquiry_count(analyst_obj["id"]),
    )
    if changed:
        db.touch(analyst_obj)
    return analyst_obj


# --- vendor eligibility ----------------------------------------------------
def vendor_has_included_placement(vendor_id):
    for inc in db.inclusions.values():
        if inc.get("vendor_id") != vendor_id:
            continue
        if inc.get("inclusion_status") != "INCLUDED":
            continue
        parent = db.documents.get(inc.get("document_id"))
        if parent is not None and parent.get("editorial_status") == "PUBLISHED":
            return True
    return False


def recompute_vendor_eligibility(vendor_obj):
    eligible = vendor_has_included_placement(vendor_obj["id"]) and (
        vendor_obj.get("active_sales_relationship_count", 0) == 0
    )
    return set_fields(vendor_obj, briefing_eligible=eligible)


def refresh_vendor(vendor_obj):
    if recompute_vendor_eligibility(vendor_obj):
        db.touch(vendor_obj)
    return vendor_obj


# --- separation register ---------------------------------------------------
def integrity_flag_for(count):
    if count == 0:
        return "CLEAR"
    if count >= 3:
        return "CONFLICT_BLOCKED"
    return "CONFLICT_REVIEW"


def apply_sales_relationship_cascade(relationship_obj):
    """The four-step cascade of PRD 3.8 (SCAFFOLD 1.2 SalesRelationship)."""
    analyst_obj = db.analysts[relationship_obj["analyst_id"]]
    vendor_obj = db.vendors[relationship_obj["vendor_id"]]

    # (1) the analyst's conflict register
    conflicted = list(analyst_obj.get("conflicted_vendor_ids") or [])
    conflicted.append(vendor_obj["id"])
    analyst_obj["conflicted_vendor_ids"] = conflicted
    analyst_obj["integrity_flag"] = integrity_flag_for(len(conflicted))
    db.touch(analyst_obj)

    # (2) open briefings for this (analyst, vendor) pair are revoked
    for brief in db.briefings.values():
        if brief.get("analyst_id") != analyst_obj["id"]:
            continue
        if brief.get("vendor_id") != vendor_obj["id"]:
            continue
        if brief.get("status") in ("REQUESTED", "SCREENED", "SCHEDULED"):
            brief["status"] = "REVOKED_BY_SEPARATION"
            brief["separation_check_result"] = "FAIL_SALES_RELATIONSHIP"
            db.touch(brief)

    # (3) conflicted inclusions revert to PROPOSED
    for inc in db.inclusions.values():
        if inc.get("vendor_id") != vendor_obj["id"]:
            continue
        parent = db.documents.get(inc.get("document_id"))
        if parent is None or parent.get("lead_analyst_id") != analyst_obj["id"]:
            continue
        if inc.get("inclusion_status") in ("PROPOSED", "UNDER_EVALUATION"):
            inc["lead_analyst_conflicted"] = True
            inc["inclusion_status"] = "PROPOSED"
            db.touch(inc)

    # (4) the vendor registry
    vendor_obj["active_sales_relationship_count"] = (
        vendor_obj.get("active_sales_relationship_count", 0) + 1
    )
    recompute_vendor_eligibility(vendor_obj)
    db.touch(vendor_obj)
