"""Payer policies, patients, clinical risk intake and the logical clock."""
from decimal import Decimal
from flask import Blueprint, request

import calc
import queries
import validate
from db import base_record, by_created_asc, db, now_iso, public, today, touch
from errors import ApiError
from middleware import (INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER, PROGRAM_ADMIN,
                        QUALITY_REVIEWER, SCHEDULER, TECHNOLOGIST, actor_id,
                        endpoint, enforce_patient_scope, is_portal)
from response import created, no_content, ok, paginated
from util import dec, fmt_date, rnd

bp = Blueprint("foundation", __name__)

SEXES = ("FEMALE", "MALE")


def _filtered(rows, filters):
    result = rows
    for param, field in filters.items():
        wanted = request.args.get(param)
        if wanted is not None and wanted != "":
            result = [row for row in result if str(row.get(field)) == wanted]
    return result


# --------------------------------------------------------------- payer policies
@bp.post("/payer-policies")
@endpoint(PROGRAM_ADMIN)
def create_payer_policy():
    body = validate.body()
    payer_code = validate.string(body, "payer_code", min_len=1, max_len=16)
    name = validate.string(body, "name", min_len=1, max_len=120)
    baseline = validate.integer(body, "baseline_screening_min_interval_months",
                                required=False, default=24, minimum=1, maximum=120)
    high_risk = validate.integer(body, "high_risk_min_interval_months",
                                 required=False, default=12, minimum=1, maximum=120)
    treatment = validate.integer(body, "treatment_monitoring_min_interval_months",
                                 required=False, default=12, minimum=1, maximum=120)
    vfa_covered = validate.boolean(body, "vfa_covered", default=True)
    height_loss = validate.number(body, "vfa_requires_height_loss_cm", required=False,
                                  default=Decimal("4.0"), minimum=0, maximum=20,
                                  max_places=1)
    grace_days = validate.integer(body, "repeat_scan_grace_days", required=False,
                                  default=30, minimum=0, maximum=180)
    lifetime_cap = validate.integer(body, "max_lifetime_screening_scans", required=False,
                                    default=6, minimum=1, maximum=40)
    appeal_allowed = validate.boolean(body, "appeal_allowed", default=False)

    for row in db.payer_policies.values():
        if row["payer_code"] == payer_code:
            raise ApiError("ERR_PAYER_CODE_TAKEN", "That payer_code is already registered.")

    record = base_record(versioned=False)
    record.update({
        "payer_code": payer_code,
        "name": name,
        "baseline_screening_min_interval_months": baseline,
        "high_risk_min_interval_months": high_risk,
        "treatment_monitoring_min_interval_months": treatment,
        "vfa_covered": vfa_covered,
        "vfa_requires_height_loss_cm": height_loss,
        "repeat_scan_grace_days": grace_days,
        "max_lifetime_screening_scans": lifetime_cap,
        "appeal_allowed": appeal_allowed,
    })
    db.payer_policies[record["id"]] = record
    return created(public(record))


@bp.get("/payer-policies/<policy_id>")
@endpoint(PROGRAM_ADMIN, SCHEDULER, INTERPRETING_PHYSICIAN)
def get_payer_policy(policy_id):
    return ok(public(queries.fetch("payer_policies", policy_id)))


@bp.get("/payer-policies")
@endpoint(PROGRAM_ADMIN, SCHEDULER, INTERPRETING_PHYSICIAN)
def list_payer_policies():
    rows = _filtered(list(db.payer_policies.values()), {"payer_code": "payer_code"})
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return paginated(rows, public)


