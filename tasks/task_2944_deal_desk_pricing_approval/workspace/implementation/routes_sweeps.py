"""Expiry sweep, SLA escalation sweep and the logical-clock endpoint.

PRD 3.8 (service levels, escalation and expiry) and PRD 2.5 (logical clock).
"""
from flask import Blueprint

import calc
import clock
import common
import db
import response
import workflow
from auth import require_roles
from validation import validate, json_body

bp = Blueprint("sweeps", __name__)

EXPIRABLE_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED")
UNSIGNED_STATUSES = ("GENERATED", "OUT_FOR_SIGNATURE")
VOID_QUOTE_EXPIRED = "QUOTE_EXPIRED"
MAX_TIER_LEVEL = 4


@bp.post("/expiry-sweeps")
@require_roles("PlatformAdmin")
def run_expiry_sweep():
    validate(json_body(), {})
    swept_at = clock.now()
    expired_quote_ids = []
    voided_order_form_ids = []
    released_exception_ids = []
    expired_grant_ids = []

    for quote in db.sorted_records(db.all_records("quotes")):
        if quote["status"] not in EXPIRABLE_STATUSES:
            continue
        if quote["expires_at"] is None or not swept_at > quote["expires_at"]:
            continue
        origin = quote["status"]
        if origin == "APPROVED":
            booked = any(
                f["status"] == "BOOKED" for f in db.order_forms_of_quote(quote["id"])
            )
            if booked:
                continue

        quote["status"] = "EXPIRED"
        db.touch(quote)
        expired_quote_ids.append(quote["id"])

        if origin == "DRAFT":
            workflow.withdraw_pending_terms(quote)
        elif origin == "PENDING_APPROVAL":
            request_row = db.open_request_of_quote(quote["id"])
            if request_row is not None and request_row["status"] == "OPEN":
                request_row["status"] = "EXPIRED"
                request_row["decided_at"] = swept_at
                request_row["total_turnaround_hours"] = calc.turnaround_hours(
                    request_row["submitted_at"], swept_at
                )
                if request_row["escalation_count"] > 0:
                    request_row["sla_state"] = "BREACHED"
                db.touch(request_row)
                workflow.void_pending_steps(request_row)
            workflow.withdraw_pending_terms(quote)
        else:
            for form in db.order_forms_of_quote(quote["id"]):
                if form["status"] not in UNSIGNED_STATUSES:
                    continue
                form["status"] = "VOID"
                form["voided_at"] = swept_at
                form["void_reason"] = VOID_QUOTE_EXPIRED
                db.touch(form)
                voided_order_form_ids.append(form["id"])

        released_exception_ids.extend(workflow.release_accepted_exceptions(quote))

    for grant in db.sorted_records(db.all_records("delegation_grants")):
        if grant["status"] != "ACTIVE":
            continue
        if swept_at < grant["ends_at"]:
            continue
        grant["status"] = "EXPIRED"
        db.touch(grant)
        expired_grant_ids.append(grant["id"])

    return response.ok({
        "swept_at": swept_at,
        "expired_quote_ids": expired_quote_ids,
        "expired_delegation_grant_ids": expired_grant_ids,
        "voided_order_form_ids": voided_order_form_ids,
        "released_exception_ids": released_exception_ids,
    })


@bp.post("/sla-escalation-sweeps")
@require_roles("PlatformAdmin")
def run_sla_escalation_sweep():
    validate(json_body(), {})
    swept_at = clock.now()
    escalated_step_ids = []
    created_step_ids = []
    breached_request_ids = []

    candidates = [
        s for s in db.sorted_records(db.all_records("approval_steps"))
        if s["decision"] == "PENDING"
    ]
    for step in candidates:
        if not swept_at > step["sla_due_at"]:
            continue
        request_row = db.get("approval_requests", step["approval_request_id"])
        if request_row is None:
            continue
        quote = db.quote(request_row["quote_id"])
        if quote is None or quote["status"] != "PENDING_APPROVAL":
            continue
        policy = common.policy_of(quote)

        step["decision"] = "ESCALATED"
        db.touch(step)
        escalated_step_ids.append(step["id"])

        request_row["escalation_count"] = int(request_row["escalation_count"]) + 1
        request_row["sla_state"] = "BREACHED"

        jump = 2 if step["in_surge_window"] else 1
        target = min(step["level"] + jump, MAX_TIER_LEVEL)
        replacement = workflow.create_step(
            request_row, policy, target, escalated_from_step_level=step["level"]
        )
        created_step_ids.append(replacement["id"])

        request_row["current_level"] = target
        if target > int(request_row["required_level"]):
            request_row["required_level"] = target
        if target == MAX_TIER_LEVEL:
            request_row["at_backstop"] = True
        db.touch(request_row)
        if request_row["id"] not in breached_request_ids:
            breached_request_ids.append(request_row["id"])

    return response.ok({
        "swept_at": swept_at,
        "escalated_step_ids": escalated_step_ids,
        "created_step_ids": created_step_ids,
        "breached_request_ids": breached_request_ids,
    })


CLOCK_SPEC = {"to_iso8601": {"type": "datetime", "required": True}}


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_logical_clock():
    body = validate(json_body(), CLOCK_SPEC)
    current = clock.set_now(body["to_iso8601"])
    return response.ok({"current_utc": current})
