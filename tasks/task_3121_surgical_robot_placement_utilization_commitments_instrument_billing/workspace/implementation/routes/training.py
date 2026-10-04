"""Surgeon training pathway, proctor cases and credentialing evidence."""

from datetime import timedelta

from flask import Blueprint

from db import (DB, base_record, as_int, as_str, check_version, parse_iso8601,
                to_iso, touch)
from errors import ApiError
from middleware import authenticate, check_region, check_segregation
from response import success
from routes import common
from serializers import (training_record as ser_record,
                         credentialing_evidence as ser_evidence)
from services import calc, machines

bp = Blueprint("training", __name__)

EVIDENCE_TYPES = ("CREDENTIAL_LETTER", "PRIVILEGE_ATTESTATION", "PROCTOR_SIGNOFF_SET")


@bp.post("/api/accounts/<account_id>/training-records")
def create_training_record(account_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    data = common.body()
    name = common.require_str(data, "surgeon_name")
    required = common.require_int(data, "required_proctored_cases", 0)
    # surgeon_npi must be unique within the account.
    for existing in calc.training_records_of_account(account_id):
        if existing.get("surgeon_name") == name and existing.get("surgeon_npi") == name:
            raise ApiError("ERR_DUPLICATE_SURGEON_NPI")
    npi = as_str(data.get("surgeon_npi")) if data.get("surgeon_npi") else \
        "%s-%d" % (account_id.replace("-", "")[:8].upper(),
                   len(calc.training_records_of_account(account_id)) + 1)
    for existing in calc.training_records_of_account(account_id):
        if existing.get("surgeon_npi") == npi:
            raise ApiError("ERR_DUPLICATE_SURGEON_NPI")
    record = base_record({
        "hospital_account_id": account_id,
        "surgeon_name": name,
        "surgeon_npi": npi,
        "training_status": "NOT_STARTED",
        "simulation_modules_completed": as_int(data.get("simulation_modules_completed"), 0),
        "required_proctored_cases": required,
        "proctored_cases_completed": 0,
        "proctor_approval_pending": False,
        "credential_expires_utc": None,
        "evidence_required_after_utc": None,
    })
    DB.surgeon_training_records[record["id"]] = record
    machines.refresh_posture(account)
    return success(ser_record(record)), 201


@bp.get("/api/training-records")
def list_training_records():
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ClinicalOperationsLead",
                  "ComplianceOfficer"])
    records = list(DB.surgeon_training_records.values())
    account_id = common.arg("hospital_account_id")
    if account_id:
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    status = common.arg("training_status")
    if status:
        records = [r for r in records if r.get("training_status") == status]
    return common.paged(records, "surgeon_training_records")


