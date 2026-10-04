"""Domain engine: serialization, derived-field recomputation, waterfall
allocation, delinquency aging and the shared lookup helpers.

All derived values are recomputed from the stored ledger whenever the ledger
moves, so denormalized totals never drift from the rows that produced them.
"""

from datetime import datetime

from db import db, iso, parse_iso, add_months
from common import touch, round_half_up_int, dec
from errors import fail
import calc

# ---------------------------------------------------------------------------
# declared enumerations
# ---------------------------------------------------------------------------
PROGRAM_LEVELS = {"UNDERGRADUATE", "GRADUATE"}
RELATIONSHIPS = {"PARENT", "GRANDPARENT", "SIBLING", "SPOUSE", "OTHER"}
COSIGNER_STATUSES = {"INVITED", "UNDER_REVIEW", "ELIGIBLE", "INELIGIBLE", "RELEASED"}
ENROLLMENT_STATUSES = {"IN_SCHOOL", "LESS_THAN_HALF_TIME", "GRADUATED", "WITHDRAWN"}
ACCRUAL_OPTIONS = {"DEFERRED", "INTEREST_ONLY", "IMMEDIATE"}
APPLICATION_STATUSES = {
    "SUBMITTED", "UNDER_REVIEW", "SCHOOL_CERT_PENDING", "APPROVED", "DENIED",
    "CANCELLED", "DISBURSED", "CLOSED",
}
CERT_STATUSES = {"REQUESTED", "CERTIFIED", "PARTIAL_CERTIFIED", "REJECTED", "EXPIRED"}
REJECTION_REASONS = {"NOT_ENROLLED", "COST_EXCEEDED", "PROGRAM_INELIGIBLE", "SCHOOL_INACTIVE"}
LOAN_STATUSES = {
    "APPROVED", "IN_SCHOOL", "GRACE", "REPAYMENT", "FORBEARANCE_DEFERMENT",
    "DELINQUENT", "DEFAULT", "PAID_IN_FULL",
}
DISBURSEMENT_STATUSES = {"SCHEDULED", "RELEASED", "CANCELLED", "FAILED"}
REFUND_STATUSES = {"NOT_APPLICABLE", "REFUND_DUE", "REFUNDED"}
PLAN_TYPES = {"STANDARD", "GRADUATED", "EXTENDED", "INCOME_BASED"}
RELIEF_TYPES = {
    "IN_SCHOOL_DEFERMENT", "RESIDENCY_DEFERMENT",
    "ECONOMIC_HARDSHIP_FORBEARANCE", "ADMINISTRATIVE_FORBEARANCE",
}
INTEREST_TREATMENTS = {"ACCRUES_UNPAID", "INTEREST_ONLY"}
RELEASE_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "DECLINED", "WITHDRAWN"}
DEFICIENCY_REASONS = [
    "INSUFFICIENT_PAYMENTS", "CREDIT_SCORE", "DTI", "RELEASE_SCORE", "DELINQUENT_LOAN",
]

POLICY_DEFAULTS = {
    "cosigner_release_min_on_time_payments": 24,
    "cosigner_release_min_credit_score": 660,
    "cosigner_release_max_dti_ratio": 0.45,
    "autodebit_rate_reduction_pct": 0.25,
    "autodebit_min_payments_before_reduction": 24,
    "extended_term_months": 120,
    "capitalized_interest_cap_pct": 0.10,
    "in_school_max_deferment_months": 48,
    "repayment_max_deferment_months": 24,
    "delinquency_notice_threshold_days": 5,
    "allows_standalone_borrower": False,
}


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------
def ser_borrower(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "full_name": r["full_name"],
        "email": r["email"],
        "state_code": r["state_code"],
        "program_level": r["program_level"],
        "credit_score": r.get("credit_score"),
        "dti_ratio": r.get("dti_ratio"),
        "enrollment_status": r.get("enrollment_status"),
        "on_time_payment_run_count": r.get("on_time_payment_run_count", 0),
        "lifetime_on_time_payment_count": r.get("lifetime_on_time_payment_count", 0),
        "status": r.get("status", "ACTIVE"),
    }


