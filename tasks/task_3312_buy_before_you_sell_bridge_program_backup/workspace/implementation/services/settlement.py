"""Settlement entries: disbursements, the three-way split and clawbacks (PRD 3.9).

A ``Disbursement`` is created against a program with a ``source_kind`` of
``CLOSING_SALE``, ``RESALE`` or ``REPAIR_CLAWBACK`` and an ``amount_cents``,
opening ``RECORDED``; it moves to ``APPLIED`` when it is processed.

A settlement entry may never exceed the combined outstanding principal and
accrued interest of the loan it settles (``ERR_DISBURSEMENT_EXCEEDS_BALANCE``),
and once applied it is split three ways: the portion applied to principal, the
portion applied to interest, and the remainder left once principal and interest
are satisfied.

A clawback is capped as well: a ``REPAIR_CLAWBACK`` entry may not exceed the
linked repair advance's approved amount less whatever has already been clawed
back from it.  Applying a clawback raises that repair advance's ``repaid_cents``,
and when the clawback brings ``repaid_cents`` level with
``approved_amount_cents`` the linked property's ``repair_status`` becomes
``COMPLETE``.

Applying a closing-sale or resale settlement sets covered advances to
``REPAID``, recomputes the loan's balances, and -- when the settlement is a
resale -- flips the property's ``program_inventory_flag`` back to false and its
``listing_status`` to ``RESOLD``.
"""

from constants import DISBURSEMENT_SOURCE_KINDS
from errors import (
    ERR_DISBURSEMENT_EXCEEDS_BALANCE,
    ERR_INVALID_STATE,
    ApiError,
)
from services import create, touch
from services import loan as loan_service
from services.lookup import get_bridge_program, get_property
from store import db
from validation import body_of, get_enum, get_int, get_str

CLOSING_SALE = "CLOSING_SALE"
RESALE = "RESALE"
REPAIR_CLAWBACK = "REPAIR_CLAWBACK"


def record_disbursement(payload):
    data = body_of(payload)
    program_id = get_str(data, "bridge_program_id", required=True)
    source_kind = get_enum(data, "source_kind", DISBURSEMENT_SOURCE_KINDS, required=True)
    amount_cents = get_int(data, "amount_cents", required=True, exclusive_minimum=0)

    return apply_entry(program_id, source_kind, amount_cents)


def apply_entry(program_id, source_kind, amount_cents):
    """Record and apply a settlement entry from an already-validated amount.

    The internal variant exists because an operation such as ``close-sale``
    books its entry as a side effect: a sale whose proceeds exactly cover a
    fully repaid loan books a zero-amount entry, and a zero amount is only
    invalid when a *client* supplies it.
    """
    program = get_bridge_program(program_id)
    if program.get("advance_status") == "SETTLED":
        raise ApiError(ERR_INVALID_STATE, "A settled program accepts no further settlement entries.")

    loan = db.first_by_field("interim_loans", "bridge_program_id", program["id"])
    if loan is None:
        raise ApiError(ERR_INVALID_STATE, "This program has no interim loan to settle against.")

    amount_cents = int(amount_cents)
    if source_kind == REPAIR_CLAWBACK:
        repair = _clawback_repair_advance(program)
        un_clawed = int(repair.get("approved_amount_cents") or 0) - int(repair.get("repaid_cents") or 0)
        if amount_cents > un_clawed:
            raise ApiError(
                ERR_DISBURSEMENT_EXCEEDS_BALANCE,
                "The clawback exceeds the repair advance's un-repaid approved amount.",
            )
    else:
        balance = loan_service.combined_balance(loan)
        if amount_cents > balance:
            raise ApiError(
                ERR_DISBURSEMENT_EXCEEDS_BALANCE,
                "The settlement amount exceeds the loan's combined outstanding balance.",
            )

    entry = {
        "bridge_program_id": program["id"],
        "source_kind": source_kind,
        "amount_cents": amount_cents,
        "status": "RECORDED",
        "applied_to_principal_cents": 0,
        "applied_to_interest_cents": 0,
        "remainder_cents": 0,
        "interim_loan_id": loan["id"],
        "repair_advance_id": None,
    }
    create("disbursements", entry)

    if source_kind == REPAIR_CLAWBACK:
        _apply_clawback(entry, program, loan)
    else:
        _apply_settlement(entry, program, loan, source_kind)

    return entry


def _clawback_repair_advance(program):
    for repair in db.all("repair_advances"):
        if repair.get("bridge_program_id") == program["id"] and repair.get("status") == "DISBURSED":
            return repair
    raise ApiError(ERR_INVALID_STATE, "No disbursed repair advance exists to claw back.")


