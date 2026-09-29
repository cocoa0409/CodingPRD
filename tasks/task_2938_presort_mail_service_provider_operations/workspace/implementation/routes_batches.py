"""Commingle batches: pooling, containerization and closing sortation."""

from flask import Blueprint

import calc
import cascades
import domain
import enums
import serialize
import shape
from envelope import enum_filter, listed, no_content, single, str_filter
from errors import ApiError
from store import db, touch

bp = Blueprint("batches", __name__)

BATCH_READ_ROLES = (
    "BureauAdmin",
    "PostageManager",
    "PresortOperator",
    "AcceptanceClerk",
)


@bp.post("/commingle-batches")
def create_batch():
    shape.authenticate(("PresortOperator",))
    body = shape.validate_body(
        {
            "mail_class": {"type": "enum", "values": enums.MAIL_CLASSES},
            "processing_category": {
                "type": "enum",
                "values": enums.PROCESSING_CATEGORIES,
            },
            "entry_facility_id": {"type": "string"},
        }
    )
    facility = domain.get_facility(body["entry_facility_id"])
    record = db.insert(
        "commingle_batches",
        {
            "entry_facility_id": facility["id"],
            "mail_class": body["mail_class"],
            "processing_category": body["processing_category"],
            "status": "OPEN",
            "member_job_count": 0,
            "total_piece_count": 0,
            "container_count": 0,
            "achieved_tier": "NONE",
            "rate_mills_per_piece": 0,
            "batch_postage_cents": 0,
        },
    )
    return single(serialize.commingle_batch(record), 201)


@bp.get("/commingle-batches/<batch_id>")
def read_batch(batch_id):
    shape.authenticate(BATCH_READ_ROLES)
    return single(serialize.commingle_batch(domain.get_batch(batch_id)))


@bp.get("/commingle-batches")
def list_batches():
    shape.authenticate(BATCH_READ_ROLES)
    status = enum_filter("status", enums.BATCH_STATUSES)
    mail_class = enum_filter("mail_class", enums.MAIL_CLASSES)
    facility_id = str_filter("entry_facility_id")
    records = []
    for batch in db.ordered("commingle_batches"):
        if status is not None and batch["status"] != status:
            continue
        if mail_class is not None and batch["mail_class"] != mail_class:
            continue
        if facility_id is not None and batch["entry_facility_id"] != facility_id:
            continue
        records.append(batch)
    return listed(records, serialize.commingle_batch)


@bp.post("/commingle-batches/<batch_id>/members")
def pool_job(batch_id):
    shape.authenticate(("PresortOperator",))
    body = shape.validate_body({"mail_job_id": {"type": "string"}})
    batch = domain.get_batch(batch_id)
    job = domain.get_job(body["mail_job_id"])
    # rungs 10 and 11
    if job["status"] == "POOLED":
        raise ApiError("ERR_JOB_ALREADY_POOLED")
    if job["status"] != "HYGIENE_CLEARED":
        raise ApiError("ERR_INVALID_JOB_STATE")
    # rung 12
    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    client = domain.get_client(job["client_id"])
    permit = domain.get_permit(job["permit_account_id"])
    # rung 18
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_SUSPENDED")
    # rung 19
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
    # rung 23
    if not job["move_update_compliant"]:
        raise ApiError("ERR_MOVE_UPDATE_STALE")
    # rung 24
    if job["address_quality_pct"] < calc.MIN_ADDRESS_QUALITY_PCT:
        raise ApiError("ERR_ADDRESS_QUALITY_BELOW_MINIMUM")
    # rung 25
    if job["mail_class"] != batch["mail_class"]:
        raise ApiError("ERR_MAIL_CLASS_MISMATCH")
    # rung 26
    if job["processing_category"] != batch["processing_category"]:
        raise ApiError("ERR_PROCESSING_CATEGORY_MISMATCH")
    # rung 27
    if not client["commingle_opt_in"]:
        raise ApiError("ERR_COMMINGLE_OPT_OUT")

    member = db.insert(
        "batch_members",
        {
            "commingle_batch_id": batch["id"],
            "mail_job_id": job["id"],
            "contributed_piece_count": job["accepted_piece_count"],
            "share_basis_pct": None,
            "allocated_postage_cents": 0,
            "allocated_adjustment_cents": 0,
        },
    )
    job["status"] = "POOLED"
    job["commingle_batch_id"] = batch["id"]
    touch(job)
    domain.derive_batch(batch, fresh_member_ids=(member["id"],))
    touch(batch)
    return single(serialize.batch_member(member), 201)


