"""Listings and the marketing campaign (PRD 3.6).

Publishing a listing is where the two sides of the program meet, because going
live floods several records at once.  The gates, in the order PRD 2.11 fixes:

* priority 15 -- the listing must be ``DRAFT`` and the program's occupancy axis
  must permit the step (``ERR_LISTING_STATE_CONFLICT``);
* priority 25 -- the go-live must not overlap another listing for the same
  departing property that is currently ``LIVE`` (``ERR_LISTING_SLOT_OVERLAP``);
* priority 31 -- the departing property's ``repair_status`` must be ``COMPLETE``
  (``ERR_REPAIR_NOT_COMPLETE``);
* priority 37 -- the program's ``occupancy_status`` must have advanced to
  ``OCCUPYING_NEW`` first (``ERR_LISTING_BEFORE_OCCUPANCY``).

Only one listing may be marketed at a time, and the rule is stated as an
interval, not a flag: a listing occupies a half-open interval from the moment it
goes live.  A new listing may perfectly well be drafted while an older one is
still ``LIVE``; what is forbidden is going live on the second one before the
first has closed.

Going live also performs a sweep: every coordination task belonging to the
program that is still ``OPEN`` and whose ``due_date`` has already passed the
logical clock is escalated to ``IN_PROGRESS`` in the same operation.
"""

from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LISTING_BEFORE_OCCUPANCY,
    ERR_LISTING_OFFER_REQUIRED,
    ERR_LISTING_SLOT_OVERLAP,
    ERR_LISTING_STATE_CONFLICT,
    ERR_PROPERTY_KIND_MISMATCH,
    ERR_REPAIR_NOT_COMPLETE,
    ApiError,
)
from services import current_time, create, touch
from services import coordination as coordination_service
from services import settlement as settlement_service
from services.lookup import get_bridge_program, get_listing, get_property
from store import db
from timeutil import format_iso, parse_iso
from validation import body_of, get_bool, get_int, get_str

OPEN = "OPEN"
LIVE = "LIVE"
DRAFT = "DRAFT"
PAUSED = "PAUSED"
CLOSED = "CLOSED"

LIVE_INTERVAL_START = "listed_at"


def create_listing(payload):
    data = body_of(payload)
    departing_property_id = get_str(data, "departing_property_id", required=True)
    program_id = get_str(data, "bridge_program_id", required=True)
    list_price_cents = get_int(data, "list_price_cents", required=True, minimum=0)

    property_record = get_property(departing_property_id)
    program = get_bridge_program(program_id)

    if property_record.get("kind") != "DEPARTING":
        raise ApiError(ERR_PROPERTY_KIND_MISMATCH, "A listing markets a DEPARTING property.")

    record = {
        "departing_property_id": property_record["id"],
        "bridge_program_id": program["id"],
        "list_price_cents": list_price_cents,
        "listed_at": None,
        "status": DRAFT,
        "marketing_status": "NOT_STARTED",
        "offer_count": 0,
    }
    create("listings", record)
    return record


def go_live(listing_id, actor):
    listing = get_listing(listing_id)
    property_record = get_property(listing["departing_property_id"])
    program = get_bridge_program(listing["bridge_program_id"])

    if int(listing.get("list_price_cents") or 0) <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "The listing's ask price must be greater than zero.")

    # priority 15 -- the listing itself must be DRAFT.  The program's occupancy
    # axis is *not* folded in here: PRD 3.6 declares the go-live gate on a second
    # listing as an explicit overlap refusal (priority 25, ERR_LISTING_SLOT_OVERLAP),
    # and the occupancy precondition of a first go-live has its own code
    # (priority 37, ERR_LISTING_BEFORE_OCCUPANCY) further down.
    if listing.get("status") != DRAFT:
        raise ApiError(ERR_LISTING_STATE_CONFLICT, "Only a DRAFT listing may go live.")
    occupancy = program.get("occupancy_status")

    # priority 25 -- the interval rule
    _assert_no_live_overlap(property_record)

    # priority 31
    if property_record.get("repair_status") != "COMPLETE":
        raise ApiError(ERR_REPAIR_NOT_COMPLETE, "The departing property's repairs are not complete.")

    # priority 37
    if occupancy == "VACANT":
        raise ApiError(
            ERR_LISTING_BEFORE_OCCUPANCY,
            "The household has not been recorded as occupying the new home.",
        )

    listing["status"] = LIVE
    listing["marketing_status"] = "ACTIVE"
    listing["listed_at"] = format_iso(current_time())
    touch(listing)

    property_record["listing_status"] = "LISTED"
    touch(property_record)

    program["occupancy_status"] = "DEPARTING_LISTED"
    touch(program)

    coordination_service.escalate_overdue_tasks(program["id"])
    return listing


