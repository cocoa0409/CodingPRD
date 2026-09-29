"""PRD 3.8 / 3.9 -- employer exit, spin-off and asset transfer, fee disclosure
with revenue-sharing allocation, and the logical-clock control endpoint."""

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

bp = Blueprint("exit", __name__)

EXIT_TYPES = (
    "SPINOFF_TO_SINGLE_PLAN",
    "TRANSFER_TO_OTHER_PEP",
    "PLAN_TERMINATION_DISTRIBUTION",
)
SUCCESSOR_REQUIRED = ("SPINOFF_TO_SINGLE_PLAN", "TRANSFER_TO_OTHER_PEP")
ALLOCATION_METHODS = ("PRO_RATA_ASSETS", "PER_CAPITA")
ELIGIBLE_STATUSES = ("ACTIVE", "SUSPENDED")


def _open_late_correction(employer):
    """A POSTED deposit whose timeliness is LATE or CORRECTION_COMPUTED."""
    return len(recompute.open_correction_deposits(employer)) > 0


def _window_gap_days(a_start, a_end, b_start, b_end):
    """None when the two closed windows overlap, otherwise the whole number of
    calendar days from the earlier window's end to the later window's start."""
    if a_start <= b_end and b_start <= a_end:
        return None
    if a_end < b_start:
        return (b_start - a_end).days
    return (a_start - b_end).days


# ==========================================================================
# ExitTransfer
# ==========================================================================


@bp.post("/pep/exit-transfers")
def create_exit():
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
    exit_type = validate.req_enum(b, "exit_type", EXIT_TYPES)
    requested = validate.req_date(b, "requested_exit_date")
    blackout_start = validate.req_date(b, "blackout_start_date")
    blackout_end = validate.req_date(b, "blackout_end_date")
    if exit_type in SUCCESSOR_REQUIRED:
        successor = validate.req_str(b, "successor_plan_name", 1, 200)
    else:
        successor = validate.opt_str(b, "successor_plan_name", 1, 200, None)

    if employer["adoption_status"] != "ACTIVE":
        fail("ERR_EMPLOYER_INVALID_STATE")

    # Priority 47: the closed blackout interval and the exit date must be ordered.
    if blackout_end < blackout_start or requested < blackout_end:
        fail("ERR_INVALID_BLACKOUT_WINDOW")

    # Priority 67: an unresolved delinquency blocks the departure.
    if _open_late_correction(employer):
        fail("ERR_OPEN_LATE_DEPOSIT_CORRECTION")

    touch = authz.touch()
    record = store.insert(
        "exits",
        {
            "adopting_employer_id": employer["id"],
            "exit_type": exit_type,
            "requested_exit_date": clockcal.fmt_date(requested),
            "blackout_start_date": clockcal.fmt_date(blackout_start),
            "blackout_end_date": clockcal.fmt_date(blackout_end),
            "successor_plan_name": successor,
            "status": "REQUESTED",
            "transferred_participant_count": None,
            "gross_account_balance_cents": None,
            "admin_recovery_cents": None,
            "flat_exit_fee_cents": None,
            "deductions_applied_cents": None,
            "unrecovered_deduction_cents": None,
            "transfer_amount_cents": None,
            "settled_amount_cents": None,
            "approved_at": None,
            "settled_at": None,
            "reversal_reason": None,
        },
    )

    employer["adoption_status"] = "EXIT_REQUESTED"
    touch.bump(employer)
    recompute.recompute_plan(store.plan_of_employer(employer), touch)
    return envelope.ok_created(envelope.VIEWS["exits"](record))


