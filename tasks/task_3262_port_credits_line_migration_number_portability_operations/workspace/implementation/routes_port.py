"""Routes: port-in requests, carrier rejections and resubmission."""

from flask import Blueprint, request

import clock
import errors
import lookups
import middleware
import models
import response
import routes_system
import storage

bp = Blueprint("port", __name__, url_prefix="/portability")

WRITERS = ("PlatformAdmin", "CustomerService")


def _is_four_digits(value):
    return isinstance(value, str) and len(value) == 4 and value.isdigit()


def _check_transfer_credentials(data, port_request):
    """transfer_pin format and pairing with the request's stored credentials.

    PRD 3.2: resubmission "takes the same `transfer_pin` and
    `account_number_at_losing_carrier` the submission took", so the presented pair
    must reproduce the pair carried on the request. A four-digit pin that
    disagrees with the request, or an account number that disagrees with the
    request, is rejected with ERR_TRANSFER_PIN_MISMATCH (422).
    """
    pin = data.get("transfer_pin")
    acct = data.get("account_number_at_losing_carrier")
    if not _is_four_digits(pin):
        errors.fail("ERR_TRANSFER_PIN_MISMATCH",
                    "transfer_pin must be exactly 4 digits.")
    if pin != port_request["transfer_pin"]:
        errors.fail("ERR_TRANSFER_PIN_MISMATCH",
                    "transfer_pin does not agree with the credentials on the port request.")
    if acct is None:
        errors.fail("ERR_INVALID_REQUEST",
                    "Field 'account_number_at_losing_carrier' is required.")
    if acct != port_request["account_number_at_losing_carrier"]:
        errors.fail("ERR_TRANSFER_PIN_MISMATCH",
                    "account_number_at_losing_carrier does not agree with the port request.")


def _check_protection(line):
    if line["port_protection_status"] == "PROTECTED":
        errors.fail("ERR_PORT_PROTECTION_ACTIVE",
                    "The line carries an active port-out protection case.")


def _check_mdn_already_reserved(port_request, line):
    holder = models.mdn_held_reserved(line["mdn"], exclude_line_id=line["id"])
    if holder is not None:
        errors.fail("ERR_MDN_ALREADY_RESERVED",
                    "Another line already holds this number as RESERVED.")


# ---------------------------------------------------------------------------
@bp.post("/port-requests")
@middleware.require_roles(*WRITERS)
def create_port_request(caller):
    data = middleware.body()
    line_id = middleware.required_str(data, "subscriber_line_id")
    line = lookups.line(line_id)
    middleware.require_expected_line_version(data, line)

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "subscriber_line_id": line_id,
        "losing_carrier_code": middleware.required_str(data, "losing_carrier_code"),
        "account_number_at_losing_carrier": middleware.required_str(
            data, "account_number_at_losing_carrier"),
        "transfer_pin": middleware.required_str(data, "transfer_pin"),
        "requested_cutover_at": clock.fmt(
            middleware.optional_instant(data, "requested_cutover_at")),
        "request_state": "DRAFT",
        "rejection_count": 0,
        "last_rejection_code": None,
        "rejections": [],
        "last_rejection_at": None,
        "submitted_at": None,
        "supersedes_port_request_id": middleware.optional_str(
            data, "supersedes_port_request_id", None),
        "cutover_completed_at": None,
    }
    if record["requested_cutover_at"] is None:
        errors.fail("ERR_INVALID_REQUEST",
                    "Field 'requested_cutover_at' is required.")
    storage.db.add("port_requests", record)

    models.touch(line)
    return response.ok(models.port_request_out(record), 201)


@bp.get("/port-requests/<request_id>")
@middleware.require_roles("PlatformAdmin", "CustomerService", "CreditAnalyst", "Customer")
def get_port_request(caller, request_id):
    record = lookups.port_request(request_id)
    line = lookups.line(record["subscriber_line_id"])
    middleware.enforce_ownership(caller, line["account_id"])
    return response.ok(models.port_request_out(record))


@bp.get("/subscriber-lines/<line_id>/port-requests")
@middleware.require_roles("PlatformAdmin", "CustomerService", "CreditAnalyst", "Customer")
def list_line_port_requests(caller, line_id):
    line = lookups.line(line_id)
    middleware.enforce_ownership(caller, line["account_id"])
    rows = [
        r for r in storage.db.all("port_requests") if r["subscriber_line_id"] == line_id
    ]
    supersedes = request.args.get("supersedes_port_request_id")
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_port_request_id"] == supersedes]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.port_request_out(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
@bp.post("/port-requests/<request_id>/submit")
@middleware.require_roles(*WRITERS)
def submit_port_request(caller, request_id):
    record = lookups.port_request(request_id)
    line = lookups.line(record["subscriber_line_id"])

    if record["request_state"] != "DRAFT":
        errors.fail("ERR_INVALID_STATE", "Only a DRAFT port request can be submitted.")
    _check_protection(line)
    _check_transfer_credentials(middleware.body(), record)

    if line["number_status"] not in ("UNASSIGNED", "RESERVED"):
        errors.fail("ERR_INVALID_STATE",
                    "The line's number_status does not permit submission.")

    cutover = clock.parse_instant(record["requested_cutover_at"])
    if cutover is None or cutover < clock.now():
        errors.fail("ERR_INVALID_STATE",
                    "requested_cutover_at is before the current logical clock instant.")

    _check_mdn_already_reserved(record, line)

    record["request_state"] = "PENDING"
    record["submitted_at"] = clock.fmt_now()
    models.touch(record)
    line["number_status"] = "RESERVED"
    models.touch(line)
    return response.ok(models.port_request_out(record))


