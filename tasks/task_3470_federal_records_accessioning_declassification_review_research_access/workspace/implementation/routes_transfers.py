"""Transfer endpoints (PRD §3.2, §3.3).

POST /records/transfers                        RecordsOfficer, 201
GET  /records/transfers                        all roles except Anonymous
GET  /records/transfers/{id}                   all roles except Anonymous
POST /records/transfers/{id}/submit-metadata   RecordsOfficer
POST /records/transfers/{id}/accession         ProcessingArchivist (creates the Collection)
POST /records/transfers/{id}/withdraw          RecordsOfficer
"""
from flask import Blueprint, request

import calcs
import constants as C
from envelope import ok_list, ok_object
from errors import err
from helpers import bump, get_schedule, get_transfer, get_agency
from store import DB, new_id, parse_dt, ts3, tsc
from validation import (
    body_fk,
    get_auth,
    get_body,
    list_page,
    req_dt,
    req_enum,
    req_int,
    req_list_str,
    req_str,
    require_ownership,
    require_role,
)

bp = Blueprint("transfers", __name__)


@bp.post("/records/transfers")
def create_transfer():
    uid, role = get_auth()                        # rung 1
    require_role(role, ["RecordsOfficer"])        # rung 2
    body = get_body()
    # rung 4: body FK existence in declared input order: schedule_id, agency_id
    schedule_id = body_fk(body, "schedule_id")
    schedule = get_schedule(schedule_id)
    agency_id = body_fk(body, "agency_id")
    get_agency(agency_id)
    require_ownership(uid, agency_id)             # rung 5
    if agency_id != schedule["agency_id"]:        # rung 6 cross-FK consistency
        raise err(
            "ERR_AGENCY_MISMATCH",
            "transfer agency_id does not equal the schedule's agency_id",
        )
    # rung 14: method/metadata compatibility
    method = req_enum(body, "transfer_method", C.TRANSFER_METHODS)
    standard = req_enum(body, "metadata_standard", C.METADATA_STANDARDS)
    if method == "ELECTRONIC" and standard != "PREMIS_3_0":
        raise err(
            "ERR_METADATA_STANDARD_MISMATCH",
            "ELECTRONIC transfers require metadata_standard PREMIS_3_0",
        )
    if method == "PHYSICAL" and standard not in ("EAD_2002", "MODS_3_7"):
        raise err(
            "ERR_METADATA_STANDARD_MISMATCH",
            "PHYSICAL transfers require metadata_standard EAD_2002 or MODS_3_7",
        )
    linear_feet = body.get("linear_feet")
    checksum_manifest = body.get("checksum_manifest")
    if method == "PHYSICAL":
        if (
            isinstance(linear_feet, bool)
            or not isinstance(linear_feet, (int, float))
            or linear_feet <= 0
        ):
            raise err(
                "ERR_METHOD_REQUIREMENT_MISSING",
                "PHYSICAL transfers require linear_feet greater than zero",
            )
    else:
        if not isinstance(checksum_manifest, str) or checksum_manifest == "":
            raise err(
                "ERR_METHOD_REQUIREMENT_MISSING",
                "ELECTRONIC transfers require a non-empty checksum_manifest",
            )
    # rung 15: business shape rules on the schedule
    if schedule["disposition"] != "PERMANENT":
        raise err(
            "ERR_NOT_PERMANENT_DISPOSITION",
            "only PERMANENT schedules may underlie a transfer",
        )
    if schedule["status"] != "APPROVED":
        raise err(
            "ERR_SCHEDULE_NOT_APPROVED",
            "transfer requires an APPROVED schedule",
        )
    unit_count = req_int(body, "unit_count")
    if unit_count < 1:
        raise err("ERR_INVALID_REQUEST", "unit_count must be at least 1")
    cutoff_dt = req_dt(body, "records_cutoff_date")
    now = ts3(DB.now())
    transfer = {
        "id": new_id(),
        "schedule_id": schedule_id,
        "agency_id": agency_id,
        "transfer_method": method,
        "metadata_standard": standard,
        "unit_count": unit_count,
        "linear_feet": linear_feet if method == "PHYSICAL" else None,
        "checksum_manifest": checksum_manifest if method == "ELECTRONIC" else None,
        "records_cutoff_date": tsc(cutoff_dt),
        "status": "INITIATED",
        "submitted_metadata_elements": [],
        "last_missing_elements": [],
        "accessioned_at": None,
        "collection_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.transfers[transfer["id"]] = transfer
    return ok_object(transfer, 201)


@bp.get("/records/transfers")
def list_transfers():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("schedule_id", "agency_id", "collection_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.transfers.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/transfers/<transfer_id>")
def get_one_transfer(transfer_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_transfer(transfer_id))


@bp.post("/records/transfers/<transfer_id>/submit-metadata")
def submit_metadata(transfer_id):
    uid, role = get_auth()
    require_role(role, ["RecordsOfficer"])
    t = get_transfer(transfer_id)                 # rung 3
    require_ownership(uid, t["agency_id"])        # rung 5
    if t["status"] not in ("INITIATED", "DEFICIENT"):   # rung 8
        raise err(
            "ERR_INVALID_STATE",
            "submit-metadata requires status INITIATED or DEFICIENT",
        )
    elements = req_list_str(get_body(), "metadata_elements")   # rung 15
    required = C.METADATA_REQUIRED[t["metadata_standard"]]
    missing = sorted(e for e in required if e not in elements)
    t["submitted_metadata_elements"] = list(elements)
    t["last_missing_elements"] = missing
    t["status"] = "VALIDATED" if not missing else "DEFICIENT"
    bump(t)
    return ok_object(t)


@bp.post("/records/transfers/<transfer_id>/accession")
def accession_transfer(transfer_id):
    _uid, role = get_auth()
    require_role(role, ["ProcessingArchivist"])
    t = get_transfer(transfer_id)                 # rung 3
    if t["status"] != "VALIDATED":                # rung 8
        raise err("ERR_TRANSFER_NOT_VALIDATED", "accession requires status VALIDATED")
    schedule = DB.schedules[t["schedule_id"]]
    cutoff_dt = parse_dt(t["records_cutoff_date"])
    # rung 13: transfer-lag gate, inclusive anniversary boundary
    eligible_at = calcs.anniversary_add(cutoff_dt, schedule["transfer_lag_years"])
    if DB.now() < eligible_at:
        raise err(
            "ERR_TRANSFER_LAG_NOT_ELAPSED",
            "transfer lag has not elapsed for this transfer",
        )
    receipt_note = req_str(get_body(), "receipt_note")   # rung 15 (supplied, not stored)
    del receipt_note
    now_dt = DB.now()
    now3 = ts3(now_dt)
    classification = schedule["classification_default"]
    collection = {
        "id": new_id(),
        "transfer_id": t["id"],
        "schedule_id": t["schedule_id"],
        "agency_id": t["agency_id"],
        "records_domain": schedule["records_domain"],
        "classification_level": classification,
        "records_cutoff_date": t["records_cutoff_date"],
        "units_total": t["unit_count"],
        "processing_status": "UNPROCESSED",
        "assigned_archivist_id": None,
        "scope_note": None,
        "arrangement_note": None,
        "container_list_summary": None,
        "restriction_posture": calcs.restriction_posture(
            {"classification_level": classification}, []
        ),
        "backlog_score": calcs.backlog_score(
            classification, schedule["records_domain"], cutoff_dt, now_dt
        ),
        "pull_count_total": 0,
        "repro_pages_fulfilled": 0,
        "foia_release_count": 0,
        "digitization_status": "NOT_REQUESTED",
        "digitization_priority": None,
        "declass_outcome": "NONE",
        "created_at": now3,
        "updated_at": now3,
        "version": 1,
    }
    DB.collections[collection["id"]] = collection
    t["status"] = "ACCESSIONED"
    t["accessioned_at"] = tsc(now_dt)
    t["collection_id"] = collection["id"]
    bump(t)
    return ok_object(t)


@bp.post("/records/transfers/<transfer_id>/withdraw")
def withdraw_transfer(transfer_id):
    uid, role = get_auth()
    require_role(role, ["RecordsOfficer"])
    t = get_transfer(transfer_id)                 # rung 3
    require_ownership(uid, t["agency_id"])        # rung 5
    if t["status"] not in ("INITIATED", "DEFICIENT", "VALIDATED"):   # rung 8
        raise err(
            "ERR_INVALID_STATE",
            "withdraw requires status INITIATED, DEFICIENT or VALIDATED",
        )
    t["status"] = "WITHDRAWN"
    bump(t)
    return ok_object(t)
