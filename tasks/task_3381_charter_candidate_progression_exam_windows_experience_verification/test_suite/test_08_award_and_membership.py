"""The charter award gate chain (levels -> experience -> conduct statement ->
open case -> balance) and post-charter society membership: exact dues,
uniqueness, the calendar-year CE renewal gate, and the revocation cascade."""
from test_helpers import (
    DEFAULTS,
    THREE_WINDOWS_SPEC,
    ApiErrorId,
    adjudicate_case,
    book_checkin_score,
    create_candidate,
    create_enrolled_enrollment,
    create_enrollment_pending,
    create_society,
    create_test_center,
    create_three_levels,
    create_three_windows,
    experience_segment,
    file_conduct_statement,
    get_candidate,
    get_membership,
    get_program_enrollment,
    join_society,
    join_society_payload,
    list_memberships,
    make_candidate_headers,
    open_external_case,
    renew_membership_payload,
    set_logical_clock,
    setup_active_membership,
    setup_approved_submission,
    setup_charterholder,
    validate_error,
)


def _pass_all_levels(candidate, enrollment):
    """Drive the candidate to a boundary PASS at all three configured levels."""
    levels = create_three_levels()
    windows = create_three_windows(levels)
    center = create_test_center()
    for code in ("LEVEL_I", "LEVEL_II", "LEVEL_III"):
        spec = THREE_WINDOWS_SPEC[code]
        book_checkin_score(
            candidate,
            enrollment,
            windows[code],
            center,
            exam_date=spec["exam_date"],
            scaled_score=levels[code]["mps_scaled_score"],
            score_clock=spec["score_clock"],
        )
    return levels, windows, center


def _charter_ready(include_conduct_statement=True, experience_segments=None):
    """Candidate with an ENROLLED enrollment, all levels passed, and an
    APPROVED experience submission; optionally files the current-year PCS.
    The clock ends at 2027-08-17 (calendar year 2027)."""
    set_logical_clock(DEFAULTS["CLOCK_SETUP"])
    candidate = create_candidate()
    enrollment = create_enrolled_enrollment(candidate["id"])
    levels, windows, center = _pass_all_levels(candidate, enrollment)
    experience = setup_approved_submission(candidate, segments=experience_segments)
    if include_conduct_statement:
        file_conduct_statement(candidate, disclosure_year=2027)
    return {
        "candidate": candidate,
        "enrollment": enrollment,
        "levels": levels,
        "windows": windows,
        "center": center,
        "submission": experience["submission"],
        "candidate_headers": make_candidate_headers(candidate["id"]),
    }


class TestAwardGates:
    def test_award_from_pending_payment_rejected(self, api, program_admin_headers):
        """PRD §3.8: "The enrollment must be `ENROLLED`
        (`ERR_ENROLLMENT_NOT_ENROLLED`)."

        Design: Corner/state_machines/c_award_from_pending_payment_rejected
        """
        set_logical_clock(DEFAULTS["CLOCK_SETUP"])
        candidate = create_candidate()
        enrollment = create_enrollment_pending(candidate["id"])
        resp = api.award_charter(enrollment["id"], program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ENROLLED)
        assert resp.status_code == 409
        assert get_candidate(candidate["id"])["charter_awarded"] is False

    def test_award_gate_levels_checked_before_experience(self, api, program_admin_headers):
        """PRD §3.8: "The charter award is a `ProgramAdmin` act against a single
        enrollment, gated by six conditions evaluated in a fixed order."
        PRD §3.8: "The candidate must hold a passing attempt, of validity
        `VALID` or `REINSTATED`, for **every** configured exam level
        (`ERR_LEVELS_NOT_ALL_PASSED`). The sum of `committee_months` across the
        candidate's `APPROVED` submissions must reach at least 36 months
        (`ERR_EXPERIENCE_REQUIREMENT_UNMET`)."

        Design: Corner/validations/c_award_gate_levels_checked_before_experience
        """
        set_logical_clock(DEFAULTS["CLOCK_SETUP"])
        candidate = create_candidate()
        enrollment = create_enrolled_enrollment(candidate["id"])
        create_three_levels()
        resp = api.award_charter(enrollment["id"], program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_LEVELS_NOT_ALL_PASSED)
        assert resp.status_code == 422

    def test_award_with_insufficient_experience_rejected(self, api, program_admin_headers):
        """PRD §3.8: "The sum of `committee_months` across the candidate's
        `APPROVED` submissions must reach at least 36 months
        (`ERR_EXPERIENCE_REQUIREMENT_UNMET`)."

        Design: Corner/errors/c_award_with_insufficient_experience_rejected
        """
        context = _charter_ready(experience_segments=[experience_segment()])
        assert context["submission"]["status"] == "APPROVED"
        assert context["submission"]["committee_months"] == 12
        resp = api.award_charter(context["enrollment"]["id"], program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_EXPERIENCE_REQUIREMENT_UNMET)
        assert resp.status_code == 422
        assert (
            get_candidate(context["candidate"]["id"])["charter_awarded"] is False
        )

    def test_award_without_conduct_statement_rejected(self, api, program_admin_headers):
        """PRD §3.8: "The candidate's `conduct_statements` must contain an entry
        whose `disclosure_year` equals the logical clock's current calendar year
        (`ERR_MISSING_CONDUCT_STATEMENT`)."

        Design: Corner/errors/c_award_without_conduct_statement_rejected
        """
        context = _charter_ready(include_conduct_statement=False)
        resp = api.award_charter(context["enrollment"]["id"], program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_CONDUCT_STATEMENT)
        assert resp.status_code == 422
        assert (
            get_candidate(context["candidate"]["id"])["charter_awarded"] is False
        )

    def test_award_with_open_case_rejected(self, api, program_admin_headers):
        """PRD §3.8: "No misconduct case for the candidate may stand in `OPENED`
        or `APPEALED` (`ERR_OPEN_MISCONDUCT_CASE`)."

        Design: Corner/errors/c_award_with_open_case_rejected
        """
        context = _charter_ready()
        open_external_case(
            context["candidate"]["id"], allegation="Pending external complaint"
        )
        resp = api.award_charter(context["enrollment"]["id"], program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_MISCONDUCT_CASE)
        assert resp.status_code == 409
        assert (
            get_candidate(context["candidate"]["id"])["charter_awarded"] is False
        )


