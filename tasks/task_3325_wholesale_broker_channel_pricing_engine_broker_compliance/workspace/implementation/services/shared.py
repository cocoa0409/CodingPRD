"""Cross-resource helpers: field access, derived-field reconciliation,
exclusivity derivation, suspension evaluation and turn-time escalation opening.
"""

from datetime import timedelta

import db
from constants import (
    BLOCKED_AT_BREACHED_POLICIES,
    CLOSING_TURN_DAYS,
    DEFECT_SUSPENSION_TIER,
    EXCLUSIVITY_BLOCKED,
    EXCLUSIVITY_CLEAR,
    EXCLUSIVITY_RESTRICTED,
    EXCLUSIVITY_WARNED,
    FINANCIAL_SUSPENSION_THRESHOLD,
    LOAN_ACTIVE_STATUSES,
    LOAN_COMMITMENT_STATUSES,
    LOAN_STATUSES,
    OPEN_DEFECT_DEADLINE_DAYS,
    QUALITY_SUSPENSION_THRESHOLD,
    REPURCHASE_WINDOW_DAYS,
    RESTRICTED_AT_BREACHED_POLICIES,
    SUSPENSION_REASON_DEFECTS,
    SUSPENSION_REASON_EXCLUSIVITY,
    SUSPENSION_REASON_FINANCIAL,
    SUSPENSION_REASON_QUALITY,
    TIER_MULTIPLIERS,
    UNDERWRITING_EXTENSION_DAYS,
    UNDERWRITING_TURN_DAYS,
    WARNED_AT_BREACHED_POLICIES,
)
from errors import ApiError
from numeric import ZERO, to_decimal
import serializers


def field(body, name, default=None):
    if not isinstance(body, dict):
        return default
    value = body.get(name, default)
    if isinstance(value, str):
        value = value.strip()
        if value == "" and default is not None:
            return default
    return value


def require_field(body, name):
    value = field(body, name, None)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "The field '%s' is required." % name)
    return value


def require_enum(body, name, allowed, default=None):
    value = field(body, name, default)
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' has an unknown value %r; expected one of %s." % (name, value, allowed),
        )
    return value


def require_int(body, name, default=None):
    value = field(body, name, default)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "The field '%s' is required." % name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return value


def optional_int(body, name, default=None):
    value = field(body, name, None)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return value


def require_decimal(body, name):
    raw = field(body, name, None)
    if raw is None:
        raise ApiError("ERR_INVALID_REQUEST", "The field '%s' is required." % name)
    value = to_decimal(raw)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    return value


def optional_decimal(body, name, default=None):
    raw = field(body, name, None)
    if raw is None:
        return default
    value = to_decimal(raw)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    return value


def require_bool(body, name, default=None):
    value = field(body, name, None)
    if value is None:
        if default is None:
            raise ApiError("ERR_INVALID_REQUEST", "The field '%s' is required." % name)
        return default
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def optional_bool(body, name, default=None):
    value = field(body, name, None)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


# ---------------------------------------------------------------------------
# Lookups (priority 3 - existence)
# ---------------------------------------------------------------------------
def get_broker(broker_id):
    row = db.brokers.get(broker_id)
    if row is None:
        raise ApiError("ERR_BROKER_NOT_FOUND", "No broker with id %s." % broker_id)
    return row


def get_license(license_id):
    row = db.licenses.get(license_id)
    if row is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND", "No license with id %s." % license_id)
    return row


def get_financial_review(review_id):
    row = db.financial_reviews.get(review_id)
    if row is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", "No financial review with id %s." % review_id)
    return row


def get_eligibility(eligibility_id):
    row = db.product_eligibilities.get(eligibility_id)
    if row is None:
        raise ApiError("ERR_ELIGIBILITY_NOT_FOUND", "No product eligibility with id %s." % eligibility_id)
    return row


def get_policy(policy_id):
    row = db.exclusivity_policies.get(policy_id)
    if row is None:
        raise ApiError("ERR_INVALID_REQUEST", "No exclusivity policy with id %s." % policy_id)
    return row


def get_rate_sheet(sheet_id):
    row = db.rate_sheets.get(sheet_id)
    if row is None:
        raise ApiError("ERR_RATE_SHEET_NOT_FOUND", "No rate sheet with id %s." % sheet_id)
    return row


def get_quote(quote_id):
    row = db.pricing_quotes.get(quote_id)
    if row is None:
        raise ApiError("ERR_QUOTE_NOT_FOUND", "No pricing quote with id %s." % quote_id)
    return row


def get_loan(loan_id):
    row = db.loan_submissions.get(loan_id)
    if row is None:
        raise ApiError("ERR_LOAN_NOT_FOUND", "No loan submission with id %s." % loan_id)
    return row


def get_plan(plan_id):
    row = db.compensation_plans.get(plan_id)
    if row is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "No compensation plan with id %s." % plan_id)
    return row


def get_escalation(escalation_id):
    row = db.turn_time_escalations.get(escalation_id)
    if row is None:
        raise ApiError("ERR_ESCALATION_NOT_FOUND", "No turn-time escalation with id %s." % escalation_id)
    return row


