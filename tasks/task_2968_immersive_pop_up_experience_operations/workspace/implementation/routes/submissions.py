"""CreativeSubmission — supersede families, review and revision rounds (PRD §3.2)."""

from flask import Blueprint, request

from db import db, new_row, now_iso, public, touch
from errors import ApiError
from middleware import EP, LM, LR, caller_id, roles
from response import list_response, object_response
from services import derive
from services.validate import Body, fail

bp = Blueprint("submissions", __name__)

APPROVAL_SCOPES = ("CREATIVE_EXECUTION", "MERCHANDISE", "MARKETING")
DECISIONS = ("APPROVED", "REJECTED", "CHANGES_REQUESTED")
OPEN_STATUSES = ("SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED")
REVISION_ROUND_CAP = 3


def _require_rep_of_record(agreement):
    if caller_id() != agreement["licensor_rep_user_id"]:
        raise ApiError("ERR_LICENSOR_REP_MISMATCH")


@bp.post("/creative-submissions")
@roles(EP)
def file_submission():
    body = Body(require_body=True)
    agreement_id = body.reference("license_agreement_id")
    run_id = body.reference("run_id")
    scope = body.enum("scope", APPROVAL_SCOPES)
    asset_code = body.string("asset_code", min_len=1, max_len=40,
                             pattern=r"^[A-Z0-9\-]+$")
    title = body.string("title", min_len=1, max_len=160)
    expected_version = body.integer("expected_agreement_version", minimum=0)

    # rung 5 — body foreign keys, left to right and scope-aware
    agreement = derive.agreement(agreement_id)
    run_row = derive.run(run_id)
    if run_row["license_agreement_id"] != agreement["id"]:
        raise ApiError("ERR_RUN_NOT_FOUND")

    # rung 7 — stale parent version
    if expected_version != agreement["version"]:
        raise ApiError("ERR_AGREEMENT_VERSION_CONFLICT")

    # rung 9 — cross-entity state
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")

    # rung 16 — eligibility
    if scope not in agreement["approval_scopes"]:
        raise ApiError("ERR_SCOPE_NOT_IN_AGREEMENT")

    row = new_row()
    row.update({
        "license_agreement_id": agreement["id"],
        "run_id": run_row["id"],
        "scope": scope,
        "asset_code": asset_code,
        "title": title,
        "submitted_by_user_id": caller_id(),
        "revision_round": 0,
        "change_note": None,
        "decision_note": None,
        "review_started_at": None,
        "resubmitted_at": None,
        "decided_at": None,
        "decided_by_user_id": None,
        "superseded_by_submission_id": None,
        "status": "SUBMITTED",
    })

    superseded_any = False
    for older in derive.submissions_of_run(run_row):
        if (older["scope"] == scope and older["asset_code"] == asset_code
                and older["status"] in OPEN_STATUSES):
            older["status"] = "SUPERSEDED"
            older["superseded_by_submission_id"] = row["id"]
            touch(older)
            superseded_any = True

    db.submissions[row["id"]] = row
    if not superseded_any:
        agreement["open_submission_count"] += 1
    touch(agreement)
    derive.rederive_clearance(run_row)
    return object_response(public(row), 201)


@bp.get("/creative-submissions/<submission_id>")
@roles(EP, LR, LM)
def read_submission(submission_id):
    return object_response(public(derive.submission(submission_id)))


@bp.get("/creative-submissions")
@roles(EP, LR, LM)
def list_submissions():
    rows = list(db.submissions.values())
    for field in ("license_agreement_id", "run_id", "scope", "status",
                  "superseded_by_submission_id"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.post("/creative-submissions/<submission_id>/start-review")
@roles(LR)
def start_review(submission_id):
    submission = derive.submission(submission_id)
    agreement = derive.agreement(submission["license_agreement_id"])

    if submission["status"] != "SUBMITTED":
        raise ApiError("ERR_SUBMISSION_INVALID_STATE")
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    _require_rep_of_record(agreement)

    submission["status"] = "IN_REVIEW"
    submission["review_started_at"] = now_iso()
    touch(submission)
    return object_response(public(submission))


@bp.post("/creative-submissions/<submission_id>/decisions")
@roles(LR)
def decide_submission(submission_id):
    submission = derive.submission(submission_id)
    body = Body(require_body=True)
    decision = body.enum("decision", DECISIONS)
    note = body.string("note", required=False, default=None, min_len=1, max_len=500)
    if decision in ("REJECTED", "CHANGES_REQUESTED") and note is None:
        fail("Field 'note' is required on a %s decision." % decision)

    agreement = derive.agreement(submission["license_agreement_id"])
    run_row = derive.run(submission["run_id"])

    if submission["status"] != "IN_REVIEW":
        raise ApiError("ERR_SUBMISSION_INVALID_STATE")
    _require_rep_of_record(agreement)
    if decision in ("APPROVED", "REJECTED"):
        if caller_id() == submission["submitted_by_user_id"]:
            raise ApiError("ERR_SOD_APPROVAL_SAME_USER")

    if decision == "CHANGES_REQUESTED":
        submission["status"] = "CHANGES_REQUESTED"
        submission["change_note"] = note
        touch(submission)
        return object_response(public(submission))

    stamp = now_iso()
    submission["decided_at"] = stamp
    submission["decided_by_user_id"] = caller_id()
    submission["decision_note"] = note
    if decision == "APPROVED":
        submission["status"] = "APPROVED"
        touch(submission)
        agreement["open_submission_count"] -= 1
        agreement["approved_submission_count"] += 1
        touch(agreement)
        derive.rederive_clearance(run_row)
    else:
        submission["status"] = "REJECTED"
        touch(submission)
        agreement["open_submission_count"] -= 1
        touch(agreement)
        if run_row["clearance_status"] == "CLEARED":
            run_row["clearance_status"] = "UNCLEARED"
            touch(run_row)
    return object_response(public(submission))


@bp.post("/creative-submissions/<submission_id>/resubmit")
@roles(EP)
def resubmit(submission_id):
    submission = derive.submission(submission_id)
    agreement = derive.agreement(submission["license_agreement_id"])

    if submission["status"] != "CHANGES_REQUESTED":
        raise ApiError("ERR_SUBMISSION_INVALID_STATE")
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    if submission["revision_round"] >= REVISION_ROUND_CAP:
        raise ApiError("ERR_REVISION_ROUND_CAP")

    submission["status"] = "SUBMITTED"
    submission["revision_round"] += 1
    submission["resubmitted_at"] = now_iso()
    submission["change_note"] = None
    touch(submission)
    return object_response(public(submission))
