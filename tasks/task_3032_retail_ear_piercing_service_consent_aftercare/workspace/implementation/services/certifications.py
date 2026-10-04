"""Certification cadence and roster discipline (PRD 2.10, 3.9)."""

import db
import errors as E
import calculations as calc
from services import common


def cumulative_score(piercer_id):
    """Cumulative chronological variant, reported beside the stored score."""
    return calc.piercer_eligibility_score(
        piercer_id, "cumulative_chronological", store=db.DB)


def issue_certification(piercer, certification_level, protocol_code,
                        issued_at, expires_at):
    record = db.CertificationRecord()
    record.piercer_id = piercer.id
    record.certification_level = certification_level
    record.sterilization_protocol_code = protocol_code
    record.issued_at = db.fmt_instant(issued_at)
    record.expires_at = db.fmt_instant(expires_at)
    record.recertification_due_at = db.fmt_instant(
        calc.certification_recertification_due(expires_at))
    record.attempted_practical_count = 0
    record.status = "VALID"
    db.DB.certifications[record.id] = record

    with db.atomic_mutation(piercer):
        _post_certification_mutation(piercer)
    return record


def revoke_certification(record, reason_code):
    if record.status not in ("VALID", "EXPIRING_SOON", "RECERTIFICATION_PENDING"):
        E.fail(E.ERR_INVALID_STATE,
               "Certification is not in a revocable state")
    record.status = "REVOKED"
    record.touch()
    piercer = db.DB.piercers.get(record.piercer_id)
    if piercer is not None:
        if record.certification_level in ("STANDARD", "SENIOR", "INSTRUCTOR"):
            if piercer.status == "ACTIVE":
                piercer.status = "SUSPENDED"
                piercer.touch()
        _post_certification_mutation(piercer)
    return record


def recertify(record, caller_id, practical_passed):
    """Submit a recertification practical assessment (PRD 3.9)."""
    status = record.status
    if status not in ("EXPIRING_SOON", "RECERTIFICATION_PENDING", "EXPIRED"):
        E.fail(E.ERR_INVALID_STATE,
               "Certification is not in a recertifiable state")

    if caller_id != record.piercer_id:
        E.fail(E.ERR_NOT_CERTIFICATION_OWNER,
               "A recertification may only be submitted by the certification owner")

    if status == "RECERTIFICATION_PENDING" and record.attempted_practical_count >= 3:
        E.fail(E.ERR_CERTIFICATION_RECERT_ATTEMPTS_EXHAUSTED,
               "Three recertification practical attempts have been consumed")
    if status == "EXPIRED" and record.attempted_practical_count >= 3:
        E.fail(E.ERR_CERTIFICATION_RECERT_ATTEMPTS_EXHAUSTED,
               "Three recertification practical attempts have been consumed")

    now = db.DB.clock

    if status == "RECERTIFICATION_PENDING":
        # Retry edge closing the renewal loop: RECERTIFICATION_PENDING -> EXPIRING_SOON
        record.status = "EXPIRING_SOON"
        record.touch()
    elif status == "EXPIRING_SOON":
        if practical_passed:
            _renew(record, now)
        else:
            record.status = "RECERTIFICATION_PENDING"
            record.attempted_practical_count += 1
            record.touch()
            if record.attempted_practical_count >= 3:
                _expire(record, level_cascade=True)
    else:  # EXPIRED
        if practical_passed:
            _renew(record, now)
        else:
            record.status = "RECERTIFICATION_PENDING"
            record.attempted_practical_count += 1
            record.touch()
            if record.attempted_practical_count >= 3:
                _expire(record, level_cascade=True)

    piercer = db.DB.piercers.get(record.piercer_id)
    if piercer is not None:
        _post_certification_mutation(piercer)
    return record


def _renew(record, now):
    record.status = "VALID"
    record.issued_at = db.fmt_instant(now)
    expires_at = db.add_months(now, db.CERTIFICATION_VALIDITY_MONTHS)
    record.expires_at = db.fmt_instant(expires_at)
    record.recertification_due_at = db.fmt_instant(
        calc.certification_recertification_due(expires_at))
    record.attempted_practical_count = 0
    record.touch()


def _expire(record, level_cascade=False):
    record.status = "EXPIRED"
    record.touch()
    if level_cascade and record.certification_level in ("STANDARD", "SENIOR", "INSTRUCTOR"):
        piercer = db.DB.piercers.get(record.piercer_id)
        if piercer is not None and piercer.status == "ACTIVE":
            piercer.status = "SUSPENDED"
            piercer.touch()


def _post_certification_mutation(piercer):
    """Recompute active_certification_id, eligibility and suspension posture."""
    common.recompute_piercer_governing_state(piercer)
    common.recompute_piercer_eligibility(piercer)
    common.evaluate_piercer_suspension(piercer)