"""Routes: appeals, manipulation flags, incentive statements, action plans."""

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import services
from middleware import require_roles
from response import parse_pagination, success_list, success_object
from routes_core import _body, _require, _sorted

bp = Blueprint("integrity", __name__)


def _response_dealer_id(resp):
    inv = db.invitations.get(resp["invitation_id"])
    if inv is None:
        return None
    tx = db.transactions.get(inv["transaction_id"])
    return tx["dealer_id"] if tx else None


# ----------------------------------------------------------------- appeals


@bp.post("/survey/appeals")
@require_roles("DealerPrincipal")
def create_appeal(user_id, role):
    data = _require(_body(), "response_id", "reason", "expected_response_version")
    resp = db.responses.get(data["response_id"])
    if resp is None:
        raise errors.not_found("Response not found")
    dealer_id = _response_dealer_id(resp)
    # cross-reference: appeal dealer resolved from response matches caller
    if dealer_id != user_id:
        raise errors.cross_reference("Appeal dealer does not match caller")
    # state validity
    if resp["status"] != "SCORED":
        raise errors.invalid_state("Response is not SCORED")
    # OCC (priority 7)
    expected = data["expected_response_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_response_version must be an integer")
    if expected != resp["version"]:
        raise errors.stale_version()
    # appeal singleton (priority 15)
    for ap in db.appeals.values():
        if ap["response_id"] == resp["id"] and ap["status"] in (
            "FILED",
            "UNDER_REVIEW",
        ):
            raise errors.appeal_already_open()
    rec = helpers.make_record()
    rec.update(
        {
            "response_id": resp["id"],
            "dealer_id": dealer_id,
            "reason": data["reason"],
            "status": "FILED",
            "decision_rationale": None,
            "prior_response_status": resp["status"],
        }
    )
    db.appeals[rec["id"]] = rec
    resp["status"] = "FLAGGED"
    helpers.touch(resp)
    return success_object(helpers.ser_appeal(rec), 201)


@bp.get("/survey/appeals/<aid>")
@require_roles(
    "PlatformAdmin", "ComplianceAuditor", "RegionalManager", "DealerPrincipal"
)
def get_appeal(user_id, role, aid):
    rec = db.appeals.get(aid)
    if rec is None:
        raise errors.not_found("Appeal not found")
    return success_object(helpers.ser_appeal(rec))


def _list_appeals(args, forced_dealer_id=None):
    limit, offset = parse_pagination(args)
    items = list(db.appeals.values())
    dealer_id = forced_dealer_id or args.get("dealer_id")
    if dealer_id is not None:
        items = [a for a in items if a["dealer_id"] == dealer_id]
    for param in ("response_id", "status"):
        v = args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_appeal(a) for a in page], limit, offset, total)


@bp.get("/survey/appeals")
@require_roles("PlatformAdmin", "ComplianceAuditor", "RegionalManager")
def list_appeals(user_id, role):
    return _list_appeals(request.args)


@bp.get("/survey/dealers/<did>/appeals")
@require_roles(
    "PlatformAdmin", "ComplianceAuditor", "RegionalManager", "DealerPrincipal"
)
def list_dealer_appeals(user_id, role, did):
    if did not in db.dealers:
        raise errors.not_found("Dealer not found")
    return _list_appeals(request.args, forced_dealer_id=did)


@bp.post("/survey/appeals/<aid>/assign")
@require_roles("RegionalManager")
def assign_appeal(user_id, role, aid):
    rec = db.appeals.get(aid)
    if rec is None:
        raise errors.not_found("Appeal not found")
    if rec["status"] != "FILED":
        raise errors.invalid_state("Appeal is not FILED")
    rec["status"] = "UNDER_REVIEW"
    helpers.touch(rec)
    return success_object(helpers.ser_appeal(rec))


