"""Port requests, CSR snapshots, cutover calendars and temporary bridges."""
from flask import Blueprint

import lookup
import store
import validate as v
from common import (auth_for, body_or_error, bump, enum_filter, guard_account_owner,
                    list_response, new_entity, object_response, optional_body,
                    pagination, paginate, sort_created_asc, sort_created_desc,
                    str_filter)
from errors import ApiError
from services import derive, porting

bp = Blueprint("porting", __name__)

PORT_REQUEST_STATUSES = ("SUBMITTED", "CSR_MISMATCH", "VALIDATED", "SCHEDULED",
                         "BRIDGED", "REJECTED", "COMPLETED", "CANCELLED")
CLAIMING_STATUSES = ("SUBMITTED", "CSR_MISMATCH", "VALIDATED", "SCHEDULED",
                     "BRIDGED", "REJECTED")
RESUBMITTABLE_FROM = ("CSR_MISMATCH", "REJECTED")
REJECTABLE_FROM = ("SUBMITTED", "CSR_MISMATCH", "VALIDATED", "SCHEDULED", "BRIDGED")
CANCELLABLE_FROM = CLAIMING_STATUSES
SLOT_STATUSES = ("OPEN", "BOOKED", "CONSUMED", "RELEASED")
BRIDGE_STATUSES = ("PROVISIONED", "ACTIVE", "RELEASED", "ORPHANED")


def _read_claims(body):
    return {
        "claimed_account_number": v.req_str(body, "claimed_account_number",
                                           min_len=1, max_len=32),
        "claimed_pin": v.req_str(body, "claimed_pin", min_len=1, max_len=16),
        "claimed_billing_name": v.req_str(body, "claimed_billing_name",
                                          min_len=1, max_len=80),
        "claimed_address_line1": v.req_str(body, "claimed_address_line1",
                                           min_len=1, max_len=80),
        "claimed_zip": v.req_str(body, "claimed_zip", exact_len=5, pattern=v.DIGITS_RE),
    }


# ---------------------------------------------------------------------------
# Port requests
# ---------------------------------------------------------------------------
@bp.route("/voip/port-requests", methods=["POST"])
def create_port_request():
    user_id, role = auth_for(("PortingSpecialist", "AccountAdmin"))
    body = body_or_error()
    guard_account_owner(role, user_id, v.peek_str(body, "account_id"))
    account_id = v.req_id(body, "account_id")
    losing_carrier_id = v.req_id(body, "losing_carrier_id")
    requested_numbers = v.req_ported_numbers(body, "requested_numbers")
    claims = _read_claims(body)

    account = lookup.account(account_id)
    lookup.carrier(losing_carrier_id)
    lookup.require_active(account)

    claimed = set(requested_numbers)
    for other in store.port_requests.values():
        if other["account_id"] != account["id"]:
            continue
        if other["status"] not in CLAIMING_STATUSES:
            continue
        if claimed.intersection(other["requested_numbers"]):
            raise ApiError("ERR_ACTIVE_PORT_REQUEST_EXISTS",
                           "Another live port request of this account claims that number.")

    row = new_entity()
    row.update({
        "account_id": account["id"],
        "losing_carrier_id": losing_carrier_id,
        "requested_numbers": requested_numbers,
        "status": "SUBMITTED",
        "resubmission_count": 0,
        "last_rejection_code": None,
        "last_match_points": None,
        "last_mismatch_fields": [],
        "validated_at": None,
        "earliest_cutover_at": None,
        "created_by_user_id": user_id,
    })
    row.update(claims)
    store.port_requests[row["id"]] = row
    return object_response(row, 201)


@bp.route("/voip/port-requests/<port_request_id>", methods=["GET"])
def get_port_request(port_request_id):
    user_id, role = auth_for(("PortingSpecialist", "CarrierLiaison", "PlatformAdmin",
                              "AccountAdmin"))
    row = lookup.port_request(port_request_id)
    guard_account_owner(role, user_id, row["account_id"])
    return object_response(row)


