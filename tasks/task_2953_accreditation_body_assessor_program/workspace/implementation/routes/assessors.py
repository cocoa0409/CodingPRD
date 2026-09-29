"""Assessors, declared competence, verification and impartiality (PRD 3.2, 3.3)."""

from flask import Blueprint

import calc
import domain
import store
from auth import (ASSESSMENT_MANAGER, DECISION_PANEL_MEMBER, LEAD_ASSESSOR,
                  SCHEME_MANAGER, TECHNICAL_EXPERT, endpoint)
from envelope import created, single
from errors import ApiError
from validators import (body, date_field, enum_field, int_field, string_field)

bp = Blueprint("assessors", __name__)

EMPLOYMENT_TYPES = ("INTERNAL", "CONTRACT")
ROLE_TYPES = ("LEAD_ASSESSOR", "TECHNICAL_ASSESSOR", "TECHNICAL_EXPERT")
RELATIONSHIP_TYPES = ("EMPLOYMENT", "OWNERSHIP", "FAMILY", "CONSULTANCY",
                      "TRAINING_DELIVERY", "NONE")
ASSESSOR_STATUSES = ("APPLICANT", "SCREENING", "QUALIFIED", "SUSPENDED", "WITHDRAWN")
ASSESSOR_TRANSITIONS = {
    ("QUALIFIED", "SUSPENDED"),
    ("SUSPENDED", "QUALIFIED"),
    ("QUALIFIED", "WITHDRAWN"),
    ("SUSPENDED", "WITHDRAWN"),
}


@bp.post("/accreditation/assessors")
@endpoint([ASSESSMENT_MANAGER])
def create_assessor(user_id, role):
    payload = body()
    full_name = string_field(payload, "full_name", 1, 120)
    email = string_field(payload, "email", 1, 320)
    employment_type = enum_field(payload, "employment_type", EMPLOYMENT_TYPES)
    capacity = int_field(payload, "annual_witness_capacity_days", 0, 250,
                         required=False, default=20)

    if email.count("@") != 1:
        raise ApiError("ERR_INVALID_REQUEST", "email must contain exactly one @ character")
    for existing in store.rows("assessors"):
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique")

    assessor = store.insert("assessors", {
        "full_name": full_name,
        "email": email,
        "employment_type": employment_type,
        "annual_witness_capacity_days": capacity,
        "qualification_status": "APPLICANT",
        "impartiality_status": "UNDECLARED",
        "committed_witness_days": 0,
        "available_witness_days": capacity,
        "granted_qualification_count": 0,
        "last_screened_on": None,
        "suspension_reason": None,
    })
    return created(store.public(assessor))


@bp.post("/accreditation/assessors/<assessor_id>/qualifications")
@endpoint([ASSESSMENT_MANAGER])
def create_qualification(user_id, role, assessor_id):
    payload = body()
    scheme_id = string_field(payload, "scheme_id", 1)
    role_type = enum_field(payload, "role_type", ROLE_TYPES)
    years = int_field(payload, "years_experience", 0, 50)
    witness_days = int_field(payload, "declared_witness_days", 0, 200)
    modules = int_field(payload, "declared_training_modules", 0, 20)
    last_witness_on = date_field(payload, "last_witness_on", required=False)

    assessor = domain.find("assessors", assessor_id)
    scheme = domain.find("schemes", scheme_id)

    if scheme["status"] != "PUBLISHED":
        raise ApiError("ERR_SCHEME_NOT_PUBLISHED")

    existing_all = domain.qualifications_of(assessor_id)
    for existing in existing_all:
        if existing["scheme_id"] == scheme_id and existing["role_type"] == role_type:
            raise ApiError("ERR_INVALID_REQUEST",
                           "a qualification already exists for this assessor, "
                           "programme and role_type")

    qualification = store.insert("qualifications", {
        "assessor_id": assessor_id,
        "scheme_id": scheme_id,
        "role_type": role_type,
        "years_experience": years,
        "declared_witness_days": witness_days,
        "declared_training_modules": modules,
        "last_witness_on": store.iso_date(last_witness_on) if last_witness_on else None,
        "verified_witness_days": 0,
        "verified_training_modules": 0,
        "verified_years_experience": None,
        "declared_points": None,
        "verified_points": None,
        "status": "PENDING",
        "granted_on": None,
        "expires_on": None,
        "evidence_verified_at": None,
    })
    qualification["declared_points"] = calc.to_number(
        calc.declared_points(qualification, assessor))

    if not existing_all and assessor["qualification_status"] == "APPLICANT":
        assessor["qualification_status"] = "SCREENING"
        store.touch(assessor)

    return created(store.public(qualification))


