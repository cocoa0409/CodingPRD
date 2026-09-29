"""Referral intake, the screening loop and admission (PRD 3.2, 3.3)."""

from flask import Blueprint

import auth
import calc
import lookup
import serialize
import validate
from clock import now
from envelope import array_response, object_response
from errors import ApiError
from services import shares
from store import db, new_row, sorted_rows, touch

bp = Blueprint("referrals", __name__)

CO = auth.ROLE_COMPLIANCE_OFFICER
IC = auth.ROLE_INTAKE_COORDINATOR
URN = auth.ROLE_UR_NURSE
AP = auth.ROLE_ATTENDING_PHYSICIAN
RIA = auth.ROLE_REVENUE_ANALYST

REQUIRED_SCREENING_INPUTS = (
    "vent_hours_at_referral",
    "icu_days_at_referral",
    "wound_stage",
    "wound_count",
    "prior_acute_discharge_at",
)

REFERRAL_STATUSES = ("RECEIVED", "INFO_REQUESTED", "CRITERIA_MET", "CRITERIA_NOT_MET",
                     "ADMITTED", "WITHDRAWN", "SUPERSEDED")

OPEN_REFERRAL_STATUSES = ("RECEIVED", "INFO_REQUESTED", "CRITERIA_MET")


def _read_screening_inputs(body):
    return {
        "vent_hours_at_referral": validate.opt_num(body, "vent_hours_at_referral", minimum=0),
        "icu_days_at_referral": validate.opt_int(body, "icu_days_at_referral", minimum=0),
        "wound_stage": validate.opt_int(body, "wound_stage", minimum=0, maximum=4),
        "wound_count": validate.opt_int(body, "wound_count", minimum=0, maximum=20),
        "prior_acute_discharge_at": validate.opt_datetime(body, "prior_acute_discharge_at"),
    }


def _decrement_open_referrals(patient):
    count = patient["open_referral_count"] - 1
    patient["open_referral_count"] = count if count > 0 else 0
    touch(patient)


def select_effective_criteria_set():
    """PRD 3.2: the newest ACTIVE set already effective on the current logical date."""
    today = now().date()
    candidates = [row for row in db.criteria_sets.values()
                  if row["status"] == "ACTIVE" and row["effective_from"] <= today]
    if not candidates:
        raise ApiError("ERR_NO_EFFECTIVE_CRITERIA_SET",
                       "No ACTIVE admission criteria set is effective on the current logical date.")
    candidates.sort(key=lambda row: (row["effective_from"], row["created_at"], row["_seq"]),
                    reverse=True)
    return candidates[0]


def evaluate_screening(referral, criteria_set):
    """Pin the set, evaluate completeness, then resolve the qualifying track."""
    referral["pinned_criteria_set_id"] = criteria_set["id"]
    missing = [name for name in REQUIRED_SCREENING_INPUTS if referral[name] is None]
    referral["missing_fields"] = missing
    referral["data_complete"] = len(missing) == 0
    referral["screened_count"] = referral["screened_count"] + 1

    if missing:
        referral["qualifying_track"] = "NONE"
        referral["status"] = "INFO_REQUESTED"
        return

    pmv_met = (referral["vent_hours_at_referral"] >= criteria_set["pmv_min_vent_hours"]
               and referral["icu_days_at_referral"] >= criteria_set["pmv_min_icu_days"])
    wound_met = (referral["wound_stage"] >= criteria_set["wound_min_stage"]
                 and referral["wound_count"] >= criteria_set["wound_min_count"])
    if pmv_met:
        referral["qualifying_track"] = "PMV"
    elif wound_met:
        referral["qualifying_track"] = "COMPLEX_WOUND"
    else:
        referral["qualifying_track"] = "NONE"

    if referral["qualifying_track"] == "NONE":
        referral["status"] = "CRITERIA_NOT_MET"
        _decrement_open_referrals(db.patients[referral["patient_id"]])
    else:
        referral["status"] = "CRITERIA_MET"


# --------------------------------------------------------------------------- #
# create, read, list
# --------------------------------------------------------------------------- #