def _assert_no_live_overlap(property_record):
    """A go-live may not overlap another listing that is currently LIVE.

    Listings scale by ``listed_at``, and a single LIVE listing occupies the open
    tail of the timeline, so any other LIVE listing for the same property is an
    overlap.  Drafting is explicitly allowed alongside a live listing; only the
    second go-live is refused.
    """
    for other in db.all("listings"):
        if other.get("departing_property_id") != property_record["id"]:
            continue
        if other.get("status") == LIVE:
            raise ApiError(
                ERR_LISTING_SLOT_OVERLAP,
                "Another listing for this property is already live.",
            )


def under_contract(listing_id, actor):
    listing = get_listing(listing_id)
    property_record = get_property(listing["departing_property_id"])
    program = get_bridge_program(listing["bridge_program_id"])

    if listing.get("status") != LIVE:
        raise ApiError(ERR_INVALID_STATE, "Only a LIVE listing may move under contract.")
    if property_record.get("listing_status") != "LISTED":
        raise ApiError(ERR_INVALID_STATE, "The property is not currently LISTED.")

    listing["offer_count"] = int(listing.get("offer_count") or 0) + 1
    touch(listing)

    property_record["listing_status"] = "UNDER_CONTRACT"
    touch(property_record)

    # The guarantee is pushed out 30 days and moved to EXTENDED.
    for offer in db.all("backup_offers"):
        if offer.get("departing_property_id") == property_record["id"] and offer.get("status") == "ISSUED":
            expires_at = parse_iso(offer.get("expires_at"))
            from constants import OFFER_EXTENSION_DAYS
            from timeutil import add_days

            if expires_at is not None:
                offer["expires_at"] = format_iso(add_days(expires_at, OFFER_EXTENSION_DAYS))
            offer["status"] = "EXTENDED"
            touch(offer)

    touch(program)
    return listing


def close_sale(listing_id, actor):
    listing = get_listing(listing_id)
    property_record = get_property(listing["departing_property_id"])
    program = get_bridge_program(listing["bridge_program_id"])

    if listing.get("status") not in (LIVE, PAUSED):
        raise ApiError(ERR_LISTING_STATE_CONFLICT, "This listing cannot be closed from its current state.")

    if int(listing.get("offer_count") or 0) < 1:
        raise ApiError(ERR_LISTING_OFFER_REQUIRED, "The listing has no recorded offer.")
    if property_record.get("listing_status") != "UNDER_CONTRACT":
        raise ApiError(ERR_LISTING_OFFER_REQUIRED, "The property is not under contract.")

    listing["status"] = CLOSED
    listing["marketing_status"] = "STOPPED"
    touch(listing)

    property_record["listing_status"] = "RESOLD"
    touch(property_record)

    program["occupancy_status"] = "DEPARTING_SOLD"
    touch(program)

    # The guarantee is no longer needed once the home sells to a third party.
    for offer in db.all("backup_offers"):
        if offer.get("departing_property_id") == property_record["id"] and offer.get("status") in ("ISSUED", "EXTENDED"):
            offer["status"] = "VOIDED"
            touch(offer)

    settlement_service.apply_entry(program["id"], "CLOSING_SALE", _closing_sale_amount(program))
    return listing


def _closing_sale_amount(program):
    """The closing proceeds booked against the program.

    The entry may never exceed the loan's combined outstanding balance
    (``ERR_DISBURSEMENT_EXCEEDS_BALANCE``), so the recorded amount is the
    program's carrying-cost burden bounded by that balance; with neither
    present it is zero and no entry is booked.
    """
    from services import loan as loan_service

    loan = db.first_by_field("interim_loans", "bridge_program_id", program["id"])
    if loan is None:
        return 0
    return loan_service.combined_balance(loan)


def relist(listing_id, payload, actor):
    data = body_of(payload)
    relist_after_pause = get_bool(data, "relist_after_pause", required=False, default=None)

    # priority 4 -- this endpoint may only relist, never take a live listing back.
    if relist_after_pause is not True:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "A relist request must supply relist_after_pause as true.",
        )

    listing = get_listing(listing_id)
    if listing.get("status") != PAUSED:
        raise ApiError(ERR_LISTING_STATE_CONFLICT, "Only a PAUSED listing may be relisted.")

    property_record = get_property(listing["departing_property_id"])
    _assert_no_live_overlap(property_record)

    listing["status"] = LIVE
    listing["marketing_status"] = "ACTIVE"
    touch(listing)

    property_record["listing_status"] = "LISTED"
    touch(property_record)
    return listing