def ser_cosigner(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "borrower_id": r.get("borrower_id"),
        "full_name": r["full_name"],
        "email": r["email"],
        "state_code": r["state_code"],
        "relationship": r["relationship"],
        "credit_score": r.get("credit_score"),
        "credit_history_months": r.get("credit_history_months"),
        "dti_ratio": r.get("dti_ratio"),
        "underwriting_status": r.get("underwriting_status", "INVITED"),
    }


def ser_school(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "name": r["name"],
        "school_code": r["school_code"],
        "state_code": r["state_code"],
        "certification_capacity_per_period_cents": r["certification_capacity_per_period_cents"],
        "active": r.get("active", True),
    }


def ser_policy(r):
    out = {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "product_code": r["product_code"],
        "program_level": r["program_level"],
    }
    for key in POLICY_DEFAULTS:
        out[key] = r.get(key, POLICY_DEFAULTS[key])
    return out


def ser_application(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "borrower_id": r["borrower_id"],
        "cosigner_id": r.get("cosigner_id"),
        "school_id": r["school_id"],
        "policy_id": r["policy_id"],
        "requested_amount_cents": r["requested_amount_cents"],
        "cost_of_attendance_cents": r["cost_of_attendance_cents"],
        "other_aid_cents": r.get("other_aid_cents", 0),
        "interest_accrual_option": r["interest_accrual_option"],
        "repayment_term_months": r["repayment_term_months"],
        "certified_limit_cents": r.get("certified_limit_cents"),
        "combined_credit_score": r.get("combined_credit_score"),
        "tier": r.get("tier"),
        "margin_rate_pct": r.get("margin_rate_pct"),
        "decision_path": r.get("decision_path"),
        "approved_amount_cents": r.get("approved_amount_cents"),
        "denial_reason": r.get("denial_reason"),
        "application_status": r.get("application_status", "SUBMITTED"),
    }


def ser_certification(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "application_id": r["application_id"],
        "school_id": r["school_id"],
        "academic_period_label": r["academic_period_label"],
        "certified_amount_cents": r.get("certified_amount_cents", 0),
        "certified_enrollment_status": r.get("certified_enrollment_status"),
        "certified_date": iso(r.get("certified_date")) if r.get("certified_date") else None,
        "certification_status": r.get("certification_status", "REQUESTED"),
        "rejection_reason": r.get("rejection_reason"),
        "period_end_date": iso(r.get("period_end_date")) if r.get("period_end_date") else None,
    }


def ser_loan(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "borrower_id": r["borrower_id"],
        "application_id": r["application_id"],
        "cosigner_id": r.get("cosigner_id"),
        "policy_id": r["policy_id"],
        "principal_cents": r.get("principal_cents", 0),
        "disbursed_amount_cents": r.get("disbursed_amount_cents", 0),
        "certified_amount_cents": r.get("certified_amount_cents", 0),
        "repayment_entered_date": iso(r.get("repayment_entered_date")) if r.get("repayment_entered_date") else None,
        "lifetime_accrued_interest_cents": r.get("lifetime_accrued_interest_cents", 0),
        "lifetime_capitalized_interest_cents": r.get("lifetime_capitalized_interest_cents", 0),
        "current_balance_cents": r.get("current_balance_cents", 0),
        "interest_accrual_option": r.get("interest_accrual_option"),
        "repayment_option": r.get("repayment_option", "DEFERRED"),
        "active_plan_type": r.get("active_plan_type"),
        "effective_rate_pct": r.get("effective_rate_pct"),
        "autodebit_enrolled": r.get("autodebit_enrolled", False),
        "autodebit_enrolled_date": iso(r.get("autodebit_enrolled_date")) if r.get("autodebit_enrolled_date") else None,
        "cumulative_deferment_months": r.get("cumulative_deferment_months", 0),
        "earned_capitalization_count": r.get("earned_capitalization_count", 0),
        "lifetime_principal_reduction_cents": r.get("lifetime_principal_reduction_cents", 0),
        "unpaid_interest_cents": r.get("unpaid_interest_cents", 0),
        "max_allowed_capitalization_cents": r.get("max_allowed_capitalization_cents", 0),
        "max_autodebit_waiver_benefit_cents": r.get("max_autodebit_waiver_benefit_cents", 0),
        "disburse_blocked": r.get("disburse_blocked", False),
        "certification_limit_cents": r.get("certification_limit_cents"),
        "days_past_due": r.get("days_past_due", 0),
        "delinquency_stage": r.get("delinquency_stage", "CURRENT"),
        "notice_obligation_status": r.get("notice_obligation_status", "NONE"),
        "loan_status": r.get("loan_status", "APPROVED"),
    }


