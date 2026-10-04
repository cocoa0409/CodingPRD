"""Program charge disclosure (PRD 3.9).

Three figures are disclosed, each floored:

* the **origination** charge is the interim loan's principal multiplied by the
  program's ``program_fee_basis_points`` and divided by ten thousand;
* the **coordination** charge is a flat 45000 cents; once two or more referrals
  are active, each additional ``OPEN`` referral adds a further coordination
  amount to that flat charge before the subtotal is formed;
* the **escalator**, which is where the careful reading pays off.  When the
  subtotal exceeds ``DISCLOSURE_MIN_CENTS`` (300000) the escalator is a
  percentage of the *actual* subtotal -- 500 basis points when it also exceeds
  ``DISCLOSURE_REVIEW_CENTS`` (500000) and 250 basis points when it does not.
  When the subtotal is at or below ``DISCLOSURE_MIN_CENTS`` the escalator is
  deliberately not computed against the small actual subtotal: it is computed
  against the fixed reference ``SUBTOTAL_REFERENCE_CENTS`` (400000) at 250 basis
  points.  That fixed reference is the evaluation-order trap in this
  calculation, and the low band ignores the small subtotal it nominally
  evaluates.

``total_program_charge_cents`` is the subtotal plus the floored escalator.

Disclosure preview runs before funding, at which point no interim loan exists
yet; the principal basis is then the linked qualification's ``capacity_cents``,
which is exactly the principal the loan will take when the program is funded.
"""

from constants import (
    COORDINATION_FLAT_CENTS,
    DISCLOSURE_MIN_CENTS,
    DISCLOSURE_REVIEW_CENTS,
    ESCALATOR_HIGH_BPS,
    ESCALATOR_LOW_BPS,
    REFERRAL_COORDINATION_CENTS,
    SUBTOTAL_REFERENCE_CENTS,
    BPS_DENOMINATOR,
)
from services.lookup import lookup, get_bridge_program
from store import db


def active_referrals_for_program(program_id):
    """Referral rows for the program that are still ``OPEN``."""
    return [
        r for r in db.all("referrals")
        if r.get("bridge_program_id") == program_id and r.get("status") == "OPEN"
    ]


def principal_basis_cents(program):
    """The principal the disclosure is computed against.

    A funded program has an interim loan whose principal is the qualification's
    capacity; before funding the capacity stands in for it.
    """
    loan = db.first_by_field("interim_loans", "bridge_program_id", program["id"])
    if loan is not None:
        return int(loan.get("principal_cents") or 0)
    qualification = lookup("qualifications", program.get("qualification_id"))
    if qualification is not None:
        return int(qualification.get("capacity_cents") or 0)
    return 0


def coordination_charge_cents(program):
    """The flat coordination charge plus any per-additional-referral amount."""
    count = len(active_referrals_for_program(program["id"]))
    extra_referrals = max(count - 1, 0)
    additional = 0
    if REFERRAL_COORDINATION_CENTS is not None:
        additional = extra_referrals * int(REFERRAL_COORDINATION_CENTS)
    return COORDINATION_FLAT_CENTS + additional


def compute_origination_cents(program, principal_cents=None):
    if principal_cents is None:
        principal_cents = principal_basis_cents(program)
    fee_bps = int(program.get("program_fee_basis_points") or 0)
    return (principal_cents * fee_bps) // BPS_DENOMINATOR


def compute_escalator_cents(subtotal_cents):
    if subtotal_cents > DISCLOSURE_MIN_CENTS:
        rate = ESCALATOR_HIGH_BPS if subtotal_cents > DISCLOSURE_REVIEW_CENTS else ESCALATOR_LOW_BPS
        return (subtotal_cents * rate) // BPS_DENOMINATOR
    return (SUBTOTAL_REFERENCE_CENTS * ESCALATOR_LOW_BPS) // BPS_DENOMINATOR


def compute_disclosure(program, principal_cents=None):
    """The ``program_charge_disclosure`` calculation."""
    origination = compute_origination_cents(program, principal_cents)
    coordination = coordination_charge_cents(program)
    subtotal = origination + coordination
    escalator = compute_escalator_cents(subtotal)
    return {
        "origination_cents": origination,
        "coordination_cents": coordination,
        "escalator_cents": escalator,
        "total_program_charge_cents": subtotal + escalator,
    }


def recompute_program_charge(program, bump_version=False):
    """Refresh the program's disclosed total from the current picture."""
    from services import touch

    figures = compute_disclosure(program)
    program["total_program_charge_cents"] = figures["total_program_charge_cents"]
    if bump_version:
        touch(program)
    return program


def program_or_404(program_id):
    return get_bridge_program(program_id)