"""Reference data, the fiscal envelope and the logical clock (PRD 3.1, 3.9, 2.4)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import lookup
import serialize
import validate
from clock import clock, iso, now
from envelope import object_response
from errors import ApiError
from services import shares
from store import db, new_row, touch

bp = Blueprint("reference", __name__)

HOSPITAL_TYPES = ("ACUTE_CARE", "CRITICAL_ACCESS")
PAYERS = ("MEDICARE_FFS", "MEDICARE_ADVANTAGE", "COMMERCIAL")
SPECIALTIES = ("PULMONOLOGY", "INFECTIOUS_DISEASE", "WOUND_CARE", "INTERNAL_MEDICINE")
CREDENTIAL_STATUSES = ("ACTIVE", "SUSPENDED")

ALL = auth.ALL_ROLES
CO = auth.ROLE_COMPLIANCE_OFFICER
IC = auth.ROLE_INTAKE_COORDINATOR
URN = auth.ROLE_UR_NURSE
AP = auth.ROLE_ATTENDING_PHYSICIAN
RIA = auth.ROLE_REVENUE_ANALYST

ZERO_PCT = Decimal("0.00")


def _unique(collection, field, value, label):
    for row in collection.values():
        if row.get(field) == value:
            raise ApiError("ERR_DUPLICATE_KEY", "%s is already in use." % label)


# --------------------------------------------------------------------------- #
# referring hospitals
# --------------------------------------------------------------------------- #

@bp.route("/referring-hospitals", methods=["POST"])
def create_hospital():
    body = validate.get_body()
    name = validate.req_str(body, "name", 1, 120)
    npi = validate.digits(validate.req_str(body, "npi", 1, None), "npi", 10)
    hospital_type = validate.req_enum(body, "hospital_type", HOSPITAL_TYPES)
    is_colocated = validate.opt_bool(body, "is_colocated", False)
    auth.require_role(CO)
    _unique(db.hospitals, "npi", npi, "npi")

    row = new_row("hospitals")
    row.update({
        "name": name,
        "npi": npi,
        "hospital_type": hospital_type,
        "is_colocated": is_colocated,
        "admissions_in_period": 0,
        "share_pct": ZERO_PCT,
        "monitoring_state": "COMPLIANT",
    })
    row["threshold_pct"] = calc.hospital_threshold_pct(row)
    db.hospitals[row["id"]] = row
    return object_response(serialize.hospital(row), 201)


@bp.route("/referring-hospitals/<hospital_id>", methods=["GET"])
def get_hospital(hospital_id):
    auth.require_role(*ALL)
    return object_response(serialize.hospital(lookup.hospital(hospital_id)))


# --------------------------------------------------------------------------- #
# patients
# --------------------------------------------------------------------------- #

@bp.route("/patients", methods=["POST"])
def create_patient():
    body = validate.get_body()
    mrn = validate.req_str(body, "mrn", 1, 24)
    full_name = validate.req_str(body, "full_name", 1, 120)
    birth_date = validate.req_date(body, "birth_date")
    primary_payer = validate.req_enum(body, "primary_payer", PAYERS)
    auth.require_role(CO, IC)
    _unique(db.patients, "mrn", mrn, "mrn")

    row = new_row("patients")
    row.update({
        "mrn": mrn,
        "full_name": full_name,
        "birth_date": birth_date,
        "primary_payer": primary_payer,
        "open_referral_count": 0,
    })
    db.patients[row["id"]] = row
    return object_response(serialize.patient(row), 201)


@bp.route("/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    auth.require_role(*ALL)
    return object_response(serialize.patient(lookup.patient(patient_id)))


# --------------------------------------------------------------------------- #
# physicians
# --------------------------------------------------------------------------- #

@bp.route("/physicians", methods=["POST"])
def create_physician():
    body = validate.get_body()
    npi = validate.digits(validate.req_str(body, "npi", 1, None), "npi", 10)
    full_name = validate.req_str(body, "full_name", 1, 120)
    specialty = validate.req_enum(body, "specialty", SPECIALTIES)
    auth.require_role(CO)
    _unique(db.physicians, "npi", npi, "npi")

    row = new_row("physicians")
    row.update({
        "npi": npi,
        "full_name": full_name,
        "specialty": specialty,
        "credential_status": "ACTIVE",
    })
    db.physicians[row["id"]] = row
    return object_response(serialize.physician(row), 201)


@bp.route("/physicians/<physician_id>", methods=["GET"])
def get_physician(physician_id):
    auth.require_role(*ALL)
    return object_response(serialize.physician(lookup.physician(physician_id)))


@bp.route("/physicians/<physician_id>/credential-status", methods=["POST"])
def set_credential_status(physician_id):
    body = validate.get_body()
    credential_status = validate.req_enum(body, "credential_status", CREDENTIAL_STATUSES)
    auth.require_role(CO)
    row = lookup.physician(physician_id)
    row["credential_status"] = credential_status
    touch(row)
    return object_response(serialize.physician(row))


# --------------------------------------------------------------------------- #
# MS-LTC-DRG rate entries
# --------------------------------------------------------------------------- #

@bp.route("/drg-rates", methods=["POST"])
def create_drg_rate():
    body = validate.get_body()
    drg_code = validate.req_str(body, "drg_code", 3, 5)
    relative_weight = validate.req_num(body, "relative_weight", max_decimals=4,
                                       strictly_positive=True)
    alos_days = validate.req_int(body, "alos_days", 1, 120)
    standard_federal_rate_cents = validate.req_int(body, "standard_federal_rate_cents", 1)
    ipps_per_diem = validate.req_int(body, "ipps_comparable_per_diem_cents", 1)
    ipps_full = validate.req_int(body, "ipps_comparable_full_cents", 1)
    auth.require_role(CO)
    _unique(db.drg_rates, "drg_code", drg_code, "drg_code")

    row = new_row("drg_rates")
    row.update({
        "drg_code": drg_code,
        "relative_weight": relative_weight,
        "alos_days": alos_days,
        "standard_federal_rate_cents": standard_federal_rate_cents,
        "ipps_comparable_per_diem_cents": ipps_per_diem,
        "ipps_comparable_full_cents": ipps_full,
    })
    db.drg_rates[row["id"]] = row
    return object_response(serialize.drg_rate(row), 201)


@bp.route("/drg-rates/<drg_rate_id>", methods=["GET"])
def get_drg_rate(drg_rate_id):
    auth.require_role(*ALL)
    return object_response(serialize.drg_rate(lookup.drg_rate(drg_rate_id)))


# --------------------------------------------------------------------------- #
# admission criteria sets
# --------------------------------------------------------------------------- #

@bp.route("/admission-criteria-sets", methods=["POST"])
def create_criteria_set():
    body = validate.get_body()
    label = validate.req_str(body, "label", 1, 40)
    effective_from = validate.req_date(body, "effective_from")
    pmv_min_vent_hours = validate.req_int(body, "pmv_min_vent_hours", 1, 1000)
    pmv_min_icu_days = validate.req_int(body, "pmv_min_icu_days", 0, 60)
    wound_min_stage = validate.req_int(body, "wound_min_stage", 1, 4)
    wound_min_count = validate.req_int(body, "wound_min_count", 1, 20)
    auth.require_role(CO)
    _unique(db.criteria_sets, "label", label, "label")
    for existing in db.criteria_sets.values():
        if existing["status"] == "ACTIVE" and effective_from <= existing["effective_from"]:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "effective_from must be strictly after every ACTIVE criteria set.")

    for existing in db.criteria_sets.values():
        if existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = new_row("criteria_sets")
    row.update({
        "label": label,
        "effective_from": effective_from,
        "pmv_min_vent_hours": pmv_min_vent_hours,
        "pmv_min_icu_days": pmv_min_icu_days,
        "wound_min_stage": wound_min_stage,
        "wound_min_count": wound_min_count,
        "status": "ACTIVE",
    })
    db.criteria_sets[row["id"]] = row
    return object_response(serialize.criteria_set(row), 201)


@bp.route("/admission-criteria-sets/<criteria_set_id>", methods=["GET"])
def get_criteria_set(criteria_set_id):
    auth.require_role(*ALL)
    return object_response(serialize.criteria_set(lookup.criteria_set(criteria_set_id)))


# --------------------------------------------------------------------------- #
# cost reporting periods
# --------------------------------------------------------------------------- #

@bp.route("/cost-reporting-periods", methods=["POST"])
def create_period():
    body = validate.get_body()
    period_label = validate.req_str(body, "period_label", 1, 40)
    start_date = validate.req_date(body, "start_date")
    end_date = validate.req_date(body, "end_date")
    if end_date <= start_date:
        raise ApiError("ERR_VALIDATION", "end_date must be strictly later than start_date.")
    auth.require_role(CO)
    _unique(db.periods, "period_label", period_label, "period_label")
    for existing in db.periods.values():
        if existing["status"] == "OPEN":
            raise ApiError("ERR_DUPLICATE_KEY", "Another cost reporting period is already OPEN.")
        if start_date <= existing["end_date"] and existing["start_date"] <= end_date:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "The period's date range overlaps an existing period.")

    row = new_row("periods")
    row.update({
        "period_label": period_label,
        "start_date": start_date,
        "end_date": end_date,
        "status": "OPEN",
        "total_admissions": 0,
        "total_payment_cents": 0,
        "final_determination_count": 0,
        "closed_at": None,
    })
    db.periods[row["id"]] = row

    # Opening a period resets facility-wide monitoring counters (PRD 2.7).
    for hospital in db.hospitals.values():
        if hospital["admissions_in_period"] != 0 or hospital["share_pct"] != ZERO_PCT:
            hospital["admissions_in_period"] = 0
            hospital["share_pct"] = ZERO_PCT
            touch(hospital)

    return object_response(serialize.period(row), 201)


@bp.route("/cost-reporting-periods/<period_id>", methods=["GET"])
def get_period(period_id):
    auth.require_role(CO, RIA, IC)
    return object_response(serialize.period(lookup.period(period_id)))


@bp.route("/cost-reporting-periods/<period_id>/recompute-referral-shares", methods=["POST"])
def recompute_referral_shares(period_id):
    validate.get_body()
    auth.require_role(CO)
    period = lookup.period(period_id)
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED", "The cost reporting period is CLOSED.")
    shares.recompute_all_shares(period)
    return object_response(serialize.period(period))


@bp.route("/cost-reporting-periods/<period_id>/close", methods=["POST"])
def close_period(period_id):
    validate.get_body()
    auth.require_role(CO)
    period = lookup.period(period_id)
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED", "The cost reporting period is already CLOSED.")

    stays = lookup.period_stays(period_id)
    stay_ids = set(row["id"] for row in stays)
    final_total = 0
    final_count = 0
    for determination in db.determinations.values():
        if determination["stay_id"] not in stay_ids:
            continue
        if determination["status"] == "DRAFT":
            raise ApiError("ERR_PERIOD_HAS_DRAFT_DETERMINATIONS",
                           "A stay in this period still holds a DRAFT payment determination.")
        if determination["status"] == "FINAL":
            final_total += determination["total_payment_cents"]
            final_count += 1

    if period["total_payment_cents"] != final_total or period["final_determination_count"] != final_count:
        raise ApiError("ERR_PERIOD_LEDGER_MISMATCH",
                       "The period ledger does not reconcile with a full recomputation.")

    for row in stays:
        if row["clinical_status"] != "DISCHARGED":
            continue
        determination = lookup.stay_live_determination(row["id"])
        if determination is None or determination["status"] != "FINAL":
            raise ApiError("ERR_INVALID_STATE",
                           "A DISCHARGED stay in this period has no FINAL payment determination.")

    period["status"] = "CLOSED"
    period["closed_at"] = now()
    touch(period)
    shares.recompute_all_shares(period)
    return object_response(serialize.period(period))


# --------------------------------------------------------------------------- #
# the logical clock
# --------------------------------------------------------------------------- #

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    body = validate.get_body()
    current_utc = validate.req_datetime(body, "current_utc")
    auth.require_role(*ALL)
    if current_utc <= now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "current_utc must be strictly after the current logical instant.")
    previous = clock.set(current_utc)
    return object_response({
        "current_utc": iso(current_utc),
        "previous_utc": iso(previous),
    })
