"""Policy writing, commission allocation, overrides and chargebacks
(PRD §3.6, §2.7 invariants, §1.3 commission_credit_allocation / chargeback_assessment).
"""

from datetime import timedelta

from db import db, ts, parse_dt
from errors import (
    err,
    ERR_POLICY_NOT_FOUND,
    ERR_ADVISOR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_REGISTRATION_NOT_ACTIVE,
    ERR_APPOINTMENT_NOT_APPROVED,
    ERR_TERMINATED_ADVISOR,
    ERR_DUPLICATE_NATURAL_KEY,
    ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS,
    ERR_REINSTATEMENT_WINDOW_CLOSED,
    ERR_RECOVERY_EXCEEDS_ASSESSED,
    ERR_CREDIT_NOT_FOUND,
)
from services import calc, derived


def get(policy_id):
    row = db.policies.get(policy_id)
    if row is None:
        raise err(ERR_POLICY_NOT_FOUND, "no policy with id %s" % policy_id)
    return row


def get_credit(credit_id):
    row = db.credits.get(credit_id)
    if row is None:
        raise err(ERR_CREDIT_NOT_FOUND, "no commission credit with id %s" % credit_id)
    return row


def _credits_of(policy_id):
    return [c for c in db.credits.values() if c["policy_id"] == policy_id]


def _credit_of_type(policy_id, credit_type):
    for credit in db.credits.values():
        if credit["policy_id"] == policy_id and credit["credit_type"] == credit_type:
            return credit
    return None


def submitted_case(policy_id):
    for case in db.joint_cases.values():
        if case["policy_id"] == policy_id and case["status"] == "SUBMITTED":
            return case
    return None


# ---------------------------------------------------------------------------
# Writing a policy (PRD §3.6)
# ---------------------------------------------------------------------------
def create(data):
    advisor_id = data.get("writing_advisor_id")
    if advisor_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "writing_advisor_id is required")
    advisor = db.advisors.get(advisor_id)
    if advisor is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % advisor_id)

    policy_number = data.get("policy_number")
    for existing in db.policies.values():
        if existing["policy_number"] == policy_number:
            raise err(ERR_DUPLICATE_NATURAL_KEY,
                      "policy_number %s is already in use" % policy_number)

    policy = {
        "policy_number": policy_number,
        "writing_advisor_id": advisor_id,
        "carrier_name": data.get("carrier_name"),
        "product_line": data.get("product_line"),
        "annual_premium_cents": int(data.get("annual_premium_cents") or 0),
        "issue_date": parse_dt(data.get("issue_date")),
        "lapse_date": None,
        "reinstatement_date": None,
        "is_advanced_commission": bool(data.get("is_advanced_commission", True)),
        "months_inforce": 0,
        "orphaned": False,
        "status": "ISSUED",
    }
    db.stamp_create(policy)
    db.insert(db.policies, policy)

    allocate_policy_credits(policy)
    derived.cascade_rollups()
    return policy


def allocate_policy_credits(policy):
    """Waterfall (PRD §3.6). The conservation invariant holds on every path."""
    case_gross = calc.case_gross_commission_cents(policy)
    case = submitted_case(policy["id"])
    primary = _credit_of_type(policy["id"], "PRIMARY")
    lead_row = _credit_of_type(policy["id"], "SPLIT_LEAD")
    support_row = _credit_of_type(policy["id"], "SPLIT_SUPPORT")

    if case is None:
        if primary is None:
            primary = _make(policy, policy["writing_advisor_id"], "PRIMARY", 1.0, case_gross)
        else:
            primary["advisor_id"] = policy["writing_advisor_id"]
            primary["credit_pct"] = 1.0
            primary["gross_commission_cents"] = case_gross
            derived.refresh_credit_amounts(primary)
            db.touch(primary)
        for row in (lead_row, support_row):
            if row is not None and row["status"] != "VOIDED":
                row["status"] = "VOIDED"
                db.touch(row)
    else:
        lead_amount, support_amount = calc.split_shares(case_gross, case["split_pct_lead"])
        if primary is not None:
            primary["credit_pct"] = 0.0
            primary["gross_commission_cents"] = 0
            primary["net_commission_cents"] = 0
            primary["status"] = "VOIDED"
            db.touch(primary)
        lead_row = _upsert_split(policy, lead_row, case["lead_advisor_id"], "SPLIT_LEAD",
                                 float(case["split_pct_lead"]), lead_amount)
        support_row = _upsert_split(policy, support_row, case["support_advisor_id"],
                                    "SPLIT_SUPPORT",
                                    float(1 - calc.d(case["split_pct_lead"])), support_amount)
    return policy


