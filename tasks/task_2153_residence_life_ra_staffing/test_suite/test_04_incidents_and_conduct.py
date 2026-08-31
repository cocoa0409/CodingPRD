"""Incident triage, conduct adjudication and the sanction cascade."""
from test_helpers import (
    ApiErrorId,
    assert_conduct_standing_derived,
    assert_timestamp_equals,
    create_incident_report_payload,
    create_student,
    read_break_housing_request,
    read_conduct_case,
    read_incident_report,
    read_room,
    read_room_change_case,
    read_student,
    route_and_sanction,
    route_incident_to_conduct,
    sanction_conduct_case,
    setup_certified_ra_with_rooms,
    setup_incident_report_at_return_cap,
    setup_repeat_offender_awaiting_second_decision,
    setup_routed_conduct_case,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSanctionCascade:
    def test_repeat_multiplier_drives_the_respondent_onto_probation(
        self, api, second_conduct_officer_headers
    ):
        """PRD §3.5: "A repeat multiplier is then formed as one plus one half for each
        prior sanctioned case, capped at two and a half; a respondent with no priors
        carries a multiplier of exactly one, one prior gives one and a half, two priors
        give two, and three or more priors are all held at the cap of two and a half."
        PRD §3.5: "**Link two:** the respondent's `conduct_standing` is re-derived from
        that total — `SUSPENDED` once `conduct_points` reaches 20 or more, otherwise
        `PROBATION` once it reaches 12 or more, otherwise `GOOD`."

        Design: Difficulty/transitive_cascade/conduct_sanction_probation_then_placement_denied_then_break_revoked
        """
        base = setup_repeat_offender_awaiting_second_decision()

        decided = validate_success(
            api.decide_conduct_case(
                base["second_conduct_case"]["id"],
                {"outcome": "SANCTION"},
                second_conduct_officer_headers,
            )
        )

        assert read_conduct_case(base["first_conduct_case"]["id"])["sanction_points"] == 5
        assert decided["prior_sanctioned_count"] == 1
        assert decided["sanction_points"] == 14, (
            f"SEVERE base 9 times the one-prior multiplier 1.5 rounds half-up to 14, "
            f"got {decided['sanction_points']}"
        )
        assert decided["status"] == "SANCTIONED"
        respondent = read_student(base["respondent"]["id"])
        assert respondent["conduct_points"] == 19
        assert respondent["conduct_standing"] == "PROBATION"
        assert_conduct_standing_derived(respondent)

    def test_probation_denies_the_room_change_case_and_revokes_the_break_stay(
        self, api, second_conduct_officer_headers
    ):
        """PRD §3.5: "**Link three:** a respondent who has just landed in `PROBATION`
        or `SUSPENDED` has `break_housing_eligible` set to false, and every room-change
        case of theirs whose `placement_status` is `REQUESTED` is moved to `DENIED`."
        PRD §3.5: "**Link four:** that loss of break-housing eligibility moves every
        break-housing request of theirs whose status is `REQUESTED` or `APPROVED` to
        `REVOKED`, stamping `revocation_cause` as `CONDUCT_INELIGIBLE`."
        PRD §3.5: "Alongside the cascade, the originating report bubbles up from
        `ROUTED_TO_CONDUCT` to `CLOSED_ADJUDICATED`, and the respondent's
        `judicial_hold` returns to false once no other case of theirs remains `OPEN` or
        `HEARING_SCHEDULED`."

        Design: Difficulty/transitive_cascade/conduct_sanction_probation_then_placement_denied_then_break_revoked
        """
        base = setup_repeat_offender_awaiting_second_decision()

        validate_success(
            api.decide_conduct_case(
                base["second_conduct_case"]["id"],
                {"outcome": "SANCTION"},
                second_conduct_officer_headers,
            )
        )

        respondent = read_student(base["respondent"]["id"])
        assert respondent["break_housing_eligible"] is False
        assert respondent["judicial_hold"] is False
        assert read_room_change_case(base["room_change_case"]["id"])["placement_status"] == "DENIED"
        stay = read_break_housing_request(base["stay"]["id"])
        assert stay["status"] == "REVOKED"
        assert stay["revocation_cause"] == "CONDUCT_INELIGIBLE"
        assert read_incident_report(base["second_report"]["id"])["status"] == "CLOSED_ADJUDICATED"
        assert read_room(base["room_202"]["id"])["break_hold_count"] == 0


def test_repeat_multiplier_walks_one_then_one_and_a_half_then_two(api, director_headers):
    """PRD §3.5: "The base figure comes from the case's own `severity`: two points for
    `MINOR`, five for `MODERATE`, nine for `SEVERE`."
    PRD §3.5: "`prior_sanctioned_count` is the number of *other* conduct cases naming
    the same respondent whose status is already `SANCTIONED`, evaluated at the moment
    of decision — so the order in which a respondent's cases are decided changes the
    arithmetic."
    PRD §3.5: "**Link one:** the respondent's `conduct_points` is increased by the
    newly computed `sanction_points`; the running total is always the sum of
    `sanction_points` over that respondent's `SANCTIONED` cases, and dismissed or
    still-open cases never contribute."

    Design: Corner/calculations/conduct_sanction_points_scale_with_prior_sanctioned_count
    """
    base = setup_certified_ra_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": 2}]
    )
    room_id = base["rooms"][0]["id"]
    subject = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )
    minor = {"severity": "MINOR", "policy_code": "NOISE"}

    first = route_and_sanction(
        base["ra_headers"], room_id, subject["id"], "2026-08-03T10:00:00Z",
        occurred_at="2026-07-20T22:00:00Z",
        narrative="Door propped open with a fire extinguisher, first offence.", **minor,
    )
    second = route_and_sanction(
        base["ra_headers"], room_id, subject["id"], "2026-08-04T10:00:00Z",
        occurred_at="2026-07-22T22:00:00Z",
        narrative="Second propped door on the same stairwell landing.", **minor,
    )
    third_routed = route_incident_to_conduct(
        base["ra_headers"], room_id, subject["id"],
        occurred_at="2026-07-24T22:00:00Z",
        narrative="Third propped door incident reported by two residents.", **minor,
    )

    third = sanction_conduct_case(
        third_routed["conduct_case"]["id"], "2026-08-05T10:00:00Z"
    )

    assert first["conduct_case"]["prior_sanctioned_count"] == 0
    assert first["conduct_case"]["sanction_points"] == 2
    assert second["conduct_case"]["prior_sanctioned_count"] == 1
    assert second["conduct_case"]["sanction_points"] == 3
    assert third["prior_sanctioned_count"] == 2
    assert third["sanction_points"] == 4
    respondent = read_student(subject["id"])
    assert respondent["conduct_points"] == 9
    assert respondent["conduct_standing"] == "GOOD"
    assert respondent["break_housing_eligible"] is True
    assert respondent["judicial_hold"] is False
    assert read_incident_report(third_routed["report"]["id"])["status"] == "CLOSED_ADJUDICATED"


