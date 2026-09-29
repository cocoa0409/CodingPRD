"""The three cascade families of PRD section 2.8.

supervision withdrawal / restoration, employment closure (separation and
partnership termination) and participant closure (suspension and exit).
"""

from domain import (
    apply, as_dt, enrollments_of_participant, exact_minutes,
    opening_of_placement, openings_of_partnership, partnership_of_opening,
    placements_of_participant, placements_of_partnership,
    shifts_of_placement, subsidy_total, support_requests_of_participant,
    sync_participant, sync_placement,
)
from counters import (
    reconcile_placement_chain, revert_stage_on_lost_placement, sync_opening,
    sync_partnership, sync_session_by_id,
)
from ledger import recompute_grant_by_id
from store import db, now, touch


# --------------------------------------------------------------------------
# window containment, shared with work-shift creation
# --------------------------------------------------------------------------

def shift_fits_window(starts_at, ends_at, case):
    """Minute span inside [start, end] inclusive and inside one UTC day."""
    if case is None:
        return False
    start_minute = case.get("approved_window_start_minute")
    end_minute = case.get("approved_window_end_minute")
    if start_minute is None or end_minute is None:
        return False
    if starts_at.date() != ends_at.date():
        return False
    span_start = exact_minutes(starts_at)
    span_end = exact_minutes(ends_at)
    return span_start >= start_minute and span_end <= end_minute


def active_authorized_cases(participant_id):
    return [c for c in db.supervision_cases.values()
            if c["participant_id"] == participant_id
            and c["status"] == "ACTIVE"
            and c["work_authorization_status"] == "APPROVED"]


# --------------------------------------------------------------------------
# supervision withdrawal and restoration
# --------------------------------------------------------------------------

def conflict_future_shifts(participant_id, reason):
    """Future scheduled shifts on active placements become CONFLICTED."""
    clock = now()
    affected = []
    for placement in placements_of_participant(participant_id):
        if placement["employment_status"] != "ACTIVE":
            continue
        touched_any = False
        for shift in shifts_of_placement(placement["id"]):
            if shift["status"] != "SCHEDULED":
                continue
            if as_dt(shift["starts_at"]) <= clock:
                continue
            shift["status"] = "CONFLICTED"
            shift["conflict_reason"] = reason
            touch(shift)
            touched_any = True
        if touched_any:
            affected.append(placement)
    for placement in affected:
        reconcile_placement_chain(placement, waterfall=True)
    participant = db.participants.get(participant_id)
    if participant is not None:
        sync_participant(participant)
    return affected


def restore_conflicted_shifts(participant_id, case):
    """The compensating cascade of a SUSPENDED -> APPROVED authorization."""
    clock = now()
    affected = []
    for placement in placements_of_participant(participant_id):
        if placement["employment_status"] != "ACTIVE":
            continue
        touched_any = False
        for shift in shifts_of_placement(placement["id"]):
            if shift["status"] != "CONFLICTED":
                continue
            if shift.get("conflict_reason") != "WORK_AUTHORIZATION_SUSPENDED":
                continue
            if as_dt(shift["starts_at"]) <= clock:
                continue
            if not shift_fits_window(as_dt(shift["starts_at"]),
                                     as_dt(shift["ends_at"]), case):
                continue
            shift["status"] = "SCHEDULED"
            shift["conflict_reason"] = None
            touch(shift)
            touched_any = True
        if touched_any:
            affected.append(placement)
    for placement in affected:
        reconcile_placement_chain(placement, waterfall=True)
    participant = db.participants.get(participant_id)
    if participant is not None:
        sync_participant(participant)
    return affected


# --------------------------------------------------------------------------
# employment closure
# --------------------------------------------------------------------------

def separate_placement(placement, separation_reason, separation_date):
    """The seven-step separation cascade of PRD section 3.7."""
    clock = now()
    placement["employment_status"] = "SEPARATED"
    placement["separation_reason"] = separation_reason
    placement["separation_date"] = separation_date
    for shift in shifts_of_placement(placement["id"]):
        if shift["status"] not in ("SCHEDULED", "CONFLICTED"):
            continue
        if as_dt(shift["starts_at"]) <= clock:
            continue
        shift["status"] = "CANCELLED"
        shift["conflict_reason"] = None
        touch(shift)
    frozen_actual = subsidy_total(placement, ("WORKED",))[0]
    placement["actual_subsidy_cents"] = frozen_actual
    placement["projected_subsidy_cents"] = 0
    placement["disbursed_subsidy_cents"] = frozen_actual
    touch(placement)
    sync_placement(placement)

    opening = opening_of_placement(placement)
    sync_opening(opening)
    sync_partnership(partnership_of_opening(opening) if opening else None)

    participant = db.participants.get(placement["participant_id"])
    if participant is not None:
        revert_stage_on_lost_placement(participant)
        sync_participant(participant)

    recompute_grant_by_id(placement.get("grant_id"), allow_waterfall=True)


def terminate_partnership(partnership):
    """Close the openings and decline their outstanding offers. No money moves."""
    closed_openings = []
    for opening in openings_of_partnership(partnership["id"]):
        if opening["status"] in ("OPEN", "FILLED"):
            opening["status"] = "CLOSED"
            touch(opening)
            closed_openings.append(opening)
    closed_ids = {o["id"] for o in closed_openings}
    participants = set()
    for placement in placements_of_partnership(partnership["id"]):
        if placement["job_opening_id"] not in closed_ids:
            continue
        if placement["employment_status"] != "OFFERED":
            continue
        placement["employment_status"] = "DECLINED"
        touch(placement)
        participants.add(placement["participant_id"])
    for opening in closed_openings:
        sync_opening(opening)
    sync_partnership(partnership)
    for participant_id in participants:
        participant = db.participants.get(participant_id)
        if participant is not None:
            sync_participant(participant)


# --------------------------------------------------------------------------
# participant closure
# --------------------------------------------------------------------------

def withdraw_scheduled_enrollments(participant_id):
    """Enrollments in ENROLLED on SCHEDULED sessions are withdrawn."""
    session_ids = []
    for enrollment in enrollments_of_participant(participant_id):
        if enrollment["status"] != "ENROLLED":
            continue
        session = db.sessions.get(enrollment["session_id"])
        if session is None or session["status"] != "SCHEDULED":
            continue
        enrollment["status"] = "WITHDRAWN"
        touch(enrollment)
        if enrollment["session_id"] not in session_ids:
            session_ids.append(enrollment["session_id"])
    for session_id in session_ids:
        sync_session_by_id(session_id)
    return session_ids


def void_open_support_requests(participant_id):
    """Void the participant's open requests, releasing approved commitments."""
    requests = support_requests_of_participant(participant_id)
    for request in requests:
        if request["status"] in ("SUBMITTED", "INFO_REQUESTED"):
            request["status"] = "VOIDED"
            touch(request)
    for grant in db.grants.values():
        recompute_grant_by_id(grant["id"], allow_waterfall=False)
    for request in requests:
        if request["status"] not in ("APPROVED", "DEFERRED"):
            continue
        request["status"] = "VOIDED"
        touch(request)
        recompute_grant_by_id(request["grant_id"], allow_waterfall=True)


def apply_suspension_cascade(participant):
    withdraw_scheduled_enrollments(participant["id"])
    sync_participant(participant)


def apply_exit_cascade(participant):
    withdraw_scheduled_enrollments(participant["id"])
    void_open_support_requests(participant["id"])
    sync_participant(participant)


def clear_field(row, field, value=None):
    return apply(row, field, value)
