"""The guaranteed backup offer (PRD 3.6, PRD 3.9).

A coordinator drafts an offer against the ``departing_property_id`` and the
``bridge_program_id``, with an ``offer_price_cents``, a ``window_start`` marking
when the exercise window opens and a ``window_days`` of between 1 and 180.  The
offer opens in ``DRAFT`` and, at creation, the system computes its
``price_basis_cents`` from the price floor.

An offer written below the floor -- whether at creation or at the moment it is
issued -- is refused with ``ERR_REGULATORY_PRICE_FLOOR``, and an offer price may
not exceed the property's appraised value at all.  Every offer whose status is
``DRAFT``, ``ISSUED``, ``EXPIRED``, ``EXTENDED`` or ``EXERCISED`` is bounded by
the floor.

Issuing requires the offer to still be ``DRAFT``, the logical clock to have
reached ``window_start``, and the linked program's ``occupancy_status`` to be
``DEPARTING_LISTED`` -- the guarantee is issued only once the old home is
genuinely on the market.  Issuing sets ``expires_at`` to ``window_start`` plus
``window_days`` and moves the offer to ``ISSUED``.

Exercising is guarded by segregation of duties (PRD 2.1): the ``Coordinator``
that issued the offer must not be the one that exercises it.
"""

from constants import (
    OFFER_EXTENSION_DAYS,
    WINDOW_DAYS_MAX,
    WINDOW_DAYS_MIN,
)
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_BACKUP_OFFER_EXPIRED,
    ERR_EXERCISE_WINDOW_NOT_OPEN,
    ERR_INVALID_STATE,
    ERR_PROPERTY_KIND_MISMATCH,
    ERR_REGULATORY_PRICE_FLOOR,
    ERR_STALE_VERSION,
    ApiError,
)
from middleware import check_segregation_of_duties
from services import current_time, create, public, touch
from services import pricing as pricing_service
from services import program as program_service
from services import settlement as settlement_service
from services.lookup import get_backup_offer, get_bridge_program, get_property
from store import db
from timeutil import add_days, format_iso, parse_iso
from validation import body_of, get_datetime, get_int, get_str


def create_offer(payload, actor):
    data = body_of(payload)

    departing_property_id = get_str(data, "departing_property_id", required=True)
    program_id = get_str(data, "bridge_program_id", required=True)
    offer_price_cents = get_int(data, "offer_price_cents", required=True, minimum=0)
    window_days = get_int(
        data, "window_days", required=True, minimum=WINDOW_DAYS_MIN, maximum=WINDOW_DAYS_MAX
    )
    window_start = get_datetime(data, "window_start", required=True)

    property_record = get_property(departing_property_id)
    program = get_bridge_program(program_id)

    if property_record.get("kind") != "DEPARTING":
        raise ApiError(ERR_PROPERTY_KIND_MISMATCH, "A backup offer backs up a DEPARTING property.")

    basis = pricing_service.price_floor_cents(property_record)
    _assert_price_ok(offer_price_cents, basis, property_record)
    program_service._assert_appraisal_current(property_record)

    record = {
        "departing_property_id": property_record["id"],
        "bridge_program_id": program["id"],
        "offer_price_cents": offer_price_cents,
        "window_days": window_days,
        "window_start": format_iso(window_start),
        "status": "DRAFT",
        "expires_at": None,
        "exercised_at": None,
        "price_basis_cents": basis,
        "created_by": actor.user_id,
        "issued_by": None,
    }
    create("backup_offers", record)
    return record


def _assert_price_ok(offer_price_cents, basis, property_record):
    """The floor bound and the appraisal ceiling (both ERR_REGULATORY_PRICE_FLOOR)."""
    if int(offer_price_cents) < int(basis):
        raise ApiError(
            ERR_REGULATORY_PRICE_FLOOR,
            "The offer price is below the regulatory price floor of %d cents." % basis,
        )
    appraised = int(property_record.get("appraised_value_cents") or 0)
    if int(offer_price_cents) > appraised:
        raise ApiError(ERR_REGULATORY_PRICE_FLOOR, "The offer price may not exceed the appraised value.")


