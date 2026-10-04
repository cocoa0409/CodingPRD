"""Qualification: the capacity reading, its revision, approval and denial.

Precedence (PRD 2.11) is applied literally in this module: the payload is
inspected for missing or out-of-range fields first (``ERR_INVALID_REQUEST``),
referenced resources are resolved next in left-to-right order (a 404 outranks
any 409 or 422 on the same request), and only then are state-appropriateness and
the economic checks applied.

Revision is permitted on a ``PENDING`` qualification and also on one that has
already been ``APPROVED``, in which case the record returns to ``PENDING`` --
but only while no enrolment has moved past its own opening state.  A
qualification that has already been enrolled and funded can no longer be
reopened this way, and the attempt is refused.

Approval is where the household's position in the program is established: the
household must clear the lender's floor (620), approval recomputes
``departing_equity_cents`` as the net equity across every departing property the
household holds, moves ``program_status`` to ``QUALIFYING`` and takes the
qualification to ``APPROVED``.  Denial is the parallel branch: the coordinator
supplies a free-text ``denial_reason``, the qualification moves to ``DENIED`` and
the household's ``program_status`` becomes ``WITHDRAWN``.
"""

from constants import (
    CREDIT_SCORE_MINIMUM,
    QUALIFICATION_VARIANTS,
    QUALIFICATION_STATUSES,
)
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CREDIT_SCORE_BELOW_MINIMUM,
    ERR_HOMEOWNER_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PROPERTY_KIND_MISMATCH,
    ApiError,
)
from services import capacity as capacity_service
from services import current_time, create, touch
from services.lookup import get_homeowner, get_property, get_qualification
from store import db
from timeutil import format_iso
from validation import body_of, get_enum, get_int, get_str

PENDING = "PENDING"
APPROVED = "APPROVED"
DENIED = "DENIED"
EXPIRED = "EXPIRED"


def _assert_property_roles(departing_property, new_property):
    """The role each property plays is fixed at reference time (PRD 3.11)."""
    if departing_property.get("kind") != "DEPARTING":
        raise ApiError(
            ERR_PROPERTY_KIND_MISMATCH,
            "The departing property must be of kind DEPARTING.",
        )
    if new_property.get("kind") != "NEW":
        raise ApiError(ERR_PROPERTY_KIND_MISMATCH, "The new property must be of kind NEW.")


def _assert_ownership(homeowner, departing_property, new_property):
    if departing_property.get("homeowner_id") != homeowner["id"]:
        raise ApiError(ERR_HOMEOWNER_MISMATCH, "The departing property is not owned by this household.")
    if new_property.get("homeowner_id") != homeowner["id"]:
        raise ApiError(ERR_HOMEOWNER_MISMATCH, "The new property is not owned by this household.")


def create_qualification(payload):
    data = body_of(payload)

    homeowner_id = get_str(data, "homeowner_id", required=True)
    departing_property_id = get_str(data, "departing_property_id", required=True)
    new_property_id = get_str(data, "new_property_id", required=True)
    target_purchase_price_cents = get_int(data, "target_purchase_price_cents", required=True, minimum=0)
    variant_used = get_enum(
        data, "variant_used", QUALIFICATION_VARIANTS, required=False, default="CONSERVATIVE"
    )

    homeowner = get_homeowner(homeowner_id)
    departing_property = get_property(departing_property_id)
    new_property = get_property(new_property_id)

    _assert_property_roles(departing_property, new_property)
    _assert_ownership(homeowner, departing_property, new_property)

    record = {
        "homeowner_id": homeowner["id"],
        "departing_property_id": departing_property["id"],
        "new_property_id": new_property["id"],
        "target_purchase_price_cents": target_purchase_price_cents,
        "variant_used": variant_used,
        "capacity_cents": 0,
        "equity_ratio": 0.0,
        "status": PENDING,
        "denial_reason": None,
        "approved_at": None,
    }
    create("qualifications", record)
    _recompute_reading(record, homeowner, departing_property)
    return record


