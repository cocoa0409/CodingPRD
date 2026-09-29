"""Enrollment lifecycle: creation, screening, adjudication, exit, accrual."""

from decimal import Decimal

from flask import Blueprint, g

import db
import middleware as mw
import response as resp
import validators as v
from services import calc, common, payments, serialize

bp = Blueprint("enrollments", __name__)

PAYMENT_MODELS = ("PER_ACRE", "PER_CREDIT")
EXIT_REASONS = ("VOLUNTARY", "LAND_SALE", "FORCE_MAJEURE")
TERMINAL = common.TERMINAL_ENROLLMENT_STATUSES

FILTERS = {
    "grower_id": ("grower_id", "str"),
    "field_id": ("field_id", "str"),
    "practice_standard_id": ("practice_standard_id", "str"),
    "status": ("status", "str"),
    "permanence_status": ("permanence_status", "str"),
    "payment_model": ("payment_model", "str"),
    "start_crop_year": ("start_crop_year", "int"),
}

READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER, mw.ROLE_REGISTRY_OFFICER)


# ---------------------------------------------------------------------------
# shared rungs
# ---------------------------------------------------------------------------
def check_methodology(standard, start_crop_year):
    """Rung 12 -- methodology availability."""
    if standard["status"] != "ACTIVE":
        common.fail("ERR_PRACTICE_STANDARD_RETIRED", "The practice standard is RETIRED.")
    if int(standard["effective_from"][0:4]) > int(start_crop_year):
        common.fail(
            "ERR_PRACTICE_STANDARD_RETIRED",
            "The standard's effective_from year is later than the enrollment's start crop year.",
        )


def run_screening(enrollment, field, standard):
    """Rung 14 -- additionality computation and the two cascading gates."""
    rows = calc.screening_input_set(
        db.sorted_rows(db.practice_history),
        field["id"],
        enrollment["practice_code"],
        enrollment["start_crop_year"],
        standard["additionality_lookback_years"],
    )
    prior_adoption_pct, score, documented_years = calc.additionality(
        rows,
        field["mapped_acres"],
        standard["additionality_lookback_years"],
        standard["telemetry_required"],
    )
    if documented_years < standard["min_documented_years"]:
        common.fail("ERR_INSUFFICIENT_PRACTICE_HISTORY")
    if prior_adoption_pct > Decimal(standard["max_prior_adoption_pct"]):
        common.fail("ERR_ADDITIONALITY_FAILED")
    return prior_adoption_pct, score, documented_years


def grower_of(enrollment):
    return db.growers.get(enrollment["grower_id"])


def require_active_grower(enrollment):
    grower = grower_of(enrollment)
    if grower is not None and grower["status"] == "SUSPENDED":
        common.fail("ERR_GROWER_SUSPENDED")
    return grower


