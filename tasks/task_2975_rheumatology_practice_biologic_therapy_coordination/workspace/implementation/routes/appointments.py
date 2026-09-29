"""PRD 3.7: infusion scheduling, administration, reversal and cancellation."""

from flask import Blueprint

import calculations as calc
import cascades
import constants as C
import serializers as S
from auth import endpoint
from errors import fail
from response import created, ok
from store import add_minutes, bump, db, stamp_versioned, touch
from validation import q_enum, q_string, read_body, v_enum, v_instant, v_string

from .common import paginate, resolve

bp = Blueprint("appointments", __name__)

APPOINTMENT_READ_ROLES = [
    "InfusionNurse",
    "Rheumatologist",
    "BenefitsCounselor",
    "PriorAuthCoordinator",
    "RegistryAdmin",
]

CHAIR_OCCUPYING_SITES = ("AMBULATORY_INFUSION_CENTER", "HOSPITAL_OUTPATIENT")


def _appointment_or_404(appointment_id):
    return resolve(db.appointments, appointment_id, "ERR_APPOINTMENT_NOT_FOUND")


def _chair_conflict(chair, start, end, ignore_id=None):
    """PRD 3.7: the buffer pads each EXISTING occupancy on both sides."""
    buffer_minutes = chair["turnover_buffer_minutes"]
    for other in db.appointments.values():
        if other["chair_id"] != chair["id"]:
            continue
        if other["id"] == ignore_id:
            continue
        if other["status"] not in ("SCHEDULED", "ADMINISTERED"):
            continue
        blocked_start = add_minutes(other["scheduled_start"], -buffer_minutes)
        blocked_end = add_minutes(other["scheduled_end"], buffer_minutes)
        if start < blocked_end and blocked_start < end:
            return True
    return False


@bp.post("/infusion-appointments")
@endpoint(["InfusionNurse"])
def schedule_appointment():
    body = read_body()
    episode_id = v_string(body, "episode_id")
    chair_id = v_string(body, "chair_id")
    scheduled_start = v_instant(body, "scheduled_start")

    episode = db.episodes.get(episode_id)
    if episode is None:
        fail("ERR_EPISODE_NOT_FOUND")
    chair = db.chairs.get(chair_id)
    if chair is None:
        fail("ERR_CHAIR_NOT_FOUND")

    if episode["therapy_state"] != "ACTIVE":
        fail("ERR_EPISODE_NOT_ACTIVE")
    if chair["status"] != "OPEN":
        fail("ERR_CHAIR_CLOSED")
    if episode["site_of_care"] not in CHAIR_OCCUPYING_SITES:
        fail(
            "ERR_SITE_OF_CARE_MISMATCH",
            "An episode sited at %s never occupies a practice chair." % episode["site_of_care"],
        )
    if chair["site_type"] != episode["site_of_care"]:
        fail("ERR_SITE_OF_CARE_MISMATCH")

    drug = db.drugs[episode["drug_id"]]
    plan = db.payer_plans[episode["payer_plan_id"]]
    scheduled_end = add_minutes(scheduled_start, drug["admin_time_minutes"])

    # PRD 3.7 fixes the selector's own internal ordering, which settles which of
    # ERR_AUTHORIZATION_UNITS_EXHAUSTED and ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW
    # this calculation would report; the selector mutates nothing until the
    # request is known to be lawful.
    authorization, selector_error = calc.select_authorization(episode, scheduled_start)
    conflicted = _chair_conflict(chair, scheduled_start, scheduled_end)

    # PRD 2.10 then ranks that outcome against the chair calendar by ladder
    # position: ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW is rule 42,
    # ERR_CHAIR_TIME_CONFLICT is rule 45 and ERR_AUTHORIZATION_UNITS_EXHAUSTED is
    # rule 48. The clarification in 2.10 lifts only the window/units pair out of
    # the ladder relative to each other, so rule 45 still outranks rule 48.
    if selector_error == "ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW":
        fail(selector_error)
    if conflicted:
        fail("ERR_CHAIR_TIME_CONFLICT")
    if selector_error is not None:
        fail(selector_error)

    # PRD 3.7: dose_sequence is counted immediately BEFORE this row is inserted;
    # cancelled appointments do not occupy a sequence number.
    occupied = sum(
        1
        for a in db.appointments.values()
        if a["episode_id"] == episode_id and a["status"] in ("SCHEDULED", "ADMINISTERED")
    )
    dose_sequence = occupied + 1

    # One unit moves out of units_remaining and into units_reserved.
    authorization["units_remaining"] -= C.UNITS_PER_DOSE
    authorization["units_reserved"] += C.UNITS_PER_DOSE
    touch(authorization)

    # The per-dose vector is computed over the reserved authorization's
    # approved_units; this dose takes the entry at position dose_sequence.
    dose_count = max(authorization["approved_units"] or 0, dose_sequence)
    waterfall = calc.cost_share_waterfall(episode, drug, plan, dose_count)
    dose_cost_share = waterfall["per_dose_share_cents"][dose_sequence - 1]

    enrollment_id, applied, out_of_pocket = calc.apply_assistance(episode, dose_cost_share)

    row = {
        "episode_id": episode_id,
        "chair_id": chair_id,
        "reserved_authorization_id": authorization["id"],
        "reserved_enrollment_id": enrollment_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "dose_sequence": dose_sequence,
        "dose_cost_share_cents": dose_cost_share,
        "assistance_applied_cents": applied,
        "patient_out_of_pocket_cents": out_of_pocket,
        "administered_at": None,
        "cancellation_reason": None,
        "reversal_reason": None,
    }
    stamp_versioned(row)
    db.appointments[row["id"]] = row
    return created(S.appointment_out(row))


