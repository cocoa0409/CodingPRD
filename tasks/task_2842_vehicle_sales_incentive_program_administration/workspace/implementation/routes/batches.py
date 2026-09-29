"""Payment batches: opening, scheduling, locking, disbursement and cancellation."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import util
import validate
from middleware import ROLE_CLAIMS_AUDITOR as AUDITOR
from middleware import ROLE_INCENTIVE_CONTROLLER as CONTROLLER
from middleware import ROLE_PROGRAM_DESIGNER as DESIGNER
from middleware import require_roles, touch
from routes import helpers
from services import calc, ledger

bp = Blueprint("batches", __name__)

OCCUPYING_STATUSES = ("OPEN", "LOCKED", "DISBURSED")


@bp.route("/payment-batches", methods=["POST"])
@require_roles(CONTROLLER)
def open_batch():
    payload = validate.body()
    batch_code = validate.get_string(payload, "batch_code", min_len=1, max_len=24)
    region_code = validate.get_string(payload, "region_code", min_len=1, max_len=8)
    period_start = validate.get_instant(payload, "period_start")
    period_end = validate.get_instant(payload, "period_end")
    if period_end < period_start:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "period_end must be at or after period_start."
        )
    scheduled_pay_date = validate.get_instant(payload, "scheduled_pay_date")
    if scheduled_pay_date < period_end:
        raise errors.ApiError(
            "ERR_INVALID_REQUEST", "scheduled_pay_date must be at or after period_end."
        )

    for existing in db.payment_batches.values():
        if existing["batch_code"] == batch_code:
            raise errors.ApiError("ERR_DUPLICATE_BATCH_CODE")

    region_batches = [
        b
        for b in db.ordered(list(db.payment_batches.values()))
        if b["region_code"] == region_code and b["status"] in OCCUPYING_STATUSES
    ]

    for other in region_batches:
        if period_start <= other["period_end"] and other["period_start"] <= period_end:
            raise errors.ApiError("ERR_BATCH_PERIOD_OVERLAP")

    preceding = [b for b in region_batches if b["period_end"] <= period_start]
    if preceding:
        nearest = max(preceding, key=lambda b: b["period_end"])
        gap_seconds = util.seconds_between(period_start, nearest["period_end"])
        if gap_seconds <= calc.SETTLEMENT_BUFFER_SECONDS:
            raise errors.ApiError("ERR_BATCH_BUFFER_VIOLATION")

    batch = db.insert(
        db.payment_batches,
        "payment_batch",
        {
            "batch_code": batch_code,
            "region_code": region_code,
            "period_start": period_start,
            "period_end": period_end,
            "scheduled_pay_date": scheduled_pay_date,
            "status": "OPEN",
            "claim_count": 0,
            "total_cents": 0,
            "held_claim_count": 0,
            "disbursed_at": None,
        },
    )
    return response.object_response(serializers.payment_batch(batch), 201)


@bp.route("/payment-batches/<batch_id>", methods=["GET"])
@require_roles(CONTROLLER, AUDITOR, DESIGNER)
def read_batch(batch_id):
    batch = helpers.get_batch(batch_id)
    return response.object_response(serializers.payment_batch(batch))


@bp.route("/payment-batches/<batch_id>/schedule-claims", methods=["POST"])
@require_roles(CONTROLLER)
def schedule_claims(batch_id):
    batch = helpers.get_batch(batch_id)
    payload = validate.body()
    claim_ids = validate.get_string_array(payload, "claim_ids")

    claims = [helpers.get_claim(claim_id) for claim_id in claim_ids]

    # Rung 10 screens the state of the *target* resource of the transition first,
    # and for this endpoint the target named in the path is the batch (PRD 2.7
    # rung 5 likewise resolves "the batch before the claims it is asked to
    # schedule"). Only once the batch itself admits the attachment do the
    # referenced claims get screened.
    if batch["status"] != "OPEN":
        raise errors.ApiError("ERR_BATCH_INVALID_STATE")

    # The whole call is a no-op unless every named claim can be attached.
    for claim in claims:
        if claim["validation_status"] != "VALIDATED" or claim["payment_status"] != "UNPAID":
            raise errors.ApiError("ERR_CLAIM_NOT_VALIDATED")
        dealer = db.dealers.get(claim["dealer_id"])
        if dealer is None or dealer["region_code"] != batch["region_code"]:
            raise errors.ApiError("ERR_CLAIM_NOT_VALIDATED")
        delivery = db.deliveries.get(claim["delivery_id"])
        if delivery is None:
            raise errors.ApiError("ERR_CLAIM_NOT_VALIDATED")
        if not (batch["period_start"] <= delivery["sale_date"] <= batch["period_end"]):
            raise errors.ApiError("ERR_CLAIM_NOT_VALIDATED")

    for claim in claims:
        claim["payment_status"] = "SCHEDULED"
        claim["payment_batch_id"] = batch["id"]
        touch(claim)

    ledger.recompute_batch(batch)
    return response.object_response(serializers.payment_batch(batch))


@bp.route("/payment-batches/<batch_id>/lock", methods=["POST"])
@require_roles(CONTROLLER)
def lock_batch(batch_id):
    batch = helpers.get_batch(batch_id)
    validate.body()
    if batch["status"] != "OPEN" or batch["claim_count"] < 1:
        raise errors.ApiError("ERR_BATCH_INVALID_STATE")
    batch["status"] = "LOCKED"
    touch(batch)
    return response.object_response(serializers.payment_batch(batch))


@bp.route("/payment-batches/<batch_id>/disburse", methods=["POST"])
@require_roles(CONTROLLER)
def disburse_batch(batch_id):
    batch = helpers.get_batch(batch_id)
    validate.body()
    if batch["status"] != "LOCKED":
        raise errors.ApiError("ERR_BATCH_INVALID_STATE")
    now = clock.now()
    if now < batch["scheduled_pay_date"]:
        raise errors.ApiError("ERR_PAY_DATE_NOT_REACHED")

    attached = [
        c
        for c in db.ordered(list(db.claims.values()))
        if c["payment_batch_id"] == batch["id"] and c["payment_status"] == "SCHEDULED"
    ]

    held = 0
    programs_touched = []
    dealers_touched = []
    for claim in attached:
        dealer = db.dealers.get(claim["dealer_id"])
        if dealer is None or dealer["status"] != "ACTIVE":
            held += 1
            continue
        claim["payment_status"] = "PAID"
        claim["paid_at"] = now
        touch(claim)
        if claim["claim_type"] == "STAIR_STEP_BONUS":
            objective = calc.find_objective(claim["program_id"], claim["dealer_id"])
            if objective is not None:
                objective["paid_payout_cents"] = claim["approved_amount_cents"]
                touch(objective)
        if claim["program_id"] not in programs_touched:
            programs_touched.append(claim["program_id"])
        if claim["dealer_id"] not in dealers_touched:
            dealers_touched.append(claim["dealer_id"])

    for program_id in programs_touched:
        ledger.recompute_program(db.programs[program_id])
    for dealer_id in dealers_touched:
        ledger.recompute_dealer(db.dealers.get(dealer_id))

    batch["status"] = "DISBURSED"
    batch["disbursed_at"] = now
    batch["held_claim_count"] = held
    ledger.recompute_batch(batch)
    return response.object_response(serializers.payment_batch(batch))


@bp.route("/payment-batches/<batch_id>/cancel", methods=["POST"])
@require_roles(CONTROLLER)
def cancel_batch(batch_id):
    batch = helpers.get_batch(batch_id)
    payload = validate.body()
    validate.get_string(payload, "cancel_note", required=False, default=None)
    if batch["status"] != "OPEN":
        raise errors.ApiError("ERR_BATCH_INVALID_STATE")

    for claim in db.ordered(list(db.claims.values())):
        if claim["payment_batch_id"] != batch["id"]:
            continue
        if claim["payment_status"] != "SCHEDULED":
            continue
        claim["payment_status"] = "UNPAID"
        claim["payment_batch_id"] = None
        touch(claim)

    batch["status"] = "CANCELLED"
    batch["claim_count"] = 0
    batch["total_cents"] = 0
    touch(batch)
    return response.object_response(serializers.payment_batch(batch))