def test_close_no_action_creates_no_conduct_case_and_no_judicial_hold(api, director_headers):
    """PRD §3.5: "`CLOSE_NO_ACTION` moves the report to `CLOSED_NO_ACTION`, and it is
    precisely characterised by what it does *not* do: **no** conduct case is created,
    `conduct_case_id` stays null, and the subject resident's `judicial_hold` is left
    exactly as it was."

    Design: Corner/state_machines/triage_close_no_action_creates_no_conduct_case_and_no_judicial_hold
    """
    base = setup_certified_ra_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": 2}]
    )
    subject = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )
    report = validate_success(
        api.create_incident_report(
            create_incident_report_payload(
                base["rooms"][0]["id"],
                subject["id"],
                occurred_at="2026-07-29T21:15:00Z",
                severity="MINOR",
                narrative="Speaker left playing in an empty room for ten minutes.",
            ),
            base["ra_headers"],
        ),
        201,
    )
    validate_success(api.submit_incident_report(report["id"], {}, base["ra_headers"]))

    closed = validate_success(
        api.triage_incident_report(
            report["id"],
            {"disposition": "CLOSE_NO_ACTION", "note": "resolved informally"},
            director_headers,
        )
    )

    assert closed["status"] == "CLOSED_NO_ACTION"
    assert closed["conduct_case_id"] is None
    assert closed["routed_by_user_id"] is None
    _, meta = validate_paginated(
        api.list_conduct_cases(
            director_headers, params={"respondent_student_id": subject["id"]}
        )
    )
    assert meta["total_count"] == 0, "CLOSE_NO_ACTION must open no conduct case"
    resident = read_student(subject["id"])
    assert resident["judicial_hold"] is False
    assert resident["conduct_points"] == 0
    assert resident["conduct_standing"] == "GOOD"