def get_quality_review(review_id):
    row = db.quality_control_reviews.get(review_id)
    if row is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", "No quality control review with id %s." % review_id)
    return row


# ---------------------------------------------------------------------------
# Derived-field reconciliation (PRD 2.10, 2.5, 3.4)
# ---------------------------------------------------------------------------
def recompute_licensed_states(broker):
    states = set()
    for row in db.licenses.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] != "ACTIVE":
            continue
        expiry = db.parse_instant(row["expires_on"])
        if expiry is not None and expiry > db.clock.now:
            states.add(row["state_code"])
    broker["licensed_states"] = sorted(states)


def recompute_approved_product_codes(broker):
    codes = set()
    for row in db.product_eligibilities.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] == "APPROVED":
            codes.add(row["product_code"])
    broker["approved_product_codes"] = sorted(codes)


# ---------------------------------------------------------------------------
# Derived loan cohorts (active_loan_count_derivation, PRD 2.5)
# ---------------------------------------------------------------------------
def recompute_active_loan_count(broker):
    count = 0
    for row in db.loan_submissions.values():
        if row["broker_id"] == broker["id"] and row["status"] in LOAN_ACTIVE_STATUSES:
            count += 1
    broker["active_loan_count"] = count


def recompute_compensation_commitment(broker):
    total = 0
    for row in db.loan_submissions.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] in LOAN_COMMITMENT_STATUSES:
            total += int(row["lender_paid_comp_cents"])
    broker["total_active_compensation_commitment_cents"] = total


# ---------------------------------------------------------------------------
# funded_volume_rollup (PRD 2.5, 3.9).
#
# Every loan that reaches FUNDED contributes its loan_amount_cents exactly
# once; a repurchase stops the row from contributing, which is precisely the
# "reduced by the loan's loan_amount_cents" step. Loans in any other status
# contribute zero.
# ---------------------------------------------------------------------------
def recompute_rolling_funded_volume(broker):
    total = 0
    for row in db.loan_submissions.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] == "FUNDED":
            total += int(row["loan_amount_cents"])
    broker["rolling_funded_volume_cents"] = total


def funded_volume_before_repurchase(broker, loan):
    """The pool read BEFORE the repurchase decrement, including this loan."""
    total = 0
    for row in db.loan_submissions.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] == "FUNDED":
            total += int(row["loan_amount_cents"])
    return total


def recompute_open_defect_tier(broker):
    from services import quality
    broker["open_defect_tier"] = quality.count_open_defects(broker["id"])


def breached_policy_count(broker):
    seen = 0
    for row in db.exclusivity_policies.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] in ("ACTIVE", "SUPERSEDED") and int(row["breach_count"]) >= 1:
            seen += 1
    return seen


def recompute_exclusivity_status(broker, touch_broker=True):
    count = breached_policy_count(broker)
    if count == 0:
        status = EXCLUSIVITY_CLEAR
    elif count == WARNED_AT_BREACHED_POLICIES:
        status = EXCLUSIVITY_WARNED
    elif count == RESTRICTED_AT_BREACHED_POLICIES:
        status = EXCLUSIVITY_RESTRICTED
    else:
        status = EXCLUSIVITY_BLOCKED
    broker["exclusivity_status"] = status
    recompute_exclusivity_scope(broker)
    if touch_broker:
        db.touch(broker)
    evaluate_suspension(broker)
    return status


def recompute_exclusivity_scope(broker):
    """Scopes covered by the breaches that escalated this broker.

    The broker-wide flag the operations consult is BroadestScopeCovered: when
    any breached policy carries a broad scope, that scope governs. A
    LOAN_SUBMISSION scope covers LOAN_SUBMISSION and RATE_LOCK; an ALL scope
    covers both."""
    scopes = set()
    for row in db.exclusivity_policies.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        if int(row["breach_count"]) < 1:
            continue
        scopes.add(row["restriction_scope"])
    broker["exclusivity_scopes_covered"] = sorted(scopes)


def exclusivity_scope_covers(broker, operation):
    scopes = broker.get("exclusivity_scopes_covered") or []
    if broker["exclusivity_status"] != EXCLUSIVITY_RESTRICTED:
        return False
    for scope in scopes:
        if scope == "ALL":
            return True
        if scope == operation:
            return True
    return False


# ---------------------------------------------------------------------------
# Suspension triggers (PRD 2.4)
# ---------------------------------------------------------------------------
def suspension_trigger_reason(broker):
    quality = to_decimal(broker["rolling_quality_score"], ZERO)
    if quality < QUALITY_SUSPENSION_THRESHOLD:
        return SUSPENSION_REASON_QUALITY
    if int(broker["open_defect_tier"]) >= DEFECT_SUSPENSION_TIER:
        return SUSPENSION_REASON_DEFECTS
    financial = to_decimal(broker["financial_strength_score"], ZERO)
    if financial < FINANCIAL_SUSPENSION_THRESHOLD:
        return SUSPENSION_REASON_FINANCIAL
    if broker["exclusivity_status"] == EXCLUSIVITY_BLOCKED:
        return SUSPENSION_REASON_EXCLUSIVITY
    return None


