"""PRD 2.9 -- plan control totals, derived gates and employer-derived fields.

The plan document is the reconciliation point for the whole plan and its
derived fields are recomputed after EVERY transition that moves money or
headcount: payroll batch validation, deposit posting, deposit reversal,
correction funding, exit settlement, exit reversal, employer admission and
census restatement.
"""

import calc
import store

# Statuses that keep an employer inside the plan's headcount.
IN_PLAN_STATUSES = (
    "APPLIED",
    "ELECTIONS_SUBMITTED",
    "RETURNED_FOR_REVISION",
    "ACTIVE",
    "SUSPENDED",
    "EXIT_REQUESTED",
    "SPINOFF_IN_PROGRESS",
)
ACTIVE_GATE_STATUSES = ("ACTIVE", "EXIT_REQUESTED", "SPINOFF_IN_PROGRESS")
OPEN_CORRECTION_TIMELINESS = ("LATE", "CORRECTION_COMPUTED")


def new_plan_totals():
    """Every control total of PRD 2.9 initialised to zero."""
    return {
        "participant_count": 0,
        "cumulative_enrolled_participant_count": 0,
        "transferred_out_participant_count": 0,
        "headcount_control_delta": 0,
        "active_employer_count": 0,
        "suspended_employer_count": 0,
        "compliance_posture": "OPEN",
        "audit_required": False,
        "total_validated_contributions_cents": 0,
        "aggregate_receivable_cents": 0,
        "total_assets_cents": 0,
        "total_corrections_funded_cents": 0,
        "transferred_out_cents": 0,
        "expense_recovered_cents": 0,
        "contribution_control_delta_cents": 0,
    }


# --------------------------------------------------------------------------
# Employer-derived fields
# --------------------------------------------------------------------------


def employer_census_flags(employer):
    """is_small_plan selects the 7-business-day safe harbour; the audit flag is
    the mirror image at the same 100-participant line."""
    small = employer["participant_count"] < calc.SMALL_PLAN_PARTICIPANT_THRESHOLD
    employer["is_small_plan"] = small
    employer["employer_audit_required"] = not small


def employer_receivable(employer):
    """The sum of batch_total_cents over the employer's batches still VALIDATED."""
    return sum(
        b["batch_total_cents"]
        for b in store.batches_of_employer(employer)
        if b["status"] == "VALIDATED"
    )


def open_correction_deposits(employer):
    """Deposits that are POSTED with timeliness LATE or CORRECTION_COMPUTED."""
    return [
        d
        for d in store.deposits_of_employer(employer)
        if d["deposit_status"] == "POSTED"
        and d["timeliness_status"] in OPEN_CORRECTION_TIMELINESS
    ]


def recompute_employer_corrections(employer):
    """contribution_hold is true exactly when at least one such deposit exists,
    and open_correction_count is the count of them."""
    open_ones = open_correction_deposits(employer)
    employer["open_correction_count"] = len(open_ones)
    employer["contribution_hold"] = len(open_ones) > 0
    return len(open_ones)


# --------------------------------------------------------------------------
# Plan control totals
# --------------------------------------------------------------------------


def recompute_plan(plan, touch):
    employers = store.employers_of_plan(plan)
    batches = store.batches_of_plan(plan)
    deposits = store.deposits_of_plan(plan)
    settled = [t for t in store.exits_of_plan(plan) if t["status"] == "SETTLED"]

    plan["total_validated_contributions_cents"] = sum(
        b["batch_total_cents"] for b in batches
        if b["status"] in ("VALIDATED", "REMITTED")
    )
    plan["aggregate_receivable_cents"] = sum(
        b["batch_total_cents"] for b in batches if b["status"] == "VALIDATED"
    )
    plan["expense_recovered_cents"] = sum(
        t["deductions_applied_cents"] or 0 for t in settled
    )
    plan["total_assets_cents"] = (
        sum(e["account_balance_cents"] for e in employers)
        + plan["expense_recovered_cents"]
    )
    plan["total_corrections_funded_cents"] = sum(
        d["restoration_cents"] or 0 for d in deposits
        if d["timeliness_status"] == "CORRECTED"
    )
    plan["transferred_out_cents"] = sum(
        t["transfer_amount_cents"] or 0 for t in settled
    )
    plan["contribution_control_delta_cents"] = (
        plan["total_assets_cents"]
        + plan["aggregate_receivable_cents"]
        + plan["transferred_out_cents"]
        - plan["total_corrections_funded_cents"]
        - plan["total_validated_contributions_cents"]
    )

    plan["participant_count"] = sum(
        e["participant_count"] for e in employers
        if e["adoption_status"] in IN_PLAN_STATUSES
    )
    plan["transferred_out_participant_count"] = sum(
        t["transferred_participant_count"] or 0 for t in settled
    )
    plan["headcount_control_delta"] = (
        plan["participant_count"]
        + plan["transferred_out_participant_count"]
        - plan["cumulative_enrolled_participant_count"]
    )

    plan["active_employer_count"] = sum(
        1 for e in employers if e["adoption_status"] in ACTIVE_GATE_STATUSES
    )
    suspended = sum(1 for e in employers if e["adoption_status"] == "SUSPENDED")
    plan["suspended_employer_count"] = suspended
    plan["compliance_posture"] = (
        "OPEN" if suspended == 0 else ("RESTRICTED" if suspended == 1 else "FROZEN")
    )
    plan["audit_required"] = (
        plan["participant_count"] >= calc.PLAN_AUDIT_PARTICIPANT_THRESHOLD
    )

    touch.bump(plan)
    return plan
