"""Defect endpoints: logging, triage, fix claims and verification (PRD SS3.6)."""
from flask import Blueprint

from constants import (
    ALL_ROLES,
    BUG_AXIS,
    BUG_CLASSES,
    SEVERITIES,
    SEVERITY_WEIGHT,
    ROLE_LOCALIZATION_PRODUCER,
    ROLE_LQA_TESTER,
    ROLE_TRANSLATION_VENDOR,
    TRIAGE_ACTIONS,
)
from db import base_row, db, fetch, insert, rows, touch
from derive import (
    apply_unit_text,
    flag_unit_for_bug,
    recompute_pass_density,
    recompute_unit_open_bugs,
)
from errors import ApiError
from middleware import endpoint, require_distinct_actor, user_id
from response import created, ok, paginated
from routehelp import arg, match_all
from serialize import lqa_bug_out, nk_lqa_bug
from validation import bad, json_body, opt_id, opt_str, present, req_enum, req_id, req_str

bp = Blueprint("lqa_bugs", __name__)

TESTERS = [ROLE_LQA_TESTER]
TRIAGERS = [ROLE_LQA_TESTER, ROLE_LOCALIZATION_PRODUCER]
VENDORS = [ROLE_TRANSLATION_VENDOR]


def _linked_unit(bug):
    if bug["translation_unit_id"] is None:
        return None
    return db.translation_units.get(bug["translation_unit_id"])


@bp.route("/lqa-bugs", methods=["POST"])
@endpoint(TESTERS)
def create_lqa_bug():
    body = json_body()
    qa_pass_id = req_id(body, "qa_pass_id")
    bug_class = req_enum(body, "bug_class", BUG_CLASSES)
    severity = req_enum(body, "severity", SEVERITIES)
    summary = req_str(body, "summary", 1, 200)
    translation_unit_id = opt_id(body, "translation_unit_id")
    if bug_class == "FUNCTIONAL_CRASH":
        translation_unit_id = None

    qa_pass = fetch("qa_passes", qa_pass_id)
    unit = None
    if translation_unit_id is not None:
        unit = fetch("translation_units", translation_unit_id)
        # rung 6 -- the unit must belong to the pass's market plan
        if unit["market_plan_id"] != qa_pass["market_plan_id"]:
            raise ApiError("ERR_CROSS_PARENT_MISMATCH")

    if qa_pass["status"] != "OPEN":
        raise ApiError("ERR_QA_PASS_NOT_OPEN")

    axis = BUG_AXIS[bug_class]
    row = base_row()
    row.update({
        "qa_pass_id": qa_pass_id,
        "translation_unit_id": translation_unit_id,
        "duplicate_of_bug_id": None,
        "bug_class": bug_class,
        "severity": severity,
        "summary": summary,
        "status": "NEW",
        "logged_by_user_id": user_id(),
        "verified_by_user_id": None,
        "severity_weight": SEVERITY_WEIGHT[severity],
        "axis": axis,
    })
    insert("lqa_bugs", row)

    if unit is not None:
        recompute_unit_open_bugs(unit)
        flag_unit_for_bug(unit, axis)
    recompute_pass_density(qa_pass)
    return created(lqa_bug_out(row))


