"""Routes: invitations and responses."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import services
from middleware import require_roles
from response import parse_pagination, success_list, success_object
from routes_core import _body, _require, _sorted

bp = Blueprint("invitations", __name__)


def _get_invitation(iid):
    inv = db.invitations.get(iid)
    if inv is None:
        raise errors.not_found("Invitation not found")
    return inv


def _wave_counter_decrement(wave, status):
    if status == "QUEUED":
        wave["queued_count"] -= 1
    elif status == "SENT":
        wave["sent_count"] -= 1


@bp.get("/survey/invitations/<iid>")
@require_roles("PlatformAdmin", "ComplianceAuditor", "SurveyVendor", "Customer")
def get_invitation(user_id, role, iid):
    inv = _get_invitation(iid)
    if role == "Customer" and inv["customer_id"] != user_id:
        raise errors.forbidden()
    return success_object(helpers.ser_invitation(inv))


@bp.get("/survey/invitations")
@require_roles("PlatformAdmin", "ComplianceAuditor", "SurveyVendor", "RegionalManager")
def list_invitations(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.invitations.values())
    for param in (
        "transaction_id",
        "customer_id",
        "wave_id",
        "question_set_id",
        "status",
    ):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i.get(param) == v]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_invitation(i) for i in page], limit, offset, total)


@bp.get("/survey/waves/<wid>/invitations")
@require_roles("PlatformAdmin", "RegionalManager", "ComplianceAuditor", "SurveyVendor")
def list_wave_invitations(user_id, role, wid):
    if wid not in db.waves:
        raise errors.not_found("Wave not found")
    limit, offset = parse_pagination(request.args)
    items = [i for i in db.invitations.values() if i["wave_id"] == wid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_invitation(i) for i in page], limit, offset, total)


@bp.post("/survey/invitations/<iid>/send")
@require_roles("SurveyVendor")
def send_invitation(user_id, role, iid):
    inv = _get_invitation(iid)
    if inv["status"] != "QUEUED":
        raise errors.invalid_state("Invitation is not QUEUED")
    wave = db.waves.get(inv["wave_id"])
    if wave is None or wave["status"] != "OPEN":
        raise errors.wave_not_open()
    cust = db.customers.get(inv["customer_id"])
    if cust is not None and cust["do_not_contact"]:
        raise errors.contact_restricted()
    now = clock.now()
    inv["status"] = "SENT"
    inv["sent_at"] = now
    inv["window_closes_at"] = now + timedelta(days=services.WINDOW_DAYS)
    helpers.touch(inv)
    wave["queued_count"] -= 1
    wave["sent_count"] += 1
    helpers.touch(wave)
    return success_object(helpers.ser_invitation(inv))


def _validate_answers(question_set, answers):
    if not isinstance(answers, list):
        raise errors.invalid_request("answers must be an array")
    expected = {q["question_code"] for q in question_set["questions"]}
    seen = set()
    for a in answers:
        if not isinstance(a, dict):
            raise errors.invalid_request("each answer must be an object")
        code = a.get("question_code")
        score = a.get("score")
        if code not in expected:
            raise errors.invalid_request("unknown question_code")
        if code in seen:
            raise errors.invalid_request("duplicate question_code")
        seen.add(code)
        if isinstance(score, bool) or not isinstance(score, int):
            raise errors.invalid_request("score must be an integer 1-10")
        if not (1 <= score <= 10):
            raise errors.invalid_request("score must be between 1 and 10")
    if seen != expected:
        raise errors.invalid_request("answers must cover every question exactly once")


@bp.post("/survey/invitations/<iid>/responses")
@require_roles("Customer")
def submit_response(user_id, role, iid):
    inv = _get_invitation(iid)
    # ownership (priority 3)
    if inv["customer_id"] != user_id:
        raise errors.forbidden()
    # state validity (priority 6)
    if inv["status"] != "SENT":
        raise errors.invalid_state("Invitation is not SENT")
    # response window (priority 8): exclusive upper bound
    if clock.now() >= inv["window_closes_at"]:
        raise errors.response_window_closed()
    data = _require(_body(), "answers")
    question_set = db.question_sets.get(inv["question_set_id"])
    _validate_answers(question_set, data["answers"])
    score = services.compute_response_score(question_set, data["answers"])
    resp = helpers.make_record()
    resp.update(
        {
            "invitation_id": inv["id"],
            "answers": data["answers"],
            "score": score,
            "status": "SCORED",
            "excluded_reason": None,
            "submitted_at": clock.now(),
        }
    )
    db.responses[resp["id"]] = resp
    inv["status"] = "RESPONDED"
    helpers.touch(inv)
    wave = db.waves.get(inv["wave_id"])
    if wave is not None:
        wave["sent_count"] -= 1
        wave["responded_count"] += 1
        helpers.touch(wave)
    return success_object(helpers.ser_response(resp), 201)


@bp.post("/survey/invitations/<iid>/opt-out")
@require_roles("Customer")
def opt_out_invitation(user_id, role, iid):
    inv = _get_invitation(iid)
    if inv["customer_id"] != user_id:
        raise errors.forbidden()
    if inv["status"] not in ("QUEUED", "SENT"):
        raise errors.invalid_state("Invitation is not QUEUED or SENT")
    prior = inv["status"]
    inv["status"] = "OPTED_OUT"
    helpers.touch(inv)
    cust = db.customers.get(inv["customer_id"])
    if cust is not None:
        cust["do_not_contact"] = True
        helpers.touch(cust)
    wave = db.waves.get(inv["wave_id"])
    if wave is not None:
        _wave_counter_decrement(wave, prior)
        wave["opted_out_count"] += 1
        helpers.touch(wave)
    return success_object(helpers.ser_invitation(inv))


@bp.post("/survey/invitations/<iid>/suppress")
@require_roles("ComplianceAuditor")
def suppress_invitation(user_id, role, iid):
    inv = _get_invitation(iid)
    if inv["status"] not in ("QUEUED", "SENT"):
        raise errors.invalid_state("Invitation is not QUEUED or SENT")
    prior = inv["status"]
    inv["status"] = "SUPPRESSED"
    helpers.touch(inv)
    wave = db.waves.get(inv["wave_id"])
    if wave is not None:
        _wave_counter_decrement(wave, prior)
        wave["suppressed_count"] += 1
        helpers.touch(wave)
    if prior == "SENT":
        for resp in db.responses.values():
            if resp["invitation_id"] == inv["id"] and resp["status"] == "SCORED":
                resp["status"] = "EXCLUDED"
                resp["excluded_reason"] = "MANIPULATION_CONFIRMED"
                helpers.touch(resp)
    return success_object(helpers.ser_invitation(inv))


# --------------------------------------------------------------- responses


@bp.get("/survey/responses/<rid>")
@require_roles(
    "PlatformAdmin", "ComplianceAuditor", "RegionalManager", "DealerPrincipal"
)
def get_response(user_id, role, rid):
    resp = db.responses.get(rid)
    if resp is None:
        raise errors.not_found("Response not found")
    return success_object(helpers.ser_response(resp))


@bp.get("/survey/responses")
@require_roles("PlatformAdmin", "ComplianceAuditor", "RegionalManager")
def list_responses(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.responses.values())
    for param in ("invitation_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_response(r) for r in page], limit, offset, total)


@bp.get("/survey/invitations/<iid>/responses")
@require_roles(
    "PlatformAdmin", "ComplianceAuditor", "RegionalManager", "DealerPrincipal"
)
def list_invitation_responses(user_id, role, iid):
    _get_invitation(iid)
    items = _sorted(
        [r for r in db.responses.values() if r["invitation_id"] == iid]
    )
    total = len(items)
    return success_list(
        [helpers.ser_response(r) for r in items], total or 10, 0, total
    )
