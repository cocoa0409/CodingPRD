"""Dispute case routes (PRD §3.9)."""

from flask import Blueprint, request

import db
from errors import (
    ERR_ADJUSTMENT_REQUIRED,
    ERR_CONTRACT_PARTNER_MISMATCH,
    ERR_DISPUTE_NOT_OWNED,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_DUPLICATE_OPEN_DISPUTE,
    ERR_INVALID_STATE,
    conflict,
    forbidden,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from util import (
    base_entity,
    get_json_body,
    logical_dt,
    paginate,
    req_field,
    req_string,
    touch,
)

bp = Blueprint("disputes", __name__)

DISPUTE_READ_ROLES = ("PlatformAdmin", "CorporateController", "ManagingPartner")


@bp.route("/dispute-cases", methods=["POST"])
def file_dispute():
    user_id, _ = require_roles("ManagingPartner")
    body = get_json_body()
    period_id = req_field(body, "period_id")
    claim_text = req_string(body, "claim_text")
    # Body FK existence (tier 4).
    period = domain.ref_period(period_id)
    # State gate (tier 5): period must be FINALIZED.
    if period["status"] != "FINALIZED":
        raise conflict(ERR_INVALID_STATE, "Disputes may only be filed on a FINALIZED period")
    # Ownership gate: filer must be the partner of the restaurant's active-family contract.
    contract = domain.active_family_contract(period["restaurant_id"])
    if contract is None or contract["partner_id"] != user_id:
        raise forbidden(
            ERR_CONTRACT_PARTNER_MISMATCH,
            "Caller is not the partner of the restaurant's active contract",
        )
    # Temporal (tier 6) BEFORE aggregate (tier 7 duplicate) — §2.5.
    now = logical_dt()
    deadline = period.get("dispute_deadline")
    if deadline is None or now > deadline:
        raise unprocessable(ERR_DISPUTE_WINDOW_CLOSED, "The dispute window has closed")
    duplicate = any(
        d["period_id"] == period["id"] and d["status"] in domain.DISPUTE_OPEN_STATUSES
        for d in db.disputes.values()
    )
    if duplicate:
        raise unprocessable(ERR_DUPLICATE_OPEN_DISPUTE, "An open dispute already exists on the period")
    d = base_entity()
    d.update({
        "period_id": period["id"],
        "filed_by_partner_id": user_id,
        "claim_text": claim_text,
        "filed_at": now,
        "adjustment_cents": None,
        # SUBMITTED at filing, then automatically UNDER_REVIEW.
        "status": "UNDER_REVIEW",
    })
    db.disputes[d["id"]] = d
    return success_object(domain.ser_dispute(d), 201)


@bp.route("/dispute-cases", methods=["GET"])
def list_disputes():
    require_roles(*DISPUTE_READ_ROLES)
    items = list(db.disputes.values())
    period_id = request.args.get("period_id")
    if period_id is not None:
        items = [d for d in items if d["period_id"] == period_id]
    filer = request.args.get("filed_by_partner_id")
    if filer is not None:
        items = [d for d in items if d["filed_by_partner_id"] == filer]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_dispute(d) for d in page], limit, offset, total)


@bp.route("/dispute-cases/<did>", methods=["GET"])
def get_dispute(did):
    require_roles(*DISPUTE_READ_ROLES)
    return success_object(domain.ser_dispute(domain.get_dispute(did)))


@bp.route("/dispute-cases/<did>/request-evidence", methods=["POST"])
def request_evidence(did):
    require_roles("CorporateController")
    d = domain.get_dispute(did)
    if d["status"] != "UNDER_REVIEW":
        raise conflict(ERR_INVALID_STATE, "Dispute must be UNDER_REVIEW to request evidence")
    d["status"] = "EVIDENCE_REQUESTED"
    touch(d)
    return success_object(domain.ser_dispute(d))


@bp.route("/dispute-cases/<did>/submit-evidence", methods=["POST"])
def submit_evidence(did):
    user_id, _ = require_roles("ManagingPartner")
    d = domain.get_dispute(did)
    if d["status"] != "EVIDENCE_REQUESTED":
        raise conflict(ERR_INVALID_STATE, "Dispute must be EVIDENCE_REQUESTED to submit evidence")
    if user_id != d["filed_by_partner_id"]:
        raise forbidden(ERR_DISPUTE_NOT_OWNED, "Caller does not own this dispute")
    get_json_body()  # evidence_text accepted; not persisted on the entity model
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success_object(domain.ser_dispute(d))


@bp.route("/dispute-cases/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    require_roles("CorporateController")
    d = domain.get_dispute(did)
    if d["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise conflict(ERR_INVALID_STATE, "Dispute must be UNDER_REVIEW or ESCALATED to resolve")
    body = get_json_body()
    outcome = req_string(body, "outcome")
    if outcome not in ("UPHELD", "ADJUSTED"):
        raise invalid_request("outcome must be UPHELD or ADJUSTED")
    if outcome == "UPHELD":
        # Upheld — the original computation stands; the period is untouched.
        d["status"] = "RESOLVED_UPHELD"
        touch(d)
        return success_object(domain.ser_dispute(d))
    # ADJUSTED requires a positive adjustment_cents.
    adjustment = body.get("adjustment_cents")
    if adjustment is None or isinstance(adjustment, bool) or not isinstance(adjustment, int) or adjustment <= 0:
        raise unprocessable(ERR_ADJUSTMENT_REQUIRED, "ADJUSTED resolution requires adjustment_cents > 0")
    d["adjustment_cents"] = adjustment
    d["status"] = "RESOLVED_ADJUSTED"
    touch(d)
    # Cascade (§3.6): the finalized period reopens and gains a FINALIZED ADJUSTMENT line.
    period = db.periods.get(d["period_id"])
    if period is not None and period["status"] == "FINALIZED":
        period["status"] = "REOPENED"
        touch(period)
        li = base_entity()
        li.update({
            "period_id": period["id"],
            "category": "ADJUSTMENT",
            "amount_cents": adjustment,
            "entry_status": "FINALIZED",
            "actual_amount_cents": adjustment,
            "partner_basis": "INCLUDED",
        })
        db.line_items[li["id"]] = li
    return success_object(domain.ser_dispute(d))


@bp.route("/dispute-cases/<did>/withdraw", methods=["POST"])
def withdraw_dispute(did):
    user_id, _ = require_roles("ManagingPartner")
    d = domain.get_dispute(did)
    if d["status"] not in ("SUBMITTED", "UNDER_REVIEW", "EVIDENCE_REQUESTED"):
        raise conflict(ERR_INVALID_STATE, "Dispute cannot be withdrawn from status %s" % d["status"])
    if user_id != d["filed_by_partner_id"]:
        raise forbidden(ERR_DISPUTE_NOT_OWNED, "Caller does not own this dispute")
    d["status"] = "WITHDRAWN"
    touch(d)
    return success_object(domain.ser_dispute(d))
