"""Shared lookups and list plumbing for the route modules."""

from db import db, serialize_list
from errors import (
    ANALYST_NOT_FOUND,
    BRIEFING_NOT_FOUND,
    CLIENT_ACCOUNT_NOT_FOUND,
    CONFERENCE_EVENT_NOT_FOUND,
    DOCUMENT_NOT_FOUND,
    INQUIRY_NOT_FOUND,
    SALES_RELATIONSHIP_NOT_FOUND,
    SEAT_NOT_FOUND,
    SPONSORSHIP_NOT_FOUND,
    VENDOR_INCLUSION_NOT_FOUND,
    VENDOR_NOT_FOUND,
    not_found,
)
from middleware import pagination


def require_client(identifier):
    obj = db.clients.get(identifier)
    if obj is None:
        raise not_found(CLIENT_ACCOUNT_NOT_FOUND, "No ClientAccount exists for id %s." % identifier)
    return obj


def require_seat(identifier):
    obj = db.seats.get(identifier)
    if obj is None:
        raise not_found(SEAT_NOT_FOUND, "No Seat exists for id %s." % identifier)
    return obj


def require_analyst(identifier):
    obj = db.analysts.get(identifier)
    if obj is None:
        raise not_found(ANALYST_NOT_FOUND, "No Analyst exists for id %s." % identifier)
    return obj


def require_inquiry(identifier):
    obj = db.inquiries.get(identifier)
    if obj is None:
        raise not_found(INQUIRY_NOT_FOUND, "No InquiryRequest exists for id %s." % identifier)
    return obj


def require_document(identifier):
    obj = db.documents.get(identifier)
    if obj is None:
        raise not_found(DOCUMENT_NOT_FOUND, "No ResearchDocument exists for id %s." % identifier)
    return obj


def require_vendor(identifier):
    obj = db.vendors.get(identifier)
    if obj is None:
        raise not_found(VENDOR_NOT_FOUND, "No Vendor exists for id %s." % identifier)
    return obj


def require_inclusion(identifier):
    obj = db.inclusions.get(identifier)
    if obj is None:
        raise not_found(
            VENDOR_INCLUSION_NOT_FOUND,
            "No VendorInclusion exists for id %s." % identifier,
        )
    return obj


def require_briefing(identifier):
    obj = db.briefings.get(identifier)
    if obj is None:
        raise not_found(BRIEFING_NOT_FOUND, "No VendorBriefing exists for id %s." % identifier)
    return obj


def require_relationship(identifier):
    obj = db.sales_relationships.get(identifier)
    if obj is None:
        raise not_found(
            SALES_RELATIONSHIP_NOT_FOUND,
            "No SalesRelationship exists for id %s." % identifier,
        )
    return obj


def require_event(identifier):
    obj = db.events.get(identifier)
    if obj is None:
        raise not_found(
            CONFERENCE_EVENT_NOT_FOUND,
            "No ConferenceEvent exists for id %s." % identifier,
        )
    return obj


def require_sponsorship(identifier):
    obj = db.sponsorships.get(identifier)
    if obj is None:
        raise not_found(
            SPONSORSHIP_NOT_FOUND, "No Sponsorship exists for id %s." % identifier
        )
    return obj


def page_of(items):
    """Sort by created_at ascending, then apply limit/offset (PRD 2.3)."""
    limit, offset = pagination()
    ordered = sorted(items, key=lambda obj: obj.get("created_at") or "")
    total = len(ordered)
    return serialize_list(ordered[offset:offset + limit]), limit, offset, total
