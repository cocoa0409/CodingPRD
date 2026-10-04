"""Advances: draw headroom, approval, disbursement, rejection and repairs.

**Headroom (PRD 3.4).**  The program fee debit is the interim loan's
``principal_cents`` multiplied by ``PROGRAM_FEE_BPS`` (150) and divided by ten
thousand.  The remaining drawable amount is the loan's ``principal_cents`` minus
its ``outstanding_principal_cents`` minus that debit.  An advance is acceptable
when its ``amount_cents`` is greater than zero and is at most that remaining
amount; **the boundary is inclusive**, so an advance for exactly the remaining
amount is accepted.  A request beyond it is refused with ``ERR_NO_CAPACITY``.

**Stakeholder gate (PRD 3.4).**  A down payment advance whose amount exceeds
``STAKE_HOLDER_REVIEW_CENTS`` (9000000 cents) is not simply disbursed: it is
downgraded to a disclosure-only entry and is not auto-approved, and an attempt
to disburse it without that prior stakeholder review is refused with
``ERR_STAKEHOLDER_REVIEW_REQUIRED``.

**Rejection (PRD 3.4).**  An underwriter may reject a ``PENDING`` advance, and
may also reject one that has already been approved provided no coordination task
linked to the program has yet been completed.  On an approved-advance rejection
the system unwinds what the approval implied: any coordination task that had
been moved to ``IN_PROGRESS`` is cancelled, and if the rejected advance was the
program's sole down payment advance the program's advance axis returns to
``PENDING`` and the interim loan's status becomes ``REPAID``.  Rejecting a
``PENDING`` advance carries none of this compensation.
"""

from constants import (
    ADVANCE_PURPOSES,
    BPS_DENOMINATOR,
    PROGRAM_FEE_BPS,
    REPAIR_APPROVAL_CEILING_CENTS,
    STAKE_HOLDER_REVIEW_CENTS,
)
from errors import (
    ERR_ADVANCE_WINDOW_CLOSED,
    ERR_INVALID_STATE,
    ERR_NO_CAPACITY,
    ERR_PROPERTY_KIND_MISMATCH,
    ERR_REPAIR_SCOPE_EXCEEDS_CAP,
    ERR_STAKEHOLDER_REVIEW_REQUIRED,
    ApiError,
)
from services import current_time, create, touch
from services import burden as burden_service
from services import coordination as coordination_service
from services import loan as loan_service
from services import referral as referral_service
from services.lookup import (
    get_bridge_advance,
    get_bridge_program,
    get_interim_loan,
    get_property,
    get_repair_advance,
)
from store import db
from timeutil import format_iso
from validation import body_of, get_enum, get_int, get_str

DOWN_PAYMENT = "DOWN_PAYMENT"
DISCLOSURE = "DISCLOSURE"


# ---------------------------------------------------------------------------
# Headroom
# ---------------------------------------------------------------------------

def headroom_cents(loan):
    """The ``bridge_advance_headroom`` calculation's remaining drawable amount."""
    principal = int(loan.get("principal_cents") or 0)
    outstanding = int(loan.get("outstanding_principal_cents") or 0)
    debit = (principal * PROGRAM_FEE_BPS) // BPS_DENOMINATOR
    return principal - outstanding - debit


def assert_headroom(loan, amount_cents):
    """The boundary is inclusive at headroom; a request beyond it is refused."""
    if amount_cents <= 0:
        raise ApiError(ERR_NO_CAPACITY, "The advance amount must be greater than zero.")
    if amount_cents > headroom_cents(loan):
        raise ApiError(ERR_NO_CAPACITY, "The requested advance exceeds the loan's draw headroom.")


# ---------------------------------------------------------------------------
# Bridge advances
# ---------------------------------------------------------------------------

def request_advance(payload):
    data = body_of(payload)
    program_id = get_str(data, "bridge_program_id", required=True)
    loan_id = get_str(data, "interim_loan_id", required=True)
    purpose = get_enum(data, "purpose", ADVANCE_PURPOSES, required=True)
    amount_cents = get_int(data, "amount_cents", required=True, exclusive_minimum=0)

    program = get_bridge_program(program_id)
    loan = get_interim_loan(loan_id)

    assert_headroom(loan, amount_cents)

    record = {
        "bridge_program_id": program["id"],
        "interim_loan_id": loan["id"],
        "purpose": purpose,
        "amount_cents": amount_cents,
        "status": "PENDING",
        "advanced_at": None,
        "_disclose_only": False,
        "_discount_granted_cents": 0,
        "_discount_unfunded_cents": 0,
    }
    create("bridge_advances", record)
    return record


