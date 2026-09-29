"""Devices, network reports, call attempts and calling restrictions."""
from flask import Blueprint

import lookup
import store
import util
import validate as v
from common import (auth_for, body_or_error, bump, bump_if_changed, enum_filter,
                    guard_account_owner, list_response, new_entity, object_response,
                    pagination, paginate, sort_created_asc, sort_created_desc,
                    str_filter)
from errors import ApiError, invalid
from services import derive, fraud

bp = Blueprint("devices", __name__)

DEVICE_TYPES = ("BASE_STATION", "HANDSET", "SOFTPHONE")
REGISTRATION_STATUSES = ("PENDING_REGISTRATION", "ADDRESS_UNVERIFIED", "REGISTERED",
                         "RELOCATION_DETECTED", "SUSPENDED_911")
CALLING_STATUSES = ("UNRESTRICTED", "INTL_BLOCKED", "FULL_BLOCKED")
DECISIONS = ("ALLOWED", "BLOCKED_DEVICE", "BLOCKED_E911", "BLOCKED_INTL",
             "BLOCKED_FRAUD", "BLOCKED_SPEND_CAP")
RESTRICTION_ACTIONS = ("BLOCK_INTL", "BLOCK_ALL", "REVIEW_UNBLOCK")


def _held_reservations_of_number(number_id):
    rows = [r for r in store.number_reservations.values()
            if r["number_id"] == number_id and r["status"] == "HELD"]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
@bp.route("/voip/devices", methods=["POST"])
def create_device():
    user_id, role = auth_for(("AccountAdmin", "PlatformAdmin"))
    body = body_or_error()
    guard_account_owner(role, user_id, v.peek_str(body, "account_id"))
    account_id = v.req_id(body, "account_id")
    mac_address = v.req_str(body, "mac_address", exact_len=12, pattern=v.HEX_UPPER_RE)
    device_type = v.req_enum(body, "device_type", DEVICE_TYPES)
    nomadic = v.opt_bool(body, "nomadic", default=False)
    assigned_number_id = v.opt_id(body, "assigned_number_id")

    account = lookup.account(account_id)
    number = (lookup.phone_number(assigned_number_id)
              if assigned_number_id is not None else None)
    lookup.require_active(account)

    reservation = None
    if number is not None:
        if number["status"] not in ("AVAILABLE", "RESERVED"):
            raise ApiError("ERR_PHONE_NUMBER_STATE_INVALID",
                           "That number is not available to assign.")
        if number["status"] == "RESERVED":
            candidates = _held_reservations_of_number(number["id"])
            if not candidates:
                raise ApiError("ERR_RESERVATION_NOT_HELD",
                               "No HELD reservation stands behind that reserved number.")
            reservation = next(
                (r for r in candidates
                 if r["account_id"] == account["id"] and r["purpose"] == "NEW_LINE"),
                candidates[0])
            if reservation["account_id"] != account["id"]:
                raise ApiError("ERR_RESERVATION_ACCOUNT_MISMATCH",
                               "That reservation is earmarked for another account.")
            if reservation["purpose"] != "NEW_LINE":
                raise ApiError("ERR_RESERVATION_PURPOSE_INVALID",
                               "A device consumes a NEW_LINE reservation.")

    for existing in store.devices.values():
        if existing["mac_address"] == mac_address:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "A device with that mac_address already exists.")

    row = new_entity()
    row.update({
        "account_id": account["id"],
        "mac_address": mac_address,
        "device_type": device_type,
        "nomadic": nomadic,
        "assigned_number_id": number["id"] if number is not None else None,
        "registration_status": "PENDING_REGISTRATION",
        "calling_status": "UNRESTRICTED",
        "toll_fraud_score": 0,
        "fraud_block_count": 0,
        "last_network_report_at": None,
        "reported_state_code": None,
        "reported_postal_code": None,
        "registration_prompt_deadline": row["created_at"] + util.hours(
            derive.E911_PROMPT_GRACE_HOURS),
    })
    store.devices[row["id"]] = row

    if number is not None:
        if reservation is not None:
            reservation["status"] = "CONSUMED"
            bump(reservation)
        number["status"] = "ASSIGNED"
        number["assigned_account_id"] = account["id"]
        bump(number)
        block = store.number_blocks.get(number["block_id"])
        if block is not None:
            derive.recompute_census(block)
    derive.recompute_posture(account)
    return object_response(row, 201)


@bp.route("/voip/devices/<device_id>", methods=["GET"])
def get_device(device_id):
    user_id, role = auth_for(("AccountAdmin", "SecurityAnalyst", "E911Validator",
                              "PlatformAdmin"))
    row = lookup.device(device_id)
    guard_account_owner(role, user_id, row["account_id"])
    return object_response(row)


