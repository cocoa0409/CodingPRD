"""PRD 3.1 reference data, plus the patient read and the quality report."""

import re

from flask import Blueprint

import calculations as calc
import constants as C
import serializers as S
from auth import endpoint, require_patient_ownership
from errors import fail
from response import created, ok
from store import bump, db, stamp_versioned
from validation import (
    q_instant,
    read_body,
    v_bool,
    v_date,
    v_enum,
    v_enum_array,
    v_int,
    v_number,
    v_string,
)

from .common import patient_or_404, unique_or_409

bp = Blueprint("reference", __name__)

MRN_PATTERN = re.compile(r"^[A-Z0-9]{6,12}$")
NPI_PATTERN = re.compile(r"^[0-9]{10}$")

STAFF_AND_PATIENT = [
    "Rheumatologist",
    "InfusionNurse",
    "PriorAuthCoordinator",
    "BenefitsCounselor",
    "PayerReviewer",
    "RegistryAdmin",
    "Patient",
]


@bp.post("/patients")
@endpoint(["RegistryAdmin"])
def create_patient():
    body = read_body()
    mrn = v_string(body, "mrn", min_len=6, max_len=12, pattern=MRN_PATTERN)
    full_name = v_string(body, "full_name", min_len=1, max_len=120)
    date_of_birth = v_date(body, "date_of_birth")
    diagnosis_code = v_enum(body, "diagnosis_code", C.DIAGNOSIS_CODES)
    registry_consent = v_bool(body, "registry_consent")

    unique_or_409(db.patients, "mrn", mrn)

    # PRD 3.1: a patient is born with every derived field at its floor.
    row = {
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "diagnosis_code": diagnosis_code,
        "registry_consent": registry_consent,
        "latest_activity_score": None,
        "latest_activity_category": None,
        "target_status": "UNASSESSED",
        "administered_dose_total": 0,
        "active_episode_count": 0,
    }
    stamp_versioned(row)
    db.patients[row["id"]] = row
    return created(S.patient_out(row))


@bp.post("/clinicians")
@endpoint(["RegistryAdmin"])
def create_clinician():
    body = read_body()
    npi = v_string(body, "npi", min_len=10, max_len=10, pattern=NPI_PATTERN)
    full_name = v_string(body, "full_name", min_len=1, max_len=120)
    role_type = v_enum(body, "role_type", C.CLINICIAN_ROLE_TYPES)
    can_attest = v_bool(body, "can_attest_formulary_exception", required=False, default=False)

    unique_or_409(db.clinicians, "npi", npi)

    row = {
        "npi": npi,
        "full_name": full_name,
        "role_type": role_type,
        "can_attest_formulary_exception": can_attest,
    }
    stamp_versioned(row)
    db.clinicians[row["id"]] = row
    return created(S.clinician_out(row))


@bp.post("/drugs")
@endpoint(["RegistryAdmin"])
def create_drug():
    body = read_body()
    name = v_string(body, "name", min_len=1, max_len=80)
    molecule_class = v_enum(body, "molecule_class", C.MOLECULE_CLASSES)
    route = v_enum(body, "route", C.ROUTES)
    formulary_tier = v_int(body, "formulary_tier", minimum=1, maximum=5)
    acquisition_cost_cents = v_int(body, "acquisition_cost_cents", minimum=1)
    admin_time_minutes = v_int(body, "admin_time_minutes", minimum=0, maximum=600)
    panel_type = v_enum(body, "monitoring_panel_type", C.PANEL_TYPES)
    interval_days = v_int(body, "monitoring_panel_interval_days", minimum=1, maximum=730)
    # PRD 3.1: both screening flags default to TRUE -- the safe default is to
    # demand the screen.
    tb_required = v_bool(body, "tb_screen_required", required=False, default=True)
    hbv_required = v_bool(body, "hbv_screen_required", required=False, default=True)
    is_biosimilar = v_bool(body, "is_biosimilar", required=False, default=False)
    step_classes = v_enum_array(
        body, "step_therapy_required_classes", C.MOLECULE_CLASSES, default=[]
    )

    unique_or_409(db.drugs, "name", name)

    row = {
        "name": name,
        "molecule_class": molecule_class,
        "route": route,
        "is_biosimilar": is_biosimilar,
        "formulary_tier": formulary_tier,
        "acquisition_cost_cents": acquisition_cost_cents,
        "admin_time_minutes": admin_time_minutes,
        "monitoring_panel_type": panel_type,
        "monitoring_panel_interval_days": interval_days,
        "tb_screen_required": tb_required,
        "hbv_screen_required": hbv_required,
        "step_therapy_required_classes": step_classes,
    }
    stamp_versioned(row)
    db.drugs[row["id"]] = row
    return created(S.drug_out(row))


