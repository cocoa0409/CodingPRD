"""Incentive program design, the approval gate, repricing and accrual."""

from flask import Blueprint, request

import clock
import db
import errors
import response
import serializers
import util
import validate
from middleware import ROLE_CLAIMS_AUDITOR as AUDITOR
from middleware import ROLE_DEALER as DEALER
from middleware import ROLE_FIELD_SALES_MANAGER as FIELD
from middleware import ROLE_INCENTIVE_CONTROLLER as CONTROLLER
from middleware import ROLE_PROGRAM_DESIGNER as DESIGNER
from middleware import caller_id, require_roles, touch
from routes import helpers
from services import calc, ledger

bp = Blueprint("programs", __name__)

INCENTIVE_TYPES = ("CUSTOMER_CASH", "FINANCE_SUBVENTION", "LEASE_SUPPORT", "DEALER_STAIR_STEP")
PROGRAM_STATUSES = ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUPERSEDED", "CLOSED")
DEAL_TYPES = ("CASH", "FINANCE", "LEASE")
TIER_BONUS_MODES = ("MARGINAL", "FULL_VOLUME")
ACCRUAL_METHODS = ("UNIT_BASED", "TAKE_RATE_BASED")
STACK_MODES = ("FORBIDDEN", "CAPPED_TOTAL", "ALLOWED")
REPRICING_MODES = ("PROSPECTIVE", "RETROACTIVE_TO_MONTH_START")
ENTRY_TYPES = ("ACCRUAL", "REVERSAL")


# --------------------------------------------------------------------------
# Program overlap and footprint conflict machinery (PRD 3.1, 3.2)
# --------------------------------------------------------------------------

def _closed_intervals_intersect(a_from, a_to, b_from, b_to):
    return a_from <= b_to and b_from <= a_to


def _trim_scope_overlaps(trim_a, trim_b):
    return trim_a is None or trim_b is None or trim_a == trim_b


def _footprints_intersect(program_a, program_b):
    for row_a in calc.program_rules(program_a["id"]):
        for row_b in calc.program_rules(program_b["id"]):
            if row_a["model_code"] != row_b["model_code"]:
                continue
            if not _trim_scope_overlaps(row_a["trim_code"], row_b["trim_code"]):
                continue
            if row_a["region_code"] != row_b["region_code"]:
                continue
            if _closed_intervals_intersect(
                row_a["build_date_from"],
                row_a["build_date_to"],
                row_b["build_date_from"],
                row_b["build_date_to"],
            ):
                return True
    return False


def _windows_intersect(program_a, program_b):
    return (
        program_a["effective_from"] < program_b["effective_to"]
        and program_b["effective_from"] < program_a["effective_to"]
    )


def _run_overlap_check(program, excluded_ids=()):
    """Rung 12: the anti-collision check of PRD 3.2."""
    for other in db.ordered(list(db.programs.values())):
        if other["id"] == program["id"] or other["id"] in excluded_ids:
            continue
        if other["status"] not in ("PENDING_APPROVAL", "ACTIVE"):
            continue
        if other["incentive_type"] != program["incentive_type"]:
            continue
        if not _windows_intersect(program, other):
            continue
        if not _footprints_intersect(program, other):
            continue
        edge = calc.find_edge(program["id"], other["id"])
        if edge is not None and edge["mode"] in ("ALLOWED", "CAPPED_TOTAL"):
            continue
        raise errors.ApiError("ERR_PROGRAM_WINDOW_OVERLAP")


# --------------------------------------------------------------------------
# Programs
# --------------------------------------------------------------------------

