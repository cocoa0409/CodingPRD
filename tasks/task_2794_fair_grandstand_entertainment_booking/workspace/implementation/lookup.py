"""Resource resolution helpers, each carrying its own 404 identifier (PRD section 2.9)."""

from db import db
from errors import ApiError


def _fetch(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def get_edition(identifier):
    return _fetch(db.editions, identifier, "ERR_FAIR_EDITION_NOT_FOUND")


def get_stage(identifier):
    return _fetch(db.stages, identifier, "ERR_STAGE_NOT_FOUND")


def get_agent(identifier):
    return _fetch(db.agents, identifier, "ERR_TALENT_AGENT_NOT_FOUND")


def get_artist(identifier):
    return _fetch(db.artists, identifier, "ERR_ARTIST_NOT_FOUND")


def get_offer(identifier):
    return _fetch(db.offers, identifier, "ERR_OFFER_NOT_FOUND")


def get_booking(identifier):
    return _fetch(db.bookings, identifier, "ERR_SHOW_BOOKING_NOT_FOUND")


def get_scale(identifier):
    return _fetch(db.scales, identifier, "ERR_TICKET_SCALE_NOT_FOUND")


def get_advance(identifier):
    return _fetch(db.advances, identifier, "ERR_PRODUCTION_ADVANCE_NOT_FOUND")


def get_rider_item(identifier):
    return _fetch(db.rider_items, identifier, "ERR_RIDER_ITEM_NOT_FOUND")


def get_sponsor(identifier):
    return _fetch(db.sponsors, identifier, "ERR_SPONSOR_NOT_FOUND")


def get_activation(identifier):
    return _fetch(db.activations, identifier, "ERR_ACTIVATION_NOT_FOUND")


def get_settlement(identifier):
    return _fetch(db.settlements, identifier, "ERR_SETTLEMENT_NOT_FOUND")
