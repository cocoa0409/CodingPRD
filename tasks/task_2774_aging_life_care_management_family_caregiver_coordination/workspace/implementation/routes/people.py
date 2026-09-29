"""Care managers, coordinated vendors and the family circle."""
from flask import Blueprint

import auth
import clock
import derive
import envelope
import lookup
import serialize
import validators as v
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("people", __name__)

CREDENTIALS = ("CMC", "CCM", "CMAC", "C_ASWCM")
VENDOR_TYPES = ("HOME_CARE", "MEDICAL", "LEGAL", "HOUSING")
STANDINGS = ("APPROVED", "PROBATION", "BARRED")
CONTACT_ROLES = ("POA_HEALTHCARE", "POA_FINANCIAL", "GUARDIAN",
                 "RESPONSIBLE_PARTY", "INTERESTED_FAMILY")

VENDOR_FILTERS = {"vendor_type": "vendor_type", "standing": "standing"}
CONTACT_FILTERS = {
    "client_id": "client_id",
    "report_status": lambda rec: derive.report_cadence(rec)[0],
}


def _opt_number(body, key, default, minimum, maximum):
    if key not in body or body.get(key) is None:
        return default
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise v.bad("Field '%s' must be a number." % key)
    if value < minimum or value > maximum:
        raise v.bad("Field '%s' is out of range." % key)
    return value


# --- care managers -------------------------------------------------------

@bp.route("/care/care-managers", methods=["POST"])
def create_care_manager():
    auth.actor_for(auth.ROLE_ADMIN)
    body = v.json_body()
    record = new_record({
        "full_name": v.req_str(body, "full_name", 1, 120),
        "credential": v.req_enum(body, "credential", CREDENTIALS),
        "hourly_rate_cents": v.req_int(body, "hourly_rate_cents", 1, None),
        "is_supervisor": v.opt_bool(body, "is_supervisor", False),
        "active": v.opt_bool(body, "active", True),
    })
    db.care_managers[record["id"]] = record
    return envelope.created(serialize.care_manager(record))


@bp.route("/care/care-managers/<care_manager_id>", methods=["GET"])
def read_care_manager(care_manager_id):
    auth.actor_for(auth.ROLE_ADMIN, auth.ROLE_CARE_MANAGER,
                   auth.ROLE_SUPERVISOR, auth.ROLE_BILLING)
    record = lookup.need_care_manager(care_manager_id)
    return envelope.ok(serialize.care_manager(record))


# --- vendors -------------------------------------------------------------

@bp.route("/care/vendors", methods=["POST"])
def create_vendor():
    auth.actor_for(auth.ROLE_ADMIN)
    body = v.json_body()
    name = v.req_str(body, "name", 1, 160)
    vendor_type = v.req_enum(body, "vendor_type", VENDOR_TYPES)
    has_referral = v.req_bool(body, "has_referral_relationship")
    referral_fee_pct = _opt_number(body, "referral_fee_pct", 0, 0, 100)
    standing = v.opt_enum(body, "standing", STANDINGS, "APPROVED")
    if has_referral and referral_fee_pct <= 0:
        raise v.bad("A declared referral relationship requires a referral_fee_pct "
                    "greater than zero.")
    record = new_record({
        "name": name,
        "vendor_type": vendor_type,
        "has_referral_relationship": has_referral,
        "referral_fee_pct": referral_fee_pct,
        "standing": standing,
    })
    db.vendors[record["id"]] = record
    return envelope.created(serialize.vendor(record))


@bp.route("/care/vendors", methods=["GET"])
def list_vendors():
    auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    records = lookup.filter_records(list(db.vendors.values()), VENDOR_FILTERS,
                                    v.filters(VENDOR_FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.vendor(r) for r in records], limit, offset)


@bp.route("/care/vendors/<vendor_id>", methods=["GET"])
def read_vendor(vendor_id):
    auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_vendor(vendor_id)
    return envelope.ok(serialize.vendor(record))


@bp.route("/care/vendors/<vendor_id>", methods=["PATCH"])
def update_vendor(vendor_id):
    auth.actor_for(auth.ROLE_ADMIN)
    body = v.json_body()
    standing = v.opt_enum(body, "standing", STANDINGS)
    referral_fee_pct = _opt_number(body, "referral_fee_pct", None, 0, 100)
    if standing is None and referral_fee_pct is None:
        raise v.bad("Supply at least one of 'standing' or 'referral_fee_pct'.")
    vendor = lookup.need_vendor(vendor_id)
    if referral_fee_pct is not None:
        vendor["referral_fee_pct"] = referral_fee_pct
    if standing is not None:
        vendor["standing"] = standing
    if standing == "BARRED":
        derive.vendor_barred_cascade(vendor)
    touch(vendor)
    return envelope.ok(serialize.vendor(vendor))


# --- family contacts -----------------------------------------------------

@bp.route("/care/family-contacts", methods=["POST"])
def create_contact():
    auth.actor_for(auth.ROLE_ADMIN, auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    client_id = v.req_str(body, "client_id", 1, None)
    full_name = v.req_str(body, "full_name", 1, 120)
    contact_role = v.req_enum(body, "contact_role", CONTACT_ROLES)
    is_surrogate = v.opt_bool(body, "is_surrogate_decision_maker", False)
    is_long_distance = v.opt_bool(body, "is_long_distance", False)
    cadence = v.opt_int(body, "reporting_cadence_days", 30, 1, 180)
    lookup.need_client(client_id)
    record = new_record({
        "client_id": client_id,
        "full_name": full_name,
        "contact_role": contact_role,
        "is_surrogate_decision_maker": is_surrogate,
        "is_long_distance": is_long_distance,
        "reporting_cadence_days": cadence,
        "last_report_sent_at": None,
        "reports_sent_count": 0,
    })
    db.contacts[record["id"]] = record
    return envelope.created(serialize.contact(record))


@bp.route("/care/family-contacts", methods=["GET"])
def list_contacts():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.contacts.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, CONTACT_FILTERS,
                                    v.filters(CONTACT_FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.contact(r) for r in records], limit, offset)


@bp.route("/care/family-contacts/<contact_id>", methods=["GET"])
def read_contact(contact_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_contact(contact_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.contact(record))


@bp.route("/care/family-contacts/<contact_id>/reports", methods=["POST"])
def send_report(contact_id):
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    v.req_str(body, "report_period_start", 1, None)
    v.req_str(body, "report_period_end", 1, None)
    v.req_str(body, "summary", 1, None)
    contact = lookup.need_contact(contact_id)
    contact["last_report_sent_at"] = clock.now()
    contact["reports_sent_count"] = contact["reports_sent_count"] + 1
    touch(contact)
    return envelope.ok(serialize.contact(contact))
