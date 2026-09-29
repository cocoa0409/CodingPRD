"""Market plan endpoints (PRD SS3.2, SS3.3, SS3.9)."""
from decimal import Decimal

from flask import Blueprint

from constants import (
    ALL_ROLES,
    BLOCKED_REASONS,
    MANDATORY_DISCLOSURES,
    MARKET_BOARD,
    MARKET_CODES,
    RATING_BANDS,
    RATING_BOARDS,
    RESTRICTED_CODES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOCALIZATION_PRODUCER,
    SCOPE_TIERS,
    BUG_OPEN_STATUSES,
)
from db import base_row, fetch, insert, rows, touch
from derive import (
    bubble_title_to_cert,
    bubble_title_to_shipped,
    by_created,
    cancel_scheduled_sessions,
    effective_disclosure_set,
    governing_submission,
    nonretired_key_count,
    plan_bugs,
    plan_passes,
    plan_sessions,
    plan_units,
    recompute_plan_cost,
    recompute_plan_required,
    refresh_title,
    set_plan_effort,
    stricter,
    title_keys,
)
from errors import ApiError
from middleware import endpoint
from response import created, ok, paginated
from routehelp import arg, match_all
from serialize import market_plan_out, nk_market_plan
from validation import bad, json_body, opt_enum, opt_int, req_enum, req_id, req_int

bp = Blueprint("market_plans", __name__)

PRODUCERS = [ROLE_LOCALIZATION_PRODUCER]
COMPLIANCE = [ROLE_COMPLIANCE_OFFICER]


@bp.route("/market-plans", methods=["POST"])
@endpoint(PRODUCERS)
def create_market_plan():
    body = json_body()
    title_id = req_id(body, "title_id")
    market_code = req_enum(body, "market_code", MARKET_CODES)
    rating_board = req_enum(body, "rating_board", RATING_BOARDS)
    if rating_board != MARKET_BOARD[market_code]:
        bad("rating_board must be the board that governs market_code")
    target_rating = req_enum(body, "target_rating", RATING_BANDS)
    scope_tier = opt_enum(body, "scope_tier", SCOPE_TIERS, None)
    budget_cap_cents = req_int(body, "budget_cap_cents", 0)
    required_voice_line_count = opt_int(body, "required_voice_line_count", 0, None, 0)

    title = fetch("titles", title_id)

    if any(
        p["title_id"] == title_id and p["market_code"] == market_code
        for p in rows("market_plans")
    ):
        raise ApiError("ERR_DUPLICATE_MARKET_CODE")

    row = base_row()
    row.update({
        "title_id": title_id,
        "market_code": market_code,
        "rating_board": rating_board,
        "target_rating": target_rating,
        "scope_tier": scope_tier,
        "cultural_adaptation_required": scope_tier == "FULL_CULTURAL",
        "budget_cap_cents": budget_cap_cents,
        "status": "DRAFT",
        "blocked_reason": None,
        "required_unit_count": 0,
        "delivered_unit_count": 0,
        "required_voice_line_count": required_voice_line_count,
        "voice_recorded_line_count": 0,
        "text_effort_units": Decimal("0.00"),
        "text_effort_variant": None,
        "localization_cost_cents": 0,
        "overage_cents": 0,
    })
    insert("market_plans", row)
    row["required_unit_count"] = sum(
        1 for k in title_keys(title_id) if k["status"] == "LOCKED"
    )
    refresh_title(title)
    return created(market_plan_out(row))


@bp.route("/market-plans/<market_plan_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_market_plan(market_plan_id):
    return ok(market_plan_out(fetch("market_plans", market_plan_id)))


@bp.route("/market-plans", methods=["GET"])
@endpoint(ALL_ROLES)
def list_market_plans():
    pairs = [
        ("title_id", arg("title_id")),
        ("market_code", arg("market_code")),
        ("status", arg("status")),
        ("scope_tier", arg("scope_tier")),
    ]
    items = [p for p in rows("market_plans") if match_all(p, pairs)]
    return paginated(items, market_plan_out, nk_market_plan)


@bp.route("/market-plans/<market_plan_id>/scope", methods=["POST"])
@endpoint(PRODUCERS)
def scope_market_plan(market_plan_id):
    plan = fetch("market_plans", market_plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_MARKET_PLAN_STATE_INVALID")
    title = fetch("titles", plan["title_id"])
    if title["localization_state"] == "PLANNING":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "Scoping requires the owning title to have left PLANNING",
        )

    recompute_plan_required(plan, nonretired_key_count(plan))
    plan["status"] = "SCOPED"
    touch(plan)
    set_plan_effort(plan, "SCOPE_ESTIMATE")
    refresh_title(title)
    return ok(market_plan_out(plan))


@bp.route("/market-plans/<market_plan_id>/start-localization", methods=["POST"])
@endpoint(PRODUCERS)
def start_localization(market_plan_id):
    plan = fetch("market_plans", market_plan_id)
    if plan["status"] != "SCOPED":
        raise ApiError("ERR_MARKET_PLAN_STATE_INVALID")
    title = fetch("titles", plan["title_id"])
    if title["localization_state"] != "STRINGS_LOCKED":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The owning title must be STRINGS_LOCKED",
        )
    if plan["scope_tier"] in ("FULL_VOICE", "FULL_CULTURAL"):
        covered = any(
            c["status"] == "SIGNED"
            and c["title_id"] == title["id"]
            and plan["market_code"] in c["territory_scope"]
            for c in rows("talent_contracts")
        )
        if not covered:
            raise ApiError(
                "ERR_PREREQUISITE_STATE_NOT_MET",
                "A voiced tier requires a SIGNED contract covering this market",
            )

    locked = by_created([k for k in title_keys(title["id"]) if k["status"] == "LOCKED"])
    for key in locked:
        unit = base_row()
        unit.update({
            "string_key_id": key["id"],
            "market_plan_id": plan["id"],
            "target_text": None,
            "target_char_count": 0,
            "applied_tm_match_pct": None,
            "overflow_chars": 0,
            "translation_status": "PENDING",
            "qa_status": "NOT_CHECKED",
            "open_bug_count": 0,
        })
        insert("translation_units", unit)

    plan["status"] = "IN_LOCALIZATION"
    plan["required_unit_count"] = len(locked)
    plan["delivered_unit_count"] = 0
    touch(plan)
    refresh_title(title)
    return ok(market_plan_out(plan))