def test_third_return_disposition_is_refused_at_the_two_round_cap(api, director_headers):
    """PRD §3.5: "`RETURN` sends the report back to `RETURNED_FOR_DETAIL` and
    increments `return_count`; it is available only while `return_count` is strictly
    below the two-round cap, and a third return draws `ERR_RETURN_LIMIT_REACHED`."
    PRD §3.5: "The same action also serves the return cycle, moving a report
    `RETURNED_FOR_DETAIL → SUBMITTED` under identical conditions and re-stamping
    `submitted_at`."

    Design: Corner/state_machines/incident_return_disposition_capped_at_two_rounds
    """
    base = setup_incident_report_at_return_cap()
    report = base["report"]
    assert report["return_count"] == 2

    response = api.triage_incident_report(
        report["id"], {"disposition": "RETURN", "note": "third pass"}, director_headers
    )

    validate_error(response, ApiErrorId.ERR_RETURN_LIMIT_REACHED.value, 409)
    after = read_incident_report(report["id"])
    assert after["return_count"] == 2
    assert after["status"] == "SUBMITTED"
    assert after["conduct_case_id"] is None


def test_hearing_beyond_the_ten_day_window_is_refused_at_the_boundary(
    api, conduct_officer_headers
):
    """PRD §3.5: "The instant must fall strictly after the logical clock and no later
    than ten days after the case's `opened_at`; an instant at or before the clock, or
    beyond that ten-day window, is refused with `ERR_HEARING_WINDOW_EXCEEDED`."
    PRD §3.5: "A `ConductOfficer` schedules the hearing on an `OPEN` case by supplying
    `hearing_at`, which moves the case to `HEARING_SCHEDULED` and records the
    scheduling officer as `scheduled_by_user_id`."

    Design: Corner/validations/hearing_scheduled_beyond_the_ten_day_window_returns_hearing_window_exceeded
    """
    base = setup_routed_conduct_case()
    case_id = base["conduct_case"]["id"]

    too_late = api.schedule_hearing(
        case_id, {"hearing_at": "2026-08-11T00:00:01Z"}, conduct_officer_headers
    )

    validate_error(too_late, ApiErrorId.ERR_HEARING_WINDOW_EXCEEDED.value, 409)
    refused = read_conduct_case(case_id)
    assert refused["status"] == "OPEN"
    assert refused["hearing_at"] is None

    on_the_boundary = validate_success(
        api.schedule_hearing(
            case_id, {"hearing_at": "2026-08-11T00:00:00Z"}, conduct_officer_headers
        )
    )
    assert on_the_boundary["status"] == "HEARING_SCHEDULED"
    assert_timestamp_equals(
        on_the_boundary["hearing_at"], "2026-08-11T00:00:00Z", "hearing_at"
    )
    assert on_the_boundary["scheduled_by_user_id"] == "co-1"
    assert_timestamp_equals(
        on_the_boundary["opened_at"], "2026-08-01T00:00:00Z", "opened_at"
    )


def test_ra_reporting_on_their_own_resident_record_is_forbidden(api, director_headers):
    """PRD §3.5: "An RA may not report on themselves: if `subject_student_id` names the
    RA's own resident record, the request is refused with `ERR_SELF_REPORT_FORBIDDEN`
    (HTTP 422)."
    PRD §3.5: "The filing RA is taken from the caller's identity and stored as
    `filed_by_ra_id`; it is never supplied in the body."

    Design: Corner/validations/ra_filing_a_report_about_their_own_student_record_returns_self_report_forbidden
    """
    base = setup_certified_ra_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": 2}]
    )
    room_id = base["rooms"][0]["id"]
    other_resident = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )

    self_report = api.create_incident_report(
        create_incident_report_payload(
            room_id,
            base["student"]["id"],
            occurred_at="2026-07-30T20:00:00Z",
            severity="MINOR",
            narrative="Self-reported noise complaint from the RA about the RA.",
        ),
        base["ra_headers"],
    )

    validate_error(self_report, ApiErrorId.ERR_SELF_REPORT_FORBIDDEN.value, 422)

    about_another = validate_success(
        api.create_incident_report(
            create_incident_report_payload(
                room_id,
                other_resident["id"],
                occurred_at="2026-07-30T20:00:00Z",
                severity="MINOR",
                narrative="Amplified music heard from the corridor after quiet hours.",
            ),
            base["ra_headers"],
        ),
        201,
    )
    assert about_another["status"] == "DRAFT"
    assert about_another["filed_by_ra_id"] == base["ra"]["id"]
    _, meta = validate_paginated(
        api.list_incident_reports(
            director_headers, params={"subject_student_id": base["student"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused self-report must leave no row behind"
