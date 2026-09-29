"""PRD 3.4 / 3.5 -- payroll delivery, reconciliation, remittance settlement,
timeliness and the late-deposit correction workflow."""

from flask import Blueprint

import authz
import calc
import clockcal
import envelope
import recompute
import store
import validate
from errors import fail
from routes_setup import need

bp = Blueprint("payroll", __name__)

CORRECTION_METHODS = ("VFCP_RECOVERY_DATE", "IRS_6621_UNDERPAYMENT")
REVERSIBLE_TIMELINESS = ("TIMELY", "LATE", "UNDETERMINED")
BATCH_READ_ROLES = (
    "RegulatorOps",
    "PooledPlanProvider",
    "AdoptingEmployer",
    "ServiceProvider",
)


def _require_recordkeeper(plan):
    """Priority 37: the acting firm must be the plan's RECORDKEEPER."""
    if not authz.is_plan_recordkeeper(plan):
        fail("ERR_NOT_PLAN_RECORDKEEPER")


def _sync_employer_money(employer):
    """The receivable and the balance are derived, never incrementally patched."""
    employer["contribution_receivable_cents"] = recompute.employer_receivable(employer)


def _employer_balance(employer):
    """account_balance_cents from first principles: every POSTED deposit of the
    employer plus every funded restoration, less every settled exit."""
    total = 0
    for deposit in store.deposits_of_employer(employer):
        if deposit["deposit_status"] == "POSTED":
            total += deposit["amount_cents"]
            if deposit["timeliness_status"] == "CORRECTED":
                total += deposit["restoration_cents"] or 0
    for transfer in store.exits_of_employer(employer):
        if transfer["status"] == "SETTLED":
            total -= transfer["settled_amount_cents"] or 0
    return total


def _sync_employer(employer):
    _sync_employer_money(employer)
    employer["account_balance_cents"] = _employer_balance(employer)


# ==========================================================================
# PayrollBatch
# ==========================================================================


@bp.post("/pep/payroll-batches")
def create_batch():
    authz.identify()
    authz.authorize("AdoptingEmployer")
    b = validate.body()

    employer = validate.resolve_fk(
        b, "adopting_employer_id", "employers", "ERR_ADOPTING_EMPLOYER_NOT_FOUND"
    )
    authz.own_if(
        plan=store.plan_of_employer(employer) if employer else None, employer=employer
    )

    validate.require_fk_shape(b, "adopting_employer_id")
    period_start = validate.req_date(b, "pay_period_start")
    period_end = validate.req_date(b, "pay_period_end")
    pay_date = validate.req_date(b, "pay_date")
    withholding_date = validate.req_date(b, "withholding_date")
    reference = validate.req_str(b, "payroll_provider_reference", 1, 64)
    compensation = validate.req_int(b, "total_eligible_compensation_cents", 0)
    deferral = validate.req_int(b, "total_deferral_cents", 0)
    match = validate.req_int(b, "total_match_cents", 0)
    loan = validate.req_int(b, "total_loan_repayment_cents", 0)
    lines = validate.req_int(b, "participant_line_count", 1)

    if employer["adoption_status"] != "ACTIVE":
        fail("ERR_EMPLOYER_INVALID_STATE")

    # Priority 40: the half-open interval must be well formed.
    if period_end <= period_start or pay_date < period_start:
        fail("ERR_INVALID_PAY_PERIOD")

    # Priority 41: half-open overlap, so exact adjacency is permitted.
    for other in store.batches_of_employer(employer):
        other_start = clockcal.parse_date(other["pay_period_start"])
        other_end = clockcal.parse_date(other["pay_period_end"])
        if period_start < other_end and other_start < period_end:
            fail("ERR_PAY_PERIOD_OVERLAP")

    # Priority 42: withholding inside the period plus a 31 calendar-day grace.
    latest = period_end + clockcal.timedelta(days=calc.WITHHOLDING_GRACE_DAYS)
    if withholding_date < period_start or withholding_date > latest:
        fail("ERR_WITHHOLDING_DATE_OUT_OF_PERIOD")

    # Priority 55: the payroll reference is unique per employer.
    for other in store.batches_of_employer(employer):
        if other["payroll_provider_reference"] == reference:
            fail("ERR_DUPLICATE_PAYROLL_REFERENCE")

    # Priority 64: an approved election is what makes the match computable.
    election = store.approved_election(employer)
    if election is None:
        fail("ERR_NO_APPROVED_ELECTION")

    rule = (
        "SMALL_PLAN_7_BUSINESS_DAY"
        if employer["is_small_plan"]
        else "GENERAL_15TH_BUSINESS_DAY"
    )
    due = calc.deposit_due_date(rule, withholding_date)

    record = store.insert(
        "batches",
        {
            "adopting_employer_id": employer["id"],
            "pay_period_start": clockcal.fmt_date(period_start),
            "pay_period_end": clockcal.fmt_date(period_end),
            "pay_date": clockcal.fmt_date(pay_date),
            "withholding_date": clockcal.fmt_date(withholding_date),
            "payroll_provider_reference": reference,
            "total_eligible_compensation_cents": compensation,
            "total_deferral_cents": deferral,
            "total_match_cents": match,
            "total_loan_repayment_cents": loan,
            "participant_line_count": lines,
            "expected_match_cents": calc.expected_match_cents(
                election, compensation, deferral
            ),
            "batch_total_cents": deferral + match + loan,
            "deposit_rule": rule,
            "deposit_due_date": clockcal.fmt_date(due),
            "status": "RECEIVED",
            "validated_at": None,
            "reconciliation_note": None,
        },
    )
    return envelope.ok_created(envelope.VIEWS["batches"](record))


