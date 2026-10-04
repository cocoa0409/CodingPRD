"""Advisor service: creation, sponsoring chains, termination cascade, remediation
(PRD §2.4, §2.9, §3.3, §3.8)."""

from db import db, ts
from errors import (
    err,
    ERR_ADVISOR_NOT_FOUND,
    ERR_DISTRICT_OFFICE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_SPONSORING_CYCLE_DETECTED,
    ERR_DUPLICATE_NATURAL_KEY,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_APPOINTMENT_NOT_APPROVED,
)
from services import derived

LIVE_CONTRACT_STATES = ("ACTIVE_TRAINING", "VALIDATING", "AT_RISK")
TERMINABLE_STATES = ("ACTIVE_TRAINING", "VALIDATING", "AT_RISK", "VALIDATED")


def get(advisor_id):
    row = db.advisors.get(advisor_id)
    if row is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % advisor_id)
    return row


def create(data):
    office_id = data.get("district_office_id")
    if office_id is None:
        raise err(ERR_DISTRICT_OFFICE_NOT_FOUND, "district_office_id is required")
    if office_id not in db.district_offices:
        raise err(ERR_DISTRICT_OFFICE_NOT_FOUND,
                  "no district office with id %s" % office_id)
    sponsor_id = data.get("sponsoring_advisor_id")
    if sponsor_id is not None and sponsor_id not in db.advisors:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % sponsor_id)
    email = data.get("email")
    if email is None:
        raise err(ERR_DUPLICATE_NATURAL_KEY, "email is required")
    for existing in db.advisors.values():
        if existing["email"] == email:
            raise err(ERR_DUPLICATE_NATURAL_KEY, "email %s is already taken" % email)

    row = {
        "full_name": data.get("full_name"),
        "email": email,
        "district_office_id": office_id,
        "sponsoring_advisor_id": sponsor_id,
        "rank": data.get("rank"),
        "contract_status": "NOT_CONTRACTED",
        "validation_posture": "VALIDATING",
        "insurance_license_status": "NONE",
        "licensing_locked": False,
        "securities_registration_status": "NONE",
        "appointment_status": "NONE",
        "team_production_cents": 0,
        "override_income_cents": 0,
        "chargeback_balance_cents": 0,
        "renewal_commission_cents": 0,
        "orphan_pool_access": False,
        "terminated_at": None,
    }
    db.stamp_create(row)
    db.insert(db.advisors, row)
    # A sponsoring chain that reaches the new advisor would be a cycle
    # (PRD §2.4). With server-minted ids this is only reachable defensively.
    if sponsor_id is not None and row["id"] in derived.chain_above(sponsor_id):
        raise err(ERR_SPONSORING_CYCLE_DETECTED,
                  "the sponsoring chain would reach the advisor itself")
    return row


def set_licensing_locked(advisor, value):
    advisor["licensing_locked"] = bool(value)
    db.touch(advisor)
    return advisor


def remediate(advisor):
    if advisor["contract_status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the advisor is terminated")
    if advisor["contract_status"] != "AT_RISK":
        raise err(ERR_INVALID_STATE, "the advisor is not AT_RISK")
    if advisor["insurance_license_status"] != "ACTIVE":
        raise err(ERR_LICENSE_NOT_ACTIVE,
                  "remediation requires an ACTIVE insurance licence")
    if advisor["appointment_status"] != "APPROVED":
        raise err(ERR_APPOINTMENT_NOT_APPROVED,
                  "remediation requires an APPROVED carrier appointment")
    contracts = [c for c in db.contracts.values()
                 if c["advisor_id"] == advisor["id"] and c["contract_status"] == "AT_RISK"]
    if not contracts:
        raise err(ERR_INVALID_STATE,
                  "no employment contract of this advisor is AT_RISK")
    for contract in contracts:
        contract["contract_status"] = "ACTIVE_TRAINING"
        db.touch(contract)
    advisor["contract_status"] = "ACTIVE_TRAINING"
    advisor["validation_posture"] = "VALIDATING"
    db.touch(advisor)
    return advisor


def terminate(advisor):
    """The broadest cascade in the system (PRD §3.8)."""
    if advisor["contract_status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the advisor is already terminated")
    if advisor["contract_status"] not in TERMINABLE_STATES:
        raise err(ERR_INVALID_STATE,
                  "an advisor who has never been contracted may not be terminated")

    now = db.now()
    advisor_id = advisor["id"]

    advisor["contract_status"] = "TERMINATED"
    advisor["validation_posture"] = "FAILED_POSTURE"
    advisor["orphan_pool_access"] = False
    advisor["terminated_at"] = ts(now)
    db.touch(advisor)

    # Contracts and their windows.
    for contract in db.contracts.values():
        if contract["advisor_id"] != advisor_id:
            continue
        if contract["contract_status"] in ("ACTIVE_TRAINING", "VALIDATING"):
            contract["contract_status"] = "TERMINATED"
            contract["end_date"] = ts(now)
            db.touch(contract)
            for period in db.validation_periods.values():
                if period["contract_id"] == contract["id"] and period["status"] in ("OPEN", "EXTENDED"):
                    period["status"] = "FAILED"
                    db.touch(period)

    # Licensing dimensions (parallel state machines).
    for lic in db.licenses.values():
        if lic["advisor_id"] == advisor_id and lic["status"] != "REVOKED":
            lic["status"] = "REVOKED"
            db.touch(lic)
    for reg in db.registrations.values():
        if reg["advisor_id"] == advisor_id and reg["status"] != "TERMINATED":
            reg["status"] = "TERMINATED"
            db.touch(reg)
    for appt in db.appointments.values():
        if appt["advisor_id"] == advisor_id and appt["appointment_status"] != "TERMINATED":
            appt["appointment_status"] = "TERMINATED"
            db.touch(appt)
    derived.refresh_license_dimension(advisor_id)
    derived.refresh_registration_dimension(advisor_id)
    derived.refresh_appointment_dimension(advisor_id)

    # Policyholder book.
    orphaned_policy_ids = set()
    for policy in db.policies.values():
        if policy["writing_advisor_id"] == advisor_id and policy["status"] in ("ISSUED", "ACTIVE"):
            policy["orphaned"] = True
            db.touch(policy)
            orphaned_policy_ids.add(policy["id"])
            assignment = {
                "policy_id": policy["id"],
                "from_advisor_id": advisor_id,
                "to_advisor_id": None,
                "assignment_method": "ROUND_ROBIN",
                "assigned_at": None,
                "status": "PENDING",
                "rejection_reason": None,
            }
            db.stamp_create(assignment)
            db.insert(db.orphans, assignment)

    # Joint work cases.
    for case in db.joint_cases.values():
        if advisor_id in (case["lead_advisor_id"], case["support_advisor_id"]) and \
                case["status"] in ("OPEN", "SUBMITTED"):
            case["status"] = "VOIDED"
            db.touch(case)

    # Renewal credits do not survive the representative.
    for credit in db.credits.values():
        if credit["advisor_id"] == advisor_id and credit["status"] == "ACCRUED" and \
                credit["credit_type"] == "RENEWAL":
            credit["status"] = "VOIDED"
            credit["gross_commission_cents"] = 0
            credit["net_commission_cents"] = 0
            db.touch(credit)

    # Rollups: override accrual is a full recomputation over live credits, so a
    # terminated descendant's contribution disappears exactly (PRD §3.6).
    derived.cascade_rollups()
    derived.recompute_chargeback_balance(advisor_id)
    for policy_id in orphaned_policy_ids:
        derived.recompute_all_chargebacks()
    return advisor