"""Existence lookups (validation priority 3). Path resources are validated
left-to-right before body-referenced entities (PRD 2.6)."""

from db import store
from errors import (
    raise_err,
    ERR_PARTY_NOT_FOUND,
    ERR_PATENT_NOT_FOUND,
    ERR_MATTER_NOT_FOUND,
    ERR_PETITION_NOT_FOUND,
    ERR_PROCEEDING_NOT_FOUND,
    ERR_BRIEF_NOT_FOUND,
    ERR_REQUEST_NOT_FOUND,
    ERR_MOTION_NOT_FOUND,
    ERR_HEARING_NOT_FOUND,
    ERR_ROOM_NOT_FOUND,
    ERR_APPEAL_NOT_FOUND,
)


def get_party(party_id):
    party = store.parties.get(party_id)
    if party is None:
        raise_err(ERR_PARTY_NOT_FOUND, f"party {party_id} does not exist")
    return party


def get_patent(patent_id):
    patent = store.patents.get(patent_id)
    if patent is None:
        raise_err(ERR_PATENT_NOT_FOUND, f"patent {patent_id} does not exist")
    return patent


def get_matter(matter_id):
    matter = store.matters.get(matter_id)
    if matter is None:
        raise_err(ERR_MATTER_NOT_FOUND, f"matter {matter_id} does not exist")
    return matter


def get_petition(petition_id):
    petition = store.petitions.get(petition_id)
    if petition is None:
        raise_err(ERR_PETITION_NOT_FOUND, f"petition {petition_id} does not exist")
    return petition


def get_proceeding(proceeding_id):
    proceeding = store.proceedings.get(proceeding_id)
    if proceeding is None:
        raise_err(ERR_PROCEEDING_NOT_FOUND,
                  f"proceeding {proceeding_id} does not exist")
    return proceeding


def get_brief(brief_id):
    brief = store.briefs.get(brief_id)
    if brief is None:
        raise_err(ERR_BRIEF_NOT_FOUND, f"brief {brief_id} does not exist")
    return brief


def get_request(request_id):
    req = store.discovery_requests.get(request_id)
    if req is None:
        raise_err(ERR_REQUEST_NOT_FOUND,
                  f"discovery request {request_id} does not exist")
    return req


def get_motion(motion_id):
    motion = store.motions.get(motion_id)
    if motion is None:
        raise_err(ERR_MOTION_NOT_FOUND, f"motion {motion_id} does not exist")
    return motion


def get_hearing(hearing_id):
    hearing = store.hearings.get(hearing_id)
    if hearing is None:
        raise_err(ERR_HEARING_NOT_FOUND, f"hearing {hearing_id} does not exist")
    return hearing


def get_room(room_id):
    room = store.rooms.get(room_id)
    if room is None:
        raise_err(ERR_ROOM_NOT_FOUND, f"hearing room {room_id} does not exist")
    return room


def get_appeal(appeal_id):
    appeal = store.appeals.get(appeal_id)
    if appeal is None:
        raise_err(ERR_APPEAL_NOT_FOUND, f"appeal {appeal_id} does not exist")
    return appeal


def proceeding_context(proceeding):
    """The (petition, patent) pair joined to a proceeding."""
    petition = store.petitions.get(proceeding["petition_id"])
    patent = store.patents.get(proceeding["patent_id"])
    return petition, patent


def is_party_to_proceeding(user_id, proceeding):
    """A party to the proceeding is its petitioner or the patent owner."""
    petition, patent = proceeding_context(proceeding)
    petitioner_id = petition["petitioner_id"] if petition else None
    owner_id = patent["owner_id"] if patent else None
    return user_id == petitioner_id or user_id == owner_id
