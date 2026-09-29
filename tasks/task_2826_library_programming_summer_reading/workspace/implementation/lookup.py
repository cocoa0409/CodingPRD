"""Path and body identifier resolution (ladder steps 5 and 6).

Path identifiers are resolved strictly left to right and the response reports
the leftmost segment that names nothing; body foreign keys are resolved only
once every path identifier has resolved, in field-declaration order.
"""

import store
from errors import ApiError


def _need(table, entity_id, error_id):
    entity = store.get(table, entity_id)
    if entity is None:
        raise ApiError(error_id)
    return entity


def branch(entity_id):
    return _need("branches", entity_id, "ERR_BRANCH_NOT_FOUND")


def room(entity_id):
    return _need("rooms", entity_id, "ERR_ROOM_NOT_FOUND")


def program(entity_id):
    return _need("programs", entity_id, "ERR_PROGRAM_NOT_FOUND")


def reservation(entity_id):
    return _need("reservations", entity_id, "ERR_RESERVATION_NOT_FOUND")


def presenter(entity_id):
    return _need("presenters", entity_id, "ERR_PRESENTER_NOT_FOUND")


def contract(entity_id):
    return _need("contracts", entity_id, "ERR_CONTRACT_NOT_FOUND")


def challenge(entity_id):
    return _need("challenges", entity_id, "ERR_CHALLENGE_NOT_FOUND")


def tier(entity_id):
    # There is no tier-level 404: an unknown tier reports the challenge code.
    return _need("tiers", entity_id, "ERR_CHALLENGE_NOT_FOUND")


def participant(entity_id):
    return _need("participants", entity_id, "ERR_PARTICIPANT_NOT_FOUND")


def entry(entity_id):
    return _need("entries", entity_id, "ERR_LOG_ENTRY_NOT_FOUND")


def lot(entity_id):
    return _need("lots", entity_id, "ERR_LOT_NOT_FOUND")


def award(entity_id):
    return _need("awards", entity_id, "ERR_AWARD_NOT_FOUND")
