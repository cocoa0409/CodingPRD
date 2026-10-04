"""Broker licences, competitor exclusivity policies and the logical clock
(PRD 3.1, 3.4, 2.10)."""

import db
from constants import (
    LICENSE_REVOKED_REASON,
    LICENSE_TYPES,
    POLICY_STATUSES,
    RESTRICTION_SCOPES,
    UNDERWRITING_EXTENSION_DAYS,
)
from errors import ApiError
from numeric import ZERO, to_decimal
from services import shared


# ---------------------------------------------------------------------------
# BrokerLicense
# ---------------------------------------------------------------------------
def create_license(broker_id, body):
    broker = shared.get_broker(broker_id)
    state_code = shared.require_field(body, "state_code")
    license_number = shared.require_field(body, "license_number")
    license_type = shared.require_enum(body, "license_type", LICENSE_TYPES)
    expires_on_raw = shared.require_field(body, "expires_on")
    expires_on = db.parse_instant(expires_on_raw)
    if expires_on is None:
        raise ApiError("ERR_INVALID_REQUEST", "expires_on must be an ISO 8601 instant.")

    row = db.base_row()
    row.update({
        "broker_id": broker["id"],
        "state_code": state_code,
        "license_number": license_number,
        "license_type": license_type,
        "expires_on": db.format_instant(expires_on),
        "status": "ACTIVE",
        "revoked_at": None,
    })
    db.licenses[row["id"]] = row
    shared.recompute_licensed_states(broker)
    db.touch(broker)
    return row


def list_licenses(broker_id, status=None):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.licenses.values() if row["broker_id"] == broker["id"]]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return rows


def revoke_license(broker_id, license_id):
    broker = shared.get_broker(broker_id)
    license_row = shared.get_license(license_id)
    if license_row["broker_id"] != broker["id"]:
        raise ApiError("ERR_LICENSE_NOT_FOUND",
                       "License %s does not belong to broker %s." % (license_id, broker_id))

    # priority 27 - only an ACTIVE license can be revoked
    if license_row["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_REVOCABLE",
                       "The license is %s." % license_row["status"])

    license_row["status"] = "REVOKED"
    license_row["revoked_at"] = db.now_iso()
    db.touch(license_row)
    shared.recompute_licensed_states(broker)

    # cascade hop 1 -> 2: matching loans are pushed to SUSPENDED_REVIEW
    affected = []
    for loan in db.loan_submissions.values():
        if loan["broker_id"] != broker["id"]:
            continue
        if loan["property_state"] != license_row["state_code"]:
            continue
        if loan["status"] not in ("SUBMITTED", "UNDERWRITING"):
            continue
        loan["status"] = "SUSPENDED_REVIEW"
        loan["suspended_reason"] = LICENSE_REVOKED_REASON
        db.touch(loan)
        affected.append(loan)

    # cascade hop 2 -> 3: unwind the commitment and reopen resolved escalations
    for loan in affected:
        shared.reopen_resolved_escalations(loan)

    shared.recompute_compensation_commitment(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return license_row


# ---------------------------------------------------------------------------
# ExclusivityPolicy
# ---------------------------------------------------------------------------
def create_policy(body):
    broker_id = shared.require_field(body, "broker_id")
    broker = shared.get_broker(broker_id)
    competitor_identifier = shared.require_field(body, "competitor_identifier")
    competitor_name = shared.require_field(body, "competitor_name")
    effective_from_raw = shared.require_field(body, "effective_from")
    effective_to_raw = shared.require_field(body, "effective_to")

    effective_from = db.parse_instant(effective_from_raw)
    effective_to = db.parse_instant(effective_to_raw)
    if effective_from is None or effective_to is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_from and effective_to must be ISO 8601 instants.")
    if not effective_to > effective_from:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_to must be strictly after effective_from.")

    status = shared.require_enum(body, "status", POLICY_STATUSES, default="ACTIVE")
    scope = shared.require_enum(body, "restriction_scope", RESTRICTION_SCOPES,
                                default="LOAN_SUBMISSION")

    row = db.base_row()
    row.update({
        "broker_id": broker["id"],
        "competitor_identifier": competitor_identifier,
        "competitor_name": competitor_name,
        "effective_from": db.format_instant(effective_from),
        "effective_to": db.format_instant(effective_to),
        "status": status,
        "breach_count": 0,
        "restriction_scope": scope,
        "breached_loan_ids": set(),
    })
    db.exclusivity_policies[row["id"]] = row
    shared.recompute_exclusivity_status(broker)
    return row


def list_policies(broker_id, status=None):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.exclusivity_policies.values() if row["broker_id"] == broker["id"]]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return rows


def void_policy(policy_id, body):
    policy = shared.get_policy(policy_id)
    broker = shared.get_broker(policy["broker_id"])
    reason = shared.field(body, "reason", None)

    policy["status"] = "VOIDED"
    policy["void_reason"] = reason
    db.touch(policy)
    shared.recompute_exclusivity_status(broker)
    return policy


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.10)
# ---------------------------------------------------------------------------
def set_current_utc(body):
    raw = shared.require_field(body, "to_iso8601")
    target = db.parse_instant(raw)
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")

    previous = db.clock.now
    db.clock.set(target)

    licenses_expired = 0
    for row in db.licenses.values():
        if row["status"] != "ACTIVE":
            continue
        expiry = db.parse_instant(row["expires_on"])
        if expiry is not None and target >= expiry:
            row["status"] = "EXPIRED"
            db.touch(row)
            licenses_expired += 1

    escalations_opened = 0
    for loan in db.loan_submissions.values():
        escalations_opened += shared.open_escalation_if_due(loan)

    for broker in db.brokers.values():
        shared.recompute_broker_derived(broker)
        db.touch(broker)
        shared.evaluate_suspension(broker)

    _ = previous
    return {
        "current_utc": db.now_iso(),
        "licenses_expired": licenses_expired,
        "escalations_opened": escalations_opened,
    }


def extend_due_at(loan):
    """Target for a reopened escalation: due-at plus the extension window."""
    due = db.parse_instant(loan.get("underwriting_due_at"))
    if due is None:
        return None
    from datetime import timedelta
    return db.format_instant(due + timedelta(days=UNDERWRITING_EXTENSION_DAYS))


def score_or_zero(value):
    return to_decimal(value, ZERO)