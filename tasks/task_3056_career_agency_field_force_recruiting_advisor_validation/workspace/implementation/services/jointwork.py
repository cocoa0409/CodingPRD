"""Joint work cases (PRD §3.6; scaffold §1.2 JointWorkCase)."""

from db import db, ts
from errors import (
    err,
    ERR_JOINT_CASE_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_ADVISOR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_SPLIT_PCT_INVALID,
    ERR_SELF_JOINT_CASE,
    ERR_JOINT_CASE_OPEN_EXISTS,
    ERR_JOINT_WORK_POSTURE_INELIGIBLE,
    ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from services import calc, derived, policies


def get(case_id):
    row = db.joint_cases.get(case_id)
    if row is None:
        raise err(ERR_JOINT_CASE_NOT_FOUND, "no joint work case with id %s" % case_id)
    return row


def _other_live_case(policy_id, exclude_id=None):
    for case in db.joint_cases.values():
        if case["id"] == exclude_id:
            continue
        if case["policy_id"] == policy_id and case["status"] in ("OPEN", "SUBMITTED"):
            return case
    return None


def create(data):
    # Body foreign keys resolve in the order the input list declares them
    # (PRD §2.4): policy_id, then lead_advisor_id, then support_advisor_id.
    policy_id = data.get("policy_id")
    if policy_id is None:
        raise err(ERR_POLICY_NOT_FOUND, "policy_id is required")
    policy = db.policies.get(policy_id)
    if policy is None:
        raise err(ERR_POLICY_NOT_FOUND, "no policy with id %s" % policy_id)
    lead_id = data.get("lead_advisor_id")
    if lead_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "lead_advisor_id is required")
    if lead_id not in db.advisors:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % lead_id)
    support_id = data.get("support_advisor_id")
    if support_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "support_advisor_id is required")
    if support_id not in db.advisors:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % support_id)

    # OCC pre-empts the state path on the pinned parent (PRD §2.6, §2.10).
    expected = data.get("expected_policy_version")
    if expected is None:
        raise err(ERR_INVALID_REQUEST, "expected_policy_version is required")
    if expected != policy["version"]:
        raise err(ERR_STALE_VERSION,
                  "the policy version has advanced since it was observed")

    if lead_id == support_id:
        raise err(ERR_SELF_JOINT_CASE,
                  "lead_advisor_id and support_advisor_id must differ")
    split = data.get("split_pct_lead")
    if split is None:
        raise err(ERR_SPLIT_PCT_INVALID, "split_pct_lead is required")
    split_dec = calc.d(split)
    if not (split_dec > 0 and split_dec <= 1):
        raise err(ERR_SPLIT_PCT_INVALID,
                  "split_pct_lead must be strictly greater than 0 and at most 1")

    if policy["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the policy is terminated")
    if _other_live_case(policy_id) is not None:
        raise err(ERR_JOINT_CASE_OPEN_EXISTS,
                  "the policy already has a joint work case in OPEN or SUBMITTED")

    case = {
        "policy_id": policy_id,
        "lead_advisor_id": lead_id,
        "support_advisor_id": support_id,
        "split_pct_lead": float(split_dec),
        "status": "OPEN",
        "submitted_at": None,
    }
    db.stamp_create(case)
    db.insert(db.joint_cases, case)
    # Opening a case increments the pinned parent's version (PRD §3.6).
    db.touch(policy)
    return case


def _posture_ok(advisor_id):
    advisor = db.advisors.get(advisor_id)
    if advisor is None:
        return False
    return advisor["validation_posture"] in ("VALIDATING", "VALIDATED")


def _balance_blocked(advisor_id):
    advisor = db.advisors.get(advisor_id)
    return advisor is not None and advisor["chargeback_balance_cents"] > calc.CHARGEBACK_BLOCK_CENTS


