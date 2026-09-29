"""The payment schedule and build delivery (PRD 3.2, 3.4)."""

from fractions import Fraction

from flask import Blueprint, request

from calc import budget_summary, gate_passes, readiness_score
from envelope import created, success
from errors import ApiError
from guards import (
    ALL_ROLES,
    ROLE_DEVELOPER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER_FINANCE,
    agreement_of_build,
    agreement_of_milestone,
    begin,
    body,
    find_agreement,
    find_build,
    find_milestone,
    require_party,
    visible,
)
from ledger import builds_of_milestone, milestones_of, recompute_ledger
from listing import matches, paged
from serializers import build as ser_build
from serializers import milestone as ser_milestone
from store import db, lock, new_id, now, now_iso, ordered, parse_instant, stamp_new, touch
from validation import Field, paging

bp = Blueprint("milestones", __name__)

MILESTONE_WRITE_ROLES = [ROLE_PLATFORM_ADMIN, ROLE_DEVELOPER, ROLE_PUBLISHER_FINANCE]

MILESTONE_FIELDS = (
    Field("agreement_id", "string", required=True),
    Field("sequence_index", "int", required=True, min=1),
    Field("title", "string", required=True, min_len=1, max_len=120, non_blank=True),
    Field("gate_profile", "enum", required=True, values=("ALPHA", "BETA", "GOLD")),
    Field("funded_amount_cents", "int", required=True, min=10000),
    Field("contractor_budget_cents", "int", required=True, min=0),
    Field(
        "acceptance_criteria", "array", required=True,
        min_items=1, max_items=20, item="nonblank_string",
    ),
    Field("depends_on_milestone_id", "string"),
)

BUILD_FIELDS = (
    Field("milestone_id", "string", required=True),
    Field("build_number", "int", required=True, min=1),
    Field("feature_completeness_pct", "number", required=True, min=0, max=100),
    Field("crash_free_sessions_pct", "number", required=True, min=0, max=100),
    Field("content_completeness_pct", "number", required=True, min=0, max=100),
    Field("known_blocker_count", "int", required=True, min=0),
    Field("addressed_condition_indexes", "array", default=None, item="int"),
    Field("release_notes", "string"),
)

MILESTONE_OPEN_FOR_BUILD = ("DEFINED", "IN_DEVELOPMENT", "CURE_PENDING")


@bp.post("/milestones")
def create_milestone():
    actor = begin(MILESTONE_WRITE_ROLES)
    _, data = body(MILESTONE_FIELDS)
    with lock:
        # Rule 19: agreement_id resolves before depends_on_milestone_id.
        agreement = find_agreement(data["agreement_id"])
        predecessor = None
        if data["depends_on_milestone_id"] is not None:
            predecessor = find_milestone(data["depends_on_milestone_id"])
        require_party(actor, agreement)

        # Rule 25: scope cannot be added to a deal that is already over.
        if agreement["status"] in ("TERMINATED", "COMPLETED"):
            raise ApiError("ERR_AGREEMENT_TERMINAL")
        # Rule 28: cancelled milestones keep their index reserved forever.
        siblings = milestones_of(agreement)
        if any(m["sequence_index"] == data["sequence_index"] for m in siblings):
            raise ApiError("ERR_SEQUENCE_INDEX_TAKEN")
        # Rule 29: the predecessor must belong to this agreement and sit strictly earlier.
        if predecessor is not None:
            if (
                predecessor["agreement_id"] != agreement["id"]
                or predecessor["sequence_index"] >= data["sequence_index"]
            ):
                raise ApiError("ERR_INVALID_DEPENDENCY")
        # Rule 30: a RESTRICTED posture refuses fresh scope outright.
        if agreement["funding_posture"] == "RESTRICTED":
            raise ApiError("ERR_FUNDING_POSTURE_RESTRICTED")
        # Rule 59: the money must fit the pool.
        if data["funded_amount_cents"] > agreement["available_funding_cents"]:
            raise ApiError("ERR_AGREEMENT_FUNDING_EXCEEDED")

        row = {
            "id": new_id(),
            "agreement_id": agreement["id"],
            "depends_on_milestone_id": data["depends_on_milestone_id"],
            "sequence_index": data["sequence_index"],
            "title": data["title"],
            "gate_profile": data["gate_profile"],
            "funded_amount_cents": data["funded_amount_cents"],
            "uplift_cents": 0,
            "contractor_budget_cents": data["contractor_budget_cents"],
            "acceptance_criteria": list(data["acceptance_criteria"]),
            "status": "DEFINED",
            "content_threshold_relief_pct": Fraction(0),
            "cure_count": 0,
            "cure_deadline_at": None,
            "open_condition_indexes": [],
            "latest_build_number": 0,
            "accepted_at": None,
        }
        stamp_new(row)
        db.milestones[row["id"]] = row
        recompute_ledger(agreement)
        touch(agreement)
        return created(ser_milestone(row))


@bp.get("/milestones/<mid>")
def read_milestone(mid):
    actor = begin(ALL_ROLES)
    with lock:
        milestone = find_milestone(mid)
        require_party(actor, agreement_of_milestone(milestone))
        return success(ser_milestone(milestone))


