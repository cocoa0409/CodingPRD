"""PRD 2.8 step 4 — existence resolution, left to right, with per-kind error codes."""

from errors import ApiError
from store import db


def _fetch(collection, identifier, error_id):
    if identifier is None:
        return None
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def project(identifier):
    return _fetch(db.projects, identifier, "ERR_PROJECT_NOT_FOUND")


def room(identifier):
    return _fetch(db.rooms, identifier, "ERR_TELECOM_ROOM_NOT_FOUND")


def rack(identifier):
    return _fetch(db.racks, identifier, "ERR_RACK_NOT_FOUND")


def assignment(identifier):
    return _fetch(db.assignments, identifier, "ERR_RACK_ASSIGNMENT_NOT_FOUND")


def segment(identifier):
    return _fetch(db.segments, identifier, "ERR_PATHWAY_SEGMENT_NOT_FOUND")


def cable_type(identifier):
    return _fetch(db.cable_types, identifier, "ERR_CABLE_TYPE_NOT_FOUND")


def link(identifier):
    return _fetch(db.links, identifier, "ERR_LINK_NOT_FOUND")


def route(identifier):
    return _fetch(db.routes, identifier, "ERR_ROUTE_NOT_FOUND")


def test_result(identifier):
    return _fetch(db.test_results, identifier, "ERR_TEST_RESULT_NOT_FOUND")


def registration(identifier):
    return _fetch(db.registrations, identifier, "ERR_WARRANTY_REGISTRATION_NOT_FOUND")


def ticket(identifier):
    return _fetch(db.tickets, identifier, "ERR_MAC_TICKET_NOT_FOUND")


def coordination(identifier):
    return _fetch(db.coordinations, identifier, "ERR_COORDINATION_NOT_FOUND")
