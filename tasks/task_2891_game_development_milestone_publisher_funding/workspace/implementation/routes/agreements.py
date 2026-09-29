"""Deal formation and the agreement lifecycle (PRD 3.1, 3.3, 3.9)."""

from fractions import Fraction

from flask import Blueprint, request

from calc import live_ops_total_cap
from envelope import created, success
from errors import ApiError
from guards import (
    ALL_ROLES,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER_FINANCE,
    begin,
    body,
    find_agreement,
    find_publisher,
    find_studio,
    require_party,
    visible,
)
from ledger import (
    apply_suspension_consequences,
    engagements_of,
    milestones_of,
    payments_of,
    promote_engagements_of_milestone,
    recompute_ledger,
    settle_rights,
)
from listing import matches, paged
from serializers import agreement as ser_agreement
from store import db, fmt_date, lock, new_id, now, now_iso, ordered, parse_instant, stamp_new, touch
from validation import Field, bad

bp = Blueprint("agreements", __name__)

FINANCE_ROLES = [ROLE_PLATFORM_ADMIN, ROLE_PUBLISHER_FINANCE]

AGREEMENT_FIELDS = (
    Field("studio_id", "string", required=True),
    Field("publisher_id", "string", required=True),
    Field("title", "string", required=True, min_len=1, max_len=160, non_blank=True),
    Field("advance_total_cents", "int", required=True, min=100000),
    Field("royalty_rate_bps", "int", required=True, min=500, max=5000),
    Field("recoupable_cost_cap_bps", "int", default=2000, min=0, max=4000),
    Field("platform_fee_bps", "int", default=3000, min=0, max=5000),
    Field("live_ops_quarterly_funding_cents", "int", default=0, min=0),
    Field("ship_date_original", "date", required=True),
)

REASON_FIELDS = (Field("reason", "string"),)

DRAW_FIELDS = (
    Field("amount_cents", "int", required=True),
    Field("memo", "string"),
)


@bp.post("/development-agreements")
def create_agreement():
    actor = begin(FINANCE_ROLES)
    _, data = body(AGREEMENT_FIELDS)
    # PRD 3.1: the ship date "must fall strictly after the logical clock's date at
    # the moment of creation; a ship date already in the past or landing on today
    # is a structural rejection".
    if data["ship_date_original"] <= now().date():
        bad("Field 'ship_date_original' must fall strictly after the logical clock date.")
    with lock:
        # Rule 19: studio_id resolves before publisher_id.
        find_studio(data["studio_id"])
        find_publisher(data["publisher_id"])
        row = {
            "id": new_id(),
            "studio_id": data["studio_id"],
            "publisher_id": data["publisher_id"],
            "title": data["title"],
            "advance_total_cents": data["advance_total_cents"],
            "royalty_rate_bps": data["royalty_rate_bps"],
            "recoupable_cost_cap_bps": data["recoupable_cost_cap_bps"],
            "platform_fee_bps": data["platform_fee_bps"],
            "live_ops_quarterly_funding_cents": data["live_ops_quarterly_funding_cents"],
            "ship_date_original": fmt_date(data["ship_date_original"]),
            "ship_date_current": fmt_date(data["ship_date_original"]),
            "schedule_slip_days": 0,
            "status": "DRAFT",
            "funding_posture": "OPEN",
            "recoupment_state": "PRE_RECOUP",
            "uplift_funded_cents": 0,
            "funding_pool_cents": data["advance_total_cents"],
            "committed_cents": 0,
            "available_funding_cents": data["advance_total_cents"],
            "accepted_value_cents": 0,
            "advance_disbursed_cents": 0,
            "holdback_reserve_cents": 0,
            "withheld_payment_cents": 0,
            "advance_recouped_cents": 0,
            "unrecouped_advance_cents": 0,
            "royalties_paid_to_date_cents": 0,
            "breach_count": 0,
            "accepted_milestone_ratio": Fraction(0),
            "sequel_rights_holder": "PUBLISHER",
            "ip_reversion_state": "NONE",
            "post_launch_support_state": "PENDING",
            "live_ops_drawn_cents": 0,
            "terminated_at": None,
        }
        require_party(actor, row)
        stamp_new(row)
        db.agreements[row["id"]] = row
        return created(ser_agreement(row))