def ser_disbursement(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "loan_id": r["loan_id"],
        "academic_period_label": r["academic_period_label"],
        "period_start_date": iso(r.get("period_start_date")) if r.get("period_start_date") else None,
        "period_end_date": iso(r.get("period_end_date")) if r.get("period_end_date") else None,
        "scheduled_date": iso(r.get("scheduled_date")) if r.get("scheduled_date") else None,
        "amount_cents": r["amount_cents"],
        "released_date": iso(r.get("released_date")) if r.get("released_date") else None,
        "remainder_credited_cents": r.get("remainder_credited_cents", 0),
        "refund_status": r.get("refund_status", "NOT_APPLICABLE"),
        "disbursement_status": r.get("disbursement_status", "SCHEDULED"),
    }


def ser_accrual_entry(r):
    # The ledger row carries only id and created_at beyond its own fields.
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "loan_id": r["loan_id"],
        "entry_date": iso(r.get("entry_date")) if r.get("entry_date") else None,
        "accrued_amount_cents": r["accrued_amount_cents"],
        "entry_status": r.get("entry_status", "ACCRUED"),
        "source_event": r.get("source_event"),
    }


def ser_plan(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "loan_id": r["loan_id"],
        "plan_type": r["plan_type"],
        "term_months": r["term_months"],
        "principal_snapshot_cents": r.get("principal_snapshot_cents"),
        "rate_snapshot_pct": r.get("rate_snapshot_pct"),
        "monthly_payment_cents": r.get("monthly_payment_cents"),
        "plan_status": r.get("plan_status", "PENDING_APPROVAL"),
    }


def ser_payment(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "loan_id": r["loan_id"],
        "due_period_index": r["due_period_index"],
        "scheduled_due_date": iso(r.get("scheduled_due_date")) if r.get("scheduled_due_date") else None,
        "paid_date": iso(r.get("paid_date")) if r.get("paid_date") else None,
        "amount_cents": r.get("amount_cents", 0),
        "payment_status": r.get("payment_status", "SCHEDULED"),
        "arrear_days": r.get("arrear_days", 0),
        "is_qualifying": r.get("is_qualifying", False),
    }


def ser_forbearance(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "loan_id": r["loan_id"],
        "relief_type": r["relief_type"],
        "months_requested": r["months_requested"],
        "interest_treatment": r.get("interest_treatment"),
        "start_date": iso(r.get("start_date")) if r.get("start_date") else None,
        "months_granted": r.get("months_granted", 0),
        "relief_status": r.get("relief_status", "REQUESTED"),
    }


def ser_release(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "loan_id": r["loan_id"],
        "cosigner_id": r.get("cosigner_id"),
        "payments_at_application": r.get("payments_at_application"),
        "independent_credit_score": r.get("independent_credit_score"),
        "independent_dti_ratio": r.get("independent_dti_ratio"),
        "required_min_payments": r.get("required_min_payments"),
        "run_at_submission": r.get("run_at_submission"),
        "release_status": r.get("release_status", "SUBMITTED"),
        "deficiency_reason": r.get("deficiency_reason"),
    }


# ---------------------------------------------------------------------------
# lookups (existence validation, PRD 2.9)
# ---------------------------------------------------------------------------
def get_borrower(bid):
    r = db.borrowers.get(bid)
    if r is None:
        fail("ERR_BORROWER_NOT_FOUND", "borrower %s does not exist" % bid)
    return r


def get_cosigner(cid, allow_released=False):
    r = db.cosigners.get(cid)
    if r is None or (not allow_released and r.get("underwriting_status") == "RELEASED"):
        fail("ERR_COSIGNER_NOT_FOUND", "cosigner %s does not exist" % cid)
    return r