@bp.post("/pep/payroll-batches/<batch_id>/validate")
def validate_batch(batch_id):
    authz.identify()
    authz.authorize("ServiceProvider")
    batch = need("batches", batch_id, "ERR_PAYROLL_BATCH_NOT_FOUND")
    employer = store.employer_of_batch(batch)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan)

    b = validate.body()
    note = validate.req_str(b, "reconciliation_note", 1, None)

    if batch["status"] != "RECEIVED":
        fail("ERR_BATCH_INVALID_STATE")
    _require_recordkeeper(plan)
    if batch["total_match_cents"] != batch["expected_match_cents"]:
        fail("ERR_MATCH_MISMATCH")

    touch = authz.touch()
    batch["status"] = "VALIDATED"
    batch["validated_at"] = clockcal.stamp()
    batch["reconciliation_note"] = note
    touch.bump(batch)

    _sync_employer_money(employer)
    touch.bump(employer)
    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["batches"](batch))


@bp.get("/pep/payroll-batches/<batch_id>")
def read_batch(batch_id):
    authz.identify()
    authz.authorize(*BATCH_READ_ROLES)
    batch = need("batches", batch_id, "ERR_PAYROLL_BATCH_NOT_FOUND")
    employer = store.employer_of_batch(batch)
    authz.own(plan=store.plan_of_employer(employer), employer=employer)
    return envelope.ok_object(envelope.VIEWS["batches"](batch))


@bp.get("/pep/payroll-batches/<batch_id>/remittance-deposits")
def list_batch_deposits(batch_id):
    authz.identify()
    authz.authorize(*BATCH_READ_ROLES)
    batch = need("batches", batch_id, "ERR_PAYROLL_BATCH_NOT_FOUND")
    employer = store.employer_of_batch(batch)
    authz.own(plan=store.plan_of_employer(employer), employer=employer)
    return envelope.paginate(store.deposits_of_batch(batch), envelope.VIEWS["deposits"])


# ==========================================================================
# RemittanceDeposit
# ==========================================================================


def _revoke_employer_data_branch(filing, touch):
    """A filing sitting in READY_TO_FILE loses its employer-data branch."""
    filing["employer_data_certified_at"] = None
    filing["certified_by_user_id"] = None
    filing["certified_employer_count"] = None
    filing["filing_status"] = (
        "PARTIALLY_CLEARED" if filing["audit_required"] else "PREPARED"
    )
    touch.bump(filing)


def _late_deposit_cascade(deposit, employer, plan, touch):
    """The fourth level of the late-deposit cascade: the plan's annual return.

    Every filing not yet FILED takes the delinquent amount onto its Schedule H
    line, and a filing already READY_TO_FILE has its employer-data branch
    revoked -- falling back to PREPARED when it needs no audit and to
    PARTIALLY_CLEARED when its audit branch is still cleared.
    """
    for filing in store.filings_of_plan(plan):
        if filing["filing_status"] == "FILED":
            continue
        changed = False
        if filing["late_deposit_schedule_h_line_cents"] is not None:
            filing["late_deposit_schedule_h_line_cents"] += deposit["amount_cents"]
            changed = True
        if filing["filing_status"] == "READY_TO_FILE":
            _revoke_employer_data_branch(filing, touch)
        elif changed:
            touch.bump(filing)