@bp.get("/api/training-records/<record_id>")
def get_training_record(record_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "ClinicalOperationsLead",
                        "ComplianceOfficer", "Surgeon"])
    record = common.get_record(record_id)
    # A Surgeon may read only their own record.
    if ctx.role == "Surgeon" and record.get("id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return success(ser_record(record))


@bp.get("/api/accounts/<account_id>/training-records")
def list_account_training_records(account_id):
    authenticate(["PlatformAdmin", "ClinicalOperationsLead", "ComplianceOfficer"])
    common.get_account(account_id)
    records = calc.training_records_of_account(account_id)
    status = common.arg("training_status")
    if status:
        records = [r for r in records if r.get("training_status") == status]
    return common.paged(records, "surgeon_training_records")


@bp.post("/api/training-records/<record_id>/complete-simulation")
def complete_simulation(record_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    record = common.get_record(record_id)
    check_region(ctx, common.get_account(record.get("hospital_account_id")))
    data = common.body()
    if record.get("training_status") not in ("NOT_STARTED", "SIMULATION_INCOMPLETE"):
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    check_version(record, data, "expected_training_record_version")
    machines.record_complete_simulation(record, data.get("simulation_modules_completed"))
    return success(ser_record(record))


@bp.post("/api/training-records/<record_id>/begin-proctoring")
def begin_proctoring(record_id):
    ctx = authenticate(["RegionalSalesDirector"])
    record = common.get_record(record_id)
    check_region(ctx, common.get_account(record.get("hospital_account_id")))
    data = common.body()
    if record.get("training_status") != "SIMULATION_COMPLETE":
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    check_version(record, data, "expected_training_record_version")
    machines.record_begin_proctoring(record, data.get("required_proctored_cases"))
    return success(ser_record(record))


@bp.post("/api/training-records/<record_id>/proctor-cases")
def log_proctor_case(record_id):
    """Log a proctored case: the completed count rises and the approval flag is
    raised, signalling a compliance review is outstanding."""
    ctx = authenticate(["ClinicalOperationsLead"])
    record = common.get_record(record_id)
    check_region(ctx, common.get_account(record.get("hospital_account_id")))
    data = common.body()
    observation_ref = common.require_str(data, "case_observation_ref")
    occurred = common.require_dt(data, "occurred_at_utc")
    proctor = base_record({
        "surgeon_training_record_id": record.get("id"),
        "hospital_account_id": record.get("hospital_account_id"),
        "case_observation_ref": observation_ref,
        "occurred_at_utc": to_iso(occurred),
        "proctor_status": "PROCTOR_LOGGED",
    })
    DB.proctor_cases[proctor["id"]] = proctor
    record["proctored_cases_completed"] = int(record.get("proctored_cases_completed") or 0) + 1
    record["proctor_approval_pending"] = True
    touch(record)
    return success(ser_record(record)), 201


@bp.post("/api/proctor-cases/<proctor_case_id>/approve")
def approve_proctor_case(proctor_case_id):
    """Compliance approval of a logged proctor case."""
    ctx = authenticate(["ComplianceOfficer"])
    proctor = common.get_proctor_case(proctor_case_id)
    record = common.get_record(proctor.get("surgeon_training_record_id"))
    account = common.get_account(record.get("hospital_account_id"))
    data = common.body()
    # Preconditions run in the order SCAFFOLD §1.2 declares them.
    # Priority 9 — the record must still be in PROCTORING.
    if record.get("training_status") != "PROCTORING":
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    # The completed count must already have reached the proctoring requirement
    # BEFORE approval increments it.
    if not calc.proctoring_satisfied(record):
        raise ApiError("ERR_PROCTORING_CASES_INCOMPLETE")
    # Priority 16 — at least one VALID or EXPIRING_SOON evidence record.
    has_evidence = any(e.get("evidence_status") in ("VALID", "EXPIRING_SOON")
                       for e in calc.evidence_of_record(record.get("id")))
    if not has_evidence:
        raise ApiError("ERR_CREDENTIALING_EVIDENCE_REQUIRED")
    # Priority 17 — segregation of duties.
    check_segregation(ctx, account)
    check_version(record, data, "expected_training_record_version")
    proctor["proctor_status"] = "PROCTOR_APPROVED"
    touch(proctor)
    record["proctored_cases_completed"] = int(record.get("proctored_cases_completed") or 0) + 1
    record["proctor_approval_pending"] = False
    # Approval carries the record through to CREDENTIALED once the requirement
    # has been met.
    if not calc.proctoring_satisfied(record):
        touch(record)
        return success(ser_record(record))
    record["training_status"] = "CREDENTIALED"
    record["credentialed_at_utc"] = to_iso(DB.clock)
    expiry = DB.clock + timedelta(days=calc.CREDENTIAL_VALIDITY_DAYS)
    record["credential_expires_utc"] = to_iso(expiry)
    record["evidence_required_after_utc"] = to_iso(
        expiry + timedelta(days=calc.EVIDENCE_GRACE_DAYS))
    touch(record)
    machines.refresh_posture(account)
    return success(ser_record(record))


@bp.post("/api/proctor-cases/<proctor_case_id>/reject")
def reject_proctor_case(proctor_case_id):
    """Rejection is the retreat: the proctoring count resets and the record
    falls back to SIMULATION_INCOMPLETE."""
    ctx = authenticate(["ComplianceOfficer"])
    proctor = common.get_proctor_case(proctor_case_id)
    record = common.get_record(proctor.get("surgeon_training_record_id"))
    account = common.get_account(record.get("hospital_account_id"))
    data = common.body()
    if record.get("training_status") != "PROCTORING":
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    check_version(record, data, "expected_training_record_version")
    proctor["proctor_status"] = "PROCTOR_REJECTED"
    touch(proctor)
    record["proctored_cases_completed"] = 0
    record["proctor_approval_pending"] = False
    record["training_status"] = "SIMULATION_INCOMPLETE"
    touch(record)
    machines.refresh_posture(account)
    return success(ser_record(record))


# ---------------------------------------------------------------------------
# Credentialing evidence
# ---------------------------------------------------------------------------

@bp.post("/api/training-records/<record_id>/credentialing-evidence")
def attach_evidence(record_id):
    ctx = authenticate(["AccountOwner"])
    record = common.get_record(record_id)
    account = common.get_account(record.get("hospital_account_id"))
    if record.get("hospital_account_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    data = common.body()
    evidence_type = common.require_str(data, "evidence_type")
    if evidence_type not in EVIDENCE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST")
    issued = common.require_dt(data, "issued_utc")
    expires = common.require_dt(data, "expires_utc")
    # Priority 29 — issued must not be later than the clock and the end must be
    # strictly later than the start.
    if issued > DB.clock or not expires > issued:
        raise ApiError("ERR_EVIDENCE_WINDOW_INVALID")
    record_evidence = base_record({
        "surgeon_training_record_id": record.get("id"),
        "hospital_account_id": account.get("id"),
        "evidence_type": evidence_type,
        "issued_utc": to_iso(issued),
        "expires_utc": to_iso(expires),
        "evidence_status": calc.evidence_initial_status(expires),
    })
    DB.credentialing_evidence[record_evidence["id"]] = record_evidence
    return success(ser_evidence(record_evidence)), 201


@bp.get("/api/training-records/<record_id>/credentialing-evidence")
def list_record_evidence(record_id):
    ctx = authenticate(["PlatformAdmin", "ClinicalOperationsLead", "ComplianceOfficer",
                        "Surgeon"])
    record = common.get_record(record_id)
    if ctx.role == "Surgeon" and record.get("id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    records = calc.evidence_of_record(record_id)
    status = common.arg("evidence_status")
    if status:
        records = [r for r in records if r.get("evidence_status") == status]
    return common.paged(records, "credentialing_evidence")


@bp.get("/api/credentialing-evidence")
def list_evidence():
    authenticate(["PlatformAdmin", "ComplianceOfficer"])
    records = list(DB.credentialing_evidence.values())
    account_id = common.arg("hospital_account_id")
    if account_id:
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    record_id = common.arg("surgeon_training_record_id")
    if record_id:
        records = [r for r in records if r.get("surgeon_training_record_id") == record_id]
    status = common.arg("evidence_status")
    if status:
        records = [r for r in records if r.get("evidence_status") == status]
    return common.paged(records, "credentialing_evidence")


@bp.get("/api/credentialing-evidence/<evidence_id>")
def get_evidence(evidence_id):
    ctx = authenticate(["PlatformAdmin", "ClinicalOperationsLead", "ComplianceOfficer",
                        "Surgeon"])
    evidence = common.get_evidence(evidence_id)
    if ctx.role == "Surgeon" and evidence.get("surgeon_training_record_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return success(ser_evidence(evidence))


@bp.post("/api/credentialing-evidence/<evidence_id>/renew")
def renew_evidence(evidence_id):
    """Renew or revive an evidence record. EXPIRED is renewable, REVOKED is
    the only status this path refuses."""
    authenticate(["ComplianceOfficer"])
    evidence = common.get_evidence(evidence_id)
    data = common.body()
    if evidence.get("evidence_status") not in ("VALID", "EXPIRING_SOON", "EXPIRED"):
        raise ApiError("ERR_EVIDENCE_NOT_RENEWABLE")
    issued = common.require_dt(data, "issued_utc")
    expires = common.require_dt(data, "expires_utc")
    if issued <= DB.clock or not expires > issued or expires <= DB.clock:
        raise ApiError("ERR_EVIDENCE_WINDOW_INVALID")
    check_version(evidence, data, "expected_evidence_version")
    evidence["issued_utc"] = to_iso(issued)
    evidence["expires_utc"] = to_iso(expires)
    evidence["evidence_status"] = "VALID"
    touch(evidence)
    record = DB.surgeon_training_records.get(evidence.get("surgeon_training_record_id"))
    if record is not None:
        machines.refresh_posture(common.get_account(record.get("hospital_account_id")))
    return success(ser_evidence(evidence))


@bp.post("/api/credentialing-evidence/<evidence_id>/revoke")
def revoke_evidence(evidence_id):
    authenticate(["ComplianceOfficer"])
    evidence = common.get_evidence(evidence_id)
    data = common.body()
    if evidence.get("evidence_status") == "REVOKED":
        raise ApiError("ERR_EVIDENCE_NOT_RENEWABLE")
    check_version(evidence, data, "expected_evidence_version")
    evidence["evidence_status"] = "REVOKED"
    touch(evidence)
    return success(ser_evidence(evidence))


@bp.post("/api/training-records/<record_id>/trigger-reevaluation")
def trigger_reevaluation(record_id):
    """Return an expired or revoked credential to proctoring."""
    ctx = authenticate(["ClinicalOperationsLead"])
    record = common.get_record(record_id)
    check_region(ctx, common.get_account(record.get("hospital_account_id")))
    data = common.body()
    if record.get("training_status") != "CREDENTIALED":
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    expires = parse_iso8601(record.get("credential_expires_utc"))
    revoked = any(e.get("evidence_status") == "REVOKED"
                  for e in calc.evidence_of_record(record.get("id")))
    # Priority 32 — re-evaluation is only due once the credential has lapsed or
    # a REVOKED evidence exists.
    if not revoked and (expires is None or DB.clock < expires):
        raise ApiError("ERR_RECERTIFICATION_NOT_DUE")
    check_version(record, data, "expected_training_record_version")
    machines.record_trigger_reevaluation(record)
    return success(ser_record(record))