# ---------------------------------------------------------------------------
# creation
# ---------------------------------------------------------------------------
@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)
    body = v.json_body()

    # Rung 4 -- ownership precedes request shape whenever the field resolves.
    early = body.get("field_id")
    if isinstance(early, str) and early in db.fields:
        mw.require_grower_owner(db.fields[early]["grower_id"])

    field_id = v.v_str(body, "field_id")
    practice_standard_id = v.v_str(body, "practice_standard_id")
    commitment_years = v.v_int(body, "commitment_years")
    start_crop_year = v.v_crop_year(body, "start_crop_year")
    enrolled_acres = v.v_dec(body, "enrolled_acres", 2, minimum=0)
    payment_model = v.v_enum(body, "payment_model", PAYMENT_MODELS)

    per_acre_rate_cents = None
    per_credit_share_pct = None
    if payment_model == "PER_ACRE":
        if v.supplied(body, "per_credit_share_pct"):
            v.bad("A PER_ACRE enrollment must omit 'per_credit_share_pct'.")
        per_acre_rate_cents = v.v_dec(
            body, "per_acre_rate_cents", 2, minimum=0, exclusive_min=True
        )
    else:
        if v.supplied(body, "per_acre_rate_cents"):
            v.bad("A PER_CREDIT enrollment must omit 'per_acre_rate_cents'.")
        per_credit_share_pct = v.v_dec(
            body, "per_credit_share_pct", 2, minimum=0, maximum=100
        )

    current = db.current_crop_year()
    if start_crop_year not in (current, current + 1):
        v.bad(
            "Field 'start_crop_year' must equal the current crop year or the current crop year "
            "plus one."
        )

    field = common.get_field(field_id)
    standard = common.get_practice_standard(practice_standard_id)
    mw.require_grower_owner(field["grower_id"])

    grower = db.growers.get(field["grower_id"])
    if grower is not None and grower["status"] == "SUSPENDED":
        common.fail("ERR_GROWER_SUSPENDED")

    if field["status"] != "MAPPED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a MAPPED field may be enrolled."
        )

    check_methodology(standard, start_crop_year)

    if (
        commitment_years < standard["min_adoption_years"]
        or commitment_years > 12
        or enrolled_acres <= 0
        or enrolled_acres > Decimal(field["mapped_acres"])
    ):
        common.fail("ERR_COMMITMENT_TERMS_INVALID")

    practice_code = standard["practice_code"]
    new_low = start_crop_year
    new_high = start_crop_year + commitment_years  # exclusive

    for other in db.sorted_rows(db.enrollments):
        if other["field_id"] != field["id"] or other["status"] in TERMINAL:
            continue
        other_low = other["start_crop_year"]
        other_high = other["start_crop_year"] + other["commitment_years"]
        if new_low < other_high and other_low < new_high:
            common.fail("ERR_COMMITMENT_PERIOD_OVERLAP")

    for other in db.sorted_rows(db.enrollments):
        if (
            other["field_id"] != field["id"]
            or other["practice_code"] != practice_code
            or other["status"] != "TERMINATED"
            or other["terminated_effective_year"] is None
        ):
            continue
        if start_crop_year < other["terminated_effective_year"] + calc.PRACTICE_COOLDOWN_YEARS:
            common.fail("ERR_PRACTICE_COOLDOWN_ACTIVE")

    for other in db.sorted_rows(db.enrollments):
        if (
            other["field_id"] == field["id"]
            and other["practice_code"] == practice_code
            and other["status"] not in TERMINAL
        ):
            common.fail("ERR_DUPLICATE_ENROLLMENT")

    row = db.common_fields()
    row.update({
        "grower_id": field["grower_id"],
        "field_id": field["id"],
        "practice_standard_id": standard["id"],
        "practice_code": practice_code,
        "pinned_standard_version": standard["standard_version"],
        "commitment_years": commitment_years,
        "start_crop_year": start_crop_year,
        "enrolled_acres": enrolled_acres,
        "payment_model": payment_model,
        "per_acre_rate_cents": per_acre_rate_cents,
        "per_credit_share_pct": per_credit_share_pct,
        "prior_adoption_pct": None,
        "additionality_score": None,
        "documented_years": None,
        "status": "DRAFT",
        "permanence_status": "NOT_STARTED",
        "screening_decision_admin_id": None,
        "baseline_approval_admin_id": None,
        "rejection_reason": None,
        "missing_items": None,
        "exit_reason": None,
        "requested_exit_year": None,
        "exit_fee_cents": None,
        "terminated_effective_year": None,
        "accrued_payment_cents": 0,
        "credits_issued_total": 0,
    })
    db.enrollments[row["id"]] = row
    return resp.object_response(serialize.enrollment(row), 201)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    mw.authorize(*READ_ROLES)
    rows = common.apply_filters(db.enrollments.values(), FILTERS)
    return resp.paginate(rows, serialize.enrollment)


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def read_enrollment(enrollment_id):
    mw.authorize(*READ_ROLES)
    row = common.get_enrollment(enrollment_id)
    mw.require_grower_owner(row["grower_id"])
    return resp.object_response(serialize.enrollment(row))


# ---------------------------------------------------------------------------
# screening cycle
# ---------------------------------------------------------------------------
def _screen_transition(enrollment_id, required_status):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)
    enrollment = common.get_enrollment(enrollment_id)
    mw.require_grower_owner(enrollment["grower_id"])
    v.json_body()
    require_active_grower(enrollment)
    if enrollment["status"] != required_status:
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "The enrollment must be in %s for this action." % required_status,
        )
    field = db.fields[enrollment["field_id"]]
    standard = db.practice_standards[enrollment["practice_standard_id"]]
    check_methodology(standard, enrollment["start_crop_year"])
    prior_adoption_pct, score, documented_years = run_screening(enrollment, field, standard)
    enrollment["prior_adoption_pct"] = prior_adoption_pct
    enrollment["additionality_score"] = score
    enrollment["documented_years"] = documented_years
    enrollment["status"] = "SCREENING"
    db.touch(enrollment)
    return enrollment