@bp.post("/payer-plans")
@endpoint(["RegistryAdmin"])
def create_payer_plan():
    body = read_body()
    name = v_string(body, "name", min_len=1, max_len=80)
    pharmacy = v_bool(body, "pharmacy_benefit_enabled")
    medical = v_bool(body, "medical_benefit_enabled")
    policy = v_enum(body, "site_of_care_policy", C.SITE_OF_CARE_POLICIES)
    coinsurance_pct = v_number(body, "coinsurance_pct", minimum=0, maximum=1, max_dp=3)
    deductible = v_int(body, "deductible_remaining_cents", minimum=0)
    facility_fee = v_int(body, "medical_facility_fee_cents", minimum=0)
    multiplier = v_number(body, "hospital_outpatient_multiplier", minimum=1, max_dp=2)
    appeal_rounds = v_int(body, "appeal_rounds_allowed", minimum=0, maximum=3)
    validity_days = v_int(body, "auth_validity_days", minimum=1, maximum=730)
    step_classes = v_enum_array(
        body, "step_therapy_classes_required", C.MOLECULE_CLASSES, default=[]
    )

    unique_or_409(db.payer_plans, "name", name)

    row = {
        "name": name,
        "pharmacy_benefit_enabled": pharmacy,
        "medical_benefit_enabled": medical,
        "site_of_care_policy": policy,
        "coinsurance_pct": coinsurance_pct,
        "deductible_remaining_cents": deductible,
        "medical_facility_fee_cents": facility_fee,
        "hospital_outpatient_multiplier": multiplier,
        "appeal_rounds_allowed": appeal_rounds,
        "auth_validity_days": validity_days,
        "step_therapy_classes_required": step_classes,
    }
    stamp_versioned(row)
    db.payer_plans[row["id"]] = row
    return created(S.payer_plan_out(row))


@bp.post("/infusion-chairs")
@endpoint(["RegistryAdmin"])
def create_chair():
    body = read_body()
    label = v_string(body, "label", min_len=1, max_len=40)
    site_type = v_enum(body, "site_type", C.SITE_TYPES)
    buffer_minutes = v_int(body, "turnover_buffer_minutes", minimum=0, maximum=240)

    unique_or_409(db.chairs, "label", label)

    row = {
        "label": label,
        "site_type": site_type,
        "turnover_buffer_minutes": buffer_minutes,
        "status": "OPEN",
    }
    stamp_versioned(row)
    db.chairs[row["id"]] = row
    return created(S.chair_out(row))


@bp.patch("/infusion-chairs/<chair_id>")
@endpoint(["RegistryAdmin"])
def patch_chair(chair_id):
    # PRD 2.10 rule 11: the chair id is settled before the payload is read.
    chair = db.chairs.get(chair_id)
    if chair is None:
        fail("ERR_CHAIR_NOT_FOUND")
    body = read_body()
    status = v_enum(body, "status", C.CHAIR_STATUSES)
    chair["status"] = status
    bump(chair)
    return ok(S.chair_out(chair))


@bp.get("/patients/<patient_id>")
@endpoint(STAFF_AND_PATIENT)
def get_patient(patient_id):
    # PRD 2.10: ownership (rule 4) precedes existence (rule 5), and here the
    # comparison is path-id against header so it can be made first.
    require_patient_ownership(patient_id)
    patient = patient_or_404(patient_id)
    return ok(S.patient_out(patient))


@bp.get("/patients/<patient_id>/quality-report")
@endpoint(["RegistryAdmin", "Rheumatologist"])
def quality_report(patient_id):
    patient = patient_or_404(patient_id)
    period_start = q_instant("period_start")
    period_end = q_instant("period_end")
    # PRD 3.9: the consent check precedes the empty-window check.
    if not patient["registry_consent"]:
        fail("ERR_REGISTRY_CONSENT_MISSING")
    return ok(calc.quality_report(patient, period_start, period_end))
