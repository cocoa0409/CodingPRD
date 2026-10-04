"""OutcomeRecord endpoints: checkpoint (persistence ladder), get, list."""
from flask import Blueprint, request

import clock
import serializers
import store
from auth import forbid, identity, require_roles
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_WRONG_CYCLE_PHASE
from response import ok_object, paginated
from validation import KIND_ENUM, KIND_INT, get_body, validate

bp = Blueprint("outcomes", __name__)

READ_ROLES = ("ProgramAdmin", "Student", "CollegeOfficer")

ALL_STATUSES = (
    "ENROLLED_Y1",
    "PERSISTED_Y2",
    "PERSISTED_Y3",
    "GRADUATED",
    "STOPPED_OUT",
    "NOT_PERSISTED",
)

# The legal moves of the persistence ladder with its re-entry ramp
# (PRD section 3.9).
LEGAL_TRANSITIONS = {
    ("ENROLLED_Y1", "PERSISTED_Y2"),
    ("PERSISTED_Y2", "PERSISTED_Y3"),
    ("PERSISTED_Y3", "GRADUATED"),
    ("ENROLLED_Y1", "NOT_PERSISTED"),
    ("ENROLLED_Y1", "STOPPED_OUT"),
    ("PERSISTED_Y2", "STOPPED_OUT"),
    ("PERSISTED_Y3", "STOPPED_OUT"),
    ("STOPPED_OUT", "PERSISTED_Y2"),
}

# A supplied credits_completed updates the cumulative credit count only on the
# two year-to-year persistence advances; otherwise it carries forward.
CREDIT_TRANSITIONS = {
    ("ENROLLED_Y1", "PERSISTED_Y2"),
    ("PERSISTED_Y2", "PERSISTED_Y3"),
}


def get_outcome_or_404(outcome_id):
    outcome = store.outcomes.get(outcome_id)
    if outcome is None:
        raise ApiError(ERR_NOT_FOUND, "outcome record not found")
    return outcome


def check_outcome_ownership(role, uid, outcome):
    if role == "CollegeOfficer" and outcome["college_id"] != uid:
        forbid("a college officer may only act on their own college's outcome records")
    if role == "Student":
        application = store.applications.get(outcome["application_id"])
        if application is None or application["student_id"] != uid:
            forbid("a student may only view their own outcome records")


@bp.post("/outcomes/<outcome_id>/checkpoint")
def checkpoint_outcome(outcome_id):
    body = get_body()
    values = validate(body, [
        ("to_status", KIND_ENUM, True, None, ALL_STATUSES),
        ("credits_completed", KIND_INT, False, None, None),
    ])
    role, uid = identity()
    require_roles(role, ("CollegeOfficer", "ProgramAdmin"))
    outcome = get_outcome_or_404(outcome_id)
    if role == "CollegeOfficer" and outcome["college_id"] != uid:
        forbid("a college officer may only checkpoint their own college's records")
    current = outcome["status"]
    target = values["to_status"]
    if (current, target) not in LEGAL_TRANSITIONS:
        raise ApiError(ERR_INVALID_STATE, "no outcome transition from %s to %s" % (current, target))
    cycle = store.cycles.get(outcome["cycle_id"])
    if cycle is None or cycle["phase"] != "OUTCOME_TRACKING":
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "checkpoints are permitted only in OUTCOME_TRACKING")
    outcome["status"] = target
    outcome["last_checkpoint_at"] = clock.now()
    if (current, target) in CREDIT_TRANSITIONS and values["credits_completed"] is not None:
        outcome["credits_completed"] = values["credits_completed"]
    store.touch(outcome)
    return ok_object(serializers.outcome(outcome))


@bp.get("/outcomes/<outcome_id>")
def get_outcome(outcome_id):
    role, uid = identity()
    require_roles(role, READ_ROLES)
    outcome = get_outcome_or_404(outcome_id)
    check_outcome_ownership(role, uid, outcome)
    return ok_object(serializers.outcome(outcome))


@bp.get("/outcomes")
def list_outcomes():
    role, _ = identity()
    require_roles(role, READ_ROLES)
    items = list(store.outcomes.values())
    for field in ("application_id", "college_id", "cycle_id", "match_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [o for o in items if o[field] == value]
    items.sort(key=lambda o: o["created_at"])
    return paginated(items, serializers.outcome)