@bp.post("/infusion-appointments/<appointment_id>/administer")
@endpoint(["InfusionNurse"])
def administer(appointment_id):
    appointment = _appointment_or_404(appointment_id)
    episode = db.episodes[appointment["episode_id"]]
    chair = db.chairs[appointment["chair_id"]]
    drug = db.drugs[episode["drug_id"]]
    patient = db.patients[episode["patient_id"]]

    # PRD 3.7: four conditions, in exactly this order.
    if appointment["status"] != "SCHEDULED":
        fail("ERR_APPOINTMENT_STATE_INVALID")
    if episode["therapy_state"] != "ACTIVE":
        fail("ERR_EPISODE_NOT_ACTIVE")
    if chair["status"] != "OPEN":
        fail("ERR_CHAIR_CLOSED")
    if calc.monitoring_status(episode, drug) != "CURRENT":
        fail("ERR_MONITORING_LAB_OVERDUE")

    appointment["status"] = "ADMINISTERED"
    appointment["administered_at"] = db.now()

    authorization = db.authorizations.get(appointment["reserved_authorization_id"])
    if authorization is not None:
        authorization["units_reserved"] -= C.UNITS_PER_DOSE
        authorization["units_consumed"] += C.UNITS_PER_DOSE
        touch(authorization)

    enrollment = db.enrollments.get(appointment["reserved_enrollment_id"])
    if enrollment is not None:
        amount = appointment["assistance_applied_cents"] or 0
        enrollment["benefit_reserved_cents"] -= amount
        enrollment["benefit_used_cents"] += amount
        touch(enrollment)

    episode["doses_administered"] += 1
    bump(episode)
    patient["administered_dose_total"] += 1
    bump(patient)
    bump(appointment)
    return ok(S.appointment_out(appointment))


@bp.post("/infusion-appointments/<appointment_id>/reverse-administration")
@endpoint(["InfusionNurse"])
def reverse_administration(appointment_id):
    appointment = _appointment_or_404(appointment_id)
    body = read_body()
    reversal_reason = v_string(body, "reversal_reason", min_len=1, max_len=240)

    if appointment["status"] != "ADMINISTERED":
        fail("ERR_APPOINTMENT_STATE_INVALID")

    episode = db.episodes[appointment["episode_id"]]
    patient = db.patients[episode["patient_id"]]

    # PRD 2.8: a genuine compensating transition -- the dose returns to
    # SCHEDULED still holding its reservations.
    appointment["status"] = "SCHEDULED"
    appointment["administered_at"] = None
    appointment["reversal_reason"] = reversal_reason

    authorization = db.authorizations.get(appointment["reserved_authorization_id"])
    if authorization is not None:
        authorization["units_consumed"] -= C.UNITS_PER_DOSE
        authorization["units_reserved"] += C.UNITS_PER_DOSE
        touch(authorization)

    enrollment = db.enrollments.get(appointment["reserved_enrollment_id"])
    if enrollment is not None:
        amount = appointment["assistance_applied_cents"] or 0
        enrollment["benefit_used_cents"] -= amount
        enrollment["benefit_reserved_cents"] += amount
        touch(enrollment)

    episode["doses_administered"] -= 1
    bump(episode)
    patient["administered_dose_total"] -= 1
    bump(patient)
    bump(appointment)
    return ok(S.appointment_out(appointment))


@bp.post("/infusion-appointments/<appointment_id>/cancel")
@endpoint(["InfusionNurse"])
def cancel(appointment_id):
    appointment = _appointment_or_404(appointment_id)
    body = read_body()
    reason = v_enum(body, "cancellation_reason", C.CALLER_CANCELLATION_REASONS)
    if appointment["status"] != "SCHEDULED":
        fail("ERR_APPOINTMENT_STATE_INVALID")
    cascades.cancel_appointment(appointment, reason)
    return ok(S.appointment_out(appointment))


@bp.get("/infusion-appointments/<appointment_id>")
@endpoint(APPOINTMENT_READ_ROLES)
def get_appointment(appointment_id):
    appointment = _appointment_or_404(appointment_id)
    return ok(S.appointment_out(appointment))


@bp.get("/infusion-appointments")
@endpoint(APPOINTMENT_READ_ROLES)
def list_appointments():
    episode_id = q_string("episode_id")
    chair_id = q_string("chair_id")
    authorization_id = q_string("reserved_authorization_id")
    enrollment_id = q_string("reserved_enrollment_id")
    status = q_enum("status", C.APPOINTMENT_STATUSES)

    rows = []
    for appointment in db.appointments.values():
        if episode_id is not None and appointment["episode_id"] != episode_id:
            continue
        if chair_id is not None and appointment["chair_id"] != chair_id:
            continue
        if (
            authorization_id is not None
            and appointment["reserved_authorization_id"] != authorization_id
        ):
            continue
        if (
            enrollment_id is not None
            and appointment["reserved_enrollment_id"] != enrollment_id
        ):
            continue
        if status is not None and appointment["status"] != status:
            continue
        rows.append(appointment)
    return paginate(rows, S.appointment_out)
