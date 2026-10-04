"""Bridge program workflows: enrolment, funding, occupancy and settlement.

Funding (PRD 3.3) is heavier than its name suggests.  Four things must hold
first: the program is still ``PENDING`` on its advance axis, the linked
qualification is ``APPROVED``, the linked property is genuinely the home being
bought (kind ``NEW``), and no interim loan already exists for the program.  When
those hold, funding originates an interim loan in ``ORIGINATED`` status whose
principal is exactly the qualification's ``capacity_cents``, stamped with an
``originated_at`` read from the logical clock; it creates the disclosure-backed
advance entries that represent the program's own charges, recomputes
``total_program_charge_cents``, resets the linked departing property's
``listing_status`` to ``UNLISTED``, and moves the household's ``program_status``
to ``ENROLLED``.  The program's advance axis becomes ``FUNDING``.

Two further gates guard the money: the loan-to-value ceiling of 7500 basis
points of the new property's appraised value, and appraisal staleness.
"""

from constants import (
    ADVANCE_PURPOSES,
    APPRAISAL_VALIDITY_DAYS,
    BPS_DENOMINATOR,
    DEFAULT_MORTGAGE_PAYOFF_CENTS,
    DEFAULT_PROGRAM_FEE_BASIS_POINTS,
    DEFAULT_PURCHASE_PRICE_CENTS,
    DEFAULT_REPAIR_PROGRESS_BPS,
    LOGICAL_CLOCK_START,
    LTV_MAX_BPS,
    PROJECTED_CARRY_MONTHS_MAX,
    PROJECTED_CARRY_MONTHS_MIN,
)
from errors import (
    ERR_APPRAISAL_STALE,
    ERR_BRIDGE_PROGRAM_NOT_FOUND,
    ERR_HOMEOWNER_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LTV_EXCEEDS_LIMIT,
    ERR_PROPERTY_KIND_MISMATCH,
    ERR_QUALIFICATION_NOT_FOUND,
    ERR_STALE_VERSION,
    ApiError,
)
from services import current_time, create, public, touch
from services import disclosure as disclosure_service
from services import loan as loan_service
from services.lookup import (
    fetch,
    get_bridge_program,
    get_homeowner,
    get_interim_loan,
    get_property,
    get_qualification,
    lookup,
)
from store import db
from timeutil import add_days, format_iso, parse_iso
from validation import body_of, get_datetime, get_enum, get_int, get_str


def create_program(homeowner_id, qualification_id, new_property_id, departing_property_id,
                   projected_carry_months, program_fee_basis_points):
    """Enrol an approved qualification into the bridge program."""
    homeowner = get_homeowner(homeowner_id)
    qualification = get_qualification(qualification_id)
    new_property = get_property(new_property_id)
    departing_property = get_property(departing_property_id)

    # A qualification that pairs a household with a property it does not own is
    # refused with ERR_HOMEOWNER_MISMATCH (PRD 3.2), and the role each property
    # plays is fixed at the moment it is referenced (PRD 3.11).
    if new_property.get("homeowner_id") != homeowner["id"]:
        raise ApiError(ERR_HOMEOWNER_MISMATCH, "The new property is not owned by this household.")
    if departing_property.get("homeowner_id") != homeowner["id"]:
        raise ApiError(ERR_HOMEOWNER_MISMATCH, "The departing property is not owned by this household.")
    if new_property.get("kind") != "NEW":
        raise ApiError(ERR_PROPERTY_KIND_MISMATCH, "The new property must be of kind NEW.")
    if departing_property.get("kind") != "DEPARTING":
        raise ApiError(ERR_PROPERTY_KIND_MISMATCH, "The departing property must be of kind DEPARTING.")

    program = {
        "homeowner_id": homeowner["id"],
        "qualification_id": qualification["id"],
        "new_property_id": new_property["id"],
        "departing_property_id": departing_property["id"],
        "projected_carry_months": projected_carry_months,
        "program_fee_basis_points": program_fee_basis_points,
        "advance_status": "PENDING",
        "occupancy_status": "VACANT",
        "outstanding_carrying_cost_cents": 0,
        "total_program_charge_cents": 0,
        "active_referral_count": 0,
    }
    create("bridge_programs", program)
    return program


def fund_program(program_id, payload):
    """Funding: originate the loan and disclose the program charges."""
    program = get_bridge_program(program_id)
    data = body_of(payload)

    expected_version = get_int(data, "expected_bridge_program_version", required=True)
    if expected_version != program["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_bridge_program_version %s does not match the program's version %s."
            % (expected_version, program["version"]),
        )

    if program.get("advance_status") != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING program may be funded.")

    qualification = get_qualification(program["qualification_id"])
    if qualification.get("status") != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "The linked qualification must be APPROVED.")

    new_property = get_property(program["new_property_id"])
    if new_property.get("kind") != "NEW":
        raise ApiError(ERR_PROPERTY_KIND_MISMATCH, "The linked property must be of kind NEW.")

    if db.first_by_field("interim_loans", "bridge_program_id", program["id"]) is not None:
        raise ApiError(ERR_INVALID_STATE, "An interim loan already exists for this program.")

    principal = int(qualification.get("capacity_cents") or 0)
    _assert_ltv_ok(principal, new_property)
    _assert_appraisal_current(new_property)

    rate_bps = get_int(data, "interest_rate_bps", required=False, default=0)

    now_text = format_iso(current_time())
    loan = loan_service.originate(program["id"], principal, rate_bps)
    loan_service.mark_originated_at(loan, now_text)
    touch(loan)

    _create_disclosure_advances(program, principal)

    program["advance_status"] = "FUNDING"
    disclosure_service.recompute_program_charge(program)
    touch(program)

    departing_property = get_property(program["departing_property_id"])
    departing_property["listing_status"] = "UNLISTED"
    touch(departing_property)

    homeowner = get_homeowner(program["homeowner_id"])
    homeowner["program_status"] = "ENROLLED"
    touch(homeowner)

    return program