@bp.post("/accreditation/qualifications/<qualification_id>/verify-evidence")
@endpoint([SCHEME_MANAGER])
def verify_evidence(user_id, role, qualification_id):
    payload = body()
    verified_years = int_field(payload, "verified_years_experience", 0, 50)
    verified_days = int_field(payload, "verified_witness_days", 0, None)
    verified_modules = int_field(payload, "verified_training_modules", 0, None)

    qualification = domain.find("qualifications", qualification_id)
    if qualification["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a PENDING qualification may be verified")

    assessor = store.get("assessors", qualification["assessor_id"])
    scheme = store.get("schemes", qualification["scheme_id"])

    qualification["verified_years_experience"] = verified_years
    qualification["verified_witness_days"] = verified_days
    qualification["verified_training_modules"] = verified_modules
    points = calc.verified_points(qualification, assessor, store.clock_date())
    qualification["verified_points"] = calc.to_number(points)
    qualification["evidence_verified_at"] = store.now_iso()

    floor = calc.ROLE_MIN_WITNESS_DAYS[qualification["role_type"]]
    required = scheme["_points_required"]
    if points >= required and verified_days >= floor:
        granted_on = store.clock_date()
        qualification["status"] = "GRANTED"
        qualification["granted_on"] = store.iso_date(granted_on)
        qualification["expires_on"] = store.iso_date(
            store.add_days(granted_on, calc.QUALIFICATION_VALID_DAYS))
        assessor["granted_qualification_count"] += 1
        store.touch(assessor)

    store.touch(qualification)
    return single(store.public(qualification))


@bp.post("/accreditation/assessors/<assessor_id>/impartiality-declarations")
@endpoint([ASSESSMENT_MANAGER, LEAD_ASSESSOR, TECHNICAL_EXPERT, DECISION_PANEL_MEMBER])
def file_declaration(user_id, role, assessor_id):
    payload = body()
    organization_id = string_field(payload, "organization_id", 1)
    relationship_type = enum_field(payload, "relationship_type", RELATIONSHIP_TYPES)
    started_on = date_field(payload, "started_on")
    ended_on = date_field(payload, "ended_on", required=False)
    detail = string_field(payload, "detail", 1, 500, required=False)

    if ended_on is not None and ended_on < started_on:
        raise ApiError("ERR_INVALID_DATE_RANGE", "ended_on must not fall before started_on")

    assessor = domain.find("assessors", assessor_id)
    domain.find("organizations", organization_id)

    severity = calc.SEVERITY_BY_RELATIONSHIP[relationship_type]
    declaration = store.insert("declarations", {
        "assessor_id": assessor_id,
        "organization_id": organization_id,
        "relationship_type": relationship_type,
        "started_on": store.iso_date(started_on),
        "ended_on": store.iso_date(ended_on) if ended_on else None,
        "detail": detail,
        "severity_class": severity,
        "cooling_off_months": calc.COOLING_OFF_MONTHS[severity],
        "declared_by_role": role,
    }, audited=False)

    pair_rows = [d for d in store.rows("declarations")
                 if d["assessor_id"] == assessor_id
                 and d["organization_id"] == organization_id]
    if store.newest(pair_rows) is declaration and severity == "STRUCTURAL" \
            and declaration["ended_on"] is None:
        if assessor["impartiality_status"] != "RESTRICTED":
            assessor["impartiality_status"] = "RESTRICTED"
        store.touch(assessor)

    return created(store.public(declaration))


@bp.post("/accreditation/assessors/<assessor_id>/screen")
@endpoint([SCHEME_MANAGER])
def screen_assessor(user_id, role, assessor_id):
    assessor = domain.find("assessors", assessor_id)

    assessor["impartiality_status"] = calc.impartiality_standing(assessor_id)
    if assessor["qualification_status"] == "SCREENING" \
            and assessor["granted_qualification_count"] >= 1:
        assessor["qualification_status"] = "QUALIFIED"
    assessor["last_screened_on"] = store.today_iso()
    store.touch(assessor)
    return single(store.public(assessor))


@bp.post("/accreditation/assessors/<assessor_id>/status")
@endpoint([SCHEME_MANAGER])
def change_assessor_status(user_id, role, assessor_id):
    payload = body()
    to_status = enum_field(payload, "to_status", ASSESSOR_STATUSES)
    reason = string_field(payload, "reason", 1, 300,
                          required=(to_status in ("SUSPENDED", "WITHDRAWN")))

    assessor = domain.find("assessors", assessor_id)
    current = assessor["qualification_status"]
    if (current, to_status) not in ASSESSOR_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a %s assessor cannot move to %s" % (current, to_status))
    if to_status == "QUALIFIED" and assessor["granted_qualification_count"] < 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "reinstatement requires at least one GRANTED qualification")

    if to_status == "SUSPENDED":
        assessor["suspension_reason"] = reason
        assessor["qualification_status"] = "SUSPENDED"
        store.touch(assessor)
        domain.teardown_assessor(assessor, "assessor suspended")
    elif to_status == "QUALIFIED":
        assessor["suspension_reason"] = None
        assessor["qualification_status"] = "QUALIFIED"
        store.touch(assessor)
    else:
        assessor["suspension_reason"] = reason
        assessor["qualification_status"] = "WITHDRAWN"
        store.touch(assessor)
        if current == "QUALIFIED":
            domain.teardown_assessor(assessor, "assessor suspended")
        for qualification in store.ordered(domain.qualifications_of(assessor_id)):
            if qualification["status"] in ("PENDING", "GRANTED"):
                qualification["status"] = "REVOKED"
                store.touch(qualification)
        assessor["granted_qualification_count"] = 0

    return single(store.public(assessor))