@bp.route("/lqa-bugs/<lqa_bug_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_lqa_bug(lqa_bug_id):
    return ok(lqa_bug_out(fetch("lqa_bugs", lqa_bug_id)))


@bp.route("/lqa-bugs", methods=["GET"])
@endpoint(ALL_ROLES)
def list_lqa_bugs():
    pairs = [
        ("qa_pass_id", arg("qa_pass_id")),
        ("translation_unit_id", arg("translation_unit_id")),
        ("duplicate_of_bug_id", arg("duplicate_of_bug_id")),
        ("bug_class", arg("bug_class")),
        ("severity", arg("severity")),
        ("status", arg("status")),
    ]
    items = [b for b in rows("lqa_bugs") if match_all(b, pairs)]
    return paginated(items, lqa_bug_out, nk_lqa_bug)


@bp.route("/lqa-bugs/<lqa_bug_id>/triage", methods=["POST"])
@endpoint(TRIAGERS)
def triage_lqa_bug(lqa_bug_id):
    body = json_body()
    triage_action = req_enum(body, "triage_action", TRIAGE_ACTIONS)
    duplicate_of_bug_id = None
    if triage_action == "DUPLICATE":
        duplicate_of_bug_id = req_id(body, "duplicate_of_bug_id")
        if duplicate_of_bug_id == lqa_bug_id:
            bad("duplicate_of_bug_id must differ from the defect being triaged")

    bug = fetch("lqa_bugs", lqa_bug_id)
    target = None
    if duplicate_of_bug_id is not None:
        target = fetch("lqa_bugs", duplicate_of_bug_id)
        # rung 6 -- the duplicate target must sit under the same QA pass
        if target["qa_pass_id"] != bug["qa_pass_id"]:
            raise ApiError("ERR_CROSS_PARENT_MISMATCH")

    if bug["status"] != "NEW":
        raise ApiError("ERR_BUG_STATE_INVALID")
    qa_pass = fetch("qa_passes", bug["qa_pass_id"])
    if qa_pass["status"] != "OPEN":
        raise ApiError("ERR_QA_PASS_NOT_OPEN")

    if target is not None and target["status"] == "DUPLICATE":
        raise ApiError(
            "ERR_BUG_STATE_INVALID", "The duplicate target may not itself be a DUPLICATE"
        )

    if triage_action == "ACCEPT":
        bug["status"] = "TRIAGED"
    elif triage_action == "REJECT":
        bug["status"] = "REJECTED"
    else:
        bug["status"] = "DUPLICATE"
        bug["duplicate_of_bug_id"] = duplicate_of_bug_id
    touch(bug)

    unit = _linked_unit(bug)
    if unit is not None:
        recompute_unit_open_bugs(unit)
    recompute_pass_density(qa_pass)
    return ok(lqa_bug_out(bug))


@bp.route("/lqa-bugs/<lqa_bug_id>/submit-fix", methods=["POST"])
@endpoint(VENDORS)
def submit_fix(lqa_bug_id):
    body = json_body(required=False)
    target_text = opt_str(body, "target_text", 0, 4000)

    bug = fetch("lqa_bugs", lqa_bug_id)
    if bug["status"] != "TRIAGED":
        raise ApiError("ERR_BUG_STATE_INVALID")
    qa_pass = fetch("qa_passes", bug["qa_pass_id"])
    if qa_pass["status"] != "OPEN":
        raise ApiError("ERR_QA_PASS_NOT_OPEN")

    bug["status"] = "FIX_SUBMITTED"
    touch(bug)

    unit = _linked_unit(bug)
    if unit is not None:
        if target_text is not None and apply_unit_text(unit, target_text):
            touch(unit)
        recompute_unit_open_bugs(unit)
    recompute_pass_density(qa_pass)
    return ok(lqa_bug_out(bug))


@bp.route("/lqa-bugs/<lqa_bug_id>/verify", methods=["POST"])
@endpoint(TESTERS)
def verify_lqa_bug(lqa_bug_id):
    bug = fetch("lqa_bugs", lqa_bug_id)

    # rung 8 -- the logger may not verify their own finding
    require_distinct_actor(bug["logged_by_user_id"])

    if bug["status"] != "FIX_SUBMITTED":
        raise ApiError("ERR_BUG_STATE_INVALID")
    qa_pass = fetch("qa_passes", bug["qa_pass_id"])
    if qa_pass["status"] != "OPEN":
        raise ApiError("ERR_QA_PASS_NOT_OPEN")

    unit = _linked_unit(bug)
    if bug["bug_class"] in ("TEXT_OVERFLOW", "TRUNCATION"):
        if unit is None or unit["overflow_chars"] != 0:
            raise ApiError("ERR_TEXT_OVERFLOW_UNRESOLVED")

    bug["status"] = "VERIFIED"
    bug["verified_by_user_id"] = user_id()
    touch(bug)

    if unit is not None:
        recompute_unit_open_bugs(unit)
    recompute_pass_density(qa_pass)
    return ok(lqa_bug_out(bug))
