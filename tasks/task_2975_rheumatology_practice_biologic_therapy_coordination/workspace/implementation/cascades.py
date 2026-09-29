"""The shared cascade tails of PRD 2.9, 3.6, 3.7 and 3.9.

The unwinding tail is stated once in the PRD and runs identically whether a
rheumatologist ordered the hold, an abnormal panel forced it, or the episode was
discontinued outright, so it lives here exactly once.
"""

import calculations as calc
import constants as C
from store import bump, db, sort_rows, touch


def _episode_appointments(episode_id):
    return sort_rows(
        [a for a in db.appointments.values() if a["episode_id"] == episode_id]
    )


def _episode_enrollments(episode_id):
    return sort_rows(
        [e for e in db.enrollments.values() if e["episode_id"] == episode_id]
    )


def release_authorization_unit(appointment):
    """PRD 2.8: one unit moves from units_reserved back to units_remaining."""
    auth_id = appointment.get("reserved_authorization_id")
    if auth_id is None:
        return
    auth = db.authorizations.get(auth_id)
    if auth is None:
        return
    auth["units_reserved"] -= C.UNITS_PER_DOSE
    auth["units_remaining"] = (auth["units_remaining"] or 0) + C.UNITS_PER_DOSE
    # PRD 2.4: moving a counter is not on its own a version-advancing event.
    touch(auth)


def release_assistance(appointment):
    """PRD 3.7 / 3.8: reserved dollars return, and EXHAUSTED becomes ACTIVE."""
    enrollment_id = appointment.get("reserved_enrollment_id")
    if enrollment_id is None:
        return
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        return
    amount = appointment.get("assistance_applied_cents") or 0
    if amount == 0:
        return
    enrollment["benefit_reserved_cents"] -= amount
    enrollment["benefit_remaining_cents"] += amount
    if enrollment["status"] == "EXHAUSTED" and enrollment["benefit_remaining_cents"] > 0:
        enrollment["status"] = "ACTIVE"
        bump(enrollment)
    else:
        touch(enrollment)


def cancel_appointment(appointment, reason):
    """PRD 3.7: SCHEDULED -> CANCELLED, releasing the unit and the dollars."""
    appointment["status"] = "CANCELLED"
    appointment["cancellation_reason"] = reason
    release_authorization_unit(appointment)
    release_assistance(appointment)
    bump(appointment)


def unwind_scheduled_appointments(episode):
    """The calendar half of the tail: cancel every still-SCHEDULED dose.

    Appointments already ADMINISTERED or already CANCELLED are untouched.
    """
    for appointment in _episode_appointments(episode["id"]):
        if appointment["status"] != "SCHEDULED":
            continue
        cancel_appointment(appointment, "THERAPY_HELD")


def terminate_enrollments(episode, reason):
    """PRD 3.8: every non-TERMINATED enrollment releases and terminates."""
    for enrollment in _episode_enrollments(episode["id"]):
        if enrollment["status"] == "TERMINATED":
            continue
        reserved = enrollment["benefit_reserved_cents"]
        enrollment["benefit_reserved_cents"] = 0
        enrollment["benefit_remaining_cents"] += reserved
        enrollment["status"] = "TERMINATED"
        enrollment["termination_reason"] = reason
        bump(enrollment)


def enter_hold(episode, patient, hold_reason):
    """PRD 3.6 / 3.9: the four-level tail of leaving ACTIVE for HELD.

    The caller is responsible for having verified that the episode is ACTIVE.
    Both the episode's and the patient's versions advance here.
    """
    drug = db.drugs.get(episode["drug_id"])
    now = db.now()
    episode["therapy_state"] = "HELD"
    episode["hold_reason"] = hold_reason
    episode["held_at"] = now
    episode["hold_count"] += 1
    molecule_class = drug["molecule_class"] if drug is not None else None
    if molecule_class is not None:
        episode["resume_not_before"] = calc.resume_not_before(
            now, hold_reason, molecule_class
        )
    else:
        episode["resume_not_before"] = now
    bump(episode)

    unwind_scheduled_appointments(episode)

    patient["active_episode_count"] -= 1
    bump(patient)


def discontinue(episode, patient, reason):
    """PRD 3.9: the tail of leaving for DISCONTINUED, plus enrollment teardown.

    ``reason`` is the caller's reason, or ``SUPERSEDED`` when the supersede
    cascade of PRD 3.4 is the mover.  The patient's active-episode count only
    drops when the episode was ACTIVE at this instant.
    """
    was_active = episode["therapy_state"] == "ACTIVE"
    now = db.now()
    episode["therapy_state"] = "DISCONTINUED"
    episode["discontinuation_reason"] = reason
    episode["discontinued_at"] = now
    episode["therapy_exposure_weeks"] = calc.therapy_exposure_weeks(episode, now)
    episode["hold_reason"] = None
    episode["held_at"] = None
    episode["resume_not_before"] = None
    bump(episode)

    unwind_scheduled_appointments(episode)
    terminate_enrollments(episode, "EPISODE_DISCONTINUED")

    if was_active:
        patient["active_episode_count"] -= 1
    bump(patient)


def supersede_planned_episodes(patient, new_episode_id):
    """PRD 3.4: every OTHER still-PLANNED episode of the patient is superseded.

    Only the superseded episode's own version advances -- the patient's version
    increment for the create is accounted for by the caller.
    """
    now = db.now()
    for episode in sort_rows(
        [e for e in db.episodes.values() if e["patient_id"] == patient["id"]]
    ):
        if episode["id"] == new_episode_id:
            continue
        if episode["therapy_state"] != "PLANNED":
            continue
        episode["therapy_state"] = "DISCONTINUED"
        episode["discontinuation_reason"] = "SUPERSEDED"
        episode["discontinued_at"] = now
        # A superseded episode never activated, so its exposure settles at 0.
        episode["therapy_exposure_weeks"] = 0
        bump(episode)
