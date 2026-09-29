"""Incentive programs, the stacking waterfall and rebate-claim adjudication."""

from flask import Blueprint, request

import cascades
import rules
import shape
import store
from calc import effective_hold, rebate_award, reserved_basis
from common import EXPORT_MODES, PROGRAM_TYPES, kw
from envelope import collection, created, ok
from errors import ApiError
from security import guard, path_ref, ref

bp = Blueprint("incentives", __name__)

PROGRAM_READ_ROLES = (
    "RebateAdministrator",
    "CertifiedInstaller",
    "Homeowner",
    "UtilityInterconnectionReviewer",
)

CLAIM_READ_ROLES = ("RebateAdministrator", "CertifiedInstaller", "Homeowner")

CLAIM_LIVE_EXCLUDED = ("VOID", "DENIED", "CLAWED_BACK")


def _claim_state_error(claim, action):
    return ApiError(
        "ERR_CLAIM_STATE_INVALID",
        "A claim in %s cannot be %s." % (claim["status"], action),
    )


def _live_application(system):
    """The system's live interconnection application, or None."""
    found = None
    for application in store.rows("applications"):
        if application["battery_system_id"] != system["id"]:
            continue
        if application["status"] == "DENIED":
            continue
        found = application
    return found


# --------------------------------------------------------------------------- #
# Incentive programs
# --------------------------------------------------------------------------- #

@bp.route("/incentive-programs", methods=["POST"])
@guard("RebateAdministrator")
def create_program(actor):
    payload = shape.body()
    name = payload.str_("name")
    program_type = payload.enum("program_type", PROGRAM_TYPES)
    total_budget_cents = payload.integer("total_budget_cents", exclusive_min=True)
    tier1_limit_kwh = payload.number("tier1_limit_kwh", exclusive_min=True)
    tier1_rate = payload.integer("tier1_rate_cents_per_kwh")
    tier2_rate = payload.integer("tier2_rate_cents_per_kwh")
    per_project_cap_cents = payload.integer("per_project_cap_cents", exclusive_min=True)
    stack_priority = payload.integer("stack_priority", minimum=1)
    max_stack_pct_of_cost_bp = payload.integer(
        "max_stack_pct_of_cost_bp", minimum=1, maximum=10000
    )
    requires_export_commitment = payload.boolean(
        "requires_export_commitment", required=False, default=False
    )
    min_capacity_commitment_kw = payload.number("min_capacity_commitment_kw")

    record = store.insert(
        "programs",
        {
            "name": name,
            "program_type": program_type,
            "total_budget_cents": total_budget_cents,
            "remaining_budget_cents": total_budget_cents,
            "reserved_budget_cents": 0,
            "paid_budget_cents": 0,
            "tier1_limit_kwh": kw(tier1_limit_kwh),
            "tier1_rate_cents_per_kwh": tier1_rate,
            "tier2_rate_cents_per_kwh": tier2_rate,
            "per_project_cap_cents": per_project_cap_cents,
            "stack_priority": stack_priority,
            "max_stack_pct_of_cost_bp": max_stack_pct_of_cost_bp,
            "requires_export_commitment": requires_export_commitment,
            "min_capacity_commitment_kw": kw(min_capacity_commitment_kw),
        },
    )
    return created(store.view(record))


@bp.route("/incentive-programs/<program_id>", methods=["GET"])
@guard(*PROGRAM_READ_ROLES)
def read_program(actor, program_id):
    record = path_ref(actor, "program", program_id)
    return ok(store.view(record))


@bp.route("/incentive-programs", methods=["GET"])
@guard(*PROGRAM_READ_ROLES)
def list_programs(actor):
    records = store.where("programs", program_type=request.args.get("program_type"))
    return collection(records)


# --------------------------------------------------------------------------- #
# Reserving a claim
# --------------------------------------------------------------------------- #

