"""Commitments: subscriptions, pledges, transitions and the supersession chain."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("commitments", __name__)

COMMITMENT_KINDS = ["RECURRING_SUBSCRIPTION", "MAJOR_GIFT_PLEDGE"]
BILLING_INTERVALS = ["MONTHLY", "ANNUAL", "NONE"]
COMMITMENT_STATUSES = ["ACTIVE", "PAST_DUE", "PAUSED", "FULFILLED", "CANCELLED"]


def _new_commitment_row(donor_id, kind, amount_cents, billing_interval, installments_total):
    now = clock.now()
    row = {
        "id": store.new_id(),
        "donor_member_id": donor_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "billing_interval": billing_interval,
        "installments_total": installments_total,
        "installments_charged": 0,
        "status": "ACTIVE",
        "pause_reason": "NONE",
        "superseded_by_commitment_id": None,
        "sequence_no": store.next_seq("commitment"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.commitments[row["id"]] = row
    return row


@bp.route("/nil/commitments", methods=["POST"])
def create_commitment():
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    donor_id = shape.string_field(body, "donor_member_id", required=True)
    kind = shape.enum_field(body, "kind", COMMITMENT_KINDS, required=True)
    amount = shape.int_field(body, "amount_cents", required=True, positive=True)
    interval = shape.enum_field(body, "billing_interval", BILLING_INTERVALS, required=True)
    installments_total = shape.int_field(body, "installments_total", default=1, minimum=1)
    expected = shape.int_field(body, "expected_donor_member_version", required=True)

    donor = lookup.donor_member(donor_id)

    if expected != donor["version"]:
        raise ApiError("ERR_STALE_DONOR_VERSION")

    if kind == "MAJOR_GIFT_PLEDGE":
        if interval != "NONE":
            raise ApiError("ERR_BILLING_INTERVAL_MISMATCH")
    else:
        if interval not in ("MONTHLY", "ANNUAL"):
            raise ApiError("ERR_BILLING_INTERVAL_MISMATCH")

    row = _new_commitment_row(donor["id"], kind, amount, interval, installments_total)
    derive.bump(donor)
    return envelope.object_response(serialize.commitment(row), 201)


@bp.route("/nil/commitments/<commitment_id>", methods=["GET"])
def read_commitment(commitment_id):
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    row = lookup.commitment(commitment_id)
    return envelope.object_response(serialize.commitment(row))


@bp.route("/nil/commitments", methods=["GET"])
def list_commitments():
    auth.authenticate(auth.NON_ATHLETE_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    donor_id = envelope.id_filter(request.args, "donor_member_id")
    superseded_by = envelope.id_filter(request.args, "superseded_by_commitment_id")
    status = envelope.enum_filter(request.args, "status", COMMITMENT_STATUSES)
    kind = envelope.enum_filter(request.args, "kind", COMMITMENT_KINDS)
    rows = store.ordered(store.commitments.values())
    if donor_id is not None:
        rows = [r for r in rows if r["donor_member_id"] == donor_id]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_commitment_id"] == superseded_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return envelope.list_response([serialize.commitment(r) for r in rows], limit, offset)


@bp.route("/nil/commitments/<commitment_id>/transitions", methods=["POST"])
def transition_commitment(commitment_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    action = shape.enum_field(body, "action", ["PAUSE", "RESUME", "CANCEL"], required=True)
    commitment = lookup.commitment(commitment_id)
    donor = store.donor_members.get(commitment["donor_member_id"])

    # Priority 13 (tier state) sits above priority 14 (commitment state).
    if action == "RESUME":
        tier = store.membership_tiers.get(donor["membership_tier_id"]) if donor else None
        if tier is None or tier["tier_status"] != "OPEN":
            raise ApiError("ERR_TIER_NOT_OPEN")

    if action == "PAUSE":
        if commitment["status"] not in ("ACTIVE", "PAST_DUE"):
            raise ApiError("ERR_COMMITMENT_STATE_INVALID")
        commitment["status"] = "PAUSED"
        commitment["pause_reason"] = "DONOR_REQUEST"
    elif action == "RESUME":
        if commitment["status"] != "PAUSED":
            raise ApiError("ERR_COMMITMENT_STATE_INVALID")
        commitment["status"] = "ACTIVE"
        commitment["pause_reason"] = "NONE"
    else:
        if commitment["status"] not in ("ACTIVE", "PAST_DUE", "PAUSED"):
            raise ApiError("ERR_COMMITMENT_STATE_INVALID")
        commitment["status"] = "CANCELLED"
    derive.touch(commitment)
    if donor is not None:
        derive.maybe_lapse_donor(donor)
    return envelope.object_response(serialize.commitment(commitment))


@bp.route("/nil/commitments/<commitment_id>/restructure", methods=["POST"])
def restructure_commitment(commitment_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    amount = shape.int_field(body, "amount_cents", required=True, positive=True)
    installments_total = shape.int_field(body, "installments_total", minimum=1)
    original = lookup.commitment(commitment_id)

    if original["status"] not in ("ACTIVE", "PAST_DUE", "PAUSED"):
        raise ApiError("ERR_COMMITMENT_STATE_INVALID")

    replacement = _new_commitment_row(
        original["donor_member_id"], original["kind"], amount,
        original["billing_interval"],
        installments_total if installments_total is not None else original["installments_total"],
    )
    original["superseded_by_commitment_id"] = replacement["id"]
    original["status"] = "CANCELLED"
    derive.touch(original)
    donor = store.donor_members.get(original["donor_member_id"])
    if donor is not None:
        derive.maybe_lapse_donor(donor)
    return envelope.object_response(serialize.commitment(replacement), 201)
