"""Account routes: business accounts and risk signals."""
from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
from services import serialize as ser
from services import audit as aud

bp = Blueprint("accounts", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


@bp.post("/ins/business-accounts")
def create_account():
    actor = mw.get_actor()
    mw.require_role(actor, "Agent", "PartnerPlatform", "PlatformAdmin")
    body = _body()
    errors.reject_unknown_keys(body, ("legal_name", "contact_email", "channel", "partner_tenant"))
    legal_name = body.get("legal_name")
    contact_email = body.get("contact_email")
    channel = body.get("channel")
    partner_tenant = body.get("partner_tenant")

    if not isinstance(legal_name, str) or not legal_name:
        raise errors.validation("legal_name is required")
    if not isinstance(contact_email, str) or not contact_email:
        raise errors.validation("contact_email is required")
    if channel not in ("DIRECT", "AGENT", "PARTNER"):
        raise errors.validation("channel must be DIRECT, AGENT or PARTNER")
    if channel == "PARTNER":
        if not isinstance(partner_tenant, str) or not partner_tenant:
            raise errors.validation("partner_tenant is required for PARTNER channel")
    else:
        partner_tenant = None
    if any(a["contact_email"] == contact_email for a in db.business_accounts.values()):
        raise errors.validation("contact_email must be unique")

    rec = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "contact_email": contact_email,
        "channel": channel,
        "partner_tenant": partner_tenant,
        "account_credit_cents": 0,
        "open_claim_count": 0,
        "claims_free_flag": True,
        "created_at": db.fmt_iso(db.clock_now()),
        "updated_at": db.fmt_iso(db.clock_now()),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.business_accounts[rec["id"]] = rec
    aud.record(actor.role, actor.user_id, "BusinessAccount", rec["id"], "create",
               after=ser.public(rec))
    return resp.ok_object(ser.public(rec), status=201)


def _get_account_scoped(actor, aid):
    rec = db.business_accounts.get(aid)
    if rec is None:
        raise errors.not_found("Business account not found")
    if actor.role == "Policyholder" and actor.user_id != rec["id"]:
        raise errors.not_found("Business account not found")
    return rec


@bp.get("/ins/business-accounts")
def list_accounts():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Agent", "PartnerPlatform")
    items = list(db.business_accounts.values())
    channel = request.args.get("channel")
    pt = request.args.get("partner_tenant")
    if channel is not None:
        items = [a for a in items if a["channel"] == channel]
    if pt is not None:
        items = [a for a in items if a["partner_tenant"] == pt]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/business-accounts/<aid>")
def get_account(aid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Agent", "PartnerPlatform", "Policyholder")
    rec = _get_account_scoped(actor, aid)
    return resp.ok_object(ser.public(rec))


@bp.get("/ins/business-accounts/<aid>/risk-signals")
def account_risk_signals(aid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter")
    rec = db.business_accounts.get(aid)
    if rec is None:
        raise errors.not_found("Business account not found")
    items = [s for s in db.risk_signals.values() if s["business_account_id"] == aid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/business-accounts/<aid>/quotes")
def account_quotes(aid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Agent", "PartnerPlatform", "Policyholder", "Underwriter")
    _get_account_scoped(actor, aid)
    items = [q for q in db.quotes.values() if q["business_account_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [q for q in items if q["status"] == status]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/business-accounts/<aid>/policies")
def account_policies(aid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Agent", "PartnerPlatform", "Policyholder", "ComplianceOfficer")
    _get_account_scoped(actor, aid)
    items = [p for p in db.policies.values() if p["business_account_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/business-accounts/<aid>/claims")
def account_claims(aid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "ClaimsAdjuster", "FinanceOfficer")
    _get_account_scoped(actor, aid)
    items = [c for c in db.claims.values() if c.get("reported_by") == aid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


# ---------------------------------------------------------------------------
# Risk signals
# ---------------------------------------------------------------------------
@bp.post("/ins/risk-signals")
def create_risk_signal():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter")
    body = _body()
    errors.reject_unknown_keys(body, ("business_account_id", "signal_type", "severity", "detail"))
    account_id = body.get("business_account_id")
    signal_type = body.get("signal_type")
    severity = body.get("severity")
    detail = body.get("detail")

    if not isinstance(account_id, str) or account_id not in db.business_accounts:
        raise errors.validation("business_account_id must reference an existing account")
    if signal_type not in ("SOS_MATCH", "PROPERTY_PIN", "LOSS_HISTORY", "FRAUD_SCREEN"):
        raise errors.validation("signal_type invalid")
    if not isinstance(severity, int) or isinstance(severity, bool) or not (1 <= severity <= 100):
        raise errors.validation("severity must be an integer in 1..100")
    if not isinstance(detail, str):
        raise errors.validation("detail is required")

    rec = {
        "id": db.new_id(),
        "business_account_id": account_id,
        "signal_type": signal_type,
        "severity": severity,
        "status": "PENDING",
        "detail": detail,
        "created_at": db.fmt_iso(db.clock_now()),
        "updated_at": db.fmt_iso(db.clock_now()),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.risk_signals[rec["id"]] = rec
    aud.record(actor.role, actor.user_id, "RiskSignalReport", rec["id"], "create",
               after=ser.public(rec))
    return resp.ok_object(ser.public(rec), status=201)
