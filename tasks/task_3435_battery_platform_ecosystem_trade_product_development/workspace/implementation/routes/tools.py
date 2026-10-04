"""Tool models (development stages, launch gates) and research insights."""
from flask import Blueprint, request

import db
from constants import (
    API_PREFIX,
    INSIGHT_DECISIONS,
    INSIGHT_KINDS,
    INSIGHT_SEVERITIES,
    ROLES,
    TOOL_CATEGORIES,
    TOOL_STAGES,
    TOOL_TIERS,
    TRADES,
)
from errors import fail
from helpers import (
    authorize,
    body,
    check_enum,
    check_int,
    ok_list,
    ok_object,
    pagination,
    page_window,
    present,
    req_bool,
    req_field,
    req_int,
    req_num,
    req_str,
)
from services import (
    add_calendar_years,
    adopted_count,
    bump,
    end_tool_listings,
    make_entity,
    platform_current_generation,
    tool_best_runtime,
    tool_regulatory_count,
)
from views import view_insight, view_tool

bp = Blueprint("tools", __name__)

# Valid stage edges of the ToolModel state machine (DISCONTINUED is terminal).
TOOL_EDGES = {
    "CONCEPT": {"FIELD_RESEARCH", "DISCONTINUED"},
    "FIELD_RESEARCH": {"PROTOTYPE", "DISCONTINUED"},
    "PROTOTYPE": {"ENGINEERING_VALIDATION", "DISCONTINUED"},
    "ENGINEERING_VALIDATION": {"LAUNCHED", "PROTOTYPE", "DISCONTINUED"},
    "LAUNCHED": {"DISCONTINUED"},
    "DISCONTINUED": set(),
}


def _get_tool_or_404(tool_id):
    tool = db.STORE["tools"].get(tool_id)
    if tool is None:
        fail("ERR_NOT_FOUND", "Tool model not found")
    return tool


@bp.route(f"{API_PREFIX}/tool-models", methods=["POST"])
def create_tool():
    authorize(["ProductEngineer"])
    data = body()
    # Priority 4: platform FK existence
    platform_id = req_field(data, "platform_id")
    platform = db.STORE["platforms"].get(platform_id)
    if platform is None:
        fail("ERR_NOT_FOUND", "platform_id does not reference an existing platform")
    # Priority 5: request shape
    model_code = req_str(data, "model_code")
    check_enum(req_field(data, "trade"), "trade", TRADES)
    check_enum(req_field(data, "category"), "category", TOOL_CATEGORIES)
    check_enum(req_field(data, "tier"), "tier", TOOL_TIERS)
    corded_conversion = req_bool(data, "corded_conversion")
    avg_power_draw_w = req_num(data, "avg_power_draw_w", gt=0)
    runtime_target_min = None
    if corded_conversion:
        # runtime_target_min REQUIRED exactly when corded_conversion is true
        runtime_target_min = req_num(data, "runtime_target_min", gt=0)
    elif present(data, "runtime_target_min"):
        fail("ERR_VALIDATION", "runtime_target_min is forbidden unless corded_conversion")
    min_gen = req_int(data, "min_pack_generation", minimum=1)
    max_gen = req_int(data, "max_pack_generation", minimum=1)
    if max_gen < min_gen:
        fail("ERR_VALIDATION", "max_pack_generation must be >= min_pack_generation")
    replacement_price_cents = req_int(data, "replacement_price_cents", minimum=0)
    warranty_days = req_int(data, "warranty_days", gt=0, multiple_of=30)
    free_replacement_days = req_int(data, "free_replacement_days", minimum=0)
    if free_replacement_days > warranty_days:
        fail("ERR_VALIDATION", "free_replacement_days may not exceed warranty_days")
    torque_min_nm = req_num(data, "torque_min_nm", gt=0)
    torque_max_nm = req_num(data, "torque_max_nm", gt=0)
    if not torque_min_nm < torque_max_nm:
        fail("ERR_VALIDATION", "torque_min_nm must be strictly below torque_max_nm")
    # Priority 11: uniqueness of model_code
    for t in db.STORE["tools"].values():
        if t["model_code"] == model_code:
            fail("ERR_DUPLICATE_SKU", "A tool model with this model_code already exists")
    # Priority 12: forward-commitment ceiling
    ceiling = (
        platform_current_generation(platform["id"])
        + platform["forward_commitment_generations"]
    )
    if max_gen > ceiling:
        fail("ERR_FORWARD_COMMITMENT_EXCEEDED", "max_pack_generation exceeds the ceiling")
    # Priority 17: RETIRED platform blocks tool creation
    if platform["status"] == "RETIRED":
        fail("ERR_PLATFORM_RETIRED", "Platform is RETIRED")
    tool = make_entity(
        {
            "platform_id": platform["id"],
            "model_code": model_code,
            "trade": data["trade"],
            "category": data["category"],
            "tier": data["tier"],
            "corded_conversion": corded_conversion,
            "avg_power_draw_w": avg_power_draw_w,
            "runtime_target_min": runtime_target_min,
            "min_pack_generation": min_gen,
            "max_pack_generation": max_gen,
            "replacement_price_cents": replacement_price_cents,
            "warranty_days": warranty_days,
            "free_replacement_days": free_replacement_days,
            "torque_min_nm": torque_min_nm,
            "torque_max_nm": torque_max_nm,
            "stage": "CONCEPT",
        }
    )
    db.STORE["tools"][tool["id"]] = tool
    return ok_object(view_tool(tool), 201)


@bp.route(f"{API_PREFIX}/tool-models/<tool_id>", methods=["GET"])
def get_tool(tool_id):
    authorize(ROLES)
    return ok_object(view_tool(_get_tool_or_404(tool_id)))


