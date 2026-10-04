"""CouncilReview creation and JitRequest routes."""
from flask import Blueprint

from constants import (
    BUDGET_CUT_MAX_PCT,
    JIT_DECISIONS,
    NON_TERMINAL_JIT_STATUSES,
    RECOMMENDATIONS,
    ROLE_APPLICANT,
    ROLE_COUNCIL_MEMBER,
    ROLE_GRANTS_OFFICER,
)
from db import STORE, new_entity, touch
from errors import fail
from serializers import council_review_json, jit_json
from services import expire_jit, get, jit_is_past_due
from util import (
    auth_context,
    get_body,
    ok_object,
    opt_num,
    opt_str,
    req_enum,
    req_int,
    req_list,
    req_str,
    require_owner,
    require_role,
)

bp = Blueprint("council_jit", __name__)


# ---------------------------------------------------------------------------
# CouncilReview
# ---------------------------------------------------------------------------
@bp.route("/grants/council-reviews", methods=["POST"])
def create_council_review():
    user_id, role = auth_context()
    require_role(role, (ROLE_COUNCIL_MEMBER,))
    body = get_body()
    application_id = req_str(body, "application_id")
    recommendation = req_enum(body, "recommendation", RECOMMENDATIONS)
    note = opt_str(body, "portfolio_balance_note")
    if recommendation == "FUND":
        priority = req_int(body, "priority_alignment_score", minimum=1, maximum=5)
    else:
        priority = None
        if body.get("priority_alignment_score") is not None:
            priority = req_int(body, "priority_alignment_score", minimum=1, maximum=5)
    app = get("applications", application_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "application not found")
    if app["status"] not in ("SCORED", "DEFERRED"):
        fail(
            "ERR_APPLICATION_NOT_SCORED",
            "council review requires SCORED or DEFERRED status",
        )
    review = new_entity()
    review.update(
        {
            "application_id": app["id"],
            "recommendation": recommendation,
            "priority_alignment_score": priority,
            "portfolio_balance_note": note,
            "recorded_by": user_id,
        }
    )
    STORE["council_reviews"][review["id"]] = review
    if recommendation == "FUND":
        app["status"] = "COUNCIL_REVIEWED"
    elif recommendation == "DEFER":
        app["status"] = "DEFERRED"
    else:
        app["status"] = "NOT_FUNDED"
    touch(app)
    return ok_object(council_review_json(review), 201)


# ---------------------------------------------------------------------------
# JitRequest
# ---------------------------------------------------------------------------
def _get_jit_or_404(jit_id):
    jit = get("jit_requests", jit_id)
    if jit is None:
        fail("ERR_JIT_REQUEST_NOT_FOUND", "JIT request not found")
    return jit


def _expire_if_past_due(jit):
    """Lazy window enforcement: any JIT op on a non-terminal request attempted
    past due_date expires the request (and the application) — PRD §3.8."""
    if jit["status"] in NON_TERMINAL_JIT_STATUSES and jit_is_past_due(jit):
        expire_jit(jit)
        fail("ERR_JIT_EXPIRED", "the logical clock is past the JIT due_date")


@bp.route("/grants/jit-requests/<jit_id>", methods=["GET"])
def get_jit(jit_id):
    auth_context()
    return ok_object(jit_json(_get_jit_or_404(jit_id)))


@bp.route("/grants/jit-requests/<jit_id>/submit-items", methods=["POST"])
def jit_submit_items(jit_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_APPLICANT,))
    jit = _get_jit_or_404(jit_id)
    app = get("applications", jit["application_id"])
    require_owner(app["applicant_id"] if app else None, user_id)
    body = get_body()
    items = req_list(body, "items_submitted", elem=str)
    _expire_if_past_due(jit)
    if jit["status"] not in ("ISSUED", "RETURNED"):
        fail("ERR_JIT_INVALID_STATE", "submit-items requires ISSUED or RETURNED")
    missing = [item for item in jit["required_items"] if item not in items]
    if missing:
        fail(
            "ERR_JIT_ITEM_MISSING",
            "items_submitted does not cover every required item: %s" % ", ".join(missing),
        )
    jit["submitted_items"] = list(items)
    jit["status"] = "SUBMITTED"
    touch(jit)
    return ok_object(jit_json(jit))


@bp.route("/grants/jit-requests/<jit_id>/adjudicate", methods=["POST"])
def jit_adjudicate(jit_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_GRANTS_OFFICER,))
    jit = _get_jit_or_404(jit_id)
    body = get_body()
    decision = req_enum(body, "decision", JIT_DECISIONS)
    cut = opt_num(body, "budget_cut_pct", minimum=0, maximum=BUDGET_CUT_MAX_PCT, default=0)
    opt_str(body, "return_reason")
    _expire_if_past_due(jit)
    if jit["status"] != "SUBMITTED":
        fail("ERR_JIT_INVALID_STATE", "adjudicate requires SUBMITTED status")
    if decision == "ACCEPT":
        jit["budget_cut_pct"] = cut
        jit["status"] = "ACCEPTED"
        touch(jit)
        app = get("applications", jit["application_id"])
        if app is not None and app["status"] == "JIT_PENDING":
            app["status"] = "JIT_COMPLETE"
            touch(app)
    else:
        jit["status"] = "RETURNED"
        touch(jit)
    return ok_object(jit_json(jit))
