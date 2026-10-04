"""Payment endpoints (PRD §3.4, §3.5): intake, retrieval, offset evaluation
(OCC-guarded), execution, and the depth-3 reversal cascade."""
from flask import Blueprint, request

from constants import (
    PAYMENT_TYPES,
    ROLE_PAYMENT_AGENCY_ANALYST,
    ROLE_TREASURY_OPERATOR,
)
from db import STORE, clock_now, new_entity, touch
from errors import (
    err_dnp_flagged_payment,
    err_invalid_state,
    err_no_active_policy,
    err_not_found,
    err_payee_not_found,
    err_payee_tin_mismatch,
    err_payment_not_executable,
    err_stale_version,
)
from middleware import (
    authenticate,
    get_body,
    list_page,
    require_roles,
    spec_field,
    validate_body,
)
from response import ok, ok_list
from serializers import serialize_payment
from services.cascades import dnp_hit, file_recompute
from services.ledger import assess_remittance, debit_reversal
from services.matching import (
    active_policy_for,
    eligible_debts_for_payment,
    execution_pool,
    intake_projection,
)
from util import gen_id

bp = Blueprint("payments", __name__)


@bp.post("/payment-files/<string:paymentFileId>/payments")
def create_payment(paymentFileId):
    """Multi-part intake (PRD §3.4): payee verification, TIN equality,
    payment-method determination, intake projection, do-not-pay scan."""
    ctx = authenticate()
    require_roles(ctx, ROLE_PAYMENT_AGENCY_ANALYST)
    data = validate_body(get_body(), [
        spec_field("payee_id", "str", required=True),
        spec_field("payee_tin", "str", required=True),
        spec_field("amount_cents", "int", required=True, gt=0),
        spec_field("payment_type", "enum", required=True, enum=PAYMENT_TYPES),
    ])
    payment_file = STORE["files"].get(paymentFileId)
    if payment_file is None:
        raise err_not_found("Payment file not found")
    payee = STORE["payees"].get(data["payee_id"])
    if payee is None:
        raise err_payee_not_found()
    if payment_file["status"] not in ("RECEIVED", "PROCESSING"):
        raise err_invalid_state("The payment file is no longer accepting payments")
    if payee["tin"] != data["payee_tin"]:
        raise err_payee_tin_mismatch()
    policy = active_policy_for(data["payment_type"])
    if policy is None:
        raise err_no_active_policy()

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "payment_file_id": paymentFileId,
        "payee_id": payee["id"],
        "payee_tin": data["payee_tin"],
        "amount_cents": data["amount_cents"],
        "payment_type": data["payment_type"],
        # payment_method_determination: EFT iff routing_number non-null.
        "payment_method": "EFT" if payee["routing_number"] is not None else "CHECK",
        # INTAKE_ESTIMATE projection (protected minimum only, no pct cap).
        "projected_offset_cents": intake_projection(policy, data["amount_cents"]),
        "total_offset_cents": 0,
        "disbursed_cents": 0,
        "executed_by_user_id": None,
        "executed_at": None,
    })
    # Do-not-pay scan at intake (PRD §2.11): a hit holds the payment.
    if dnp_hit(data["payee_tin"]):
        ent["integrity_status"] = "FLAGGED"
        ent["processing_status"] = "HELD"
    else:
        ent["integrity_status"] = "CLEAR"
        ent["processing_status"] = "VERIFIED"
    STORE["payments"][ent["id"]] = ent
    # First payment flips the file to PROCESSING; payment_count recomputes.
    file_recompute(payment_file)
    return ok(serialize_payment(ent), 201)


@bp.get("/payments/<string:paymentId>")
def get_payment(paymentId):
    authenticate()
    payment = STORE["payments"].get(paymentId)
    if payment is None:
        raise err_not_found("Payment not found")
    return ok(serialize_payment(payment))


@bp.get("/payments")
def list_payments():
    authenticate()
    items = list(STORE["payments"].values())
    payment_file_id = request.args.get("payment_file_id")
    payee_id = request.args.get("payee_id")
    processing_status = request.args.get("processing_status")
    integrity_status = request.args.get("integrity_status")
    if payment_file_id is not None:
        items = [p for p in items if p["payment_file_id"] == payment_file_id]
    if payee_id is not None:
        items = [p for p in items if p["payee_id"] == payee_id]
    if processing_status is not None:
        items = [p for p in items if p["processing_status"] == processing_status]
    if integrity_status is not None:
        items = [p for p in items if p["integrity_status"] == integrity_status]
    page, limit, offset, total = list_page(items)
    return ok_list([serialize_payment(p) for p in page], limit, offset, total)


