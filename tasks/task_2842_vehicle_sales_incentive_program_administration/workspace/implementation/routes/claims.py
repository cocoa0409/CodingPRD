"""Claim submission, adjudication and chargebacks."""

from flask import Blueprint, request

import clock
import db
import errors
import response
import serializers
import validate
from middleware import ROLE_CLAIMS_AUDITOR as AUDITOR
from middleware import ROLE_DEALER as DEALER
from middleware import ROLE_INCENTIVE_CONTROLLER as CONTROLLER
from middleware import ROLE_PROGRAM_DESIGNER as DESIGNER
from middleware import caller_id, require_roles, touch
from routes import helpers
from services import calc, ledger

bp = Blueprint("claims", __name__)

VALIDATION_STATUSES = ("SUBMITTED", "VALIDATED", "REJECTED")
PAYMENT_STATUSES = ("UNPAID", "SCHEDULED", "PAID", "CHARGED_BACK")
DECISIONS = ("APPROVE", "REJECT")


@bp.route("/claims", methods=["POST"])
@require_roles(DEALER)
def submit_claim():
    payload = validate.body()

    # Rung 4 (dealer ownership) precedes payload shape and body foreign keys
    # whenever the claimed delivery can already be resolved.
    raw_delivery_id = payload.get("delivery_id")
    if isinstance(raw_delivery_id, str) and raw_delivery_id in db.deliveries:
        helpers.require_dealer_ownership(db.deliveries[raw_delivery_id]["dealer_id"])

    delivery_id = validate.get_string(payload, "delivery_id", min_len=1)
    program_id = validate.get_string(payload, "program_id", min_len=1)
    claimed_amount_cents = validate.get_int(payload, "claimed_amount_cents", minimum=0)
    expected_version = validate.get_int(payload, "expected_program_version")

    delivery = helpers.get_delivery(delivery_id)
    program = helpers.get_program(program_id)
    helpers.require_dealer_ownership(delivery["dealer_id"])

    if expected_version != program["version"]:
        raise errors.ApiError("ERR_STALE_PROGRAM_VERSION")

    if program["status"] != "ACTIVE":
        raise errors.ApiError("ERR_PROGRAM_NOT_ACTIVE")

    if not calc.window_contains(program, delivery["sale_date"]):
        raise errors.ApiError("ERR_SALE_DATE_OUTSIDE_PROGRAM_WINDOW")

    dealer = db.dealers.get(delivery["dealer_id"])
    if dealer is not None:
        helpers.require_good_standing(dealer)

    for existing in calc.delivery_claims(delivery_id):
        if existing["program_id"] != program_id:
            continue
        if existing["validation_status"] == "REJECTED":
            continue
        if existing["payment_status"] == "CHARGED_BACK":
            continue
        raise errors.ApiError("ERR_DUPLICATE_CLAIM")

    if program_id not in [p["id"] for p in calc.candidate_programs(delivery)]:
        raise errors.ApiError("ERR_NO_ELIGIBLE_PROGRAM")

    allocation = calc.stack_allocation(delivery)
    if program_id in allocation["blocked_program_ids"]:
        raise errors.ApiError("ERR_STACK_COMBINATION_FORBIDDEN")
    if program_id in allocation["capped_out_program_ids"]:
        raise errors.ApiError("ERR_STACK_CAP_EXCEEDED")

    claim_type = (
        "STAIR_STEP_BONUS" if program["incentive_type"] == "DEALER_STAIR_STEP" else "UNIT_INCENTIVE"
    )
    claim = db.insert(
        db.claims,
        "claim",
        {
            "delivery_id": delivery_id,
            "dealer_id": delivery["dealer_id"],
            "program_id": program_id,
            "payment_batch_id": None,
            "claim_type": claim_type,
            "claimed_amount_cents": claimed_amount_cents,
            "approved_amount_cents": 0,
            "rate_basis": None,
            "snapshot_per_unit_cents": program["per_unit_amount_cents"],
            "validation_status": "SUBMITTED",
            "payment_status": "UNPAID",
            "rejection_error_id": None,
            "adjudicated_by_user_id": None,
            "paid_at": None,
        },
    )
    touch(program)
    return response.object_response(serializers.claim(claim), 201)