@bp.route("/market-plans/<market_plan_id>/enter-lqa", methods=["POST"])
@endpoint(PRODUCERS)
def enter_lqa(market_plan_id):
    plan = fetch("market_plans", market_plan_id)
    if plan["status"] != "IN_LOCALIZATION":
        raise ApiError("ERR_MARKET_PLAN_STATE_INVALID")
    if plan["required_unit_count"] < 1:
        raise ApiError(
            "ERR_LOCALIZATION_INCOMPLETE",
            "The plan must own at least one required translation unit",
        )
    if plan["delivered_unit_count"] != plan["required_unit_count"]:
        raise ApiError(
            "ERR_LOCALIZATION_INCOMPLETE",
            "Every required translation unit must be DELIVERED",
        )
    if plan["voice_recorded_line_count"] < plan["required_voice_line_count"]:
        raise ApiError(
            "ERR_LOCALIZATION_INCOMPLETE",
            "Recorded voice lines have not met the required quota",
        )

    plan["status"] = "LQA"
    touch(plan)
    set_plan_effort(plan, "DELIVERED_ACTUAL")
    title = fetch("titles", plan["title_id"])
    bubble_title_to_cert(title)
    return ok(market_plan_out(plan))


@bp.route("/market-plans/<market_plan_id>/mark-release-ready", methods=["POST"])
@endpoint(COMPLIANCE)
def mark_release_ready(market_plan_id):
    plan = fetch("market_plans", market_plan_id)
    if plan["status"] != "LQA":
        raise ApiError("ERR_MARKET_PLAN_STATE_INVALID")

    # rung 12 -- structural preconditions
    passes = plan_passes(plan["id"])
    if any(p["status"] != "CLOSED" for p in passes):
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET", "Every QA pass of the plan must be CLOSED"
        )
    if not any(p["pass_type"] == "LINGUISTIC" for p in passes):
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "At least one LINGUISTIC QA pass must exist",
        )
    title = fetch("titles", plan["title_id"])
    if title["release_gate_state"] == "BLOCKED":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET", "The title release gate is BLOCKED"
        )

    # rung 13 -- domain business rules, in the order SS3.9 declares for this gate
    governing = governing_submission(plan["id"])
    effective = set(effective_disclosure_set(governing)) if governing else set()

    for code in RESTRICTED_CODES[plan["market_code"]]:
        if code in effective:
            raise ApiError("ERR_CONTENT_RESTRICTION_UNRESOLVED")
    for code in MANDATORY_DISCLOSURES[plan["market_code"]]:
        if code not in effective:
            raise ApiError("ERR_MANDATORY_DISCLOSURE_MISSING")

    for unit in plan_units(plan["id"]):
        if unit["overflow_chars"] > 0 and unit["qa_status"] != "PASSED":
            raise ApiError("ERR_TEXT_OVERFLOW_UNRESOLVED")
    for bug in plan_bugs(plan["id"]):
        if bug["bug_class"] in ("TEXT_OVERFLOW", "TRUNCATION") and bug["status"] in BUG_OPEN_STATUSES:
            raise ApiError("ERR_TEXT_OVERFLOW_UNRESOLVED")

    if governing is None or governing["status"] != "RATED":
        raise ApiError(
            "ERR_RATING_BAND_MISMATCH",
            "The governing rating submission must be RATED",
        )
    assigned = governing["assigned_rating"]
    if assigned is None or stricter(assigned, plan["target_rating"]):
        raise ApiError("ERR_RATING_BAND_MISMATCH")

    if plan["overage_cents"] != 0:
        raise ApiError("ERR_BUDGET_OVERAGE")

    plan["status"] = "RELEASE_READY"
    touch(plan)
    refresh_title(title)
    bubble_title_to_shipped(title)
    return ok(market_plan_out(plan))


@bp.route("/market-plans/<market_plan_id>/block", methods=["POST"])
@endpoint(COMPLIANCE)
def block_market_plan(market_plan_id):
    body = json_body()
    blocked_reason = req_enum(body, "blocked_reason", BLOCKED_REASONS)

    plan = fetch("market_plans", market_plan_id)
    if plan["status"] not in ("SCOPED", "IN_LOCALIZATION", "LQA"):
        raise ApiError("ERR_MARKET_PLAN_STATE_INVALID")

    cancel_scheduled_sessions(plan_sessions(plan["id"]))

    plan["status"] = "BLOCKED"
    plan["blocked_reason"] = blocked_reason
    touch(plan)
    recompute_plan_cost(plan)

    # the title gate becomes BLOCKED because at least one plan is BLOCKED
    title = fetch("titles", plan["title_id"])
    refresh_title(title)
    return ok(market_plan_out(plan))
