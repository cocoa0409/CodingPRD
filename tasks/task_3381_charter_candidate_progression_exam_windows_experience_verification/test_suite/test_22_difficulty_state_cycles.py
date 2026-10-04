"""Difficulty probe — non_linear_state_machine: the MisconductCase
sanction-appeal-dismissal cycle with suspension compensation, and the two
independent state dimensions on ExamAppointment."""
from datetime import datetime, timezone

from test_helpers import (
    adjudicate_case,
    appeal_case,
    book_appointment,
    check_in_appointment,
    create_candidate,
    create_enrolled_enrollment,
    get_appointment,
    get_attempt_for_appointment,
    get_candidate,
    open_external_case,
    open_incident_case,
    set_logical_clock,
    setup_bookable_context,
)

CLOCK = "2027-01-05T00:00:00Z"


def _parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _case_setup():
    """Candidate (ENROLLED) plus an external-report misconduct case opened by
    investigator inv-1; clock then advances to 2027-03-20."""
    set_logical_clock(CLOCK)
    candidate = create_candidate()
    create_enrolled_enrollment(candidate["id"])
    case = open_external_case(candidate["id"], investigator_user_id="inv-1")
    set_logical_clock("2027-03-20T00:00:00Z")
    return candidate, case


def _flagged_appointment_setup():
    """Booked appointment flagged POLICY_FLAGGED by a proctor-filed incident
    case while its booking dimension stays SCHEDULED."""
    context = setup_bookable_context()
    appointment = book_appointment(context, exam_date="2027-03-03", pay_fee=False)
    case = open_incident_case(
        context["candidate"]["id"],
        appointment["id"],
        allegation="Suspected unauthorized notes",
    )
    return context, appointment, case


class TestMisconductCaseCycle:
    def test_suspension_sanction_sets_suspended_until(self, api):
        """PRD §3.7: "A `SUSPENSION_12M` sets the candidate's `suspended_until`
        to the sanction instant plus 365 days."
        PRD §3.7: "The candidate's derived `conduct_standing` reads `REVOKED`
        whenever `conduct_revoked` is set, else `SUSPENDED` while
        `suspended_until` lies in the future relative to the logical clock, else
        `GOOD_STANDING`."

        Design: Difficulty/non_linear_state_machine/misconduct_case_sanction_appeal_cycle
        """
        candidate, case = _case_setup()
        sanctioned = adjudicate_case(
            case,
            outcome="SANCTIONED",
            sanction_type="SUSPENSION_12M",
            adjudicator_user_id="adj-1",
        )
        assert sanctioned["status"] == "SANCTIONED"
        after = get_candidate(candidate["id"])
        assert _parse_iso(after["suspended_until"]) == datetime(
            2028, 3, 19, tzinfo=timezone.utc
        )
        assert after["conduct_standing"] == "SUSPENDED"

    def test_dismissal_after_appeal_compensates(self, api):
        """PRD §3.7: "The sanctioned candidate — and only the candidate whose
        case it is — may appeal, moving the case from `SANCTIONED` to
        `APPEALED` (from anything else, `ERR_INVALID_CASE_STATE`)"
        PRD §3.7: "Compensation fires only when a prior sanction existed on this
        case: every attempt that case invalidated is reinstated — `INVALIDATED`
        to `REINSTATED`; `suspended_until` is cleared to `null`;
        `conduct_revoked` returns to false, with `charter_awarded` restored to
        true when this case's revocation had cleared it; and progression and
        curriculum access are recomputed, restoring what invalidation had
        removed."

        Design: Difficulty/non_linear_state_machine/misconduct_case_sanction_appeal_cycle
        """
        candidate, case = _case_setup()
        sanctioned = adjudicate_case(
            case,
            outcome="SANCTIONED",
            sanction_type="SUSPENSION_12M",
            adjudicator_user_id="adj-1",
        )
        assert sanctioned["status"] == "SANCTIONED"
        set_logical_clock("2027-03-25T00:00:00Z")
        appealed = appeal_case(case, candidate, appeal_reason="New evidence from employer")
        assert appealed["status"] == "APPEALED"
        assert appealed["version"] == case["version"] + 2
        dismissed = adjudicate_case(
            appealed,
            outcome="DISMISSED",
            adjudicator_user_id="adj-1",
        )
        assert dismissed["status"] == "DISMISSED"
        after = get_candidate(candidate["id"])
        assert after["suspended_until"] is None
        assert after["conduct_standing"] == "GOOD_STANDING"


class TestAppointmentParallelDimensions:
    def test_checkin_allowed_under_policy_flag(self, api):
        """PRD §3.7: "When an `appointment_id` is present the case reports an
        exam-day incident: its `origin` becomes `EXAM_INCIDENT` and the flagged
        appointment's `compliance_status` moves from `CLEAR` to
        `POLICY_FLAGGED`"
        PRD §3.5: "The appointment must be `SCHEDULED`
        (`ERR_APPOINTMENT_NOT_SCHEDULED`) — note that the appointment's
        `compliance_status` does **not** gate check-in — and the logical clock's
        calendar date must equal the appointment's `exam_date`
        (`ERR_CHECKIN_NOT_ON_EXAM_DATE`)."

        Design: Difficulty/non_linear_state_machine/appointment_booking_and_compliance_dimensions_are_independent
        """
        context, appointment, _case = _flagged_appointment_setup()
        flagged = get_appointment(appointment["id"])
        assert flagged["booking_status"] == "SCHEDULED"
        assert flagged["compliance_status"] == "POLICY_FLAGGED"
        updated, attempt = check_in_appointment(appointment, context["candidate"])
        assert updated["booking_status"] == "CHECKED_IN"
        assert updated["compliance_status"] == "POLICY_FLAGGED"
        assert attempt["id"] == get_attempt_for_appointment(appointment["id"])["id"]

    def test_dismissal_clears_compliance_not_booking(self, api):
        """PRD §3.7: "Dismissal, reachable from `OPENED` or `APPEALED`, closes
        the case `DISMISSED` and clears any flagged appointment's
        `compliance_status` to `CLEARED` — from `POLICY_FLAGGED` or from
        `CONFIRMED_VIOLATION` alike."

        Design: Difficulty/non_linear_state_machine/appointment_booking_and_compliance_dimensions_are_independent
        """
        context, appointment, case = _flagged_appointment_setup()
        check_in_appointment(appointment, context["candidate"])
        adjudicate_case(case, outcome="DISMISSED", adjudicator_user_id="adj-9")
        after = get_appointment(appointment["id"])
        assert after["compliance_status"] == "CLEARED"
        assert after["booking_status"] == "CHECKED_IN"