def get_school(sid):
    r = db.schools.get(sid)
    if r is None:
        fail("ERR_SCHOOL_NOT_FOUND", "school %s does not exist" % sid)
    return r


def get_policy(pid):
    r = db.policies.get(pid)
    if r is None:
        fail("ERR_POLICY_NOT_FOUND", "loan policy %s does not exist" % pid)
    return r


def get_application(aid):
    r = db.applications.get(aid)
    if r is None:
        fail("ERR_APPLICATION_NOT_FOUND", "application %s does not exist" % aid)
    return r


def get_loan(lid):
    r = db.loans.get(lid)
    if r is None:
        fail("ERR_LOAN_NOT_FOUND", "loan %s does not exist" % lid)
    return r


def get_certification(cid):
    r = db.certifications.get(cid)
    if r is None:
        fail("ERR_CERTIFICATION_NOT_FOUND", "certification %s does not exist" % cid)
    return r


def policy_of(loan):
    return db.policies.get(loan.get("policy_id"))


def policy_value(loan, key):
    pol = policy_of(loan)
    if pol and pol.get(key) is not None:
        return pol[key]
    return POLICY_DEFAULTS.get(key)


# ---------------------------------------------------------------------------
# child collections
# ---------------------------------------------------------------------------
def certs_of_application(app_id):
    return [c for c in db.certifications.values() if c["application_id"] == app_id]


def disbursements_of(loan_id):
    return [d for d in db.disbursements.values() if d["loan_id"] == loan_id]


def payments_of(loan_id):
    return [p for p in db.payments.values() if p["loan_id"] == loan_id]


def plans_of(loan_id):
    return [p for p in db.repayment_plans.values() if p["loan_id"] == loan_id]


def entries_of(loan_id):
    return [e for e in db.accrual_entries.values() if e["loan_id"] == loan_id]


def releases_of(loan_id):
    return [r for r in db.release_applications.values() if r["loan_id"] == loan_id]


def loans_of_application(app_id):
    return [l for l in db.loans.values() if l["application_id"] == app_id]


def forbearances_of(loan_id):
    return [f for f in db.forbearances.values() if f["loan_id"] == loan_id]


def active_plan(loan_id):
    for p in plans_of(loan_id):
        if p.get("plan_status") == "ACTIVE":
            return p
    return None


def sort_by_created(records):
    return sorted(records, key=lambda r: r.get("created_seq", 0))


# ---------------------------------------------------------------------------
# certification_limit_waterfall
# ---------------------------------------------------------------------------
def _ordered_included_certs(app_id):
    included = [
        c for c in certs_of_application(app_id)
        if c.get("certification_status") in ("CERTIFIED", "PARTIAL_CERTIFIED")
    ]
    return sorted(
        included,
        key=lambda c: (
            c.get("certified_date") or datetime.min.replace(tzinfo=db.clock.tzinfo),
            c.get("created_seq", 0),
        ),
    )


def run_waterfall(app):
    """Recompute every certification's allocated amount against the frozen
    ceiling, then the application and loan totals (PRD 3.3)."""
    ceiling = max(0, int(app["cost_of_attendance_cents"]) - int(app.get("other_aid_cents", 0)))
    remaining = ceiling
    total = 0
    for child in _ordered_included_certs(app["id"]):
        requested = int(child.get("requested_amount_cents", child.get("certified_amount_cents", 0)))
        allocated = min(int(child.get("certified_amount_cents", 0)), remaining)
        child["certified_amount_cents"] = allocated
        remaining -= allocated
        total += allocated
        child["certification_status"] = (
            "CERTIFIED" if allocated >= requested else "PARTIAL_CERTIFIED"
        )
    app["certified_amount_cents"] = total
    for loan in loans_of_application(app["id"]):
        loan["certified_amount_cents"] = total
        refresh_loan(loan)
    return total


# ---------------------------------------------------------------------------
# loan-derived recomputation
# ---------------------------------------------------------------------------
def _is_capitalized(entry):
    return entry.get("entry_status") == "CAPITALIZED"


