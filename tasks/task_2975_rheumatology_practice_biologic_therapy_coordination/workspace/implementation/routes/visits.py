"""PRD 3.2: booking, check-in and disease activity scoring."""

from flask import Blueprint

import calculations as calc
import constants as C
import serializers as S
from auth import acting_role, acting_user_id, endpoint
from errors import fail
from response import created, ok
from store import bump, db, stamp_versioned
from validation import (
    q_enum,
    q_string,
    read_body,
    v_enum,
    v_instant,
    v_int,
    v_number,
    v_string,
)

from .common import paginate, resolve

bp = Blueprint("visits", __name__)

VISIT_READ_ROLES = [
    "Rheumatologist",
    "InfusionNurse",
    "RegistryAdmin",
    "PriorAuthCoordinator",
    "BenefitsCounselor",
    "Patient",
]


@bp.post("/visits")
@endpoint(["RegistryAdmin", "Rheumatologist"])
def book_visit():
    body = read_body()
    patient_id = v_string(body, "patient_id")
    clinician_id = v_string(body, "clinician_id")
    visit_datetime = v_instant(body, "visit_datetime")
    visit_type = v_enum(body, "visit_type", C.VISIT_TYPES)

    # PRD 3.2: a rheumatologist may only book their own book.
    if acting_role() == "Rheumatologist" and clinician_id != acting_user_id():
        fail("ERR_NOT_RESOURCE_OWNER")

    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_REFERENCE_NOT_FOUND", "The named patient does not exist.")
    clinician = db.clinicians.get(clinician_id)
    # A clinician_id resolving to a NURSE is refused exactly like one resolving
    # to nothing at all (PRD 3.2).
    if clinician is None or clinician["role_type"] != "RHEUMATOLOGIST":
        fail("ERR_REFERENCE_NOT_FOUND", "The named clinician cannot treat visits.")

    visit_end = calc.visit_end_datetime(visit_datetime, visit_type)
    overlapping = calc.clinician_overlapping_visit_count(
        clinician_id, visit_datetime, visit_end
    )
    if overlapping >= C.CLINICIAN_CONCURRENT_VISIT_CAP:
        fail("ERR_CLINICIAN_CAPACITY_EXCEEDED")

    row = {
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "visit_datetime": visit_datetime,
        "visit_end_datetime": visit_end,
        "visit_type": visit_type,
        "status": "SCHEDULED",
        "scoring_instrument": None,
        "tender_joint_count": None,
        "swollen_joint_count": None,
        "patient_global_assessment": None,
        "physician_global_assessment": None,
        "crp_mg_dl": None,
        "esr_mm_hr": None,
        "activity_score": None,
        "activity_category": None,
        "escalation_recommendation": None,
        "scored_at": None,
    }
    stamp_versioned(row)
    db.visits[row["id"]] = row
    return created(S.visit_out(row))


@bp.post("/visits/<visit_id>/check-in")
@endpoint(["InfusionNurse"])
def check_in(visit_id):
    visit = resolve(db.visits, visit_id, "ERR_VISIT_NOT_FOUND")
    if visit["status"] != "SCHEDULED":
        fail("ERR_VISIT_NOT_CHECKED_IN", "This visit has already left SCHEDULED.")
    visit["status"] = "CHECKED_IN"
    bump(visit)
    return ok(S.visit_out(visit))


@bp.post("/visits/<visit_id>/score")
@endpoint(["Rheumatologist"])
def score_visit(visit_id):
    # The visit must be resolved before the ownership comparison can be made at
    # all, because the comparison reads the visit's own clinician_id.
    visit = resolve(db.visits, visit_id, "ERR_VISIT_NOT_FOUND")
    if acting_user_id() != visit["clinician_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    body = read_body()
    instrument = v_enum(body, "scoring_instrument", C.SCORING_INSTRUMENTS)
    tender = v_int(body, "tender_joint_count", minimum=0, maximum=28)
    swollen = v_int(body, "swollen_joint_count", minimum=0, maximum=28)
    patient_global = v_number(body, "patient_global_assessment", minimum=0, maximum=10, max_dp=1)
    physician_global = v_number(
        body, "physician_global_assessment", required=False, minimum=0, maximum=10, max_dp=1
    )
    crp = v_number(body, "crp_mg_dl", required=False, minimum=0, max_dp=2)
    esr = v_int(body, "esr_mm_hr", required=False, minimum=0, maximum=200)

    # PRD 3.2: under CDAI all four components are required, which is a payload
    # shape rule and therefore precedes the state check.
    if instrument == "CDAI" and physician_global is None:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'physician_global_assessment' is required under the CDAI instrument.",
        )

    if visit["status"] != "CHECKED_IN":
        fail("ERR_VISIT_NOT_CHECKED_IN", "This visit is not CHECKED_IN.")

    if instrument == "DAS28_CRP" and crp is None:
        fail("ERR_ACUTE_PHASE_REACTANT_MISSING")

    if instrument == "CDAI":
        score = calc.cdai_score(tender, swollen, patient_global, physician_global)
        category = calc.cdai_category(score)
    else:
        score = calc.das28_crp_score(tender, swollen, crp, patient_global)
        category = calc.das28_category(score)

    recommendation = calc.escalation_recommendation(
        visit["patient_id"], category, visit["visit_datetime"]
    )

    visit["scoring_instrument"] = instrument
    visit["tender_joint_count"] = tender
    visit["swollen_joint_count"] = swollen
    visit["patient_global_assessment"] = patient_global
    visit["physician_global_assessment"] = physician_global
    visit["crp_mg_dl"] = crp
    visit["esr_mm_hr"] = esr
    visit["activity_score"] = score
    visit["activity_category"] = category
    visit["escalation_recommendation"] = recommendation
    visit["status"] = "SCORED"
    visit["scored_at"] = db.now()
    bump(visit)

    patient = db.patients.get(visit["patient_id"])
    if patient is not None:
        calc.project_patient_activity(patient)
        bump(patient)

    return ok(S.visit_out(visit))


@bp.get("/visits/<visit_id>")
@endpoint(VISIT_READ_ROLES)
def get_visit(visit_id):
    visit = resolve(db.visits, visit_id, "ERR_VISIT_NOT_FOUND")
    return ok(S.visit_out(visit))


@bp.get("/visits")
@endpoint(VISIT_READ_ROLES)
def list_visits():
    patient_id = q_string("patient_id")
    # PRD 2.1: a caller acting as Patient must supply their own id as the filter.
    if acting_role() == "Patient" and patient_id != acting_user_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    clinician_id = q_string("clinician_id")
    status = q_enum("status", C.VISIT_STATUSES)

    rows = []
    for visit in db.visits.values():
        if patient_id is not None and visit["patient_id"] != patient_id:
            continue
        if clinician_id is not None and visit["clinician_id"] != clinician_id:
            continue
        if status is not None and visit["status"] != status:
            continue
        rows.append(visit)
    return paginate(rows, S.visit_out)
