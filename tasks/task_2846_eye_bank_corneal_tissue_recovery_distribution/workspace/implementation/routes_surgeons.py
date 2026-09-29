"""Surgeons, credentialing and surgeon requests."""

from flask import Blueprint, request

import auth
import calc
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("surgeons", __name__)

SPECIALTIES = ("PK", "DSAEK", "DMEK", "THERAPEUTIC")
CREDENTIAL_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED")
PROCEDURE_TYPES = ("PK", "DSAEK", "DMEK", "THERAPEUTIC")
LATERALITY_PREFERENCES = ("OD", "OS", "ANY")
URGENCIES = ("ROUTINE", "URGENT")
REQUEST_STATUSES = ("OPEN", "ALLOCATED", "FULFILLED", "CANCELLED", "EXPIRED")


def request_sort(rows):
    return sorted(rows, key=lambda r: (-r["priority_score"], r["created_at"], r["_seq"]))


@bp.post("/eye-bank/surgeons")
def create_surgeon():
    auth.authenticate(("EyeBankCoordinator",))
    body = auth.body_dict()

    full_name = validate.req_str(body, "full_name", 1, 80)
    center_code = validate.req_str(body, "center_code", 1, 16)
    specialty = validate.req_enum(body, "specialty", SPECIALTIES)

    row = store.base_row()
    row.update(
        {
            "full_name": full_name,
            "center_code": center_code,
            "specialty": specialty,
            "credential_status": "ACTIVE",
            "gross_billed_cents": 0,
            "credited_fee_cents": 0,
            "outstanding_fee_cents": 0,
            "substantiated_reaction_count": 0,
        }
    )
    store.DB["surgeons"][row["id"]] = row
    return envelope.ok(serialize.surgeon(row), 201)


@bp.get("/eye-bank/surgeons/<surgeon_id>")
def get_surgeon(surgeon_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    row = validate.lookup("surgeons", surgeon_id)
    return envelope.ok(serialize.surgeon(row))


@bp.post("/eye-bank/surgeons/<surgeon_id>/credential-status")
def set_credential_status(surgeon_id):
    auth.authenticate(("MedicalDirector",))
    row = validate.lookup("surgeons", surgeon_id)
    body = auth.body_dict()
    status = validate.req_enum(body, "credential_status", CREDENTIAL_STATUSES)
    row["credential_status"] = status
    store.touch(row)
    return envelope.ok(serialize.surgeon(row))


@bp.get("/eye-bank/surgeons/<surgeon_id>/requests")
def list_surgeon_requests(surgeon_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    validate.lookup("surgeons", surgeon_id)
    rows = [r for r in store.DB["requests"].values() if r["surgeon_id"] == surgeon_id]
    return envelope.nested_list(request_sort(rows), serialize.surgeon_request)


@bp.post("/eye-bank/surgeon-requests")
def create_surgeon_request():
    actor = auth.authenticate(("Surgeon", "EyeBankCoordinator"))
    body = auth.body_dict()

    surgeon = validate.resolve_fk(body, "surgeon_id", "surgeons")

    validate.req_str(body, "surgeon_id")
    procedure_type = validate.req_enum(body, "procedure_type", PROCEDURE_TYPES)
    surgery_date = validate.req_dt(body, "surgery_date")
    min_ecd = validate.req_int(body, "min_ecd", 500, 4000)
    max_age = validate.req_int(body, "max_donor_age_years", 0, 110)
    preference = validate.req_enum(body, "laterality_preference", LATERALITY_PREFERENCES)
    urgency = validate.req_enum(body, "urgency", URGENCIES)
    if surgeon is None:
        raise ApiError("ERR_INVALID_REQUEST", "surgeon_id must reference a surgeon.")

    if actor.is_surgeon and actor.user_id != surgeon["id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "A surgeon may only open their own requests."
        )

    if surgeon["credential_status"] != "ACTIVE":
        raise ApiError("ERR_SURGEON_NOT_CREDENTIALED", "The surgeon is not ACTIVE.")
    if surgery_date <= store.now():
        raise ApiError("ERR_SURGERY_DATE_IN_PAST", "surgery_date must be in the future.")

    row = store.base_row()
    row.update(
        {
            "surgeon_id": surgeon["id"],
            "procedure_type": procedure_type,
            "surgery_date": surgery_date,
            "min_ecd": min_ecd,
            "max_donor_age_years": max_age,
            "laterality_preference": preference,
            "urgency": urgency,
            "status": "OPEN",
            "base_score": 0,
            "priority_tier": "STANDARD",
            "priority_score": 0,
            "cancel_reason": None,
        }
    )
    calc.apply_priority(row)
    store.DB["requests"][row["id"]] = row
    return envelope.ok(serialize.surgeon_request(row), 201)


@bp.get("/eye-bank/surgeon-requests/<request_id>")
def get_surgeon_request(request_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    row = validate.lookup("requests", request_id)
    return envelope.ok(serialize.surgeon_request(row))


@bp.get("/eye-bank/surgeon-requests")
def list_requests():
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector"))
    rows = list(store.DB["requests"].values())
    surgeon_id = request.args.get("surgeon_id")
    if surgeon_id is not None:
        rows = [r for r in rows if r["surgeon_id"] == surgeon_id]
    status = request.args.get("status")
    if status is not None:
        validate.filter_enum("status", status, REQUEST_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    return envelope.paginated(request_sort(rows), serialize.surgeon_request)


@bp.post("/eye-bank/surgeon-requests/<request_id>/cancel")
def cancel_request(request_id):
    actor = auth.authenticate(("Surgeon", "EyeBankCoordinator"))
    req = validate.lookup("requests", request_id)
    body = auth.body_dict()
    cancel_reason = validate.req_str(body, "cancel_reason", 1, 500)

    if actor.is_surgeon and actor.user_id != req["surgeon_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "A surgeon may only cancel their own requests.")

    if req["status"] not in ("OPEN", "ALLOCATED"):
        raise ApiError(
            "ERR_REQUEST_STATE_INVALID", "Only an OPEN or ALLOCATED request may be cancelled."
        )

    live = cascade.live_allocation_for_request(request_id)
    if live is not None and live["status"] != "RESERVED":
        raise ApiError(
            "ERR_ALLOCATION_STATE_INVALID",
            "The request's allocation has already left RESERVED.",
        )

    req["cancel_reason"] = cancel_reason
    req["status"] = "CANCELLED"
    store.touch(req)

    if live is not None:
        cascade.cancel_reserved_allocation(live, "REQUEST_CANCELLED", reopen=False)
        tissue = store.DB["tissues"].get(live["tissue_id"])
        if tissue is not None and tissue["disposition_status"] == "RESERVED":
            tissue["disposition_status"] = "ELIGIBLE"
            store.touch(tissue)

    return envelope.ok(serialize.surgeon_request(req))