def recompute_ledger_totals(loan):
    """lifetime_* totals are derived from the ledger so they can never drift
    from the rows that produced them (PRD 2.11). `unpaid_interest_cents` is a
    running figure owned by the accrual and capitalization events, because
    capitalization zeroes the un-capitalized balance and restarts the window.
    """
    entries = entries_of(loan["id"])
    acc = sum(e["accrued_amount_cents"] for e in entries
              if e.get("entry_status") in ("ACCRUED", "CAPITALIZED"))
    cap = sum(e["accrued_amount_cents"] for e in entries if _is_capitalized(e))
    loan["lifetime_accrued_interest_cents"] = acc
    loan["lifetime_capitalized_interest_cents"] = cap
    return loan.get("unpaid_interest_cents", 0)


def recompute_disbursed(loan):
    released = sum(
        d["amount_cents"] for d in disbursements_of(loan["id"])
        if d.get("disbursement_status") == "RELEASED"
    )
    refunded = sum(
        d.get("remainder_credited_cents", 0) for d in disbursements_of(loan["id"])
        if d.get("refund_status") == "REFUNDED"
    )
    loan["_refunded_amount_cents"] = refunded
    loan["disbursed_amount_cents"] = released - refunded
    return loan["disbursed_amount_cents"]


def refresh_loan(loan):
    """Re-derive every computed loan field that is not event-specific."""
    recompute_disbursed(loan)
    loan["principal_cents"] = (
        loan["disbursed_amount_cents"]
        + loan.get("lifetime_capitalized_interest_cents", 0)
        - loan.get("_principal_repaid_cents", 0)
    )
    policy_cap = policy_value(loan, "capitalized_interest_cap_pct")
    loan["max_allowed_capitalization_cents"] = calc.max_allowed_capitalization(
        loan["disbursed_amount_cents"], policy_cap
    )
    _refresh_rate(loan)
    _refresh_blocked(loan)
    _refresh_aging(loan)
    loan["current_balance_cents"] = (
        loan["principal_cents"] + loan.get("unpaid_interest_cents", 0)
    )
    return loan


