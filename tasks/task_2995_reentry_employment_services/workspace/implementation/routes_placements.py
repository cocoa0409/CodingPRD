"""Placement and work-shift endpoints — PRD sections 3.6, 3.7 and 3.9."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from cascades import active_authorized_cases, separate_placement, shift_fits_window
from common import list_result, match_filters, READ_ROLES, resolve
from counters import (
    advance_stage_on_active_placement, reconcile_placement_chain, sync_opening,
    sync_partnership,
)
from domain import (
    BONDING_STATUSES, COMMUTE_BUFFER_MINUTES, MILESTONE_DAYS,
    OFFER_RESPONSES, RECIDIVISM_EVENTS, RETENTION_OUTCOMES,
    SEPARATION_REASONS, SUBSIDY_PLACEMENT_CAP_CENTS, SUBSIDY_TRACKS,
    as_date, as_dt, dec, enrollments_of_participant, hours2,
    opening_of_placement, partnership_of_opening, partnership_of_placement,
    rows, shifts_of_placement, shifts_of_participant, subsidy_total,
    sync_participant, sync_placement,
)
from envelope import created, ok
from errors import fail
from ledger import recompute_grant_by_id
from matching import blocking_error, score_match
from store import db, fmt_instant, new_row, now, now_str, public, touch
from validation import (
    body, caller_id, opt_enum, opt_str, req_date, req_enum, req_instant,
    req_int, req_str, require_roles,
)

bp = Blueprint("placements", __name__)

MANAGER = ["CaseManager"]
LIAISON = ["EmployerLiaison"]
BONDING_TARGETS = ["REQUESTED", "BONDED", "CLAIMED", "EXPIRED"]
BONDING_EDGES = {
    ("NONE", "REQUESTED"),
    ("REQUESTED", "BONDED"),
    ("BONDED", "CLAIMED"),
    ("BONDED", "EXPIRED"),
}
SHIFT_TARGETS = ["WORKED", "CANCELLED"]
OCCUPYING_SHIFT_STATUSES = ("SCHEDULED", "CONFLICTED", "WORKED")


# --------------------------------------------------------------------------
# placements
# --------------------------------------------------------------------------

@bp.post("/placements")
def create_placement():
    require_roles(MANAGER)
    payload = body()
    participant_id = req_str(payload, "participant_id")
    job_opening_id = req_str(payload, "job_opening_id")
    subsidy_track = req_enum(payload, "subsidy_track", SUBSIDY_TRACKS)
    expected_version = req_int(payload, "expected_job_opening_version")
    start_date = req_date(payload, "start_date")
    grant_id = payload.get("grant_id")
    if subsidy_track == "SUBSIDIZED_WORK_EXPERIENCE":
        if grant_id is None:
            fail("ERR_VALIDATION",
                 "grant_id is required for a subsidised placement")
        grant_id = req_str(payload, "grant_id")
    elif grant_id is not None:
        fail("ERR_VALIDATION",
             "grant_id must be null for an unsubsidised placement")

    if participant_id not in db.participants:
        fail("ERR_PARTICIPANT_NOT_FOUND", "participant_id matches no participant")
    if job_opening_id not in db.job_openings:
        fail("ERR_JOB_OPENING_NOT_FOUND", "job_opening_id matches no job opening")
    if grant_id is not None and grant_id not in db.grants:
        fail("ERR_GRANT_NOT_FOUND", "grant_id matches no grant")

    participant = db.participants[participant_id]
    opening = db.job_openings[job_opening_id]
    partnership = db.partnerships.get(opening["partnership_id"])

    if expected_version != opening["version"]:
        fail("ERR_STALE_JOB_OPENING_VERSION",
             "The job opening has been modified since it was last read")

    blocking = blocking_error(participant, opening, partnership)
    if blocking is not None:
        fail(blocking, "The placement is not eligible")

    score, breakdown = score_match(participant, opening, partnership)
    row = new_row(
        participant_id=participant_id,
        job_opening_id=job_opening_id,
        grant_id=grant_id,
        subsidy_track=subsidy_track,
        start_date=payload["start_date"],
        employment_status="OFFERED",
        bonding_status="NONE",
        schedule_compliance="COMPLIANT",
        match_score=score,
        match_breakdown=breakdown,
        projected_subsidy_cents=0,
        actual_subsidy_cents=0,
        disbursed_subsidy_cents=0,
        recidivism_event="NONE",
        separation_reason=None,
        separation_date=None,
        retention_30_outcome=None,
        retention_60_outcome=None,
        retention_90_outcome=None,
        last_retention_check_at=None,
    )
    db.placements[row["id"]] = row
    sync_opening(opening)
    sync_partnership(partnership)
    sync_participant(participant)
    recompute_grant_by_id(grant_id, allow_waterfall=False)
    return created(public(row))


@bp.get("/placements/<placement_id>")
def read_placement(placement_id):
    require_roles(READ_ROLES)
    placement = resolve("placements", db.placements, placement_id)
    return ok(public(placement))


@bp.get("/placements")
def list_placements():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.placements),
        string_filters=["participant_id", "job_opening_id", "grant_id",
                        "employment_status", "bonding_status",
                        "schedule_compliance"],
    )
    return list_result(result)


@bp.post("/placements/<placement_id>/offer-response")
def offer_response(placement_id):
    require_roles(["Participant"])
    payload = body()
    response = req_enum(payload, "response", OFFER_RESPONSES)

    placement = resolve("placements", db.placements, placement_id)
    if caller_id() != placement["participant_id"]:
        fail("ERR_NOT_PLACEMENT_PARTICIPANT",
             "Only the placement's participant may answer the offer")
    if placement["employment_status"] != "OFFERED":
        fail("ERR_PLACEMENT_INVALID_STATE",
             "Only an OFFERED placement may be answered")

    participant = db.participants.get(placement["participant_id"])
    opening = opening_of_placement(placement)
    partnership = partnership_of_opening(opening) if opening else None

    if response == "ACCEPTED":
        if participant is not None and participant[
                "suspension_status"] == "SUSPENDED":
            fail("ERR_PARTICIPANT_SUSPENDED",
                 "A suspended participant may not accept an offer")
        if partnership is None or partnership["status"] != "ACTIVE":
            fail("ERR_PARTNERSHIP_NOT_ACTIVE",
                 "The employer partnership is not ACTIVE")
        if int(partnership["active_placement_count"]) >= int(
                partnership["max_concurrent_placements"]):
            fail("ERR_PARTNERSHIP_CAPACITY_REACHED",
                 "The employer has reached its concurrent placement ceiling")
        placement["employment_status"] = "ACTIVE"
    else:
        placement["employment_status"] = "DECLINED"
    touch(placement)

    sync_opening(opening)
    sync_partnership(partnership)
    sync_placement(placement)
    if participant is not None:
        if response == "ACCEPTED":
            advance_stage_on_active_placement(participant)
        sync_participant(participant)
    recompute_grant_by_id(placement.get("grant_id"), allow_waterfall=False)
    return ok(public(placement))


@bp.post("/placements/<placement_id>/separate")
def separate(placement_id):
    require_roles(LIAISON)
    payload = body()
    separation_reason = req_enum(payload, "separation_reason",
                                 SEPARATION_REASONS)
    separation_date = req_date(payload, "separation_date")

    placement = resolve("placements", db.placements, placement_id)
    if placement["employment_status"] != "ACTIVE":
        fail("ERR_PLACEMENT_INVALID_STATE",
             "Only an ACTIVE placement may be separated")
    if separation_date < as_date(placement["start_date"]):
        fail("ERR_VALIDATION",
             "separation_date may not precede the placement start date")
    if separation_date > now().date():
        fail("ERR_VALIDATION", "separation_date may not be in the future")

    separate_placement(placement, separation_reason, payload["separation_date"])
    return ok(public(placement))


@bp.post("/placements/<placement_id>/bonding")
def drive_bonding(placement_id):
    require_roles(LIAISON)
    payload = body()
    to_status = req_enum(payload, "to_status", BONDING_TARGETS)

    placement = resolve("placements", db.placements, placement_id)
    current = placement["bonding_status"]
    if (current, to_status) not in BONDING_EDGES:
        fail("ERR_BONDING_INVALID_STATE",
             "That bonding transition is not declared")

    employment = placement["employment_status"]
    if to_status in ("REQUESTED", "BONDED"):
        if employment not in ("OFFERED", "ACTIVE"):
            fail("ERR_PLACEMENT_INVALID_STATE",
                 "Bonding may only move while the placement is live")
    else:
        if employment != "SEPARATED":
            fail("ERR_PLACEMENT_INVALID_STATE",
                 "A bond may only be closed after separation")

    partnership = partnership_of_placement(placement)
    if to_status == "REQUESTED":
        if partnership is None or not partnership.get("fidelity_bond_enabled"):
            fail("ERR_FIDELITY_BOND_UNAVAILABLE",
                 "The employer partnership carries no fidelity bond")
    if to_status == "CLAIMED":
        if placement["separation_reason"] != "TERMINATED_FOR_CAUSE":
            fail("ERR_BONDING_CLAIM_NOT_ELIGIBLE",
                 "A bond answers only for a termination for cause")

    placement["bonding_status"] = to_status
    touch(placement)
    return ok(public(placement))


@bp.post("/placements/<placement_id>/retention-check")
def retention_check(placement_id):
    require_roles(MANAGER)
    payload = body()
    milestone_days = req_int(payload, "milestone_days")
    if milestone_days not in MILESTONE_DAYS:
        fail("ERR_VALIDATION", "milestone_days must be 30, 60 or 90")
    outcome = req_enum(payload, "outcome", RETENTION_OUTCOMES)
    recidivism_event = opt_enum(payload, "recidivism_event", RECIDIVISM_EVENTS)

    placement = resolve("placements", db.placements, placement_id)
    if placement["employment_status"] in ("OFFERED", "DECLINED"):
        fail("ERR_PLACEMENT_INVALID_STATE",
             "A placement that never started has no retention milestones")

    milestone_at = as_date(placement["start_date"]) + timedelta(
        days=milestone_days)
    if now().date() < milestone_at:
        fail("ERR_MILESTONE_NOT_REACHED", "The milestone has not elapsed yet")

    field = "retention_%d_outcome" % milestone_days
    if placement[field] is not None:
        fail("ERR_MILESTONE_ALREADY_RECORDED",
             "That milestone already carries an outcome")

    placement[field] = outcome
    placement["last_retention_check_at"] = now_str()
    if recidivism_event is not None:
        placement["recidivism_event"] = recidivism_event
    touch(placement)

    participant = db.participants.get(placement["participant_id"])
    if (milestone_days == 30 and outcome == "RETAINED"
            and placement["employment_status"] == "ACTIVE"
            and participant is not None and participant["stage"] == "PLACED"):
        participant["stage"] = "RETENTION"
        touch(participant)
    if participant is not None:
        sync_participant(participant)
    return ok(public(placement))


# --------------------------------------------------------------------------
# work shifts
# --------------------------------------------------------------------------

def _session_conflict(participant_id, starts_at, ends_at):
    buffer_delta = timedelta(minutes=COMMUTE_BUFFER_MINUTES)
    low = starts_at - buffer_delta
    high = ends_at + buffer_delta
    for enrollment in enrollments_of_participant(participant_id):
        if enrollment["status"] != "ENROLLED":
            continue
        session = db.sessions.get(enrollment["session_id"])
        if session is None or session["status"] != "SCHEDULED":
            continue
        session_start = as_dt(session["starts_at"])
        session_end = as_dt(session["ends_at"])
        if low <= session_end and session_start <= high:
            return True
    return False


@bp.post("/placements/<placement_id>/work-shifts")
def create_work_shift(placement_id):
    require_roles(MANAGER)
    payload = body()
    starts_at = req_instant(payload, "starts_at")
    ends_at = req_instant(payload, "ends_at")
    if ends_at <= starts_at:
        fail("ERR_VALIDATION", "ends_at must be strictly after starts_at")

    placement = resolve("placements", db.placements, placement_id)
    if placement["employment_status"] != "ACTIVE":
        fail("ERR_PLACEMENT_INVALID_STATE",
             "Shifts may only be scheduled on an ACTIVE placement")

    participant_id = placement["participant_id"]
    cases = active_authorized_cases(participant_id)
    if not cases:
        fail("ERR_WORK_NOT_AUTHORIZED",
             "The participant holds no active approved work authorisation")
    if not any(shift_fits_window(starts_at, ends_at, case) for case in cases):
        fail("ERR_SHIFT_OUTSIDE_WINDOW",
             "The shift falls outside the approved work window")
    if starts_at <= now():
        fail("ERR_SHIFT_IN_PAST", "A shift must start in the future")

    for other in shifts_of_participant(participant_id):
        if other["status"] not in OCCUPYING_SHIFT_STATUSES:
            continue
        other_start = as_dt(other["starts_at"])
        other_end = as_dt(other["ends_at"])
        if starts_at < other_end and other_start < ends_at:
            fail("ERR_SHIFT_OVERLAP",
                 "The shift overlaps another shift of this participant")
    if _session_conflict(participant_id, starts_at, ends_at):
        fail("ERR_SHIFT_CONFLICTS_SESSION",
             "The shift collides with a readiness session commute buffer")

    minutes = Decimal((ends_at - starts_at).total_seconds()) / Decimal(60)
    scheduled_hours = hours2(minutes / Decimal(60))
    candidate = {
        "starts_at": fmt_instant(starts_at),
        "_seq": 10 ** 9,
        "scheduled_hours": scheduled_hours,
    }
    before = int(placement["projected_subsidy_cents"])
    capped, uncapped = subsidy_total(placement, ("SCHEDULED", "WORKED"),
                                     extra=candidate)
    if uncapped > SUBSIDY_PLACEMENT_CAP_CENTS:
        fail("ERR_SUBSIDY_CAP_EXCEEDED",
             "The placement subsidy ceiling would be exceeded")
    grant = db.grants.get(placement.get("grant_id"))
    increase = capped - before
    if grant is not None and increase > int(grant["available_cents"]):
        fail("ERR_GRANT_FUNDS_INSUFFICIENT",
             "The grant cannot cover the additional subsidy")

    row = new_row(
        placement_id=placement_id,
        starts_at=fmt_instant(starts_at),
        ends_at=fmt_instant(ends_at),
        scheduled_hours=scheduled_hours,
        status="SCHEDULED",
        conflict_reason=None,
    )
    db.work_shifts[row["id"]] = row
    reconcile_placement_chain(placement, waterfall=False)
    return created(public(row))


@bp.get("/placements/<placement_id>/work-shifts")
def list_placement_shifts(placement_id):
    require_roles(READ_ROLES)
    resolve("placements", db.placements, placement_id)
    result = match_filters(shifts_of_placement(placement_id),
                           string_filters=["status"])
    result = sorted(result, key=lambda s: (s["starts_at"], s["_seq"]))
    return list_result(result)


@bp.get("/work-shifts/<shift_id>")
def read_work_shift(shift_id):
    require_roles(READ_ROLES)
    shift = resolve("work_shifts", db.work_shifts, shift_id)
    return ok(public(shift))


@bp.get("/work-shifts")
def list_work_shifts():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.work_shifts),
        string_filters=["placement_id", "status", "conflict_reason"],
    )
    return list_result(result)


@bp.post("/work-shifts/<shift_id>/status")
def drive_shift_status(shift_id):
    require_roles(MANAGER)
    payload = body()
    to_status = req_enum(payload, "to_status", SHIFT_TARGETS)

    shift = resolve("work_shifts", db.work_shifts, shift_id)
    current = shift["status"]
    placement = db.placements.get(shift["placement_id"])
    clock = now()

    if to_status == "WORKED":
        if current != "SCHEDULED":
            fail("ERR_WORK_SHIFT_INVALID_STATE",
                 "Only a SCHEDULED shift may be marked worked")
        if as_dt(shift["ends_at"]) > clock:
            fail("ERR_WORK_SHIFT_INVALID_STATE",
                 "A shift cannot be worked before it has finished")
        if placement is None or placement["employment_status"] != "ACTIVE":
            fail("ERR_PLACEMENT_INVALID_STATE",
                 "The owning placement is no longer active")
        shift["status"] = "WORKED"
        shift["conflict_reason"] = None
        touch(shift)
        reconcile_placement_chain(placement, waterfall=False)
    else:
        if current == "SCHEDULED":
            if as_dt(shift["starts_at"]) <= clock:
                fail("ERR_WORK_SHIFT_INVALID_STATE",
                     "A shift already under way cannot be cancelled")
        elif current != "CONFLICTED":
            fail("ERR_WORK_SHIFT_INVALID_STATE",
                 "Only a scheduled or conflicted shift may be cancelled")
        shift["status"] = "CANCELLED"
        shift["conflict_reason"] = None
        touch(shift)
        reconcile_placement_chain(placement, waterfall=True)
    return ok(public(shift))