@bp.post("/pep/exit-transfers/<exit_id>/approve")
def approve_exit(exit_id):
    authz.identify()
    authz.authorize("PooledPlanProvider")
    transfer = need("exits", exit_id, "ERR_EXIT_TRANSFER_NOT_FOUND")
    employer = store.employer_of_exit(transfer)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan)

    if transfer["status"] != "REQUESTED":
        fail("ERR_TRANSFER_INVALID_STATE")
    if plan["compliance_posture"] == "FROZEN":
        fail("ERR_PLAN_COMPLIANCE_FROZEN")

    start = clockcal.parse_date(transfer["blackout_start_date"])
    end = clockcal.parse_date(transfer["blackout_end_date"])
    for other in store.exits_of_plan(plan):
        if other["id"] == transfer["id"] or other["status"] == "REVERSED":
            continue
        gap = _window_gap_days(
            start,
            end,
            clockcal.parse_date(other["blackout_start_date"]),
            clockcal.parse_date(other["blackout_end_date"]),
        )
        if gap is None or gap <= calc.BLACKOUT_BUFFER_DAYS:
            fail("ERR_BLACKOUT_WINDOW_CONFLICT")

    touch = authz.touch()
    transfer["status"] = "APPROVED"
    transfer["approved_at"] = clockcal.stamp()
    touch.bump(transfer)
    employer["adoption_status"] = "SPINOFF_IN_PROGRESS"
    touch.bump(employer)
    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["exits"](transfer))


@bp.post("/pep/exit-transfers/<exit_id>/settle")
def settle_exit(exit_id):
    authz.identify()
    authz.authorize("PooledPlanProvider")
    transfer = need("exits", exit_id, "ERR_EXIT_TRANSFER_NOT_FOUND")
    employer = store.employer_of_exit(transfer)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan)

    if transfer["status"] != "APPROVED":
        fail("ERR_TRANSFER_INVALID_STATE")
    if clockcal.today() <= clockcal.parse_date(transfer["blackout_end_date"]):
        fail("ERR_BLACKOUT_NOT_ENDED")
    if _open_late_correction(employer):
        fail("ERR_OPEN_LATE_DEPOSIT_CORRECTION")
    for batch in store.batches_of_employer(employer):
        if batch["status"] == "VALIDATED":
            fail("ERR_UNREMITTED_CONTRIBUTIONS")

    figures = calc.exit_waterfall(
        employer["account_balance_cents"],
        employer["participant_count"],
        transfer["exit_type"],
    )

    touch = authz.touch()
    transfer.update(figures)
    transfer["status"] = "SETTLED"
    transfer["settled_at"] = clockcal.stamp()
    touch.bump(transfer)

    employer["adoption_status"] = "EXITED"
    employer["exited_at"] = clockcal.stamp()
    employer["account_balance_cents"] = 0
    touch.bump(employer)

    election = store.approved_election(employer)
    if election is not None:
        election["status"] = "SUPERSEDED"
        touch.bump(election)

    for test in store.tests_of_plan(plan):
        if (
            test["scope"] == "EMPLOYER_LEVEL"
            and test["adopting_employer_id"] == employer["id"]
            and test["status"] != "CLOSED"
        ):
            test["status"] = "CLOSED"
            test["closed_reason"] = "EMPLOYER_EXITED"
            touch.bump(test)

    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["exits"](transfer))


@bp.post("/pep/exit-transfers/<exit_id>/reverse")
def reverse_exit(exit_id):
    authz.identify()
    authz.authorize("PooledPlanProvider")
    transfer = need("exits", exit_id, "ERR_EXIT_TRANSFER_NOT_FOUND")
    employer = store.employer_of_exit(transfer)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan)

    b = validate.body()
    reason = validate.req_str(b, "reversal_reason", 1, None)

    if transfer["status"] != "SETTLED":
        fail("ERR_TRANSFER_INVALID_STATE")

    settled_year = clockcal.parse_instant(transfer["settled_at"]).year
    for filing in store.filings_of_plan(plan):
        if filing["filing_status"] == "FILED" and filing["plan_year"] == settled_year:
            fail("ERR_FILING_ALREADY_SUBMITTED")

    touch = authz.touch()
    gross = transfer["gross_account_balance_cents"] or 0
    transfer["status"] = "REVERSED"
    transfer["reversal_reason"] = reason
    touch.bump(transfer)

    employer["adoption_status"] = "SPINOFF_IN_PROGRESS"
    employer["account_balance_cents"] = gross
    employer["exited_at"] = None
    touch.bump(employer)
    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["exits"](transfer))