@bp.route("/rebate-claims", methods=["POST"])
@guard("CertifiedInstaller")
def create_claim(actor):
    payload = shape.body()
    system_id = payload.fk("battery_system_id")
    system = ref("battery_system", system_id)
    program_id = payload.fk("program_id")
    program = ref("program", program_id)

    capacity_commitment_kw = payload.number("capacity_commitment_kw", exclusive_min=True)
    export_commitment = payload.enum("export_commitment", EXPORT_MODES)
    expected_version = payload.integer("expected_battery_system_version", minimum=0)

    # Step 6 -- the build dimension is a state precondition of the reservation.
    if system["build_status"] not in ("DESIGN_LOCKED", "INSTALLED"):
        raise ApiError(
            "ERR_SYSTEM_BUILD_STATE_INVALID",
            "A bank in %s cannot reserve an incentive." % system["build_status"],
        )
    # Step 7 -- optimistic concurrency on the aggregate parent.
    if expected_version != system["version"]:
        raise ApiError(
            "ERR_STALE_SYSTEM_VERSION",
            "The battery system has version %d." % system["version"],
        )
    # Step 11 -- cross-entity gating on the grid dimension.
    if system["grid_status"] not in ("APPROVED_TO_INSTALL", "PTO_GRANTED"):
        raise ApiError(
            "ERR_SYSTEM_GRID_STATE_INVALID",
            "The utility has not yet approved this bank for installation.",
        )
    # Step 13 -- one live claim per program.
    for existing in store.rows("claims"):
        if (
            existing["battery_system_id"] == system["id"]
            and existing["program_id"] == program["id"]
            and existing["status"] not in CLAIM_LIVE_EXCLUDED
        ):
            raise ApiError(
                "ERR_DUPLICATE_PROGRAM_CLAIM",
                "The bank already holds a live claim on this program.",
            )

    # Step 14 -- the three commitment checks, in order.
    if program["requires_export_commitment"]:
        application = _live_application(system)
        if export_commitment == "NON_EXPORT" or application is None or (
            application["export_mode"] == "NON_EXPORT"
        ):
            raise ApiError(
                "ERR_EXPORT_COMMITMENT_REQUIRED",
                "This program requires an exporting posture.",
            )
    if capacity_commitment_kw < program["min_capacity_commitment_kw"] or (
        capacity_commitment_kw > system["continuous_kw"]
    ):
        raise ApiError(
            "ERR_CAPACITY_COMMITMENT_INVALID",
            "The committed capacity is outside the permitted band.",
        )

    basis = reserved_basis(system)
    amount, ceiling, headroom = rebate_award(
        system, program, export_commitment, basis
    )
    if headroom <= 0:
        raise ApiError(
            "ERR_STACK_CAP_EXCEEDED",
            "The stacking ceiling leaves no headroom for another incentive.",
        )
    # Step 15 -- the budget objection is reported last of all.
    if int(program["remaining_budget_cents"]) < amount:
        raise ApiError(
            "ERR_PROGRAM_BUDGET_EXHAUSTED",
            "The program pool cannot cover this reservation.",
        )

    record = store.insert(
        "claims",
        {
            "battery_system_id": system_id,
            "program_id": program_id,
            "capacity_commitment_kw": kw(capacity_commitment_kw),
            "export_commitment": export_commitment,
            "basis_kwh_reserved": kw(basis),
            "basis_kwh_final": None,
            "reserved_amount_cents": amount,
            "final_amount_cents": None,
            "stack_ceiling_cents": ceiling,
            "status": "RESERVED",
            "approved_by_user_id": None,
            "paid_by_user_id": None,
            "paid_at": None,
            "clawback_reason": None,
        },
    )
    rules.reserve_funds(program, amount)
    store.touch(system)
    return created(store.view(record))


@bp.route("/rebate-claims/<claim_id>", methods=["GET"])
@guard(*CLAIM_READ_ROLES)
def read_claim(actor, claim_id):
    record = path_ref(actor, "claim", claim_id)
    return ok(store.view(record))


@bp.route("/rebate-claims", methods=["GET"])
@guard(*CLAIM_READ_ROLES)
def list_claims(actor):
    records = store.where(
        "claims",
        battery_system_id=request.args.get("battery_system_id"),
        program_id=request.args.get("program_id"),
        status=request.args.get("status"),
    )
    return collection(records)


# --------------------------------------------------------------------------- #
# Adjudication, payment and the compensating actions
# --------------------------------------------------------------------------- #

