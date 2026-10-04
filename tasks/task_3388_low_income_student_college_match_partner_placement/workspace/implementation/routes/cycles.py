"""MatchCycle endpoints: create, get, advance, run-match, outcome-summary."""
from flask import Blueprint

import clock
import serializers
import store
from auth import ALL_AUTHENTICATED, identity, require_roles
from calculations import create_package, latest_list_seq, rate_bp
from errors import (
    ApiError,
    ERR_CYCLE_BLOCKED,
    ERR_CYCLE_OVERLAP,
    ERR_INVALID_STATE,
    ERR_MATCH_ALREADY_RUN,
    ERR_NOT_FOUND,
    ERR_WRONG_CYCLE_PHASE,
)
from response import ok_object
from validation import KIND_DATETIME, KIND_STR, get_body, validate

bp = Blueprint("cycles", __name__)

# The nine-phase pipeline in its one fixed order (PRD section 2.7).
PHASES = [
    "SETUP",
    "RECRUITMENT",
    "APPLICATION_OPEN",
    "REVIEW",
    "RANKING",
    "MATCH_RUN",
    "REGULAR_DECISION",
    "OUTCOME_TRACKING",
    "CLOSED",
]

# Terminal states plus MATCHED for the OUTCOME_TRACKING -> CLOSED gate.
CLOSEABLE_APPLICATION_STATUSES = ("NOT_FINALIST", "REGULAR_DENIED", "WITHDRAWN", "ENROLLED", "MATCHED")


def get_cycle_or_404(cycle_id):
    cycle = store.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError(ERR_NOT_FOUND, "cycle not found")
    return cycle


@bp.post("/cycles")
def create_cycle():
    body = get_body()
    values = validate(body, [
        ("name", KIND_STR, True, None, None),
        ("app_opens_at", KIND_DATETIME, True, None, None),
        ("app_closes_at", KIND_DATETIME, True, None, None),
        ("ranking_opens_at", KIND_DATETIME, True, None, None),
        ("ranking_closes_at", KIND_DATETIME, True, None, None),
    ])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    # The new cycle's application window must not share a single date with the
    # window of any cycle that is not yet CLOSED; the windows are closed
    # intervals, so touching dates conflict (PRD section 3.1).
    new_open = values["app_opens_at"].date()
    new_close = values["app_closes_at"].date()
    for existing in store.cycles.values():
        if existing["phase"] == "CLOSED":
            continue
        ex_open = existing["app_opens_at"].date()
        ex_close = existing["app_closes_at"].date()
        if new_open <= ex_close and ex_open <= new_close:
            raise ApiError(
                ERR_CYCLE_OVERLAP,
                "application window shares a date with a non-CLOSED cycle",
            )
    cycle = store.create(store.cycles, {
        "name": values["name"],
        "app_opens_at": values["app_opens_at"],
        "app_closes_at": values["app_closes_at"],
        "ranking_opens_at": values["ranking_opens_at"],
        "ranking_closes_at": values["ranking_closes_at"],
        "phase": "SETUP",
        "match_run_completed": False,
    })
    return ok_object(serializers.cycle(cycle), 201)


@bp.get("/cycles/<cycle_id>")
def get_cycle(cycle_id):
    role, _ = identity()
    require_roles(role, ALL_AUTHENTICATED)
    return ok_object(serializers.cycle(get_cycle_or_404(cycle_id)))


@bp.post("/cycles/<cycle_id>/advance")
def advance_cycle(cycle_id):
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    cycle = get_cycle_or_404(cycle_id)
    _advance(cycle)
    return ok_object(serializers.cycle(cycle))