@bp.get("/pep/exit-transfers/<exit_id>")
def read_exit(exit_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer")
    transfer = need("exits", exit_id, "ERR_EXIT_TRANSFER_NOT_FOUND")
    employer = store.employer_of_exit(transfer)
    authz.own(plan=store.plan_of_employer(employer), employer=employer)
    return envelope.ok_object(envelope.VIEWS["exits"](transfer))


# ==========================================================================
# FeeDisclosure
# ==========================================================================


@bp.post("/pep/fee-disclosures")
def create_disclosure():
    authz.identify()
    authz.authorize("PooledPlanProvider")
    b = validate.body()

    plan = validate.resolve_fk(
        b, "plan_document_id", "plans", "ERR_PLAN_DOCUMENT_NOT_FOUND"
    )
    authz.own_if(plan=plan)

    validate.require_fk_shape(b, "plan_document_id")
    period_start = validate.req_date(b, "disclosure_period_start")
    period_end = validate.req_date(b, "disclosure_period_end")
    method = validate.req_enum(b, "allocation_method", ALLOCATION_METHODS)
    pool = validate.req_int(b, "revenue_sharing_pool_cents", 0)

    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")

    # Priority 39: something must actually be billable.
    firms = store.service_providers_of_plan(plan)
    if not any(f["direct_fee_cents_per_participant"] > 0 for f in firms):
        fail("ERR_NO_BILLABLE_SERVICE_PROVIDER")

    if period_end < period_start:
        fail("ERR_INVALID_DISCLOSURE_PERIOD")

    # The net plan expense is computed first: every engaged firm contributes its
    # per-participant fee to the gross, whatever its provider_type.
    expense = calc.net_plan_expense(
        plan["participant_count"],
        sum(f["direct_fee_cents_per_participant"] for f in firms),
        pool,
    )

    # The allocation runs second, over the eligible population in created_at order.
    eligible = [
        e
        for e in store.employers_of_plan(plan)
        if e["adoption_status"] in ELIGIBLE_STATUSES
    ]
    allocation = calc.revenue_sharing_allocation(eligible, method, pool)

    record = {
        "plan_document_id": plan["id"],
        "disclosure_period_start": clockcal.fmt_date(period_start),
        "disclosure_period_end": clockcal.fmt_date(period_end),
        "allocation_method": method,
        "revenue_sharing_pool_cents": pool,
        "gross_direct_fees_cents": expense["gross_direct_fees_cents"],
        "expense_rebate_pct": expense["expense_rebate_pct"],
        "revenue_sharing_offset_cents": expense["revenue_sharing_offset_cents"],
        "net_plan_expense_cents": expense["net_plan_expense_cents"],
        "total_revenue_sharing_allocated_cents": allocation[
            "total_revenue_sharing_allocated_cents"
        ],
        "residual_cents_distributed": allocation["residual_cents_distributed"],
        "allocation_lines": allocation["allocation_lines"],
        "eligible_employer_count": allocation["eligible_employer_count"],
        "disclosed_at": clockcal.stamp(),
    }
    store.insert("disclosures", record, versioned=False)

    # revenue_sharing_credit_cents is a running lifetime total per employer.
    touch = authz.touch()
    for employer in eligible:
        credit = allocation["credits"].get(employer["id"], 0)
        if credit:
            employer["revenue_sharing_credit_cents"] += credit
            touch.bump(employer)

    return envelope.ok_created(envelope.VIEWS["disclosures"](record))


@bp.get("/pep/fee-disclosures/<disclosure_id>")
def read_disclosure(disclosure_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer")
    disclosure = need("disclosures", disclosure_id, "ERR_FEE_DISCLOSURE_NOT_FOUND")
    authz.own(plan=store.plan_of_disclosure(disclosure))
    return envelope.ok_object(envelope.VIEWS["disclosures"](disclosure))


# ==========================================================================
# The logical clock -- no business state changes
# ==========================================================================


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authz.identify()
    authz.authorize("RegulatorOps")
    b = validate.body()
    instant = validate.req_instant(b, "current_utc")
    clockcal.set_clock(instant)
    return envelope.ok_object({"current_utc": clockcal.fmt_instant(clockcal.now())})
