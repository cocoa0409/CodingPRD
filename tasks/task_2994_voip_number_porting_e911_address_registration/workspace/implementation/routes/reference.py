"""Logical clock and reference data: accounts, carriers, jurisdictions, remittance runs."""
from flask import Blueprint

import lookup
import store
import util
import validate as v
from common import (auth_for, body_or_error, guard_account_owner, new_entity,
                    object_response)
from errors import ApiError
from services import fees

bp = Blueprint("reference", __name__)

ACCOUNT_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
CSR_POLICIES = ("STRICT", "RELAXED")
FEE_TYPES = ("PER_LINE", "PER_LOCATION")
DEFAULT_INTL_DAILY_CAP_CENTS = 2000


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_for(("PlatformAdmin",))
    body = body_or_error()
    current = v.req_instant(body, "current_utc")
    previous = store.set_clock(current)
    return object_response({
        "current_utc": util.to_iso(current),
        "previous_utc": util.to_iso(previous),
    })


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@bp.route("/voip/accounts", methods=["POST"])
def create_account():
    auth_for(("PlatformAdmin",))
    body = body_or_error()
    account_number = v.req_str(body, "account_number", min_len=8, max_len=12,
                               pattern=v.UPPER_ALNUM_RE)
    billing_name = v.req_str(body, "billing_name", min_len=1, max_len=80)
    service_state_code = v.req_str(body, "service_state_code", exact_len=2,
                                   pattern=v.UPPER_ALPHA_RE)
    status = v.opt_enum(body, "status", ACCOUNT_STATUSES, default="ACTIVE")
    intl_calling_enabled = v.opt_bool(body, "intl_calling_enabled", default=False)
    intl_daily_cap_cents = v.opt_int(body, "intl_daily_cap_cents", minimum=0,
                                     default=DEFAULT_INTL_DAILY_CAP_CENTS)
    for existing in store.accounts.values():
        if existing["account_number"] == account_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "An account with that account_number already exists.")
    row = new_entity()
    row.update({
        "account_number": account_number,
        "billing_name": billing_name,
        "service_state_code": service_state_code,
        "status": status,
        "intl_calling_enabled": intl_calling_enabled,
        "intl_daily_cap_cents": intl_daily_cap_cents,
        "e911_compliance_posture": "COMPLIANT",
        "fee_liability_cents": 0,
        "ported_number_count": 0,
    })
    store.accounts[row["id"]] = row
    return object_response(row, 201)


@bp.route("/voip/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = auth_for(("PlatformAdmin", "BillingAdmin", "SecurityAnalyst",
                              "AccountAdmin"))
    row = lookup.account(account_id)
    guard_account_owner(role, user_id, row["id"])
    return object_response(row)


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
@bp.route("/voip/carriers", methods=["POST"])
def create_carrier():
    auth_for(("PlatformAdmin",))
    body = body_or_error()
    name = v.req_str(body, "name", min_len=1, max_len=80)
    ocn = v.req_str(body, "ocn", exact_len=4, pattern=v.UPPER_ALNUM_RE)
    csr_match_policy = v.req_enum(body, "csr_match_policy", CSR_POLICIES)
    porting_buffer_minutes = v.req_int(body, "porting_buffer_minutes", minimum=0, maximum=240)
    foc_business_days = v.req_int(body, "foc_business_days", minimum=1, maximum=10)
    for existing in store.carriers.values():
        if existing["ocn"] == ocn:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "A carrier with that ocn already exists.")
    row = new_entity(with_mutation_fields=False)
    row.update({
        "name": name,
        "ocn": ocn,
        "csr_match_policy": csr_match_policy,
        "porting_buffer_minutes": porting_buffer_minutes,
        "foc_business_days": foc_business_days,
    })
    store.carriers[row["id"]] = row
    return object_response(row, 201)


@bp.route("/voip/carriers/<carrier_id>", methods=["GET"])
def get_carrier(carrier_id):
    auth_for(("PlatformAdmin", "PortingSpecialist", "CarrierLiaison"))
    return object_response(lookup.carrier(carrier_id))


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------
@bp.route("/voip/jurisdictions", methods=["POST"])
def create_jurisdiction():
    auth_for(("PlatformAdmin",))
    body = body_or_error()
    state_code = v.req_str(body, "state_code", exact_len=2, pattern=v.UPPER_ALPHA_RE)
    county_fips = v.req_str(body, "county_fips", exact_len=5, pattern=v.DIGITS_RE)
    fee_type = v.req_enum(body, "fee_type", FEE_TYPES)
    monthly_fee_cents = v.req_int(body, "monthly_fee_cents", minimum=1, maximum=10000)
    remit_day_of_month = v.req_int(body, "remit_day_of_month", minimum=1, maximum=28)
    for existing in store.jurisdictions.values():
        if (existing["state_code"] == state_code
                and existing["county_fips"] == county_fips):
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "A jurisdiction with that state_code and county_fips exists.")
    row = new_entity()
    row.update({
        "state_code": state_code,
        "county_fips": county_fips,
        "fee_type": fee_type,
        "monthly_fee_cents": monthly_fee_cents,
        "remit_day_of_month": remit_day_of_month,
        "pending_fee_cents": 0,
        "remitted_fee_cents": 0,
        "last_remitted_period": None,
    })
    store.jurisdictions[row["id"]] = row
    return object_response(row, 201)


@bp.route("/voip/jurisdictions/<jurisdiction_id>", methods=["GET"])
def get_jurisdiction(jurisdiction_id):
    auth_for(("PlatformAdmin", "BillingAdmin", "E911Validator"))
    return object_response(lookup.jurisdiction(jurisdiction_id))


# ---------------------------------------------------------------------------
# Remittance runs
# ---------------------------------------------------------------------------
@bp.route("/voip/jurisdictions/<jurisdiction_id>/remittance-runs", methods=["POST"])
def create_remittance_run(jurisdiction_id):
    auth_for(("BillingAdmin",))
    body = body_or_error()
    period_month = v.req_period(body, "period_month")
    jurisdiction = lookup.jurisdiction(jurisdiction_id)
    fees.check_period_closed(jurisdiction, period_month)
    return object_response(fees.run_remittance(jurisdiction, period_month))
