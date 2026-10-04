"""Consent instruments, guardian verification and the jurisdiction age ladder.

Implements PRD 2.4, 3.1 and 3.2.
"""

import db
import errors as E
import calculations as calc
from services import common


def capture_consent(customer, jurisdiction, consent_type, identification_type,
                    identification_number_masked, signed_at):
    record = db.ConsentRecord()
    record.customer_id = customer.id
    record.jurisdiction_id = jurisdiction.id
    record.consent_type = consent_type
    record.identification_type = identification_type
    record.identification_number_masked = identification_number_masked
    record.signed_at = db.fmt_instant(signed_at)
    record.required_identification_type = common.required_identification_type(
        customer, jurisdiction, consent_type)
    if consent_type == "SELF":
        record.guardian_verification_status = "NOT_REQUIRED"
    else:
        record.guardian_verification_status = "PENDING_VERIFICATION"
    record.consent_status = "PENDING"
    db.DB.consents[record.id] = record
    return record


def verify_consent(consent):
    """PENDING -> ACTIVE, guarded by age, guardian and identification gates."""
    if consent.consent_status != "PENDING":
        E.fail(E.ERR_INVALID_STATE, "Consent is not PENDING")

    customer = db.DB.customers.get(consent.customer_id)
    jurisdiction = db.DB.jurisdictions.get(consent.jurisdiction_id)
    if customer is None or jurisdiction is None:
        E.fail(E.ERR_NOT_FOUND, "Consent references a missing parent row")

    # Business safety: the age gate is evaluated before other business rules.
    common.enforce_age_gate(customer, jurisdiction, [consent.consent_type])

    # Business constraints: the guardian gate precedes the identification gate.
    common.enforce_guardian_gate(consent, jurisdiction)
    common.enforce_identification_gate(consent)

    consent.consent_status = "ACTIVE"
    signed_at = db.parse_instant(consent.signed_at)
    if signed_at is None:
        E.fail(E.ERR_INVALID_REQUEST, "Consent signed_at is not a valid instant")
    consent.expires_at = db.fmt_instant(
        calc.consent_expiry(signed_at))
    consent.touch()
    return consent


def reject_consent(consent, reason_code):
    if consent.consent_status != "PENDING":
        E.fail(E.ERR_INVALID_STATE, "Consent is not PENDING")
    consent.consent_status = "REJECTED"
    consent.touch()
    return consent


def revoke_consent(consent):
    if consent.consent_status != "ACTIVE":
        E.fail(E.ERR_INVALID_STATE, "Consent is not ACTIVE")
    consent.consent_status = "REVOKED"
    consent.touch()
    common.cancel_booking_rows([
        a for a in db.DB.appointments.values()
        if a.customer_id == consent.customer_id
        and a.jurisdiction_id == consent.jurisdiction_id
        and a.status in ("BOOKED", "CONFIRMED")])
    return consent


def renew_consent(consent):
    if consent.consent_status != "EXPIRED":
        E.fail(E.ERR_INVALID_STATE, "Consent is not EXPIRED")
    consent.consent_status = "PENDING"
    if consent.consent_type == "SELF":
        consent.guardian_verification_status = "NOT_REQUIRED"
    else:
        consent.guardian_verification_status = "PENDING_VERIFICATION"
    consent.touch()
    return consent


def record_guardian_verification(consent, outcome):
    """Parallel dimension: never touches consent_status (PRD 3.2)."""
    if consent.consent_type == "SELF":
        E.fail(E.ERR_INVALID_STATE, "A SELF consent has no guardian dimension")
    if consent.guardian_verification_status not in ("PENDING_VERIFICATION", "FAILED"):
        E.fail(E.ERR_INVALID_STATE,
               "Guardian verification is not PENDING_VERIFICATION or FAILED")
    if outcome not in ("VERIFIED", "FAILED"):
        E.fail(E.ERR_INVALID_REQUEST, "outcome must be VERIFIED or FAILED")
    consent.guardian_verification_status = outcome
    consent.touch()
    return consent