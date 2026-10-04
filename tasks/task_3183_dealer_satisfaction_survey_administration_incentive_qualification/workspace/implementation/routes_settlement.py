"""Routes: incentive statements and action plans."""

from flask import Blueprint, request

import db
import errors
import helpers
import services
from middleware import require_roles
from response import parse_pagination, success_list, success_object
from routes_core import _body, _require, _sorted

bp = Blueprint("settlement", __name__)


# -------------------------------------------------------------- statements


@bp.post("/survey/statements")
@require_roles("PlatformAdmin", "RegionalManager")
def create_statement(user_id, role):
    data = _require(_body(), "dealer_id", "wave_id", "expected_wave_version")
    dealer = db.dealers.get(data["dealer_id"])
    if dealer is None:
        raise errors.not_found("Dealer not found")
    wave = db.waves.get(data["wave_id"])
    if wave is None:
        raise errors.not_found("Wave not found")
    expected = data["expected_wave_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_wave_version must be an integer")
    if expected != wave["version"]:
        raise errors.stale_version()
    # supersede prior PROVISIONAL for the same (dealer_id, wave_id)
    prior = None
    for st in db.statements.values():
        if (
            st["dealer_id"] == dealer["id"]
            and st["wave_id"] == wave["id"]
            and st["status"] == "PROVISIONAL"
        ):
            prior = st
            break
    values = services.compute_statement_values(dealer, wave)
    rec = helpers.make_record()
    rec.update(
        {
            "dealer_id": dealer["id"],
            "wave_id": wave["id"],
            "status": "PROVISIONAL",
            "supersedes_id": prior["id"] if prior else None,
        }
    )
    rec.update(values)
    db.statements[rec["id"]] = rec
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        helpers.touch(prior)
    helpers.touch(wave)  # statement creation bumps wave version
    return success_object(helpers.ser_statement(rec), 201)


@bp.get("/survey/statements/<sid>")
@require_roles(
    "PlatformAdmin", "RegionalManager", "ComplianceAuditor", "DealerPrincipal"
)
def get_statement(user_id, role, sid):
    rec = db.statements.get(sid)
    if rec is None:
        raise errors.not_found("Statement not found")
    return success_object(helpers.ser_statement(rec))


def _list_statements(args, forced_dealer_id=None):
    limit, offset = parse_pagination(args)
    items = list(db.statements.values())
    dealer_id = forced_dealer_id or args.get("dealer_id")
    if dealer_id is not None:
        items = [s for s in items if s["dealer_id"] == dealer_id]
    for param in ("wave_id", "supersedes_id", "status"):
        v = args.get(param)
        if v is not None:
            items = [s for s in items if s.get(param) == v]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [helpers.ser_statement(s) for s in page], limit, offset, total
    )


@bp.get("/survey/statements")
@require_roles("PlatformAdmin", "RegionalManager", "ComplianceAuditor")
def list_statements(user_id, role):
    return _list_statements(request.args)


@bp.get("/survey/dealers/<did>/statements")
@require_roles(
    "PlatformAdmin", "RegionalManager", "ComplianceAuditor", "DealerPrincipal"
)
def list_dealer_statements(user_id, role, did):
    if did not in db.dealers:
        raise errors.not_found("Dealer not found")
    return _list_statements(request.args, forced_dealer_id=did)


@bp.post("/survey/statements/<sid>/pay")
@require_roles("PlatformAdmin")
def pay_statement(user_id, role, sid):
    rec = db.statements.get(sid)
    if rec is None:
        raise errors.not_found("Statement not found")
    if rec["status"] != "FINAL":
        raise errors.invalid_state("Statement is not FINAL")
    rec["status"] = "PAID"
    helpers.touch(rec)
    return success_object(helpers.ser_statement(rec))


# ------------------------------------------------------------ action plans


@bp.post("/survey/action-plans")
@require_roles("DealerPrincipal", "FieldConsultant")
def create_action_plan(user_id, role):
    data = _require(_body(), "dealer_id", "wave_id", "title", "items", "due_date")
    if data["dealer_id"] not in db.dealers:
        raise errors.not_found("Dealer not found")
    if data["wave_id"] not in db.waves:
        raise errors.not_found("Wave not found")
    if role == "DealerPrincipal" and data["dealer_id"] != user_id:
        raise errors.forbidden()
    items = data["items"]
    if not isinstance(items, list) or len(items) < 1:
        raise errors.validation("items must contain at least one item")
    for item in items:
        if not isinstance(item, dict):
            raise errors.validation("each item must be an object")
        for f in ("action", "owner", "due_date"):
            if f not in item:
                raise errors.validation(f"item missing {f}")
    try:
        due = __import__("clock").parse_iso(data["due_date"])
    except (ValueError, TypeError):
        raise errors.invalid_request("due_date must be ISO8601")
    rec = helpers.make_record()
    rec.update(
        {
            "dealer_id": data["dealer_id"],
            "wave_id": data["wave_id"],
            "title": data["title"],
            "items": items,
            "due_date": due,
            "status": "DRAFT",
            "review_note": None,
        }
    )
    db.action_plans[rec["id"]] = rec
    return success_object(helpers.ser_action_plan(rec), 201)


