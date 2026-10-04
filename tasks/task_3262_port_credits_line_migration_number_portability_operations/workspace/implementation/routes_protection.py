"""Routes: port-out protection cases."""

from flask import Blueprint, request

import clock
import errors
import lookups
import middleware
import models
import response
import storage

bp = Blueprint("protection", __name__, url_prefix="/portability")

PROTECTION_TYPES = ("ACCOUNT_PIN", "PORT_FREEZE", "FRAUD_HOLD")
READERS = ("PlatformAdmin", "CustomerService", "CreditAnalyst")
WRITERS = ("PlatformAdmin", "CustomerService")


@bp.post("/port-protection-cases")
@middleware.require_roles(*WRITERS)
def create_protection_case(caller):
    data = middleware.body()
    line_id = middleware.required_str(data, "subscriber_line_id")
    lookups.line(line_id)

    protection_type = middleware.required_str(data, "protection_type")
    if protection_type not in PROTECTION_TYPES:
        errors.fail("ERR_INVALID_REQUEST", "protection_type is not a recognized value.")

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "subscriber_line_id": line_id,
        "protection_type": protection_type,
        "verified_identity": middleware.optional_bool(data, "verified_identity", False),
        "case_state": "REQUESTED",
        "set_at": None,
        "cleared_at": None,
        "reason_code": middleware.required_str(data, "reason_code"),
    }
    # Opening a case changes nothing about the line; the freeze only takes effect
    # on an activation.
    storage.db.add("port_protection_cases", record)
    return response.ok(models.protection_out(record), 201)


@bp.get("/port-protection-cases")
@middleware.require_roles(*READERS)
def list_protection_cases(caller):
    rows = storage.db.all("port_protection_cases")

    line_filter = request.args.get("subscriber_line_id")
    if line_filter is not None:
        rows = [c for c in rows if c["subscriber_line_id"] == line_filter]

    state_filter = request.args.get("case_state")
    if state_filter is not None:
        rows = [c for c in rows if c["case_state"] == state_filter]

    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.protection_out(r) for r in page], limit, offset, total)


@bp.post("/port-protection-cases/<case_id>/resolve")
@middleware.require_roles("PlatformAdmin")
def resolve_protection_case(caller, case_id):
    data = middleware.body()
    case = lookups.protection_case(case_id)

    resolution = data.get("resolution")
    if resolution not in ("ACTIVATE", "DENY", "CLEAR"):
        errors.fail("ERR_INVALID_REQUEST", "resolution must be ACTIVATE, DENY or CLEAR.")

    line = lookups.line(case["subscriber_line_id"])

    if resolution == "ACTIVATE":
        if case["case_state"] != "REQUESTED":
            errors.fail("ERR_INVALID_STATE", "Only a REQUESTED case can be activated.")
        if not case["verified_identity"]:
            errors.fail("ERR_IDENTITY_NOT_VERIFIED",
                        "The requesting party has not passed identity verification.")
        if models.has_active_protection(line["id"]):
            errors.fail("ERR_PROTECTION_ALREADY_ACTIVE",
                        "Another protection case on this line is already ACTIVE.")
        case["case_state"] = "ACTIVE"
        case["set_at"] = clock.fmt_now()
        models.touch(case)
        line["port_protection_status"] = "PROTECTED"
        models.touch(line)

    elif resolution == "DENY":
        if case["case_state"] != "REQUESTED":
            errors.fail("ERR_INVALID_STATE", "Only a REQUESTED case can be denied.")
        case["case_state"] = "DENIED"
        models.touch(case)

    else:  # CLEAR
        if case["case_state"] != "ACTIVE":
            errors.fail("ERR_INVALID_STATE", "Only an ACTIVE case can be cleared.")
        case["case_state"] = "CLEARED"
        case["cleared_at"] = clock.fmt_now()
        case["set_at"] = None
        models.touch(case)
        line["port_protection_status"] = "UNPROTECTED"
        models.touch(line)

        # Clearing a freeze does not bless an in-flight port request.
        for port_request in storage.db.all("port_requests"):
            if port_request["subscriber_line_id"] != line["id"]:
                continue
            if port_request["request_state"] == "RESUBMITTED":
                port_request["request_state"] = "REJECTED"
                models.touch(port_request)
                line["number_status"] = "UNASSIGNED"
                models.touch(line)

    return response.ok(models.protection_out(case))