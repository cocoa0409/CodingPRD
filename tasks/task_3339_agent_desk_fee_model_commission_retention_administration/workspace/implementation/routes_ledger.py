"""CommissionEntry ledger reads, retention report reads, referral agreement routes."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request
from helpers import new_record, touch, paginate, sort_by_created
import views

bp = Blueprint("ledger", __name__)


@bp.route("/commission-entries/<entryId>", methods=["GET"])
def get_entry(entryId):
    require_roles(*ALL_ROLES)
    e = db["entries"].get(entryId)
    if not e:
        raise err_not_found("CommissionEntry not found")
    return ok(views.entry_view(e))


@bp.route("/commission-entries", methods=["GET"])
def list_entries():
    require_roles("FranchiseeOwner", "BrokerOfRecord", "ManagingBroker",
                  "TrustAccountant", "ComplianceAuditor", "PlatformAdmin")
    items = list(db["entries"].values())
    args = request.args
    if args.get("office_id") is not None:
        items = [e for e in items if e["office_id"] == args.get("office_id")]
    if args.get("transaction_id") is not None:
        items = [e for e in items if e.get("transaction_id") == args.get("transaction_id")]
    if args.get("status") is not None:
        items = [e for e in items if e["status"] == args.get("status")]
    if args.get("entry_kind") is not None:
        items = [e for e in items if e["entry_kind"] == args.get("entry_kind")]
    if args.get("entry_month") is not None:
        items = [e for e in items if e["entry_month"] == args.get("entry_month")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.entry_view(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Retention reports (flat reads)
# ---------------------------------------------------------------------------

@bp.route("/retention-reports/<reportId>", methods=["GET"])
def get_report(reportId):
    require_roles(*ALL_ROLES)
    r = db["reports"].get(reportId)
    if not r:
        raise err_not_found("AgentRetentionReport not found")
    return ok(views.report_view(r))


@bp.route("/retention-reports", methods=["GET"])
def list_reports():
    require_roles(*ALL_ROLES)
    items = list(db["reports"].values())
    args = request.args
    if args.get("office_id") is not None:
        items = [r for r in items if r["office_id"] == args.get("office_id")]
    if args.get("period_month") is not None:
        items = [r for r in items if r["period_month"] == args.get("period_month")]
    if args.get("status") is not None:
        items = [r for r in items if r["status"] == args.get("status")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.report_view(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Referral agreements
# ---------------------------------------------------------------------------

def get_referral_or_404(rid):
    r = db["referrals"].get(rid)
    if not r:
        raise err_not_found("ReferralAgreement not found")
    return r


@bp.route("/referral-agreements", methods=["POST"])
def create_referral():
    require_roles("ManagingBroker")
    body = request.get_json(silent=True) or {}
    referring = body.get("referring_office_id")
    receiving = body.get("receiving_office_id")
    agent_id = body.get("agent_id")
    bps = body.get("referral_fee_bps")
    replaces = body.get("replaces_agreement_id")
    if not isinstance(referring, str) or referring not in db["offices"]:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "referring_office_id does not resolve")
    if not isinstance(receiving, str) or receiving not in db["offices"]:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "receiving_office_id does not resolve")
    if not isinstance(agent_id, str) or agent_id not in db["agents"]:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "agent_id does not resolve")
    if not isinstance(bps, int) or isinstance(bps, bool) or bps < 0 or bps > 5000:
        raise err_invalid_request("referral_fee_bps must be between 0 and 5000")
    if replaces is not None and (not isinstance(replaces, str) or replaces not in db["referrals"]):
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "replaces_agreement_id does not resolve")
    rec = new_record()
    rec.update({
        "referring_office_id": referring,
        "receiving_office_id": receiving,
        "agent_id": agent_id,
        "referral_fee_bps": bps,
        "status": "PROPOSED",
        "replaces_agreement_id": replaces,
        "fulfilled_transaction_id": None,
    })
    db["referrals"][rec["id"]] = rec
    return ok(views.referral_view(rec), 201)


@bp.route("/referral-agreements/<agreementId>", methods=["GET"])
def get_referral(agreementId):
    require_roles(*ALL_ROLES)
    r = get_referral_or_404(agreementId)
    return ok(views.referral_view(r))


@bp.route("/referral-agreements", methods=["GET"])
def list_referrals():
    require_roles("FranchiseeOwner", "BrokerOfRecord", "ManagingBroker",
                  "TrustAccountant", "ComplianceAuditor", "PlatformAdmin")
    items = list(db["referrals"].values())
    args = request.args
    if args.get("referring_office_id") is not None:
        items = [r for r in items if r["referring_office_id"] == args.get("referring_office_id")]
    if args.get("receiving_office_id") is not None:
        items = [r for r in items if r["receiving_office_id"] == args.get("receiving_office_id")]
    if args.get("agent_id") is not None:
        items = [r for r in items if r["agent_id"] == args.get("agent_id")]
    if args.get("status") is not None:
        items = [r for r in items if r["status"] == args.get("status")]
    if args.get("replaces_agreement_id") is not None:
        items = [r for r in items if r.get("replaces_agreement_id") == args.get("replaces_agreement_id")]
    if args.get("fulfilled_transaction_id") is not None:
        items = [r for r in items if r.get("fulfilled_transaction_id") == args.get("fulfilled_transaction_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.referral_view(r) for r in page], total, limit, offset)


@bp.route("/referral-agreements/<agreementId>/accept", methods=["POST"])
def accept_referral(agreementId):
    require_roles("ManagingBroker")
    r = get_referral_or_404(agreementId)
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not PROPOSED")
    referring = db["offices"].get(r["referring_office_id"])
    receiving = db["offices"].get(r["receiving_office_id"])
    if referring and receiving and referring["market_code"] == receiving["market_code"]:
        raise ApiError("ERR_SAME_MARKET_REFERRAL", 422,
                       "Referral fees apply only across markets")
    if r.get("replaces_agreement_id"):
        old = db["referrals"].get(r["replaces_agreement_id"])
        if not old or old["status"] != "ACTIVE":
            raise ApiError("ERR_REPLACED_NOT_ACTIVE", 409,
                           "Replaced agreement is not ACTIVE")
    r["status"] = "ACTIVE"
    touch(r)
    if r.get("replaces_agreement_id"):
        old = db["referrals"].get(r["replaces_agreement_id"])
        old["status"] = "WITHDRAWN"
        touch(old)
    return ok(views.referral_view(r))


@bp.route("/referral-agreements/<agreementId>/decline", methods=["POST"])
def decline_referral(agreementId):
    require_roles("ManagingBroker")
    r = get_referral_or_404(agreementId)
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not PROPOSED")
    r["status"] = "DECLINED"
    touch(r)
    return ok(views.referral_view(r))


@bp.route("/referral-agreements/<agreementId>/withdraw", methods=["POST"])
def withdraw_referral(agreementId):
    require_roles("ManagingBroker")
    r = get_referral_or_404(agreementId)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not ACTIVE")
    if r.get("fulfilled_transaction_id"):
        raise ApiError("ERR_AGREEMENT_LOCKED", 409, "Agreement is already fulfilled")
    r["status"] = "WITHDRAWN"
    touch(r)
    return ok(views.referral_view(r))
