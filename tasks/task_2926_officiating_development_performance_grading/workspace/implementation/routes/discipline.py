"""Discipline, suspension cascades and remediation (PRD 2.8, 3.8)."""

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, touch
from errors import fail
from middleware import ANY_ROLE, ROLE_DIRECTOR, endpoint
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("discipline", __name__)

OUTCOMES = ["CLEARED", "REASSESSED", "ESCALATED"]
REMEDIATION_CYCLE_CAP = 2
RESTORABLE_STATUSES = ("PROBATION", "SUSPENDED")
RELEASABLE_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED")


@bp.route("/discipline-actions", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def open_discipline_action():
    """"A `SUSPENSION` submitted without `suspension_games`, or with a value below
    1, is rejected with `ERR_INVALID_REQUEST`; conversely `suspension_games` must
    be null for a `WARNING` and for a `REMEDIATION`.\""""
    data = v.body()
    official_id = v.req_str(data, "official_id")
    reason_category = v.req_enum(data, "reason_category", calc.REASON_CATEGORIES)
    severity = v.req_enum(data, "severity", calc.SEVERITIES)
    expected_official_version = v.req_int(
        data, "expected_official_version", minimum=0)
    if severity == "SUSPENSION":
        suspension_games = v.req_int(data, "suspension_games", minimum=1)
    else:
        if v.present(data, "suspension_games"):
            fail(errors.ERR_INVALID_REQUEST,
                 "suspension_games must be null for a %s." % severity)
        suspension_games = None

    official = derive.get_official(official_id)
    derive.require_program_open(derive.program_of_official(official))

    if expected_official_version != official["version"]:
        fail(errors.ERR_STALE_OFFICIAL_VERSION,
             "expected_official_version %d does not match the official's "
             "current version %d." % (expected_official_version,
                                      official["version"]))

    # "Opening an action first supersedes any prior discipline the official is
    # already carrying", in created_at ascending order.
    for prior in derive.discipline_actions_of(official["id"]):
        if prior["status"] in derive.DISCIPLINE_SUPERSEDABLE:
            prior["status"] = "SUPERSEDED"
            touch(prior)

    row = base_row()
    row.update({
        "official_id": official["id"],
        "reason_category": reason_category,
        "severity": severity,
        "suspension_games": suspension_games,
        "status": "OPENED",
        "remediation_cycle_count": 0,
        "remediation_plan": None,
        "resolution_note": None,
    })
    db.discipline_actions[row["id"]] = row

    # "What the action does to the official depends on its severity."
    if severity == "SUSPENSION":
        if official["status"] in ("ACTIVE", "PROBATION"):
            official["status"] = "SUSPENDED"
        derive.void_assignments(official)
    elif severity == "REMEDIATION":
        if official["status"] == "ACTIVE":
            official["status"] = "PROBATION"
    elif reason_category == "PERFORMANCE":
        if official["status"] == "ACTIVE":
            official["status"] = "PROBATION"
    # "In every case the official's version bumps by 1 and their season record's
    # postseason_eligible is re-derived."
    touch(official)
    derive.refresh_postseason_eligible(official)
    return object_response(row, 201)


@bp.route("/discipline-actions/<action_id>/assign-remediation", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def assign_remediation(action_id):
    """"It is legal from `OPENED` or from `REASSESSED`, and it is capped: an
    action whose `remediation_cycle_count` has already reached 2 is refused a
    further cycle with `ERR_REMEDIATION_CYCLE_LIMIT`.\""""
    data = v.body()
    remediation_plan = v.req_str(data, "remediation_plan")

    action = derive.get_discipline_action(action_id)
    official = db.officials.get(action["official_id"])
    derive.require_program_open(derive.program_of_official(official))
    if action["status"] not in ("OPENED", "REASSESSED"):
        fail(errors.ERR_DISCIPLINE_STATE_INVALID,
             "Remediation may only be assigned from OPENED or REASSESSED.")
    if action["remediation_cycle_count"] >= REMEDIATION_CYCLE_CAP:
        fail(errors.ERR_REMEDIATION_CYCLE_LIMIT,
             "This action has exhausted its remediation cycles.")

    action["status"] = "REMEDIATION_ASSIGNED"
    action["remediation_plan"] = remediation_plan
    action["remediation_cycle_count"] = action["remediation_cycle_count"] + 1
    touch(action)
    return object_response(action)


@bp.route("/discipline-actions/<action_id>/resolve", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def resolve_discipline_action(action_id):
    """REASSESSED is legal only from REMEDIATION_ASSIGNED; CLEARED and ESCALATED
    are legal from OPENED, REMEDIATION_ASSIGNED or REASSESSED."""
    data = v.body()
    outcome = v.req_enum(data, "outcome", OUTCOMES)
    note = v.opt_str(data, "note", 1, None, None)

    action = derive.get_discipline_action(action_id)
    official = db.officials.get(action["official_id"])
    derive.require_program_open(derive.program_of_official(official))

    if outcome == "REASSESSED":
        legal_from = ("REMEDIATION_ASSIGNED",)
    else:
        legal_from = ("OPENED", "REMEDIATION_ASSIGNED", "REASSESSED")
    if action["status"] not in legal_from:
        fail(errors.ERR_DISCIPLINE_STATE_INVALID,
             "%s is not legal from %s." % (outcome, action["status"]))

    action["status"] = outcome
    if note is not None:
        action["resolution_note"] = note
    touch(action)

    if outcome == "CLEARED" and official is not None:
        # "an official on PROBATION moves PROBATION -> ACTIVE, and an official who
        # is SUSPENDED moves SUSPENDED -> ACTIVE, in both cases only when no other
        # discipline action of that official remains in the non-terminal set."
        if (official["status"] in RESTORABLE_STATUSES
                and not derive.has_blocking_discipline(official["id"])):
            official["status"] = "ACTIVE"
            touch(official)
        derive.refresh_postseason_eligible(official)
    elif outcome == "ESCALATED" and official is not None:
        # "the official's status is set to RELEASED ... every one of that
        # official's assignments in PROPOSED or CONFIRMED status on a SCHEDULED or
        # IN_PROGRESS game is VOIDED ... and the official's version bumps by 1."
        if official["status"] in RELEASABLE_STATUSES:
            official["status"] = "RELEASED"
        derive.void_assignments(official)
        touch(official)
        derive.refresh_postseason_eligible(official)
    return object_response(action)


@bp.route("/discipline-actions/<action_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_discipline_action(action_id):
    return object_response(derive.get_discipline_action(action_id))


@bp.route("/discipline-actions", methods=["GET"])
@endpoint(ANY_ROLE)
def list_discipline_actions():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.discipline_actions)
    for name in ("official_id", "status", "reason_category", "severity"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