@bp.get("/survey/action-plans/<pid>")
@require_roles("PlatformAdmin", "RegionalManager", "FieldConsultant", "DealerPrincipal")
def get_action_plan(user_id, role, pid):
    rec = db.action_plans.get(pid)
    if rec is None:
        raise errors.not_found("ActionPlan not found")
    services.maybe_mark_overdue(rec)
    return success_object(helpers.ser_action_plan(rec))


def _list_plans(args, forced_dealer_id=None):
    limit, offset = parse_pagination(args)
    items = list(db.action_plans.values())
    for p in items:
        services.maybe_mark_overdue(p)
    dealer_id = forced_dealer_id or args.get("dealer_id")
    if dealer_id is not None:
        items = [p for p in items if p["dealer_id"] == dealer_id]
    for param in ("wave_id", "status"):
        v = args.get(param)
        if v is not None:
            items = [p for p in items if p.get(param) == v]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [helpers.ser_action_plan(p) for p in page], limit, offset, total
    )


@bp.get("/survey/action-plans")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "FieldConsultant",
    "ComplianceAuditor",
)
def list_action_plans(user_id, role):
    return _list_plans(request.args)


@bp.get("/survey/dealers/<did>/action-plans")
@require_roles("PlatformAdmin", "RegionalManager", "FieldConsultant", "DealerPrincipal")
def list_dealer_action_plans(user_id, role, did):
    if did not in db.dealers:
        raise errors.not_found("Dealer not found")
    return _list_plans(request.args, forced_dealer_id=did)


def _get_plan_for_transition(pid):
    rec = db.action_plans.get(pid)
    if rec is None:
        raise errors.not_found("ActionPlan not found")
    return rec


def _check_plan_ownership(user_id, plan):
    if plan["dealer_id"] != user_id:
        raise errors.forbidden()


@bp.post("/survey/action-plans/<pid>/submit")
@require_roles("DealerPrincipal")
def submit_action_plan(user_id, role, pid):
    rec = _get_plan_for_transition(pid)
    _check_plan_ownership(user_id, rec)
    if rec["status"] != "DRAFT":
        raise errors.invalid_state("ActionPlan is not DRAFT")
    dealer = db.dealers.get(rec["dealer_id"])
    if dealer is not None and dealer["posture"] == "SUSPENDED":
        raise errors.dealer_suspended()
    rec["status"] = "SUBMITTED"
    helpers.touch(rec)
    return success_object(helpers.ser_action_plan(rec))


@bp.post("/survey/action-plans/<pid>/review")
@require_roles("FieldConsultant")
def review_action_plan(user_id, role, pid):
    rec = _get_plan_for_transition(pid)
    if rec["status"] != "SUBMITTED":
        raise errors.invalid_state("ActionPlan is not SUBMITTED")
    data = _require(_body(), "outcome")
    outcome = data["outcome"]
    if outcome not in ("APPROVED", "REJECTED"):
        raise errors.invalid_request("outcome must be APPROVED or REJECTED")
    note = data.get("review_note")
    if not isinstance(note, str) or not note.strip():
        raise errors.invalid_request("review_note must be non-empty")
    rec["review_note"] = note
    rec["status"] = outcome
    helpers.touch(rec)
    return success_object(helpers.ser_action_plan(rec))


@bp.post("/survey/action-plans/<pid>/revise")
@require_roles("DealerPrincipal")
def revise_action_plan(user_id, role, pid):
    rec = _get_plan_for_transition(pid)
    _check_plan_ownership(user_id, rec)
    if rec["status"] != "REJECTED":
        raise errors.invalid_state("ActionPlan is not REJECTED")
    rec["status"] = "DRAFT"
    rec["review_note"] = None
    helpers.touch(rec)
    return success_object(helpers.ser_action_plan(rec))


@bp.post("/survey/action-plans/<pid>/start")
@require_roles("DealerPrincipal")
def start_action_plan(user_id, role, pid):
    rec = _get_plan_for_transition(pid)
    _check_plan_ownership(user_id, rec)
    if rec["status"] != "APPROVED":
        raise errors.invalid_state("ActionPlan is not APPROVED")
    rec["status"] = "IN_PROGRESS"
    helpers.touch(rec)
    return success_object(helpers.ser_action_plan(rec))


@bp.post("/survey/action-plans/<pid>/complete")
@require_roles("FieldConsultant")
def complete_action_plan(user_id, role, pid):
    rec = _get_plan_for_transition(pid)
    if rec["status"] != "IN_PROGRESS":
        raise errors.invalid_state("ActionPlan is not IN_PROGRESS")
    rec["status"] = "COMPLETED"
    helpers.touch(rec)
    return success_object(helpers.ser_action_plan(rec))
