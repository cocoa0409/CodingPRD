"""Take-home privileges: request, evaluate, revoke (PRD 3.6, 3.7, 3.10)."""
import db
from constants import PRIVILEGE_GRANTED
from errors import ApiError
from services import carry, entity, patient_flow, program as program_svc, stability


def privilege_of(privilege_id):
    row = db.take_home_privileges.get(privilege_id)
    if row is None:
        raise ApiError("ERR_PRIVILEGE_NOT_FOUND", "No TakeHomePrivilege with the supplied id")
    return row


def patient_of(privilege):
    return db.patients.get(privilege.get("patient_id"))


def program_of(privilege):
    return db.programs.get(privilege.get("program_id"))


# ---------------------------------------------------------------------------
# request
# ---------------------------------------------------------------------------
def create_privilege(patient, requested_carries, carry_interval_days, actor, reissued_from=None):
    if requested_carries is None or requested_carries < 0:
        raise ApiError("ERR_INVALID_REQUEST", "requested_carries must be a non-negative integer")
    if (
        carry_interval_days is None
        or carry_interval_days < 1
        or carry_interval_days > 28
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "carry_interval_days must fall between 1 and 28 inclusive",
        )

    source = None
    if reissued_from:
        source = db.take_home_privileges.get(reissued_from)
        if source is None:
            raise ApiError("ERR_PRIVILEGE_NOT_FOUND", "No TakeHomePrivilege with the supplied id")
        # REVOKED -> PENDING_REVIEW preconditions (a reissue).
        if source.get("decision") != "REVOKED":
            raise ApiError(
                "ERR_REISSUE_SOURCE_NOT_REVOKED",
                "reissued_from_privilege_id names a privilege that is not REVOKED",
            )
        if patient.get("status") != "ACTIVE":
            raise ApiError("ERR_PATIENT_NOT_ACTIVE", "Patient is not ACTIVE")
        program_svc.ensure_carry_posture(db.programs.get(patient.get("program_id")))

    _ = actor
    row = entity.make_privilege(
        patient, requested_carries, carry_interval_days, reissued_from=reissued_from
    )
    db.take_home_privileges[row["id"]] = row
    row["timetable_reconciled"] = patient_flow.recompute_timetable(row, patient)
    ledger = carry.ensure_ledger_for_patient(patient)
    carry.refresh_carry_ledger(ledger, bump=True)
    carry.refresh_quota_tolerant(row["program_id"], bump=True)
    return row


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------
def evaluate(privilege, actor, body=None):
    _ = actor
    patient = patient_of(privilege)
    program = program_of(privilege)
    from services import patient as patient_svc

    patient_svc.derive_time_in_treatment(patient)
    privilege["timetable_reconciled"] = patient_flow.recompute_timetable(privilege, patient)

    # priority 7: state. Both PENDING_REVIEW and DENIED are evaluable; anything
    # else reports the stale-state code ERR_PRIVILEGE_NOT_PENDING.
    state = privilege.get("decision")
    if state not in ("PENDING_REVIEW", "DENIED"):
        raise ApiError("ERR_PRIVILEGE_NOT_PENDING", "TakeHomePrivilege is not PENDING_REVIEW")
    # priority 9: carries need a NORMAL clinic, not merely a non-FROZEN one.
    program_svc.ensure_carry_posture(program)
    # priority 10: diversion control
    if patient.get("diversion_standing") == "CONFIRMED_DIVERSION":
        raise ApiError(
            "ERR_DIVERSIONS_OR_FINDINGS_OPEN",
            "A patient under confirmed diversion may not receive a carry",
        )

    # Priority 18 then 19 then 20: the first failing condition in the declared
    # order is the one reported. A failed condition also fires the
    # PENDING_REVIEW -> DENIED transition, which releases the hold and records a
    # denial_reason_code without synthesizing any dose; the caller sees the
    # corresponding 422/402 status with the reason visible on the row.
    failure = _first_failure(patient, privilege)
    if failure is not None:
        _deny(privilege, patient, failure)
        raise ApiError(_FAILURE_ERRORS[failure], _failure_message(failure))

    requested = privilege.get("requested_carries") or 0
    cap = carry.carry_cap_waterfall(privilege, patient, privilege["program_id"])
    privilege["eligible_carry_cap"] = cap

    if cap <= 0 and requested > 0:
        # The program pool has no room to grant anything: the request is refused
        # with the resource-exhaustion code rather than granted at zero.
        _deny(privilege, patient, "CLINIC_MAX_CARRIES_EXCEEDED")
        raise ApiError(
            "ERR_PROGRAM_CARRY_QUOTA_EXHAUSTED",
            "The program's carry pool remainder is zero or negative",
        )

    privilege["decision"] = "APPROVED"
    privilege["denial_reason_code"] = None
    privilege["approved_carries"] = cap
    privilege["evaluation_basis"] = "TIME_IN_TREATMENT"
    privilege["expires_on"] = patient_svc.expiration_date_for(patient)
    # The signed ledger delta this row makes: +1 on an ordinary approval, -1 when
    # the approval is a reissue.
    privilege["hold_ledger_delta"] = -1 if privilege.get("reissued_from_privilege_id") else 1
    db.stamp(privilege)
    _release_hold(patient, privilege)
    carry.synthesize_take_home_doses(patient, privilege, cap)
    ledger = carry.ensure_ledger_for_patient(patient)
    carry.refresh_carry_ledger(ledger, bump=True)
    carry.refresh_quota_tolerant(privilege["program_id"], bump=True)
    return privilege