@bp.route("/programs", methods=["POST"])
@require_roles(DESIGNER)
def create_program():
    payload = validate.body()
    program_code = validate.get_string(payload, "program_code", min_len=1, max_len=32)
    name = validate.get_string(payload, "name", min_len=1)
    incentive_type = validate.get_enum(payload, "incentive_type", INCENTIVE_TYPES)
    effective_from = validate.get_instant(payload, "effective_from")
    effective_to = validate.get_instant(payload, "effective_to")
    if effective_to <= effective_from:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "effective_to must be strictly later than effective_from."
        )
    per_unit_amount_cents = validate.get_int(payload, "per_unit_amount_cents", minimum=0)
    budget_cents = validate.get_int(payload, "budget_cents", minimum=0)
    stack_group = validate.get_string(payload, "stack_group", min_len=1)
    priority_rank = validate.get_int(payload, "priority_rank", minimum=1)
    apr_buydown_bps = validate.get_int(
        payload, "apr_buydown_bps", required=False, default=0, minimum=0, maximum=2000
    )
    residual_support_bps = validate.get_int(
        payload, "residual_support_bps", required=False, default=0, minimum=0, maximum=1500
    )
    projected_take_rate_bps = validate.get_int(
        payload, "projected_take_rate_bps", required=False, default=0, minimum=0, maximum=10000
    )
    stack_cap_cents = validate.get_int(
        payload, "stack_cap_cents", required=False, default=0, minimum=0
    )
    tier_schedule = validate.get_tier_schedule(payload)
    tier_bonus_mode = validate.get_enum(
        payload, "tier_bonus_mode", TIER_BONUS_MODES, required=False, default="MARGINAL"
    )
    accrual_method = validate.get_enum(
        payload, "accrual_method", ACCRUAL_METHODS, required=False, default="UNIT_BASED"
    )
    supersedes_program_id = validate.get_string(
        payload, "supersedes_program_id", required=False, default=None
    )

    if supersedes_program_id is not None:
        helpers.get_program(supersedes_program_id)

    for existing in db.programs.values():
        if existing["program_code"] == program_code:
            raise errors.ApiError("ERR_DUPLICATE_PROGRAM_CODE")

    program = db.insert(
        db.programs,
        "program",
        {
            "program_code": program_code,
            "name": name,
            "incentive_type": incentive_type,
            "status": "DRAFT",
            "effective_from": effective_from,
            "effective_to": effective_to,
            "per_unit_amount_cents": per_unit_amount_cents,
            "apr_buydown_bps": apr_buydown_bps,
            "residual_support_bps": residual_support_bps,
            "stack_group": stack_group,
            "priority_rank": priority_rank,
            "stack_cap_cents": stack_cap_cents,
            "budget_cents": budget_cents,
            "tier_schedule": tier_schedule,
            "tier_bonus_mode": tier_bonus_mode,
            "accrual_method": accrual_method,
            "projected_take_rate_bps": projected_take_rate_bps,
            "committed_cents": 0,
            "paid_cents": 0,
            "accrued_budget_cents": 0,
            "claimed_units": 0,
            "per_unit_spend_cents": 0,
            "residual_impact_bps": 0,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "supersedes_program_id": supersedes_program_id,
        },
    )
    return response.object_response(serializers.program(program), 201)


