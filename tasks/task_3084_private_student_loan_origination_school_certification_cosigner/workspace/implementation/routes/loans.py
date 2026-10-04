"""Loan servicing routes: disbursements, accrual, plans, payments, relief,
delinquency, default and the summary read."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, iso, parse_iso, add_months
from common import stamp, touch, body_of, required, enum
from errors import fail
from middleware import guard, require_borrower_owns
from response import object_body, array_body, paginate
import engine
import calc

bp = Blueprint("loans", __name__)
PREFIX = "/private-student-loans"


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loans/<lid>", methods=["GET"])
@guard("Borrower", "Cosigner", "Servicer", "Underwriter", "School")
def read_loan(lid, _user_id=None, _role=None):
    engine.sweep()
    loan = engine.get_loan(lid)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan))


@bp.route(PREFIX + "/loans", methods=["GET"])
@guard("Servicer", "Underwriter", "PlatformAdmin")
def list_loans(_user_id=None, _role=None):
    limit = max(1, min(100, int(request.args.get("limit", 10))))
    offset = max(0, int(request.args.get("offset", 0)))
    engine.sweep()
    records = engine.sort_by_created(db.loans.values())
    for key in ("borrower_id", "cosigner_id", "policy_id", "application_id"):
        value = request.args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    page, limit, offset, total = paginate(records, limit, offset)
    return array_body([engine.ser_loan(r) for r in page], limit, offset, total)


@bp.route(PREFIX + "/borrowers/<bid>/loans", methods=["GET"])
@guard("Borrower", "Servicer", "Underwriter")
def borrower_loans(bid, _user_id=None, _role=None):
    engine.get_borrower(bid)
    engine.sweep()
    records = [l for l in engine.sort_by_created(db.loans.values()) if l["borrower_id"] == bid]
    return array_body([engine.ser_loan(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/loans/<lid>/summary", methods=["GET"])
@guard("Borrower", "Cosigner", "Servicer", "Underwriter")
def loan_summary(lid, _user_id=None, _role=None):
    engine.sweep()
    loan = engine.get_loan(lid)
    engine.refresh_loan(loan)
    live_days = loan.get("days_past_due", 0)
    period_close = live_days - 5 if live_days > 5 else 0
    headroom = max(0, int(loan.get("certified_amount_cents", 0))
                   - int(loan.get("disbursed_amount_cents", 0)))
    data = {
        "current_balance_cents": loan.get("current_balance_cents", 0),
        "unpaid_interest_cents": loan.get("unpaid_interest_cents", 0),
        "days_past_due": live_days,
        "period_close_days_past_due": period_close,
        "delinquency_stage": loan.get("delinquency_stage", "CURRENT"),
        "effective_rate_pct": loan.get("effective_rate_pct"),
        "certified_headroom_cents": headroom,
        "release_eligible": engine.release_eligible(loan),
        "notice_obligation_status": loan.get("notice_obligation_status", "NONE"),
    }
    return object_body(data)


# ---------------------------------------------------------------------------
# enrollment / repayment entry / autodebit
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loans/<lid>/enrollment-status", methods=["POST"])
@guard("School")
def enrollment_status(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    app = engine.get_application(loan["application_id"])
    if loan.get("loan_status") != "IN_SCHOOL":
        fail("ERR_INVALID_STATE", "loan %s is not IN_SCHOOL" % lid)
    live = [c for c in engine.certs_of_application(app["id"])
            if c.get("certification_status") in ("CERTIFIED", "PARTIAL_CERTIFIED")]
    if not live:
        fail("ERR_INVALID_STATE", "loan %s holds no live certification" % lid)
    data = body_of(request)
    status = required(data, "enrollment_status")
    enum(status, engine.ENROLLMENT_STATUSES)
    borrower = db.borrowers.get(loan["borrower_id"])
    if borrower is not None:
        borrower["enrollment_status"] = status
        touch(borrower)
    if status in ("GRADUATED", "WITHDRAWN"):
        loan["loan_status"] = "GRACE"
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan))


@bp.route(PREFIX + "/loans/<lid>/enter-repayment", methods=["POST"])
@guard("Servicer")
def enter_repayment(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    if loan.get("loan_status") != "GRACE":
        fail("ERR_INVALID_STATE", "loan %s is not in GRACE" % lid)
    if engine.active_plan(lid) is None:
        fail("ERR_PLAN_REQUIRED", "loan %s holds no ACTIVE repayment plan" % lid)

    loan["repayment_entered_date"] = db.now()
    uncapped = int(loan.get("unpaid_interest_cents", 0))
    cap_pct = engine.policy_value(loan, "capitalized_interest_cap_pct")
    capitalized, _cap = calc.capitalized_interest(
        uncapped, int(loan.get("disbursed_amount_cents", 0)), cap_pct
    )
    # Book the capitalization ledger row, then re-derive unpaid interest.
    entry = {
        "loan_id": loan["id"],
        "entry_date": db.now(),
        "accrued_amount_cents": capitalized,
        "entry_status": "CAPITALIZED",
        "source_event": "CAPITALIZATION",
    }
    stamp(entry, new=True)
    db.accrual_entries[entry["id"]] = entry
    loan["earned_capitalization_count"] = loan.get("earned_capitalization_count", 0) + 1
    loan["loan_status"] = "REPAYMENT"
    # capitalization zeroes the un-capitalized balance and restarts the window;
    # interest above the cap stays in unpaid_interest_cents and keeps accruing.
    loan["unpaid_interest_cents"] = max(0, uncapped - capitalized)
    engine.recompute_ledger_totals(loan)
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan))


@bp.route(PREFIX + "/loans/<lid>/autodebit", methods=["POST"])
@guard("Borrower")
def autodebit(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    require_borrower_owns(_user_id, loan["borrower_id"])
    data = body_of(request)
    enrolled = required(data, "enrolled")
    if not isinstance(enrolled, bool):
        fail("ERR_INVALID_REQUEST", "enrolled must be a boolean")
    if loan.get("loan_status") in ("DELINQUENT", "DEFAULT"):
        fail("ERR_LOAN_DELINQUENT", "loan %s cannot accept an automatic-debit change" % lid)
    loan["autodebit_enrolled"] = enrolled
    loan["autodebit_enrolled_date"] = db.now() if enrolled else None
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan))


@bp.route(PREFIX + "/loans/<lid>/deferment-projection", methods=["POST"])
@guard("Borrower", "Servicer")
def deferment_projection(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    data = body_of(request)
    window = int(required(data, "window_months"))
    projected = calc.accrued_consolidated(
        int(loan.get("principal_cents", 0)), loan.get("effective_rate_pct", 0), window
    )
    return object_body({
        "projected_unpaid_interest_cents": projected,
        "projection_variant": "accrued_consolidated",
    })


@bp.route(PREFIX + "/loans/<lid>/accrual-entries", methods=["POST"])
@guard("Servicer")
def book_accrual(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    data = body_of(request)
    entry_date = required(data, "entry_date")
    window = int(required(data, "window_months"))
    accrued = calc.accrued_per_period(
        int(loan.get("principal_cents", 0)), loan.get("effective_rate_pct", 0), window
    )
    entry = {
        "loan_id": loan["id"],
        "entry_date": parse_iso(entry_date),
        "accrued_amount_cents": accrued,
        "entry_status": "ACCRUED",
        "source_event": "PERIOD_ACCRUAL",
    }
    stamp(entry, new=True)
    db.accrual_entries[entry["id"]] = entry
    # Booking extends the un-capitalized window (PRD 3.5): months not yet covered
    # by a CAPITALIZED entry keep accruing, so the running unpaid figure grows by
    # this booking's per-period amount. Capitalization restarts the window.
    loan["unpaid_interest_cents"] = int(loan.get("unpaid_interest_cents", 0)) + accrued
    engine.recompute_ledger_totals(loan)
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan), 201)


@bp.route(PREFIX + "/loans/<lid>/accrual-entries", methods=["GET"])
@guard("Borrower", "Servicer", "Underwriter")
def list_accruals(lid, _user_id=None, _role=None):
    engine.get_loan(lid)
    records = engine.sort_by_created(engine.entries_of(lid))
    return array_body([engine.ser_accrual_entry(r) for r in records], 10, 0, len(records))


# ---------------------------------------------------------------------------
# repayment plans
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loans/<lid>/repayment-plans", methods=["POST"])
@guard("Borrower", "Servicer")
def create_plan(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    data = body_of(request)
    # Request shape (priority 11) precedes the OCC guard (priority 14).
    plan_type = required(data, "plan_type")
    enum(plan_type, engine.PLAN_TYPES)
    term = int(required(data, "term_months"))

    # The OCC guard is required and is evaluated before any other state or
    # business check on this write path (SCAFFOLD 1.2.1 / PRD 2.8).
    expected = data.get("expected_loan_version")
    if expected is None:
        fail("ERR_STALE_VERSION", "expected_loan_version is required")
    if int(expected) != int(loan.get("version", 1)):
        fail("ERR_STALE_VERSION", "expected_loan_version does not match the loan")
    if loan.get("loan_status") in ("DEFAULT", "PAID_IN_FULL"):
        fail("ERR_INVALID_STATE", "loan %s cannot accept a repayment plan" % lid)

    policy = engine.get_policy(loan["policy_id"])
    if plan_type == "EXTENDED":
        ceiling = int(policy.get("extended_term_months",
                                 engine.POLICY_DEFAULTS["extended_term_months"]))
        if term > ceiling:
            fail("ERR_PRODUCT_RULE_UNSUPPORTED",
                 "EXTENDED plan term exceeds the product ceiling")

    snapshot = int(loan.get("principal_cents", 0))
    rate = float(loan.get("effective_rate_pct") or 0.0)
    plan = {
        "loan_id": loan["id"],
        "plan_type": plan_type,
        "term_months": term,
        "principal_snapshot_cents": snapshot,
        "rate_snapshot_pct": rate,
        "monthly_payment_cents": calc.monthly_payment_cents(snapshot, rate, term),
        "plan_status": "PENDING_APPROVAL",
    }
    stamp(plan, new=True)
    db.repayment_plans[plan["id"]] = plan
    touch(loan)
    return object_body(engine.ser_plan(plan), 201)


@bp.route(PREFIX + "/loans/<lid>/repayment-plans", methods=["GET"])
@guard("Borrower", "Servicer", "Underwriter")
def list_plans(lid, _user_id=None, _role=None):
    engine.get_loan(lid)
    records = engine.sort_by_created(engine.plans_of(lid))
    return array_body([engine.ser_plan(r) for r in records], 10, 0, len(records))


def _resolve_plan_child(plan_id):
    plan = db.repayment_plans.get(plan_id)
    if plan is None:
        fail("ERR_LOAN_CHILD_NOT_FOUND", "repayment plan %s does not exist" % plan_id)
    return plan


@bp.route(PREFIX + "/repayment-plans/<pid>/approve", methods=["POST"])
@guard("Servicer")
def approve_plan(pid, _user_id=None, _role=None):
    plan = _resolve_plan_child(pid)
    loan = engine.get_loan(plan["loan_id"])
    if plan.get("plan_status") != "PENDING_APPROVAL":
        fail("ERR_INVALID_STATE", "plan %s is not PENDING_APPROVAL" % pid)
    if loan.get("loan_status") not in ("IN_SCHOOL", "GRACE", "REPAYMENT", "FORBEARANCE_DEFERMENT"):
        fail("ERR_INVALID_STATE", "loan %s cannot activate a plan" % loan["id"])
    policy = engine.get_policy(loan["policy_id"])
    if plan["plan_type"] == "EXTENDED":
        ceiling = int(policy.get("extended_term_months",
                                 engine.POLICY_DEFAULTS["extended_term_months"]))
        if int(plan["term_months"]) > ceiling:
            fail("ERR_PRODUCT_RULE_UNSUPPORTED",
                 "EXTENDED plan term exceeds the product ceiling")
    if int(plan.get("monthly_payment_cents", 0)) < 5000:
        fail("ERR_AMOUNT_OUT_OF_RANGE", "monthly_payment_cents is below the 5000-cent floor")

    for sibling in engine.plans_of(loan["id"]):
        if sibling["id"] != plan["id"] and sibling.get("plan_status") == "ACTIVE":
            sibling["plan_status"] = "SUPERSEDED"
            touch(sibling)
    plan["plan_status"] = "ACTIVE"
    touch(plan)
    loan["active_plan_type"] = plan["plan_type"]
    touch(loan)
    return object_body(engine.ser_plan(plan))


@bp.route(PREFIX + "/repayment-plans/<pid>/decline", methods=["POST"])
@guard("Servicer")
def decline_plan(pid, _user_id=None, _role=None):
    plan = _resolve_plan_child(pid)
    if plan.get("plan_status") != "PENDING_APPROVAL":
        fail("ERR_INVALID_STATE", "plan %s is not PENDING_APPROVAL" % pid)
    plan["plan_status"] = "DECLINED"
    touch(plan)
    return object_body(engine.ser_plan(plan))


# ---------------------------------------------------------------------------
# payments
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loans/<lid>/payment-schedule", methods=["POST"])
@guard("Servicer")
def payment_schedule(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    if loan.get("repayment_entered_date") is None:
        fail("ERR_INVALID_STATE", "loan %s has not entered repayment" % lid)
    plan = engine.active_plan(lid)
    if plan is None:
        fail("ERR_PLAN_REQUIRED", "loan %s holds no ACTIVE repayment plan" % lid)
    data = body_of(request)
    periods = int(required(data, "periods"))
    created = []
    base = loan["repayment_entered_date"]
    existing = {p["due_period_index"] for p in engine.payments_of(lid)}
    for k in range(1, periods + 1):
        if k in existing:
            continue
        payment = {
            "loan_id": loan["id"],
            "due_period_index": k,
            "scheduled_due_date": add_months(base, k),
            "paid_date": None,
            "amount_cents": int(plan.get("monthly_payment_cents", 0)),
            "payment_status": "SCHEDULED",
            "arrear_days": 0,
            "is_qualifying": False,
        }
        stamp(payment, new=True)
        db.payments[payment["id"]] = payment
        created.append(payment)
    touch(loan)
    return array_body([engine.ser_payment(p) for p in created], 10, 0, len(created))


@bp.route(PREFIX + "/loans/<lid>/payments", methods=["POST"])
@guard("Borrower", "Servicer")
def record_payment(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    data = body_of(request)
    index = int(required(data, "due_period_index"))
    paid_date = parse_iso(required(data, "paid_date"))
    amount = int(required(data, "amount_cents"))

    if loan.get("loan_status") not in ("REPAYMENT", "DELINQUENT", "FORBEARANCE_DEFERMENT"):
        fail("ERR_INVALID_STATE", "loan %s cannot accept a payment" % lid)

    target = None
    for p in engine.payments_of(lid):
        if p["due_period_index"] == index:
            target = p
            break
    if target is None:
        target = {
            "loan_id": loan["id"],
            "due_period_index": index,
            "scheduled_due_date": None,
            "paid_date": None,
            "amount_cents": amount,
            "payment_status": "SCHEDULED",
            "arrear_days": 0,
            "is_qualifying": False,
        }
        stamp(target, new=True)
        db.payments[target["id"]] = target

    due = target.get("scheduled_due_date")
    threshold = int(engine.policy_value(loan, "delinquency_notice_threshold_days"))
    if due is None:
        # A payment recorded without a generated schedule is treated as cleared
        # on its own reported date; the on-time/late split still reads the loan.
        arrear = 0
    else:
        arrear = max(0, (paid_date - due).days)

    # Late settlement is the mirror image: the paid date is later than the due
    # date plus the notice threshold and the loan must be REPAYMENT or DELINQUENT.
    accepted = loan.get("loan_status") in ("REPAYMENT", "DELINQUENT")

    # On-time settlement is inclusive of the
    # grace window: a payment landing no later than the period's
    # scheduled_due_date plus the product's notice threshold is on time (PRD 3.6).
    if due is None or arrear <= threshold:
        target["payment_status"] = "PAID_ON_TIME"
        target["arrear_days"] = 0
        target["is_qualifying"] = True
        borrower = db.borrowers.get(loan["borrower_id"])
        if borrower is not None:
            borrower["on_time_payment_run_count"] = borrower.get("on_time_payment_run_count", 0) + 1
            borrower["lifetime_on_time_payment_count"] = (
                borrower.get("lifetime_on_time_payment_count", 0) + 1
            )
            touch(borrower)
        loan["current_balance_cents"] = loan.get("current_balance_cents", 0) - amount
        loan["_principal_repaid_cents"] = loan.get("_principal_repaid_cents", 0) + amount
        if loan.get("loan_status") == "FORBEARANCE_DEFERMENT":
            pass
    elif accepted:
        target["payment_status"] = "PAID_LATE"
        target["arrear_days"] = arrear
        target["is_qualifying"] = False
        borrower = db.borrowers.get(loan["borrower_id"])
        if borrower is not None:
            borrower["on_time_payment_run_count"] = 0
            touch(borrower)
    else:
        fail("ERR_INVALID_STATE", "loan %s cannot accept a late payment" % lid)

    target["paid_date"] = paid_date
    touch(target)
    engine._refresh_aging(loan)
    engine._apply_delinquency_notice(loan)
    if target["payment_status"] == "PAID_LATE" and loan.get("loan_status") == "REPAYMENT":
        loan["loan_status"] = "DELINQUENT"
    _maybe_paid_in_full(loan)
    touch(loan)
    return object_body(engine.ser_payment(target), 201)


@bp.route(PREFIX + "/loans/<lid>/payments", methods=["GET"])
@guard("Borrower", "Cosigner", "Servicer")
def list_payments(lid, _user_id=None, _role=None):
    engine.get_loan(lid)
    engine.sweep()
    records = engine.sort_by_created(engine.payments_of(lid))
    return array_body([engine.ser_payment(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/payments/<pid>", methods=["GET"])
@guard("Borrower", "Servicer")
def read_payment(pid, _user_id=None, _role=None):
    record = db.payments.get(pid)
    if record is None:
        fail("ERR_LOAN_CHILD_NOT_FOUND", "payment %s does not exist" % pid)
    return object_body(engine.ser_payment(record))


@bp.route(PREFIX + "/payments/<pid>/reverse", methods=["POST"])
@guard("Servicer")
def reverse_payment(pid, _user_id=None, _role=None):
    record = db.payments.get(pid)
    if record is None:
        fail("ERR_LOAN_CHILD_NOT_FOUND", "payment %s does not exist" % pid)
    if record.get("payment_status") not in ("PAID_ON_TIME", "PAID_LATE", "MISSED"):
        fail("ERR_INVALID_STATE", "payment %s cannot be reversed" % pid)
    data = body_of(request)
    loan = engine.get_loan(record["loan_id"])
    if "reason" not in data or data.get("reason") is None:
        fail("ERR_INVALID_REQUEST", "reason is required")

    entry = {
        "loan_id": loan["id"],
        "entry_date": db.now(),
        "accrued_amount_cents": 0,
        "entry_status": "ACCRUED",
        "source_event": "PAYMENT_REVERSAL",
    }
    stamp(entry, new=True)
    db.accrual_entries[entry["id"]] = entry

    record["payment_status"] = "REVERSED"
    record["is_qualifying"] = False
    touch(record)
    loan["current_balance_cents"] = loan.get("current_balance_cents", 0) + int(
        record.get("amount_cents", 0))
    loan["_principal_repaid_cents"] = max(
        0, loan.get("_principal_repaid_cents", 0) - int(record.get("amount_cents", 0)))
    borrower = db.borrowers.get(loan["borrower_id"])
    if borrower is not None:
        engine.refresh_borrower_run(borrower)
        touch(borrower)
    touch(loan)
    return object_body(engine.ser_payment(record))


def _maybe_paid_in_full(loan):
    if loan.get("current_balance_cents", 0) > 0:
        return
    for p in engine.payments_of(loan["id"]):
        if p.get("payment_status") not in ("PAID_ON_TIME", "PAID_LATE", "REVERSED"):
            return
    loan["loan_status"] = "PAID_IN_FULL"
    app = engine.get_application(loan["application_id"])
    if app.get("application_status") == "DISBURSED":
        app["application_status"] = "CLOSED"
        touch(app)


# ---------------------------------------------------------------------------
# disbursements
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loans/<lid>/disbursements", methods=["POST"])
@guard("Servicer")
def schedule_disbursement(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    data = body_of(request)
    # Precedence: OCC stale-version (priority 14) then business-safety blocked
    # (priority 15) then the overlap safety check (priority 17). Shape (11)
    # comes before both.
    label = required(data, "academic_period_label")
    start = parse_iso(required(data, "period_start_date"))
    end = parse_iso(required(data, "period_end_date"))
    scheduled = parse_iso(required(data, "scheduled_date"))
    amount = int(required(data, "amount_cents"))

    expected = data.get("expected_loan_version")
    if expected is None:
        fail("ERR_STALE_VERSION", "expected_loan_version is required")
    if int(expected) != int(loan.get("version", 1)):
        fail("ERR_STALE_VERSION", "expected_loan_version does not match the loan")
    if loan.get("disburse_blocked", False):
        fail("ERR_DISBURSEMENT_BLOCKED", "loan %s is blocked for disbursement" % lid)

    for existing in engine.disbursements_of(lid):
        if existing.get("disbursement_status") == "CANCELLED":
            continue
        if start <= existing["period_end_date"] and existing["period_start_date"] <= end:
            fail("ERR_DISBURSEMENT_WINDOW_OVERLAP",
                 "academic period window overlaps an existing disbursement")

    record = {
        "loan_id": loan["id"],
        "academic_period_label": label,
        "period_start_date": start,
        "period_end_date": end,
        "scheduled_date": scheduled,
        "amount_cents": amount,
        "released_date": None,
        "remainder_credited_cents": 0,
        "refund_status": "NOT_APPLICABLE",
        "disbursement_status": "SCHEDULED",
    }
    stamp(record, new=True)
    db.disbursements[record["id"]] = record
    touch(loan)
    return object_body(engine.ser_disbursement(record), 201)


@bp.route(PREFIX + "/loans/<lid>/disbursements", methods=["GET"])
@guard("Borrower", "School", "Servicer", "Underwriter")
def list_disbursements(lid, _user_id=None, _role=None):
    engine.get_loan(lid)
    records = engine.sort_by_created(engine.disbursements_of(lid))
    return array_body([engine.ser_disbursement(r) for r in records], 10, 0, len(records))


def _resolve_disbursement(did):
    record = db.disbursements.get(did)
    if record is None:
        fail("ERR_LOAN_CHILD_NOT_FOUND", "disbursement %s does not exist" % did)
    return record


@bp.route(PREFIX + "/disbursements/<did>", methods=["GET"])
@guard("Borrower", "School", "Servicer")
def read_disbursement(did, _user_id=None, _role=None):
    record = _resolve_disbursement(did)
    return object_body(engine.ser_disbursement(record))


@bp.route(PREFIX + "/disbursements/<did>/release", methods=["POST"])
@guard("Servicer")
def release_disbursement(did, _user_id=None, _role=None):
    record = _resolve_disbursement(did)
    loan = engine.get_loan(record["loan_id"])
    if record.get("disbursement_status") != "SCHEDULED":
        fail("ERR_INVALID_STATE", "disbursement %s is not SCHEDULED" % did)
    if loan.get("loan_status") not in ("APPROVED", "IN_SCHOOL"):
        fail("ERR_INVALID_STATE", "loan %s cannot release funds" % loan["id"])
    if loan.get("disburse_blocked", False):
        fail("ERR_DISBURSEMENT_BLOCKED", "loan %s is blocked for disbursement" % loan["id"])

    app = engine.get_application(loan["application_id"])
    live = [c for c in engine.certs_of_application(app["id"])
            if c["academic_period_label"] == record["academic_period_label"]
            and c.get("certification_status") in ("CERTIFIED", "PARTIAL_CERTIFIED")]
    if not live:
        fail("ERR_INVALID_STATE",
             "no live certification covers period %s" % record["academic_period_label"])

    headroom = max(0, int(loan.get("certified_amount_cents", 0))
                   - int(loan.get("disbursed_amount_cents", 0)))
    if int(record["amount_cents"]) > headroom:
        fail("ERR_DISBURSEMENT_OVER_CERTIFIED",
             "release exceeds the loan's certification headroom")

    record["released_date"] = db.now()
    record["disbursement_status"] = "RELEASED"
    touch(record)
    engine.recompute_disbursed(loan)
    if int(loan.get("disbursed_amount_cents", 0)) > int(loan.get("certified_amount_cents", 0)):
        record["refund_status"] = "REFUND_DUE"
        touch(record)
    if loan.get("loan_status") == "APPROVED":
        loan["loan_status"] = "IN_SCHOOL"
        if app.get("application_status") == "SCHOOL_CERT_PENDING":
            app["application_status"] = "DISBURSED"
            touch(app)
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_disbursement(record))


@bp.route(PREFIX + "/disbursements/<did>", methods=["DELETE"])
@guard("Servicer")
def cancel_disbursement(did, _user_id=None, _role=None):
    record = _resolve_disbursement(did)
    loan = engine.get_loan(record["loan_id"])
    if record.get("disbursement_status") != "SCHEDULED":
        fail("ERR_INVALID_STATE", "disbursement %s is not SCHEDULED" % did)
    record["disbursement_status"] = "CANCELLED"
    touch(record)
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_disbursement(record))


@bp.route(PREFIX + "/disbursements/<did>/reschedule", methods=["POST"])
@guard("Servicer")
def reschedule_disbursement(did, _user_id=None, _role=None):
    record = _resolve_disbursement(did)
    loan = engine.get_loan(record["loan_id"])
    if record.get("disbursement_status") != "FAILED":
        fail("ERR_INVALID_STATE", "disbursement %s is not FAILED" % did)
    data = body_of(request)
    scheduled = parse_iso(required(data, "scheduled_date"))
    if scheduled < db.now():
        fail("ERR_INVALID_REQUEST", "scheduled_date is in the past")
    record["scheduled_date"] = scheduled
    record["disbursement_status"] = "SCHEDULED"
    touch(record)
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_disbursement(record))


@bp.route(PREFIX + "/disbursements/<did>/school-refund", methods=["POST"])
@guard("School")
def school_refund(did, _user_id=None, _role=None):
    record = _resolve_disbursement(did)
    loan = engine.get_loan(record["loan_id"])
    if record.get("disbursement_status") != "RELEASED":
        fail("ERR_INVALID_STATE", "disbursement %s is not RELEASED" % did)
    if int(record.get("remainder_credited_cents", 0)) != 0:
        fail("ERR_INVALID_STATE", "disbursement %s already carries a refund" % did)
    data = body_of(request)
    amount = int(required(data, "remainder_credited_cents"))
    if amount > int(record["amount_cents"]):
        fail("ERR_AMOUNT_OUT_OF_RANGE",
             "remainder_credited_cents exceeds the disbursement amount")
    record["remainder_credited_cents"] = amount
    record["refund_status"] = "REFUNDED"
    touch(record)
    touch(loan)
    engine.recompute_disbursed(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_disbursement(record))


# ---------------------------------------------------------------------------
# relief
# ---------------------------------------------------------------------------
def _relief_cap(loan):
    if loan.get("loan_status") in ("IN_SCHOOL", "GRACE"):
        return int(engine.policy_value(loan, "in_school_max_deferment_months"))
    if loan.get("loan_status") == "REPAYMENT":
        return int(engine.policy_value(loan, "repayment_max_deferment_months"))
    return int(engine.policy_value(loan, "repayment_max_deferment_months"))


@bp.route(PREFIX + "/loans/<lid>/forbearances", methods=["POST"])
@guard("Servicer", "Borrower")
def create_forbearance(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    data = body_of(request)
    relief_type = required(data, "relief_type")
    months = int(required(data, "months_requested"))
    treatment = required(data, "interest_treatment")
    enum(treatment, engine.INTEREST_TREATMENTS)
    start = parse_iso(required(data, "start_date"))

    if relief_type not in engine.RELIEF_TYPES:
        fail("ERR_PRODUCT_RULE_UNSUPPORTED",
             "relief_type %s is not offered by the private product" % relief_type)
    if loan.get("loan_status") not in ("IN_SCHOOL", "GRACE", "REPAYMENT", "FORBEARANCE_DEFERMENT"):
        fail("ERR_INVALID_STATE", "loan %s does not admit relief" % lid)
    if months < 1:
        fail("ERR_INVALID_REQUEST", "months_requested must be at least 1")

    # priority 21: overlapping relief window (zero-gap adjacency is an overlap).
    requested_end = add_months(start, months)
    for existing in engine.forbearances_of(lid):
        if existing.get("relief_status") != "GRANTED":
            continue
        ex_start = existing["start_date"]
        ex_end = add_months(ex_start, int(existing.get("months_granted", 0)))
        if start <= ex_end and ex_start <= requested_end:
            fail("ERR_FORBEARANCE_OVERLAP", "relief window overlaps an existing grant")

    # priority 28: cumulative deferment cap.
    cap = _relief_cap(loan)
    cumulative = int(loan.get("cumulative_deferment_months", 0))
    if cumulative + months > cap:
        fail("ERR_DEFERMENT_CAP_EXCEEDED", "granting the relief would breach the product cap")

    granted = min(months, cap - cumulative)
    record = {
        "loan_id": loan["id"],
        "relief_type": relief_type,
        "months_requested": months,
        "interest_treatment": treatment,
        "start_date": start,
        "months_granted": granted,
        "relief_status": "GRANTED",
    }
    stamp(record, new=True)
    db.forbearances[record["id"]] = record
    loan["cumulative_deferment_months"] = cumulative + granted
    prior = loan.get("loan_status")
    if prior not in ("FORBEARANCE_DEFERMENT",):
        loan["_pre_relief_status"] = prior
    loan["repayment_option"] = treatment
    loan["loan_status"] = "FORBEARANCE_DEFERMENT"
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_forbearance(record), 201)


@bp.route(PREFIX + "/loans/<lid>/forbearances", methods=["GET"])
@guard("Borrower", "Servicer")
def list_forbearances(lid, _user_id=None, _role=None):
    engine.get_loan(lid)
    records = engine.sort_by_created(engine.forbearances_of(lid))
    return array_body([engine.ser_forbearance(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/forbearances/<fid>", methods=["GET"])
@guard("Borrower", "Servicer")
def read_forbearance(fid, _user_id=None, _role=None):
    record = db.forbearances.get(fid)
    if record is None:
        fail("ERR_LOAN_CHILD_NOT_FOUND", "forbearance %s does not exist" % fid)
    return object_body(engine.ser_forbearance(record))


@bp.route(PREFIX + "/loans/<lid>/forbearances/<fid>/cancel", methods=["POST"])
@guard("Servicer")
def cancel_forbearance(lid, fid, _user_id=None, _role=None):
    record = db.forbearances.get(fid)
    if record is None or record.get("loan_id") != lid:
        fail("ERR_LOAN_CHILD_NOT_FOUND", "forbearance %s does not belong to loan %s" % (fid, lid))
    loan = engine.get_loan(lid)
    if record.get("relief_status") != "GRANTED":
        fail("ERR_INVALID_STATE", "forbearance %s is not GRANTED" % fid)
    if record["start_date"] < db.now():
        fail("ERR_INVALID_STATE", "forbearance %s has already started" % fid)
    record["relief_status"] = "CANCELLED"
    touch(record)
    loan["cumulative_deferment_months"] = max(
        0, int(loan.get("cumulative_deferment_months", 0)) - int(record.get("months_granted", 0)))
    loan["loan_status"] = loan.get("_pre_relief_status") or "REPAYMENT"
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_forbearance(record))


# ---------------------------------------------------------------------------
# delinquency / default
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loans/<lid>/cure", methods=["POST"])
@guard("Servicer")
def cure(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    if loan.get("loan_status") != "DELINQUENT":
        fail("ERR_INVALID_STATE", "loan %s is not DELINQUENT" % lid)
    missed = [p for p in engine.payments_of(lid) if p.get("payment_status") == "MISSED"]
    cleared = {p["due_period_index"] for p in engine.payments_of(lid)
               if p.get("payment_status") in ("PAID_ON_TIME", "PAID_LATE")}
    for p in missed:
        if p["due_period_index"] not in cleared:
            fail("ERR_INVALID_STATE",
                 "missed period %s has not been superseded" % p["due_period_index"])
    loan["days_past_due"] = 0
    loan["delinquency_stage"] = "CURRENT"
    loan["loan_status"] = "REPAYMENT"
    borrower = db.borrowers.get(loan["borrower_id"])
    if borrower is not None:
        engine.refresh_borrower_run(borrower)
        touch(borrower)
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan))


@bp.route(PREFIX + "/loans/<lid>/declare-default", methods=["POST"])
@guard("Servicer")
def declare_default(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    if loan.get("loan_status") != "DELINQUENT":
        fail("ERR_INVALID_STATE", "loan %s is not DELINQUENT" % lid)
    days = engine.days_past_due_of(loan)
    if days < 120:
        fail("ERR_DEFAULT_THRESHOLD_NOT_MET",
             "days_past_due %s is below the 120-day default threshold" % days)
    loan["days_past_due"] = days
    loan["delinquency_stage"] = engine.stage_for(days)
    loan["notice_obligation_status"] = "PENDING"
    loan["disburse_blocked"] = True
    loan["loan_status"] = "DEFAULT"
    cos = db.cosigners.get(loan.get("cosigner_id")) if loan.get("cosigner_id") else None
    if cos is not None:
        cos["underwriting_status"] = "INELIGIBLE"
        touch(cos)
    for rel in engine.releases_of(lid):
        if rel.get("release_status") in ("SUBMITTED", "UNDER_REVIEW"):
            rel["release_status"] = "DECLINED"
            rel["deficiency_reason"] = "DELINQUENT_LOAN"
            touch(rel)
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan))


@bp.route(PREFIX + "/loans/<lid>/rehabilitate", methods=["POST"])
@guard("Servicer")
def rehabilitate(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    if loan.get("loan_status") != "DEFAULT":
        fail("ERR_INVALID_STATE", "loan %s is not DEFAULT" % lid)
    data = body_of(request)
    amount = int(required(data, "rehabilitation_amount_cents"))
    plan = engine.active_plan(lid)
    required_amount = 3 * int(plan.get("monthly_payment_cents", 0)) if plan else 0
    if amount < required_amount:
        fail("ERR_AMOUNT_OUT_OF_RANGE",
             "rehabilitation_amount_cents is below three monthly payments")
    loan["disburse_blocked"] = False
    # Rehabilitation supersedes every outstanding missed period, so arrears
    # recompute to zero rather than being re-derived from the old due dates.
    for p in engine.payments_of(lid):
        if p.get("payment_status") in ("MISSED", "PAID_LATE"):
            p["_superseded"] = True
            touch(p)
    loan["days_past_due"] = 0
    loan["delinquency_stage"] = "CURRENT"
    loan["loan_status"] = "REPAYMENT"
    touch(loan)
    engine.refresh_loan(loan)
    return object_body(engine.ser_loan(loan))