def _first_failure(patient, privilege):
    """The first failing approval condition in the global priority order."""
    if (patient.get("time_in_treatment_days") or 0) < 90:
        return "TIME_IN_TREATMENT_INSUFFICIENT"
    if not privilege.get("timetable_reconciled"):
        return "TIMETABLE_LOOKAHEAD_FAILED"
    if (patient.get("denial_count_12mo") or 0) > 2:
        return "ACTIVE_DENIAL_HISTORY"
    if stability.direction_b(patient) < stability.floor_for(patient):
        return "STABILITY_BELOW_THRESHOLD"
    return None


_FAILURE_ERRORS = {
    "TIME_IN_TREATMENT_INSUFFICIENT": "ERR_TIME_IN_TREATMENT_INSUFFICIENT",
    "TIMETABLE_LOOKAHEAD_FAILED": "ERR_TIMETABLE_LOOKAHEAD_FAILED",
    "ACTIVE_DENIAL_HISTORY": "ERR_ACTIVE_DENIAL_HISTORY",
    "STABILITY_BELOW_THRESHOLD": "ERR_STABILITY_BELOW_THRESHOLD",
}


def _failure_message(reason):
    return {
        "TIME_IN_TREATMENT_INSUFFICIENT": "time_in_treatment_days is below 90",
        "TIMETABLE_LOOKAHEAD_FAILED": "timetable_reconciled is false for the day before evaluation",
        "ACTIVE_DENIAL_HISTORY": "denial_count_12mo exceeds 2",
        "STABILITY_BELOW_THRESHOLD": (
            "The DIRECTION_B_TAKE_HOME_READINESS reading is below the phase floor"
        ),
    }[reason]


def _deny(privilege, patient, reason):
    """PENDING_REVIEW (or DENIED) -> DENIED, releasing the hold."""
    privilege["decision"] = "DENIED"
    privilege["denial_reason_code"] = reason
    privilege["approved_carries"] = 0
    privilege["hold_ledger_delta"] = 0
    db.stamp(privilege)
    ledger = carry.ensure_ledger_for_patient(patient)
    carry.refresh_carry_ledger(ledger, bump=True)
    carry.refresh_quota_tolerant(privilege["program_id"], bump=True)
    return privilege


def _release_hold(patient, privilege):
    ledger = carry.ensure_ledger_for_patient(patient)
    carry.refresh_carry_ledger(ledger, bump=True)
    carry.refresh_quota_tolerant(privilege["program_id"], bump=True)


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------
def revoke(privilege, actor):
    if privilege.get("decision") not in PRIVILEGE_GRANTED:
        raise ApiError(
            "ERR_PRIVILEGE_NOT_ACTIVE",
            "TakeHomePrivilege is not APPROVED or APPROVED_WITH_EXCEPTION",
        )
    _ = actor
    patient = patient_of(privilege)
    was_exception = privilege.get("decision") == "APPROVED_WITH_EXCEPTION"
    if was_exception and privilege.get("exception_id"):
        for row in db.take_home_exceptions.values():
            if row["id"] == privilege.get("exception_id") and row.get("status") == "GRANTED":
                row["status"] = "REVOKED"
                db.stamp(row)
    patient_flow.revoke_privilege(privilege, reset_phase=True, cancel_doses=True)
    if patient is not None:
        stability.refresh_patient(patient, publish="A")
    return privilege