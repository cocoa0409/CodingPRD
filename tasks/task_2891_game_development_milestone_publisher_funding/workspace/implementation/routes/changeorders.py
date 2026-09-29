"""Scope change management: uplifts, cuts and the ship date (PRD 3.7)."""

from fractions import Fraction

from flask import Blueprint, request

from envelope import created, success
from errors import ApiError
from guards import (
    ALL_ROLES,
    ROLE_DEVELOPER,
    ROLE_PUBLISHER_FINANCE,
    ROLE_PUBLISHER_REVIEWER,
    agreement_of_change_order,
    begin,
    body,
    find_agreement,
    find_change_order,
    find_milestone,
    require_party,
    visible,
)
from ledger import (
    MAX_SLIP_DAYS,
    MAX_UPLIFT_BPS,
    change_orders_of,
    recompute_ledger,
    recompute_ship_date,
)
from listing import matches, paged
from money import apply_bps, frac
from serializers import change_order as ser_change_order
from store import db, lock, new_id, now_iso, ordered, stamp_new, touch
from validation import Field, bad

bp = Blueprint("changeorders", __name__)

PROPOSE_ROLES = [ROLE_DEVELOPER, ROLE_PUBLISHER_REVIEWER, ROLE_PUBLISHER_FINANCE]

ORDER_FIELDS = (
    Field("agreement_id", "string", required=True),
    Field("target_milestone_id", "string", required=True),
    Field("order_type", "enum", required=True, values=("FUNDING_UPLIFT", "FEATURE_CUT")),
    Field("requested_amount_cents", "int", default=None, min=0),
    Field("ship_date_delta_days", "int", default=None, min=-60, max=60),
    Field("content_threshold_relief_pct", "number", default=None, min=0, max=25),
    Field("rationale", "string", required=True, min_len=1, max_len=500, non_blank=True),
    Field("expected_agreement_version", "int", required=True),
)

DECIDE_FIELDS = (
    Field("decision", "enum", required=True, values=("APPROVE", "DECLINE")),
    Field("decision_note", "string"),
)

AMENDABLE = ("DEFINED", "IN_DEVELOPMENT", "UNDER_REVIEW", "CURE_PENDING")
APPROVABLE = ("DEFINED", "IN_DEVELOPMENT", "CURE_PENDING")


@bp.post("/change-orders")
def create_change_order():
    actor = begin(PROPOSE_ROLES)
    _, data = body(ORDER_FIELDS)
    requested = data["requested_amount_cents"]
    relief = data["content_threshold_relief_pct"]
    # Structural conditional requirements of PRD 2.10.
    if data["order_type"] == "FUNDING_UPLIFT":
        if requested is None or requested < 1:
            bad("A FUNDING_UPLIFT change order requires 'requested_amount_cents' of at least 1.")
    elif relief is None:
        bad("A FEATURE_CUT change order requires 'content_threshold_relief_pct'.")
    if requested is None:
        requested = 0
    if relief is None:
        relief = Fraction(0)
    delta = data["ship_date_delta_days"]
    if delta is None:
        delta = 0

    with lock:
        # Rule 19: agreement_id resolves before target_milestone_id.
        agreement = find_agreement(data["agreement_id"])
        milestone = find_milestone(data["target_milestone_id"])
        require_party(actor, agreement)
        # Rule 21: the mandatory freshness check of PRD 2.7.
        if data["expected_agreement_version"] != agreement["version"]:
            raise ApiError("ERR_STALE_AGREEMENT_VERSION")
        # Rule 23.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 37.
        if milestone["status"] not in AMENDABLE:
            raise ApiError("ERR_MILESTONE_NOT_AMENDABLE")

        row = {
            "id": new_id(),
            "agreement_id": agreement["id"],
            "target_milestone_id": milestone["id"],
            "order_type": data["order_type"],
            "requested_amount_cents": requested,
            "ship_date_delta_days": delta,
            "content_threshold_relief_pct": relief,
            "rationale": data["rationale"],
            "state": "PROPOSED",
            "decision_note": None,
            "decided_at": None,
        }
        stamp_new(row)
        # Cascade: a newer proposal supersedes any still-PROPOSED order on the
        # same target milestone.
        for other in change_orders_of(agreement):
            if (
                other["target_milestone_id"] == milestone["id"]
                and other["state"] == "PROPOSED"
            ):
                other["state"] = "SUPERSEDED"
                touch(other)
        db.change_orders[row["id"]] = row
        touch(agreement)
        return created(ser_change_order(row))