@bp.route("/enrollments/<enrollment_id>/submit", methods=["POST"])
def submit_enrollment(enrollment_id):
    enrollment = _screen_transition(enrollment_id, "DRAFT")
    return resp.object_response(serialize.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/resubmit", methods=["POST"])
def resubmit_enrollment(enrollment_id):
    enrollment = _screen_transition(enrollment_id, "INFO_REQUESTED")
    enrollment["missing_items"] = None
    return resp.object_response(serialize.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/request-info", methods=["POST"])
def request_info(enrollment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    enrollment = common.get_enrollment(enrollment_id)
    body = v.json_body()
    missing_items = v.v_str_list(body, "missing_items")
    if enrollment["status"] != "SCREENING":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an enrollment in SCREENING may be returned for more information.",
        )
    enrollment["missing_items"] = missing_items
    enrollment["status"] = "INFO_REQUESTED"
    db.touch(enrollment)
    return resp.object_response(serialize.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/screen", methods=["POST"])
def screen_enrollment(enrollment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    enrollment = common.get_enrollment(enrollment_id)
    body = v.json_body()
    decision = v.v_enum(body, "decision", ("ACCEPT", "REJECT"))
    rejection_reason = None
    if decision == "REJECT":
        rejection_reason = v.v_str(body, "rejection_reason")
    if enrollment["status"] != "SCREENING":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only an enrollment in SCREENING may be adjudicated."
        )
    enrollment["screening_decision_admin_id"] = g.user_id
    if decision == "ACCEPT":
        enrollment["status"] = "ACCEPTED"
    else:
        enrollment["rejection_reason"] = rejection_reason
        enrollment["status"] = "REJECTED"
    db.touch(enrollment)
    return resp.object_response(serialize.enrollment(enrollment))


# ---------------------------------------------------------------------------
# contract exit
# ---------------------------------------------------------------------------
@bp.route("/enrollments/<enrollment_id>/request-exit", methods=["POST"])
def request_exit(enrollment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)
    enrollment = common.get_enrollment(enrollment_id)
    mw.require_grower_owner(enrollment["grower_id"])
    body = v.json_body()
    exit_reason = v.v_enum(body, "exit_reason", EXIT_REASONS)
    requested_exit_year = v.v_crop_year(body, "requested_exit_year")
    require_active_grower(enrollment)
    if enrollment["status"] != "ACTIVE":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE enrollment may request an exit."
        )
    current = db.current_crop_year()
    if requested_exit_year < current + 1:
        common.fail("ERR_EXIT_WINDOW_NOT_OPEN")
    if current - enrollment["start_crop_year"] < calc.EXIT_NOTICE_MIN_YEARS:
        common.fail("ERR_EXIT_WINDOW_NOT_OPEN")
    enrollment["exit_reason"] = exit_reason
    enrollment["requested_exit_year"] = requested_exit_year
    enrollment["status"] = "EXIT_REQUESTED"
    db.touch(enrollment)
    return resp.object_response(serialize.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/decide-exit", methods=["POST"])
def decide_exit(enrollment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    enrollment = common.get_enrollment(enrollment_id)
    body = v.json_body()
    decision = v.v_enum(body, "decision", ("APPROVE", "DENY"))
    rejection_reason = None
    if decision == "DENY":
        rejection_reason = v.v_str(body, "rejection_reason")
    if enrollment["status"] != "EXIT_REQUESTED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an enrollment in EXIT_REQUESTED may be adjudicated.",
        )

    if decision == "DENY":
        enrollment["status"] = "ACTIVE"
        enrollment["rejection_reason"] = rejection_reason
        enrollment["exit_reason"] = None
        enrollment["requested_exit_year"] = None
        db.touch(enrollment)
        return resp.object_response(serialize.enrollment(enrollment))

    current = db.current_crop_year()
    elapsed = current - enrollment["start_crop_year"]
    fully_served = elapsed >= enrollment["commitment_years"]
    settled = common.settled_cents(enrollment["id"])
    fee = calc.exit_fee_cents(enrollment, settled, current)

    if fully_served:
        enrollment["status"] = "EXITED"
        enrollment["exit_fee_cents"] = 0
        db.touch(enrollment)
        for payment in common.enrollment_payments(enrollment["id"]):
            if payment["status"] != "ACCRUED":
                continue
            payment["status"] = "PAID"
            payment["paid_at"] = db.now_raw()
            db.touch(payment)
            grower = grower_of(enrollment)
            if grower is not None:
                grower["net_paid_cents"] = grower["net_paid_cents"] + payment["net_amount_cents"]
                db.touch(grower)
    else:
        enrollment["status"] = "TERMINATED"
        enrollment["exit_fee_cents"] = fee
        enrollment["permanence_status"] = "BREACHED"
        enrollment["terminated_effective_year"] = current
        db.touch(enrollment)
        for payment in common.enrollment_payments(enrollment["id"]):
            if payment["status"] != "ACCRUED":
                continue
            payment["status"] = "VOID"
            db.touch(payment)
            enrollment["accrued_payment_cents"] = (
                enrollment["accrued_payment_cents"] - payment["net_amount_cents"]
            )
            db.touch(enrollment)

    common.release_field(enrollment)
    return resp.object_response(serialize.enrollment(enrollment))


# ---------------------------------------------------------------------------
# per-acre payment accrual
# ---------------------------------------------------------------------------
@bp.route("/enrollments/<enrollment_id>/accrue-payment", methods=["POST"])
def accrue_payment(enrollment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    enrollment = common.get_enrollment(enrollment_id)
    body = v.json_body()
    crop_year = v.v_crop_year(body, "crop_year")
    if enrollment["payment_model"] != "PER_ACRE":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a PER_ACRE enrollment accrues payments through this endpoint.",
        )
    if payments.duplicate_accrual_exists(enrollment["id"], crop_year, "PER_ACRE"):
        common.fail("ERR_DUPLICATE_PAYMENT")
    row = payments.accrue_per_acre(enrollment, crop_year)
    return resp.object_response(serialize.grower_payment(row), 201)