def _apply_clawback(entry, program, loan):
    repair = _clawback_repair_advance(program)
    entry["repair_advance_id"] = repair["id"]

    # A clawback's proceeds are applied to principal first, then interest, with
    # any excess reported as remainder -- the same three-way split.
    outstanding_principal = int(loan.get("outstanding_principal_cents") or 0)
    accrued_interest = int(loan.get("accrued_interest_cents") or 0)
    amount = int(entry["amount_cents"])

    to_principal = min(amount, outstanding_principal)
    to_interest = min(amount - to_principal, accrued_interest)
    entry["applied_to_principal_cents"] = to_principal
    entry["applied_to_interest_cents"] = to_interest
    entry["remainder_cents"] = amount - to_principal - to_interest

    loan_service.apply_principal_payment(loan, to_principal)
    loan["_repaid_interest_cents"] = int(loan.get("_repaid_interest_cents") or 0) + to_interest
    entry["status"] = "APPLIED"
    touch(entry)

    repair["repaid_cents"] = int(repair.get("repaid_cents") or 0) + amount
    touch(repair)
    if int(repair["repaid_cents"]) >= int(repair.get("approved_amount_cents") or 0):
        repair["status"] = "SETTLED"
        touch(repair)
        property_record = get_property(repair["property_id"])
        property_record["repair_status"] = "COMPLETE"
        touch(property_record)

    loan_service.recompute_and_touch(loan)
    touch(program)
    return entry


def _apply_settlement(entry, program, loan, source_kind):
    outstanding_principal = int(loan.get("outstanding_principal_cents") or 0)
    accrued_interest = int(loan.get("accrued_interest_cents") or 0)
    amount = int(entry["amount_cents"])

    to_principal = min(amount, outstanding_principal)
    to_interest = min(amount - to_principal, accrued_interest)
    entry["applied_to_principal_cents"] = to_principal
    entry["applied_to_interest_cents"] = to_interest
    entry["remainder_cents"] = amount - to_principal - to_interest

    loan_service.apply_principal_payment(loan, to_principal)
    loan["_repaid_interest_cents"] = int(loan.get("_repaid_interest_cents") or 0) + to_interest

    # Covered advances are retired (PRD 3.9: "sets covered advances to REPAID").
    _retire_covered_advances(loan, to_principal)

    entry["status"] = "APPLIED"
    touch(entry)

    loan_service.recompute_and_touch(loan)

    if source_kind == RESALE:
        property_record = get_property(program["departing_property_id"])
        property_record["program_inventory_flag"] = False
        property_record["listing_status"] = "RESOLD"
        touch(property_record)

    touch(program)
    return entry


def _retire_covered_advances(loan, applied_principal_cents):
    """Mark disbursed advances ``REPAID`` up to the principal the entry covered."""
    covered = 0
    for advance in loan_service.disbursed_advances(loan):
        if covered >= applied_principal_cents:
            break
        advance["status"] = "REPAID"
        touch(advance)
        covered += int(advance.get("amount_cents") or 0)


def create_resale_entry_from_exercise(program):
    """The settlement entry an exercised guarantee records (PRD 3.9).

    Exercising always records a ``RESALE`` entry -- the PRD lists it among the
    exercise's side effects without conditioning it on the loan having been
    drawn.  The entry stays ``RECORDED`` rather than ``APPLIED``: applying a
    resale settlement would flip ``program_inventory_flag`` back to false and the
    property to ``RESOLD``, which is the opposite of what the exercise itself
    just set.
    """
    loan = db.first_by_field("interim_loans", "bridge_program_id", program["id"])
    if loan is None:
        return None
    balance = loan_service.combined_balance(loan)
    entry = {
        "bridge_program_id": program["id"],
        "source_kind": RESALE,
        "amount_cents": max(balance, 0),
        "status": "RECORDED",
        "applied_to_principal_cents": 0,
        "applied_to_interest_cents": 0,
        "remainder_cents": 0,
        "interim_loan_id": loan["id"],
        "repair_advance_id": None,
    }
    create("disbursements", entry)
    return entry


def summary(program_id=None):
    """The aggregate settlement read (PRD 3.11)."""
    entries = [
        d for d in db.all("disbursements")
        if d.get("status") == "APPLIED"
        and (program_id is None or d.get("bridge_program_id") == program_id)
    ]
    return {
        "total_applied_to_principal_cents": sum(int(d.get("applied_to_principal_cents") or 0) for d in entries),
        "total_applied_to_interest_cents": sum(int(d.get("applied_to_interest_cents") or 0) for d in entries),
        "remainder_cents": sum(int(d.get("remainder_cents") or 0) for d in entries),
        "entry_count": len(entries),
    }