@bp.route("/rebate-claims/<claim_id>/submit", methods=["POST"])
@guard("CertifiedInstaller")
def submit_claim(actor, claim_id):
    claim = path_ref(actor, "claim", claim_id)
    if claim["status"] != "RESERVED":
        raise _claim_state_error(claim, "submitted")

    system = store.get("battery_systems", claim["battery_system_id"])
    if system is None or system["build_status"] != "COMMISSIONED":
        raise ApiError(
            "ERR_SYSTEM_BUILD_STATE_INVALID",
            "The bank must be commissioned before its claim is adjudicated.",
        )
    if system["grid_status"] != "PTO_GRANTED":
        raise ApiError(
            "ERR_SYSTEM_GRID_STATE_INVALID",
            "The bank must hold permission to operate before its claim is adjudicated.",
        )
    if system["warranty_status"] != "ACTIVE":
        raise ApiError(
            "ERR_WARRANTY_NOT_ACTIVE",
            "The bank's manufacturer warranty is not active.",
        )

    claim["status"] = "SUBMITTED"
    store.touch(claim)
    return ok(store.view(claim))


@bp.route("/rebate-claims/<claim_id>/decision", methods=["POST"])
@guard("RebateAdministrator")
def decide_claim(actor, claim_id):
    claim = path_ref(actor, "claim", claim_id)
    payload = shape.body()
    decision = payload.enum("decision", ("APPROVE", "DENY"))

    if claim["status"] != "SUBMITTED":
        raise _claim_state_error(claim, "decided")
    if decision == "APPROVE" and claim["final_amount_cents"] is None:
        raise ApiError(
            "ERR_CLAIM_STATE_INVALID",
            "The final award has not been computed for this claim.",
        )

    program = store.get("programs", claim["program_id"])
    if decision == "APPROVE":
        claim["status"] = "APPROVED"
        claim["approved_by_user_id"] = actor.user_id
        store.touch(claim)
    else:
        hold = effective_hold(claim)
        claim["status"] = "DENIED"
        store.touch(claim)
        if program is not None:
            rules.release_hold(program, hold)
    return ok(store.view(claim))


@bp.route("/rebate-claims/<claim_id>/pay", methods=["POST"])
@guard("RebateAdministrator")
def pay_claim(actor, claim_id):
    claim = path_ref(actor, "claim", claim_id)
    if claim["status"] != "APPROVED":
        raise _claim_state_error(claim, "paid")
    if claim["approved_by_user_id"] is not None and (
        actor.user_id == claim["approved_by_user_id"]
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approving administrator may not release the payment.",
        )

    amount = int(claim["final_amount_cents"])
    claim["status"] = "PAID"
    claim["paid_by_user_id"] = actor.user_id
    claim["paid_at"] = store.now()
    store.touch(claim)

    program = store.get("programs", claim["program_id"])
    if program is not None:
        rules.disburse(program, amount)
    return ok(store.view(claim))


@bp.route("/rebate-claims/<claim_id>/clawback", methods=["POST"])
@guard("RebateAdministrator")
def clawback_claim(actor, claim_id):
    claim = path_ref(actor, "claim", claim_id)
    payload = shape.body()
    reason = payload.str_("clawback_reason")

    if claim["status"] != "PAID":
        raise _claim_state_error(claim, "clawed back")

    amount = int(claim["final_amount_cents"])
    claim["status"] = "CLAWED_BACK"
    claim["clawback_reason"] = reason
    store.touch(claim)

    program = store.get("programs", claim["program_id"])
    if program is not None:
        rules.reverse_payment(program, amount)

    system = store.get("battery_systems", claim["battery_system_id"])
    cascades.cascade_d(claim, system)
    return ok(store.view(claim))


@bp.route("/rebate-claims/<claim_id>/void", methods=["POST"])
@guard("CertifiedInstaller")
def void_claim(actor, claim_id):
    claim = path_ref(actor, "claim", claim_id)
    payload = shape.body()
    reason = payload.str_("reason")

    if claim["status"] != "RESERVED":
        raise _claim_state_error(claim, "voided")

    hold = effective_hold(claim)
    claim["status"] = "VOID"
    claim["clawback_reason"] = reason
    store.touch(claim)

    program = store.get("programs", claim["program_id"])
    if program is not None:
        rules.release_hold(program, hold)
    return ok(store.view(claim))
