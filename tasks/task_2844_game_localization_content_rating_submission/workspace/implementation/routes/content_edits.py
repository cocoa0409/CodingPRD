"""Content edit endpoints and the seven-hop apply cascade (PRD SS3.8)."""
from flask import Blueprint

from constants import (
    ALL_ROLES,
    CONTENT_DESCRIPTORS,
    EDIT_KINDS,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOCALIZATION_PRODUCER,
)
from db import base_row, db, fetch, insert, rows, touch
from derive import (
    by_created,
    pass_bugs,
    plan_units,
    recompute_pass_density,
    recompute_plan_cost,
    recompute_plan_delivered,
    recompute_plan_required,
    recompute_unit_open_bugs,
    revert_plan_from_lqa,
    plan_passes,
)
from errors import ApiError
from middleware import endpoint
from response import created, ok, paginated
from routehelp import arg, match_all
from serialize import content_edit_out, nk_content_edit
from validation import (
    bad,
    json_body,
    opt_enum_list,
    opt_id_list,
    req_enum,
    req_id,
    req_str,
)

bp = Blueprint("content_edits", __name__)

PROPOSERS = [ROLE_COMPLIANCE_OFFICER, ROLE_LOCALIZATION_PRODUCER]
COMPLIANCE = [ROLE_COMPLIANCE_OFFICER]


def _resolve_keys(key_ids, title_id):
    """Rung 5 existence then rung 6 same-title coherence, in list order."""
    resolved = []
    for key_id in key_ids:
        key = fetch("string_keys", key_id)
        if key["title_id"] != title_id:
            raise ApiError("ERR_CROSS_PARENT_MISMATCH")
        resolved.append(key)
    return resolved


@bp.route("/content-edits", methods=["POST"])
@endpoint(PROPOSERS)
def create_content_edit():
    body = json_body()
    rating_submission_id = req_id(body, "rating_submission_id")
    edit_kind = req_enum(body, "edit_kind", EDIT_KINDS)
    rationale = req_str(body, "rationale", 1, 500)
    affected = opt_id_list(body, "affected_string_key_ids")
    removed = opt_enum_list(body, "removed_content_codes", CONTENT_DESCRIPTORS)

    submission = fetch("rating_submissions", rating_submission_id)
    plan = fetch("market_plans", submission["market_plan_id"])
    _resolve_keys(affected, plan["title_id"])

    disclosed = set(submission["disclosed_content_codes"])
    for code in removed:
        if code not in disclosed:
            bad("removed_content_codes must be a subset of disclosed_content_codes")

    if submission["status"] != "EDITS_REQUIRED":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The rating submission must be EDITS_REQUIRED",
        )

    row = base_row()
    row.update({
        "rating_submission_id": rating_submission_id,
        "edit_kind": edit_kind,
        "affected_string_key_ids": list(affected),
        "removed_content_codes": list(removed),
        "rationale": rationale,
        "status": "PROPOSED",
        "invalidated_unit_count": 0,
        "applied_at_utc": None,
    })
    insert("content_edits", row)
    return created(content_edit_out(row))


@bp.route("/content-edits/<content_edit_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_content_edit(content_edit_id):
    return ok(content_edit_out(fetch("content_edits", content_edit_id)))


@bp.route("/content-edits", methods=["GET"])
@endpoint(ALL_ROLES)
def list_content_edits():
    pairs = [
        ("rating_submission_id", arg("rating_submission_id")),
        ("edit_kind", arg("edit_kind")),
        ("status", arg("status")),
    ]
    items = [e for e in rows("content_edits") if match_all(e, pairs)]
    return paginated(items, content_edit_out, nk_content_edit)


@bp.route("/content-edits/<content_edit_id>/apply", methods=["POST"])
@endpoint(COMPLIANCE)
def apply_content_edit(content_edit_id):
    edit = fetch("content_edits", content_edit_id)
    if edit["status"] != "PROPOSED":
        raise ApiError("ERR_CONTENT_EDIT_NOT_PROPOSED")

    submission = fetch("rating_submissions", edit["rating_submission_id"])
    if submission["status"] not in ("EDITS_REQUIRED", "RATED"):
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The rating submission must be EDITS_REQUIRED or RATED",
        )

    plan = fetch("market_plans", submission["market_plan_id"])
    keys = _resolve_keys(edit["affected_string_key_ids"], plan["title_id"])
    affected_ids = set(edit["affected_string_key_ids"])

    # hop 2 -- revert every drafted or delivered unit of this plan
    reverted_unit_ids = []
    undelivered = 0
    for unit in by_created(plan_units(plan["id"])):
        if unit["string_key_id"] not in affected_ids:
            continue
        if unit["translation_status"] not in ("DRAFTED", "DELIVERED"):
            continue
        if unit["translation_status"] == "DELIVERED":
            undelivered += 1
        unit["translation_status"] = "PENDING"
        unit["qa_status"] = "NOT_CHECKED"
        unit["target_text"] = None
        unit["target_char_count"] = 0
        unit["overflow_chars"] = 0
        unit["applied_tm_match_pct"] = None
        touch(unit)
        reverted_unit_ids.append(unit["id"])

    # hop 1 -- the edit itself carries the count reverted by hop 2
    edit["status"] = "APPLIED"
    edit["applied_at_utc"] = db.now()
    edit["invalidated_unit_count"] = len(reverted_unit_ids)
    touch(edit)

    recompute_plan_delivered(plan)

    # hop 3 -- REMOVE_CONTENT retires the affected locked keys
    if edit["edit_kind"] == "REMOVE_CONTENT":
        retired = False
        for key in by_created(keys):
            if key["status"] == "LOCKED":
                key["status"] = "RETIRED"
                touch(key)
                retired = True
        if retired:
            recompute_plan_required(plan)

    # hops 4, 5 and 7 -- the plan falls out of LQA, dragging passes and the title
    # Hop 4 fires whenever this edit un-delivered work the plan had already
    # counted as complete. Retiring the affected keys in hop 3 can lower
    # required_unit_count by the same amount delivered_unit_count fell, so the
    # bare inequality is not on its own a sufficient trigger.
    reopened = []
    if plan["status"] == "LQA" and (
        undelivered > 0
        or plan["delivered_unit_count"] < plan["required_unit_count"]
    ):
        reopened = revert_plan_from_lqa(plan)
        recompute_plan_cost(plan)

    # hop 6 -- verified defects on reopened passes whose unit was reverted
    for qa_pass in reopened:
        dragged = False
        for bug in by_created(pass_bugs(qa_pass["id"])):
            if bug["status"] == "VERIFIED" and bug["translation_unit_id"] in reverted_unit_ids:
                bug["status"] = "TRIAGED"
                bug["verified_by_user_id"] = None
                touch(bug)
                dragged = True
        if dragged:
            recompute_pass_density(qa_pass)
            for unit_id in reverted_unit_ids:
                unit = db.translation_units.get(unit_id)
                if unit is not None:
                    recompute_unit_open_bugs(unit)

    return ok(content_edit_out(edit))


@bp.route("/content-edits/<content_edit_id>/withdraw", methods=["POST"])
@endpoint(PROPOSERS)
def withdraw_content_edit(content_edit_id):
    edit = fetch("content_edits", content_edit_id)
    if edit["status"] != "PROPOSED":
        raise ApiError("ERR_CONTENT_EDIT_NOT_PROPOSED")

    edit["status"] = "WITHDRAWN"
    touch(edit)
    return ok(content_edit_out(edit))