@bp.route("/claims", methods=["GET"])
@require_roles(AUDITOR, CONTROLLER, DESIGNER, DEALER)
def list_claims():
    program_id = validate.query_string("program_id")
    dealer_id = validate.query_string("dealer_id")
    delivery_id = validate.query_string("delivery_id")
    payment_batch_id = validate.query_string("payment_batch_id")
    validation_status = validate.query_enum("validation_status", VALIDATION_STATUSES)
    payment_status = validate.query_enum("payment_status", PAYMENT_STATUSES)
    rows = db.ordered(list(db.claims.values()))
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if delivery_id is not None:
        rows = [r for r in rows if r["delivery_id"] == delivery_id]
    if payment_batch_id is not None:
        rows = [r for r in rows if r["payment_batch_id"] == payment_batch_id]
    if validation_status is not None:
        rows = [r for r in rows if r["validation_status"] == validation_status]
    if payment_status is not None:
        rows = [r for r in rows if r["payment_status"] == payment_status]
    return response.listing(rows, request.args, serializers.claim)


@bp.route("/claims/<claim_id>", methods=["GET"])
@require_roles(AUDITOR, CONTROLLER, DESIGNER, DEALER)
def read_claim(claim_id):
    claim = helpers.get_claim(claim_id)
    return response.object_response(serializers.claim(claim))


@bp.route("/claims/<claim_id>/adjudicate", methods=["POST"])
@require_roles(AUDITOR)
def adjudicate_claim(claim_id):
    claim = helpers.get_claim(claim_id)
    delivery = db.deliveries.get(claim["delivery_id"])

    # Rung 3: the auditor who vouched for the delivery may not decide its money.
    if (
        delivery is not None
        and delivery["validated_by_user_id"] is not None
        and delivery["validated_by_user_id"] == caller_id()
    ):
        raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES")

    payload = validate.body()
    decision = validate.get_enum(payload, "decision", DECISIONS)
    rejection_error_id = validate.get_string(
        payload, "rejection_error_id", required=False, default=None
    )

    if claim["validation_status"] != "SUBMITTED":
        raise errors.ApiError("ERR_CLAIM_ALREADY_ADJUDICATED")

    # PRD 2.7: "no side effect of any kind is applied to any entity once a check
    # fails", so adjudicated_by_user_id is only stamped once the decision's own
    # gates have all passed -- never before them.
    if decision == "REJECT":
        claim["adjudicated_by_user_id"] = caller_id()
        claim["validation_status"] = "REJECTED"
        claim["approved_amount_cents"] = 0
        claim["rejection_error_id"] = rejection_error_id
        touch(claim)
        return response.object_response(serializers.claim(claim))

    program = db.programs[claim["program_id"]]
    if program["status"] != "ACTIVE":
        raise errors.ApiError("ERR_PROGRAM_NOT_ACTIVE")
    if delivery is None or delivery["status"] != "VALIDATED":
        raise errors.ApiError("ERR_DELIVERY_NOT_VALIDATED")

    if claim["claim_type"] == "STAIR_STEP_BONUS":
        objective = calc.find_objective(claim["program_id"], claim["dealer_id"])
        if objective is None or objective["status"] != "FINAL":
            raise errors.ApiError("ERR_OBJECTIVE_NOT_FINAL")

    amount, rate_basis = calc.claim_payable(claim)
    if program["committed_cents"] + amount > program["budget_cents"]:
        raise errors.ApiError("ERR_PROGRAM_BUDGET_EXHAUSTED")

    claim["adjudicated_by_user_id"] = caller_id()
    claim["validation_status"] = "VALIDATED"
    claim["approved_amount_cents"] = amount
    claim["rate_basis"] = rate_basis
    touch(claim)
    ledger.recompute_program(program)
    return response.object_response(serializers.claim(claim))


