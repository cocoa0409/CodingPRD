"""Guided-therapy operations, consult scheduling and the weekly sweep.

Sources: SCAFFOLD 1.2 state machines M6-M9, 1.3 `adherence_rate_restricted`,
`dropout_risk_score`, `spine_red_flags_weight`, `review_reconciliation_ladder`;
PRD 3.2, 3.4, 3.5.
"""

from datetime import timedelta

from db import STORE, create, member_red_flag_weight
from errors import ApiError, invalid_reference, invalid_state
from services import billing, common, intake
from utils import d, fmt, parse_iso, round2, week_of

REVIEW_LAPSE_DAYS = 7
NO_ENGAGEMENT_STALE_DAYS = 14
ESCALATION_THRESHOLD = d("0.30")


# ---------------------------------------------------------------------------
# M6 -- ExerciseSession
# ---------------------------------------------------------------------------
def session(ident):
    return STORE.need("ExerciseSession", ident, "ExerciseSession")


def book_session(enrollment_id, payload):
    item = intake.enrollment(enrollment_id)
    if item["enrollment_status"] == "ACTIVATION_FAILED":
        raise ApiError(
            "ERR_SESSION_ACTIVATION_FAILED",
            "An enrollment in ACTIVATION_FAILED cannot take new work.",
        )
    session_week = payload.get("session_week")
    if session_week is None:
        raise invalid_reference("session_week is required.")
    session_week = int(session_week)
    session_date = parse_iso(payload.get("session_date"))
    if session_date is None:
        raise invalid_reference("session_date must be an ISO 8601 instant.")
    if week_of(session_date) != session_week:
        raise invalid_reference(
            "session_week must equal the week_index of session_date."
        )
    for existing in common.sessions_of(enrollment_id):
        if existing["session_week"] == session_week:
            raise ApiError(
                "ERR_WEEK_ALREADY_SCHEDULED",
                "This enrollment already carries a session in that ISO week.",
            )
    recorded_via = payload.get("recorded_via")
    if recorded_via not in ("SENSOR", "CAMERA"):
        raise invalid_reference("recorded_via must be SENSOR or CAMERA.")
    row = create("ExerciseSession", {
        "enrollment_id": enrollment_id,
        "session_date": fmt(session_date),
        "session_week": session_week,
        "recorded_via": recorded_via,
        "session_status": "SCHEDULED",
        "planned_reps": int(payload.get("planned_reps", 0)),
        "completed_reps": 0,
        "planned_minutes": int(payload.get("planned_minutes", 0)),
        "completed_minutes": 0,
        "pain_score_before": 0.0,
        "scheduled_send_at": fmt(STORE.clock),
        "pain_score_after": payload.get("pain_score_after"),
        "track_restricted": bool(payload.get("track_restricted", False)),
        "adherence_numerator": 0.0,
        "adherence_denominator": 2.0 if payload.get("track_restricted") else 1.0,
    })
    STORE.touch("Enrollment", item)
    return row


def complete_session(session_id, payload, acting_member_id=None):
    row = session(session_id)
    item = intake.enrollment(row["enrollment_id"])
    if row["session_status"] == "MISSED":
        raise invalid_state("A missed session can never be completed retroactively.")
    if row["session_status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED session can be completed.")
    if item["enrollment_status"] != "ACTIVE":
        raise invalid_state("The enrollment must be ACTIVE to credit a session.")
    if row["session_week"] != week_of(STORE.clock):
        raise ApiError(
            "ERR_SESSION_WEEK_CLOSED",
            "A session can only be completed inside the week it was booked into.",
        )
    if payload.get("pain_score_after") is None:
        raise invalid_reference("pain_score_after must be supplied.")
    after = d(payload["pain_score_after"])
    if after < 0 or after > 10:
        raise ApiError(
            "ERR_VITALS_OUT_OF_RANGE", "pain_score_after must be within [0, 10]."
        )
    before = common.current_pain_score(item)
    if after > before + d("2.0"):
        raise ApiError(
            "ERR_PAIN_WORSENED",
            "The reported pain is worse than the pre-session score.",
        )

    units = d(payload.get("completed_denominator_units", 0))
    if units < 0:
        raise invalid_reference("completed_denominator_units must not be negative.")
    bonus = d("1.0") if after <= before else d("0.0")
    row["session_status"] = "COMPLETED"
    row["completed_reps"] = row["planned_reps"]
    row["completed_minutes"] = row["planned_minutes"]
    row["pain_score_before"] = float(before)
    row["pain_score_after"] = float(after)
    row["adherence_numerator"] = min(d("1.0"), units + bonus)
    row["adherence_denominator"] = d("2.0") if row["track_restricted"] else d("1.0")
    row["adherence_numerator"] = float(row["adherence_numerator"])
    row["adherence_denominator"] = float(row["adherence_denominator"])
    STORE.touch("ExerciseSession", row)
    # A member-sourced completion never moves the member-sourced risk score.
    common.recompute_projection(item)
    STORE.touch("Enrollment", item)
    return row