@bp.route("/programs", methods=["GET"])
@require_roles(DESIGNER, CONTROLLER, FIELD, AUDITOR)
def list_programs():
    status = validate.query_enum("status", PROGRAM_STATUSES)
    incentive_type = validate.query_enum("incentive_type", INCENTIVE_TYPES)
    supersedes_program_id = validate.query_string("supersedes_program_id")
    rows = db.ordered(list(db.programs.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if incentive_type is not None:
        rows = [r for r in rows if r["incentive_type"] == incentive_type]
    if supersedes_program_id is not None:
        rows = [r for r in rows if r["supersedes_program_id"] == supersedes_program_id]
    return response.listing(rows, request.args, serializers.program)


@bp.route("/programs/<program_id>", methods=["GET"])
@require_roles(DESIGNER, CONTROLLER, FIELD, AUDITOR, DEALER)
def read_program(program_id):
    program = helpers.get_program(program_id)
    return response.object_response(serializers.program(program))


# --------------------------------------------------------------------------
# Eligibility footprint rows
# --------------------------------------------------------------------------

@bp.route("/programs/<program_id>/eligibility-rules", methods=["POST"])
@require_roles(DESIGNER)
def append_eligibility_rule(program_id):
    program = helpers.get_program(program_id)
    payload = validate.body()
    model_code = validate.get_string(payload, "model_code", min_len=1, max_len=16)
    region_code = validate.get_string(payload, "region_code", min_len=1, max_len=8)
    build_date_from = validate.get_instant(payload, "build_date_from")
    build_date_to = validate.get_instant(payload, "build_date_to")
    if build_date_to < build_date_from:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "build_date_to must be at or after build_date_from."
        )
    trim_code = validate.get_string(
        payload, "trim_code", required=False, default=None, min_len=1, max_len=16
    )
    min_msrp_cents = validate.get_int(
        payload, "min_msrp_cents", required=False, default=0, minimum=0
    )
    max_msrp_cents = validate.get_int(
        payload, "max_msrp_cents", required=False, default=None, minimum=0
    )
    allowed_deal_types = validate.get_string_array(
        payload,
        "allowed_deal_types",
        required=False,
        default=list(DEAL_TYPES),
        allowed=DEAL_TYPES,
    )

    if program["status"] != "DRAFT":
        raise errors.ApiError("ERR_PROGRAM_INVALID_STATE")

    for existing in calc.program_rules(program_id):
        if (
            existing["model_code"] == model_code
            and existing["trim_code"] == trim_code
            and existing["region_code"] == region_code
            and _closed_intervals_intersect(
                build_date_from,
                build_date_to,
                existing["build_date_from"],
                existing["build_date_to"],
            )
        ):
            raise errors.ApiError("ERR_ELIGIBILITY_RULE_CONFLICT")

    rule = db.insert(
        db.eligibility_rules,
        "eligibility_rule",
        {
            "program_id": program_id,
            "model_code": model_code,
            "trim_code": trim_code,
            "region_code": region_code,
            "build_date_from": build_date_from,
            "build_date_to": build_date_to,
            "min_msrp_cents": min_msrp_cents,
            "max_msrp_cents": max_msrp_cents,
            "allowed_deal_types": allowed_deal_types,
        },
        versioned=False,
    )
    touch(program)
    return response.object_response(serializers.eligibility_rule(rule), 201)


@bp.route("/programs/<program_id>/eligibility-rules", methods=["GET"])
@require_roles(DESIGNER, CONTROLLER, FIELD, AUDITOR, DEALER)
def list_eligibility_rules(program_id):
    helpers.get_program(program_id)
    rows = calc.program_rules(program_id)
    return response.listing(rows, request.args, serializers.eligibility_rule)


# --------------------------------------------------------------------------
# Stackability edges
# --------------------------------------------------------------------------

@bp.route("/programs/<program_id>/stackability-constraints", methods=["POST"])
@require_roles(DESIGNER)
def declare_stack_edge(program_id):
    program = helpers.get_program(program_id)
    payload = validate.body()
    program_b_id = validate.get_string(payload, "program_b_id", min_len=1)
    mode = validate.get_enum(payload, "mode", STACK_MODES)
    cap_amount_cents = validate.get_int(
        payload, "cap_amount_cents", required=False, default=None, minimum=0
    )
    if mode == "CAPPED_TOTAL" and cap_amount_cents is None:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "cap_amount_cents is required when mode is CAPPED_TOTAL."
        )
    if mode != "CAPPED_TOTAL" and cap_amount_cents is not None:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "cap_amount_cents must be null unless mode is CAPPED_TOTAL."
        )

    helpers.get_program(program_b_id)

    if program_b_id == program_id:
        raise errors.ApiError("ERR_INVALID_STACK_EDGE")
    if calc.find_edge(program_id, program_b_id) is not None:
        raise errors.ApiError("ERR_INVALID_STACK_EDGE")

    edge = db.insert(
        db.stackability_constraints,
        "stackability_constraint",
        {
            "program_a_id": program_id,
            "program_b_id": program_b_id,
            "mode": mode,
            "cap_amount_cents": cap_amount_cents,
        },
        versioned=False,
    )
    touch(program)
    return response.object_response(serializers.stack_edge(edge), 201)


@bp.route("/programs/<program_id>/stackability-constraints", methods=["GET"])
@require_roles(DESIGNER, CONTROLLER, AUDITOR)
def list_stack_edges(program_id):
    helpers.get_program(program_id)
    rows = calc.program_edges(program_id)
    return response.listing(rows, request.args, serializers.stack_edge)


# --------------------------------------------------------------------------
# The approval gate
# --------------------------------------------------------------------------

