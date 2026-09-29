"""Rating submission endpoints (PRD SS3.7)."""
from flask import Blueprint

from constants import (
    ALL_ROLES,
    BOARD_DECISIONS,
    CONTENT_DESCRIPTORS,
    FOOTAGE_MANDATORY_CODES,
    MANDATORY_DISCLOSURES,
    MAX_APPEALS,
    RATING_BANDS,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RATING_BOARD_LIAISON,
)
from db import base_row, db, fetch, insert, rows, touch
from derive import (
    applied_edit_count,
    band_for_score,
    by_created,
    compute_fee_cents,
    effective_disclosure_set,
    plan_submissions,
    refresh_submission_board_view,
    self_assessed_risk_score,
    stricter,
    submission_edits,
)
from errors import ApiError
from middleware import endpoint, require_distinct_actor, user_id
from response import created, ok, paginated
from routehelp import arg, match_all
from serialize import nk_rating_submission, rating_submission_out
from validation import (
    bad,
    json_body,
    opt_enum,
    present,
    req_enum,
    req_enum_list,
    req_id,
    req_int,
)

bp = Blueprint("rating_submissions", __name__)

COMPLIANCE = [ROLE_COMPLIANCE_OFFICER]
LIAISON = [ROLE_RATING_BOARD_LIAISON]

NON_TERMINAL = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "EDITS_REQUIRED")


def _withdraw(submission):
    """Withdraw a submission and every PROPOSED edit filed against it."""
    submission["status"] = "WITHDRAWN"
    touch(submission)
    for edit in by_created(submission_edits(submission["id"])):
        if edit["status"] == "PROPOSED":
            edit["status"] = "WITHDRAWN"
            touch(edit)


@bp.route("/rating-submissions", methods=["POST"])
@endpoint(COMPLIANCE)
def create_rating_submission():
    body = json_body()
    market_plan_id = req_id(body, "market_plan_id")
    disclosed = req_enum_list(body, "disclosed_content_codes", CONTENT_DESCRIPTORS, True)
    footage_asset_count = req_int(body, "footage_asset_count", 0)
    # target_rating is declared for symmetry but the stored value is copied from
    # the market plan, so a divergent supplied value is ignored, not rejected.
    opt_enum(body, "target_rating", RATING_BANDS, None)
    expected_version = req_int(body, "expected_market_plan_version", 0)

    plan = fetch("market_plans", market_plan_id)

    # rung 9 -- optimistic concurrency on the parent market plan
    if expected_version != plan["version"]:
        raise ApiError("ERR_STALE_MARKET_PLAN_VERSION")

    # rung 12 -- the market must be in LQA or already release-ready
    if plan["status"] not in ("LQA", "RELEASE_READY"):
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The market plan must be in LQA or RELEASE_READY",
        )

    siblings = plan_submissions(market_plan_id)
    for existing in by_created(siblings):
        if existing["status"] in NON_TERMINAL:
            _withdraw(existing)

    row = base_row()
    row.update({
        "market_plan_id": market_plan_id,
        "submission_round": len(siblings) + 1,
        "rating_board": plan["rating_board"],
        "disclosed_content_codes": list(disclosed),
        "footage_asset_count": footage_asset_count,
        "target_rating": plan["target_rating"],
        "assigned_rating": None,
        "self_assessed_risk_score": None,
        "board_adjusted_risk_score": None,
        "projected_rating_band": None,
        "fee_cents": 0,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "appeal_count": 0,
        "submitted_at_utc": None,
    })
    insert("rating_submissions", row)
    touch(plan)
    return created(rating_submission_out(row))