# --------------------------------------------------------------------- patients
@bp.post("/patients")
@endpoint(SCHEDULER, PROGRAM_ADMIN)
def create_patient():
    body = validate.body()
    mrn = validate.string(body, "mrn", min_len=1, max_len=24)
    policy_id = validate.string(body, "primary_payer_policy_id")
    birth_date = validate.date_field(body, "birth_date")
    sex = validate.enum(body, "sex", SEXES)
    postmenopausal = validate.boolean(body, "postmenopausal", default=False)
    height = validate.number(body, "baseline_height_cm", minimum=80, maximum=230,
                             min_exclusive=True, max_places=1)
    if birth_date >= today():
        validate.bad("birth_date must be strictly earlier than the logical clock date.")

    queries.fetch("payer_policies", policy_id)
    for row in db.patients.values():
        if row["mrn"] == mrn:
            raise ApiError("ERR_MRN_TAKEN", "That mrn is already registered.")

    record = base_record()
    record.update({
        "mrn": mrn,
        "primary_payer_policy_id": policy_id,
        "birth_date": fmt_date(birth_date),
        "sex": sex,
        "postmenopausal": postmenopausal,
        "baseline_height_cm": height,
        "open_scheduled_order_count": 0,
        "lifetime_screening_scan_count": 0,
        "baseline_report_id": None,
        "last_finalized_report_id": None,
        "current_screening_interval_months": None,
        "next_eligible_scan_date": None,
        "_birth_date": birth_date,
    })
    db.patients[record["id"]] = record
    return created(public(record))


@bp.get("/patients/<patient_id>")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, QUALITY_REVIEWER,
          INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER)
def get_patient(patient_id):
    record = queries.patient(patient_id)
    enforce_patient_scope(record["id"])
    return ok(public(record))


@bp.get("/patients")
@endpoint(PROGRAM_ADMIN, SCHEDULER, INTERPRETING_PHYSICIAN)
def list_patients():
    rows = _filtered(list(db.patients.values()), {
        "primary_payer_policy_id": "primary_payer_policy_id",
        "baseline_report_id": "baseline_report_id",
        "last_finalized_report_id": "last_finalized_report_id",
        "mrn": "mrn",
    })
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return paginated(rows, public)


# ------------------------------------------------------- risk factor profiles
@bp.post("/patients/<patient_id>/risk-factor-profiles")
@endpoint(SCHEDULER, INTERPRETING_PHYSICIAN)
def create_risk_factor_profile(patient_id):
    body = validate.body()
    expected_version = validate.integer(body, "expected_patient_version")
    height = validate.number(body, "height_cm", minimum=80, maximum=230,
                             min_exclusive=True, max_places=1)
    weight = validate.number(body, "weight_kg", minimum=20, maximum=300,
                             min_exclusive=True, max_places=1)
    flags = {}
    for field, _weight in calc.CRF_POINTS:
        flags[field] = validate.boolean(body, field, default=False)
    alcohol = validate.number(body, "alcohol_units_per_day", required=False,
                              default=Decimal("0"), minimum=0, maximum=40, max_places=1)

    patient = queries.patient(patient_id)
    if expected_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION",
                       "expected_patient_version does not match the patient's version.")

    metres = height / dec(100)
    bmi = rnd(weight / (metres * metres), 2)
    height_loss = rnd(dec(patient["baseline_height_cm"]) - height, 1)
    count = sum(1 for field, _w in calc.CRF_POINTS if flags[field])
    if alcohol >= calc.ALCOHOL_RISK_MIN_UNITS:
        count += 1

    for existing in queries.risk_profiles_of_patient(patient_id):
        if existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    record = base_record()
    record.update({
        "patient_id": patient_id,
        "status": "ACTIVE",
        "recorded_at_utc": now_iso(),
        "height_cm": height,
        "weight_kg": weight,
        "bmi": bmi,
        "height_loss_cm": height_loss,
        "alcohol_units_per_day": alcohol,
        "clinical_risk_factor_count": count,
    })
    record.update(flags)
    db.risk_factor_profiles[record["id"]] = record
    touch(patient)
    return created(public(record))


@bp.get("/patients/<patient_id>/risk-factor-profiles")
@endpoint(PROGRAM_ADMIN, SCHEDULER, INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER)
def list_risk_factor_profiles(patient_id):
    patient = queries.patient(patient_id)
    enforce_patient_scope(patient["id"])
    rows = _filtered(queries.risk_profiles_of_patient(patient_id), {"status": "status"})
    rows.sort(key=lambda row: (row["recorded_at_utc"], row["created_at"], row["_seq"]),
              reverse=True)
    return paginated(rows, public)


# ------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
@endpoint(PROGRAM_ADMIN, SCHEDULER, TECHNOLOGIST, QUALITY_REVIEWER,
          INTERPRETING_PHYSICIAN, PATIENT_PORTAL_USER)
def set_clock():
    body = validate.body()
    moment = validate.instant_field(body, "to_iso8601")
    db.clock = moment
    return no_content()
