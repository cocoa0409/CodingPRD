"""Collection endpoints (PRD §3.4) + the computed digitization queue.

GET  /records/collections                              all roles except Anonymous
GET  /records/collections/{id}                         all roles except Anonymous
POST /records/collections/{id}/begin-processing        ProcessingArchivist
POST /records/collections/{id}/complete-description    ProcessingArchivist
POST /records/collections/{id}/enqueue-digitization    ProcessingArchivist
POST /records/collections/{id}/complete-digitization   ProcessingArchivist
POST /records/collections/{id}/publish-digital         ChiefArchivist
GET  /records/digitization-queue                       PlatformAdmin, ProcessingArchivist,
                                                       DeclassReviewer, ChiefArchivist,
                                                       ResearchRoomStaff
"""
from flask import Blueprint, request

import calcs
import constants as C
from envelope import ok_list, ok_object
from errors import err
from helpers import bump, get_collection
from store import DB, parse_dt
from validation import get_auth, get_body, list_page, parse_pagination, require_role

bp = Blueprint("collections", __name__)

QUEUE_ROLES = [
    "PlatformAdmin",
    "ProcessingArchivist",
    "DeclassReviewer",
    "ChiefArchivist",
    "ResearchRoomStaff",
]


@bp.get("/records/collections")
def list_collections():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in (
        "transfer_id",
        "schedule_id",
        "agency_id",
        "processing_status",
        "restriction_posture",
    ):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.collections.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/collections/<collection_id>")
def get_one_collection(collection_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_collection(collection_id))


@bp.post("/records/collections/<collection_id>/begin-processing")
def begin_processing(collection_id):
    uid, role = get_auth()
    require_role(role, ["ProcessingArchivist"])
    c = get_collection(collection_id)             # rung 3
    if c["processing_status"] != "UNPROCESSED":   # rung 8
        raise err(
            "ERR_INVALID_STATE",
            "begin-processing requires processing_status UNPROCESSED",
        )
    c["processing_status"] = "PROCESSING"
    c["assigned_archivist_id"] = uid
    bump(c)
    return ok_object(c)


@bp.post("/records/collections/<collection_id>/complete-description")
def complete_description(collection_id):
    _uid, role = get_auth()
    require_role(role, ["ProcessingArchivist"])
    c = get_collection(collection_id)             # rung 3
    if c["processing_status"] != "PROCESSING":    # rung 8
        raise err(
            "ERR_INVALID_STATE",
            "complete-description requires processing_status PROCESSING",
        )
    body = get_body()                             # rung 15
    notes = {}
    for field in ("scope_note", "arrangement_note", "container_list_summary"):
        v = body.get(field)
        if not isinstance(v, str) or v == "":
            raise err(
                "ERR_DESCRIPTION_INCOMPLETE",
                "scope_note, arrangement_note and container_list_summary must "
                "all be non-empty",
            )
        notes[field] = v
    c.update(notes)
    c["processing_status"] = "DESCRIBED"
    bump(c)
    return ok_object(c)


@bp.post("/records/collections/<collection_id>/enqueue-digitization")
def enqueue_digitization(collection_id):
    _uid, role = get_auth()
    require_role(role, ["ProcessingArchivist"])
    c = get_collection(collection_id)             # rung 3
    # ladder order: rung 8 from-state -> rung 10 posture -> rung 15 shape
    if c["digitization_status"] != "NOT_REQUESTED":
        raise err(
            "ERR_INVALID_STATE",
            "enqueue-digitization requires digitization_status NOT_REQUESTED",
        )
    if c["restriction_posture"] != "PUBLIC":
        raise err(
            "ERR_COLLECTION_RESTRICTED",
            "enqueue-digitization requires restriction_posture PUBLIC",
        )
    if c["processing_status"] != "DESCRIBED":
        raise err(
            "ERR_COLLECTION_NOT_DESCRIBED",
            "enqueue-digitization requires processing_status DESCRIBED",
        )
    c["digitization_status"] = "QUEUED"
    c["digitization_priority"] = calcs.digitization_priority(c, DB.now())
    bump(c)
    return ok_object(c)


@bp.post("/records/collections/<collection_id>/complete-digitization")
def complete_digitization(collection_id):
    _uid, role = get_auth()
    require_role(role, ["ProcessingArchivist"])
    c = get_collection(collection_id)             # rung 3
    if c["digitization_status"] != "QUEUED":      # rung 8
        raise err(
            "ERR_DIGITIZATION_NOT_QUEUED",
            "complete-digitization requires digitization_status QUEUED",
        )
    c["digitization_status"] = "DIGITIZED"
    bump(c)
    return ok_object(c)


@bp.post("/records/collections/<collection_id>/publish-digital")
def publish_digital(collection_id):
    _uid, role = get_auth()
    require_role(role, ["ChiefArchivist"])
    c = get_collection(collection_id)             # rung 3
    if c["processing_status"] != "DESCRIBED":     # rung 8 (from-state)
        raise err(
            "ERR_INVALID_STATE",
            "publish-digital requires processing_status DESCRIBED",
        )
    if c["digitization_status"] != "DIGITIZED":   # rung 8 (endpoint-specific)
        raise err(
            "ERR_DIGITIZATION_NOT_READY",
            "publish-digital requires digitization_status DIGITIZED",
        )
    if c["restriction_posture"] != "PUBLIC":      # rung 10
        raise err(
            "ERR_COLLECTION_RESTRICTED",
            "publish-digital requires restriction_posture PUBLIC",
        )
    c["processing_status"] = "PUBLISHED"
    bump(c)
    return ok_object(c)


@bp.get("/records/digitization-queue")
def digitization_queue():
    _uid, role = get_auth()
    require_role(role, QUEUE_ROLES)
    queued = [
        c for c in DB.collections.values() if c["digitization_status"] == "QUEUED"
    ]
    # priority DESC, records_cutoff_date ASC (older first), created_at ASC.
    # id is never used; Python's sort is stable so exact created_at ties keep
    # insertion order.
    queued.sort(
        key=lambda c: (
            -c["digitization_priority"],
            parse_dt(c["records_cutoff_date"]),
            c["created_at"],
        )
    )
    total = len(queued)
    limit, offset = parse_pagination()
    return ok_list(queued[offset:offset + limit], total, limit, offset)
