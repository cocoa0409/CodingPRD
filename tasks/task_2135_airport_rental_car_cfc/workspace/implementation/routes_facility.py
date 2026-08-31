"""Facility inventory, brands, agreements, counter spaces, zones and the clock."""

from flask import Blueprint, g

import calc
import serializers as ser
from domain import agreement_or_404, bump, check_owner, facility_or_404, rows_of
from errors import ApiError
from store import all_rows, db, get, new_row
from validation import (ALL_ROLES, body, endpoint, opt_int, opt_str, pagination,
                        paginate, q_enum, q_int, q_str, req_date, req_enum,
                        req_int, req_str, to_date)
import response as resp

bp = Blueprint("facility", __name__)

CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED")
COMPLIANCE_STATUSES = ("COMPLIANT", "DELINQUENT", "COVENANT_BREACH")
SPACE_CLASSES = ("COUNTER", "READY_RETURN")
RENT_BASES = ("CUMULATIVE_YTD", "MONTHLY_STANDALONE")


# --------------------------------------------------------------------------
# Facility
# --------------------------------------------------------------------------

@bp.route("/rac/facilities", methods=["POST"])
@endpoint(["FacilityAdmin"])
def create_facility():
    data = body()
    code = req_str(data, "code", min_len=3, max_len=8, upper=True)
    name = req_str(data, "name")
    cfc_rate = req_int(data, "cfc_rate_per_transaction_day_cents", minimum=0)
    ds_req = req_int(data, "ds_reserve_requirement_cents", minimum=0)
    om_req = req_int(data, "om_reserve_requirement_cents", minimum=0)
    cap_cap = req_int(data, "capital_fund_cap_cents", minimum=0)
    overflow_stalls = req_int(data, "overflow_lot_stalls", minimum=0)
    surcharge = opt_int(data, "overflow_daily_surcharge_cents", 0)
    grace_days = opt_int(data, "remittance_grace_days", 20)

    row = new_row("facilities", {
        "code": code,
        "name": name,
        "cfc_rate_per_transaction_day_cents": cfc_rate,
        "ds_reserve_requirement_cents": ds_req,
        "om_reserve_requirement_cents": om_req,
        "capital_fund_cap_cents": cap_cap,
        "overflow_lot_stalls": overflow_stalls,
        "overflow_daily_surcharge_cents": surcharge,
        "remittance_grace_days": grace_days,
        "trust_lifetime_received_cents": 0,
        "trust_debt_service_reserve_cents": 0,
        "trust_debt_service_funded_cents": 0,
        "trust_om_reserve_cents": 0,
        "trust_capital_fund_cents": 0,
        "trust_unallocated_cents": 0,
        "trust_encumbered_cents": 0,
        "trust_disbursed_cents": 0,
        "bond_coverage_status": "DEFICIENT",
        "funded_obligation_count": 0,
        "overflow_stalls_allocated": 0,
    })
    calc.recompute_bond_coverage(row)
    return resp.created(ser.facility(row))


