"""Clinics, physicians, fitters, patients and the clinic reconciliation read."""
from flask import Blueprint

from calc import dispensing_summary
from common import (ALL_ROLES, authorize, body_json, enum_arg, fail, need_date,
                    need_enum, need_str, need_str_list, opt_bool, opt_str,
                    paginate, respond_list, respond_object)
from store import (ACCREDITATION_BODIES, CREDENTIALS, PAYER_TYPES,
                   PRIVILEGE_SCOPES, SPECIALTIES, SUPERVISION_LEVELS, clinic_json,
                   db, fitter_json, insert, lookup, patient_json, physician_json,
                   sort_created, stamp)

bp = Blueprint("clinics", __name__)


@bp.post("/dme/clinics")
def create_clinic():
    authorize(["PracticeAdmin"])
    body = body_json()
    name = need_str(body, "name", 1, 120)
    state_code = need_str(body, "state_code", 2, 2, pattern=r"^[A-Z]{2}$")
    accreditation_body = need_enum(body, "accreditation_body", ACCREDITATION_BODIES)
    accreditation_expires_on = need_date(body, "accreditation_expires_on")
    ioas_supervision_level = need_enum(body, "ioas_supervision_level", SUPERVISION_LEVELS)
    specialties = need_str_list(body, "dispensing_specialties", SPECIALTIES)
    row = stamp({
        "name": name,
        "state_code": state_code,
        "accreditation_body": accreditation_body,
        "accreditation_expires_on": accreditation_expires_on,
        "ioas_supervision_level": ioas_supervision_level,
        "dispensing_specialties": specialties,
        "dispensing_status": "ACTIVE",
        "stockout_par_level_count": 0,
    })
    insert("clinics", row)
    return respond_object(clinic_json(row), 201)


@bp.get("/dme/clinics/<clinic_id>")
def get_clinic(clinic_id):
    authorize(ALL_ROLES)
    row = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    return respond_object(clinic_json(row), 200)


@bp.get("/dme/clinics/<clinic_id>/dispensing-summary")
def get_dispensing_summary(clinic_id):
    authorize(["PracticeAdmin", "ComplianceOfficer", "InventoryManager"])
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    return respond_object(dispensing_summary(clinic), 200)


@bp.post("/dme/clinics/<clinic_id>/physicians")
def create_physician(clinic_id):
    authorize(["PracticeAdmin"])
    body = body_json()
    full_name = need_str(body, "full_name", 1, 120)
    npi = need_str(body, "npi", 10, 10, pattern=r"^\d{10}$")
    specialty = need_enum(body, "specialty", SPECIALTIES)
    group_member = opt_bool(body, "group_member", True)
    stark = opt_bool(body, "stark_disclosure_on_file", False)
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    for existing in db["physicians"].values():
        if existing["npi"] == npi:
            fail("ERR_DUPLICATE_NPI")
    row = stamp({
        "clinic_id": clinic["id"],
        "full_name": full_name,
        "npi": npi,
        "specialty": specialty,
        "group_member": group_member,
        "stark_disclosure_on_file": stark,
    })
    insert("physicians", row)
    return respond_object(physician_json(row), 201)


@bp.get("/dme/clinics/<clinic_id>/physicians")
def list_physicians(clinic_id):
    authorize(["PracticeAdmin", "ComplianceOfficer", "OrthoPhysician"])
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    specialty = enum_arg("specialty", SPECIALTIES)
    rows = [r for r in db["physicians"].values() if r["clinic_id"] == clinic["id"]]
    if specialty is not None:
        rows = [r for r in rows if r["specialty"] == specialty]
    page, pagination = paginate(sort_created(rows))
    return respond_list([physician_json(r) for r in page], pagination, 200)


@bp.post("/dme/clinics/<clinic_id>/fitters")
def create_fitter(clinic_id):
    authorize(["PracticeAdmin"])
    body = body_json()
    full_name = need_str(body, "full_name", 1, 120)
    credential = need_enum(body, "credential", CREDENTIALS)
    credential_expires_on = need_date(body, "credential_expires_on")
    privilege_scope = need_enum(body, "privilege_scope", PRIVILEGE_SCOPES)
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    row = stamp({
        "clinic_id": clinic["id"],
        "full_name": full_name,
        "credential": credential,
        "credential_expires_on": credential_expires_on,
        "privilege_scope": privilege_scope,
        "fitting_minutes_booked": 0,
    })
    insert("fitters", row)
    return respond_object(fitter_json(row), 201)


@bp.get("/dme/clinics/<clinic_id>/fitters")
def list_fitters(clinic_id):
    authorize(["PracticeAdmin", "ComplianceOfficer", "DmeFitter"])
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    privilege_scope = enum_arg("privilege_scope", PRIVILEGE_SCOPES)
    rows = [r for r in db["fitters"].values() if r["clinic_id"] == clinic["id"]]
    if privilege_scope is not None:
        rows = [r for r in rows if r["privilege_scope"] == privilege_scope]
    page, pagination = paginate(sort_created(rows))
    return respond_list([fitter_json(r) for r in page], pagination, 200)


@bp.get("/dme/fitters/<fitter_id>")
def get_fitter(fitter_id):
    authorize(["PracticeAdmin", "ComplianceOfficer", "DmeFitter"])
    row = lookup("fitters", fitter_id, "ERR_FITTER_NOT_FOUND")
    return respond_object(fitter_json(row), 200)


@bp.post("/dme/clinics/<clinic_id>/patients")
def create_patient(clinic_id):
    authorize(["PracticeAdmin", "InsuranceCoordinator"])
    body = body_json()
    full_name = need_str(body, "full_name", 1, 120)
    dob = need_date(body, "dob")
    payer_type = need_enum(body, "payer_type", PAYER_TYPES)
    member_id = opt_str(body, "member_id")
    medicare_beneficiary = opt_bool(body, "medicare_beneficiary", False)
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    row = stamp({
        "clinic_id": clinic["id"],
        "full_name": full_name,
        "dob": dob,
        "payer_type": payer_type,
        "member_id": member_id,
        "medicare_beneficiary": medicare_beneficiary,
    })
    insert("patients", row)
    return respond_object(patient_json(row), 201)


@bp.get("/dme/clinics/<clinic_id>/patients")
def list_patients(clinic_id):
    authorize(["PracticeAdmin", "InsuranceCoordinator"])
    clinic = lookup("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    payer_type = enum_arg("payer_type", PAYER_TYPES)
    rows = [r for r in db["patients"].values() if r["clinic_id"] == clinic["id"]]
    if payer_type is not None:
        rows = [r for r in rows if r["payer_type"] == payer_type]
    page, pagination = paginate(sort_created(rows))
    return respond_list([patient_json(r) for r in page], pagination, 200)
