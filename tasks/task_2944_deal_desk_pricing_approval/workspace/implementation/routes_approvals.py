"""Submission, approval requests, step decisions, reopen and renegotiate.

PRD 3.7 (submission and the two tracks), 3.8 (turnaround and renegotiation).
"""
from flask import Blueprint, request as flask_request

import auth
import calc
import clock
import common
import db
import response
import routes_quotes
import validation
import workflow
from auth import require_roles
from errors import fail
from validation import validate, json_body

bp = Blueprint("approvals", __name__)

ALL = auth.ALL_ROLES

AUTO_APPROVED_NOTE = "AUTO_APPROVED_BELOW_RISK_THRESHOLD"
MAX_TIER_LEVEL = 4


# ---- submit ----------------------------------------------------------------

@bp.post("/quotes/<quote_id>/submit")
@require_roles("SalesRep")
def submit_quote(quote_id):
    quote = common.must_get("quotes", quote_id)
    validate(json_body(), {})
    common.require_owner(quote)
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_NOT_DRAFT")
    common.require_not_expired(quote)

    policy = common.policy_of(quote)
    lines = db.lines_of_quote(quote_id)

    # structural gates, in the fixed sequence of PRD 3.7
    if not lines:
        fail("ERR_QUOTE_HAS_NO_LINES")
    if policy["status"] != "ACTIVE":
        fail("ERR_DESK_POLICY_SUPERSEDED")
    minimum_term = 0
    for line in lines:
        product = db.product(line["product_id"])
        if product is not None and int(product["min_term_months"]) > minimum_term:
            minimum_term = int(product["min_term_months"])
    if int(quote["term_months"]) < minimum_term:
        fail("ERR_TERM_BELOW_PRODUCT_MINIMUM")
    if int(quote["payment_terms_days"]) > int(policy["standard_payment_terms_days"]):
        covered = False
        for term in db.terms_of_quote(quote_id):
            if term["term_category"] != "PAYMENT_TERMS":
                continue
            if term["review_state"] not in ("PENDING", "APPROVED"):
                continue
            if calc.dec(term["requested_numeric_value"]) == calc.dec(quote["payment_terms_days"]):
                covered = True
                break
        if not covered:
            fail("ERR_NONSTANDARD_TERM_REQUIRED")

    priced = workflow.compute_pricing(quote, policy=policy, lines=lines)
    if priced["arrangement_type"] != "SINGLE_ELEMENT":
        cleared = any(
            a["status"] == "CLEARED" for a in db.assessments_of_quote(quote_id)
        )
        if not cleared:
            fail("ERR_REVREC_NOT_CLEARED")

    final_margin = priced["final_margin_pct"]
    if final_margin < calc.dec(policy["absolute_margin_floor_pct"]):
        fail("ERR_ABSOLUTE_MARGIN_FLOOR_BREACH")
    if final_margin < calc.dec(policy["margin_floor_pct"]):
        rescued = any(
            e["status"] == "ACCEPTED" for e in db.exceptions_of_quote(quote_id)
        )
        if not rescued:
            fail("ERR_MARGIN_FLOOR_BREACH")

    # every precondition passed: reprice and enter approval
    workflow.reprice(quote, policy)
    workflow.rescore_quote_terms(quote, policy)
    instant = clock.now()
    quote["submitted_at"] = instant
    quote["pinned_policy_version"] = policy["version"]
    quote["status"] = "PENDING_APPROVAL"
    db.touch(quote)

    cfo_threshold = calc.dec(policy["terms_cfo_risk_threshold"])
    review_threshold = calc.dec(policy["terms_review_risk_threshold"])
    required_level = quote["required_approval_level"]

    request_row = {
        "quote_id": quote_id,
        "required_level": required_level,
        "current_level": 0,
        "discount_track_state": "NOT_REQUIRED" if required_level == 0 else "PENDING",
        "terms_track_state": "NOT_REQUIRED",
        "status": "OPEN",
        "escalation_count": 0,
        "at_backstop": False,
        "sla_state": "ON_TRACK",
        "requires_cfo_cosign": calc.dec(quote["terms_risk_score_dominant"]) >= cfo_threshold,
        "submitted_at": instant,
        "decided_at": None,
        "total_turnaround_hours": None,
    }
    db.insert("approval_requests", request_row)
    db.mark_fresh(request_row)

    pending_terms = [
        t for t in db.terms_of_quote(quote_id) if t["review_state"] == "PENDING"
    ]
    if pending_terms:
        if calc.dec(quote["terms_risk_score_aggregate"]) >= review_threshold:
            request_row["terms_track_state"] = "PENDING_LEGAL"
        else:
            for term in pending_terms:
                term["review_state"] = "APPROVED"
                term["reviewed_at"] = instant
                term["reviewed_by_user_id"] = None
                term["reviewer_note"] = AUTO_APPROVED_NOTE
                db.touch(term)
            request_row["terms_track_state"] = "NOT_REQUIRED"

    if request_row["discount_track_state"] == "PENDING":
        workflow.create_step(request_row, policy, 1)
        request_row["current_level"] = 1

    workflow.try_join(request_row, quote, policy)
    return response.ok(quote)