# --------------------------------------------------------------------------
# Chargebacks
# --------------------------------------------------------------------------

def _direct_chargeback_amount(claim, reason):
    if reason in ledger.FULL_REVERSAL_REASONS:
        return claim["approved_amount_cents"]
    if reason == "OBJECTIVE_REVISED":
        objective = calc.find_objective(claim["program_id"], claim["dealer_id"])
        if objective is None:
            return 0
        return objective["paid_payout_cents"] - objective["payout_cents"]
    recomputed, _ = calc.claim_payable(claim, force_repriced=True)
    return claim["approved_amount_cents"] - recomputed


@bp.route("/claims/<claim_id>/chargebacks", methods=["POST"])
@require_roles(AUDITOR)
def raise_chargeback(claim_id):
    claim = helpers.get_claim(claim_id)
    payload = validate.body()
    reason = validate.get_enum(payload, "reason", ledger.CHARGEBACK_REASONS)

    if claim["payment_status"] not in ("SCHEDULED", "PAID"):
        raise errors.ApiError("ERR_CHARGEBACK_NOT_APPLICABLE")

    amount = _direct_chargeback_amount(claim, reason)
    if amount <= 0:
        raise errors.ApiError("ERR_CHARGEBACK_NOT_APPLICABLE")

    chargeback = ledger.create_chargeback(claim, reason, amount, created_by_user_id=caller_id())

    if reason in ledger.FULL_REVERSAL_REASONS:
        ledger.reverse_claim_payment(claim)
    else:
        # A partial recovery leaves the claim's payment state exactly where it was.
        touch(claim)

    ledger.recompute_program(db.programs[claim["program_id"]])
    ledger.recompute_dealer(db.dealers.get(claim["dealer_id"]))
    return response.object_response(serializers.chargeback(chargeback), 201)


@bp.route("/claims/<claim_id>/chargebacks", methods=["GET"])
@require_roles(AUDITOR, CONTROLLER, DEALER)
def list_chargebacks(claim_id):
    helpers.get_claim(claim_id)
    status = validate.query_enum("status", ("PENDING", "RECOVERED", "WRITTEN_OFF"))
    rows = calc.claim_chargebacks(claim_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.listing(rows, request.args, serializers.chargeback)


def _resolve_chargeback(chargeback_id, new_status):
    chargeback = helpers.get_chargeback(chargeback_id)
    if chargeback["status"] != "PENDING":
        raise errors.ApiError("ERR_CHARGEBACK_INVALID_STATE")
    chargeback["status"] = new_status
    chargeback["recovered_at"] = clock.now()
    touch(chargeback)
    claim = db.claims.get(chargeback["claim_id"])
    if claim is not None:
        ledger.recompute_dealer(db.dealers.get(claim["dealer_id"]))
        ledger.recompute_program(db.programs[claim["program_id"]])
    return chargeback


@bp.route("/chargebacks/<chargeback_id>/recover", methods=["POST"])
@require_roles(CONTROLLER)
def recover_chargeback(chargeback_id):
    validate.body()
    chargeback = _resolve_chargeback(chargeback_id, "RECOVERED")
    return response.object_response(serializers.chargeback(chargeback))


@bp.route("/chargebacks/<chargeback_id>/write-off", methods=["POST"])
@require_roles(CONTROLLER)
def write_off_chargeback(chargeback_id):
    payload = validate.body()
    validate.get_string(payload, "write_off_note", required=False, default=None)
    chargeback = _resolve_chargeback(chargeback_id, "WRITTEN_OFF")
    return response.object_response(serializers.chargeback(chargeback))
