"""Reusable rejection-ladder guards, each pinned to its PRD rule."""
from common import fail, now, today, whole_days
from store import db

MN_NOTE_VALIDITY_DAYS = 90


def guard_clinic_accreditation(clinic):
    """Priority 28."""
    expires_on = clinic["accreditation_expires_on"]
    if expires_on is None or expires_on < today():
        fail("ERR_CLINIC_ACCREDITATION_EXPIRED")


def guard_supplier_standards(supplier):
    """Priority 29."""
    if supplier is None:
        fail("ERR_SUPPLIER_STANDARDS_NOT_ATTESTED")
    if not supplier["dmepos_standards_attested"]:
        fail("ERR_SUPPLIER_STANDARDS_NOT_ATTESTED")
    expires_on = supplier["accreditation_expires_on"]
    if expires_on is None or expires_on < today():
        fail("ERR_SUPPLIER_STANDARDS_NOT_ATTESTED")


def guard_supplier_quality(supplier):
    """Priority 30."""
    if supplier is not None and supplier["quality_hold"]:
        fail("ERR_SUPPLIER_QUALITY_HOLD")


def guard_compliance_hold(encounter):
    """Priority 31."""
    if encounter["compliance_hold"]:
        fail("ERR_COMPLIANCE_HOLD_ACTIVE")


def guard_ioas(encounter, product, clinic):
    """Priority 32."""
    if encounter["ioas_attested_at"] is None:
        fail("ERR_IOAS_SUPERVISION_MISSING")
    if product["ioas_supervision_required"] == "DIRECT":
        if clinic["ioas_supervision_level"] != "DIRECT":
            fail("ERR_IOAS_SUPERVISION_MISSING")
        if encounter["ioas_supervision_level_observed"] != "DIRECT":
            fail("ERR_IOAS_SUPERVISION_MISSING")


def guard_stark(encounter, attesting_physician_id=None):
    """Priority 34."""
    ordering = db["physicians"].get(encounter["ordering_physician_id"])
    if ordering is None:
        fail("ERR_STARK_DISCLOSURE_MISSING")
    if not ordering["group_member"]:
        fail("ERR_STARK_DISCLOSURE_MISSING")
    if not ordering["stark_disclosure_on_file"]:
        fail("ERR_STARK_DISCLOSURE_MISSING")
    if attesting_physician_id is not None:
        attesting = db["physicians"].get(attesting_physician_id)
        if attesting is None or not attesting["group_member"]:
            fail("ERR_STARK_DISCLOSURE_MISSING")


def guard_medical_necessity(encounter):
    """Priority 35."""
    for field in ("mn_signed_at", "mn_diagnosis_code", "mn_functional_deficit",
                  "mn_expected_duration_months"):
        if encounter[field] is None:
            fail("ERR_MEDICAL_NECESSITY_MISSING")
    if whole_days(encounter["mn_signed_at"], now()) > MN_NOTE_VALIDITY_DAYS:
        fail("ERR_MEDICAL_NECESSITY_MISSING")


def guard_fitter_credential(fitter):
    """Priority 36."""
    if fitter["credential"] == "NONE":
        fail("ERR_FITTER_CREDENTIAL_EXPIRED")
    expires_on = fitter["credential_expires_on"]
    if expires_on is None or expires_on < today():
        fail("ERR_FITTER_CREDENTIAL_EXPIRED")


def guard_fitter_privilege(fitter, product):
    """Priority 37."""
    if product["category"] in ("CUSTOM_FITTED_PREFAB", "CUSTOM_FABRICATED"):
        if fitter["privilege_scope"] != "CUSTOM_AND_OFF_SHELF":
            fail("ERR_FITTER_PRIVILEGE_SCOPE")


def guard_clinic_dispensing(clinic, par_level=None):
    """Priority 60."""
    status = clinic["dispensing_status"]
    if status == "SUSPENDED":
        fail("ERR_CLINIC_DISPENSING_SUSPENDED")
    if status == "RESTRICTED" and par_level is not None:
        if par_level["stock_posture"] == "STOCKOUT":
            fail("ERR_CLINIC_DISPENSING_SUSPENDED")