def _advance(cycle):
    current = cycle["phase"]
    if current == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "CLOSED is terminal")
    nxt = PHASES[PHASES.index(current) + 1]

    # Advance preconditions (ERR_CYCLE_BLOCKED, priority 5).
    if nxt == "MATCH_RUN":
        if clock.now() < cycle["ranking_closes_at"]:
            raise ApiError(ERR_CYCLE_BLOCKED, "the logical clock has not reached ranking_closes_at")
        for application in store.applications.values():
            if application["cycle_id"] == cycle["id"] and application["status"] == "UNDER_REVIEW":
                raise ApiError(ERR_CYCLE_BLOCKED, "applications of this cycle remain UNDER_REVIEW")
    elif nxt == "REGULAR_DECISION":
        if not cycle["match_run_completed"]:
            raise ApiError(ERR_CYCLE_BLOCKED, "the match run has not executed")
    elif nxt == "CLOSED":
        for application in store.applications.values():
            if (application["cycle_id"] == cycle["id"]
                    and application["status"] not in CLOSEABLE_APPLICATION_STATUSES):
                raise ApiError(ERR_CYCLE_BLOCKED, "non-terminal applications remain in this cycle")

    # Cascade side effects.
    if nxt == "REVIEW":
        # Nominations the student never acted on die with the application window.
        for referral in store.referrals.values():
            if referral["cycle_id"] == cycle["id"] and referral["status"] == "NOMINATED":
                referral["status"] = "EXPIRED"
                store.touch(referral)
    elif nxt == "MATCH_RUN":
        # Lists lock; finalists who never submitted slide into the regular pool.
        for application in store.applications.values():
            if application["cycle_id"] != cycle["id"]:
                continue
            if application["status"] == "RANKING_SUBMITTED":
                application["status"] = "RANKING_LOCKED"
                store.touch(application)
            elif application["status"] == "FINALIST":
                application["status"] = "REGULAR_POOL"
                store.touch(application)

    cycle["phase"] = nxt
    store.touch(cycle)


@bp.post("/cycles/<cycle_id>/run-match")
def run_match(cycle_id):
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    cycle = get_cycle_or_404(cycle_id)
    if cycle["match_run_completed"]:
        raise ApiError(ERR_MATCH_ALREADY_RUN, "the match run has already executed for this cycle")
    if cycle["phase"] != "MATCH_RUN":
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "run-match is permitted only in MATCH_RUN")

    candidates = [
        a for a in store.applications.values()
        if a["cycle_id"] == cycle["id"] and a["status"] == "RANKING_LOCKED"
    ]
    # academic_index DESC, tie-break created_at ASC (never id); Python's sort
    # is stable, so equal keys keep insertion order.
    candidates.sort(key=lambda a: (-a["academic_index"], a["created_at"]))

    matched_count = 0
    unmatched_count = 0
    for application in candidates:
        if _assign(application, cycle):
            matched_count += 1
        else:
            # No qualifying slot on the list: fall through
            # RANKING_LOCKED -> UNMATCHED -> REGULAR_POOL within the same run.
            application["status"] = "REGULAR_POOL"
            store.touch(application)
            unmatched_count += 1

    cycle["match_run_completed"] = True
    store.touch(cycle)
    return ok_object({"matched_count": matched_count, "unmatched_count": unmatched_count})


def _assign(application, cycle):
    """Walk the application's current list in rank_position ascending; the
    first qualifying college wins (the match is binding). Returns True when a
    match was made."""
    seq = latest_list_seq(application["id"])
    entries = sorted(
        (e for e in store.ranking_entries.values()
         if e["application_id"] == application["id"] and e["list_seq"] == seq),
        key=lambda e: e["rank_position"],
    )
    for entry in entries:
        college = store.colleges.get(entry["college_id"])
        if college is None:
            continue
        if college["status"] != "ACTIVE":
            continue
        if serializers.slots_committed(college["id"]) >= college["match_slots"]:
            continue
        if application["academic_index"] < college["min_academic_index"]:
            continue
        # Four-link assignment cascade (PRD section 3.5).
        match = store.create(store.matches, {
            "application_id": application["id"],
            "college_id": college["id"],
            "cycle_id": cycle["id"],
            "rank_position_awarded": entry["rank_position"],
            "status": "BINDING",
            "matched_at": clock.now(),
        })
        create_package(match["id"], application, college, True)
        application["status"] = "MATCHED"
        application["matched_college_id"] = college["id"]
        store.touch(application)
        student = store.students.get(application["student_id"])
        if student is not None:
            student["student_stage"] = "MATCHED"
            store.touch(student)
        return True
    return False


@bp.get("/cycles/<cycle_id>/outcome-summary")
def outcome_summary(cycle_id):
    role, _ = identity()
    require_roles(role, ALL_AUTHENTICATED)
    cycle = get_cycle_or_404(cycle_id)
    records = [o for o in store.outcomes.values() if o["cycle_id"] == cycle["id"]]
    denominator = len(records)
    on_track = sum(
        1 for o in records
        if o["status"] in ("PERSISTED_Y2", "PERSISTED_Y3", "GRADUATED")
    )
    cohort150 = sum(1 for o in records if o["status"] == "GRADUATED")
    return ok_object({
        "enrolled_count": denominator,
        "on_track_numerator": on_track,
        "on_track_denominator": denominator,
        "on_track_rate_bp": rate_bp(on_track, denominator),
        "cohort150_numerator": cohort150,
        "cohort150_denominator": denominator,
        "cohort150_rate_bp": rate_bp(cohort150, denominator),
    })