@bp.route("/referrals", methods=["POST"])
def create_referral():
    body = validate.get_body()
    patient_id = validate.req_str(body, "patient_id", 1, None)
    referring_hospital_id = validate.req_str(body, "referring_hospital_id", 1, None)
    drg_rate_id = validate.req_str(body, "drg_rate_id", 1, None)
    expected_patient_version = validate.req_int(body, "expected_patient_version")
    optional = _read_screening_inputs(body)
    auth.require_role(IC)

    patient = lookup.patient(patient_id)
    lookup.hospital(referring_hospital_id)
    lookup.drg_rate(drg_rate_id)

    if expected_patient_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION",
                       "expected_patient_version does not match the patient's current version.")

    for existing in db.referrals.values():
        if existing["patient_id"] == patient_id and existing["status"] in OPEN_REFERRAL_STATUSES:
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = new_row("referrals")
    row.update({
        "patient_id": patient_id,
        "referring_hospital_id": referring_hospital_id,
        "drg_rate_id": drg_rate_id,
        "pinned_criteria_set_id": None,
        "wound_stage": optional["wound_stage"],
        "wound_count": optional["wound_count"],
        "vent_hours_at_referral": optional["vent_hours_at_referral"],
        "icu_days_at_referral": optional["icu_days_at_referral"],
        "prior_acute_discharge_at": optional["prior_acute_discharge_at"],
        "data_complete": False,
        "missing_fields": [],
        "qualifying_track": "NONE",
        "status": "RECEIVED",
        "screened_count": 0,
    })
    db.referrals[row["id"]] = row

    patient["open_referral_count"] = 1
    touch(patient)

    return object_response(serialize.referral(row), 201)


@bp.route("/referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    auth.require_role(*auth.ALL_ROLES)
    return object_response(serialize.referral(lookup.referral(referral_id)))


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    auth.require_role(IC, CO, RIA)
    limit, offset = validate.pagination()
    patient_id = validate.query_str("patient_id")
    referring_hospital_id = validate.query_str("referring_hospital_id")
    drg_rate_id = validate.query_str("drg_rate_id")
    pinned_criteria_set_id = validate.query_str("pinned_criteria_set_id")
    status = validate.query_enum("status", REFERRAL_STATUSES)

    rows = list(db.referrals.values())
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if referring_hospital_id is not None:
        rows = [r for r in rows if r["referring_hospital_id"] == referring_hospital_id]
    if drg_rate_id is not None:
        rows = [r for r in rows if r["drg_rate_id"] == drg_rate_id]
    if pinned_criteria_set_id is not None:
        rows = [r for r in rows if r["pinned_criteria_set_id"] == pinned_criteria_set_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = sorted_rows(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.referral(r) for r in page], limit, offset, len(rows))


# --------------------------------------------------------------------------- #
# the screening loop
# --------------------------------------------------------------------------- #

@bp.route("/referrals/<referral_id>/screen", methods=["POST"])
def screen_referral(referral_id):
    validate.get_body()
    auth.require_role(IC)
    referral = lookup.referral(referral_id)
    if referral["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED referral may be screened.")
    criteria_set = select_effective_criteria_set()
    evaluate_screening(referral, criteria_set)
    touch(referral)
    return object_response(serialize.referral(referral))


@bp.route("/referrals/<referral_id>/submit-info", methods=["POST"])
def submit_referral_info(referral_id):
    body = validate.get_body()
    supplied = _read_screening_inputs(body)
    auth.require_role(IC)
    referral = lookup.referral(referral_id)
    if referral["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Information may be submitted only on an INFO_REQUESTED referral.")
    criteria_set = select_effective_criteria_set()

    for name in REQUIRED_SCREENING_INPUTS:
        if supplied[name] is not None:
            referral[name] = supplied[name]

    evaluate_screening(referral, criteria_set)
    touch(referral)
    return object_response(serialize.referral(referral))


@bp.route("/referrals/<referral_id>/withdraw", methods=["POST"])
def withdraw_referral(referral_id):
    validate.get_body()
    auth.require_role(IC)
    referral = lookup.referral(referral_id)
    if referral["status"] not in OPEN_REFERRAL_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "Only a RECEIVED, INFO_REQUESTED or CRITERIA_MET referral may be withdrawn.")
    referral["status"] = "WITHDRAWN"
    touch(referral)
    _decrement_open_referrals(db.patients[referral["patient_id"]])
    return object_response(serialize.referral(referral))


# --------------------------------------------------------------------------- #
# admission
# --------------------------------------------------------------------------- #

def _select_admission_period(admitted_on):
    for row in db.periods.values():
        if row["status"] != "OPEN":
            continue
        if row["start_date"] <= admitted_on <= row["end_date"]:
            return row
    return None