@bp.route("/programs/<program_id>/submit", methods=["POST"])
@require_roles(DESIGNER)
def submit_program(program_id):
    program = helpers.get_program(program_id)
    validate.body()
    if program["status"] != "DRAFT":
        raise errors.ApiError("ERR_PROGRAM_INVALID_STATE")
    # PRD 3.2: "The submission is admitted only when the program is in DRAFT, when
    # the program has at least one eligibility footprint row, and when effective_to
    # is strictly later than effective_from. Two type-specific gates apply..."
    # These are admission conditions on the program's own state, so an unmet one is
    # rung 10 (transition legality) and reports ERR_PROGRAM_INVALID_STATE; rung 6
    # only screens the request payload, and submit carries none of these values.
    if not calc.program_rules(program_id):
        raise errors.ApiError(
            "ERR_PROGRAM_INVALID_STATE", "A program needs at least one eligibility footprint row."
        )
    if program["effective_to"] <= program["effective_from"]:
        raise errors.ApiError(
            "ERR_PROGRAM_INVALID_STATE",
            "effective_to must be strictly later than effective_from.",
        )
    if program["incentive_type"] == "DEALER_STAIR_STEP" and not program["tier_schedule"]:
        raise errors.ApiError(
            "ERR_PROGRAM_INVALID_STATE", "A stair-step program needs at least one tier."
        )
    if program["incentive_type"] == "LEASE_SUPPORT" and program["residual_support_bps"] <= 0:
        raise errors.ApiError(
            "ERR_PROGRAM_INVALID_STATE",
            "A lease-support program needs residual_support_bps above 0.",
        )

    _run_overlap_check(program)

    program["status"] = "PENDING_APPROVAL"
    program["submitted_by_user_id"] = caller_id()
    touch(program)
    return response.object_response(serializers.program(program))


@bp.route("/programs/<program_id>/revise", methods=["POST"])
@require_roles(DESIGNER)
def revise_program(program_id):
    program = helpers.get_program(program_id)
    payload = validate.body()
    validate.get_string(payload, "revision_note", required=False, default=None)
    if program["status"] != "PENDING_APPROVAL":
        raise errors.ApiError("ERR_PROGRAM_INVALID_STATE")
    program["status"] = "DRAFT"
    program["submitted_by_user_id"] = None
    touch(program)
    return response.object_response(serializers.program(program))


@bp.route("/programs/<program_id>/approve", methods=["POST"])
@require_roles(CONTROLLER)
def approve_program(program_id):
    program = helpers.get_program(program_id)
    validate.body()
    if program["submitted_by_user_id"] is not None and program["submitted_by_user_id"] == caller_id():
        raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES")
    if program["status"] != "PENDING_APPROVAL":
        raise errors.ApiError("ERR_PROGRAM_INVALID_STATE")

    superseded = None
    if program["supersedes_program_id"] is not None:
        superseded = helpers.get_program(program["supersedes_program_id"])
        if superseded["status"] != "ACTIVE":
            raise errors.ApiError("ERR_PROGRAM_NOT_ACTIVE")

    excluded = [superseded["id"]] if superseded is not None else []
    _run_overlap_check(program, excluded_ids=excluded)

    program["status"] = "ACTIVE"
    program["approved_by_user_id"] = caller_id()
    touch(program)

    if superseded is not None:
        ledger.supersede_cascade(superseded)

    return response.object_response(serializers.program(program))


@bp.route("/programs/<program_id>/close", methods=["POST"])
@require_roles(CONTROLLER)
def close_program(program_id):
    program = helpers.get_program(program_id)
    payload = validate.body()
    validate.get_string(payload, "closure_note", required=False, default=None)
    if program["status"] != "ACTIVE":
        raise errors.ApiError("ERR_PROGRAM_INVALID_STATE")
    for claim in calc.program_claims(program_id):
        if claim["payment_status"] == "SCHEDULED":
            raise errors.ApiError("ERR_PROGRAM_INVALID_STATE")

    program["status"] = "CLOSED"
    touch(program)
    ledger.close_cascade(program)
    return response.object_response(serializers.program(program))


# --------------------------------------------------------------------------
# Repricing
# --------------------------------------------------------------------------