def approve_advance(advance_id):
    advance = get_bridge_advance(advance_id)
    if advance.get("status") != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING advance may be approved.")

    program = get_bridge_program(advance["bridge_program_id"])

    # A down payment above the stakeholder threshold is downgraded to a
    # disclosure-only entry and is not auto-approved (PRD 3.4).
    if advance.get("purpose") == DOWN_PAYMENT and int(advance.get("amount_cents") or 0) > STAKE_HOLDER_REVIEW_CENTS:
        advance["_disclose_only"] = True
        advance["purpose"] = DISCLOSURE
        touch(advance)
        touch(program)
        return advance

    granted, unfunded = referral_service.discount_for_advance(advance)
    advance["_discount_granted_cents"] = granted
    advance["_discount_unfunded_cents"] = unfunded

    advance["status"] = "APPROVED"
    touch(advance)
    touch(program)
    return advance


def reject_advance(advance_id):
    advance = get_bridge_advance(advance_id)
    status = advance.get("status")
    program = get_bridge_program(advance["bridge_program_id"])

    if status == "PENDING":
        advance["status"] = "REJECTED"
        touch(advance)
        return advance

    if status != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING or APPROVED advance may be rejected.")

    # The rejection is only permitted while no coordination task linked to the
    # program has already reached COMPLETED.
    if coordination_service.has_completed_task_for_program(program["id"]):
        raise ApiError(
            ERR_INVALID_STATE,
            "A coordination task for this program is already COMPLETED.",
        )

    advance["status"] = "REJECTED"
    touch(advance)

    # Compensate: cancel any task that the approval had moved to IN_PROGRESS.
    for task in db.all("coordination_tasks"):
        if task.get("bridge_program_id") != program["id"]:
            continue
        if task.get("status") == "IN_PROGRESS":
            task["status"] = "CANCELLED"
            touch(task)

    if _is_sole_down_payment(advance, program):
        program["advance_status"] = "PENDING"
        touch(program)
        loan = db.first_by_field("interim_loans", "bridge_program_id", program["id"])
        if loan is not None:
            loan["status"] = "REPAID"
            touch(loan)

    return advance


def _is_sole_down_payment(advance, program):
    """True when the rejected advance is the program's only down payment."""
    if advance.get("purpose") != DOWN_PAYMENT:
        return False
    for other in db.all("bridge_advances"):
        if other.get("bridge_program_id") != program["id"]:
            continue
        if other.get("id") == advance["id"]:
            continue
        if other.get("purpose") == DOWN_PAYMENT and other.get("status") != "REJECTED":
            return False
    return True


def disburse_advance(advance_id):
    advance = get_bridge_advance(advance_id)
    if advance.get("status") != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Only an APPROVED advance may be disbursed.")

    program = get_bridge_program(advance["bridge_program_id"])
    if program.get("advance_status") not in ("FUNDING", "FUNDED"):
        raise ApiError(ERR_INVALID_STATE, "The program's advance axis does not permit disbursement.")

    loan = get_interim_loan(advance["interim_loan_id"])
    amount = int(advance.get("amount_cents") or 0)

    # A down payment above the stakeholder threshold may not be disbursed
    # without that prior review (PRD 3.4).
    if advance.get("purpose") == DOWN_PAYMENT and amount > STAKE_HOLDER_REVIEW_CENTS:
        raise ApiError(
            ERR_STAKEHOLDER_REVIEW_REQUIRED,
            "This down payment requires prior stakeholder review before disbursement.",
        )

    assert_headroom(loan, amount)

    advance["status"] = "DISBURSED"
    advance["advanced_at"] = format_iso(current_time())
    touch(advance)

    loan_service.recompute_and_touch(loan)

    if advance.get("purpose") == DOWN_PAYMENT:
        program["advance_status"] = "FUNDED"
        # The down payment is what turns an originated loan into a drawn one
        # (PRD 3.5 opens the loan ``ORIGINATED``; a later disbursement is what
        # draws against it), and the household becomes BRIDGED.
        if loan.get("status") == "ORIGINATED":
            loan["status"] = "DRAWN"
        homeowner = db.get("homeowners", program.get("homeowner_id"))
        if homeowner is not None:
            homeowner["program_status"] = "BRIDGED"
            touch(homeowner)
    touch(program)

    burden_service.recompute_program_burden(program)

    # The coordination task assigned to this piece of work moves to IN_PROGRESS.
    _mark_task_in_progress(program["id"], advance.get("purpose"))
    return advance


def _mark_task_in_progress(program_id, purpose):
    candidates = [
        t for t in db.all("coordination_tasks")
        if t.get("bridge_program_id") == program_id and t.get("status") == "OPEN"
    ]
    if not candidates:
        return
    preferred = {
        "REPAIR": ("REPAIR_BID", "INSPECTION"),
        "DOWN_PAYMENT": ("CLOSING_PREP",),
    }.get(purpose, ())
    candidates.sort(key=lambda t: (t.get("created_at") or "", t.get("_seq", 0)))
    chosen = None
    for kind in preferred:
        for task in candidates:
            if task.get("task_kind") == kind:
                chosen = task
                break
        if chosen is not None:
            break
    if chosen is None:
        chosen = candidates[0]
    chosen["status"] = "IN_PROGRESS"
    touch(chosen)


# ---------------------------------------------------------------------------
# Repair advances
# ---------------------------------------------------------------------------