def _refresh_rate(loan):
    borrower = db.borrowers.get(loan["borrower_id"], {})
    margin = dec(loan.get("_margin_rate_pct") or 0)
    enrolled = loan.get("autodebit_enrolled", False)
    lifetime = borrower.get("lifetime_on_time_payment_count", 0)
    policy_min = policy_value(loan, "autodebit_min_payments_before_reduction")
    reduction = policy_value(loan, "autodebit_rate_reduction_pct")
    if loan.get("loan_status") == "DEFAULT":
        loan["effective_rate_pct"] = float(calc.quantize(margin, 4))
    else:
        loan["effective_rate_pct"] = calc.effective_rate_pct(
            margin, enrolled, lifetime, policy_min, reduction
        )
    months = 0
    if loan.get("interest_accrual_option") == "IMMEDIATE" and loan.get("_created_dt"):
        delta = db.now() - loan["_created_dt"]
        months = max(0, delta.days // 30)
    loan["max_autodebit_waiver_benefit_cents"] = calc.max_autodebit_waiver_benefit_cents(
        loan.get("current_balance_cents", 0) or loan.get("principal_cents", 0),
        reduction,
        months,
    )


def _refresh_blocked(loan):
    blocked = loan.get("loan_status") in ("DEFAULT", "FORBEARANCE_DEFERMENT")
    for d in disbursements_of(loan["id"]):
        if d.get("refund_status") == "REFUND_DUE":
            blocked = True
        if d.get("disbursement_status") == "FAILED":
            blocked = True
    loan["disburse_blocked"] = blocked


def _open_due_dates(loan):
    dates = []
    for p in payments_of(loan["id"]):
        if p.get("payment_status") in ("MISSED", "PAID_LATE"):
            if p.get("_superseded"):
                continue
            if p.get("scheduled_due_date"):
                dates.append(p["scheduled_due_date"])
    return dates


def days_past_due_of(loan):
    dates = _open_due_dates(loan)
    if not dates:
        return 0
    oldest = min(dates)
    return max(0, (db.now() - oldest).days)


def stage_for(days):
    if days == 0:
        return "CURRENT"
    if days <= 29:
        return "LATE"
    if days <= 119:
        return "DELINQUENT"
    return "DEFAULT_ELIGIBLE"


def _refresh_aging(loan):
    days = days_past_due_of(loan)
    loan["days_past_due"] = days
    loan["delinquency_stage"] = stage_for(days)


def refresh_borrower_run(borrower):
    """Rebuild the current unbroken run: the count of consecutive cleared
    qualifying periods ending at the most recent cleared due period."""
    payments = sorted(
        [p for p in db.payments.values() if p["loan_id"] in {
            l["id"] for l in db.loans.values() if l["borrower_id"] == borrower["id"]
        } and p.get("payment_status") in ("PAID_ON_TIME", "PAID_LATE", "MISSED")],
        key=lambda p: (p.get("due_period_index") or 0),
    )
    run = 0
    for p in payments:
        if p.get("payment_status") == "PAID_ON_TIME":
            run += 1
        elif p.get("payment_status") in ("PAID_LATE", "MISSED"):
            run = 0
    borrower["on_time_payment_run_count"] = run
    return run


# ---------------------------------------------------------------------------
# clock-driven sweeps
# ---------------------------------------------------------------------------
def sweep():
    now = db.now()
    for p in list(db.payments.values()):
        if p.get("payment_status") != "SCHEDULED":
            continue
        due = p.get("scheduled_due_date")
        if due is None:
            continue
        loan = db.loans.get(p["loan_id"])
        threshold = policy_value(loan, "delinquency_notice_threshold_days") if loan else 5
        if (now - due).days > int(threshold):
            p["payment_status"] = "MISSED"
            p["is_qualifying"] = False
            touch(p)
            if loan is not None:
                borrower = db.borrowers.get(loan["borrower_id"])
                if borrower is not None:
                    borrower["on_time_payment_run_count"] = 0
                _refresh_aging(loan)
                if loan.get("loan_status") == "REPAYMENT":
                    loan["loan_status"] = "DELINQUENT"
                _apply_delinquency_notice(loan)
                touch(loan)
    for c in list(db.certifications.values()):
        if c.get("certification_status") not in ("CERTIFIED", "PARTIAL_CERTIFIED"):
            continue
        end = c.get("period_end_date")
        if end is None:
            continue
        if (now - add_months(end, 0)).days > 30 and now > end:
            if (now - end).days > 30:
                c["certification_status"] = "EXPIRED"
                touch(c)
                app = db.applications.get(c["application_id"])
                if app is not None:
                    run_waterfall(app)
                    _revert_application_after_cert_events(app)
    refresh_all_derived()


def _revert_application_after_cert_events(app):
    children = certs_of_application(app["id"])
    live = [c for c in children if c.get("certification_status") in ("CERTIFIED", "PARTIAL_CERTIFIED", "REQUESTED")]
    if children and not live and app.get("application_status") == "SCHOOL_CERT_PENDING":
        app["application_status"] = "APPROVED"
        touch(app)


def _apply_delinquency_notice(loan):
    threshold = int(policy_value(loan, "delinquency_notice_threshold_days"))
    if loan.get("days_past_due", 0) >= threshold:
        loan["notice_obligation_status"] = "PENDING"


def refresh_all_derived():
    for loan in list(db.loans.values()):
        refresh_loan(loan)


# ---------------------------------------------------------------------------
# release-eligibility roll-up
# ---------------------------------------------------------------------------
def release_eligible(loan):
    cos = db.cosigners.get(loan.get("cosigner_id")) if loan.get("cosigner_id") else None
    if cos is None or cos.get("underwriting_status") != "ELIGIBLE":
        return False
    if loan.get("loan_status") in ("DELINQUENT", "DEFAULT"):
        return False
    if loan.get("notice_obligation_status") == "PENDING":
        return False
    borrower = db.borrowers.get(loan["borrower_id"], {})
    required = int(policy_value(loan, "cosigner_release_min_on_time_payments"))
    return int(borrower.get("on_time_payment_run_count", 0)) >= required