@bp.post("/payments/<string:paymentId>/evaluate-offsets")
def evaluate_offsets(paymentId):
    """VERIFIED/EVALUATED -> EVALUATED. Re-evaluation supersedes: prior
    PROPOSED offsets drop to DROPPED before the fresh waterfall runs.
    OCC-guarded on expected_payment_version (PRD §2.7)."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    data = validate_body(get_body(), [
        spec_field("expected_payment_version", "int", required=True),
    ])
    payment = STORE["payments"].get(paymentId)
    if payment is None:
        raise err_not_found("Payment not found")
    if payment["processing_status"] not in ("VERIFIED", "EVALUATED"):
        raise err_invalid_state("Only a VERIFIED or EVALUATED payment can be evaluated")
    if data["expected_payment_version"] != payment["version"]:
        raise err_stale_version()

    for o in STORE["offsets"].values():
        if o["payment_id"] == paymentId and o["status"] == "PROPOSED":
            o["status"] = "DROPPED"
            touch(o)

    eligible = eligible_debts_for_payment(payment)
    remaining = execution_pool(payment, eligible)
    for debt in eligible:
        if remaining <= 0:
            break
        take = min(remaining, debt["current_balance_cents"])
        if take <= 0:
            continue
        off = new_entity()
        off["id"] = gen_id()
        off.update({
            "payment_id": paymentId,
            "debt_id": debt["id"],
            # Snapshot of Debt.priority_rank at proposal time.
            "priority_rank": debt["priority_rank"],
            "offset_amount_cents": take,
            # fee/net/applied_at stay null until application (PRD §3.4).
            "fee_cents": None,
            "net_remittance_cents": None,
            "applied_at": None,
            "status": "PROPOSED",
        })
        STORE["offsets"][off["id"]] = off
        remaining -= take

    payment["processing_status"] = "EVALUATED"
    touch(payment)  # version increments with each evaluation (PRD §3.4)
    return ok(serialize_payment(payment))


@bp.post("/payments/<string:paymentId>/execute")
def execute_payment(paymentId):
    """EVALUATED -> EXECUTED: apply every PROPOSED offset, assess the §2.9 fee
    per offset against its creditor, disburse the remainder."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    validate_body(get_body(), [])
    payment = STORE["payments"].get(paymentId)
    if payment is None:
        raise err_not_found("Payment not found")
    if payment["processing_status"] != "EVALUATED":
        raise err_payment_not_executable()
    if payment["integrity_status"] != "CLEAR":
        raise err_dnp_flagged_payment()

    now = clock_now()
    proposed = sorted(
        (o for o in STORE["offsets"].values()
         if o["payment_id"] == paymentId and o["status"] == "PROPOSED"),
        key=lambda o: o["_seq"],
    )
    total_offset = 0
    for o in proposed:
        debt = STORE["debts"].get(o["debt_id"])
        creditor = STORE["creditors"].get(debt["creditor_agency_id"]) if debt else None
        o["status"] = "APPLIED"
        o["applied_at"] = now
        fee_cents, net_cents = assess_remittance(creditor, o["offset_amount_cents"])
        o["fee_cents"] = fee_cents
        o["net_remittance_cents"] = net_cents
        touch(o)
        debt["current_balance_cents"] -= o["offset_amount_cents"]
        if debt["current_balance_cents"] == 0 and debt["status"] in ("ACTIVE", "IN_COLLECTION"):
            debt["status"] = "PAID_IN_FULL"
        touch(debt)
        total_offset += o["offset_amount_cents"]

    payment["total_offset_cents"] = total_offset
    payment["disbursed_cents"] = payment["amount_cents"] - total_offset
    payment["executed_by_user_id"] = ctx.user_id
    payment["executed_at"] = now
    payment["processing_status"] = "EXECUTED"
    touch(payment)
    file_recompute(STORE["files"][payment["payment_file_id"]])
    return ok(serialize_payment(payment))


@bp.post("/payments/<string:paymentId>/reverse")
def reverse_payment(paymentId):
    """EXECUTED -> REVERSED, depth-3 cascade (PRD §3.5): (1) every APPLIED
    offset -> REVERSED with the debt's balance restored and PAID_IN_FULL debts
    reopened to ACTIVE; (2) each affected creditor's ledger debited by the
    original gross and net amounts; (3) outstanding receivables re-derive on
    the next read. Refund path deliberately does none of this (§3.6)."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    validate_body(get_body(), [])
    payment = STORE["payments"].get(paymentId)
    if payment is None:
        raise err_not_found("Payment not found")
    if payment["processing_status"] != "EXECUTED":
        raise err_invalid_state("Only an EXECUTED payment can be reversed")

    applied = sorted(
        (o for o in STORE["offsets"].values()
         if o["payment_id"] == paymentId and o["status"] == "APPLIED"),
        key=lambda o: o["_seq"],
    )
    for o in applied:
        o["status"] = "REVERSED"
        touch(o)
        debt = STORE["debts"].get(o["debt_id"])
        if debt is not None:
            debt["current_balance_cents"] += o["offset_amount_cents"]
            if debt["status"] == "PAID_IN_FULL":
                debt["status"] = "ACTIVE"
            touch(debt)
            creditor = STORE["creditors"].get(debt["creditor_agency_id"])
            if creditor is not None:
                debit_reversal(creditor, o["offset_amount_cents"], o["net_remittance_cents"])

    payment["total_offset_cents"] = 0
    payment["disbursed_cents"] = 0
    payment["processing_status"] = "REVERSED"
    touch(payment)
    file_recompute(STORE["files"][payment["payment_file_id"]])
    return ok(serialize_payment(payment))
