"""PRD 3.8: assistance programs, segregation of duties, the reauth calendar."""

from flask import Blueprint

import constants as C
import serializers as S
from auth import acting_user_id, endpoint
from errors import fail
from response import created, ok
from store import add_days, bump, db, stamp_versioned
from validation import q_enum, read_body, v_enum, v_instant, v_int, v_string

from .common import episode_or_404, paginate, resolve

bp = Blueprint("assistance", __name__)

ENROLLMENT_READ_ROLES = [
    "BenefitsCounselor",
    "PriorAuthCoordinator",
    "Rheumatologist",
    "InfusionNurse",
    "RegistryAdmin",
]


def _enrollment_or_404(enrollment_id):
    return resolve(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


def _window(program_type, coverage_start):
    """PRD 3.8: the window length is a property of the program class."""
    coverage_end = add_days(coverage_start, C.PROGRAM_DURATION_DAYS[program_type])
    reauth_due_at = add_days(coverage_end, -C.REAUTH_LEAD_DAYS)
    return coverage_end, reauth_due_at


@bp.post("/assistance-enrollments")
@endpoint(["BenefitsCounselor"])
def create_enrollment():
    body = read_body()
    episode_id = v_string(body, "episode_id")
    program_type = v_enum(body, "program_type", C.PROGRAM_TYPES)
    annual_benefit_cents = v_int(body, "annual_benefit_cents", minimum=1)
    coverage_start = v_instant(body, "coverage_start")

    if db.episodes.get(episode_id) is None:
        fail("ERR_EPISODE_NOT_FOUND")

    coverage_end, reauth_due_at = _window(program_type, coverage_start)

    row = {
        "episode_id": episode_id,
        "program_type": program_type,
        "status": "SUBMITTED",
        "annual_benefit_cents": annual_benefit_cents,
        "benefit_used_cents": 0,
        "benefit_reserved_cents": 0,
        "benefit_remaining_cents": annual_benefit_cents,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "reauth_due_at": reauth_due_at,
        "submitted_by_user_id": acting_user_id(),
        "attested_by_user_id": None,
        "attested_at": None,
        "termination_reason": None,
    }
    stamp_versioned(row)
    db.enrollments[row["id"]] = row
    return created(S.enrollment_out(row))


@bp.post("/assistance-enrollments/<enrollment_id>/attest")
@endpoint(["BenefitsCounselor"])
def attest_enrollment(enrollment_id):
    enrollment = _enrollment_or_404(enrollment_id)
    read_body(required=False)
    # PRD 3.8: the state check precedes the duties check.
    if enrollment["status"] != "SUBMITTED":
        fail("ERR_ENROLLMENT_STATE_INVALID")
    if enrollment["submitted_by_user_id"] == acting_user_id():
        fail("ERR_SEGREGATION_OF_DUTIES")

    enrollment["status"] = "ACTIVE"
    enrollment["attested_by_user_id"] = acting_user_id()
    enrollment["attested_at"] = db.now()
    bump(enrollment)
    return ok(S.enrollment_out(enrollment))


@bp.post("/assistance-enrollments/<enrollment_id>/reauthorize")
@endpoint(["BenefitsCounselor"])
def reauthorize_enrollment(enrollment_id):
    enrollment = _enrollment_or_404(enrollment_id)
    body = read_body(required=False)
    annual_benefit_cents = v_int(body, "annual_benefit_cents", required=False, minimum=1)

    if enrollment["status"] != "REAUTH_PENDING":
        fail("ERR_ENROLLMENT_STATE_INVALID")

    if annual_benefit_cents is not None:
        enrollment["annual_benefit_cents"] = annual_benefit_cents

    now = db.now()
    coverage_end, reauth_due_at = _window(enrollment["program_type"], now)
    enrollment["status"] = "ACTIVE"
    enrollment["coverage_start"] = now
    enrollment["coverage_end"] = coverage_end
    enrollment["reauth_due_at"] = reauth_due_at
    enrollment["benefit_used_cents"] = 0
    # Reservations already standing against scheduled doses survive untouched.
    enrollment["benefit_remaining_cents"] = (
        enrollment["annual_benefit_cents"] - enrollment["benefit_reserved_cents"]
    )
    bump(enrollment)
    return ok(S.enrollment_out(enrollment))


@bp.get("/assistance-enrollments/<enrollment_id>")
@endpoint(ENROLLMENT_READ_ROLES)
def get_enrollment(enrollment_id):
    enrollment = _enrollment_or_404(enrollment_id)
    return ok(S.enrollment_out(enrollment))


@bp.get("/therapy-episodes/<episode_id>/assistance-enrollments")
@endpoint(ENROLLMENT_READ_ROLES)
def list_episode_enrollments(episode_id):
    episode_or_404(episode_id)
    status = q_enum("status", C.ENROLLMENT_STATUSES)
    rows = [
        e
        for e in db.enrollments.values()
        if e["episode_id"] == episode_id and (status is None or e["status"] == status)
    ]
    return paginate(rows, S.enrollment_out)