@bp.route("/voip/devices", methods=["GET"])
def list_devices():
    auth_for(("SecurityAnalyst", "E911Validator", "PlatformAdmin"))
    limit, offset = pagination()
    account_id = str_filter("account_id")
    assigned_number_id = str_filter("assigned_number_id")
    registration_status = enum_filter("registration_status", REGISTRATION_STATUSES)
    calling_status = enum_filter("calling_status", CALLING_STATUSES)
    rows = list(store.devices.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if assigned_number_id is not None:
        rows = [r for r in rows if r["assigned_number_id"] == assigned_number_id]
    if registration_status is not None:
        rows = [r for r in rows if r["registration_status"] == registration_status]
    if calling_status is not None:
        rows = [r for r in rows if r["calling_status"] == calling_status]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Network reports and relocation detection
# ---------------------------------------------------------------------------
def _drift_class(device, reported_state_code, reported_postal_code):
    registration = derive.current_registration(device["id"])
    if registration is None:
        return "NO_REGISTRATION", None
    if reported_postal_code == registration["postal_code"]:
        return "SAME_LOCATION", registration
    if reported_state_code == registration["state_code"]:
        return "INTRA_JURISDICTION", registration
    return "CROSS_JURISDICTION", registration


@bp.route("/voip/devices/<device_id>/network-reports", methods=["POST"])
def create_network_report(device_id):
    user_id, role = auth_for(("AccountAdmin", "PlatformAdmin"))
    device = lookup.device(device_id)
    guard_account_owner(role, user_id, device["account_id"])
    body = body_or_error()
    reported_state_code = v.req_str(body, "reported_state_code", exact_len=2,
                                   pattern=v.UPPER_ALPHA_RE)
    reported_postal_code = v.req_str(body, "reported_postal_code", exact_len=5,
                                     pattern=v.DIGITS_RE)

    drift, registration = _drift_class(device, reported_state_code, reported_postal_code)
    relocating = drift in ("INTRA_JURISDICTION", "CROSS_JURISDICTION")
    if relocating and not device["nomadic"]:
        raise ApiError("ERR_NON_NOMADIC_DEVICE_RELOCATION",
                       "A non-nomadic device may not report a relocation.")

    if drift == "NO_REGISTRATION":
        device["registration_status"] = "ADDRESS_UNVERIFIED"
    elif drift == "INTRA_JURISDICTION":
        if device["registration_status"] == "REGISTERED":
            device["registration_status"] = "ADDRESS_UNVERIFIED"
    elif drift == "CROSS_JURISDICTION":
        if device["registration_status"] == "REGISTERED":
            device["registration_status"] = "RELOCATION_DETECTED"

    if relocating and registration is not None and registration["verification_status"] == "VERIFIED":
        registration["verification_status"] = "STALE"
        bump(registration)

    device["reported_state_code"] = reported_state_code
    device["reported_postal_code"] = reported_postal_code
    device["last_network_report_at"] = store.now()
    bump(device)
    derive.recompute_posture(store.accounts.get(device["account_id"]))
    return object_response(device)


# ---------------------------------------------------------------------------
# Call attempts
# ---------------------------------------------------------------------------
def _persist_attempt(device, destination_e164, country_code, duration, minutes, rate,
                     base, decision, error_id, realtime=0, subtotal=0, pct=0,
                     projected=0):
    """Append the audit row.  It survives even when the caller sees an error."""
    row = new_entity(with_mutation_fields=False)
    row.update({
        "device_id": device["id"],
        "destination_e164": destination_e164,
        "destination_country_code": country_code,
        "requested_duration_seconds": duration,
        "billable_minutes": minutes,
        "rate_cents_per_minute": rate,
        "estimated_base_cents": base,
        "day_subtotal_cents": subtotal,
        "surcharge_pct_applied": pct,
        "projected_day_total_cents": projected,
        "realtime_risk_score": realtime,
        "decision": decision,
        "decision_error_id": error_id,
    })
    store.call_attempts[row["id"]] = row
    return row


@bp.route("/voip/devices/<device_id>/call-attempts", methods=["POST"])
def create_call_attempt(device_id):
    user_id, role = auth_for(("AccountAdmin", "PlatformAdmin"))
    device = lookup.device(device_id)
    guard_account_owner(role, user_id, device["account_id"])
    body = body_or_error()
    destination_e164 = v.req_str(body, "destination_e164", pattern=v.E164_DEST_RE)
    country_code = v.req_str(body, "destination_country_code", min_len=1, max_len=3,
                             pattern=v.DIGITS_RE)
    duration = v.req_int(body, "requested_duration_seconds", minimum=1, maximum=36000)
    if not destination_e164[1:].startswith(country_code):
        raise invalid("destination_country_code")

    account = store.accounts.get(device["account_id"])
    if account is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", "The device's account no longer exists.")
    lookup.require_active(account)

    minutes = fraud.billable_minutes(duration)
    rate = fraud.rate_for(country_code)
    base = rate * minutes
    domestic = country_code == "1"

    def refuse(decision, error_id, message, realtime=0, subtotal=0, pct=0, projected=0):
        _persist_attempt(device, destination_e164, country_code, duration, minutes,
                         rate, base, decision, error_id, realtime, subtotal, pct,
                         projected)
        raise ApiError(error_id, message)

    if device["calling_status"] == "FULL_BLOCKED":
        refuse("BLOCKED_DEVICE", "ERR_DEVICE_CALLING_BLOCKED",
               "The device is fully blocked from calling.")
    if device["registration_status"] == "SUSPENDED_911":
        refuse("BLOCKED_E911", "ERR_DEVICE_911_SUSPENDED",
               "The device is suspended for a rejected dispatchable location.")
    if account["e911_compliance_posture"] == "BLOCKED":
        refuse("BLOCKED_E911", "ERR_ACCOUNT_E911_BLOCKED",
               "The account's E911 compliance posture is BLOCKED.")
    if device["assigned_number_id"] is not None:
        registration = derive.current_registration(device["id"])
        if (registration is None
                or registration["verification_status"] not in ("VERIFIED", "STALE")):
            refuse("BLOCKED_E911", "ERR_E911_REGISTRATION_REQUIRED",
                   "A number-holding device needs a current dispatchable location.")
    if not domestic and not account["intl_calling_enabled"]:
        refuse("BLOCKED_INTL", "ERR_INTL_CALLING_DISABLED",
               "International calling is disabled on this account.")
    if not domestic and device["calling_status"] == "INTL_BLOCKED":
        refuse("BLOCKED_INTL", "ERR_INTL_BLOCKED_ON_DEVICE",
               "The device is blocked from international calling.")

    tracked = ("toll_fraud_score", "fraud_block_count", "calling_status")
    before = {field: device[field] for field in tracked}
    score = fraud.realtime_score(device, country_code)
    device["toll_fraud_score"] = score
    if score >= fraud.FRAUD_THRESHOLD:
        device["fraud_block_count"] = device["fraud_block_count"] + 1
        if device["fraud_block_count"] >= fraud.FULL_BLOCK_AT_FRAUD_BLOCKS:
            device["calling_status"] = "FULL_BLOCKED"
        elif device["calling_status"] == "UNRESTRICTED":
            device["calling_status"] = "INTL_BLOCKED"
        bump_if_changed(device, before, tracked)
        refuse("BLOCKED_FRAUD", "ERR_TOLL_FRAUD_THRESHOLD_BREACHED",
               "The real-time toll-fraud score is at or above the threshold.",
               realtime=score)
    bump_if_changed(device, before, tracked)

    subtotal = pct = projected = 0
    if not domestic:
        subtotal, pct, projected = fraud.spend_projection(account, base)
        if projected > account["intl_daily_cap_cents"]:
            refuse("BLOCKED_SPEND_CAP", "ERR_INTL_SPEND_CAP_EXCEEDED",
                   "The projected daily international spend exceeds the cap.",
                   realtime=score, subtotal=subtotal, pct=pct, projected=projected)

    row = _persist_attempt(device, destination_e164, country_code, duration, minutes,
                           rate, base, "ALLOWED", None, score, subtotal, pct, projected)
    return object_response(row, 201)


@bp.route("/voip/devices/<device_id>/call-attempts", methods=["GET"])
def list_call_attempts(device_id):
    user_id, role = auth_for(("AccountAdmin", "SecurityAnalyst", "PlatformAdmin"))
    device = lookup.device(device_id)
    guard_account_owner(role, user_id, device["account_id"])
    limit, offset = pagination()
    decision = enum_filter("decision", DECISIONS)
    rows = [a for a in store.call_attempts.values() if a["device_id"] == device["id"]]
    if decision is not None:
        rows = [a for a in rows if a["decision"] == decision]
    rows = sort_created_desc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Calling restrictions
# ---------------------------------------------------------------------------
@bp.route("/voip/devices/<device_id>/calling-restrictions", methods=["POST"])
def apply_calling_restriction(device_id):
    auth_for(("SecurityAnalyst",))
    device = lookup.device(device_id)
    body = body_or_error()
    action = v.req_enum(body, "action", RESTRICTION_ACTIONS)
    v.opt_free_text(body, "note")

    if action == "REVIEW_UNBLOCK":
        score = fraud.daily_review_score(device)
        registration = derive.current_registration(device["id"])
        device["toll_fraud_score"] = score
        if (registration is None or registration["verification_status"] != "VERIFIED"
                or score >= fraud.FRAUD_THRESHOLD):
            raise ApiError("ERR_UNBLOCK_REVIEW_SCORE_TOO_HIGH",
                           "The review gates for an unblock are not satisfied.")
        device["calling_status"] = "UNRESTRICTED"
        device["fraud_block_count"] = 0
    elif action == "BLOCK_INTL":
        if device["calling_status"] == "UNRESTRICTED":
            device["calling_status"] = "INTL_BLOCKED"
    else:
        if device["calling_status"] != "FULL_BLOCKED":
            device["calling_status"] = "FULL_BLOCKED"
    bump(device)
    return object_response(device)