@bp.get("/quotes/<quote_id>/approval-requests")
@require_roles(ALL)
def list_approval_requests(quote_id):
    common.must_get("quotes", quote_id)
    window, total, limit, offset = validation.paginate(db.requests_of_quote(quote_id))
    return response.listing(window, total, limit, offset)


# ---- approval steps --------------------------------------------------------

@bp.get("/approval-steps")
@require_roles(ALL)
def list_approval_steps():
    rows = db.sorted_records(db.all_records("approval_steps"))
    for field in ("approval_request_id", "delegation_grant_id", "decision"):
        value = flask_request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    window, total, limit, offset = validation.paginate(rows)
    return response.listing(window, total, limit, offset)


@bp.get("/approval-steps/<step_id>")
@require_roles(ALL)
def read_approval_step(step_id):
    return response.ok(common.must_get("approval_steps", step_id))


STEP_DECIDE_SPEC = {
    "decision": {
        "type": "enum",
        "required": True,
        "values": ("APPROVE", "REJECT", "REQUEST_CHANGES"),
    },
    "decision_note": {"type": "string"},
}


def _resolve_delegation(step, quote, policy):
    """PRD 2.10: owned authority, else the four narrowing delegation checks."""
    if auth.current_role() == step["assigned_role"]:
        return None

    user_id = auth.current_user_id()
    candidates = [
        g for g in db.sorted_records(db.all_records("delegation_grants"))
        if g["grantee_user_id"] == user_id and g["tier_level"] == step["level"]
    ]
    if not candidates:
        fail(
            "ERR_APPROVER_ROLE_MISMATCH",
            "The acting user holds neither the step's assigned_role nor a matching grant.",
        )

    band = db.tier_at_level(policy["id"], step["level"])
    if band is not None and int(band["max_delegation_levels"]) == 0:
        fail("ERR_DELEGATION_LEVEL_NOT_DELEGABLE")

    now = clock.now()
    live = [
        g for g in candidates
        if g["status"] == "ACTIVE" and g["starts_at"] <= now < g["ends_at"]
    ]
    if not live:
        fail("ERR_DELEGATION_NOT_ACTIVE")

    blended = calc.dec(quote["final_blended_discount_pct"])
    for grant in live:
        if blended <= calc.dec(grant["max_discount_pct"]):
            return grant
    fail("ERR_DELEGATION_SCOPE_EXCEEDED")


@bp.post("/approval-steps/<step_id>/decide")
@require_roles("DealDeskAnalyst", "SalesDirector", "VPSales", "CFO")
def decide_approval_step(step_id):
    step = common.must_get("approval_steps", step_id)
    body = validate(json_body(), STEP_DECIDE_SPEC)
    request_row = db.get("approval_requests", step["approval_request_id"])
    quote = db.quote(request_row["quote_id"])
    policy = common.policy_of(quote)

    if step["decision"] != "PENDING":
        fail("ERR_STEP_ALREADY_DECIDED")
    if quote["status"] != "PENDING_APPROVAL":
        fail("ERR_QUOTE_NOT_PENDING_APPROVAL")
    if auth.current_user_id() == quote["owner_rep_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The quote owner may not decide its approval steps.")
    grant = _resolve_delegation(step, quote, policy)
    common.require_not_expired(quote)

    decided_at = clock.now()
    step["acting_user_id"] = auth.current_user_id()
    step["decided_at"] = decided_at
    step["turnaround_hours"] = calc.turnaround_hours(step["created_at"], decided_at)
    step["decision_note"] = body.get("decision_note")
    if grant is not None:
        step["delegation_grant_id"] = grant["id"]
        grant["used_step_count"] = int(grant["used_step_count"]) + 1
        db.touch(grant)

    decision = body["decision"]
    if decision == "APPROVE":
        step["decision"] = "APPROVED"
        db.touch(step)
        if step["level"] < request_row["required_level"]:
            next_level = step["level"] + 1
            workflow.create_step(request_row, policy, next_level)
            request_row["current_level"] = next_level
            db.touch(request_row)
        else:
            request_row["discount_track_state"] = "CLEARED"
            db.touch(request_row)
            workflow.try_join(request_row, quote, policy)
    elif decision == "REJECT":
        step["decision"] = "REJECTED"
        db.touch(step)
        request_row["discount_track_state"] = "BLOCKED"
        db.touch(request_row)
        workflow.reject_request(request_row, quote)
    else:
        step["decision"] = "CHANGES_REQUESTED"
        db.touch(step)
        request_row["status"] = "CHANGES_REQUESTED"
        db.touch(request_row)
        quote["status"] = "CHANGES_REQUESTED"
        db.touch(quote)
    return response.ok(step)