@bp.route("/rating-submissions/<rating_submission_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_rating_submission(rating_submission_id):
    return ok(rating_submission_out(fetch("rating_submissions", rating_submission_id)))


@bp.route("/rating-submissions", methods=["GET"])
@endpoint(ALL_ROLES)
def list_rating_submissions():
    pairs = [
        ("market_plan_id", arg("market_plan_id")),
        ("rating_board", arg("rating_board")),
        ("status", arg("status")),
    ]
    items = [s for s in rows("rating_submissions") if match_all(s, pairs)]
    return paginated(items, rating_submission_out, nk_rating_submission)


@bp.route("/rating-submissions/<rating_submission_id>/submit", methods=["POST"])
@endpoint(COMPLIANCE)
def submit_rating_submission(rating_submission_id):
    submission = fetch("rating_submissions", rating_submission_id)
    if submission["status"] != "DRAFT":
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")

    plan = fetch("market_plans", submission["market_plan_id"])
    if plan["status"] != "LQA":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET", "The market plan must be in LQA"
        )

    effective = set(effective_disclosure_set(submission))
    for code in MANDATORY_DISCLOSURES[plan["market_code"]]:
        if code not in effective:
            raise ApiError("ERR_MANDATORY_DISCLOSURE_MISSING")
    if effective & set(FOOTAGE_MANDATORY_CODES) and submission["footage_asset_count"] < 1:
        raise ApiError("ERR_FOOTAGE_EVIDENCE_MISSING")

    title = fetch("titles", plan["title_id"])
    submission["status"] = "SUBMITTED"
    submission["submitted_at_utc"] = db.now()
    submission["submitted_by_user_id"] = user_id()
    submission["self_assessed_risk_score"] = self_assessed_risk_score(submission)
    submission["fee_cents"] = compute_fee_cents(submission, title)
    touch(submission)
    return ok(rating_submission_out(submission))


@bp.route("/rating-submissions/<rating_submission_id>/begin-review", methods=["POST"])
@endpoint(LIAISON)
def begin_review(rating_submission_id):
    submission = fetch("rating_submissions", rating_submission_id)

    # rung 8 -- the filer may not review their own package
    require_distinct_actor(submission["submitted_by_user_id"])

    if submission["status"] != "SUBMITTED":
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")

    submission["status"] = "UNDER_REVIEW"
    submission["reviewed_by_user_id"] = user_id()
    refresh_submission_board_view(submission)
    touch(submission)
    return ok(rating_submission_out(submission))


@bp.route("/rating-submissions/<rating_submission_id>/record-outcome", methods=["POST"])
@endpoint(LIAISON)
def record_outcome(rating_submission_id):
    body = json_body()
    board_decision = req_enum(body, "board_decision", BOARD_DECISIONS)

    submission = fetch("rating_submissions", rating_submission_id)

    # rung 3 -- the assigned band must match the projected band exactly
    if board_decision == "RATE":
        assigned = req_enum(body, "assigned_rating", RATING_BANDS)
        if (
            submission["projected_rating_band"] is not None
            and assigned != submission["projected_rating_band"]
        ):
            bad("assigned_rating must equal the submission's projected_rating_band")
    else:
        assigned = None
        if present(body, "assigned_rating"):
            bad("assigned_rating must be absent when board_decision is REQUIRE_EDITS")

    # rung 8 -- the filer may not record the outcome
    require_distinct_actor(submission["submitted_by_user_id"])

    if submission["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")

    if board_decision == "RATE":
        submission["status"] = "RATED"
        submission["assigned_rating"] = assigned
    else:
        submission["status"] = "EDITS_REQUIRED"
    touch(submission)
    return ok(rating_submission_out(submission))


@bp.route("/rating-submissions/<rating_submission_id>/appeal", methods=["POST"])
@endpoint(COMPLIANCE)
def appeal_rating_submission(rating_submission_id):
    submission = fetch("rating_submissions", rating_submission_id)
    if submission["status"] != "RATED":
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")
    if applied_edit_count(submission) < 1:
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "An appeal requires at least one APPLIED content edit",
        )
    assigned = submission["assigned_rating"]
    if assigned is None or not stricter(assigned, submission["target_rating"]):
        raise ApiError("ERR_RATING_BAND_MISMATCH")
    if submission["appeal_count"] >= MAX_APPEALS:
        raise ApiError("ERR_MAX_APPEALS_EXCEEDED")

    submission["status"] = "UNDER_REVIEW"
    submission["appeal_count"] = submission["appeal_count"] + 1
    submission["assigned_rating"] = None
    refresh_submission_board_view(submission)
    touch(submission)
    return ok(rating_submission_out(submission))


@bp.route("/rating-submissions/<rating_submission_id>/withdraw", methods=["POST"])
@endpoint(COMPLIANCE)
def withdraw_rating_submission(rating_submission_id):
    submission = fetch("rating_submissions", rating_submission_id)
    if submission["status"] not in NON_TERMINAL:
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")

    _withdraw(submission)
    return ok(rating_submission_out(submission))
