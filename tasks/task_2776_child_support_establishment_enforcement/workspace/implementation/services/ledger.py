"""Payment allocation waterfall and the TANF/non-TANF distribution split
(PRD 3.5).  The waterfall performs no rounding of any kind.
"""
import db
from services import interest

TANF_PASS_THROUGH_CAP_CENTS = 10000


def _sorted(rows):
    return sorted(rows, key=lambda c: (c["due_date"], c["created_at"], c["_seq"]))


def _period_covers(charge, day):
    """period_start_date is inclusive, period_end_date is exclusive."""
    return charge["period_start_date"] <= day < charge["period_end_date"]


def genetic_cost_outstanding(case):
    """Unreimbursed genetic testing cost, when the obligor is liable."""
    action = db.case_paternity_action(case["id"])
    if action is None or action.get("genetic_cost_liable_party") != "NCP":
        return 0
    cost = action.get("genetic_cost_cents") or 0
    reimbursed = sum(p.get("applied_genetic_cost_cents") or 0
                     for p in db.case_payments(case["id"]))
    return max(0, cost - reimbursed)


def allocate(case, amount_cents, received_at):
    """Run the six buckets in order and mutate the charges they consume."""
    received_day = received_at.date()
    # Bucket four's ceiling is snapshotted at the start of the request.
    interest_snapshot = interest.interest_receivable(case)
    genetic_snapshot = genetic_cost_outstanding(case)

    remaining = amount_cents
    applied = {
        "applied_current_cents": 0,
        "applied_medical_cents": 0,
        "applied_arrears_cents": 0,
        "applied_interest_cents": 0,
        "applied_genetic_cost_cents": 0,
        "unapplied_credit_cents": 0,
    }
    visited = set()
    open_charges = [c for c in db.case_charges(case["id"]) if c["status"] == "OPEN"]

    def consume(rows, key):
        nonlocal remaining
        for charge in rows:
            if remaining == 0:
                break
            visited.add(charge["id"])
            take = min(remaining, charge["unpaid_balance_cents"])
            if take == 0:
                continue
            charge["paid_cents"] += take
            charge["unpaid_balance_cents"] -= take
            applied[key] += take
            remaining -= take

    # Bucket 1 — current support for the period the payment lands in.
    consume(_sorted([c for c in open_charges
                     if c["charge_type"] == "CURRENT_SUPPORT"
                     and _period_covers(c, received_day)]),
            "applied_current_cents")
    # Bucket 2 — medical support for the same period.
    consume(_sorted([c for c in open_charges
                     if c["charge_type"] == "MEDICAL_SUPPORT"
                     and _period_covers(c, received_day)]),
            "applied_medical_cents")
    # Bucket 3 — arrears: every remaining open charge, oldest first.
    consume(_sorted([c for c in open_charges if c["id"] not in visited]),
            "applied_arrears_cents")

    # Bucket 4 — interest, capped by the snapshot taken above.
    if remaining != 0 and interest_snapshot > 0:
        take = min(remaining, interest_snapshot)
        applied["applied_interest_cents"] = take
        remaining -= take

    # Bucket 5 — genetic testing cost, only when the obligor is liable.
    if remaining != 0 and genetic_snapshot > 0:
        take = min(remaining, genetic_snapshot)
        applied["applied_genetic_cost_cents"] = take
        remaining -= take

    # Bucket 6 — whatever is left becomes unapplied credit.
    applied["unapplied_credit_cents"] = remaining

    # A charge driven to a zero balance is satisfied, retroactively silencing
    # interest from this payment's received_at onward.
    for charge_id in visited:
        charge = db.charges.get(charge_id)
        if charge is not None and charge["status"] == "OPEN" \
                and charge["unpaid_balance_cents"] <= 0:
            charge["unpaid_balance_cents"] = 0
            charge["status"] = "SATISFIED"
    return applied


def distribute(case, amount_cents, applied):
    """Split the applied buckets between the custodian and the state."""
    distributable = (applied["applied_current_cents"]
                     + applied["applied_medical_cents"]
                     + applied["applied_arrears_cents"]
                     + applied["applied_interest_cents"]
                     + applied["applied_genetic_cost_cents"])
    if case["tanf_assistance"]:
        pass_through = min(applied["applied_current_cents"],
                           TANF_PASS_THROUGH_CAP_CENTS)
        disbursed = pass_through
        retained = distributable - pass_through
    else:
        disbursed = (applied["applied_current_cents"]
                     + applied["applied_medical_cents"]
                     + applied["applied_arrears_cents"])
        retained = (applied["applied_interest_cents"]
                    + applied["applied_genetic_cost_cents"])
    return disbursed, retained


def post_to_case(case, applied):
    """Roll the buckets into the case's running ledger counters."""
    case["total_collected_principal_cents"] += (
        applied["applied_current_cents"]
        + applied["applied_medical_cents"]
        + applied["applied_arrears_cents"]
        + applied["applied_genetic_cost_cents"])
    case["interest_collected_cents"] += applied["applied_interest_cents"]
    case["unapplied_credit_cents"] += applied["unapplied_credit_cents"]