@bp.route(f"{API_PREFIX}/tool-models", methods=["GET"])
def list_tools():
    authorize(ROLES)
    limit, offset = pagination()
    items = list(db.STORE["tools"].values())
    platform_id = request.args.get("platform_id")
    if platform_id is not None:
        items = [t for t in items if t["platform_id"] == platform_id]
    stage = request.args.get("stage")
    if stage is not None:
        items = [t for t in items if t["stage"] == stage]
    page, total = page_window(items, limit, offset)
    return ok_list([view_tool(t) for t in page], total, limit, offset)


@bp.route(f"{API_PREFIX}/tool-models/<tool_id>/transition", methods=["POST"])
def transition_tool(tool_id):
    authorize(["ProductEngineer"])
    tool = _get_tool_or_404(tool_id)
    data = body()
    # Priority 5: shape (enum membership + required OCC field)
    to_stage = check_enum(req_field(data, "to_stage"), "to_stage", TOOL_STAGES)
    expected = check_int(req_field(data, "expected_tool_model_version"),
                         "expected_tool_model_version")
    # Priority 6: valid from-state / stage edges
    if to_stage not in TOOL_EDGES[tool["stage"]]:
        fail("ERR_INVALID_STATE", f"Cannot transition {tool['stage']} -> {to_stage}")
    # Priority 8: optimistic concurrency
    if expected != tool["version"]:
        fail("ERR_STALE_VERSION", "expected_tool_model_version does not match")
    platform = db.STORE["platforms"][tool["platform_id"]]
    # Priority 13: tool development gates
    if tool["stage"] == "FIELD_RESEARCH" and to_stage == "PROTOTYPE":
        if adopted_count(tool["id"], "FIELD_RESEARCH") < 2:
            fail("ERR_INSUFFICIENT_FIELD_RESEARCH",
                 "Fewer than 2 adopted FIELD_RESEARCH insights")
    if tool["stage"] == "PROTOTYPE" and to_stage == "ENGINEERING_VALIDATION":
        if adopted_count(tool["id"], "JOBSITE_OBSERVATION") < 1:
            fail("ERR_INSUFFICIENT_FIELD_RESEARCH",
                 "No adopted JOBSITE_OBSERVATION insight")
    if to_stage == "LAUNCHED":
        if tool_regulatory_count(tool) < 1:
            fail("ERR_CERTIFICATION_REQUIRED", "REGULATORY compatibility set is empty")
        if tool["corded_conversion"]:
            best = tool_best_runtime(tool)
            if best is None or best < tool["runtime_target_min"]:
                fail("ERR_RUNTIME_TARGET_UNMET", "best_runtime_min below runtime_target_min")
        # Priority 17: RETIRED platform blocks launch
        if platform["status"] == "RETIRED":
            fail("ERR_PLATFORM_RETIRED", "Platform is RETIRED")
        # Priority 18: backward-commitment window
        if platform.get("sunset_date") is not None:
            horizon = add_calendar_years(
                db.clock_now().date(), platform["backward_commitment_years"]
            )
            if horizon > platform["sunset_date"].date():
                fail("ERR_BACKWARD_COMMITMENT_WINDOW_EXCEEDED",
                     "Launch plus backward commitment exceeds sunset_date")
    tool["stage"] = to_stage
    bump(tool)
    if to_stage == "DISCONTINUED":
        end_tool_listings(tool["id"])
    return ok_object(view_tool(tool))


@bp.route(f"{API_PREFIX}/tool-models/<tool_id>/insights", methods=["GET"])
def list_tool_insights(tool_id):
    authorize(ROLES)
    _get_tool_or_404(tool_id)
    limit, offset = pagination()
    items = [i for i in db.STORE["insights"].values() if i["tool_model_id"] == tool_id]
    page, total = page_window(items, limit, offset)
    return ok_list([view_insight(i) for i in page], total, limit, offset)


# ------------------------------------------------------------- insights ----
@bp.route(f"{API_PREFIX}/insights", methods=["POST"])
def create_insight():
    user_id, _ = authorize(["FieldResearcher"])
    data = body()
    tool_model_id = req_field(data, "tool_model_id")
    if db.STORE["tools"].get(tool_model_id) is None:
        fail("ERR_NOT_FOUND", "tool_model_id does not reference an existing tool")
    kind = check_enum(req_field(data, "kind"), "kind", INSIGHT_KINDS)
    summary = req_str(data, "summary")
    severity = check_enum(req_field(data, "severity"), "severity", INSIGHT_SEVERITIES)
    insight = make_entity(
        {
            "tool_model_id": tool_model_id,
            "kind": kind,
            "summary": summary,
            "severity": severity,
            "status": "SUBMITTED",
            "submitted_by_user_id": user_id,
        }
    )
    db.STORE["insights"][insight["id"]] = insight
    return ok_object(view_insight(insight), 201)


@bp.route(f"{API_PREFIX}/insights/<insight_id>/decide", methods=["POST"])
def decide_insight(insight_id):
    user_id, _ = authorize(["ProductEngineer"])
    insight = db.STORE["insights"].get(insight_id)
    if insight is None:
        fail("ERR_NOT_FOUND", "Research insight not found")
    data = body()
    decision = check_enum(req_field(data, "decision"), "decision", INSIGHT_DECISIONS)
    if insight["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Insight is not SUBMITTED")
    if user_id == insight["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "Decider must differ from the submitter")
    insight["status"] = decision
    bump(insight)
    if decision == "ADOPTED":
        # Adopted-count recompute trigger: bump the linked ToolModel version.
        bump(db.STORE["tools"][insight["tool_model_id"]])
    return ok_object(view_insight(insight))
