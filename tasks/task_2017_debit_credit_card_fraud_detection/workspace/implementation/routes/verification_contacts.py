"""VerificationContact endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("verification_contacts", __name__)

VALID_CHANNELS = {"VOICE", "SMS", "EMAIL"}
VALID_OUTCOMES = {"CONFIRMED_FRAUD", "CONFIRMED_LEGIT", "UNREACHABLE"}


@bp.route("/fraudops/verification-contacts", methods=["POST"])
def create_contact():
    user_id, _ = middleware.require_role("FraudAnalyst")
    body = request.get_json(silent=True) or {}
    alert_id = body.get("alert_id")
    channel = body.get("channel")
    if not isinstance(alert_id, str) or not alert_id:
        raise errors.err_invalid_request("alert_id is required")
    if channel not in VALID_CHANNELS:
        raise errors.err_invalid_request("channel must be VOICE, SMS, or EMAIL")

    alert = db.fraud_alerts.get(alert_id)
    if not alert:
        raise errors.err_not_found("FraudAlert not found")
    domain._apply_alert_expiry(alert)

    if alert["alert_status"] not in ("IN_REVIEW", "CONTACT_PENDING"):
        raise errors.err_invalid_state("Alert must be IN_REVIEW or CONTACT_PENDING")
    if alert["assigned_to_user_id"] != user_id:
        raise errors.err_forbidden_role("Alert is assigned to another analyst")

    # 60-minute gap per account
    now = db.get_clock()
    latest = None
    for c in db.verification_contacts.values():
        if c["account_id"] != alert["account_id"]:
            continue
        ca = db._parse_iso(c["contacted_at"])
        if latest is None or ca > latest:
            latest = ca
    if latest is not None and (now - latest) < timedelta(minutes=60):
        raise errors.err_contact_too_soon()

    contact = middleware.stamp_new(
        {
            "alert_id": alert["id"],
            "account_id": alert["account_id"],
            "channel": channel,
            "contact_status": "PENDING",
            "outcome": None,
            "contacted_at": db.get_clock_iso(),
            "created_by_user_id": user_id,
        }
    )
    db.verification_contacts[contact["id"]] = contact

    # transition alert IN_REVIEW -> CONTACT_PENDING
    if alert["alert_status"] == "IN_REVIEW":
        alert["alert_status"] = "CONTACT_PENDING"
        middleware.touch(alert)

    return response.success(domain.ser_contact(contact), status_code=201)


@bp.route("/fraudops/verification-contacts", methods=["GET"])
def list_contacts():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args
    items = sorted(db.verification_contacts.values(), key=lambda c: (c["created_at"], c["id"]))
    for key in ("alert_id", "account_id", "contact_status"):
        v = args.get(key)
        if v:
            items = [c for c in items if c.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_contact(c) for c in sliced], pagination=pg)


@bp.route("/fraudops/verification-contacts/<cid>", methods=["GET"])
def get_contact(cid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    c = db.verification_contacts.get(cid)
    if not c:
        raise errors.err_not_found("VerificationContact not found")
    return response.success(domain.ser_contact(c))


@bp.route("/fraudops/verification-contacts/<cid>/complete", methods=["POST"])
def complete_contact(cid):
    user_id, _ = middleware.require_role("FraudAnalyst")
    c = db.verification_contacts.get(cid)
    if not c:
        raise errors.err_not_found("VerificationContact not found")
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in VALID_OUTCOMES:
        raise errors.err_invalid_request("outcome must be CONFIRMED_FRAUD, CONFIRMED_LEGIT, or UNREACHABLE")
    if c["created_by_user_id"] != user_id:
        raise errors.err_forbidden_role("Only the creating analyst may complete this contact")
    if c["contact_status"] != "PENDING":
        raise errors.err_invalid_state("Contact is not PENDING")
    c["contact_status"] = "COMPLETED"
    c["outcome"] = outcome
    middleware.touch(c)
    return response.success(domain.ser_contact(c))