class TestMembership:
    def test_wrong_dues_amount_rejected(self, api):
        """PRD §3.9: "the join supplies the `candidate_id` in the body under the
        society in the path, and dues are exact — `dues_payment_cents` must
        equal the society's `annual_dues_cents` to the cent, else
        `ERR_INCORRECT_DUES_AMOUNT`."
        PRD §3.9: "A new membership opens `ACTIVE` with `paid_through_year` set
        to the logical clock's current calendar year and an empty `ce_records`
        list."

        Design: Corner/errors/c_wrong_dues_amount_rejected
        """
        context = setup_charterholder()
        society = create_society()
        short = api.create_membership(
            society["id"],
            join_society_payload(context["candidate"]["id"], 27499),
            context["candidate_headers"],
        )
        validate_error(short, ApiErrorId.ERR_INCORRECT_DUES_AMOUNT)
        assert short.status_code == 422
        membership = join_society(society, context["candidate"])
        assert membership["status"] == "ACTIVE"
        assert membership["paid_through_year"] == 2027
        rows = list_memberships(params={"candidate_id": context["candidate"]["id"]})
        assert len(rows) == 1

    def test_duplicate_membership_rejected(self, api):
        """PRD §3.9: "Joining requires the candidate's `charter_awarded` to be
        true (`ERR_CHARTER_REQUIRED`), and a candidate may hold only one
        `ACTIVE` membership per society (`ERR_DUPLICATE_MEMBERSHIP`)."

        Design: Corner/errors/c_duplicate_membership_rejected
        """
        context = setup_active_membership()
        resp = api.create_membership(
            context["society"]["id"],
            join_society_payload(
                context["candidate"]["id"],
                context["society"]["annual_dues_cents"],
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)
        assert resp.status_code == 409
        rows = list_memberships(
            params={
                "candidate_id": context["candidate"]["id"],
                "society_id": context["society"]["id"],
            }
        )
        assert len(rows) == 1

    def test_renew_without_ce_credits_rejected(self, api):
        """PRD §3.9: "Renewal advances the membership one calendar year and uses
        the **calendar-year** variant only: the membership must be `ACTIVE`
        (`ERR_INVALID_MEMBERSHIP_STATE`), its `calendar_year_credits` for the
        current clock year must meet the society's requirement
        (`ERR_CE_REQUIREMENT_NOT_MET`), and the dues payment must again match
        exactly (`ERR_INCORRECT_DUES_AMOUNT`)."

        Design: Corner/errors/c_renew_without_ce_credits_rejected
        """
        context = setup_active_membership()
        membership = context["membership"]
        resp = api.renew_membership(
            membership["id"],
            renew_membership_payload(context["society"]["annual_dues_cents"]),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CE_REQUIREMENT_NOT_MET)
        assert resp.status_code == 422
        assert get_membership(membership["id"])["paid_through_year"] == 2027

    def test_charter_revocation_terminates_memberships(self, api):
        """PRD §3.7: "A `CHARTER_REVOCATION` clears the candidate's
        `charter_awarded` to false, sets `conduct_revoked` true, and terminates
        every `ACTIVE` society membership the candidate holds — `ACTIVE` to
        `TERMINATED`."
        PRD §3.7: "The candidate's derived `conduct_standing` reads `REVOKED`
        whenever `conduct_revoked` is set, else `SUSPENDED` while
        `suspended_until` lies in the future relative to the logical clock, else
        `GOOD_STANDING`."
        PRD §3.9: "the membership must be `ACTIVE`
        (`ERR_INVALID_MEMBERSHIP_STATE`)"

        Design: Corner/cross_cutting_layers/c_charter_revocation_terminates_memberships
        """
        context = setup_active_membership()
        case = open_external_case(
            context["candidate"]["id"], allegation="Confirmed ethics violation"
        )
        adjudicate_case(
            case,
            outcome="SANCTIONED",
            sanction_type="CHARTER_REVOCATION",
            adjudicator_user_id="adj-1",
        )
        candidate = get_candidate(context["candidate"]["id"])
        assert candidate["charter_awarded"] is False
        assert candidate["conduct_standing"] == "REVOKED"
        membership = get_membership(context["membership"]["id"])
        assert membership["status"] == "TERMINATED"
        renew = api.renew_membership(
            membership["id"],
            renew_membership_payload(context["society"]["annual_dues_cents"]),
            context["candidate_headers"],
        )
        validate_error(renew, ApiErrorId.ERR_INVALID_MEMBERSHIP_STATE)
        assert renew.status_code == 409
        enrollment = get_program_enrollment(context["enrollment"]["id"])
        assert enrollment["status"] == "CHARTER_AWARDED"