def submit(case, actor_id):
    # Ownership scope (PRD §2.1): X-User-ID must equal the case's lead_advisor_id.
    # Ownership is an access-control check, evaluated before the state path.
    if actor_id != case["lead_advisor_id"]:
        raise err(ERR_INSUFFICIENT_PERMISSIONS,
                  "only the lead advisor may submit this case")
    if case["status"] == "CLOSED":
        raise err(ERR_ALREADY_TERMINAL, "the case is closed")
    if case["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "the case is not OPEN")
    policy = db.policies.get(case["policy_id"])
    if policy is None:
        raise err(ERR_POLICY_NOT_FOUND, "the case's policy no longer exists")
    if policy["status"] not in ("ISSUED", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "the policy is not ISSUED or ACTIVE")
    if not _posture_ok(case["lead_advisor_id"]) or not _posture_ok(case["support_advisor_id"]):
        raise err(ERR_JOINT_WORK_POSTURE_INELIGIBLE,
                  "both advisors must be VALIDATING or VALIDATED to submit a joint case")
    if _balance_blocked(policy["writing_advisor_id"]) or \
            _balance_blocked(case["lead_advisor_id"]) or \
            _balance_blocked(case["support_advisor_id"]):
        raise err(ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS,
                  "a chargeback balance blocks new business")
    if _other_live_case(policy["id"], exclude_id=case["id"]) is not None:
        raise err(ERR_JOINT_CASE_OPEN_EXISTS,
                  "the policy already has another joint work case in OPEN or SUBMITTED")

    case["status"] = "SUBMITTED"
    case["submitted_at"] = ts(db.now())
    db.touch(case)
    policies.allocate_policy_credits(policy)
    derived.cascade_rollups()
    return case


def close(case):
    if case["status"] == "CLOSED":
        raise err(ERR_ALREADY_TERMINAL, "the case is already closed")
    if case["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "the case is not SUBMITTED")
    case["status"] = "CLOSED"
    db.touch(case)
    return case


def void(case, actor_id, role):
    policy = db.policies.get(case["policy_id"])
    if policy is None:
        raise err(ERR_POLICY_NOT_FOUND, "the case's policy no longer exists")

    if case["status"] == "VOIDED":
        raise err(ERR_ALREADY_TERMINAL, "the case is already voided")
    if case["status"] == "CLOSED":
        raise err(ERR_ALREADY_TERMINAL, "the case is closed")

    if case["status"] == "OPEN":
        if actor_id != case["lead_advisor_id"]:
            raise err(ERR_INVALID_STATE, "only the lead advisor may void this case")
    elif case["status"] == "SUBMITTED":
        # Shared power: the FinancialRep lead and a ManagingDirector.
        if role == "FinancialRep" and actor_id != case["lead_advisor_id"]:
            raise err(ERR_INVALID_STATE, "only the lead advisor may void this case")
        submitted_at = case["submitted_at"]
        if submitted_at is None:
            raise err(ERR_INVALID_STATE, "the case was never submitted")
        from db import parse_dt
        from datetime import timedelta
        window = parse_dt(submitted_at) + timedelta(days=calc.JOINT_VOID_WINDOW_DAYS)
        if db.now() > window:
            raise err(ERR_INVALID_STATE, "the void window has closed")
        for credit in db.credits.values():
            if credit["policy_id"] == policy["id"] and credit["status"] == "RECOVERED":
                raise err(ERR_INVALID_STATE,
                          "a recovered credit blocks voiding the case")
    else:
        raise err(ERR_INVALID_STATE, "the case is not OPEN or SUBMITTED")

    case["status"] = "VOIDED"
    db.touch(case)
    # Split credits are voided and the PRIMARY credit is RESTORED to credit_pct
    # 1.00 with gross_commission_cents recomputed to the case gross (PRD §3.6).
    policies.restore_primary_credit(policy)
    derived.cascade_rollups()
    return case


def reopen(case):
    if case["status"] != "VOIDED":
        raise err(ERR_INVALID_STATE, "only a voided case may be reopened")
    policy = db.policies.get(case["policy_id"])
    if policy is None:
        raise err(ERR_POLICY_NOT_FOUND, "the case's policy no longer exists")
    if policy["status"] not in ("ISSUED", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "the policy is not ISSUED or ACTIVE")
    case["status"] = "OPEN"
    case["submitted_at"] = None
    db.touch(case)
    return case