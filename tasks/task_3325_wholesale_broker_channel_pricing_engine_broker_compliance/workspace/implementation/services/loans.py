"""Loan submission, the compensation election, the underwriting loop and the
closing pipeline (PRD 3.6, 3.7, 3.8)."""

from datetime import timedelta

import db
from constants import (
    BORROWER_PAID_RATE_IMPACT,
    CLOSING_PATH_ESCALATION,
    CLOSING_PATH_STANDARD,
    CLOSING_TURN_DAYS,
    DECISION_TYPES,
    ELECTION_BORROWER_PAID,
    ELECTION_LENDER_PAID,
    ELECTION_UNDECIDED,
    LENDER_PAID_RATE_IMPACT,
    LOAN_WITHDRAWABLE_STATUSES,
    NEAR_DEADLINE_WINDOW_DAYS,
    OPEN_DEFECT_DEADLINE_DAYS,
    QC_DEFECT_HOLD_NOTE,
    UNDERWRITING_TURN_DAYS,
)
from errors import ApiError
from numeric import ZERO, round_half_up, to_decimal
from services import finance, pricing, shared


# ---------------------------------------------------------------------------
# compensation_split (PRD 3.6)
# ---------------------------------------------------------------------------
def apply_compensation_split(loan, plan, election):
    """Returns the delta to add to the broker's commitment."""
    previous_lender_paid = int(loan.get("lender_paid_comp_cents") or 0)
    if election == ELECTION_LENDER_PAID:
        loan["lender_paid_comp_cents"] = int(plan["lender_paid_amount_cents"])
        loan["borrower_paid_comp_cents"] = 0
    elif election == ELECTION_BORROWER_PAID:
        loan["lender_paid_comp_cents"] = 0
        loan["borrower_paid_comp_cents"] = int(plan["borrower_paid_amount_cents"])
    else:
        loan["lender_paid_comp_cents"] = 0
        loan["borrower_paid_comp_cents"] = 0

    if election == ELECTION_UNDECIDED:
        loan["rate_impact_pct"] = ZERO
    elif election == plan["default_election"]:
        loan["rate_impact_pct"] = ZERO
    elif election == ELECTION_LENDER_PAID:
        loan["rate_impact_pct"] = LENDER_PAID_RATE_IMPACT
    else:
        loan["rate_impact_pct"] = BORROWER_PAID_RATE_IMPACT

    quote = shared.get_quote(loan["pricing_quote_id"])
    quote_note = to_decimal(quote["note_rate_pct"], ZERO)
    if election == ELECTION_UNDECIDED:
        loan["final_note_rate_pct"] = quote_note
    else:
        loan["final_note_rate_pct"] = round_half_up(quote_note + loan["rate_impact_pct"], 3)
    return int(loan["lender_paid_comp_cents"]) - previous_lender_paid


def validate_plan_for_election(broker_id, plan_id, election):
    """Priority 17: the plan must be ACTIVE, own-broker, and default-matching."""
    plan = db.compensation_plans.get(plan_id)
    if plan is None or plan["broker_id"] != broker_id:
        raise ApiError("ERR_PLAN_NOT_FOUND",
                       "comp_plan_id %s names no plan of broker %s." % (plan_id, broker_id))
    if not plan["is_active"]:
        raise ApiError("ERR_COMPENSATION_PLAN_MISMATCH",
                       "The nominated compensation plan is not ACTIVE.")
    if plan["default_election"] != election:
        raise ApiError("ERR_COMPENSATION_PLAN_MISMATCH",
                       "The plan default %s does not equal the elected value %s."
                       % (plan["default_election"], election))
    return plan


# ---------------------------------------------------------------------------
# Eligibility envelope (PRD 3.3)
# ---------------------------------------------------------------------------
def eligibility_covers(broker_id, product_code, loan_amount_cents, ltv_ratio, representative_fico):
    for row in db.product_eligibilities.values():
        if row["broker_id"] != broker_id:
            continue
        if row["status"] != "APPROVED":
            continue
        if row["product_code"] != product_code:
            continue
        if int(loan_amount_cents) > int(row["max_loan_amount_cents"]):
            continue
        if to_decimal(ltv_ratio, ZERO) > to_decimal(row["max_ltv"], ZERO):
            continue
        if int(representative_fico) < int(row["min_fico"]):
            continue
        return row
    return None