@bp.route("/programs/<program_id>/repricings", methods=["POST"])
@require_roles(DESIGNER)
def apply_repricing(program_id):
    program = helpers.get_program(program_id)
    payload = validate.body()
    mode = validate.get_enum(payload, "mode", REPRICING_MODES)
    new_amount = validate.get_int(payload, "new_per_unit_amount_cents", minimum=0)
    expected_version = validate.get_int(payload, "expected_program_version")

    if expected_version != program["version"]:
        raise errors.ApiError("ERR_STALE_PROGRAM_VERSION")

    now = clock.now()
    if program["status"] != "ACTIVE" or not calc.window_contains(program, now):
        raise errors.ApiError("ERR_REPRICING_WINDOW_CLOSED")

    previous_amount = program["per_unit_amount_cents"]
    month_start = util.month_start_of(now)
    program["per_unit_amount_cents"] = new_amount
    touch(program)

    event = db.insert(
        db.repricing_events,
        "repricing_event",
        {
            "program_id": program_id,
            "mode": mode,
            "new_per_unit_amount_cents": new_amount,
            "effective_at": now,
            "previous_per_unit_amount_cents": previous_amount,
            "month_start": month_start,
            "affected_claim_count": 0,
            "net_adjustment_cents": 0,
        },
    )

    if mode == "RETROACTIVE_TO_MONTH_START":
        affected, net = ledger.apply_retroactive_repricing(program, month_start, now)
        event["affected_claim_count"] = affected
        event["net_adjustment_cents"] = net

    return response.object_response(serializers.repricing_event(event), 201)


@bp.route("/programs/<program_id>/repricings", methods=["GET"])
@require_roles(DESIGNER, CONTROLLER, AUDITOR)
def list_repricings(program_id):
    helpers.get_program(program_id)
    rows = calc.program_repricings(program_id)
    return response.listing(rows, request.args, serializers.repricing_event)


# --------------------------------------------------------------------------
# Monthly accrual and the spend summary
# --------------------------------------------------------------------------

@bp.route("/programs/<program_id>/accruals", methods=["POST"])
@require_roles(CONTROLLER)
def run_accrual(program_id):
    program = helpers.get_program(program_id)
    payload = validate.body()
    period_month = validate.get_month(payload, "period_month")

    for row in calc.program_accruals(program_id):
        if row["entry_type"] == "ACCRUAL" and row["period_month"] == period_month:
            raise errors.ApiError("ERR_ACCRUAL_PERIOD_ALREADY_RUN")

    unit_basis, accrued_cents = calc.accrual_lines(program, period_month)
    row = db.insert(
        db.budget_accruals,
        "budget_accrual",
        {
            "program_id": program_id,
            "period_month": period_month,
            "accrual_method": program["accrual_method"],
            "entry_type": "ACCRUAL",
            "unit_basis": unit_basis,
            "accrued_cents": accrued_cents,
            "reversal_cents": 0,
            "source_reference": None,
        },
    )
    ledger.recompute_program(program)
    return response.object_response(serializers.budget_accrual(row), 201)


@bp.route("/programs/<program_id>/accruals", methods=["GET"])
@require_roles(CONTROLLER, DESIGNER, AUDITOR)
def list_accruals(program_id):
    helpers.get_program(program_id)
    entry_type = validate.query_enum("entry_type", ENTRY_TYPES)
    period_month = validate.query_string("period_month")
    rows = calc.program_accruals(program_id)
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    if period_month is not None:
        rows = [r for r in rows if r["period_month"] == period_month]
    return response.listing(rows, request.args, serializers.budget_accrual)


@bp.route("/programs/<program_id>/spend-summary", methods=["GET"])
@require_roles(DESIGNER, CONTROLLER, AUDITOR)
def spend_summary(program_id):
    program = helpers.get_program(program_id)
    data = {
        "program_id": program["id"],
        "claimed_units": program["claimed_units"],
        "committed_cents": program["committed_cents"],
        "paid_cents": program["paid_cents"],
        "accrued_budget_cents": program["accrued_budget_cents"],
        "per_unit_spend_cents": program["per_unit_spend_cents"],
        "residual_impact_bps": program["residual_impact_bps"],
        "budget_remaining_cents": program["budget_cents"] - program["committed_cents"],
    }
    return response.object_response(data)
