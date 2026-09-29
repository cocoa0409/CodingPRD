"""Dispatchable-location capture and regulatory validation (PRD 3.7)."""
from flask import Blueprint

import lookup
import store
import util
import validate as v
from common import (auth_for, body_or_error, bump, enum_filter, guard_account_owner,
                    list_response, new_entity, object_response, pagination, paginate,
                    sort_created_asc, str_filter)
from errors import ApiError
from services import derive

bp = Blueprint("e911", __name__)

VERIFICATION_STATUSES = ("UNVERIFIED", "VERIFIED", "STALE", "REJECTED", "SUPERSEDED")
VERIFIABLE_FROM = ("UNVERIFIED", "STALE")
OUTCOMES = ("VERIFIED", "REJECTED")


def _owner_of_named_device(body):
    """The account that owns the device named in the body, or None when unresolvable."""
    device_id = v.peek_str(body, "device_id")
    if device_id is None:
        return None
    device = store.devices.get(device_id)
    return device["account_id"] if device is not None else None


@bp.route("/voip/e911-registrations", methods=["POST"])
def create_registration():
    user_id, role = auth_for(("AccountAdmin", "PlatformAdmin"))
    body = body_or_error()
    guard_account_owner(role, user_id, _owner_of_named_device(body))
    device_id = v.req_id(body, "device_id")
    jurisdiction_id = v.req_id(body, "jurisdiction_id")
    address_line1 = v.req_str(body, "address_line1", min_len=1, max_len=80)
    unit = v.opt_str(body, "unit", max_len=20, default="")
    city = v.req_str(body, "city", min_len=1, max_len=40)
    state_code = v.req_str(body, "state_code", exact_len=2, pattern=v.UPPER_ALPHA_RE)
    postal_code = v.req_str(body, "postal_code", exact_len=5, pattern=v.DIGITS_RE)

    device = lookup.device(device_id)
    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    account = lookup.account(device["account_id"])
    lookup.require_active(account)
    if state_code != jurisdiction["state_code"]:
        raise ApiError("ERR_JURISDICTION_STATE_MISMATCH",
                       "The address is not inside the named jurisdiction's state.")

    previous = derive.current_registration(device["id"])
    if previous is not None:
        previous["superseded_at"] = store.now()
        previous["verification_status"] = "SUPERSEDED"
        bump(previous)

    row = new_entity()
    row.update({
        "device_id": device["id"],
        "account_id": device["account_id"],
        "jurisdiction_id": jurisdiction["id"],
        "address_line1": address_line1,
        "unit": unit,
        "city": city,
        "state_code": state_code,
        "postal_code": postal_code,
        "normalized_location_key": "%s|%s|%s" % (
            util.normalize_alnum(address_line1), util.normalize_alnum(unit), postal_code),
        "verification_status": "UNVERIFIED",
        "effective_from": store.now(),
        "verified_at": None,
        "superseded_at": None,
        "rejection_note": None,
    })
    store.e911_registrations[row["id"]] = row

    device["registration_status"] = "ADDRESS_UNVERIFIED"
    bump(device)
    derive.recompute_posture(account)
    return object_response(row, 201)


@bp.route("/voip/e911-registrations/<registration_id>", methods=["GET"])
def get_registration(registration_id):
    user_id, role = auth_for(("AccountAdmin", "E911Validator", "BillingAdmin",
                              "PlatformAdmin"))
    row = lookup.registration(registration_id)
    guard_account_owner(role, user_id, row["account_id"])
    return object_response(row)


@bp.route("/voip/e911-registrations", methods=["GET"])
def list_registrations():
    auth_for(("E911Validator", "BillingAdmin", "PlatformAdmin"))
    limit, offset = pagination()
    account_id = str_filter("account_id")
    device_id = str_filter("device_id")
    jurisdiction_id = str_filter("jurisdiction_id")
    verification_status = enum_filter("verification_status", VERIFICATION_STATUSES)
    rows = list(store.e911_registrations.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if device_id is not None:
        rows = [r for r in rows if r["device_id"] == device_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/voip/e911-registrations/<registration_id>/verify", methods=["POST"])
def verify_registration(registration_id):
    auth_for(("E911Validator",))
    body = body_or_error()
    outcome = v.req_enum(body, "outcome", OUTCOMES)
    rejection_note = v.opt_free_text(body, "rejection_note")

    registration = lookup.registration(registration_id)
    if registration["verification_status"] not in VERIFIABLE_FROM:
        raise ApiError("ERR_REGISTRATION_NOT_VERIFIABLE",
                       "Only an UNVERIFIED or STALE registration can be validated.")

    device = store.devices.get(registration["device_id"])
    if outcome == "VERIFIED":
        registration["verification_status"] = "VERIFIED"
        registration["verified_at"] = store.now()
        if device is not None:
            device["registration_status"] = "REGISTERED"
    else:
        registration["verification_status"] = "REJECTED"
        registration["rejection_note"] = rejection_note
        if device is not None:
            device["registration_status"] = "SUSPENDED_911"
    bump(registration)
    if device is not None:
        bump(device)
        derive.recompute_posture(store.accounts.get(device["account_id"]))
    return object_response(registration)