# ---------------------------------------------------------------------------
# Loan submission
# ---------------------------------------------------------------------------
def create_loan_submission(caller, body):
    broker_id = shared.require_field(body, "broker_id")

    # priority 3 - existence, checked left to right
    broker = shared.get_broker(broker_id)
    quote = shared.get_quote(shared.require_field(body, "pricing_quote_id"))
    if quote["broker_id"] != broker["id"]:
        raise ApiError("ERR_QUOTE_NOT_FOUND",
                       "pricing_quote_id %s belongs to another broker." % quote["id"])

    # priority 11 - exclusivity breach
    disclosed = shared.field(body, "competitor_channel_identifier", None)
    if disclosed:
        policy = pricing.find_active_policy_by_competitor(broker["id"], disclosed)
        if policy is not None:
            pricing.record_breach(policy)
            shared.recompute_exclusivity_status(broker)
            raise ApiError("ERR_EXCLUSIVITY_POLICY_BREACH",
                           "competitor_channel_identifier is listed on an ACTIVE policy.")

    # priority 12 - scope-restricted broker
    if shared.exclusivity_scope_covers(broker, "LOAN_SUBMISSION"):
        raise ApiError("ERR_BROKER_EXCLUSIVITY_RESTRICTED",
                       "The breached policy's restriction_scope covers loan submission.")

    property_state = shared.field(body, "property_state", None)
    loan_amount_raw = to_decimal(shared.field(body, "loan_amount_cents", None))

    # priority 13 - licence coverage (the case-sensitive USPS code decides)
    shared.recompute_licensed_states(broker)
    if property_state is None or property_state not in broker["licensed_states"]:
        raise ApiError("ERR_PROPERTY_STATE_NOT_LICENSED",
                       "property_state %s is not covered by an unexpired license."
                       % property_state)

    # priority 14 - the approved product envelope, read off the immutable quote
    ltv_ratio = to_decimal(quote["ltv_ratio"], ZERO)
    if loan_amount_raw is None:
        loan_amount_raw = to_decimal(quote["loan_amount_cents"], ZERO)
    if eligibility_covers(broker["id"], quote["product_code"], loan_amount_raw,
                          ltv_ratio, quote["representative_fico"]) is None:
        raise ApiError("ERR_PRODUCT_NOT_ELIGIBLE",
                       "No APPROVED ProductEligibility covers this submission.")

    # priority 15 - the sheet must still be PUBLISHED
    if not pricing.quote_sheet_is_live(quote):
        raise ApiError("ERR_PRICING_QUOTE_SUPERSEDED",
                       "The quote's rate sheet is no longer PUBLISHED.")

    # priority 29 - body well-formedness
    borrower_name = shared.require_field(body, "borrower_name")
    loan_amount_cents = shared.require_int(body, "loan_amount_cents")
    lock_expires_at_raw = shared.require_field(body, "lock_expires_at")

    election = shared.field(body, "compensation_election", ELECTION_UNDECIDED)
    if election is None:
        election = ELECTION_UNDECIDED
    if election not in (ELECTION_LENDER_PAID, ELECTION_BORROWER_PAID, ELECTION_UNDECIDED):
        raise ApiError("ERR_INVALID_REQUEST",
                       "compensation_election %r is not a declared value." % election)
    plan_id = shared.field(body, "comp_plan_id", None)

    # priority 17 - plan consistency, only when a decided election is supplied
    plan = None
    if election != ELECTION_UNDECIDED:
        if not plan_id:
            raise ApiError("ERR_COMPENSATION_PLAN_MISMATCH",
                           "A decided election requires a comp_plan_id.")
        plan = validate_plan_for_election(broker["id"], plan_id, election)

    # priority 31 - the acting-brokerage ownership rule, after the business
    # catalogue and before the broker-standing gate (PRD 2.11)
    if caller.role == "BrokerUser" and caller.user_id != broker["id"]:
        raise ApiError("ERR_BROKER_RESOURCE_FORBIDDEN",
                       "BrokerUser %s may not submit for broker %s."
                       % (caller.user_id, broker["id"]))

    # priority 34 - broker standing is the final business gate
    if broker["status"] != "APPROVED":
        raise ApiError("ERR_BROKER_NOT_APPROVED",
                       "Broker %s is %s." % (broker["id"], broker["status"]))

    lock_expires_at = db.parse_instant(lock_expires_at_raw)
    if lock_expires_at is None:
        raise ApiError("ERR_INVALID_REQUEST", "lock_expires_at must be an ISO 8601 instant.")
    if not lock_expires_at > db.clock.now:
        raise ApiError("ERR_INVALID_REQUEST",
                       "lock_expires_at must be strictly after the logical clock.")

    row = db.base_row()
    row.update({
        "broker_id": broker["id"],
        "pricing_quote_id": quote["id"],
        "comp_plan_id": plan_id if election != ELECTION_UNDECIDED else None,
        "borrower_name": borrower_name,
        "property_state": property_state,
        "loan_amount_cents": loan_amount_cents,
        "lock_expires_at": db.format_instant(lock_expires_at),
        "competitor_channel_identifier": disclosed,
        "compensation_election": election,
        "lender_paid_comp_cents": 0,
        "borrower_paid_comp_cents": 0,
        "rate_impact_pct": ZERO,
        "final_note_rate_pct": to_decimal(quote["note_rate_pct"], ZERO),
        "defect_remediation_open": False,
        "status": "SUBMITTED",
        "closing_path": None,
        "submitted_at": db.now_iso(),
        "underwriting_due_at": shared.current_underwriting_deadline(),
        "closing_due_at": None,
        "cleared_at": None,
        "suspended_reason": None,
        "repurchase_exposure_cents": 0,
    })
    if plan is not None:
        apply_compensation_split(row, plan, election)
    else:
        apply_compensation_split(row, {"lender_paid_amount_cents": 0,
                                       "borrower_paid_amount_cents": 0,
                                       "default_election": ELECTION_UNDECIDED},
                                 ELECTION_UNDECIDED)

    db.loan_submissions[row["id"]] = row
    shared.recompute_compensation_commitment(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return row


def elect_compensation(loan_id, caller, body):
    loan = shared.get_loan(loan_id)
    broker = shared.get_broker(loan["broker_id"])

    election = shared.require_enum(
        body, "compensation_election",
        [ELECTION_LENDER_PAID, ELECTION_BORROWER_PAID, ELECTION_UNDECIDED])
    plan_id = shared.field(body, "comp_plan_id", None)

    # priority 17 - plan consistency
    plan = validate_plan_for_election(broker["id"], plan_id, election)

    # priority 18 - the election window and the no-op rule
    if loan["status"] != "SUBMITTED":
        raise ApiError("ERR_COMPENSATION_ELECTION_IMMUTABLE",
                       "The loan has left SUBMITTED and its election is frozen.")
    if loan["compensation_election"] == election:
        raise ApiError("ERR_COMPENSATION_ELECTION_IMMUTABLE",
                       "The election already carries the value %s." % election)

    # priority 31 - the acting-brokerage ownership rule follows the catalogue
    if caller.role == "BrokerUser" and caller.user_id != broker["id"]:
        raise ApiError("ERR_BROKER_RESOURCE_FORBIDDEN",
                       "BrokerUser %s may not act on this loan." % caller.user_id)

    delta = apply_compensation_split(loan, plan, election)
    loan["comp_plan_id"] = plan_id
    db.touch(loan)
    broker["total_active_compensation_commitment_cents"] = (
        int(broker["total_active_compensation_commitment_cents"]) + delta)
    db.touch(broker)
    return loan


def withdraw_loan(loan_id, caller):
    loan = shared.get_loan(loan_id)
    broker = shared.get_broker(loan["broker_id"])

    # priority 19 - status precondition
    if loan["status"] not in LOAN_WITHDRAWABLE_STATUSES:
        raise ApiError("ERR_LOAN_NOT_WITHDRAWABLE",
                       "A loan in status %s cannot be withdrawn." % loan["status"])

    # priority 31 - the acting-brokerage ownership rule follows the catalogue
    if caller.role == "BrokerUser" and caller.user_id != broker["id"]:
        raise ApiError("ERR_BROKER_RESOURCE_FORBIDDEN",
                       "BrokerUser %s may not withdraw this loan." % caller.user_id)

    loan["status"] = "WITHDRAWN"
    db.touch(loan)
    shared.recompute_compensation_commitment(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return loan


def resubmit_loan(loan_id, caller, body):
    loan = shared.get_loan(loan_id)
    broker = shared.get_broker(loan["broker_id"])

    # priority 33 - only a loan in SUSPENDED_REVIEW may be resubmitted
    if loan["status"] != "SUSPENDED_REVIEW":
        raise ApiError("ERR_LOAN_NOT_SUSPENDED",
                       "A loan in status %s cannot be resubmitted." % loan["status"])

    note = shared.field(body, "resubmission_note", None)
    if not note or not str(note).strip():
        raise ApiError("ERR_INVALID_REQUEST", "resubmission_note is required.")

    # priority 31 - the acting-brokerage ownership rule follows the catalogue
    if caller.role == "BrokerUser" and caller.user_id != broker["id"]:
        raise ApiError("ERR_BROKER_RESOURCE_FORBIDDEN",
                       "BrokerUser %s may not resubmit this loan." % caller.user_id)

    loan["status"] = "SUBMITTED"
    loan["submitted_at"] = db.now_iso()
    loan["underwriting_due_at"] = shared.current_underwriting_deadline()
    db.touch(loan)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return loan


def underwrite_loan(loan_id, body):
    loan = shared.get_loan(loan_id)
    broker = shared.get_broker(loan["broker_id"])

    # priority 4 - broker version guard, before the loan's state preconditions
    if not isinstance(body, dict) or "expected_broker_version" not in body:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_broker_version is required on this endpoint.")
    expected = body.get("expected_broker_version")
    if expected is None or int(expected) != int(broker["version"]):
        raise ApiError("ERR_STALE_VERSION",
                       "expected_broker_version %r no longer matches version %s."
                       % (expected, broker["version"]))

    # priority 19 - loan state
    if loan["status"] != "SUBMITTED":
        raise ApiError("ERR_LOAN_NOT_SUBMITTED",
                       "A loan in status %s cannot enter underwriting." % loan["status"])

    # priority 20 - the election must be decided
    if loan["compensation_election"] == ELECTION_UNDECIDED:
        raise ApiError("ERR_COMPENSATION_ELECTION_PENDING",
                       "The compensation election is still UNDECIDED.")

    # priority 16 then 7 - broker standing
    if broker["status"] != "APPROVED":
        raise ApiError("ERR_BROKER_NOT_APPROVED",
                       "Broker %s is %s." % (broker["id"], broker["status"]))
    if broker["exclusivity_status"] == "BLOCKED":
        raise ApiError("ERR_BROKER_EXCLUSIVITY_BLOCKED",
                       "A BLOCKED broker may not move a loan into underwriting.")

    loan["status"] = "UNDERWRITING"
    loan["submitted_at"] = db.now_iso()
    loan["underwriting_due_at"] = shared.current_underwriting_deadline()
    db.touch(loan)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return loan


# ---------------------------------------------------------------------------
# Underwriting decisions (PRD 3.7)
# ---------------------------------------------------------------------------
def create_underwriting_decision(caller, body):
    loan = shared.get_loan(shared.require_field(body, "loan_submission_id"))
    broker = shared.get_broker(loan["broker_id"])

    decision_type = shared.require_enum(body, "decision_type", DECISION_TYPES)
    conditions = shared.field(body, "conditions", None)
    decision_notes = shared.field(body, "decision_notes", None)

    # priority 19 - the loan must be UNDERWRITING
    if loan["status"] != "UNDERWRITING":
        raise ApiError("ERR_LOAN_NOT_UNDERWRITING",
                       "A loan in status %s cannot take an underwriting decision." % loan["status"])

    # priority 29 - a CONDITIONAL decision needs its conditions
    if decision_type == "CONDITIONAL":
        if not isinstance(conditions, list) or len(conditions) == 0:
            raise ApiError("ERR_DECISION_CONDITIONS_REQUIRED",
                           "A CONDITIONAL decision requires a non-empty conditions array.")

    existing = [row for row in db.underwriting_decisions.values()
                if row["loan_submission_id"] == loan["id"]]
    is_first_decision = len(existing) == 0

    row = db.base_row()
    row.update({
        "loan_submission_id": loan["id"],
        "broker_id": broker["id"],
        "underwriter_id": caller.user_id,
        "decision_type": decision_type,
        "conditions": list(conditions) if isinstance(conditions, list) else [],
        "decision_notes": decision_notes,
        "decided_at": db.now_iso(),
        "is_final": False,
    })

    if decision_type == "CONDITIONAL":
        row["is_final"] = True
        db.underwriting_decisions[row["id"]] = row
        loan["status"] = "CONDITIONAL_APPROVAL"
        loan["underwriting_due_at"] = shared.current_underwriting_deadline()
    elif decision_type == "APPROVED":
        row["is_final"] = True
        db.underwriting_decisions[row["id"]] = row
        loan["status"] = "CONDITIONAL_APPROVAL"
        loan["underwriting_due_at"] = shared.current_underwriting_deadline()
    elif decision_type == "DENIED":
        row["is_final"] = True
        db.underwriting_decisions[row["id"]] = row
        loan["status"] = "DENIED"
    else:  # SUSPENDED
        row["is_final"] = True
        db.underwriting_decisions[row["id"]] = row
        loan["status"] = "SUSPENDED_REVIEW"
        if int(broker["open_defect_tier"]) >= 1:
            auto = db.base_row()
            auto.update({
                "loan_submission_id": loan["id"],
                "broker_id": broker["id"],
                "underwriter_id": caller.user_id,
                "decision_type": "SUSPENDED",
                "conditions": [],
                "decision_notes": QC_DEFECT_HOLD_NOTE,
                "decided_at": db.now_iso(),
                "is_final": False,
            })
            db.underwriting_decisions[auto["id"]] = auto
            loan["underwriting_due_at"] = shared.current_defect_deadline()
            if is_first_decision:
                broker["suspended_reason"] = QC_DEFECT_HOLD_NOTE
        else:
            loan["underwriting_due_at"] = shared.current_underwriting_deadline()

    db.touch(loan)
    # DENIED and SUSPENDED_REVIEW both leave the SUBMITTED / UNDERWRITING /
    # CONDITIONAL_APPROVAL commitment cohort (PRD 2.5), so the lender-paid
    # commitment is re-derived from the loan rows on every decision.
    shared.recompute_compensation_commitment(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return row


# ---------------------------------------------------------------------------
# Clear to close and funding (PRD 3.8)
# ---------------------------------------------------------------------------
def clear_to_close(loan_id):
    loan = shared.get_loan(loan_id)
    broker = shared.get_broker(loan["broker_id"])

    # priority 19
    if loan["status"] != "CONDITIONAL_APPROVAL":
        raise ApiError("ERR_LOAN_NOT_CONDITIONAL",
                       "A loan in status %s cannot be cleared to close." % loan["status"])
    # priority 21
    if loan["defect_remediation_open"]:
        raise ApiError("ERR_DEFECT_REMEDIATION_OPEN",
                       "An OPEN defect finding blocks clear-to-close.")
    # priority 22
    if shared.has_open_escalation(loan["id"], stage="CLOSING"):
        raise ApiError("ERR_CLOSING_ESCALATION_OPEN",
                       "An OPEN CLOSING escalation blocks clear-to-close.")

    loan["status"] = "CLEAR_TO_CLOSE"
    loan["cleared_at"] = db.now_iso()
    loan["closing_due_at"] = shared.current_closing_deadline()
    loan["closing_path"] = (
        CLOSING_PATH_ESCALATION if shared.has_any_escalation(loan["id"])
        else CLOSING_PATH_STANDARD
    )
    db.touch(loan)
    # CLEAR_TO_CLOSE is outside the commitment cohort (PRD 2.5).
    shared.recompute_compensation_commitment(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return loan


def fund_loan(loan_id):
    loan = shared.get_loan(loan_id)
    broker = shared.get_broker(loan["broker_id"])

    # priority 19
    if loan["status"] != "CLEAR_TO_CLOSE":
        raise ApiError("ERR_LOAN_NOT_CLEAR_TO_CLOSE",
                       "A loan in status %s cannot be funded." % loan["status"])
    # priority 21
    if loan["defect_remediation_open"]:
        raise ApiError("ERR_DEFECT_REMEDIATION_OPEN",
                       "An OPEN defect finding blocks funding.")
    # priority 22
    if shared.has_open_escalation(loan["id"]):
        raise ApiError("ERR_CLOSING_ESCALATION_OPEN",
                       "An OPEN TurnTimeEscalation blocks funding.")
    # priority 16
    if broker["status"] != "APPROVED":
        raise ApiError("ERR_BROKER_NOT_APPROVED",
                       "Broker %s is %s." % (broker["id"], broker["status"]))

    loan["status"] = "FUNDED"
    db.touch(loan)
    shared.recompute_compensation_commitment(broker)
    shared.recompute_rolling_funded_volume(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return loan


# ---------------------------------------------------------------------------
# Closing pipeline read (PRD 3.8)
# ---------------------------------------------------------------------------
def closing_pipeline(broker_id=None):
    escalated = []
    standard = []
    near_deadline = 0
    horizon = db.clock.advance_days(NEAR_DEADLINE_WINDOW_DAYS)
    for row in db.loan_submissions.values():
        if broker_id is not None and row["broker_id"] != broker_id:
            continue
        if row["status"] != "CLEAR_TO_CLOSE":
            continue
        if row["closing_path"] == CLOSING_PATH_ESCALATION:
            escalated.append(row)
        elif row["closing_path"] == CLOSING_PATH_STANDARD:
            standard.append(row)
        due = db.parse_instant(row.get("closing_due_at"))
        if due is not None and db.clock.now <= due <= horizon:
            near_deadline += 1
    escalated.sort(key=lambda row: (row["created_at"], row["id"]))
    standard.sort(key=lambda row: (row["created_at"], row["id"]))
    return {
        "escalated_count": len(escalated),
        "standard_count": len(standard),
        "near_deadline_count": near_deadline,
        "escalated_loan_ids": [row["id"] for row in escalated],
        "standard_loan_ids": [row["id"] for row in standard],
    }


# ---------------------------------------------------------------------------
# Turn-time escalations (PRD 2.6, 3.7)
# ---------------------------------------------------------------------------
def resolve_escalation(escalation_id, body):
    escalation = shared.get_escalation(escalation_id)

    # priority 27 - must still be OPEN
    if escalation["status"] != "OPEN":
        raise ApiError("ERR_ESCALATION_ALREADY_RESOLVED",
                       "The escalation is already resolved.")

    # priority 29 - the note is mandatory and at least ten characters
    note = shared.field(body, "resolution_note", None)
    if not note or len(str(note).strip()) < 10:
        raise ApiError("ERR_INVALID_REQUEST",
                       "resolution_note must be present and at least 10 characters.")

    escalation["status"] = "RESOLVED"
    escalation["resolved_at"] = db.now_iso()
    escalation["resolution_note"] = str(note).strip()
    db.touch(escalation)

    loan = db.loan_submissions.get(escalation["loan_submission_id"])
    if loan is not None:
        if escalation["stage"] == "UNDERWRITING" and loan["status"] in (
                "UNDERWRITING", "CONDITIONAL_APPROVAL"):
            loan["underwriting_due_at"] = shared.current_underwriting_deadline()
            db.touch(loan)
        broker = db.brokers.get(loan["broker_id"])
        if broker is not None:
            db.touch(broker)
    return escalation


def schedule_receipt(namespace):
    """Utility kept for symmetry: no scheduled task is registered anywhere."""
    return dict(namespace)


def turn_days():
    return (UNDERWRITING_TURN_DAYS, CLOSING_TURN_DAYS, OPEN_DEFECT_DEADLINE_DAYS)


def deadline_after(days):
    return db.format_instant(db.clock.now + timedelta(days=days))