def request_repair_advance(payload):
    data = body_of(payload)
    property_id = get_str(data, "property_id", required=True)
    program_id = get_str(data, "bridge_program_id", required=True)
    scope = get_str(data, "scope", required=True)
    approved_amount_cents = get_int(data, "approved_amount_cents", required=True, minimum=0)
    escrow_release_mode = get_enum(
        data, "escrow_release_mode", ("LUMP_SUM", "MILESTONE"), required=False, default="MILESTONE"
    )

    property_record = get_property(property_id)
    program = get_bridge_program(program_id)

    _assert_repair_cap(property_record, approved_amount_cents, exclude_id=None)

    record = {
        "property_id": property_record["id"],
        "bridge_program_id": program["id"],
        "scope": scope,
        "approved_amount_cents": approved_amount_cents,
        "escrow_release_mode": escrow_release_mode,
        "status": "REQUESTED",
        "repaid_cents": 0,
        "disbursed_at": None,
    }
    create("repair_advances", record)
    return record


def approve_repair_advance(repair_id):
    repair = get_repair_advance(repair_id)
    if repair.get("status") != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "Only a REQUESTED repair advance may be approved.")

    program = get_bridge_program(repair["bridge_program_id"])
    if program.get("advance_status") not in ("FUNDING", "FUNDED"):
        raise ApiError(ERR_ADVANCE_WINDOW_CLOSED, "The program's advance window is closed.")

    property_record = get_property(repair["property_id"])
    if property_record.get("kind") != "DEPARTING":
        raise ApiError(ERR_PROPERTY_KIND_MISMATCH, "Repairs apply to a DEPARTING property.")

    _assert_repair_ceiling(repair)
    _assert_repair_cap(property_record, int(repair.get("approved_amount_cents") or 0), exclude_id=repair["id"])

    repair["status"] = "APPROVED"
    touch(repair)

    property_record["repair_status"] = "IN_PROGRESS"
    touch(property_record)
    return repair


def disburse_repair_advance(repair_id):
    repair = get_repair_advance(repair_id)
    if repair.get("status") != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Only an APPROVED repair advance may be disbursed.")

    program = get_bridge_program(repair["bridge_program_id"])
    if program.get("advance_status") not in ("FUNDING", "FUNDED"):
        raise ApiError(ERR_INVALID_STATE, "The program's advance axis does not permit disbursement.")

    # PRD 3.4 gates repair disbursement on the coordination work that bids the
    # repair; the scaffold states the precondition as every PHOTOGRAPHY /
    # REPAIR_BID task for the program being COMPLETED.
    if not coordination_service.tasks_unlocking_repair_complete(program["id"]):
        raise ApiError(
            ERR_INVALID_STATE,
            "Repair funds are unlocked once the programme's photo and repair-bid tasks are complete.",
        )

    loan = db.first_by_field("interim_loans", "bridge_program_id", program["id"])
    if loan is None:
        raise ApiError(ERR_INVALID_STATE, "This program has no interim loan.")

    amount = int(repair.get("approved_amount_cents") or 0)
    assert_headroom(loan, amount)

    repair["status"] = "DISBURSED"
    repair["disbursed_at"] = format_iso(current_time())
    touch(repair)

    # Disbursing approved repair funds draws them against the interim loan,
    # raising drawn_cents and outstanding_principal_cents (PRD 3.4).
    loan_service.recompute_and_touch(loan)
    touch(program)
    burden_service.recompute_program_burden(program)
    return repair


def _assert_repair_ceiling(repair):
    """The per-advance approval ceiling (PRD 3.4)."""
    amount = int(repair.get("approved_amount_cents") or 0)
    if amount > REPAIR_APPROVAL_CEILING_CENTS:
        raise ApiError(
            ERR_REPAIR_SCOPE_EXCEEDS_CAP,
            "The approved amount exceeds the %d cent repair ceiling." % REPAIR_APPROVAL_CEILING_CENTS,
        )


def _assert_repair_cap(property_record, candidate_amount, exclude_id):
    """The cumulative repair cap for the property (PRD 3.4/3.11).

    PRD 3.4 states the cumulative approved amount across every repair advance
    for the property may not exceed the property's repair cap, and applies at
    creation and again at approval.  The PRD states the per-advance ceiling as
    5000000 cents and nowhere states a different per-property figure, so the
    same figure serves as the property-level cap.
    """
    ceiling = REPAIR_APPROVAL_CEILING_CENTS
    cumulative = candidate_amount
    for other in db.all("repair_advances"):
        if other.get("property_id") != property_record["id"]:
            continue
        if exclude_id is not None and other.get("id") == exclude_id:
            continue
        cumulative += int(other.get("approved_amount_cents") or 0)
    if cumulative > REPAIR_APPROVAL_CEILING_CENTS:
        raise ApiError(
            ERR_REPAIR_SCOPE_EXCEEDS_CAP,
            "The cumulative repair amount exceeds the property's repair cap.",
        )