@bp.route("/rac/facilities/<facility_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_facility(facility_id):
    return resp.ok(ser.facility(facility_or_404(facility_id)))


# --------------------------------------------------------------------------
# Concessionaire
# --------------------------------------------------------------------------

@bp.route("/rac/concessionaires", methods=["POST"])
@endpoint(["FacilityAdmin"])
def create_concessionaire():
    data = body()
    facility_id = req_str(data, "facility_id")
    legal_name = req_str(data, "legal_name")
    brand_code = req_str(data, "brand_code", min_len=2, max_len=8, upper=True)
    contact_email = req_str(data, "contact_email")

    facility = facility_or_404(facility_id)
    for other in all_rows("concessionaires"):
        if other["facility_id"] == facility["id"] and other["brand_code"] == brand_code:
            raise ApiError("ERR_DUPLICATE_BRAND_CODE")

    row = new_row("concessionaires", {
        "facility_id": facility["id"],
        "legal_name": legal_name,
        "brand_code": brand_code,
        "contact_email": contact_email,
        "agreement_count": 0,
    })
    return resp.created(ser.concessionaire(row))


@bp.route("/rac/concessionaires/<concessionaire_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_concessionaire(concessionaire_id):
    row = get("concessionaires", concessionaire_id, "ERR_CONCESSIONAIRE_NOT_FOUND")
    return resp.ok(ser.concessionaire(row))


@bp.route("/rac/concessionaires", methods=["GET"])
@endpoint(ALL_ROLES)
def list_concessionaires():
    limit, offset = pagination()
    rows = rows_of("concessionaires", facility_id=q_str("facility_id"))
    items, limit, offset, total = paginate(rows, limit, offset, ser.concessionaire)
    return resp.listing(items, limit, offset, total)


# --------------------------------------------------------------------------
# ConcessionAgreement
# --------------------------------------------------------------------------

@bp.route("/rac/concession-agreements", methods=["POST"])
@endpoint(["FacilityAdmin"])
def create_agreement():
    data = body()
    facility_id = req_str(data, "facility_id")
    concessionaire_id = req_str(data, "concessionaire_id")
    contract_year_index = req_int(data, "contract_year_index", minimum=1)
    term_start_date = req_date(data, "term_start_date")
    term_end_date = req_date(data, "term_end_date")
    mag_annual_cents = req_int(data, "mag_annual_cents", minimum=0)
    rate_bps = req_int(data, "percentage_rent_rate_bps", minimum=0, maximum=10000)
    basis = req_enum(data, "rent_settlement_basis", RENT_BASES)

    facility = facility_or_404(facility_id)
    concessionaire = get("concessionaires", concessionaire_id,
                         "ERR_CONCESSIONAIRE_NOT_FOUND")

    row = new_row("agreements", {
        "facility_id": facility["id"],
        "concessionaire_id": concessionaire["id"],
        "contract_year_index": contract_year_index,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "mag_annual_cents": mag_annual_cents,
        "percentage_rent_rate_bps": rate_bps,
        "rent_settlement_basis": basis,
        "contract_status": "DRAFT",
        "compliance_status": "COMPLIANT",
        "gross_revenue_ytd_cents": 0,
        "transaction_days_ytd": 0,
        "accepted_report_count": 0,
        "percentage_rent_accrued_cents": 0,
        "rent_billed_to_date_cents": 0,
        "last_installment_cents": 0,
        "rent_tier": "MAG_FLOOR",
        "mag_shortfall_cents": 0,
        "counter_units_assigned": 0,
        "fleet_stalls_allocated": 0,
    })
    concessionaire["agreement_count"] += 1
    bump(concessionaire)
    return resp.created(ser.agreement(row))


@bp.route("/rac/concession-agreements/<agreement_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_agreement(agreement_id):
    return resp.ok(ser.agreement(agreement_or_404(agreement_id)))


@bp.route("/rac/concession-agreements", methods=["GET"])
@endpoint(ALL_ROLES)
def list_agreements():
    limit, offset = pagination()
    rows = rows_of("agreements",
                   facility_id=q_str("facility_id"),
                   concessionaire_id=q_str("concessionaire_id"),
                   contract_status=q_enum("contract_status", CONTRACT_STATUSES),
                   compliance_status=q_enum("compliance_status", COMPLIANCE_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.agreement)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/concession-agreements/<agreement_id>/execute", methods=["POST"])
@endpoint(["FacilityAdmin"])
def execute_agreement(agreement_id):
    row = agreement_or_404(agreement_id)
    if row["contract_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if to_date(row["term_start_date"]) >= to_date(row["term_end_date"]):
        raise ApiError("ERR_INVALID_STATE",
                       "term_start_date must be strictly earlier than term_end_date.")
    row["contract_status"] = "ACTIVE"
    bump(row)
    return resp.ok(ser.agreement(row))


@bp.route("/rac/concession-agreements/<agreement_id>/suspend", methods=["POST"])
@endpoint(["FacilityAdmin"])
def suspend_agreement(agreement_id):
    row = agreement_or_404(agreement_id)
    if row["contract_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    row["contract_status"] = "SUSPENDED"
    for assignment in all_rows("counter_assignments"):
        if assignment["agreement_id"] != row["id"] or assignment["status"] != "ACTIVE":
            continue
        assignment["status"] = "ALLOCATED"
        bump(assignment)
        space = db.counter_spaces.get(assignment["counter_space_id"])
        if space is not None and space.get("active_assignment_id") == assignment["id"]:
            space["active_assignment_id"] = None
            bump(space)
    bump(row)
    return resp.ok(ser.agreement(row))


@bp.route("/rac/concession-agreements/<agreement_id>/reinstate", methods=["POST"])
@endpoint(["FacilityAdmin"])
def reinstate_agreement(agreement_id):
    row = agreement_or_404(agreement_id)
    if row["contract_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    row["contract_status"] = "ACTIVE"
    bump(row)
    return resp.ok(ser.agreement(row))


# --------------------------------------------------------------------------
# CounterSpace
# --------------------------------------------------------------------------

@bp.route("/rac/counter-spaces", methods=["POST"])
@endpoint(["FacilityAdmin"])
def create_counter_space():
    data = body()
    facility_id = req_str(data, "facility_id")
    terminal_code = req_str(data, "terminal_code")
    space_label = req_str(data, "space_label")
    space_class = req_enum(data, "space_class", SPACE_CLASSES)

    facility = facility_or_404(facility_id)
    for other in all_rows("counter_spaces"):
        if other["facility_id"] == facility["id"] and other["space_label"] == space_label:
            raise ApiError("ERR_DUPLICATE_SPACE_LABEL")

    row = new_row("counter_spaces", {
        "facility_id": facility["id"],
        "terminal_code": terminal_code,
        "space_label": space_label,
        "space_class": space_class,
        "active_assignment_id": None,
        "assignment_count": 0,
    })
    return resp.created(ser.counter_space(row))


@bp.route("/rac/counter-spaces/<counter_space_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_counter_space(counter_space_id):
    row = get("counter_spaces", counter_space_id, "ERR_COUNTER_SPACE_NOT_FOUND")
    return resp.ok(ser.counter_space(row))


@bp.route("/rac/counter-spaces", methods=["GET"])
@endpoint(ALL_ROLES)
def list_counter_spaces():
    limit, offset = pagination()
    rows = rows_of("counter_spaces",
                   facility_id=q_str("facility_id"),
                   space_class=q_enum("space_class", SPACE_CLASSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.counter_space)
    return resp.listing(items, limit, offset, total)


# --------------------------------------------------------------------------
# FleetParkingZone
# --------------------------------------------------------------------------

@bp.route("/rac/fleet-parking-zones", methods=["POST"])
@endpoint(["FacilityAdmin"])
def create_zone():
    data = body()
    facility_id = req_str(data, "facility_id")
    zone_label = req_str(data, "zone_label")
    stall_capacity = req_int(data, "stall_capacity", minimum=0)

    facility = facility_or_404(facility_id)
    row = new_row("zones", {
        "facility_id": facility["id"],
        "zone_label": zone_label,
        "stall_capacity": stall_capacity,
        "stalls_allocated": 0,
    })
    return resp.created(ser.zone(row))


@bp.route("/rac/fleet-parking-zones/<zone_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_zone(zone_id):
    return resp.ok(ser.zone(get("zones", zone_id, "ERR_ZONE_NOT_FOUND")))


@bp.route("/rac/fleet-parking-zones", methods=["GET"])
@endpoint(ALL_ROLES)
def list_zones():
    limit, offset = pagination()
    rows = rows_of("zones", facility_id=q_str("facility_id"))
    items, limit, offset, total = paginate(rows, limit, offset, ser.zone)
    return resp.listing(items, limit, offset, total)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

def _valid_iso(value):
    if not isinstance(value, str) or len(value) < 10:
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        import datetime as _dt
        _dt.datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        return False
    return True


@bp.route("/rac/_clock/set_current_utc", methods=["POST"])
@endpoint(["FacilityAdmin"])
def set_clock():
    data = body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field 'to_iso8601'.")
    to_iso8601 = data["to_iso8601"]
    if not _valid_iso(to_iso8601):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")

    db.clock = to_iso8601
    today = to_iso8601[:10]

    delinquent_remittance_count = 0
    deferred_obligation_count = 0
    expired_agreement_count = 0

    for remittance in all_rows("remittances"):
        if remittance["status"] != "PENDING":
            continue
        if remittance["due_date"] >= today:
            continue
        remittance["status"] = "DELINQUENT"
        bump(remittance)
        delinquent_remittance_count += 1
        agreement = db.agreements.get(remittance["agreement_id"])
        if agreement is not None and agreement["compliance_status"] == "COMPLIANT":
            agreement["compliance_status"] = "DELINQUENT"
            bump(agreement)

    for obligation in all_rows("obligations"):
        if obligation["status"] != "SCHEDULED":
            continue
        if obligation["due_date"] >= today:
            continue
        obligation["status"] = "DEFERRED"
        bump(obligation)
        deferred_obligation_count += 1

    for agreement in all_rows("agreements"):
        if agreement["contract_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if agreement["term_end_date"] >= today:
            continue
        if agreement["contract_status"] == "ACTIVE":
            agreement["contract_status"] = "EXPIRED"
        else:
            agreement["contract_status"] = "TERMINATED"
            for assignment in all_rows("counter_assignments"):
                if assignment["agreement_id"] != agreement["id"]:
                    continue
                if assignment["status"] not in ("ALLOCATED", "ACTIVE"):
                    continue
                assignment["status"] = "RELEASED"
                bump(assignment)
                space = db.counter_spaces.get(assignment["counter_space_id"])
                if space is not None:
                    space["assignment_count"] -= 1
                    bump(space)
        bump(agreement)
        expired_agreement_count += 1

    return resp.ok({
        "current_utc": db.clock,
        "delinquent_remittance_count": delinquent_remittance_count,
        "deferred_obligation_count": deferred_obligation_count,
        "expired_agreement_count": expired_agreement_count,
    })