@bp.get("/milestones")
def list_milestones():
    actor = begin(ALL_ROLES)
    with lock:
        rows = [
            row for row in ordered(db.milestones.values())
            if matches(
                row, request.args,
                ("agreement_id", "depends_on_milestone_id", "status", "gate_profile"),
            )
        ]
        rows = visible(actor, rows, agreement_of_milestone)
        return paged(rows, request.args, ser_milestone)


@bp.get("/milestones/<mid>/budget-summary")
def milestone_budget_summary(mid):
    actor = begin(ALL_ROLES)
    with lock:
        milestone = find_milestone(mid)
        require_party(actor, agreement_of_milestone(milestone))
        return success(budget_summary(milestone))


@bp.post("/milestone-builds")
def submit_build():
    actor = begin([ROLE_DEVELOPER])
    _, data = body(BUILD_FIELDS)
    addressed = data["addressed_condition_indexes"]
    if addressed is None:
        addressed = []
    with lock:
        # Rule 19: build creation resolves milestone_id.
        milestone = find_milestone(data["milestone_id"])
        agreement = agreement_of_milestone(milestone)
        require_party(actor, agreement)
        # Rule 23.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        # Rule 31.
        if milestone["status"] not in MILESTONE_OPEN_FOR_BUILD:
            raise ApiError("ERR_MILESTONE_NOT_OPEN_FOR_BUILD")
        # Rule 46: the gate outranks the dependency, numbering and cure-window rules.
        if not gate_passes(
            milestone,
            data["feature_completeness_pct"],
            data["crash_free_sessions_pct"],
            data["content_completeness_pct"],
            data["known_blocker_count"],
        ):
            raise ApiError("ERR_BUILD_GATE_NOT_MET")
        # Rule 47.
        if milestone["depends_on_milestone_id"] is not None:
            predecessor = db.milestones.get(milestone["depends_on_milestone_id"])
            if predecessor is None or predecessor["status"] != "ACCEPTED":
                raise ApiError("ERR_DEPENDENCY_NOT_ACCEPTED")
        # Rule 48.
        if data["build_number"] <= milestone["latest_build_number"]:
            raise ApiError("ERR_BUILD_NUMBER_NOT_INCREASING")
        cure_resubmission = milestone["status"] == "CURE_PENDING"
        # Rule 49: a cure resubmission must cover every open condition.
        if cure_resubmission:
            outstanding = set(milestone["open_condition_indexes"])
            if not outstanding.issubset(set(addressed)):
                raise ApiError("ERR_CONDITIONS_NOT_ADDRESSED")
            # Rule 51: the cure window is inclusive at millisecond granularity.
            deadline = milestone["cure_deadline_at"]
            if deadline is not None and now() > parse_instant(deadline):
                raise ApiError("ERR_CURE_WINDOW_EXPIRED")

        row = {
            "id": new_id(),
            "milestone_id": milestone["id"],
            "build_number": data["build_number"],
            "feature_completeness_pct": data["feature_completeness_pct"],
            "crash_free_sessions_pct": data["crash_free_sessions_pct"],
            "content_completeness_pct": data["content_completeness_pct"],
            "known_blocker_count": data["known_blocker_count"],
            "addressed_condition_indexes": list(addressed),
            "release_notes": data["release_notes"],
            "readiness_score": readiness_score(
                data["feature_completeness_pct"],
                data["crash_free_sessions_pct"],
                data["content_completeness_pct"],
            ),
            "gate_state": "PASSED",
            "submitted_at": now_iso(),
        }
        stamp_new(row)

        # Every earlier PASSED build of the same milestone is superseded.
        for other in builds_of_milestone(milestone):
            if other["gate_state"] == "PASSED":
                other["gate_state"] = "SUPERSEDED"
                touch(other)

        db.builds[row["id"]] = row
        milestone["status"] = "UNDER_REVIEW"
        milestone["latest_build_number"] = data["build_number"]
        if cure_resubmission:
            milestone["open_condition_indexes"] = []
            milestone["cure_deadline_at"] = None
        touch(milestone)
        return created(ser_build(row))


@bp.get("/milestone-builds/<bid>")
def read_build(bid):
    actor = begin(ALL_ROLES)
    with lock:
        build = find_build(bid)
        require_party(actor, agreement_of_build(build))
        return success(ser_build(build))


@bp.get("/milestones/<mid>/builds")
def list_milestone_builds(mid):
    """PRD 2.3: the one documented exception to created_at ordering."""
    actor = begin(ALL_ROLES)
    # Rule 6 outranks the path lookup at rule 13.
    paging(request.args)
    with lock:
        milestone = find_milestone(mid)
        require_party(actor, agreement_of_milestone(milestone))
        rows = [
            row for row in builds_of_milestone(milestone)
            if matches(row, request.args, ("gate_state",))
        ]
        rows.sort(key=lambda row: row["build_number"], reverse=True)
        return paged(rows, request.args, ser_build)