def _sync_suspension(employer, touch):
    """contribution_hold and open_correction_count are derived from the deposits;
    the suspension follows the count in both directions."""
    before_status = employer["adoption_status"]
    before_hold = employer["contribution_hold"]
    before_count = employer["open_correction_count"]
    count = recompute.recompute_employer_corrections(employer)
    if count > 0 and employer["adoption_status"] == "ACTIVE":
        employer["adoption_status"] = "SUSPENDED"
    elif count == 0 and employer["adoption_status"] == "SUSPENDED":
        employer["adoption_status"] = "ACTIVE"
    if (
        employer["adoption_status"] != before_status
        or employer["contribution_hold"] != before_hold
        or employer["open_correction_count"] != before_count
    ):
        touch.bump(employer)
    return count


@bp.post("/pep/remittance-deposits")
def create_deposit():
    authz.identify()
    authz.authorize("AdoptingEmployer")
    b = validate.body()

    batch = validate.resolve_fk(
        b, "payroll_batch_id", "batches", "ERR_PAYROLL_BATCH_NOT_FOUND"
    )
    employer = store.employer_of_batch(batch) if batch else None
    authz.own_if(
        plan=store.plan_of_employer(employer) if employer else None, employer=employer
    )

    validate.require_fk_shape(b, "payroll_batch_id")
    deposit_date = validate.req_date(b, "deposit_date")
    amount = validate.req_int(b, "amount_cents", 1)
    reference = validate.req_str(b, "deposit_reference", 1, 64)

    if batch["status"] != "VALIDATED":
        fail("ERR_BATCH_INVALID_STATE")

    withholding_date = clockcal.parse_date(batch["withholding_date"])
    if deposit_date > clockcal.today() or deposit_date < withholding_date:
        fail("ERR_DEPOSIT_DATE_OUT_OF_RANGE")

    if amount != batch["batch_total_cents"]:
        fail("ERR_DEPOSIT_AMOUNT_MISMATCH")

    record = store.insert(
        "deposits",
        {
            "payroll_batch_id": batch["id"],
            "deposit_date": clockcal.fmt_date(deposit_date),
            "amount_cents": amount,
            "deposit_reference": reference,
            "deposit_status": "PENDING",
            "timeliness_status": "UNDETERMINED",
            "business_days_elapsed": None,
            "late_by_business_days": None,
            "posted_at": None,
            "posting_reference": None,
            "correction_method": None,
            "recovery_date": None,
            "actual_investment_return_cents": 0,
            "lost_earnings_cents": None,
            "restoration_cents": None,
            "excise_tax_cents": None,
            "form_5330_reference": None,
            "funded_at": None,
            "reversal_reason": None,
        },
    )
    return envelope.ok_created(envelope.VIEWS["deposits"](record))


@bp.post("/pep/remittance-deposits/<deposit_id>/post")
def post_deposit(deposit_id):
    authz.identify()
    authz.authorize("ServiceProvider")
    deposit = need("deposits", deposit_id, "ERR_REMITTANCE_DEPOSIT_NOT_FOUND")
    batch = store.batch_of_deposit(deposit)
    employer = store.employer_of_batch(batch)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan)

    b = validate.body()
    reference = validate.req_str(b, "posting_reference", 1, 64)

    if batch["status"] != "VALIDATED":
        fail("ERR_BATCH_INVALID_STATE")
    if deposit["deposit_status"] != "PENDING":
        fail("ERR_DEPOSIT_INVALID_STATE")
    _require_recordkeeper(plan)

    touch = authz.touch()
    deposit_date = clockcal.parse_date(deposit["deposit_date"])
    withholding_date = clockcal.parse_date(batch["withholding_date"])
    due = clockcal.parse_date(batch["deposit_due_date"])

    deposit["deposit_status"] = "POSTED"
    deposit["posted_at"] = clockcal.stamp()
    deposit["posting_reference"] = reference
    deposit["business_days_elapsed"] = calc.business_days_elapsed(
        withholding_date, deposit_date
    )
    if deposit_date > due:
        deposit["timeliness_status"] = "LATE"
        deposit["late_by_business_days"] = calc.late_by_business_days(due, deposit_date)
    else:
        deposit["timeliness_status"] = "TIMELY"
        deposit["late_by_business_days"] = 0
    touch.bump(deposit)

    batch["status"] = "REMITTED"
    touch.bump(batch)

    _sync_employer(employer)
    touch.bump(employer)

    if deposit["timeliness_status"] == "LATE":
        _sync_suspension(employer, touch)
        _late_deposit_cascade(deposit, employer, plan, touch)

    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["deposits"](deposit))