def revise_qualification(qualification_id, payload):
    data = body_of(payload)
    qualification = get_qualification(qualification_id)

    if "variant_used" in data and data["variant_used"] is not None:
        variant_used = get_enum(data, "variant_used", QUALIFICATION_VARIANTS, required=False)
    else:
        variant_used = None
    if "target_purchase_price_cents" in data and data["target_purchase_price_cents"] is not None:
        target = get_int(data, "target_purchase_price_cents", required=False, minimum=0)
    else:
        target = None

    status = qualification.get("status")
    if status in (DENIED, EXPIRED):
        raise ApiError(ERR_INVALID_STATE, "A denied or expired qualification cannot be revised.")
    if status not in (PENDING, APPROVED):
        raise ApiError(ERR_INVALID_STATE, "The qualification is not in a revocable state.")

    if status == APPROVED:
        if _has_funded_enrolment(qualification["id"]):
            raise ApiError(
                ERR_INVALID_STATE,
                "A qualification that has already been enrolled and funded cannot be reopened.",
            )

    if variant_used is not None:
        qualification["variant_used"] = variant_used
    if target is not None:
        qualification["target_purchase_price_cents"] = target

    qualification["status"] = PENDING
    homeowner = get_homeowner(qualification["homeowner_id"])
    departing_property = get_property(qualification["departing_property_id"])
    _recompute_reading(qualification, homeowner, departing_property)
    # Revising is a mutation of the record (PRD 2.5), so it refreshes
    # ``updated_at`` and increments ``version`` even when the revision only
    # moves the status back to PENDING.
    touch(qualification)
    return qualification


def approve_qualification(qualification_id):
    qualification = get_qualification(qualification_id)
    status = qualification.get("status")

    if status in (DENIED, EXPIRED):
        raise ApiError(ERR_ALREADY_TERMINAL, "This qualification is already terminal.")
    if status != PENDING:
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING qualification may be approved.")

    homeowner = get_homeowner(qualification["homeowner_id"])
    if int(homeowner.get("credit_score") or 0) < CREDIT_SCORE_MINIMUM:
        raise ApiError(
            ERR_CREDIT_SCORE_BELOW_MINIMUM,
            "The household credit score is below %d." % CREDIT_SCORE_MINIMUM,
        )

    departing_property = get_property(qualification["departing_property_id"])
    _recompute_reading(qualification, homeowner, departing_property)

    qualification["status"] = APPROVED
    qualification["approved_at"] = format_iso(current_time())
    touch(qualification)

    homeowner["departing_equity_cents"] = capacity_service.household_net_equity(homeowner)
    homeowner["program_status"] = "QUALIFYING"
    touch(homeowner)
    return qualification


def deny_qualification(qualification_id, payload):
    data = body_of(payload)
    denial_reason = get_str(data, "denial_reason", required=True)

    qualification = get_qualification(qualification_id)
    if qualification.get("status") != PENDING:
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING qualification may be denied.")

    qualification["status"] = DENIED
    qualification["denial_reason"] = denial_reason
    touch(qualification)

    homeowner = get_homeowner(qualification["homeowner_id"])
    homeowner["program_status"] = "WITHDRAWN"
    touch(homeowner)
    return qualification


def _recompute_reading(qualification, homeowner, departing_property):
    qualification["capacity_cents"] = capacity_service.compute_capacity_cents(
        homeowner, departing_property, qualification["variant_used"]
    )
    qualification["equity_ratio"] = capacity_service.compute_equity_ratio(departing_property)
    return qualification


def _has_funded_enrolment(qualification_id):
    """True when a referencing program has moved past its opening state."""
    for program in db.all("bridge_programs"):
        if program.get("qualification_id") != qualification_id:
            continue
        if program.get("advance_status") != "PENDING":
            return True
    return False