def _create_disclosure_advances(program, principal):
    """The disclosure-backed advance entries for the program's own charges."""
    figures = disclosure_service.compute_disclosure(program, principal)
    for purpose, amount in (
        ("FEE", figures["origination_cents"]),
        ("DISCLOSURE", figures["coordination_cents"] + figures["escalator_cents"]),
    ):
        if amount <= 0:
            continue
        advance = {
            "bridge_program_id": program["id"],
            "interim_loan_id": db.first_by_field("interim_loans", "bridge_program_id", program["id"])["id"],
            "purpose": purpose,
            "amount_cents": amount,
            "status": "PENDING",
            "advanced_at": None,
            "_auto_disclosure": True,
        }
        create("bridge_advances", advance)


def _assert_ltv_ok(principal_cents, new_property):
    """The loan-to-value ceiling: principal * 10000 // appraisal <= 7500."""
    appraised = int(new_property.get("appraised_value_cents") or 0)
    if appraised <= 0:
        raise ApiError(ERR_LTV_EXCEEDS_LIMIT, "The new property has no appraised value.")
    ltv_bps = (int(principal_cents) * BPS_DENOMINATOR) // appraised
    if ltv_bps > LTV_MAX_BPS:
        raise ApiError(
            ERR_LTV_EXCEEDS_LIMIT,
            "The interim loan principal sits above the %d bps loan-to-value ceiling." % LTV_MAX_BPS,
        )


def _assert_appraisal_current(property_record):
    """Appraisal staleness, enforced at funding and at offer issuance."""
    appraisal_date = parse_iso(property_record.get("appraisal_date"))
    if appraisal_date is None:
        return
    if current_time() > add_days(appraisal_date, APPRAISAL_VALIDITY_DAYS):
        raise ApiError(ERR_APPRAISAL_STALE, "The property appraisal is stale.")


def occupy_new(program_id):
    """The household records its move into the new home (PRD 3.10)."""
    program = get_bridge_program(program_id)

    if program.get("occupancy_status") != "VACANT":
        raise ApiError(ERR_INVALID_STATE, "The program's occupancy axis is not VACANT.")
    if program.get("advance_status") not in ("FUNDING", "FUNDED"):
        raise ApiError(ERR_INVALID_STATE, "The money axis must have reached FUNDING or FUNDED.")

    new_property = get_property(program["new_property_id"])
    if new_property.get("program_inventory_flag") is True:
        raise ApiError(
            ERR_INVALID_STATE,
            "A home the program acquired through its guarantee is not a home the household is moving into.",
        )

    program["occupancy_status"] = "OCCUPYING_NEW"
    touch(program)
    return program


def settle_program_for_final_repayment(program):
    """Settle a program on the final repayment (PRD 3.10).

    Permitted only when the money axis is ``FUNDED``, the loan is ``REPAYING``,
    ``outstanding_carrying_cost_cents`` is exactly zero, and every repair advance
    belonging to the program has reached ``SETTLED``.
    """
    if program.get("advance_status") != "FUNDED":
        return False
    if int(program.get("outstanding_carrying_cost_cents") or 0) != 0:
        return False
    for repair in db.all("repair_advances"):
        if repair.get("bridge_program_id") == program["id"] and repair.get("status") != "SETTLED":
            return False

    program["advance_status"] = "SETTLED"
    from services import burden as burden_service

    burden_service.recompute_program_burden(program)
    touch(program)

    homeowner = get_homeowner(program["homeowner_id"])
    homeowner["program_status"] = "SETTLED"
    _seal_household_if_closed(homeowner)
    touch(homeowner)
    return True


def recompute_active_referral_count(program):
    program["active_referral_count"] = len([
        r for r in db.all("referrals")
        if r.get("bridge_program_id") == program["id"] and r.get("status") == "OPEN"
    ])
    return program


def _seal_household_if_closed(homeowner):
    """``sealed_flag`` is set when every program for the household is SETTLED."""
    programs = db.by_field("bridge_programs", "homeowner_id", homeowner["id"])
    if not programs:
        return
    if all(p.get("advance_status") == "SETTLED" for p in programs):
        homeowner["sealed_flag"] = True


def has_non_terminal_program(homeowner_id):
    return any(
        p.get("advance_status") != "SETTLED"
        for p in db.all("bridge_programs")
        if p.get("homeowner_id") == homeowner_id
    )


def parse_create_body(payload):
    """Validate the enrolment payload (PRD 3.3)."""
    data = body_of(payload)
    homeowner_id = get_str(data, "homeowner_id", required=True)
    qualification_id = get_str(data, "qualification_id", required=True)
    new_property_id = get_str(data, "new_property_id", required=True)
    departing_property_id = get_str(data, "departing_property_id", required=True)
    months = get_int(
        data,
        "projected_carry_months",
        required=True,
        minimum=PROJECTED_CARRY_MONTHS_MIN,
        maximum=PROJECTED_CARRY_MONTHS_MAX,
    )
    fee_bps = get_int(
        data,
        "program_fee_basis_points",
        required=False,
        default=DEFAULT_PROGRAM_FEE_BASIS_POINTS,
        minimum=0,
    )
    return homeowner_id, qualification_id, new_property_id, departing_property_id, months, fee_bps