def issue_offer(offer_id, actor):
    offer = get_backup_offer(offer_id)

    if offer.get("status") != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Only a DRAFT offer may be issued.")

    property_record = get_property(offer["departing_property_id"])
    basis = pricing_service.price_floor_cents(property_record)
    offer["price_basis_cents"] = basis
    _assert_price_ok(offer.get("offer_price_cents"), basis, property_record)

    window_start = parse_iso(offer.get("window_start"))
    if window_start is None or current_time() < window_start:
        raise ApiError(
            ERR_EXERCISE_WINDOW_NOT_OPEN,
            "The exercise window has not opened yet.",
        )

    program = get_bridge_program(offer["bridge_program_id"])
    if program.get("occupancy_status") != "DEPARTING_LISTED":
        raise ApiError(
            ERR_INVALID_STATE,
            "The guarantee may only be issued once the departing home is on the market.",
        )

    offer["status"] = "ISSUED"
    offer["expires_at"] = format_iso(add_days(window_start, int(offer.get("window_days") or 0)))
    offer["issued_by"] = actor.user_id
    touch(offer)
    return offer


def extend_offer(offer_id, actor):
    offer = get_backup_offer(offer_id)
    status = offer.get("status")
    property_record = get_property(offer["departing_property_id"])

    if status == "EXPIRED":
        if property_record.get("listing_status") != "LISTED":
            raise ApiError(ERR_INVALID_STATE, "The property must still be LISTED to reissue the offer.")
        offer["status"] = "ISSUED"
        offer["expires_at"] = format_iso(add_days(current_time(), int(offer.get("window_days") or 0)))
        offer["issued_by"] = actor.user_id
        touch(offer)
        return offer

    if status == "EXTENDED":
        expires_at = parse_iso(offer.get("expires_at"))
        if expires_at is None or current_time() > expires_at:
            raise ApiError(ERR_BACKUP_OFFER_EXPIRED, "The offer's extended window has lapsed.")
        offer["status"] = "ISSUED"
        offer["expires_at"] = format_iso(add_days(current_time(), int(offer.get("window_days") or 0)))
        touch(offer)
        return offer

    if status == "ISSUED":
        expires_at = parse_iso(offer.get("expires_at"))
        if expires_at is None or current_time() > expires_at:
            raise ApiError(ERR_BACKUP_OFFER_EXPIRED, "The offer's exercise window has lapsed.")
        offer["status"] = "EXTENDED"
        offer["expires_at"] = format_iso(add_days(expires_at, OFFER_EXTENSION_DAYS))
        touch(offer)
        return offer

    raise ApiError(ERR_INVALID_STATE, "This offer cannot be extended from its current state.")


def exercise_offer(offer_id, payload, actor):
    offer = get_backup_offer(offer_id)
    data = body_of(payload)

    # Segregation of duties is settled before the payload is inspected (PRD 2.11).
    check_segregation_of_duties(actor, offer)

    expected_version = get_int(data, "expected_backup_offer_version", required=True)
    if expected_version != offer["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_backup_offer_version %s does not match the offer's version %s."
            % (expected_version, offer["version"]),
        )

    status = offer.get("status")
    if status == "EXPIRED":
        raise ApiError(ERR_BACKUP_OFFER_EXPIRED, "The offer's exercise window has lapsed.")
    if status == "VOIDED":
        raise ApiError(ERR_ALREADY_TERMINAL, "This offer is void.")
    if status not in ("ISSUED", "EXTENDED"):
        raise ApiError(ERR_INVALID_STATE, "Only an ISSUED or EXTENDED offer may be exercised.")

    expires_at = parse_iso(offer.get("expires_at"))
    if expires_at is None or current_time() > expires_at:
        raise ApiError(ERR_BACKUP_OFFER_EXPIRED, "The offer's exercise window has lapsed.")

    property_record = get_property(offer["departing_property_id"])
    if property_record.get("listing_status") != "LISTED":
        raise ApiError(ERR_INVALID_STATE, "The property must still be LISTED to exercise the offer.")

    program = get_bridge_program(offer["bridge_program_id"])

    offer["status"] = "EXERCISED"
    offer["exercised_at"] = format_iso(current_time())
    touch(offer)

    property_record["listing_status"] = "SOLD_TO_PROGRAM"
    property_record["program_inventory_flag"] = True
    touch(property_record)

    for listing in db.all("listings"):
        if listing.get("bridge_program_id") == program["id"] and listing.get("status") == "LIVE":
            listing["status"] = "PAUSED"
            listing["marketing_status"] = "STOPPED"
            touch(listing)

    entry = settlement_service.create_resale_entry_from_exercise(program)
    touch(program)
    return offer