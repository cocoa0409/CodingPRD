"""Repayment, delinquency and the single act that settles a program.

The size and timing of a repayment determine which of several paths it takes
(PRD 3.5):

* a payment **strictly smaller** than the sum of outstanding principal and
  accrued interest reduces principal, recomputes interest and puts the loan in
  ``REPAYING``;
* a payment **exactly equal** to that sum is a final repayment: it zeroes both
  principal and interest, takes the loan to ``REPAID``, and is the only kind of
  repayment that can settle the program;
* a short or long *final* payment is refused with ``ERR_SETTLEMENT_NOT_FULL``.

A final repayment may not be posted while the program's
``outstanding_carrying_cost_cents`` is anything but zero -- the carrying costs
must be cleared first, refused with ``ERR_CARRYING_COST_UNPAID``.

Ordering note.  PRD 2.11 puts state-appropriateness before money, but the
carrying-cost condition is not a state check: it is a precondition on *final
settlement*, and PRD 3.10 states that "a final repayment that would settle the
loan but leave the program's carrying costs outstanding is refused earlier with
``ERR_CARRYING_COST_UNPAID``".  It is therefore evaluated only once the payment
is known to be final -- so an undersized payment with carrying costs outstanding
is still accepted as a partial repayment.  ``ERR_ALREADY_TERMINAL`` keeps its
state-level precedence ahead of both: a loan that is already ``REPAID`` cannot
repay again whatever the amount or the carrying costs.
"""

from constants import ADVANCE_STATUSES, LOAN_STATUSES
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CARRYING_COST_UNPAID,
    ERR_INVALID_STATE,
    ERR_LOAN_ALREADY_REPAID,
    ERR_SETTLEMENT_NOT_FULL,
    ERR_STALE_VERSION,
    ApiError,
)
from services import touch
from services import loan as loan_service
from services import program as program_service
from services.lookup import get_interim_loan
from store import db
from validation import body_of, get_int


def post_repayment(loan_id, payload):
    loan = get_interim_loan(loan_id)
    data = body_of(payload)

    amount_cents = get_int(data, "amount_cents", required=True, exclusive_minimum=0)
    expected_version = get_int(data, "expected_interim_loan_version", required=True)

    if expected_version != loan["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_interim_loan_version %s does not match the loan's version %s."
            % (expected_version, loan["version"]),
        )

    if loan.get("status") == "REPAID":
        raise ApiError(ERR_ALREADY_TERMINAL, "This loan is already repaid.")

    # PRD 2.11: state-appropriateness is judged before money.  A repayment is
    # declared only from a state the loan has actually drawn into (PRD 3.5 opens
    # the loan ORIGINATED, and the repayment paths run from DRAWN, REPAYING or
    # DELINQUENT), so an undrawn loan is refused as a state error before any
    # amount is compared.
    if loan.get("status") not in ("DRAWN", "REPAYING", "DELINQUENT"):
        raise ApiError(
            ERR_INVALID_STATE,
            "No repayment path is declared from the loan's current state.",
        )

    program = db.get("bridge_programs", loan.get("bridge_program_id"))

    loan_service.recompute(loan)
    total = loan_service.combined_balance(loan)

    if amount_cents < total:
        loan_service.apply_principal_payment(loan, amount_cents)
        loan_service.recompute(loan)
        loan["status"] = "REPAYING"
        touch(loan)
        return loan

    if amount_cents > total:
        raise ApiError(
            ERR_SETTLEMENT_NOT_FULL,
            "A final repayment must equal the combined principal and interest.",
        )

    # The payment is exactly the combined balance, so it is a final repayment.
    if program is not None and int(program.get("outstanding_carrying_cost_cents") or 0) != 0:
        raise ApiError(
            ERR_CARRYING_COST_UNPAID,
            "Outstanding carrying costs must be cleared before the program can settle.",
        )

    loan_service.apply_final_payment(loan)
    loan_service.recompute(loan)
    loan["outstanding_principal_cents"] = 0
    loan["accrued_interest_cents"] = 0
    loan["status"] = "REPAID"
    touch(loan)

    if program is not None:
        program_service.settle_program_for_final_repayment(program)
    return loan


def reopen_advance(loan_id, actor):
    """Reopen a repaid loan when a repair clawback remains un-repaid (PRD 3.5)."""
    loan = get_interim_loan(loan_id)

    if loan.get("status") != "REPAID":
        raise ApiError(ERR_LOAN_ALREADY_REPAID, "Only a REPAID loan may be reopened.")

    program_id = loan.get("bridge_program_id")
    candidate = None
    for repair in db.all("repair_advances"):
        if repair.get("bridge_program_id") != program_id:
            continue
        if repair.get("status") != "DISBURSED":
            continue
        if int(repair.get("repaid_cents") or 0) < int(repair.get("approved_amount_cents") or 0):
            candidate = repair
            break

    if candidate is None:
        raise ApiError(
            ERR_LOAN_ALREADY_REPAID,
            "No disbursed repair advance with an un-repaid balance exists for this program.",
        )

    if loan.get("_reopened_for_repair_id") == candidate["id"]:
        raise ApiError(ERR_LOAN_ALREADY_REPAID, "A reopen has already been applied for this repair.")

    un_clawed = int(candidate.get("approved_amount_cents") or 0) - int(candidate.get("repaid_cents") or 0)

    loan["_reopened_for_repair_id"] = candidate["id"]
    loan["status"] = "REPAYING"
    loan["_repaid_principal_cents"] = max(int(loan.get("drawn_cents") or 0) - un_clawed, 0)
    loan_service.recompute(loan)
    loan["outstanding_principal_cents"] = un_clawed
    touch(loan)
    return loan