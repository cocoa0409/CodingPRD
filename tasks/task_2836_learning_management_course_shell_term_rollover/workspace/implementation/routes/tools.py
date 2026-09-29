"""Third-party tool governance: integrations and reviews -- PRD 3.7."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import db, mark, new_immutable, new_record, set_field
from errors import require
from middleware import (ACCESSIBILITY_REVIEWER, INSTRUCTOR, LMS_ADMIN,
                        PRIVACY_REVIEWER, actor, as_decimal, as_enum, as_int,
                        as_str, bad, body, role)
from routes.common import apply_filters, created, guard, listing, ok
from services import cascade, compute

bp = Blueprint("tools", __name__)

SCOPES = ("NONE", "ROSTER_ONLY", "ROSTER_AND_GRADES", "FULL_PROFILE")
WCAG_LEVELS = ("NONE", "A", "AA", "AAA")
DIMENSIONS = ("PRIVACY", "ACCESSIBILITY")
DECISIONS = ("CLEAR", "CONDITIONS", "BLOCK")
ACTIONS = ("OPEN_REVIEW", "FINALIZE_REVIEW", "SUSPEND", "REOPEN_REVIEW")
DEFAULT_SUSPENSION_REASON = "privacy incident"
REJECTED_PLACEMENT_REASON = "tool rejected"
SUSPENDED_PLACEMENT_REASON = "tool suspended"
DIMENSION_ROLE = {"PRIVACY": PRIVACY_REVIEWER,
                  "ACCESSIBILITY": ACCESSIBILITY_REVIEWER}
DIMENSION_FIELD = {"PRIVACY": "privacy_review_state",
                   "ACCESSIBILITY": "accessibility_review_state"}
DECISION_STATE = {"CLEAR": "CLEARED", "CONDITIONS": "CONDITIONAL",
                  "BLOCK": "BLOCKED"}
ZERO = Decimal("0.00")


@bp.post("/tool-integrations")
def create_tool():
    guard(LMS_ADMIN)
    payload = body()
    vendor_name = as_str(payload, "vendor_name", required=True)
    tool_name = as_str(payload, "tool_name", required=True)
    tool_version = as_str(payload, "tool_version", required=True)
    scope = as_enum(payload, "data_sharing_scope", SCOPES, required=True)
    pii_tier = as_int(payload, "pii_tier", default=0, low=0, high=3)
    vpat_score = as_decimal(payload, "vpat_score", default=Decimal("100.00"),
                            low=0, high=100)
    wcag_level = as_enum(payload, "wcag_level", WCAG_LEVELS, default="AA")

    duplicate = [t for t in db.tools.values()
                 if t["vendor_name"] == vendor_name and t["tool_name"] == tool_name]
    require(not duplicate, "ERR_DUPLICATE_TOOL",
            "This vendor already has a tool registered under that name.")

    tool = new_record(
        _kind="tool",
        vendor_name=vendor_name,
        tool_name=tool_name,
        tool_version=tool_version,
        data_sharing_scope=scope,
        pii_tier=pii_tier,
        vpat_score=vpat_score,
        wcag_level=wcag_level,
        privacy_review_state="PENDING",
        accessibility_review_state="PENDING",
        approval_state="DRAFT",
        risk_score=None,
        approved_version=None,
        active_placement_count=0,
        suspension_reason=None,
        _review_round=1,
    )
    db.tools[tool["id"]] = tool
    return created(tool)


@bp.get("/tool-integrations")
def list_tools():
    guard(LMS_ADMIN, PRIVACY_REVIEWER, ACCESSIBILITY_REVIEWER, INSTRUCTOR)
    records = apply_filters(db.tools.values(), {
        "vendor_name": "vendor_name",
        "approval_state": "approval_state",
        "data_sharing_scope": "data_sharing_scope",
    })
    return listing(records)


@bp.get("/tool-integrations/<tool_id>")
def read_tool(tool_id):
    guard(LMS_ADMIN, PRIVACY_REVIEWER, ACCESSIBILITY_REVIEWER, INSTRUCTOR)
    return ok(lookup.tool(tool_id))


@bp.patch("/tool-integrations/<tool_id>")
def update_tool(tool_id):
    guard(LMS_ADMIN)
    tool = lookup.tool(tool_id)
    payload = body()
    tool_version = as_str(payload, "tool_version")
    scope = as_enum(payload, "data_sharing_scope", SCOPES)
    pii_tier = as_int(payload, "pii_tier", low=0, high=3)
    vpat_score = as_decimal(payload, "vpat_score", low=0, high=100)
    wcag_level = as_enum(payload, "wcag_level", WCAG_LEVELS)
    if tool_version is not None:
        set_field(tool, "tool_version", tool_version)
    if scope is not None:
        set_field(tool, "data_sharing_scope", scope)
    if pii_tier is not None:
        set_field(tool, "pii_tier", pii_tier)
    if vpat_score is not None:
        set_field(tool, "vpat_score", vpat_score)
    if wcag_level is not None:
        set_field(tool, "wcag_level", wcag_level)
    mark(tool)
    return ok(tool)


@bp.post("/tool-integrations/<tool_id>/transitions")
def drive_tool(tool_id):
    guard(LMS_ADMIN)
    tool = lookup.tool(tool_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared tool action." % action)
    reason = as_str(payload, "reason")
    state = tool["approval_state"]

    if action == "OPEN_REVIEW":
        require(state == "DRAFT", "ERR_INVALID_STATE_TRANSITION",
                "OPEN_REVIEW runs from DRAFT, not from %s." % state)
        require(tool["privacy_review_state"] == "PENDING"
                and tool["accessibility_review_state"] == "PENDING",
                "ERR_INVALID_STATE_TRANSITION",
                "Both verdict dimensions must be PENDING to open a review.")
        set_field(tool, "approval_state", "UNDER_REVIEW")
        mark(tool)
        return ok(tool)

    if action == "FINALIZE_REVIEW":
        require(state == "UNDER_REVIEW", "ERR_INVALID_STATE_TRANSITION",
                "FINALIZE_REVIEW runs from UNDER_REVIEW, not from %s." % state)
        require(tool["privacy_review_state"] != "PENDING"
                and tool["accessibility_review_state"] != "PENDING",
                "ERR_REVIEW_INCOMPLETE",
                "Both verdict dimensions must have left PENDING.")
        compute.rescore_tool(tool)
        score = tool["risk_score"]
        blocked = ("BLOCKED" in (tool["privacy_review_state"],
                                 tool["accessibility_review_state"]))
        if blocked or score >= compute.RISK_REJECT_AT:
            set_field(tool, "approval_state", "REJECTED")
            set_field(tool, "approved_version", None)
            mark(tool)
            cascade.block_tool_placements(tool, REJECTED_PLACEMENT_REASON)
            return ok(tool)
        both_cleared = (tool["privacy_review_state"] == "CLEARED"
                        and tool["accessibility_review_state"] == "CLEARED")
        if both_cleared and score < compute.RISK_APPROVE_BELOW:
            set_field(tool, "approval_state", "APPROVED")
        else:
            set_field(tool, "approval_state", "CONDITIONAL")
        set_field(tool, "approved_version", tool["tool_version"])
        mark(tool)
        return ok(tool)

    if action == "SUSPEND":
        require(state in ("APPROVED", "CONDITIONAL"),
                "ERR_INVALID_STATE_TRANSITION",
                "SUSPEND runs from APPROVED or CONDITIONAL, not from %s." % state)
        set_field(tool, "approval_state", "SUSPENDED")
        set_field(tool, "suspension_reason",
                  reason if reason else DEFAULT_SUSPENSION_REASON)
        mark(tool)
        cascade.block_tool_placements(tool, SUSPENDED_PLACEMENT_REASON)
        return ok(tool)

    require(state == "SUSPENDED", "ERR_INVALID_STATE_TRANSITION",
            "REOPEN_REVIEW runs from SUSPENDED, not from %s." % state)
    set_field(tool, "approval_state", "UNDER_REVIEW")
    set_field(tool, "privacy_review_state", "PENDING")
    set_field(tool, "accessibility_review_state", "PENDING")
    set_field(tool, "approved_version", None)
    tool["_review_round"] = tool.get("_review_round", 1) + 1
    mark(tool)
    return ok(tool)


@bp.post("/tool-reviews")
def create_review():
    guard(PRIVACY_REVIEWER, ACCESSIBILITY_REVIEWER)
    payload = body()
    declared = payload.get("dimension")
    if declared in DIMENSIONS:
        require(DIMENSION_ROLE[declared] == role(), "ERR_ROLE_NOT_PERMITTED",
                "A %s may not file the %s verdict." % (role(), declared))
    tool = lookup.fk(payload, "tool_id", "tools")
    if tool is None:
        as_str(payload, "tool_id", required=True)
    dimension = as_enum(payload, "dimension", DIMENSIONS, required=True)
    decision = as_enum(payload, "decision", DECISIONS, required=True)
    conditions_note = as_str(payload, "conditions_note")
    if decision == "CONDITIONS" and not conditions_note:
        bad("conditions_note", "is required when the decision is CONDITIONS")

    require(tool["approval_state"] == "UNDER_REVIEW",
            "ERR_INVALID_STATE_TRANSITION",
            "A tool in %s does not accept a review." % tool["approval_state"])

    round_no = tool.get("_review_round", 1)
    current = [r for r in db.reviews.values()
               if r["tool_id"] == tool["id"] and r.get("_round") == round_no]
    other = [r for r in current if r["dimension"] != dimension]
    require(all(r["reviewer_user_id"] != actor() for r in other),
            "ERR_SEGREGATION_OF_DUTIES",
            "The two review dimensions must be decided by two different people.")
    require(not [r for r in current if r["dimension"] == dimension],
            "ERR_REVIEW_DIMENSION_CONFLICT",
            "This tool already holds a %s review in this round." % dimension)

    review = new_immutable(
        _kind="review",
        tool_id=tool["id"],
        dimension=dimension,
        decision=decision,
        reviewer_user_id=actor(),
        conditions_note=conditions_note,
        _round=round_no,
    )
    db.reviews[review["id"]] = review
    set_field(tool, DIMENSION_FIELD[dimension], DECISION_STATE[decision])
    mark(tool)
    return created(review)


@bp.get("/tool-reviews")
def list_reviews():
    guard(LMS_ADMIN, PRIVACY_REVIEWER, ACCESSIBILITY_REVIEWER)
    records = apply_filters(db.reviews.values(), {
        "tool_id": "tool_id",
        "dimension": "dimension",
        "decision": "decision",
    })
    return listing(records)


@bp.get("/tool-reviews/<review_id>")
def read_review(review_id):
    guard(LMS_ADMIN, PRIVACY_REVIEWER, ACCESSIBILITY_REVIEWER)
    return ok(lookup.review(review_id))
