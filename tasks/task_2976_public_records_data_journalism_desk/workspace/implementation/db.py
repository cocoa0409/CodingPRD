"""In-memory data store.

Every collection starts EMPTY on each boot.  Nothing is ever seeded, preloaded
or hardcoded: tests build all state through the declared endpoints.
"""
import itertools
import uuid

import clock
from errors import ApiError

COLLECTIONS = (
    "desks",
    "agencies",
    "records_requests",
    "appeals",
    "datasets",
    "field_definitions",
    "investigations",
    "analysis_runs",
    "findings",
    "expert_reviewers",
    "review_assignments",
    "subject_response_requests",
    "secure_enclaves",
    "enclave_sessions",
)

store = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def reset():
    for name in COLLECTIONS:
        store[name].clear()


def new_id():
    return str(uuid.uuid4())


def insert(collection, entity, versioned=True):
    """Stamp system fields and store the row."""
    ts = clock.now_iso()
    entity["id"] = entity.get("id") or new_id()
    entity["created_at"] = ts
    if versioned:
        entity["updated_at"] = ts
        entity["version"] = 1
    entity["_seq"] = next(_seq)
    store[collection][entity["id"]] = entity
    return entity


def touch(entity):
    """A row that was actually modified gets its own bump and timestamp."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] = entity.get("version", 0) + 1
    return entity


def serialize(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_all(entities):
    return [serialize(e) for e in entities]


def ordered(collection):
    """Default ordering: created_at ascending (insertion order breaks ties)."""
    rows = list(store[collection].values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def all_of(collection):
    return list(store[collection].values())


# --------------------------------------------------------------------------
# Existence helpers.  Each raises the entity-specific not-found error.
# --------------------------------------------------------------------------
_NOT_FOUND = {
    "desks": "ERR_DESK_NOT_FOUND",
    "agencies": "ERR_AGENCY_NOT_FOUND",
    "records_requests": "ERR_REQUEST_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
    "datasets": "ERR_DATASET_NOT_FOUND",
    "field_definitions": "ERR_FIELD_NOT_FOUND",
    "investigations": "ERR_INVESTIGATION_NOT_FOUND",
    "analysis_runs": "ERR_RUN_NOT_FOUND",
    "findings": "ERR_FINDING_NOT_FOUND",
    "expert_reviewers": "ERR_REVIEWER_NOT_FOUND",
    "review_assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "subject_response_requests": "ERR_SUBJECT_REQUEST_NOT_FOUND",
    "secure_enclaves": "ERR_ENCLAVE_NOT_FOUND",
    "enclave_sessions": "ERR_SESSION_NOT_FOUND",
}


def find(collection, entity_id):
    if not isinstance(entity_id, str):
        return None
    return store[collection].get(entity_id)


def must(collection, entity_id):
    row = find(collection, entity_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection], "%s was not found." % collection[:-1].replace("_", " "))
    return row


def get_desk(i):
    return must("desks", i)


def get_agency(i):
    return must("agencies", i)


def get_request(i):
    return must("records_requests", i)


def get_appeal(i):
    return must("appeals", i)


def get_dataset(i):
    return must("datasets", i)


def get_field(i):
    return must("field_definitions", i)


def get_investigation(i):
    return must("investigations", i)


def get_run(i):
    return must("analysis_runs", i)


def get_finding(i):
    return must("findings", i)


def get_reviewer(i):
    return must("expert_reviewers", i)


def get_assignment(i):
    return must("review_assignments", i)


def get_subject(i):
    return must("subject_response_requests", i)


def get_enclave(i):
    return must("secure_enclaves", i)


def get_session(i):
    return must("enclave_sessions", i)


# --------------------------------------------------------------------------
# Relationship helpers
# --------------------------------------------------------------------------
def children(collection, field, value):
    rows = [r for r in store[collection].values() if r.get(field) == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def datasets_of_investigation(investigation_id):
    return children("datasets", "investigation_id", investigation_id)


def datasets_of_request(request_id):
    return children("datasets", "request_id", request_id)


def runs_of_investigation(investigation_id):
    return children("analysis_runs", "investigation_id", investigation_id)


def findings_of_investigation(investigation_id):
    return children("findings", "investigation_id", investigation_id)


def subjects_of_investigation(investigation_id):
    return children("subject_response_requests", "investigation_id", investigation_id)


def investigations_of_desk(desk_id):
    return children("investigations", "desk_id", desk_id)


def sessions_of_enclave(enclave_id):
    return children("enclave_sessions", "enclave_id", enclave_id)


def sessions_of_dataset(dataset_id):
    return children("enclave_sessions", "dataset_id", dataset_id)


def fields_of_dataset(dataset_id):
    return children("field_definitions", "dataset_id", dataset_id)


def assignments_of_finding(finding_id):
    return children("review_assignments", "finding_id", finding_id)


def assignments_of_reviewer(reviewer_id):
    return children("review_assignments", "reviewer_id", reviewer_id)


def appeals_of_request(request_id):
    return children("appeals", "request_id", request_id)


def desk_of_dataset(dataset):
    request = find("records_requests", dataset.get("request_id"))
    if request is None:
        return None
    return find("desks", request.get("desk_id"))