def restore_primary_credit(policy):
    """Voiding a submitted joint case restores the PRIMARY credit to
    credit_pct 1.00 with its gross recomputed to the case gross, and voids the
    two SPLIT rows (PRD §3.6)."""
    case_gross = calc.case_gross_commission_cents(policy)
    primary = _credit_of_type(policy["id"], "PRIMARY")
    if primary is not None:
        primary["credit_pct"] = 1.0
        primary["gross_commission_cents"] = case_gross
        primary["status"] = "ACCRUED"
        derived.refresh_credit_amounts(primary)
        db.touch(primary)
    for credit_type in ("SPLIT_LEAD", "SPLIT_SUPPORT"):
        row = _credit_of_type(policy["id"], credit_type)
        if row is not None and row["status"] != "VOIDED":
            row["status"] = "VOIDED"
            row["gross_commission_cents"] = 0
            row["net_commission_cents"] = 0
            db.touch(row)
    return policy


def _upsert_split(policy, row, advisor_id, credit_type, pct, amount):
    if row is None:
        return _make(policy, advisor_id, credit_type, pct, amount)
    row["advisor_id"] = advisor_id
    row["credit_pct"] = pct
    row["gross_commission_cents"] = int(amount)
    row["status"] = "ACCRUED"
    derived.refresh_credit_amounts(row)
    db.touch(row)
    return row


def _make(policy, advisor_id, credit_type, pct, amount):
    row = {
        "policy_id": policy["id"],
        "advisor_id": advisor_id,
        "credit_type": credit_type,
        "credit_pct": pct,
        "gross_commission_cents": int(amount),
        "net_commission_cents": int(amount),
        "advanced_paid_cents": 0,
        "case_gross_commission_cents": calc.case_gross_commission_cents(policy),
        "chargeback_assessed_cents": 0,
        "recovered_cents": 0,
        "chargeback_reason": None,
        "status": "ACCRUED",
    }
    db.stamp_create(row)
    db.insert(db.credits, row)
    return row


# ---------------------------------------------------------------------------
# Activation gate (PRD §3.6; error precedence §2.10 compliance sub-order)
# ---------------------------------------------------------------------------
def activate(policy):
    if policy["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the policy is terminated")
    if policy["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "the policy is not ISSUED")
    advisor = db.advisors.get(policy["writing_advisor_id"])
    if advisor is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "the writing advisor no longer exists")
    # Priority 6 — licensing compliance FIRST, then the fiscal block: PRD §2.10
    # pins that a request refused for both reports the compliance failure.
    if advisor["insurance_license_status"] != "ACTIVE":
        raise err(ERR_LICENSE_NOT_ACTIVE,
                  "the writing advisor holds no ACTIVE insurance licence")
    if policy["product_line"] == "ANNUITY" and advisor["securities_registration_status"] != "ACTIVE":
        raise err(ERR_REGISTRATION_NOT_ACTIVE,
                  "annuity business requires an ACTIVE securities registration")
    if advisor["appointment_status"] != "APPROVED":
        raise err(ERR_APPOINTMENT_NOT_APPROVED,
                  "the writing advisor holds no APPROVED carrier appointment")
    if advisor["contract_status"] == "TERMINATED":
        raise err(ERR_TERMINATED_ADVISOR, "the writing advisor is terminated")
    # Priority 8 — the fiscal block: a new business-writing request is refused
    # while the advisor's balance exceeds CHARGEBACK_BLOCK_CENTS (PRD §3.6).
    if advisor["chargeback_balance_cents"] > calc.CHARGEBACK_BLOCK_CENTS:
        raise err(ERR_CHARGEBACK_BALANCE_BLOCKS_NEW_BUSINESS,
                  "the advisor's chargeback balance blocks new business")
    policy["status"] = "ACTIVE"
    policy["months_inforce"] = 0
    db.touch(policy)
    return policy


# ---------------------------------------------------------------------------
# Lapse / chargeback cascade (PRD §3.6)
# ---------------------------------------------------------------------------
def _assess_policy_credits(policy, reason):
    """Assess every PAID/ACCRUED credit of the policy, then propagate: a
    charged-back credit first recomputes and reassesses the dependent OVERRIDE
    row of the next ancestor up the chain (PRD §3.6)."""
    months = int(policy["months_inforce"])
    is_advanced = bool(policy["is_advanced_commission"])
    surrender = reason == "SURRENDER"
    affected = set()
    for credit in _credits_of(policy["id"]):
        if credit["status"] not in ("PAID", "ACCRUED"):
            continue
        gross = int(credit["gross_commission_cents"])
        if gross <= 0:
            continue
        assessed = calc.assessed_amount(gross, months, is_advanced, surrender=surrender)
        if assessed <= 0:
            continue
        credit["chargeback_assessed_cents"] = assessed
        credit["chargeback_reason"] = reason
        credit["status"] = "CHARGED_BACK"
        derived.refresh_credit_amounts(credit)
        db.touch(credit)
        affected.add(credit["advisor_id"])
        affected.update(derived.chain_above(credit["advisor_id"]))
    for advisor_id in affected:
        derived.recompute_chargeback_balance(advisor_id)
    derived.cascade_rollups()