@bp.route("/voip/port-requests", methods=["GET"])
def list_port_requests():
    auth_for(("PortingSpecialist", "CarrierLiaison", "PlatformAdmin"))
    limit, offset = pagination()
    account_id = str_filter("account_id")
    losing_carrier_id = str_filter("losing_carrier_id")
    status = enum_filter("status", PORT_REQUEST_STATUSES)
    rows = list(store.port_requests.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if losing_carrier_id is not None:
        rows = [r for r in rows if r["losing_carrier_id"] == losing_carrier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# CSR snapshots
# ---------------------------------------------------------------------------
@bp.route("/voip/port-requests/<port_request_id>/csr-snapshots", methods=["POST"])
def create_csr_snapshot(port_request_id):
    user_id, _role = auth_for(("CarrierLiaison",))
    body = body_or_error()
    values = {
        "account_number_on_file": v.req_str(body, "account_number_on_file",
                                            min_len=1, max_len=32),
        "pin_on_file": v.req_str(body, "pin_on_file", min_len=1, max_len=16),
        "billing_name_on_file": v.req_str(body, "billing_name_on_file",
                                          min_len=1, max_len=80),
        "address_line1_on_file": v.req_str(body, "address_line1_on_file",
                                           min_len=1, max_len=80),
        "zip_on_file": v.req_str(body, "zip_on_file", exact_len=5, pattern=v.DIGITS_RE),
    }
    expected_version = v.req_int(body, "expected_port_request_version")

    port_request = lookup.port_request(port_request_id)
    if port_request["status"] != "SUBMITTED":
        raise ApiError("ERR_PORT_REQUEST_STATE_INVALID",
                       "A carrier record may only be transcribed onto a SUBMITTED request.")
    if expected_version != port_request["version"]:
        raise ApiError("ERR_STALE_PORT_REQUEST_VERSION",
                       "The port request has moved on since it was read.")
    if user_id == port_request["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                       "The filing principal may not transcribe the carrier's record.")

    carrier = lookup.carrier(port_request["losing_carrier_id"])
    match_points, threshold, match_status, mismatch_fields = porting.evaluate_csr(
        port_request, values, carrier)

    porting.supersede_current_snapshot(port_request["id"])

    row = new_entity()
    row["port_request_id"] = port_request["id"]
    row.update(values)
    row.update({
        "match_points": match_points,
        "threshold_applied": threshold,
        "match_status": match_status,
        "mismatch_fields": mismatch_fields,
        "superseded_at": None,
    })
    store.csr_snapshots[row["id"]] = row

    port_request["last_match_points"] = match_points
    port_request["last_mismatch_fields"] = list(mismatch_fields)
    if match_status == "MATCHED":
        port_request["status"] = "VALIDATED"
        port_request["validated_at"] = store.now()
        port_request["earliest_cutover_at"] = porting.earliest_cutover_floor(
            port_request["validated_at"], carrier["foc_business_days"])
    else:
        port_request["status"] = "CSR_MISMATCH"
    bump(port_request)
    return object_response(row, 201)


@bp.route("/voip/port-requests/<port_request_id>/csr-snapshots", methods=["GET"])
def list_csr_snapshots(port_request_id):
    auth_for(("PortingSpecialist", "CarrierLiaison", "PlatformAdmin"))
    limit, offset = pagination()
    port_request = lookup.port_request(port_request_id)
    rows = [s for s in store.csr_snapshots.values()
            if s["port_request_id"] == port_request["id"]]
    rows = sort_created_desc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Correction, rejection and cancellation
# ---------------------------------------------------------------------------
@bp.route("/voip/port-requests/<port_request_id>/resubmit", methods=["POST"])
def resubmit_port_request(port_request_id):
    user_id, role = auth_for(("PortingSpecialist", "AccountAdmin"))
    port_request = lookup.port_request(port_request_id)
    guard_account_owner(role, user_id, port_request["account_id"])
    body = body_or_error()
    claims = _read_claims(body)

    if port_request["status"] not in RESUBMITTABLE_FROM:
        raise ApiError("ERR_PORT_REQUEST_STATE_INVALID",
                       "Only a CSR_MISMATCH or REJECTED request may be resubmitted.")
    if (port_request["status"] == "REJECTED"
            and port_request["last_rejection_code"] not in porting.RESUBMITTABLE_REJECTION_CODES):
        raise ApiError("ERR_REJECTION_NOT_RESUBMITTABLE",
                       "That rejection reason can never be resubmitted.")
    if port_request["resubmission_count"] >= porting.MAX_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED",
                       "The resubmission budget for this request is exhausted.")

    port_request.update(claims)
    port_request["resubmission_count"] = port_request["resubmission_count"] + 1
    port_request["status"] = "SUBMITTED"
    port_request["last_match_points"] = None
    port_request["last_mismatch_fields"] = []
    port_request["validated_at"] = None
    port_request["earliest_cutover_at"] = None
    port_request["last_rejection_code"] = None
    porting.supersede_current_snapshot(port_request["id"])
    bump(port_request)
    return object_response(port_request)


@bp.route("/voip/port-requests/<port_request_id>/reject", methods=["POST"])
def reject_port_request(port_request_id):
    user_id, _role = auth_for(("CarrierLiaison",))
    body = body_or_error()
    reason_code = v.req_enum(body, "reason_code", porting.REJECTION_CODES)
    v.opt_free_text(body, "note")

    port_request = lookup.port_request(port_request_id)
    if port_request["status"] not in REJECTABLE_FROM:
        raise ApiError("ERR_PORT_REQUEST_STATE_INVALID",
                       "This request is not in a rejectable status.")
    if user_id == port_request["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                       "The filing principal may not record the carrier's rejection.")

    port_request["status"] = "REJECTED"
    port_request["last_rejection_code"] = reason_code
    bump(port_request)
    porting.unwind_cascade(port_request)
    return object_response(port_request)


@bp.route("/voip/port-requests/<port_request_id>/cancel", methods=["POST"])
def cancel_port_request(port_request_id):
    user_id, role = auth_for(("PortingSpecialist", "AccountAdmin"))
    port_request = lookup.port_request(port_request_id)
    guard_account_owner(role, user_id, port_request["account_id"])
    body = optional_body()
    v.opt_free_text(body, "reason_note")

    if port_request["status"] not in CANCELLABLE_FROM:
        raise ApiError("ERR_PORT_REQUEST_STATE_INVALID",
                       "A COMPLETED or CANCELLED request cannot be cancelled.")
    port_request["status"] = "CANCELLED"
    bump(port_request)
    porting.unwind_cascade(port_request)
    return object_response(port_request)


# ---------------------------------------------------------------------------
# Booking and completion
# ---------------------------------------------------------------------------
@bp.route("/voip/port-requests/<port_request_id>/schedule", methods=["POST"])
def schedule_port_request(port_request_id):
    auth_for(("PortingSpecialist",))
    body = body_or_error()
    cutover_slot_id = v.req_id(body, "cutover_slot_id")

    port_request = lookup.port_request(port_request_id)
    slot = lookup.cutover_slot(cutover_slot_id)

    if port_request["status"] != "VALIDATED":
        raise ApiError("ERR_PORT_REQUEST_NOT_SCHEDULABLE",
                       "Only a VALIDATED port request can be scheduled.")
    if slot["status"] != "OPEN":
        raise ApiError("ERR_SLOT_NOT_OPEN", "That cutover slot is not OPEN.")
    account = store.accounts.get(port_request["account_id"])
    if account is not None and account["e911_compliance_posture"] == "BLOCKED":
        raise ApiError("ERR_ACCOUNT_E911_BLOCKED",
                       "The account's E911 compliance posture is BLOCKED.")
    if slot["carrier_id"] != port_request["losing_carrier_id"]:
        raise ApiError("ERR_SLOT_CARRIER_MISMATCH",
                       "That slot belongs to another carrier's calendar.")
    if (port_request["earliest_cutover_at"] is not None
            and slot["window_start"] < port_request["earliest_cutover_at"]):
        raise ApiError("ERR_CUTOVER_BEFORE_FOC",
                       "The window starts before the firm-order-commitment floor.")

    port_request["status"] = "SCHEDULED"
    bump(port_request)
    slot["status"] = "BOOKED"
    slot["booked_port_request_id"] = port_request["id"]
    slot["booked_at"] = store.now()
    bump(slot)
    return object_response(port_request)


@bp.route("/voip/port-requests/<port_request_id>/complete-cutover", methods=["POST"])
def complete_cutover(port_request_id):
    auth_for(("PortingSpecialist",))
    optional_body()
    port_request = lookup.port_request(port_request_id)
    if port_request["status"] not in ("BRIDGED", "SCHEDULED"):
        raise ApiError("ERR_PORT_REQUEST_STATE_INVALID",
                       "Completion is permitted only from SCHEDULED or BRIDGED.")
    if (port_request["status"] == "SCHEDULED"
            and porting.live_bridges_for(port_request["id"])):
        raise ApiError("ERR_PORT_REQUEST_STATE_INVALID",
                       "An unresolved bridge must be settled before completion.")

    port_request["status"] = "COMPLETED"
    bump(port_request)
    porting.complete_cascade(port_request)
    derive.recompute_ported_number_count(store.accounts.get(port_request["account_id"]))
    return object_response(port_request)


# ---------------------------------------------------------------------------
# Cutover slots
# ---------------------------------------------------------------------------
@bp.route("/voip/cutover-slots", methods=["POST"])
def create_cutover_slot():
    auth_for(("PortingSpecialist",))
    body = body_or_error()
    carrier_id = v.req_id(body, "carrier_id")
    window_start = v.req_instant(body, "window_start")
    window_end = v.req_instant(body, "window_end")
    carrier = lookup.carrier(carrier_id)

    porting.check_window_length(window_start, window_end)
    porting.check_slot_overlap(carrier, window_start, window_end)

    row = new_entity()
    row.update({
        "carrier_id": carrier["id"],
        "window_start": window_start,
        "window_end": window_end,
        "status": "OPEN",
        "booked_port_request_id": None,
        "booked_at": None,
    })
    store.cutover_slots[row["id"]] = row
    return object_response(row, 201)


@bp.route("/voip/cutover-slots/<slot_id>", methods=["GET"])
def get_cutover_slot(slot_id):
    auth_for(("PortingSpecialist", "CarrierLiaison", "PlatformAdmin"))
    return object_response(lookup.cutover_slot(slot_id))


@bp.route("/voip/cutover-slots", methods=["GET"])
def list_cutover_slots():
    auth_for(("PortingSpecialist", "CarrierLiaison", "PlatformAdmin"))
    limit, offset = pagination()
    carrier_id = str_filter("carrier_id")
    booked_port_request_id = str_filter("booked_port_request_id")
    status = enum_filter("status", SLOT_STATUSES)
    rows = list(store.cutover_slots.values())
    if carrier_id is not None:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    if booked_port_request_id is not None:
        rows = [r for r in rows
                if r["booked_port_request_id"] == booked_port_request_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Temporary bridges
# ---------------------------------------------------------------------------
@bp.route("/voip/temporary-bridges", methods=["POST"])
def create_temporary_bridge():
    auth_for(("PortingSpecialist",))
    body = body_or_error()
    port_request_id = v.req_id(body, "port_request_id")
    reservation_id = v.req_id(body, "reservation_id")

    port_request = lookup.port_request(port_request_id)
    reservation = lookup.reservation(reservation_id)

    if (port_request["status"] != "SCHEDULED"
            or porting.booked_slot_for(port_request["id"]) is None):
        raise ApiError("ERR_BRIDGE_SLOT_NOT_BOOKED",
                       "A bridge needs a SCHEDULED request with a BOOKED slot.")
    if reservation["status"] != "HELD":
        raise ApiError("ERR_RESERVATION_NOT_HELD",
                       "Only a HELD reservation can be consumed by a bridge.")
    if reservation["account_id"] != port_request["account_id"]:
        raise ApiError("ERR_RESERVATION_ACCOUNT_MISMATCH",
                       "That reservation belongs to another account.")
    if reservation["purpose"] != "PORT_BRIDGE":
        raise ApiError("ERR_RESERVATION_PURPOSE_INVALID",
                       "A bridge consumes a PORT_BRIDGE reservation.")

    reservation["status"] = "CONSUMED"
    bump(reservation)

    row = new_entity()
    row.update({
        "port_request_id": port_request["id"],
        "reservation_id": reservation["id"],
        "bridge_number_id": reservation["number_id"],
        "status": "PROVISIONED",
        "activated_at": None,
        "released_at": None,
    })
    store.temporary_bridges[row["id"]] = row
    return object_response(row, 201)


@bp.route("/voip/temporary-bridges/<bridge_id>/activate", methods=["POST"])
def activate_temporary_bridge(bridge_id):
    auth_for(("PortingSpecialist",))
    optional_body()
    bridge = lookup.temporary_bridge(bridge_id)
    if bridge["status"] != "PROVISIONED":
        raise ApiError("ERR_BRIDGE_STATE_INVALID",
                       "Only a PROVISIONED bridge can be activated.")
    slot = porting.booked_slot_for(bridge["port_request_id"])
    now = store.now()
    if slot is None or not (slot["window_start"] <= now < slot["window_end"]):
        raise ApiError("ERR_BRIDGE_ACTIVATION_OUTSIDE_WINDOW",
                       "The logical clock is outside the booked cutover window.")

    bridge["status"] = "ACTIVE"
    bridge["activated_at"] = now
    bump(bridge)
    port_request = store.port_requests.get(bridge["port_request_id"])
    if port_request is not None:
        port_request["status"] = "BRIDGED"
        bump(port_request)
    return object_response(bridge)


@bp.route("/voip/temporary-bridges/<bridge_id>", methods=["GET"])
def get_temporary_bridge(bridge_id):
    auth_for(("PortingSpecialist", "PlatformAdmin"))
    return object_response(lookup.temporary_bridge(bridge_id))


@bp.route("/voip/temporary-bridges", methods=["GET"])
def list_temporary_bridges():
    auth_for(("PortingSpecialist", "PlatformAdmin"))
    limit, offset = pagination()
    port_request_id = str_filter("port_request_id")
    reservation_id = str_filter("reservation_id")
    bridge_number_id = str_filter("bridge_number_id")
    status = enum_filter("status", BRIDGE_STATUSES)
    rows = list(store.temporary_bridges.values())
    if port_request_id is not None:
        rows = [r for r in rows if r["port_request_id"] == port_request_id]
    if reservation_id is not None:
        rows = [r for r in rows if r["reservation_id"] == reservation_id]
    if bridge_number_id is not None:
        rows = [r for r in rows if r["bridge_number_id"] == bridge_number_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
