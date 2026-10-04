"""Documented exceptions (PRD 3.9; SCAFFOLD TakeHomeException state machine)."""
import db
from constants import JUSTIFICATION_MIN
from errors import ApiError
from services import carry, entity, patient_flow, privilege as privilege_svc, program as program_svc, stability


def exception_of(exception_id):
    row = db.take_home_exceptions.get(exception_id)
    if row is None:
        raise ApiError("ERR_EXCEPTION_NOT_FOUND", "No TakeHomeException with the supplied id")
    return row


def patient_of(exception):
    return db.patients.get(exception.get("patient_id"))


def privilege_for_exception(exception_id, decisions=None):
    """The privilege whose exception_id equals this exception's identifier."""
    for row in db.take_home_privileges.values():
        if row.get("exception_id") != exception_id:
            continue
        if decisions is None or row.get("decision") in decisions:
            return row
    return None


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
def create_exception(
    patient, requested_carries, exception_type, clinical_justification, supervisor_id,
    actor, privilege=None,
):
    if clinical_justification is None or len(clinical_justification) < JUSTIFICATION_MIN:
        raise ApiError(
            "ERR_JUSTIFICATION_TOO_SHORT",
            "clinical_justification must be at least %d characters" % JUSTIFICATION_MIN,
        )
    if requested_carries is None or requested_carries < 0:
        raise ApiError("ERR_INVALID_REQUEST", "requested_carries must be a non-negative integer")
    # Segregation of duties at priority 3: the acting physician may not nominate
    # themselves as the reviewing supervisor.
    if str(supervisor_id) == str(actor.user_id):
        raise ApiError(
            "ERR_SELF_REVIEW_FORBIDDEN",
            "The acting user may not nominate themselves as the reviewer",
        )
    if privilege is None:
        raise ApiError(
            "ERR_PRIVILEGE_NOT_FOUND",
            "An exception attaches to a TakeHomePrivilege",
        )
    if privilege.get("decision") != "DENIED":
        raise ApiError(
            "ERR_PRIVILEGE_NOT_DENIED",
            "TakeHomePrivilege is not DENIED, so no exception can attach to it",
        )
    row = entity.make_exception(
        patient,
        requested_carries,
        exception_type,
        clinical_justification,
        supervisor_id,
        actor.user_id,
    )
    row["privilege_id"] = privilege["id"]
    privilege["exception_id"] = row["id"]
    db.stamp(privilege)
    db.take_home_exceptions[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------
def route(exception, actor):
    if exception.get("status") != "REQUESTED":
        raise ApiError("ERR_EXCEPTION_NOT_REQUESTED", "TakeHomeException is not REQUESTED")
    if str(exception.get("requesting_physician_id")) == str(exception.get("supervisor_id")):
        raise ApiError(
            "ERR_SELF_REVIEW_FORBIDDEN",
            "The requesting physician and the supervisor must differ",
        )
    justification = exception.get("clinical_justification") or ""
    if len(justification) < JUSTIFICATION_MIN:
        raise ApiError(
            "ERR_JUSTIFICATION_TOO_SHORT",
            "clinical_justification must be at least %d characters" % JUSTIFICATION_MIN,
        )
    patient = patient_of(exception)
    exception["status"] = "SUPERVISOR_REVIEW"
    _evaluate_domain_b(exception, actor)
    if patient is not None:
        stability.refresh_patient(patient, publish=None)
    db.stamp(exception)
    return exception


def _evaluate_domain_b(exception, actor):
    """True when the granting physician's read cleared the applicable floor."""
    patient = patient_of(exception)
    if patient is None:
        exception["evaluated_domain_b"] = False
        return False
    granting_id = exception.get("supervisor_id")
    evaluator = db.users.get(granting_id) or actor
    _ = evaluator
    exception["evaluated_domain_b"] = stability.cleared(patient)
    return exception["evaluated_domain_b"]


# ---------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------
def decide(exception, decision, granted_carries, actor):
    if exception.get("status") != "SUPERVISOR_REVIEW":
        raise ApiError(
            "ERR_EXCEPTION_NOT_AWAITING_SUPERVISOR",
            "TakeHomeException is not SUPERVISOR_REVIEW",
        )
    if str(exception.get("requesting_physician_id")) == str(actor.user_id):
        raise ApiError(
            "ERR_SELF_REVIEW_FORBIDDEN",
            "A director may never decide an exception the director authored",
        )
    if decision == "DENY":
        exception["status"] = "DENIED"
        db.stamp(exception)
        return exception
    if decision != "GRANT":
        raise ApiError("ERR_INVALID_REQUEST", "decision must be GRANT or DENY")

    patient = patient_of(exception)
    program = db.programs.get(exception.get("program_id"))
    # Priority 9 posture gate and priority 10 diversion gate precede the constraint.
    program_svc.ensure_carry_posture(program)
    if patient is not None and patient.get("diversion_standing") == "CONFIRMED_DIVERSION":
        raise ApiError(
            "ERR_DIVERSIONS_OR_FINDINGS_OPEN",
            "A patient under confirmed diversion may not receive a carry",
        )
    # Priority 19: the domain-B floor.
    if not exception.get("evaluated_domain_b"):
        raise ApiError(
            "ERR_STABILITY_BELOW_THRESHOLD",
            "evaluated_domain_b is false for this exception",
        )
    # Priority 24: the granted carries must not exceed the applicable table cap.
    # §3.9 defines that cap as the *larger* of the phase-table and
    # time-in-treatment allowances — the nested maximum is what lets an exception
    # lift a patient to whichever table treats them more generously — so a
    # MAINTENANCE patient at a low tenure is bounded by the phase table's 6, not
    # by the time table's 1.
    from services import patient as patient_svc

    if patient is not None:
        patient_svc.derive_time_in_treatment(patient)
    time_cap = carry.table_cap_time((patient or {}).get("time_in_treatment_days") or 0)
    phase_cap = carry.table_cap_phase((patient or {}).get("treatment_phase"))
    applicable_cap = max(time_cap, phase_cap)
    if granted_carries is not None and granted_carries > applicable_cap:
        raise ApiError(
            "ERR_EXCEPTION_CARRIES_EXCEED_CAP",
            "granted_carries exceeds the applicable carry-table cap",
        )
    if granted_carries is not None:
        exception["requested_carries"] = granted_carries
    # Priority 20: the pool must have a positive remainder.
    if carry.program_pool_remaining(exception["program_id"]) <= 0:
        raise ApiError(
            "ERR_PROGRAM_CARRY_QUOTA_EXHAUSTED",
            "The program's carry pool remainder is zero or negative",
        )

    cap = carry.phase_stability_exception_cap(exception, patient, exception["program_id"])
    exception["granted_carries"] = cap
    exception["status"] = "GRANTED"
    db.stamp(exception)

    linked = privilege_for_exception(exception["id"], decisions=("DENIED",))
    if linked is None:
        linked = privilege_for_exception(exception["id"])
    if linked is not None:
        linked["decision"] = "APPROVED_WITH_EXCEPTION"
        linked["approved_carries"] = cap
        linked["eligible_carry_cap"] = cap
        linked["evaluation_basis"] = "PHASE_STABILITY"
        linked["expires_on"] = patient_svc.expiration_date_for(patient)
        linked["exception_id"] = exception["id"]
        linked["hold_ledger_delta"] = 0
        db.stamp(linked)
        ledger = carry.ensure_ledger_for_patient(patient)
        carry.refresh_carry_ledger(ledger, bump=True)
        carry.synthesize_take_home_doses(patient, linked, cap)
        carry.refresh_carry_ledger(ledger, bump=True)
        carry.refresh_quota_tolerant(exception["program_id"], bump=True)
        stability.refresh_patient(patient, publish=None)
    return exception


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------
def revoke(exception, actor):
    if exception.get("status") != "GRANTED":
        raise ApiError("ERR_EXCEPTION_NOT_GRANTED", "TakeHomeException is not GRANTED")
    exception["status"] = "REVOKED"
    db.stamp(exception)
    linked = privilege_for_exception(exception["id"], decisions=("APPROVED_WITH_EXCEPTION",))
    if linked is not None:
        patient_flow.revoke_privilege(linked, reset_phase=True, cancel_doses=True)
    return exception