@bp.get("/change-orders/<cid>")
def read_change_order(cid):
    actor = begin(ALL_ROLES)
    with lock:
        order = find_change_order(cid)
        require_party(actor, agreement_of_change_order(order))
        return success(ser_change_order(order))


@bp.get("/change-orders")
def list_change_orders():
    actor = begin(ALL_ROLES)
    with lock:
        rows = [
            row for row in ordered(db.change_orders.values())
            if matches(
                row, request.args,
                ("agreement_id", "target_milestone_id", "state", "order_type"),
            )
        ]
        kind = request.args.get("kind")
        if kind:
            rows = [row for row in rows if row["order_type"] == kind]
        rows = visible(actor, rows, agreement_of_change_order)
        return paged(rows, request.args, ser_change_order)


def _prospective_slip(agreement, order):
    """The slip the schedule would carry once this order is approved."""
    applied = [
        c for c in change_orders_of(agreement)
        if c["state"] in ("APPROVED_UPLIFT", "APPROVED_CUT")
    ]
    return sum(c["ship_date_delta_days"] for c in applied) + order["ship_date_delta_days"]


@bp.post("/change-orders/<cid>/decide")
def decide_change_order(cid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    _, data = body(DECIDE_FIELDS)
    approve = data["decision"] == "APPROVE"
    with lock:
        order = find_change_order(cid)
        agreement = agreement_of_change_order(order)
        require_party(actor, agreement)
        # Rule 23.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 36.
        if order["state"] != "PROPOSED":
            raise ApiError("ERR_CHANGE_ORDER_NOT_PROPOSED")
        milestone = db.milestones[order["target_milestone_id"]]
        # Rule 37: an approval narrows the amendable set further.
        allowed = APPROVABLE if approve else AMENDABLE
        if milestone["status"] not in allowed:
            raise ApiError("ERR_MILESTONE_NOT_AMENDABLE")

        if approve:
            # Rule 57: the uplift cap, twenty-five percent of advance_total_cents.
            if order["order_type"] == "FUNDING_UPLIFT":
                cap = apply_bps(agreement["advance_total_cents"], MAX_UPLIFT_BPS)
                if agreement["uplift_funded_cents"] + order["requested_amount_cents"] > cap:
                    raise ApiError("ERR_UPLIFT_CAP_EXCEEDED")
            # Rule 58: the slip limit, bounded in both directions.
            if abs(_prospective_slip(agreement, order)) > MAX_SLIP_DAYS:
                raise ApiError("ERR_SHIP_DATE_SLIP_EXCEEDED")
            # Rule 67: a cut may not push a milestone's funding below zero.
            if order["order_type"] == "FEATURE_CUT":
                available = milestone["funded_amount_cents"] + milestone["uplift_cents"]
                if order["requested_amount_cents"] > available:
                    raise ApiError("ERR_CUT_EXCEEDS_MILESTONE_FUNDING")

        order["decided_at"] = now_iso()
        if data["decision_note"] is not None:
            order["decision_note"] = data["decision_note"]

        if not approve:
            # Branch C: nothing else at all moves.
            order["state"] = "DECLINED"
        elif order["order_type"] == "FUNDING_UPLIFT":
            # Branch A.
            order["state"] = "APPROVED_UPLIFT"
            milestone["uplift_cents"] += order["requested_amount_cents"]
            touch(milestone)
            recompute_ledger(agreement)
            recompute_ship_date(agreement)
            recompute_ledger(agreement)
        else:
            # Branch B: the pool is credited by shrinking the commitment.
            order["state"] = "APPROVED_CUT"
            milestone["uplift_cents"] -= order["requested_amount_cents"]
            milestone["content_threshold_relief_pct"] = frac(
                milestone["content_threshold_relief_pct"]
            ) + frac(order["content_threshold_relief_pct"])
            touch(milestone)
            recompute_ledger(agreement)
            recompute_ship_date(agreement)
            recompute_ledger(agreement)

        touch(order)
        touch(agreement)
        return success(ser_change_order(order))