def weekly_transition(session_id, payload):
    row = session(session_id)
    item = intake.enrollment(row["enrollment_id"])
    named = payload.get("session_week")
    if named is not None and int(named) != row["session_week"]:
        raise invalid_reference(
            "session_week names a different week than the session is booked into."
        )
    if row["session_status"] == "SCHEDULED" and row[
        "session_week"
    ] < week_of(STORE.clock):
        row["session_status"] = "MISSED"
        row["adherence_numerator"] = 0.0
        STORE.touch("ExerciseSession", row)
        common.recompute_adherence(item)
    else:
        STORE.touch("ExerciseSession", row)
    STORE.touch("Enrollment", item)
    return row


# ---------------------------------------------------------------------------
# M7 -- OutreachContact
# ---------------------------------------------------------------------------
def contact(ident):
    return STORE.need("OutreachContact", ident, "OutreachContact")


def weekly_outreach_requirement(item):
    since = parse_iso(item.get("review_pending_since"))
    if since is None:
        return 1
    held = int((STORE.clock - since).total_seconds() // (7 * 86400))
    return 2 if held >= 1 else 1


def queue_outreach(payload):
    item = intake.enrollment(payload.get("enrollment_id"))
    week = payload.get("contact_week")
    if week is None:
        raise invalid_reference("contact_week is required.")
    week = int(week)
    if week < 1 or week > 4:
        raise ApiError(
            "ERR_OUTREACH_WINDOW_CLOSED",
            "Outreach contacts are only available in weeks 1 through 4.",
        )
    if week < week_of(STORE.clock):
        raise ApiError(
            "ERR_OUTREACH_WEEK_LAPSED",
            "That outreach week has already passed.",
        )
    channel = payload.get("channel")
    if channel not in ("PUSH", "SMS", "PHONE"):
        raise invalid_reference("channel must be PUSH, SMS or PHONE.")
    required = weekly_outreach_requirement(item)
    existing = [o for o in common.outreach_of(item["id"])
                if o["contact_week"] == week]
    if len(existing) >= required:
        raise ApiError(
            "ERR_OUTREACH_CONTACT_LIMIT",
            "The weekly outreach requirement for that week is already satisfied.",
        )
    supplied = parse_iso(payload.get("contact_occurred_at"))
    row = create("OutreachContact", {
        "enrollment_id": item["id"],
        "contact_week": week,
        "channel": channel,
        "contact_occurred_at": fmt(supplied) if supplied else None,
        "outreach_status": "QUEUED",
        "scheduled_send_at": fmt(STORE.clock),
    })
    STORE.touch("Enrollment", item)
    return row


def deliver_outreach(contact_id):
    row = contact(contact_id)
    item = intake.enrollment(row["enrollment_id"])
    if row["outreach_status"] != "QUEUED":
        raise invalid_state("An outreach contact cannot be re-delivered.")
    if item["enrollment_status"] != "ACTIVE":
        raise invalid_state("The enrollment must be ACTIVE to deliver outreach.")
    if row["contact_week"] != week_of(STORE.clock):
        raise invalid_state(
            "Outreach can only be delivered inside the week it was queued for."
        )
    if common.consecutive_missed(item) > 3:
        raise invalid_state("The member has missed more than three sessions.")
    supplied = parse_iso(row.get("contact_occurred_at"))
    # The week's inclusivity cut is the smaller of the sender-supplied instant
    # and the current logical clock instant.
    cut = min(supplied, STORE.clock) if supplied else STORE.clock
    row["outreach_status"] = "DELIVERED"
    row["contact_occurred_at"] = fmt(cut)
    STORE.touch("OutreachContact", row)
    STORE.touch("Enrollment", item)
    return row


# ---------------------------------------------------------------------------
# M8 -- Clinician
# ---------------------------------------------------------------------------
def create_clinician(payload):
    discipline = payload.get("discipline")
    if discipline not in ("PHYSICAL_THERAPIST", "PHYSICIAN"):
        raise invalid_reference("discipline is not recognised.")
    from db import new_record

    row = new_record("Clinician", {
        "full_name": payload.get("full_name"),
        "discipline": discipline,
        "license_number": payload.get("license_number"),
        "clinician_status": "AVAILABLE",
        "weekly_capacity_slots": int(payload.get("weekly_capacity_slots", 0)),
        "weekly_completed_minutes": 0,
        "weekly_scheduled_minutes": 0,
    })
    STORE.insert("Clinician", row)
    return row


def limit_clinician(clinician_id):
    row = intake.clinician(clinician_id)
    if row["clinician_status"] != "AVAILABLE":
        raise invalid_state("Only an AVAILABLE clinician can be limited.")
    row["clinician_status"] = "LIMITED"
    STORE.touch("Clinician", row)
    return row


def restore_clinician(clinician_id):
    row = intake.clinician(clinician_id)
    if row["clinician_status"] != "LIMITED":
        raise invalid_state("Only a LIMITED clinician can be restored.")
    row["clinician_status"] = "AVAILABLE"
    STORE.touch("Clinician", row)
    return row


def deactivate_clinician(clinician_id):
    """Deactivate, having first cancelled every scheduled consult."""
    row = intake.clinician(clinician_id)
    if row["clinician_status"] == "DEACTIVATED":
        raise invalid_state("This clinician is already deactivated.")
    deactivate_appointments(row)
    row["clinician_status"] = "DEACTIVATED"
    STORE.touch("Clinician", row)
    return row


# ---------------------------------------------------------------------------
# M9 -- Appointment
# ---------------------------------------------------------------------------
def appointment(ident):
    return STORE.need("Appointment", ident, "Appointment")


def _block(start_minute):
    return start_minute // 60


def book_appointment(payload):
    item = intake.enrollment(payload.get("enrollment_id"))
    clinician_row = intake.clinician(payload.get("clinician_id"))
    # Constraint 1 of the three booking constraints is clinician availability and
    # existence, evaluated before the timeline geometry and the weekly capacity
    # checks (PRD 3.4).  Deactivation is terminal, so a DEACTIVATED clinician can
    # never take a consult.
    if clinician_row["clinician_status"] == "DEACTIVATED":
        raise invalid_reference(
            "A deactivated clinician cannot take a new consult."
        )
    date = parse_iso(payload.get("appointment_date"))
    if date is None:
        raise invalid_reference("appointment_date must be an ISO 8601 date.")
    start_minute = int(payload.get("start_minute", 0))
    if start_minute < 0 or start_minute > 1439:
        raise invalid_reference("start_minute must lie within [0, 1439].")
    duration = int(payload.get("duration_minutes", 0))
    if duration < 15 or duration > 120:
        raise invalid_reference("duration_minutes must lie within [15, 120].")
    slot_type = payload.get("slot_type")
    if slot_type not in ("INITIAL_CONSULT", "FOLLOW_UP"):
        raise invalid_reference("slot_type is not recognised.")

    same_day = [a for a in STORE.all("Appointment")
                if a["clinician_id"] == clinician_row["id"]
                and a["appointment_date"] == fmt(date)
                and a["appointment_status"] != "CANCELLED"]
    for other in same_day:
        if abs(int(other["start_minute"]) - start_minute) < 60:
            raise ApiError(
                "ERR_APPOINTMENT_OVERLAP",
                "Consults on one clinician's day must start at least 60 minutes apart.",
            )
        other_block = _block(int(other["start_minute"]))
        if other_block == _block(start_minute):
            raise ApiError(
                "ERR_APPOINTMENT_OVERLAP",
                "That 60-minute block is already occupied on this clinician's day.",
            )

    week = week_of(date)
    scheduled = 0
    for a in STORE.all("Appointment"):
        if a["clinician_id"] != clinician_row["id"]:
            continue
        if a["appointment_status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if week_of(parse_iso(a["appointment_date"])) != week:
            continue
        scheduled += int(a["duration_minutes"])
    cap = int(clinician_row["weekly_capacity_slots"]) * 60
    if scheduled + duration > cap:
        raise ApiError(
            "ERR_CLINICIAN_CAPACITY_EXCEEDED",
            "This booking exceeds the clinician's weekly capacity.",
        )

    row = create("Appointment", {
        "enrollment_id": item["id"],
        "clinician_id": clinician_row["id"],
        "appointment_date": fmt(date),
        "start_minute": start_minute,
        "duration_minutes": duration,
        "slot_type": slot_type,
        "appointment_status": "SCHEDULED",
        "cancelled_at": None,
    })
    refresh_clinician_minutes(clinician_row)
    STORE.touch("Clinician", clinician_row)
    return row


def refresh_clinician_minutes(clinician_row, week=None):
    """Derived minute totals for one ISO week of this clinician's timeline.

    `weekly_completed_minutes` sums `duration_minutes` over COMPLETED consults
    in the week, and `weekly_scheduled_minutes` over SCHEDULED and COMPLETED
    consults in the same week (PRD 3.4).  The week defaults to the most recent
    consult touched on this clinician's timeline.
    """
    if week is None:
        weeks = sorted(
            week_of(parse_iso(a["appointment_date"]))
            for a in STORE.all("Appointment")
            if a["clinician_id"] == clinician_row["id"]
            and parse_iso(a["appointment_date"]) is not None
        )
        week = weeks[-1] if weeks else week_of(STORE.clock)
    completed = 0
    scheduled = 0
    for a in STORE.all("Appointment"):
        if a["clinician_id"] != clinician_row["id"]:
            continue
        date = parse_iso(a["appointment_date"])
        if date is None or week_of(date) != week:
            continue
        if a["appointment_status"] == "COMPLETED":
            completed += int(a["duration_minutes"])
        if a["appointment_status"] in ("SCHEDULED", "COMPLETED"):
            scheduled += int(a["duration_minutes"])
    clinician_row["weekly_completed_minutes"] = completed
    clinician_row["weekly_scheduled_minutes"] = scheduled
    return clinician_row


def deactivate_appointments(clinician_row):
    """Cancel every scheduled consult and cascade the pain revert."""
    for row in STORE.all("Appointment"):
        if row["clinician_id"] != clinician_row["id"]:
            continue
        if row["appointment_status"] != "SCHEDULED":
            continue
        row["appointment_status"] = "CANCELLED"
        row["cancelled_at"] = fmt(STORE.clock)
        STORE.touch("Appointment", row)
        item = STORE.get("Enrollment", row["enrollment_id"])
        if item is not None:
            item["pain_reduction_points"] = 0.0
            item["consult_cancellation_count"] = (
                item.get("consult_cancellation_count") or 0
            ) + 1
            STORE.touch("Enrollment", item)
    return clinician_row


def cancel_appointment(appointment_id):
    row = appointment(appointment_id)
    if row["appointment_status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED consult can be cancelled.")
    row["appointment_status"] = "CANCELLED"
    row["cancelled_at"] = fmt(STORE.clock)
    STORE.touch("Appointment", row)
    item = STORE.get("Enrollment", row["enrollment_id"])
    if item is not None:
        item["consult_cancellation_count"] = (
            item.get("consult_cancellation_count") or 0
        ) + 1
        STORE.touch("Enrollment", item)
    return row


def complete_appointment(appointment_id, payload=None):
    row = appointment(appointment_id)
    if row["appointment_status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED consult can be completed.")
    start = parse_iso(row["appointment_date"]) + timedelta(
        minutes=int(row["start_minute"])
    )
    if start > STORE.clock:
        raise invalid_state("A consult whose start has not arrived cannot complete.")
    row["appointment_status"] = "COMPLETED"
    STORE.touch("Appointment", row)
    clinician_row = STORE.get("Clinician", row["clinician_id"])
    if clinician_row is not None:
        refresh_clinician_minutes(clinician_row)
        STORE.touch("Clinician", clinician_row)
    return row


# ---------------------------------------------------------------------------
# spine_red_flags_weight
# ---------------------------------------------------------------------------
def spine_red_flags(client_id, weeks):
    client_row = intake.client(client_id)
    total = 0
    for member_row in STORE.all("Member"):
        if member_row["client_account_id"] != client_id:
            continue
        if member_row["member_status"] not in ("ELIGIBLE", "ENROLLED"):
            continue
        if member_row["musculo_condition_code"] not in ("LOW_BACK", "NECK"):
            continue
        weight = member_red_flag_weight(member_row)
        member_row["red_flag_weight"] = weight
        for week in weeks:
            # Strictly-greater: a member landing exactly on 0.30 is not escalated.
            if d(weight) > ESCALATION_THRESHOLD:
                member_row["coach_escalated"] = True
                member_row["last_escalated_week"] = week
                client_row["red_flag_escalation_count"] = (
                    client_row.get("red_flag_escalation_count") or 0
                ) + 1
                STORE.touch("Member", member_row)
    return total


# ---------------------------------------------------------------------------
# review_reconciliation_ladder
# ---------------------------------------------------------------------------
def reconcile_reviews(client_id=None):
    """The chronological review ladder; idempotent on a second call."""
    ordered = []
    for item in STORE.all("Enrollment"):
        if item.get("review_pending_since") is None:
            continue
        if client_id is not None:
            owner = STORE.get("Member", item["member_id"])
            if not owner or owner["client_account_id"] != client_id:
                continue
        ordered.append(item)
    ordered.sort(key=lambda e: (e["review_pending_since"], e["created_at"], e["id"]))

    reconciled = 0
    accelerated = 0
    activation_failed = 0
    for item in ordered:
        # Step 2 -- conduct reviews that were seeded and never conducted.
        lapsed_reviews = []
        for review_row in STORE.all("ClinicalReview"):
            if review_row["enrollment_id"] != item["id"]:
                continue
            if review_row["review_status"] != "SUBMITTED":
                continue
            opened = parse_iso(review_row["review_opened_at"])
            if opened is None:
                continue
            if opened + timedelta(days=REVIEW_LAPSE_DAYS) <= STORE.clock:
                lapsed_reviews.append(review_row)
        lapsed_reviews.sort(key=lambda r: (r["review_opened_at"], r["created_at"]))
        for review_row in lapsed_reviews:
            review_row["review_status"] = "CONDUCTED"
            review_row["review_decision"] = "REJECT"
            review_row["conducted_at"] = fmt(STORE.clock)
            STORE.touch("ClinicalReview", review_row)
            if item.get("clinical_review_outcome") is None:
                item["clinical_review_outcome"] = "REJECTED"
                STORE.touch("Enrollment", item)
            accelerated += 1
            reconciled += 1

        # Step 3 -- retire stale NO_ENGAGEMENT reviews.
        if item["enrollment_status"] in (
            "PENDING_SCREENING", "PENDING_CLINICAL_REVIEW"
        ) and item.get("transition_reason") == "NO_ENGAGEMENT":
            created = parse_iso(item["created_at"])
            if created is not None and created < STORE.clock - timedelta(
                days=NO_ENGAGEMENT_STALE_DAYS
            ):
                item["enrollment_status"] = "ACTIVATION_FAILED"
                STORE.touch("Enrollment", item)
                activation_failed += 1
                reconciled += 1

    # Step 4 -- pick up roster files nobody screened.
    screened = 0
    for file_row in STORE.all("EligibilityFile"):
        if file_row["file_status"] != "INGESTED":
            continue
        if client_id is not None and file_row["client_account_id"] != client_id:
            continue
        created = parse_iso(file_row["created_at"])
        if created is None:
            continue
        if created + timedelta(days=REVIEW_LAPSE_DAYS) <= STORE.clock:
            intake.screen_eligibility_file(file_row["id"])
            screened += 1

    return {
        "reconciled_enrollment_count": reconciled,
        "accelerated_enrollment_count": accelerated,
        "activation_failed_count": activation_failed,
        "screened_file_count": screened,
    }


def weekly_reconciliation(client_id):
    client_row = intake.client(client_id)
    previous = STORE.client_cursor(client_id)
    # The sweep advances the client's shared week-schedule cursor by exactly
    # one week; it also never lags that client's week-scoped work, so a client
    # whose clock has been moved forward catches its cursor up to the week its
    # own scheduled sessions and outreach already sit in before the cut runs.
    pending_weeks = [1]
    for row in STORE.all("ExerciseSession"):
        if row["session_status"] != "SCHEDULED":
            continue
        item = STORE.get("Enrollment", row["enrollment_id"])
        owner = STORE.get("Member", item["member_id"]) if item else None
        if owner and owner["client_account_id"] == client_id:
            pending_weeks.append(row["session_week"])
    for row in STORE.all("OutreachContact"):
        if row["outreach_status"] != "QUEUED":
            continue
        item = STORE.get("Enrollment", row["enrollment_id"])
        owner = STORE.get("Member", item["member_id"]) if item else None
        if owner and owner["client_account_id"] == client_id:
            pending_weeks.append(row["contact_week"])
    new_cursor = max(previous + 1, week_of(STORE.clock), max(pending_weeks) + 1)
    STORE.set_client_cursor(client_id, new_cursor)
    client_row["week_schedule_cursor"] = new_cursor

    touched_enrollments = set()

    missed = 0
    for row in STORE.all("ExerciseSession"):
        if row["session_status"] != "SCHEDULED":
            continue
        item = STORE.get("Enrollment", row["enrollment_id"])
        if item is None:
            continue
        owner = STORE.get("Member", item["member_id"])
        if not owner or owner["client_account_id"] != client_id:
            continue
        if row["session_week"] >= new_cursor:
            continue
        row["session_status"] = "MISSED"
        row["adherence_numerator"] = 0.0
        STORE.touch("ExerciseSession", row)
        missed += 1
        touched_enrollments.add(item["id"])

    lapsed = 0
    for row in STORE.all("OutreachContact"):
        if row["outreach_status"] != "QUEUED":
            continue
        item = STORE.get("Enrollment", row["enrollment_id"])
        if item is None:
            continue
        owner = STORE.get("Member", item["member_id"])
        if not owner or owner["client_account_id"] != client_id:
            continue
        if row["contact_week"] >= new_cursor:
            continue
        row["outreach_status"] = "FAILED"
        STORE.touch("OutreachContact", row)
        lapsed += 1
        touched_enrollments.add(item["id"])

    no_shows = 0
    for row in STORE.all("Appointment"):
        if row["appointment_status"] != "SCHEDULED":
            continue
        item = STORE.get("Enrollment", row["enrollment_id"])
        if item is None:
            continue
        owner = STORE.get("Member", item["member_id"])
        if not owner or owner["client_account_id"] != client_id:
            continue
        start = parse_iso(row["appointment_date"]) + timedelta(
            minutes=int(row["start_minute"])
        )
        if start < STORE.clock:
            row["appointment_status"] = "NO_SHOW"
            STORE.touch("Appointment", row)
            item["pain_reduction_points"] = 0.0
            item["function_gain_points"] = 0.0
            STORE.touch("Enrollment", item)
            no_shows += 1

    # The weekly reconciliation recomputes every enrollment's week-scoped
    # measures, not only those a cut happened to touch: the week's history has
    # moved on for all of them.
    for item in STORE.all("Enrollment"):
        owner = STORE.get("Member", item["member_id"])
        if not owner or owner["client_account_id"] != client_id:
            continue
        if item["enrollment_status"] != "ACTIVE":
            continue
        # Only enrollments that actually carry session or outreach history take
        # part in the week's reconciliation: the model is driven by observed
        # traffic, so an enrollment with nothing recorded is left untouched.
        if not (common.sessions_of(item["id"]) or common.outreach_of(item["id"])):
            continue
        common.recompute_adherence(item)
        common.recompute_weeks_active(item)
        common.recompute_milestone(item)
        common.recompute_risk(item)
        common.recompute_risk(item)
        STORE.touch("Enrollment", item)

    ladder = reconcile_reviews(client_id)

    weeks = list(range(previous + 1, new_cursor + 1)) or [new_cursor]
    spine_red_flags(client_id, weeks)

    STORE.touch("ClientAccount", client_row)
    billing.refresh_draft_invoices(client_id)

    return {
        "advanced_week_index": new_cursor,
        "missed_session_count": missed,
        "lapsed_outreach_count": lapsed,
        "no_show_count": no_shows,
        "activation_failed_count": ladder["activation_failed_count"],
        "screened_file_count": ladder["screened_file_count"],
    }