# ---- reopen ----------------------------------------------------------------

@bp.post("/quotes/<quote_id>/reopen")
@require_roles("SalesRep")
def reopen_quote(quote_id):
    quote = common.must_get("quotes", quote_id)
    validate(json_body(), {})
    common.require_owner(quote)
    if quote["status"] != "CHANGES_REQUESTED":
        fail("ERR_QUOTE_NOT_CHANGES_REQUESTED")
    common.require_not_expired(quote)

    quote["status"] = "DRAFT"
    quote["revision_count"] = int(quote["revision_count"]) + 1
    quote["submitted_at"] = None
    quote["approved_at"] = None
    quote["policy_revalidation_required"] = False
    db.touch(quote)

    request_row = db.open_request_of_quote(quote_id)
    if request_row is not None and request_row["status"] == "CHANGES_REQUESTED":
        request_row["status"] = "CANCELLED"
        request_row["decided_at"] = clock.now()
        request_row["total_turnaround_hours"] = calc.turnaround_hours(
            request_row["submitted_at"], request_row["decided_at"]
        )
        db.touch(request_row)
        workflow.void_pending_steps(request_row)

    for term in db.terms_of_quote(quote_id):
        if term["review_state"] != "APPROVED":
            continue
        term["review_state"] = "PENDING"
        term["reviewed_by_user_id"] = None
        term["reviewed_at"] = None
        term["reviewer_note"] = None
        term["cfo_cosigned_at"] = None
        term["cfo_cosigned_by_user_id"] = None
        db.touch(term)

    workflow.stale_assessments(quote)
    return response.ok(quote)


# ---- renegotiate -----------------------------------------------------------

RENEGOTIATE_SPEC = {
    "expected_quote_version": {"type": "integer", "required": True},
    "term_months": {"type": "integer", "ge": 1, "le": 60},
    "payment_terms_days": {"type": "integer", "ge": 1, "le": 180},
    "billing_frequency": {
        "type": "enum",
        "values": ("ANNUAL", "SEMI_ANNUAL", "QUARTERLY", "MONTHLY"),
    },
}


@bp.post("/quotes/<quote_id>/renegotiate")
@require_roles("SalesRep")
def renegotiate_quote(quote_id):
    source = common.must_get("quotes", quote_id)
    body = validate(json_body(), RENEGOTIATE_SPEC)
    common.require_owner(source)
    if body["expected_quote_version"] != source["version"]:
        fail("ERR_STALE_QUOTE_VERSION", "expected_quote_version does not match the quote.")

    policy = common.policy_of(source)
    clone = routes_quotes.new_quote_record(
        source["account_id"],
        source["title"],
        body.get("term_months", source["term_months"]),
        body.get("payment_terms_days", source["payment_terms_days"]),
        body.get("billing_frequency", source["billing_frequency"]),
        policy,
        auth.current_user_id(),
        renegotiated_from_quote_id=source["id"],
    )

    for line in db.lines_of_quote(source["id"]):
        copy = {
            "quote_id": clone["id"],
            "product_id": line["product_id"],
            "quantity": line["quantity"],
            "requested_discount_pct": line["requested_discount_pct"],
            "unit_list_price_cents": line["unit_list_price_cents"],
            "unit_cost_cents": line["unit_cost_cents"],
            "rev_rec_category": line["rev_rec_category"],
            "extended_list_cents": 0,
            "extended_cost_cents": 0,
            "provisional_net_cents": 0,
            "final_net_cents": 0,
            "volume_tier_level_applied": 0,
            "bundle_discount_applied_pct": calc.rhu(0, 6),
            "effective_stack_discount_pct": calc.rhu(0, 6),
        }
        db.insert("quote_lines", copy)
        db.mark_fresh(copy)
    workflow.reprice(clone, policy)

    for other in db.sorted_records(db.all_records("quotes")):
        if other["id"] == clone["id"]:
            continue
        if other.get("renegotiated_from_quote_id") != source["id"]:
            continue
        if other["status"] != "DRAFT":
            continue
        other["status"] = "SUPERSEDED"
        db.touch(other)

    source["renegotiation_count"] = int(source["renegotiation_count"]) + 1
    db.touch(source)
    return response.created(clone)
