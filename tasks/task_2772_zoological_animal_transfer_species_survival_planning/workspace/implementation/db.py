"""In-memory store. Starts completely empty on every boot -- nothing is ever seeded."""
import uuid

from flask import g

from core import fail, now_instant

institutions = {}
programs = {}
veterinarians = {}
animals = {}
recommendations = {}
agreements = {}
documents = {}
tests = {}
occupancies = {}
bookings = {}
protocols = {}
submissions = {}

crate_sessions = []       # {animal_id, session_date, trainer_name, duration_minutes}
observations = []         # {protocol_id, stage, aggression_level, observer_name, observed_on, seq}

_counter = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _counter["n"] += 1
    return _counter["n"]


def insert(collection, rec, common=True):
    rec["id"] = new_id()
    rec["_seq"] = next_seq()
    rec["created_at"] = now_instant()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version -- at most one bump per record per request."""
    if rec is None:
        return rec
    rec["updated_at"] = now_instant()
    try:
        seen = g._touched
    except AttributeError:
        seen = g._touched = set()
    key = rec["id"]
    if key not in seen:
        seen.add(key)
        rec["version"] = rec.get("version", 0) + 1
    return rec


def _get(collection, ident, error_id):
    if not isinstance(ident, str):
        fail(error_id)
    rec = collection.get(ident)
    if rec is None:
        fail(error_id)
    return rec


def get_institution(ident):
    return _get(institutions, ident, "ERR_INSTITUTION_NOT_FOUND")


def get_program(ident):
    return _get(programs, ident, "ERR_SPECIES_PROGRAM_NOT_FOUND")


def get_vet(ident):
    return _get(veterinarians, ident, "ERR_VETERINARIAN_NOT_FOUND")


def get_animal(ident):
    return _get(animals, ident, "ERR_ANIMAL_NOT_FOUND")


def get_recommendation(ident):
    return _get(recommendations, ident, "ERR_RECOMMENDATION_NOT_FOUND")


def get_agreement(ident):
    return _get(agreements, ident, "ERR_AGREEMENT_NOT_FOUND")


def get_document(ident):
    return _get(documents, ident, "ERR_DOCUMENT_NOT_FOUND")


def get_test(ident):
    return _get(tests, ident, "ERR_TEST_NOT_FOUND")


def get_occupancy(ident):
    return _get(occupancies, ident, "ERR_OCCUPANCY_NOT_FOUND")


def get_booking(ident):
    return _get(bookings, ident, "ERR_BOOKING_NOT_FOUND")


def get_protocol(ident):
    return _get(protocols, ident, "ERR_PROTOCOL_NOT_FOUND")


def get_submission(ident):
    return _get(submissions, ident, "ERR_SUBMISSION_NOT_FOUND")


def sorted_by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