@bp.post("/port-requests/<request_id>/rejections")
@middleware.require_roles("PlatformAdmin")
def record_rejection(caller, request_id):
    data = middleware.body()
    record = lookups.port_request(request_id)

    if record["request_state"] != "PENDING":
        errors.fail("ERR_INVALID_STATE", "Only a PENDING port request can be rejected.")

    code = data.get("rejection_code")
    if not isinstance(code, str) or code == "":
        errors.fail("ERR_INVALID_REQUEST", "Field 'rejection_code' is required.")
    catalog_row = routes_system.get_catalog(code)
    if catalog_row is None:
        errors.fail("ERR_REJECTION_CODE_NOT_FOUND",
                    "The supplied rejection_code matches no catalog row.")

    occurred_at = clock.fmt_now()
    entry = {
        "rejection_code": catalog_row["rejection_code"],
        "guidance_text": catalog_row["guidance_text"],
        "resubmission_allowed": catalog_row["resubmission_allowed"],
        "retry_after_hours": catalog_row["retry_after_hours"],
        "occurred_at": occurred_at,
    }
    record["rejections"].append(entry)
    record["rejection_count"] = len(record["rejections"])
    record["last_rejection_code"] = catalog_row["rejection_code"]
    record["last_rejection_at"] = occurred_at
    record["request_state"] = "REJECTED"
    models.touch(record)

    line = lookups.line(record["subscriber_line_id"])
    line["number_status"] = "UNASSIGNED"
    models.touch(line)
    return response.ok(entry, 201)


@bp.post("/port-requests/<request_id>/resubmit")
@middleware.require_roles(*WRITERS)
def resubmit_port_request(caller, request_id):
    record = lookups.port_request(request_id)
    line = lookups.line(record["subscriber_line_id"])

    if record["request_state"] != "REJECTED":
        errors.fail("ERR_INVALID_STATE", "Only a REJECTED port request can be resubmitted.")
    _check_protection(line)
    _check_transfer_credentials(middleware.body(), record)

    catalog_row = routes_system.get_catalog(record["last_rejection_code"])
    if catalog_row is None or not catalog_row["resubmission_allowed"]:
        errors.fail("ERR_RESUBMISSION_NOT_ALLOWED",
                    "The most recent rejection code does not allow resubmission.")

    last_at = clock.parse_instant(record["last_rejection_at"])
    eligible_at = clock.add_hours(last_at, catalog_row["retry_after_hours"])
    if clock.now() < eligible_at:
        errors.fail("ERR_RESUBMISSION_COOLDOWN",
                    "The cooling-off period has not elapsed.")

    _check_mdn_already_reserved(record, line)

    record["request_state"] = "RESUBMITTED"
    record["submitted_at"] = clock.fmt_now()
    models.touch(record)

    line["number_status"] = "RESERVED"
    if line["billing_mode"] == "PREPAID":
        line["retention_cycle_count"] = line["retention_cycle_count"] + 1
    models.touch(line)

    # Conditional declared side effect: a PROTECTED line is cleared on resubmission.
    if line["port_protection_status"] == "PROTECTED":
        for case in storage.db.all("port_protection_cases"):
            if case["subscriber_line_id"] == line["id"] and case["case_state"] == "ACTIVE":
                case["case_state"] = "CLEARED"
                case["cleared_at"] = clock.fmt_now()
                models.touch(case)
        line["port_protection_status"] = "UNPROTECTED"
        models.touch(line)

    return response.ok(models.port_request_out(record))


@bp.post("/port-requests/<request_id>/accept")
@middleware.require_roles("PlatformAdmin")
def accept_port_request(caller, request_id):
    record = lookups.port_request(request_id)

    if record["request_state"] not in ("PENDING", "RESUBMITTED"):
        errors.fail("ERR_INVALID_STATE",
                    "Only a PENDING or RESUBMITTED request can be accepted.")

    cutover = clock.parse_instant(record["requested_cutover_at"])
    if cutover is None or cutover < clock.now():
        errors.fail("ERR_INVALID_STATE",
                    "requested_cutover_at is before the current logical clock instant.")

    record["request_state"] = "ACCEPTED_PENDING_CUTOVER"
    models.touch(record)
    return response.ok(models.port_request_out(record))


@bp.post("/port-requests/<request_id>/cancel")
@middleware.require_roles(*WRITERS)
def cancel_port_request(caller, request_id):
    record = lookups.port_request(request_id)
    state = record["request_state"]

    if state == "PENDING":
        record["request_state"] = "CANCELLED"
        models.touch(record)
        line = lookups.line(record["subscriber_line_id"])
        line["number_status"] = "UNASSIGNED"
        models.touch(line)
    elif state == "REJECTED":
        if record["rejection_count"] < 3:
            errors.fail("ERR_INVALID_STATE",
                        "A rejected request may only be cancelled after three rejections.")
        record["request_state"] = "CANCELLED"
        models.touch(record)
    else:
        errors.fail("ERR_INVALID_STATE",
                    "Only a PENDING or REJECTED request can be cancelled.")

    return response.ok(models.port_request_out(record))