@bp.post("/pep/remittance-deposits/<deposit_id>/reverse")
def reverse_deposit(deposit_id):
    authz.identify()
    authz.authorize("ServiceProvider")
    deposit = need("deposits", deposit_id, "ERR_REMITTANCE_DEPOSIT_NOT_FOUND")
    batch = store.batch_of_deposit(deposit)
    employer = store.employer_of_batch(batch)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan)

    b = validate.body()
    reason = validate.req_str(b, "reversal_reason", 1, None)

    if deposit["deposit_status"] != "POSTED":
        fail("ERR_DEPOSIT_INVALID_STATE")
    if deposit["timeliness_status"] not in REVERSIBLE_TIMELINESS:
        fail("ERR_DEPOSIT_NOT_REVERSIBLE")
    _require_recordkeeper(plan)

    touch = authz.touch()
    deposit["deposit_status"] = "REVERSED"
    deposit["timeliness_status"] = "UNDETERMINED"
    deposit["business_days_elapsed"] = None
    deposit["late_by_business_days"] = None
    deposit["reversal_reason"] = reason
    touch.bump(deposit)

    batch["status"] = "VALIDATED"
    touch.bump(batch)

    _sync_employer(employer)
    touch.bump(employer)
    _sync_suspension(employer, touch)
    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["deposits"](deposit))


@bp.post("/pep/remittance-deposits/<deposit_id>/compute-correction")
def compute_correction(deposit_id):
    authz.identify()
    authz.authorize("ServiceProvider")
    deposit = need("deposits", deposit_id, "ERR_REMITTANCE_DEPOSIT_NOT_FOUND")
    batch = store.batch_of_deposit(deposit)
    employer = store.employer_of_batch(batch)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan)

    b = validate.body()
    method = validate.req_enum(b, "correction_method", CORRECTION_METHODS)
    recovery_date = validate.req_date(b, "recovery_date")
    actual_return = validate.req_int(b, "actual_investment_return_cents", 0)

    if deposit["deposit_status"] != "POSTED":
        fail("ERR_DEPOSIT_INVALID_STATE")
    if deposit["timeliness_status"] != "LATE":
        fail("ERR_CORRECTION_INVALID_STATE")
    _require_recordkeeper(plan)

    deposit_date = clockcal.parse_date(deposit["deposit_date"])
    if recovery_date < deposit_date or recovery_date > clockcal.today():
        fail("ERR_INVALID_RECOVERY_DATE")

    due = clockcal.parse_date(batch["deposit_due_date"])
    earnings = calc.lost_earnings(
        method, deposit["amount_cents"], due, deposit_date, recovery_date
    )
    restoration = calc.restoration_cents(earnings, actual_return)

    deposit["correction_method"] = method
    deposit["recovery_date"] = clockcal.fmt_date(recovery_date)
    deposit["actual_investment_return_cents"] = actual_return
    deposit["lost_earnings_cents"] = earnings
    deposit["restoration_cents"] = restoration
    deposit["excise_tax_cents"] = calc.excise_tax_cents(restoration)
    deposit["timeliness_status"] = "CORRECTION_COMPUTED"
    authz.touch().bump(deposit)
    return envelope.ok_object(envelope.VIEWS["deposits"](deposit))


@bp.post("/pep/remittance-deposits/<deposit_id>/fund-correction")
def fund_correction(deposit_id):
    authz.identify()
    authz.authorize("AdoptingEmployer")
    deposit = need("deposits", deposit_id, "ERR_REMITTANCE_DEPOSIT_NOT_FOUND")
    batch = store.batch_of_deposit(deposit)
    employer = store.employer_of_batch(batch)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan, employer=employer)

    b = validate.body()
    reference = validate.opt_str(b, "form_5330_reference", 1, 64, None)

    if (
        deposit["deposit_status"] != "POSTED"
        or deposit["timeliness_status"] != "CORRECTION_COMPUTED"
    ):
        fail("ERR_CORRECTION_INVALID_STATE")

    if (deposit["excise_tax_cents"] or 0) > 0 and reference is None:
        fail("ERR_FORM_5330_REFERENCE_REQUIRED")

    touch = authz.touch()
    deposit["timeliness_status"] = "CORRECTED"
    deposit["funded_at"] = clockcal.stamp()
    deposit["form_5330_reference"] = reference
    touch.bump(deposit)

    _sync_employer(employer)
    touch.bump(employer)
    _sync_suspension(employer, touch)
    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["deposits"](deposit))


@bp.get("/pep/remittance-deposits/<deposit_id>")
def read_deposit(deposit_id):
    authz.identify()
    authz.authorize(*BATCH_READ_ROLES)
    deposit = need("deposits", deposit_id, "ERR_REMITTANCE_DEPOSIT_NOT_FOUND")
    employer = store.employer_of_deposit(deposit)
    authz.own(plan=store.plan_of_employer(employer), employer=employer)
    return envelope.ok_object(envelope.VIEWS["deposits"](deposit))