@bp.get("/commingle-batches/<batch_id>/members")
def list_batch_members(batch_id):
    shape.authenticate(BATCH_READ_ROLES)
    domain.get_batch(batch_id)
    return listed(domain.batch_members(batch_id), serialize.batch_member)


@bp.delete("/commingle-batches/<batch_id>/members/<batch_member_id>")
def withdraw_member(batch_id, batch_member_id):
    shape.authenticate(("PresortOperator",))
    shape.validate_body({})
    batch = domain.get_batch(batch_id)
    member = domain.must_get("batch_members", batch_member_id)
    # rung 6
    if member["commingle_batch_id"] != batch["id"]:
        raise ApiError("ERR_BATCH_MEMBER_NOT_FOUND")
    # rung 12
    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    job = db.mail_jobs.get(member["mail_job_id"])
    if job is None or job["status"] != "POOLED":
        raise ApiError("ERR_INVALID_JOB_STATE")

    del db.batch_members[member["id"]]
    job["status"] = "HYGIENE_CLEARED"
    job["commingle_batch_id"] = None
    job["postage_due_cents"] = 0
    touch(job)
    domain.derive_batch(batch)
    touch(batch)
    return no_content()


@bp.post("/commingle-batches/<batch_id>/containers")
def add_container(batch_id):
    shape.authenticate(("PresortOperator",))
    body = shape.validate_body(
        {
            "container_type": {"type": "enum", "values": enums.CONTAINER_TYPES},
            "destination_zip3": {"type": "string", "check": shape.zip3_check},
            "sort_level": {"type": "enum", "values": enums.SORT_LEVELS},
            "piece_count": {"type": "integer"},
        }
    )
    batch = domain.get_batch(batch_id)
    # rung 12
    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    # rung 31
    if body["piece_count"] < 1:
        raise ApiError("ERR_INVALID_PIECE_COUNT")

    facility = db.entry_facilities[batch["entry_facility_id"]]
    zone, committed_days = calc.zone_and_days(
        facility, body["destination_zip3"], batch["mail_class"]
    )
    record = db.insert(
        "sort_containers",
        {
            "commingle_batch_id": batch["id"],
            "container_type": body["container_type"],
            "destination_zip3": body["destination_zip3"],
            "sort_level": body["sort_level"],
            "piece_count": body["piece_count"],
            "qualifies": calc.container_qualifies(
                body["container_type"], body["sort_level"], body["piece_count"]
            ),
            "placard_id": None,
            "sequence_index": batch["container_count"],
            "zone": zone,
            "committed_days": committed_days,
            "status": "STAGED",
        },
    )
    batch["container_count"] += 1
    touch(batch)
    return single(serialize.sort_container(record), 201)


@bp.get("/commingle-batches/<batch_id>/containers")
def list_batch_containers(batch_id):
    shape.authenticate(BATCH_READ_ROLES)
    domain.get_batch(batch_id)
    return listed(domain.batch_containers(batch_id), serialize.sort_container)


@bp.post("/commingle-batches/<batch_id>/sort")
def close_sortation(batch_id):
    shape.authenticate(("PresortOperator",))
    shape.validate_body({})
    batch = domain.get_batch(batch_id)
    # rung 12
    if batch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    containers = domain.batch_containers(batch["id"])
    # rung 32
    if batch["member_job_count"] < 1 or batch["container_count"] < 1:
        raise ApiError("ERR_BATCH_HAS_NO_CONTAINERS")
    # rung 33
    if any(not container["qualifies"] for container in containers):
        raise ApiError("ERR_CONTAINER_NOT_QUALIFIED")
    # rung 34
    if sum(c["piece_count"] for c in containers) != batch["total_piece_count"]:
        raise ApiError("ERR_CONTAINER_PIECE_MISMATCH")

    cascades.close_sortation(batch)
    return single(serialize.commingle_batch(batch))


@bp.get("/commingle-batches/<batch_id>/postage-statements")
def list_batch_statements(batch_id):
    shape.authenticate(("BureauAdmin", "PostageManager", "AcceptanceClerk"))
    domain.get_batch(batch_id)
    return listed(domain.batch_statements(batch_id), serialize.postage_statement)


@bp.get("/commingle-batches/<batch_id>/drop-shipments")
def list_batch_shipments(batch_id):
    shape.authenticate(BATCH_READ_ROLES)
    domain.get_batch(batch_id)
    return listed(domain.batch_shipments(batch_id), serialize.drop_shipment)