def lapse(policy, lapse_date):
    if policy["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the policy is terminated")
    if policy["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "the policy is not ACTIVE")
    if policy["lapse_date"] is not None and policy["reinstatement_date"] is None:
        raise err(ERR_INVALID_STATE, "the policy is already lapsed")
    end = parse_dt(lapse_date)
    policy["status"] = "LAPSED"
    policy["lapse_date"] = end
    policy["months_inforce"] = calc.completed_months(policy["issue_date"], end)
    db.touch(policy)
    _assess_policy_credits(policy, "LAPSE_WITHIN_12MO")
    return policy


def reinstate(policy):
    if policy["status"] != "LAPSED":
        raise err(ERR_INVALID_STATE, "the policy is not LAPSED")
    lapse_date = policy["lapse_date"]
    window = lapse_date + timedelta(days=calc.REINSTATEMENT_WINDOW_DAYS)
    if not db.now() < window:
        raise err(ERR_REINSTATEMENT_WINDOW_CLOSED,
                  "the reinstatement window has closed")
    policy["status"] = "ACTIVE"
    policy["reinstatement_date"] = ts(db.now())
    policy["lapse_date"] = None
    policy["months_inforce"] = 0
    db.touch(policy)
    for credit in _credits_of(policy["id"]):
        if credit["status"] == "CHARGED_BACK":
            credit["status"] = "PAID"
            credit["chargeback_assessed_cents"] = 0
            credit["chargeback_reason"] = None
            # recovered_cents is left UNCHANGED (PRD §3.6).
            derived.refresh_credit_amounts(credit)
            db.touch(credit)
    derived.recompute_all_chargebacks()
    derived.cascade_rollups()
    return policy


def surrender(policy):
    if policy["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the policy is terminated")
    if policy["status"] not in ("ACTIVE", "LAPSED"):
        raise err(ERR_INVALID_STATE, "the policy is not ACTIVE or LAPSED")
    already_assessed = policy["status"] == "LAPSED"
    policy["status"] = "SURRENDERED"
    db.touch(policy)
    if not already_assessed:
        _assess_policy_credits(policy, "SURRENDER")
    return policy


def terminate(policy):
    if policy["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the policy is terminated")
    if policy["status"] != "SURRENDERED":
        raise err(ERR_INVALID_STATE, "the policy is not SURRENDERED")
    policy["status"] = "TERMINATED"
    db.touch(policy)
    for assignment in db.orphans.values():
        if assignment["policy_id"] == policy["id"] and assignment["status"] == "PENDING":
            assignment["status"] = "REJECTED"
            assignment["rejection_reason"] = "POLICY_TERMINATED"
            db.touch(assignment)
    return policy


# ---------------------------------------------------------------------------
# Commission credit transitions (scaffold §1.2 CommissionCredit)
# ---------------------------------------------------------------------------
def pay(credit):
    if credit["status"] in ("VOIDED", "RECOVERED"):
        raise err(ERR_ALREADY_TERMINAL, "the credit is terminal")
    if credit["status"] != "ACCRUED":
        raise err(ERR_INVALID_STATE, "the credit is not ACCRUED")
    credit["status"] = "PAID"
    credit["advanced_paid_cents"] = int(credit["net_commission_cents"])
    db.touch(credit)
    return credit


def void(credit):
    if credit["status"] in ("VOIDED", "RECOVERED"):
        raise err(ERR_ALREADY_TERMINAL, "the credit is terminal")
    if credit["status"] != "ACCRUED":
        raise err(ERR_INVALID_STATE, "the credit is not ACCRUED")
    if int(credit["recovered_cents"]) != 0:
        raise err(ERR_INVALID_STATE,
                  "a credit with recovered money may not be voided")
    credit["status"] = "VOIDED"
    credit["gross_commission_cents"] = 0
    credit["net_commission_cents"] = 0
    db.touch(credit)
    derived.recompute_team_production(credit["advisor_id"])
    derived.cascade_rollups()
    return credit


def recover(credit, amount_cents):
    if credit["status"] == "RECOVERED":
        raise err(ERR_ALREADY_TERMINAL, "the credit is already recovered")
    if credit["status"] != "CHARGED_BACK":
        raise err(ERR_INVALID_STATE, "the credit is not CHARGED_BACK")
    amount = int(amount_cents)
    remainder = int(credit["chargeback_assessed_cents"]) - int(credit["recovered_cents"])
    if amount <= 0 or amount > remainder:
        raise err(ERR_RECOVERY_EXCEEDS_ASSESSED,
                  "the recovery amount exceeds the outstanding assessment")
    credit["recovered_cents"] = int(credit["recovered_cents"]) + amount
    db.touch(credit)
    derived.recompute_chargeback_balance(credit["advisor_id"])
    if int(credit["recovered_cents"]) == int(credit["chargeback_assessed_cents"]):
        credit["status"] = "RECOVERED"
        db.touch(credit)
    return credit