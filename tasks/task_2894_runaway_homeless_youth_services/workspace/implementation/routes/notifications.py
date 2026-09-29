"""The parental-notification obligation: attempts and resolution (PRD 3.4)."""

from flask import Blueprint

import authz
import calc
import cascade
import envelope
import find
import serial
import shape
import store
from errors import fail

bp = Blueprint("notifications", __name__)

ATTEMPT_CHANNELS = ("PHONE", "IN_PERSON", "CERTIFIED_MAIL", "EMAIL")
OUTCOMES = ("CONTACTED", "WAIVED", "LAW_ENFORCEMENT_REPORTED")
WAIVER_REASONS = ("ABUSE_DISCLOSED", "TRAFFICKING_RISK", "COURT_ORDER")


def _youth_of(notification):
    admission = store.admissions.get(notification["admission_id"])
    if admission is None:
        return None, None
    return admission, store.youths.get(admission["youth_id"])


@bp.post("/ryhs/guardian-notifications/<notification_id>/attempt")
def record_attempt(notification_id):
    authz.require(authz.SHELTER_CASE_MANAGER)
    notification = find.notification(notification_id)
    body = shape.body()
    channel = shape.need_enum(body, "attempt_channel", ATTEMPT_CHANNELS)

    # Ladder 12.
    if notification["status"] in calc.RESOLVED_NOTIFICATION_STATUSES:
        fail("ERR_NOTIFICATION_ALREADY_RESOLVED")

    notification["attempt_count"] += 1
    notification["last_attempt_at"] = store.now()
    # "overwriting whatever channel a previous attempt had recorded"
    notification["attempt_channel"] = channel
    if notification["status"] == "PENDING":
        notification["status"] = "ATTEMPTED"
    # An attempt against an OVERDUE obligation leaves it OVERDUE.
    store.touch(notification)

    _admission, youth = _youth_of(notification)
    cascade.refresh_youth(youth)
    return envelope.ok(serial.notification(notification))


@bp.post("/ryhs/guardian-notifications/<notification_id>/resolve")
def resolve(notification_id):
    user_id, role = authz.require(authz.SHELTER_CASE_MANAGER, authz.PROGRAM_ADMIN)
    notification = find.notification(notification_id)
    body = shape.body()
    outcome = shape.need_enum(body, "outcome", OUTCOMES)
    waiver_reason = shape.opt_enum(body, "waiver_reason", WAIVER_REASONS)
    if outcome == "WAIVED" and waiver_reason is None:
        fail("ERR_INVALID_REQUEST", "waiver_reason is required when waiving a notification")

    # PRD 3.4: a waiver "may only be performed by a ProgramAdmin".
    if outcome == "WAIVED" and role != authz.PROGRAM_ADMIN:
        fail("ERR_UNAUTHORIZED_ROLE")

    # Ladder 12.
    if notification["status"] in calc.RESOLVED_NOTIFICATION_STATUSES:
        fail("ERR_NOTIFICATION_ALREADY_RESOLVED")

    admission, youth = _youth_of(notification)

    if outcome == "CONTACTED":
        # Ladder 22: zero recorded attempts, or a FROZEN youth, forbids guardian contact.
        if notification["attempt_count"] < 1:
            fail("ERR_NOTIFICATION_UNSAFE_CONTACT")
        if youth is not None and youth["risk_posture"] == "FROZEN":
            fail("ERR_NOTIFICATION_UNSAFE_CONTACT")

    # Ladder 24: the administrator who waives may not be the case manager who admitted.
    if outcome == "WAIVED" and admission is not None and user_id == admission["admitting_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    was_overdue = notification["status"] == "OVERDUE"
    clock = store.now()
    notification["status"] = outcome
    notification["resolved_at"] = clock
    notification["resolving_user_id"] = user_id
    if outcome == "WAIVED":
        notification["waiver_reason"] = waiver_reason
    if outcome == "LAW_ENFORCEMENT_REPORTED":
        notification["runaway_report_filed_at"] = clock
    store.touch(notification)

    if was_overdue and admission is not None:
        # "the program's overdue_notification_count falls by one and the program's
        # posture is recomputed"
        cascade.refresh_program_of(admission)
    # "The youth's risk_posture is recomputed on every resolution."
    cascade.refresh_youth(youth)
    return envelope.ok(serial.notification(notification))
