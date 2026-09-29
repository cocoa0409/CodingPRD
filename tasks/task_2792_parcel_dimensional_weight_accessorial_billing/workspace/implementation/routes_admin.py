"""Shipper accounts, rate contracts, service levels, surcharge windows and the
logical clock (PRD 3.1, 3.2, 2.4)."""

import re

from flask import Blueprint

import domain
import serializers as ser
import validators as v
from auth import (ROLE_BILLING_OPS, ROLE_CARRIER_ADMIN, ROLE_CARRIER_OPS,
                  ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER, authorize,
                  enforce_named_shipper, enforce_shipper_scope)
from errors import ApiError
from response import pagination_params, paginate, success
from store import (add_days, db, iso, new_record, now, parse_instant,
                   set_clock, sorted_records, touch)

bp = Blueprint("admin", __name__)

CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")
WINDOW_KINDS = ("PEAK_SEASON", "DEMAND")
WINDOW_STATUSES = ("SCHEDULED", "ACTIVE", "CANCELLED")
CODE_PATTERN = re.compile(r"^[A-Z0-9]+(_[A-Z0-9]+)*$")


# --------------------------------------------------------------------------
# shipper accounts
# --------------------------------------------------------------------------

@bp.route("/shipper-accounts", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def create_shipper_account():
    body = v.get_body()
    account_number = v.req_string(body, "account_number", min_len=4, max_len=32)
    name = v.req_string(body, "name")
    billing_email = v.opt_string(body, "billing_email")

    for existing in db.shipper_accounts.values():
        if existing["account_number"] == account_number:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "account_number is already registered.")

    record = new_record()
    record.update({
        "account_number": account_number,
        "name": name,
        "billing_email": billing_email,
        "status": "ACTIVE",
    })
    db.shipper_accounts[record["id"]] = record
    return success(ser.shipper_account(record), 201)


@bp.route("/shipper-accounts/<shipper_id>/suspend", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def suspend_shipper_account(shipper_id):
    account = domain.shipper_or_404(shipper_id)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_SHIPPER_SUSPENDED",
                       "The shipper account is already SUSPENDED.")
    account["status"] = "SUSPENDED"
    touch(account)
    return success(ser.shipper_account(account))


@bp.route("/shipper-accounts/<shipper_id>", methods=["GET"])
@authorize(ROLE_CARRIER_ADMIN, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR,
           ROLE_SHIPPER_USER)
def read_shipper_account(shipper_id):
    account = domain.shipper_or_404(shipper_id)
    enforce_shipper_scope(account["id"])
    return success(ser.shipper_account(account))


# --------------------------------------------------------------------------
# rate contracts
# --------------------------------------------------------------------------

def _closed_overlap(a_from, a_to, b_from, b_to):
    return a_from <= b_to and b_from <= a_to


