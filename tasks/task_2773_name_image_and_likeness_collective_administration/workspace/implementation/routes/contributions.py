"""Contributions: fee bands, settlement outcomes, refunds and their fan-out."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("contributions", __name__)

SOURCE_KINDS = ["SUBSCRIPTION_CHARGE", "MAJOR_GIFT_INSTALLMENT", "ONE_TIME_GIFT"]
DESIGNATIONS = ["UNRESTRICTED", "ROSTER_POOL", "CHARITY_PROGRAM"]
PROCESSOR_OUTCOMES = ["APPROVE", "DECLINE", "DEFER"]
CONTRIBUTION_STATUSES = ["PENDING", "SETTLED", "FAILED", "REFUNDED"]
DEDUCTION_VARIANTS = ["AT_RECEIPT", "YEAR_END_RECOMPUTE"]


def record_contribution_row(donor, commitment, gross_amount_cents, source_kind,
                            designation, processor_outcome):
    now = clock.now()
    row = {
        "id": store.new_id(),
        "donor_member_id": donor["id"],
        "commitment_id": commitment["id"] if commitment is not None else None,
        "gross_amount_cents": gross_amount_cents,
        "source_kind": source_kind,
        "designation": designation,
        "processor_outcome": processor_outcome,
        "status": "PENDING",
        "processing_fee_cents": 0,
        "net_amount_cents": 0,
        "deductible_amount_cents": 0,
        "deduction_variant": None,
        "received_at": now,
        "sequence_no": store.next_seq("contribution"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.contributions[row["id"]] = row
    return row


def settle_contribution(row, outcome, collective, sync=True):
    """Resolve a PENDING contribution and fan out in all four directions."""
    donor = store.donor_members.get(row["donor_member_id"])
    commitment = (store.commitments.get(row["commitment_id"])
                  if row["commitment_id"] else None)
    if outcome == "APPROVE":
        row["status"] = "SETTLED"
        row["processing_fee_cents"] = calc.processing_fee(row["gross_amount_cents"])
        row["net_amount_cents"] = row["gross_amount_cents"] - row["processing_fee_cents"]
        row["deduction_variant"] = "AT_RECEIPT"
        derive.touch(row)
        if donor is not None:
            derive.attribute_deductibility(donor, "AT_RECEIPT")
            derive.activate_donor(donor)
            derive.sync_donor_lifetime(donor)
        if commitment is not None:
            if commitment["status"] == "PAST_DUE":
                commitment["status"] = "ACTIVE"
            commitment["installments_charged"] += 1
            if (commitment["status"] == "ACTIVE"
                    and commitment["installments_charged"] >= commitment["installments_total"]):
                commitment["status"] = "FULFILLED"
            derive.touch(commitment)
            if donor is not None:
                derive.maybe_lapse_donor(donor)
    else:
        row["status"] = "FAILED"
        row["processing_fee_cents"] = 0
        row["net_amount_cents"] = 0
        row["deductible_amount_cents"] = 0
        derive.touch(row)
        if commitment is not None and commitment["status"] == "ACTIVE":
            commitment["status"] = "PAST_DUE"
            derive.touch(commitment)
    if sync and collective is not None:
        derive.sync_collective(collective)


@bp.route("/nil/contributions", methods=["POST"])
def create_contribution():
    auth.authenticate([auth.COLLECTIVE_DIRECTOR, auth.TREASURY_OFFICER])
    body = shape.body()
    donor_id = shape.string_field(body, "donor_member_id", required=True)
    gross = shape.int_field(body, "gross_amount_cents", required=True, positive=True)
    source_kind = shape.enum_field(body, "source_kind", SOURCE_KINDS, required=True)
    commitment_id = shape.string_field(body, "commitment_id")
    designation = shape.enum_field(body, "designation", DESIGNATIONS, default="UNRESTRICTED")
    processor_outcome = shape.enum_field(body, "processor_outcome", PROCESSOR_OUTCOMES,
                                        default="APPROVE")

    donor = lookup.donor_member(donor_id)
    commitment = None
    if commitment_id is not None:
        commitment = lookup.commitment(commitment_id)
        if commitment["donor_member_id"] != donor["id"]:
            raise ApiError("ERR_COMMITMENT_DONOR_MISMATCH")
        if commitment["status"] not in ("ACTIVE", "PAST_DUE"):
            raise ApiError("ERR_COMMITMENT_NOT_CHARGEABLE")

    if source_kind in ("SUBSCRIPTION_CHARGE", "MAJOR_GIFT_INSTALLMENT"):
        if commitment is None:
            raise ApiError("ERR_SOURCE_KIND_COMMITMENT_MISMATCH")
    elif commitment is not None:
        raise ApiError("ERR_SOURCE_KIND_COMMITMENT_MISMATCH")

    collective = store.collectives.get(donor["collective_id"])
    row = record_contribution_row(donor, commitment, gross, source_kind,
                                  designation, processor_outcome)
    if processor_outcome == "APPROVE":
        settle_contribution(row, "APPROVE", collective)
    elif processor_outcome == "DECLINE":
        settle_contribution(row, "DECLINE", collective)
    return envelope.object_response(serialize.contribution(row), 201)


@bp.route("/nil/contributions/<contribution_id>", methods=["GET"])
def read_contribution(contribution_id):
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    row = lookup.contribution(contribution_id)
    return envelope.object_response(serialize.contribution(row))


@bp.route("/nil/contributions", methods=["GET"])
def list_contributions():
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    donor_id = envelope.id_filter(request.args, "donor_member_id")
    commitment_id = envelope.id_filter(request.args, "commitment_id")
    status = envelope.enum_filter(request.args, "status", CONTRIBUTION_STATUSES)
    designation = envelope.enum_filter(request.args, "designation", DESIGNATIONS)
    variant = envelope.enum_filter(request.args, "deduction_variant", DEDUCTION_VARIANTS)
    rows = store.ordered(store.contributions.values())
    if donor_id is not None:
        rows = [r for r in rows if r["donor_member_id"] == donor_id]
    if commitment_id is not None:
        rows = [r for r in rows if r["commitment_id"] == commitment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if designation is not None:
        rows = [r for r in rows if r["designation"] == designation]
    if variant is not None:
        rows = [r for r in rows if r["deduction_variant"] == variant]
    return envelope.list_response([serialize.contribution(r) for r in rows], limit, offset)


@bp.route("/nil/contributions/<contribution_id>/settlements", methods=["POST"])
def settle(contribution_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR, auth.TREASURY_OFFICER])
    body = shape.body()
    outcome = shape.enum_field(body, "outcome", ["APPROVE", "DECLINE"], required=True)
    row = lookup.contribution(contribution_id)

    if row["status"] != "PENDING":
        raise ApiError("ERR_CONTRIBUTION_STATE_INVALID")

    donor = store.donor_members.get(row["donor_member_id"])
    collective = store.collectives.get(donor["collective_id"]) if donor else None
    settle_contribution(row, outcome, collective)
    return envelope.object_response(serialize.contribution(row))


@bp.route("/nil/contributions/<contribution_id>/refund", methods=["POST"])
def refund(contribution_id):
    auth.authenticate([auth.TREASURY_OFFICER])
    row = lookup.contribution(contribution_id)

    if row["status"] != "SETTLED":
        raise ApiError("ERR_CONTRIBUTION_STATE_INVALID")

    row["status"] = "REFUNDED"
    derive.touch(row)
    donor = store.donor_members.get(row["donor_member_id"])
    if donor is not None:
        derive.sync_donor_lifetime(donor)
        collective = store.collectives.get(donor["collective_id"])
        if collective is not None:
            derive.sync_collective(collective)
    return envelope.object_response(serialize.contribution(row))