def evaluate_suspension(broker):
    """Move an APPROVED broker to SUSPENDED when any trigger holds."""
    if broker["status"] != "APPROVED":
        return False
    reason = suspension_trigger_reason(broker)
    if reason is None:
        return False
    broker["status"] = "SUSPENDED"
    broker["suspended_reason"] = reason
    withdraw_submitted_loans(broker)
    recompute_active_loan_count(broker)
    db.touch(broker)
    return True


def withdraw_submitted_loans(broker):
    """Withdraw every SUBMITTED loan of the broker and unwind its commitment."""
    for row in db.loan_submissions.values():
        if row["broker_id"] != broker["id"]:
            continue
        if row["status"] == "SUBMITTED":
            row["status"] = "WITHDRAWN"
            db.touch(row)
    recompute_compensation_commitment(broker)


# ---------------------------------------------------------------------------
# Turn-time commitments (PRD 2.6)
# ---------------------------------------------------------------------------
def current_underwriting_deadline():
    return db.format_instant(db.clock.advance_days(UNDERWRITING_TURN_DAYS))


def current_closing_deadline():
    return db.format_instant(db.clock.advance_days(CLOSING_TURN_DAYS))


def current_defect_deadline():
    return db.format_instant(db.clock.advance_days(OPEN_DEFECT_DEADLINE_DAYS))


def current_repurchase_deadline():
    return db.format_instant(db.clock.advance_days(REPURCHASE_WINDOW_DAYS))


def open_escalation_if_due(loan):
    """Open at most one escalation per (loan, stage) on each evaluation."""
    opened = 0
    status = loan["status"]
    if status in ("UNDERWRITING", "CONDITIONAL_APPROVAL"):
        due = db.parse_instant(loan.get("underwriting_due_at"))
        if due is not None and db.clock.now >= due:
            if open_escalation(loan, "UNDERWRITING", loan["underwriting_due_at"]) is not None:
                opened += 1
    if status == "CLEAR_TO_CLOSE":
        due = db.parse_instant(loan.get("closing_due_at"))
        if due is not None and db.clock.now >= due:
            if open_escalation(loan, "CLOSING", loan["closing_due_at"]) is not None:
                opened += 1
    return opened


def open_escalation(loan, stage, target_due_at):
    for row in db.turn_time_escalations.values():
        if row["loan_submission_id"] != loan["id"]:
            continue
        if row["stage"] != stage:
            continue
        if row["status"] == "OPEN":
            return None
    row = db.base_row()
    row.update({
        "loan_submission_id": loan["id"],
        "broker_id": loan["broker_id"],
        "stage": stage,
        "opened_at": db.now_iso(),
        "target_due_at": target_due_at,
        "resolved_at": None,
        "resolution_note": None,
        "status": "OPEN",
    })
    db.turn_time_escalations[row["id"]] = row
    return row


def escalations_for_loan(loan_id, stage=None, status=None):
    rows = []
    for row in db.turn_time_escalations.values():
        if row["loan_submission_id"] != loan_id:
            continue
        if stage is not None and row["stage"] != stage:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def has_open_escalation(loan_id, stage=None):
    return len(escalations_for_loan(loan_id, stage=stage, status="OPEN")) > 0


def has_any_escalation(loan_id):
    return len(escalations_for_loan(loan_id)) > 0


# ---------------------------------------------------------------------------
# Escalation status refresh (licence revocation cascade hop 2)
# ---------------------------------------------------------------------------
def reopen_resolved_escalations(loan):
    """Reopen every RESOLVED escalation of the loan with an extended target."""
    extended = None
    due = db.parse_instant(loan.get("underwriting_due_at"))
    if due is not None:
        extended = db.format_instant(due + timedelta(days=UNDERWRITING_EXTENSION_DAYS))
    for row in escalations_for_loan(loan["id"], status="RESOLVED"):
        row["status"] = "OPEN"
        row["resolved_at"] = None
        if extended is not None:
            row["target_due_at"] = extended
        db.touch(row)


def recompute_broker_derived(broker):
    """Recompute every derived broker field, then re-evaluate suspension."""
    recompute_licensed_states(broker)
    recompute_approved_product_codes(broker)
    recompute_active_loan_count(broker)
    recompute_compensation_commitment(broker)
    recompute_rolling_funded_volume(broker)
    recompute_open_defect_tier(broker)
    recompute_exclusivity_status(broker, touch_broker=False)


def ratio_pair_totals(funded_volume, suspended_volume, lifetime_funded, in_flight):
    """Structural reconciliation residual for the broker read."""
    return int(funded_volume) + int(suspended_volume) - (
        int(lifetime_funded) + int(in_flight))


def find_loan_or_error(loan_id):
    return db.loan_submissions.get(loan_id)


def statuses_in(rows, allowed):
    return [row for row in rows if row["status"] in allowed]


def summarize(payload_fn, rows):
    return [payload_fn(row) for row in rows]


__all__ = [name for name in dir() if not name.startswith("_")]