@bp.get("/development-agreements/<aid>")
def read_agreement(aid):
    actor = begin(ALL_ROLES)
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        return success(ser_agreement(agreement))


@bp.get("/development-agreements")
def list_agreements():
    actor = begin(ALL_ROLES)
    with lock:
        rows = [
            row for row in ordered(db.agreements.values())
            if matches(row, request.args, ("studio_id", "publisher_id", "status"))
        ]
        rows = visible(actor, rows, lambda row: row)
        return paged(rows, request.args, ser_agreement)


@bp.get("/development-agreements/<aid>/recoupment-summary")
def recoupment_summary(aid):
    actor = begin(ALL_ROLES)
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        from serializers import _value

        keys = (
            "funding_pool_cents",
            "advance_disbursed_cents",
            "advance_recouped_cents",
            "unrecouped_advance_cents",
            "royalties_paid_to_date_cents",
            "recoupment_state",
            "accepted_milestone_ratio",
            "ip_reversion_state",
            "sequel_rights_holder",
            "post_launch_support_state",
            "live_ops_drawn_cents",
        )
        payload = {"agreement_id": agreement["id"]}
        for key in keys:
            payload[key] = _value(agreement[key])
        return success(payload)


@bp.post("/development-agreements/<aid>/activate")
def activate(aid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        # Rule 22, then 26, then 27.
        if agreement["status"] != "DRAFT":
            raise ApiError("ERR_AGREEMENT_NOT_DRAFT")
        milestones = milestones_of(agreement)
        if not any(m["status"] == "DEFINED" for m in milestones):
            raise ApiError("ERR_AGREEMENT_HAS_NO_MILESTONES")
        if agreement["committed_cents"] != agreement["funding_pool_cents"]:
            raise ApiError("ERR_FUNDING_ALLOCATION_INCOMPLETE")

        agreement["status"] = "ACTIVE"
        agreement["funding_posture"] = "OPEN"
        # Step one: unblocked DEFINED milestones open for delivery.
        for milestone in milestones:
            if milestone["status"] == "DEFINED" and milestone["depends_on_milestone_id"] is None:
                milestone["status"] = "IN_DEVELOPMENT"
                touch(milestone)
                # Step two: their PROPOSED engagements are promoted.
                promote_engagements_of_milestone(milestone)
        recompute_ledger(agreement)
        touch(agreement)
        return success(ser_agreement(agreement))


@bp.post("/development-agreements/<aid>/suspend")
def suspend(aid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    body(REASON_FIELDS)
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        agreement["status"] = "SUSPENDED"
        agreement["funding_posture"] = "FROZEN"
        apply_suspension_consequences(agreement)
        recompute_ledger(agreement)
        touch(agreement)
        return success(ser_agreement(agreement))


@bp.post("/development-agreements/<aid>/reinstate")
def reinstate(aid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    body(REASON_FIELDS)
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        # Rule 24, then rule 68.
        if agreement["status"] != "SUSPENDED":
            raise ApiError("ERR_AGREEMENT_NOT_SUSPENDED")
        if agreement["breach_count"] > 0:
            raise ApiError("ERR_AGREEMENT_HAS_BREACH")

        agreement["status"] = "ACTIVE"
        recompute_ledger(agreement)
        # Step one: held payments return to PENDING_AUTHORIZATION.
        for payment in payments_of(agreement):
            if payment["status"] == "HELD_PENDING_CURE":
                payment["status"] = "PENDING_AUTHORIZATION"
                touch(payment)
        recompute_ledger(agreement)
        # Step two: restore engagements, branches evaluated in the PRD's order.
        posture = agreement["funding_posture"]
        for engagement in engagements_of(agreement):
            if engagement["status"] != "SUSPENDED":
                continue
            milestone = db.milestones[engagement["milestone_id"]]
            state = milestone["status"]
            if posture == "RESTRICTED" and state in ("DEFINED", "IN_DEVELOPMENT"):
                continue
            if state in ("CANCELLED", "BREACHED"):
                continue
            if state == "DEFINED":
                engagement["status"] = "PROPOSED"
                touch(engagement)
            elif state in ("IN_DEVELOPMENT", "UNDER_REVIEW", "CURE_PENDING", "ACCEPTED"):
                engagement["status"] = "ACTIVE"
                touch(engagement)
        # Step three: recompute the posture, which can only be OPEN or RESTRICTED.
        recompute_ledger(agreement)
        touch(agreement)
        return success(ser_agreement(agreement))


@bp.post("/development-agreements/<aid>/terminate")
def terminate(aid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    body(REASON_FIELDS)
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        # Rule 25: not already TERMINATED or COMPLETED.
        if agreement["status"] in ("TERMINATED", "COMPLETED"):
            raise ApiError("ERR_AGREEMENT_TERMINAL")

        agreement["status"] = "TERMINATED"
        agreement["funding_posture"] = "FROZEN"
        agreement["terminated_at"] = now_iso()

        # Step one: cancel unfinished work.
        cancelled = []
        for milestone in milestones_of(agreement):
            if milestone["status"] in ("DEFINED", "IN_DEVELOPMENT", "UNDER_REVIEW", "CURE_PENDING"):
                milestone["status"] = "CANCELLED"
                touch(milestone)
                cancelled.append(milestone["id"])
        recompute_ledger(agreement)

        # Step two: stop the money and the vendors.
        for payment in payments_of(agreement):
            if payment["status"] in ("PENDING_AUTHORIZATION", "HELD_PENDING_CURE"):
                payment["status"] = "WITHHELD"
                touch(payment)
        ended = []
        for engagement in engagements_of(agreement):
            if engagement["milestone_id"] in cancelled and engagement["status"] in (
                "PROPOSED", "ACTIVE", "SUSPENDED",
            ):
                engagement["status"] = "TERMINATED_EARLY"
                touch(engagement)
                ended.append(engagement["id"])

        # Step three: their still-open invoices are voided.
        for invoice in ordered(db.invoices.values()):
            if invoice["engagement_id"] in ended and invoice["status"] == "SUBMITTED":
                invoice["status"] = "VOIDED"
                touch(invoice)

        # Step four: recompute the ledger and settle the rights position.
        recompute_ledger(agreement)
        settle_rights(agreement)
        touch(agreement)
        return success(ser_agreement(agreement))


@bp.post("/development-agreements/<aid>/cure-sweep")
def cure_sweep(aid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        clock = now()
        expired = [
            m for m in milestones_of(agreement)
            if m["status"] == "CURE_PENDING"
            and m["cure_deadline_at"] is not None
            and clock > parse_instant(m["cure_deadline_at"])
        ]
        # Rule 52: at least one cure window must actually have expired.
        if not expired:
            raise ApiError("ERR_CURE_WINDOW_STILL_OPEN")

        # Step one: the expired milestones breach; breach_count is recomputed.
        for milestone in expired:
            milestone["status"] = "BREACHED"
            touch(milestone)
        recompute_ledger(agreement)
        # Step two: the agreement freezes.
        agreement["status"] = "SUSPENDED"
        agreement["funding_posture"] = "FROZEN"
        # Step three: the ordinary suspension consequences.
        apply_suspension_consequences(agreement)
        # Step four: withheld_payment_cents is recomputed.
        recompute_ledger(agreement)
        touch(agreement)
        return success(ser_agreement(agreement))


@bp.post("/development-agreements/<aid>/live-ops-draws")
def live_ops_draw(aid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    _, data = body(DRAW_FIELDS)
    with lock:
        agreement = require_party(actor, find_agreement(aid))
        # Rule 44 then rule 62; the terminal-agreement rule deliberately does not apply.
        if agreement["post_launch_support_state"] != "ACTIVE":
            raise ApiError("ERR_POST_LAUNCH_NOT_ACTIVE")
        amount = data["amount_cents"]
        if amount > agreement["live_ops_quarterly_funding_cents"]:
            raise ApiError("ERR_LIVE_OPS_CAP_EXCEEDED")
        total_cap = live_ops_total_cap(agreement)
        if agreement["live_ops_drawn_cents"] + amount > total_cap:
            raise ApiError("ERR_LIVE_OPS_CAP_EXCEEDED")
        agreement["live_ops_drawn_cents"] += amount
        if agreement["live_ops_drawn_cents"] == total_cap:
            agreement["post_launch_support_state"] = "EXPIRED"
        touch(agreement)
        return success(ser_agreement(agreement))