@bp.post("/survey/appeals/<aid>/decide")
@require_roles("ComplianceAuditor")
def decide_appeal(user_id, role, aid):
    rec = db.appeals.get(aid)
    if rec is None:
        raise errors.not_found("Appeal not found")
    if rec["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Appeal is not UNDER_REVIEW")
    data = _require(_body(), "outcome")
    outcome = data["outcome"]
    if outcome not in ("UPHELD", "DENIED"):
        raise errors.invalid_request("outcome must be UPHELD or DENIED")
    rationale = data.get("decision_rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise errors.invalid_request("decision_rationale must be non-empty")
    rec["decision_rationale"] = rationale
    rec["status"] = outcome
    helpers.touch(rec)
    resp = db.responses.get(rec["response_id"])
    if resp is not None and resp["status"] == "FLAGGED":
        if outcome == "UPHELD":
            resp["status"] = "EXCLUDED"
            resp["excluded_reason"] = "APPEAL_UPHELD"
        else:
            resp["status"] = resp.get("prior_response_status_snapshot") or "SCORED"
            # per spec, DENIED returns response to prior status (SCORED)
            resp["status"] = rec["prior_response_status"]
            if resp["status"] not in ("SCORED",):
                resp["status"] = "SCORED"
            resp["excluded_reason"] = None
        helpers.touch(resp)
    return success_object(helpers.ser_appeal(rec))


# ------------------------------------------------------------------- flags


@bp.post("/survey/flags")
@require_roles("ComplianceAuditor")
def create_flag(user_id, role):
    data = _require(_body(), "dealer_id", "kind", "evidence")
    if data["dealer_id"] not in db.dealers:
        raise errors.not_found("Dealer not found")
    response_id = data.get("response_id")
    if response_id is not None and response_id not in db.responses:
        raise errors.not_found("Response not found")
    if data["kind"] not in ("COACHING", "OPT_OUT_SUPPRESSION", "CONTACT_TAMPERING"):
        raise errors.invalid_request("invalid kind")
    rec = helpers.make_record()
    rec.update(
        {
            "dealer_id": data["dealer_id"],
            "response_id": response_id,
            "kind": data["kind"],
            "evidence": data["evidence"],
            "status": "OPEN",
            "confirmed_at": None,
        }
    )
    db.flags[rec["id"]] = rec
    return success_object(helpers.ser_flag(rec), 201)


@bp.get("/survey/flags/<fid>")
@require_roles("PlatformAdmin", "ComplianceAuditor", "RegionalManager")
def get_flag(user_id, role, fid):
    rec = db.flags.get(fid)
    if rec is None:
        raise errors.not_found("Flag not found")
    return success_object(helpers.ser_flag(rec))


def _list_flags(args, forced_dealer_id=None):
    limit, offset = parse_pagination(args)
    items = list(db.flags.values())
    dealer_id = forced_dealer_id or args.get("dealer_id")
    if dealer_id is not None:
        items = [f for f in items if f["dealer_id"] == dealer_id]
    for param in ("response_id", "status"):
        v = args.get(param)
        if v is not None:
            items = [f for f in items if f.get(param) == v]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_flag(f) for f in page], limit, offset, total)


@bp.get("/survey/flags")
@require_roles("PlatformAdmin", "ComplianceAuditor", "RegionalManager")
def list_flags(user_id, role):
    return _list_flags(request.args)


@bp.get("/survey/dealers/<did>/flags")
@require_roles(
    "PlatformAdmin", "ComplianceAuditor", "RegionalManager", "DealerPrincipal"
)
def list_dealer_flags(user_id, role, did):
    if did not in db.dealers:
        raise errors.not_found("Dealer not found")
    return _list_flags(request.args, forced_dealer_id=did)


@bp.post("/survey/flags/<fid>/resolve")
@require_roles("ComplianceAuditor")
def resolve_flag(user_id, role, fid):
    rec = db.flags.get(fid)
    if rec is None:
        raise errors.not_found("Flag not found")
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Flag is not OPEN")
    data = _require(_body(), "outcome")
    outcome = data["outcome"]
    if outcome not in ("CONFIRMED", "DISMISSED"):
        raise errors.invalid_request("outcome must be CONFIRMED or DISMISSED")
    rec["status"] = outcome
    if outcome == "CONFIRMED":
        rec["confirmed_at"] = clock.now()
    helpers.touch(rec)
    if outcome == "CONFIRMED":
        resp = db.responses.get(rec["response_id"]) if rec["response_id"] else None
        if resp is not None and resp["status"] == "SCORED":
            resp["status"] = "EXCLUDED"
            resp["excluded_reason"] = "MANIPULATION_CONFIRMED"
            helpers.touch(resp)
        dealer = db.dealers.get(rec["dealer_id"])
        if dealer is not None:
            services.recompute_confirmed_flag_count(dealer)
            services.apply_posture(dealer)
            helpers.touch(dealer)
    return success_object(helpers.ser_flag(rec))