def _overlaps_existing_stay(patient_id, admitted_at):
    """A stay occupies the half-open interval [admitted_at, discharged_at)."""
    for row in db.stays.values():
        if row["patient_id"] != patient_id:
            continue
        if row["clinical_status"] == "RECOMBINED":
            continue
        end = row["discharged_at"]
        if end is None or admitted_at < end:
            return True
    return False


@bp.route("/referrals/<referral_id>/admit", methods=["POST"])
def admit_referral(referral_id):
    body = validate.get_body()
    admitted_at = validate.opt_datetime(body, "admitted_at")
    override_reason = validate.opt_str(body, "override_reason", min_len=0)
    auth.require_role(IC)
    referral = lookup.referral(referral_id)

    if referral["status"] != "CRITERIA_MET" and referral["status"] != "CRITERIA_NOT_MET":
        raise ApiError("ERR_INVALID_STATE", "Only a CRITERIA_MET referral may be admitted.")

    instant = now()
    if admitted_at is None:
        admitted_at = instant

    period = _select_admission_period(admitted_at.date())
    if period is None:
        raise ApiError("ERR_NO_OPEN_PERIOD",
                       "No OPEN cost reporting period covers the admission date.")

    if referral["qualifying_track"] not in ("PMV", "COMPLEX_WOUND"):
        raise ApiError("ERR_REFERRAL_NOT_ELIGIBLE",
                       "The referral does not qualify for admission on either clinical track.")

    patient = db.patients[referral["patient_id"]]
    for row in db.stays.values():
        if row["patient_id"] == patient["id"] and row["clinical_status"] in ("ADMITTED", "INTERRUPTED"):
            raise ApiError("ERR_PATIENT_ALREADY_ADMITTED",
                           "The patient already occupies a live stay.")

    if _overlaps_existing_stay(patient["id"], admitted_at):
        raise ApiError("ERR_PATIENT_STAY_OVERLAP",
                       "The admission overlaps an existing stay of the same patient.")

    hospital = db.hospitals[referral["referring_hospital_id"]]
    has_override = override_reason is not None and len(override_reason) > 0
    if hospital["monitoring_state"] == "BREACHED" and not has_override:
        raise ApiError("ERR_REFERRAL_SOURCE_BREACHED",
                       "The referring hospital is in breach; an override_reason is required.")

    if referral["prior_acute_discharge_at"] is not None \
            and admitted_at < referral["prior_acute_discharge_at"]:
        raise ApiError("ERR_ADMISSION_BEFORE_ACUTE_DISCHARGE",
                       "admitted_at precedes the referral's prior acute discharge.")
    if admitted_at > instant:
        raise ApiError("ERR_ADMISSION_IN_FUTURE",
                       "admitted_at is after the current logical instant.")

    criteria_set = db.criteria_sets.get(referral["pinned_criteria_set_id"])
    if criteria_set is not None and criteria_set["status"] == "SUPERSEDED":
        raise ApiError("ERR_CRITERIA_SET_SUPERSEDED",
                       "The referral's pinned criteria set has been superseded; re-screen it.")

    stay = new_row("stays")
    stay.update({
        "patient_id": patient["id"],
        "referral_id": referral["id"],
        "cost_reporting_period_id": period["id"],
        "interrupted_parent_stay_id": None,
        "admitted_at": admitted_at,
        "discharged_at": None,
        "resumed_at": None,
        "clinical_status": "ADMITTED",
        "payment_review_status": "PENDING",
        "carried_los_days": 0,
        "interruption_days_total": 0,
        "interruption_count": 0,
        "covered_los_days": None,
        "sso_threshold_days": None,
        "short_stay_outlier_applied": None,
        "discharge_payment_pct": None,
        "discharge_disposition": None,
        "estimated_cost_cents": None,
        "counts_toward_admission_threshold": True,
        "admitted_with_override": bool(hospital["monitoring_state"] == "BREACHED" and has_override),
        "override_reason": override_reason if has_override else None,
    })
    db.stays[stay["id"]] = stay

    referral["status"] = "ADMITTED"
    touch(referral)

    patient["open_referral_count"] = 0
    touch(patient)

    period["total_admissions"] = period["total_admissions"] + 1
    touch(period)

    hospital_version = hospital["version"]
    hospital["admissions_in_period"] = hospital["admissions_in_period"] + 1
    shares.recompute_all_shares(period)
    if hospital["version"] == hospital_version:
        touch(hospital)

    return object_response(serialize.stay(stay), 201)
