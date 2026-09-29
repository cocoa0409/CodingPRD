"""Translation unit endpoints (PRD SS3.3)."""
from flask import Blueprint

from constants import (
    ALL_ROLES,
    QA_STATUSES,
    ROLE_LQA_TESTER,
    ROLE_TRANSLATION_VENDOR,
)
from db import fetch, rows, touch
from derive import apply_unit_text, recompute_plan_delivered
from errors import ApiError
from middleware import endpoint
from response import ok, paginated
from routehelp import arg, match_all
from serialize import nk_translation_unit, translation_unit_out
from validation import json_body, opt_int, opt_str, present, req_enum

bp = Blueprint("translation_units", __name__)

VENDORS = [ROLE_TRANSLATION_VENDOR]
TESTERS = [ROLE_LQA_TESTER]


@bp.route("/translation-units/<translation_unit_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_translation_unit(translation_unit_id):
    return ok(translation_unit_out(fetch("translation_units", translation_unit_id)))


@bp.route("/translation-units", methods=["GET"])
@endpoint(ALL_ROLES)
def list_translation_units():
    pairs = [
        ("market_plan_id", arg("market_plan_id")),
        ("string_key_id", arg("string_key_id")),
        ("translation_status", arg("translation_status")),
        ("qa_status", arg("qa_status")),
    ]
    items = [u for u in rows("translation_units") if match_all(u, pairs)]
    return paginated(items, translation_unit_out, nk_translation_unit)


@bp.route("/translation-units/<translation_unit_id>", methods=["PUT"])
@endpoint(VENDORS)
def write_target_text(translation_unit_id):
    body = json_body()
    if not present(body, "target_text"):
        from validation import bad
        bad("target_text is required")
    target_text = opt_str(body, "target_text", 1, 2000)
    opt_int(body, "target_char_count", 0)  # accepted, always re-derived server-side
    applied_tm_match_pct = opt_int(body, "applied_tm_match_pct", 0, 100)

    unit = fetch("translation_units", translation_unit_id)

    # rung 11 -- own state; a DELIVERED unit refuses further text writes
    if unit["translation_status"] == "DELIVERED":
        raise ApiError("ERR_UNIT_NOT_DELIVERED")
    plan = fetch("market_plans", unit["market_plan_id"])
    if plan["status"] != "IN_LOCALIZATION":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The owning market plan must be IN_LOCALIZATION",
        )

    apply_unit_text(unit, target_text)
    if applied_tm_match_pct is not None:
        unit["applied_tm_match_pct"] = applied_tm_match_pct
    unit["translation_status"] = "DRAFTED"
    touch(unit)
    return ok(translation_unit_out(unit))


@bp.route("/translation-units/<translation_unit_id>/deliver", methods=["POST"])
@endpoint(VENDORS)
def deliver_unit(translation_unit_id):
    body = json_body(required=False)
    applied_tm_match_pct = opt_int(body, "applied_tm_match_pct", 0, 100)

    unit = fetch("translation_units", translation_unit_id)
    if unit["translation_status"] != "DRAFTED":
        raise ApiError("ERR_UNIT_NOT_DELIVERED")
    plan = fetch("market_plans", unit["market_plan_id"])
    if plan["status"] != "IN_LOCALIZATION":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The owning market plan must be IN_LOCALIZATION",
        )

    if applied_tm_match_pct is not None:
        unit["applied_tm_match_pct"] = applied_tm_match_pct
    unit["translation_status"] = "DELIVERED"
    touch(unit)
    plan["delivered_unit_count"] = sum(
        1 for u in rows("translation_units")
        if u["market_plan_id"] == plan["id"] and u["translation_status"] == "DELIVERED"
    )
    touch(plan)
    return ok(translation_unit_out(unit))


@bp.route("/translation-units/<translation_unit_id>/qa-mark", methods=["POST"])
@endpoint(TESTERS)
def qa_mark_unit(translation_unit_id):
    body = json_body()
    qa_status = req_enum(body, "qa_status", QA_STATUSES)

    unit = fetch("translation_units", translation_unit_id)

    # cross-axis guard reported through the unit's own-state error
    if unit["translation_status"] != "DELIVERED":
        raise ApiError("ERR_UNIT_NOT_DELIVERED")
    if qa_status == "PASSED":
        if unit["open_bug_count"] != 0:
            raise ApiError(
                "ERR_UNIT_NOT_DELIVERED",
                "A unit with open defects may not be marked PASSED",
            )
        if unit["overflow_chars"] != 0:
            raise ApiError(
                "ERR_UNIT_NOT_DELIVERED",
                "A unit with overflow characters may not be marked PASSED",
            )

    unit["qa_status"] = qa_status
    touch(unit)
    return ok(translation_unit_out(unit))