@bp.route("/rate-contracts", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def create_rate_contract():
    body = v.get_body()

    shipper = domain.shipper_or_404(v.peek_str(body, "shipper_id"))
    supersedes_id = v.peek_str(body, "supersedes_contract_id")
    predecessor = None
    if body.get("supersedes_contract_id") is not None:
        predecessor = domain.contract_or_404(supersedes_id)

    effective_from = v.req_date(body, "effective_from")
    effective_to = v.req_date(body, "effective_to")
    dim_divisor = v.req_int(body, "dim_divisor", minimum=100, maximum=250)
    min_charge_cents = v.req_int(body, "min_charge_cents", minimum=0)
    rate_table = v.req_rate_table(body, "rate_table")
    tier_discount_table = v.req_tier_table(body, "tier_discount_table")
    overrides = v.opt_overrides(body, "accessorial_rate_overrides")
    residential_waived = v.opt_bool(body, "residential_waived", False)

    if effective_to < effective_from:
        raise ApiError("ERR_INVALID_PERIOD",
                       "effective_to must be on or after effective_from.")

    for other in db.rate_contracts.values():
        if other["shipper_id"] != shipper["id"]:
            continue
        if other["status"] not in ("DRAFT", "ACTIVE"):
            continue
        if predecessor is not None and other["id"] == predecessor["id"]:
            continue
        if _closed_overlap(effective_from, effective_to,
                           other["effective_from"], other["effective_to"]):
            raise ApiError("ERR_CONTRACT_PERIOD_OVERLAP",
                           "The effectivity window intersects another DRAFT or "
                           "ACTIVE contract of this shipper.")

    record = new_record()
    record.update({
        "shipper_id": shipper["id"],
        "supersedes_contract_id": predecessor["id"] if predecessor else None,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "dim_divisor": dim_divisor,
        "min_charge_cents": min_charge_cents,
        "rate_table": rate_table,
        "tier_discount_table": tier_discount_table,
        "accessorial_rate_overrides": overrides,
        "residential_waived": residential_waived,
        "status": "DRAFT",
        "activated_at": None,
    })
    db.rate_contracts[record["id"]] = record
    return success(ser.rate_contract(record), 201)


@bp.route("/rate-contracts/<contract_id>/activate", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def activate_rate_contract(contract_id):
    contract = domain.contract_or_404(contract_id)
    account = domain.shipper_or_404(contract["shipper_id"])

    body = v.get_body()
    expected = v.req_int(body, "expected_shipper_account_version")
    if expected != account["version"]:
        raise ApiError("ERR_STALE_SHIPPER_VERSION",
                       "expected_shipper_account_version does not match the "
                       "shipper account's current version.")

    predecessor = None
    if contract["supersedes_contract_id"] is not None:
        predecessor = db.rate_contracts.get(contract["supersedes_contract_id"])

    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVATABLE",
                       "Only a DRAFT contract may be activated.")
    if contract["supersedes_contract_id"] is not None:
        if (predecessor is None
                or predecessor["shipper_id"] != contract["shipper_id"]
                or predecessor["status"] != "ACTIVE"):
            raise ApiError("ERR_CONTRACT_NOT_ACTIVATABLE",
                           "The supersession target must be an ACTIVE contract "
                           "of the same shipper.")

    contract["activated_at"] = iso(now())
    contract["status"] = "ACTIVE"
    touch(contract)

    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        predecessor["effective_to"] = add_days(contract["effective_from"], -1)
        touch(predecessor)
        touch(account)

    return success(ser.rate_contract(contract))


@bp.route("/rate-contracts/<contract_id>", methods=["GET"])
@authorize(ROLE_CARRIER_ADMIN, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR)
def read_rate_contract(contract_id):
    return success(ser.rate_contract(domain.contract_or_404(contract_id)))


@bp.route("/rate-contracts", methods=["GET"])
@authorize(ROLE_CARRIER_ADMIN, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR)
def list_rate_contracts():
    from flask import request

    limit, offset = pagination_params()
    shipper_id = request.args.get("shipper_id")
    supersedes = request.args.get("supersedes_contract_id")
    status = request.args.get("status")

    rows = sorted_records(list(db.rate_contracts.values()))
    if shipper_id is not None:
        rows = [r for r in rows if r["shipper_id"] == shipper_id]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_contract_id"] == supersedes]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.rate_contract, limit, offset)


# --------------------------------------------------------------------------
# service levels
# --------------------------------------------------------------------------

@bp.route("/service-levels", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def create_service_level():
    body = v.get_body()
    code = v.req_string(body, "code")
    if not CODE_PATTERN.match(code):
        v.bad("Field 'code' must be uppercase snake case.")
    name = v.req_string(body, "name")
    guarantee_hours = v.req_int(body, "guarantee_hours", minimum=1, maximum=336)
    guaranteed = v.req_bool(body, "guaranteed")

    for existing in db.service_levels.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY", "code is already defined.")

    record = new_record(versioned=False)
    record.update({
        "code": code,
        "name": name,
        "guarantee_hours": guarantee_hours,
        "guaranteed": guaranteed,
    })
    db.service_levels[record["id"]] = record
    return success(ser.service_level(record), 201)


@bp.route("/service-levels/<service_level_id>", methods=["GET"])
@authorize(ROLE_CARRIER_ADMIN, ROLE_CARRIER_OPS, ROLE_BILLING_OPS,
           ROLE_REVENUE_AUDITOR, ROLE_SHIPPER_USER)
def read_service_level(service_level_id):
    return success(ser.service_level(domain.service_level_or_404(service_level_id)))


# --------------------------------------------------------------------------
# surcharge windows
# --------------------------------------------------------------------------

@bp.route("/surcharge-windows", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def create_surcharge_window():
    body = v.get_body()

    service_level = None
    if body.get("service_level_id") is not None:
        service_level = domain.service_level_or_404(v.peek_str(body, "service_level_id"))

    code = v.req_string(body, "code")
    kind = v.req_enum(body, "kind", WINDOW_KINDS)
    start_date = v.req_date(body, "start_date")
    end_date = v.req_date(body, "end_date")
    per_package_cents = v.req_int(body, "per_package_cents", minimum=0)
    oversize_add_cents = v.opt_int(body, "oversize_add_cents", 0, minimum=0)

    for existing in db.surcharge_windows.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY", "code is already scheduled.")

    if end_date <= start_date:
        raise ApiError("ERR_INVALID_PERIOD",
                       "end_date must be strictly after start_date.")

    scope = service_level["id"] if service_level else None
    for other in db.surcharge_windows.values():
        if other["kind"] != kind or other["service_level_id"] != scope:
            continue
        if other["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if start_date < other["end_date"] and other["start_date"] < end_date:
            raise ApiError("ERR_SURCHARGE_WINDOW_OVERLAP",
                           "The window intersects another SCHEDULED or ACTIVE "
                           "window of the same kind and scope.")

    record = new_record()
    record.update({
        "code": code,
        "kind": kind,
        "service_level_id": scope,
        "start_date": start_date,
        "end_date": end_date,
        "per_package_cents": per_package_cents,
        "oversize_add_cents": oversize_add_cents,
        "status": "SCHEDULED",
    })
    db.surcharge_windows[record["id"]] = record
    return success(ser.surcharge_window(record), 201)


@bp.route("/surcharge-windows/<window_id>/activate", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def activate_surcharge_window(window_id):
    window = domain.window_or_404(window_id)
    if window["status"] != "SCHEDULED":
        raise ApiError("ERR_WINDOW_NOT_IN_STATE",
                       "Only a SCHEDULED window may be armed.")
    window["status"] = "ACTIVE"
    touch(window)
    return success(ser.surcharge_window(window))


@bp.route("/surcharge-windows/<window_id>/cancel", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def cancel_surcharge_window(window_id):
    window = domain.window_or_404(window_id)
    if window["status"] not in ("SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_WINDOW_NOT_IN_STATE",
                       "Only a SCHEDULED or ACTIVE window may be cancelled.")
    window["status"] = "CANCELLED"
    touch(window)
    return success(ser.surcharge_window(window))


@bp.route("/surcharge-windows/<window_id>", methods=["GET"])
@authorize(ROLE_CARRIER_ADMIN, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR)
def read_surcharge_window(window_id):
    return success(ser.surcharge_window(domain.window_or_404(window_id)))


@bp.route("/surcharge-windows", methods=["GET"])
@authorize(ROLE_CARRIER_ADMIN, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR)
def list_surcharge_windows():
    from flask import request

    limit, offset = pagination_params()
    kind = request.args.get("kind")
    service_level_id = request.args.get("service_level_id")
    status = request.args.get("status")

    rows = sorted_records(list(db.surcharge_windows.values()))
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    if service_level_id is not None:
        rows = [r for r in rows if r["service_level_id"] == service_level_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.surcharge_window, limit, offset)


# --------------------------------------------------------------------------
# logical clock (PRD 2.4)
# --------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@authorize(ROLE_CARRIER_ADMIN)
def set_current_utc():
    body = v.get_body()
    raw, parsed = v.req_instant(body, "now_utc")
    set_clock(parsed)
    return success({"now_utc": iso(parsed)})
