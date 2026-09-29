"""Corner cases for the `validations` section of the corner design index.

Every test here translates exactly one refusal claimed by one non-stub
`validations` instance of `SCAFFOLD_CORNER_DESIGN.yaml`, asserts the single
error id PRD.md names for that situation, and re-reads the target rows to prove
the refused write changed nothing.

The harness restarts the server before every test, so each test rebuilds its
whole world from `2026-08-01T00:00:00Z` through public endpoints (PRD §2.4).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_student_headers

# 2024-07-31 plus 730 days is 2026-07-31, one day short of the 2026-08-01
# clock, so a member whose only completion sits here is LAPSED (PRD §3.1).
LAPSED_TRAINING_AT = "2024-07-31T00:00:00Z"

# The canonical session: 2026-08-20T10:00:00Z -> 11:30:00Z, 90 whole minutes,
# 19 days past the allegation notice and therefore clear of the 10-day floor.
SESSION_START = fixtures.SESSION_START
SESSION_END = fixtures.SESSION_END


# ---------------------------------------------------------------------------
# Shared setup helpers (plain functions, not fixtures — see the briefing)
# ---------------------------------------------------------------------------


def _formal_case_with_panel(api, response_window_days=5):
    """NOTIFIED + FORMAL, one room (buffer 30), a CURRENT chair, 3 panelists."""
    world = fixtures.seed_formal_case(
        client=api, response_window_days=response_window_days
    )
    fixtures.seed_panel(world, panel_size=3, client=api)
    return world


def _session_payload(world, **overrides):
    # The overrides are merged into the keyword dict before the call so that an
    # override of a named parameter (chair_id, panelist_ids, start_at, end_at)
    # replaces the default instead of colliding with a positional argument.
    base = {
        "case_id": world["case"]["id"],
        "room_id": world["room"]["id"],
        "chair_id": world["chair"]["id"],
        "panelist_ids": [p["id"] for p in world["panelists"]],
        "start_at": SESSION_START,
        "end_at": SESSION_END,
    }
    base.update(overrides)
    return factories.hearing_session_payload(**base)


def _assert_no_session_scheduled(api, world, officer):
    """No session row, an untouched room ledger and a case still in NOTIFIED."""
    assertions.assert_page(
        api.list_hearing_sessions(officer, {"case_id": world["case"]["id"]}),
        [],
        expected_total=0,
    )
    room = validate_success(api.get_hearing_room(world["room"]["id"], officer))
    assert room["booked_minutes_total"] == 0, room
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "NOTIFIED", case
    assert case["hearing_round"] == 0, case
    return case


def _rank_six_case(api, world, officer):
    """A CONTRACT_CHEATING case on the SEED-B exhibit pair.

    Evidence 81.50 -> contribution 32.60; base 40 for CONTRACT_CHEATING and no
    priors give provisional 72.60, severity 72.60 and tier rank 6 (PRD §3.4).
    Returns `(case, student, student_headers)`.
    """
    student = fixtures.create_student(officer, api)
    report = fixtures.create_report(
        world["offering"]["id"],
        student["id"],
        world["reporter_h"],
        api,
        alleged_violation_type="CONTRACT_CHEATING",
    )
    fixtures.attach_similarity_evidence(report["id"], world["reporter_h"], api)
    fixtures.attach_proctor_log(report["id"], world["reporter_h"], api)
    fixtures.submit_report(report["id"], world["reporter_h"], api)
    fixtures.triage_report(report["id"], "ACCEPT", headers=officer, client=api)
    case = fixtures.open_case(report["id"], officer, api)
    assert case["recommended_ladder_rank"] == 6, case
    return case, student, make_student_headers(student["id"])


def _propose_sanction_response(api, world, officer, ladder_rank, **overrides):
    """Raw office proposal against the case's current version (PRD §3.8)."""
    case = fixtures.read_case(world["case"]["id"], officer, api)
    return api.create_sanction(
        factories.sanction_payload(
            case["id"],
            case["version"],
            ladder_rank,
            case["decided_at"],
            **overrides,
        ),
        officer,
    )


def _assert_no_sanction(api, world, officer, expected_version):
    """A refused proposal creates nothing and never advances the case."""
    assertions.assert_page(
        api.list_sanctions(officer, {"case_id": world["case"]["id"]}),
        [],
        expected_total=0,
    )
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "DECIDED", case
    assert case["version"] == expected_version, case
    return case


def _assert_no_votes(api, world, officer, expected_total=0):
    rows, meta = assertions.validate_list(
        api.list_panel_votes(officer, {"session_id": world["session"]["id"]})
    )
    assert meta["total_count"] == expected_total, meta
    session = validate_success(
        api.get_hearing_session(world["session"]["id"], officer)
    )
    assert session["status"] == "CONVENED", session
    assert session["panel_finding"] is None, session
    assert session["effective_vote_count"] == 0, session
    return rows


# ---------------------------------------------------------------------------
# Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
# ---------------------------------------------------------------------------


def test_hearing_with_a_lapsed_chair_is_refused(api, officer):
    """A chair whose newest training completion is over 730 days old is refused.

    PRD §3.7: "The chair's `training_status` must be `CURRENT`, otherwise
    `ERR_CHAIR_TRAINING_LAPSED`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)
    lapsed_chair = fixtures.create_faculty(
        world["dept"]["id"],
        trained=True,
        completed_at=LAPSED_TRAINING_AT,
        headers=officer,
        client=api,
    )
    assert lapsed_chair["training_status"] == "LAPSED", lapsed_chair

    response = api.create_hearing_session(
        _session_payload(world, chair_id=lapsed_chair["id"]), officer
    )
    validate_error(response, ApiErrorId.ERR_CHAIR_TRAINING_LAPSED.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_with_the_reporter_seated_on_the_panel_is_refused(api, officer):
    """Seating the case's own reporter as a panelist is a conflict of interest.

    PRD §3.7: "neither `chair_id` nor any element of `panelist_ids` may equal
    the `reporter_id` of the case's originating report or the `instructor_id` of
    the case's offering, otherwise `ERR_PANEL_CONFLICT_OF_INTEREST`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)
    conflicted = [
        world["panelists"][0]["id"],
        world["panelists"][1]["id"],
        world["reporter"]["id"],
    ]

    response = api.create_hearing_session(
        _session_payload(world, panelist_ids=conflicted), officer
    )
    validate_error(response, ApiErrorId.ERR_PANEL_CONFLICT_OF_INTEREST.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_with_too_few_panelists_is_refused(api, officer):
    """A rank-3 case needs exactly three panelists; two is refused.

    PRD §3.7: "`required_panel_size` is derived from the case's
    `recommended_ladder_rank` at scheduling time: 3 when the rank is 5 or below
    ... The supplied `panelist_ids` must have exactly that length ... any
    violation is `ERR_PANEL_SIZE_INVALID`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)
    assert world["case"]["recommended_ladder_rank"] == 3, world["case"]
    two_of_three = [world["panelists"][0]["id"], world["panelists"][1]["id"]]

    response = api.create_hearing_session(
        _session_payload(world, panelist_ids=two_of_three), officer
    )
    validate_error(response, ApiErrorId.ERR_PANEL_SIZE_INVALID.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_with_a_duplicated_panelist_is_refused(api, officer):
    """Three ids of which two are the same member is refused on panel size.

    PRD §3.7: "The supplied `panelist_ids` must have exactly that length, must
    contain no duplicates, and must not contain `chair_id`; any violation is
    `ERR_PANEL_SIZE_INVALID`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)
    duplicated = [
        world["panelists"][0]["id"],
        world["panelists"][0]["id"],
        world["panelists"][1]["id"],
    ]

    response = api.create_hearing_session(
        _session_payload(world, panelist_ids=duplicated), officer
    )
    validate_error(response, ApiErrorId.ERR_PANEL_SIZE_INVALID.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_with_the_chair_listed_among_the_panelists_is_refused(api, officer):
    """The chair sitting in `panelist_ids` is a panel-size violation, not a COI.

    PRD §3.7: "The supplied `panelist_ids` ... must not contain `chair_id`; any
    violation is `ERR_PANEL_SIZE_INVALID`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)
    chair_seated = [
        world["panelists"][0]["id"],
        world["panelists"][1]["id"],
        world["chair"]["id"],
    ]

    response = api.create_hearing_session(
        _session_payload(world, panelist_ids=chair_seated), officer
    )
    validate_error(response, ApiErrorId.ERR_PANEL_SIZE_INVALID.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_whose_start_is_after_its_end_is_refused(api, officer):
    """An inverted interval is refused on the window rule, not the notice rule.

    Both instants sit 19 days past the allegation notice, so the rank-38 notice
    floor is satisfied and only the interval rule can fire.
    PRD §3.7: "The interval itself must be well formed ... `start_at` before
    `end_at`, a whole number of minutes, and a duration from 15 to 240 minutes
    inclusive, otherwise `ERR_MEETING_WINDOW_INVALID`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)

    response = api.create_hearing_session(
        _session_payload(world, start_at=SESSION_END, end_at=SESSION_START), officer
    )
    validate_error(response, ApiErrorId.ERR_MEETING_WINDOW_INVALID.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_shorter_than_fifteen_minutes_is_refused(api, officer):
    """A ten-minute hearing is below the 15-minute floor.

    PRD §3.7: "a duration from 15 to 240 minutes inclusive, otherwise
    `ERR_MEETING_WINDOW_INVALID`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)

    response = api.create_hearing_session(
        _session_payload(world, end_at="2026-08-20T10:10:00Z"), officer
    )
    validate_error(response, ApiErrorId.ERR_MEETING_WINDOW_INVALID.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_longer_than_four_hours_is_refused(api, officer):
    """A 300-minute hearing is above the 240-minute ceiling.

    PRD §3.7: "a duration from 15 to 240 minutes inclusive, otherwise
    `ERR_MEETING_WINDOW_INVALID`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)

    response = api.create_hearing_session(
        _session_payload(world, end_at="2026-08-20T15:00:00Z"), officer
    )
    validate_error(response, ApiErrorId.ERR_MEETING_WINDOW_INVALID.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_hearing_that_is_not_a_whole_number_of_minutes_is_refused(api, officer):
    """90 minutes and 30 seconds is refused even though it is inside the range.

    PRD §3.7: "The interval itself must be well formed ... a whole number of
    minutes ... otherwise `ERR_MEETING_WINDOW_INVALID`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)

    response = api.create_hearing_session(
        _session_payload(world, end_at="2026-08-20T11:30:30Z"), officer
    )
    validate_error(response, ApiErrorId.ERR_MEETING_WINDOW_INVALID.value, 409)
    _assert_no_session_scheduled(api, world, officer)


def test_a_well_formed_hearing_is_scheduled_and_charges_the_room_ledger(api, officer):
    """The positive control: every gate cleared, so the session is created.

    PRD §3.7: "On success the session is created in `SCHEDULED` with
    `round_number` set to the case's `hearing_round` plus one, `quorum_required`
    ... 2 for a three-member panel ... the room's `booked_minutes_total`
    increases by the session's whole minutes plus twice the room's
    `buffer_minutes`, a `HEARING_NOTICE` notification is created for the case,
    `adjudication_status` becomes `HEARING_SCHEDULED`."
    Design: Corner/validations/hearing_scheduling_rejects_lapsed_chairs_conflicted_panels_bad_sizes_and_bad_intervals
    """
    world = _formal_case_with_panel(api)

    session = validate_success(
        api.create_hearing_session(_session_payload(world), officer), 201
    )
    assertions.assert_hearing_session(
        session,
        {
            "case_id": world["case"]["id"],
            "room_id": world["room"]["id"],
            "chair_id": world["chair"]["id"],
            "status": "SCHEDULED",
            "required_panel_size": 3,
            "round_number": 1,
            "quorum_required": 2,
            "effective_vote_count": 0,
            "panel_finding": None,
            "panel_severity_recommendation": None,
            "adjourn_reason": None,
        },
    )
    assertions.assert_instant_equals(session["start_at"], SESSION_START, "start_at")
    assertions.assert_instant_equals(session["end_at"], SESSION_END, "end_at")

    room = validate_success(api.get_hearing_room(world["room"]["id"], officer))
    assert room["booked_minutes_total"] == fixtures.SESSION_LEDGER_MINUTES, room

    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "HEARING_SCHEDULED", case
    assert case["hearing_round"] == 1, case

    assertions.assert_page(
        api.list_hearing_sessions(officer, {"case_id": case["id"]}),
        [session["id"]],
        expected_total=1,
    )
    _, notices = assertions.validate_list(
        api.list_notifications(
            officer, {"case_id": case["id"], "kind": "HEARING_NOTICE"}
        )
    )
    assert notices["total_count"] == 1, notices


# ---------------------------------------------------------------------------
# Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
# ---------------------------------------------------------------------------


def test_attorney_advisor_is_refused_below_ladder_rank_six(api, officer):
    """A licensed attorney is still refused on a rank-3 case.

    PRD §3.5: "an `ATTORNEY` request is rejected with
    `ERR_ATTORNEY_ADVISOR_NOT_PERMITTED` when the case's
    `recommended_ladder_rank` is below 6."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)
    assert world["case"]["recommended_ladder_rank"] == 3, world["case"]

    response = api.create_advisor_engagement(
        factories.attorney_engagement_payload(world["case"]["id"]),
        world["student_h"],
    )
    validate_error(response, ApiErrorId.ERR_ATTORNEY_ADVISOR_NOT_PERMITTED.value, 409)
    assertions.assert_page(
        api.list_case_advisor_engagements(world["case"]["id"], officer),
        [],
        expected_total=0,
    )


def test_unlicensed_attorney_advisor_is_refused_on_a_rank_six_case(api, officer):
    """Rank 6 opens the attorney door, but only to a bar-licensed one.

    PRD §3.5: "an `ATTORNEY` request with `advisor_bar_licensed` false is
    rejected with `ERR_ATTORNEY_NOT_LICENSED`."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)
    high_case, _student, high_student_h = _rank_six_case(api, world, officer)

    response = api.create_advisor_engagement(
        factories.advisor_engagement_payload(
            high_case["id"], advisor_kind="ATTORNEY", advisor_bar_licensed=False
        ),
        high_student_h,
    )
    validate_error(response, ApiErrorId.ERR_ATTORNEY_NOT_LICENSED.value, 409)
    assertions.assert_page(
        api.list_case_advisor_engagements(high_case["id"], officer),
        [],
        expected_total=0,
    )


def test_licensed_attorney_advisor_is_accepted_on_a_rank_six_case(api, officer):
    """The positive control for both attorney gates.

    PRD §3.5: "The new engagement has `status` `REQUESTED`, `speaking_rights`
    false, `reconfirmation_required` false and `decision_reason` null."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)
    high_case, _student, high_student_h = _rank_six_case(api, world, officer)

    engagement = validate_success(
        api.create_advisor_engagement(
            factories.attorney_engagement_payload(high_case["id"]), high_student_h
        ),
        201,
    )
    assertions.assert_advisor_engagement(
        engagement,
        {
            "case_id": high_case["id"],
            "advisor_kind": "ATTORNEY",
            "advisor_bar_licensed": True,
            "status": "REQUESTED",
            "speaking_rights": False,
            "reconfirmation_required": False,
            "decision_reason": None,
        },
    )
    assertions.assert_page(
        api.list_case_advisor_engagements(high_case["id"], officer),
        [engagement["id"]],
        expected_total=1,
    )


def test_a_third_advisor_engagement_is_refused(api, officer):
    """Two live engagements exhaust the case's advisor allowance.

    PRD §3.5: "a request is rejected with `ERR_ADVISOR_LIMIT_REACHED` when the
    case already holds two engagements whose `status` is `REQUESTED` or
    `APPROVED`."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)
    fixtures.request_advisor(world, "FACULTY_ADVISOR", api)
    fixtures.request_advisor(world, "STUDENT_PEER", api)

    response = api.create_advisor_engagement(
        factories.advisor_engagement_payload(
            world["case"]["id"], advisor_kind="FACULTY_ADVISOR"
        ),
        world["student_h"],
    )
    validate_error(response, ApiErrorId.ERR_ADVISOR_LIMIT_REACHED.value, 409)
    _rows, meta = assertions.validate_list(
        api.list_case_advisor_engagements(world["case"]["id"], officer)
    )
    assert meta["total_count"] == 2, meta


def test_a_denied_engagement_stops_counting_against_the_advisor_limit(api, officer):
    """Denial frees the slot the request occupied.

    PRD §3.5: "Denied engagements stop counting against the limit."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)
    fixtures.request_advisor(world, "FACULTY_ADVISOR", api)
    fixtures.request_advisor(world, "STUDENT_PEER", api)
    fixtures.review_advisor(
        world, "DENY", "Named advisor is not eligible.", client=api
    )
    assert world["engagement"]["status"] == "DENIED", world["engagement"]

    replacement = validate_success(
        api.create_advisor_engagement(
            factories.advisor_engagement_payload(
                world["case"]["id"], advisor_kind="STUDENT_PEER"
            ),
            world["student_h"],
        ),
        201,
    )
    assert replacement["status"] == "REQUESTED", replacement
    _rows, meta = assertions.validate_list(
        api.list_case_advisor_engagements(world["case"]["id"], officer)
    )
    assert meta["total_count"] == 3, meta


def test_informal_pathway_is_refused_on_a_rank_six_case(api, officer):
    """A rank-6 case may not be settled informally.

    PRD §3.4: "Choosing `INFORMAL` for a case whose `recommended_ladder_rank`
    exceeds 3 is rejected with `ERR_INFORMAL_PATHWAY_NOT_PERMITTED`."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)
    high_case, _student, _high_student_h = _rank_six_case(api, world, officer)

    response = api.set_case_pathway(
        high_case["id"], factories.pathway_payload("INFORMAL"), officer
    )
    validate_error(response, ApiErrorId.ERR_INFORMAL_PATHWAY_NOT_PERMITTED.value, 409)
    reread = fixtures.read_case(high_case["id"], officer, api)
    assert reread["pathway"] == "UNASSIGNED", reread
    assert reread["adjudication_status"] == "INTAKE_REVIEW", reread
    assert reread["version"] == high_case["version"], reread


def test_notice_response_window_below_the_policy_floor_is_refused(api, officer):
    """4 days is a shape-valid integer but breaks the 5..30 policy range.

    PRD §3.5: "`response_window_days` must be an integer of at least 1 to
    satisfy the request shape, but the policy range of 5 to 30 inclusive is a
    business rule, not a shape rule: a value of 4 or of 31 is rejected with
    `ERR_RESPONSE_WINDOW_OUT_OF_RANGE` and HTTP 409."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)

    response = api.create_case_notification(
        world["case"]["id"],
        factories.notification_payload("ALLEGATION_NOTICE", 4),
        officer,
    )
    validate_error(response, ApiErrorId.ERR_RESPONSE_WINDOW_OUT_OF_RANGE.value, 409)
    assertions.assert_page(
        api.list_case_notifications(world["case"]["id"], officer), [], expected_total=0
    )
    reread = fixtures.read_case(world["case"]["id"], officer, api)
    assert reread["adjudication_status"] == "INTAKE_REVIEW", reread
    assert reread["version"] == world["case"]["version"], reread


def test_notice_response_window_above_the_policy_ceiling_is_refused(api, officer):
    """31 days breaks the same policy range from the other side.

    PRD §3.5: "a value of 4 or of 31 is rejected with
    `ERR_RESPONSE_WINDOW_OUT_OF_RANGE` and HTTP 409, whereas a value of 0, a
    negative value or a non-integer is rejected as an invalid request with HTTP
    400."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)

    response = api.create_case_notification(
        world["case"]["id"],
        factories.notification_payload("ALLEGATION_NOTICE", 31),
        officer,
    )
    validate_error(response, ApiErrorId.ERR_RESPONSE_WINDOW_OUT_OF_RANGE.value, 409)
    assertions.assert_page(
        api.list_case_notifications(world["case"]["id"], officer), [], expected_total=0
    )
    reread = fixtures.read_case(world["case"]["id"], officer, api)
    assert reread["adjudication_status"] == "INTAKE_REVIEW", reread


def test_notice_response_window_policy_boundaries_are_accepted(api, officer):
    """Both ends of the inclusive 5..30 range are legal.

    PRD §3.5: "the policy range of 5 to 30 inclusive ... Every notice records
    `sent_at` from the current logical clock, computes `response_deadline_at` as
    `sent_at` plus `response_window_days` days."
    Design: Corner/validations/advisor_rights_and_notice_windows_are_gated_by_rank_licensure_and_policy_range
    """
    world = fixtures.seed_case(client=api)

    floor_notice = validate_success(
        api.create_case_notification(
            world["case"]["id"],
            factories.notification_payload("ALLEGATION_NOTICE", 5),
            officer,
        ),
        201,
    )
    assertions.assert_notification(
        floor_notice,
        {
            "case_id": world["case"]["id"],
            "kind": "ALLEGATION_NOTICE",
            "response_window_days": 5,
            "acknowledged_at": None,
        },
    )
    assertions.assert_instant_equals(
        floor_notice["sent_at"], fixtures.CLOCK_T0, "sent_at"
    )
    assertions.assert_instant_equals(
        floor_notice["response_deadline_at"], "2026-08-06T00:00:00Z", "deadline"
    )

    fixtures.seed_sibling_case(world, client=api, course_code="ENGL-202")
    ceiling_notice = validate_success(
        api.create_case_notification(
            world["sibling"]["id"],
            factories.notification_payload("ALLEGATION_NOTICE", 30),
            officer,
        ),
        201,
    )
    assert ceiling_notice["response_window_days"] == 30, ceiling_notice
    assertions.assert_instant_equals(
        ceiling_notice["response_deadline_at"], "2026-08-31T00:00:00Z", "deadline"
    )


# ---------------------------------------------------------------------------
# Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
# ---------------------------------------------------------------------------


def test_vote_for_a_faculty_member_off_the_panel_is_refused(api, officer):
    """A ballot for someone who was never seated is refused.

    PRD §3.7: "`panelist_id` must be an element of the session's
    `panelist_ids`, otherwise `ERR_NOT_A_PANELIST`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_convened_session(client=api)
    outsider = fixtures.create_faculty(
        world["dept"]["id"], trained=False, headers=officer, client=api
    )
    assert outsider["id"] not in world["session"]["panelist_ids"], outsider

    response = api.create_panel_vote(
        factories.panel_vote_payload(
            world["session"]["id"], outsider["id"], "RESPONSIBLE", 3
        ),
        world["chair_h"],
    )
    validate_error(response, ApiErrorId.ERR_NOT_A_PANELIST.value, 409)
    _assert_no_votes(api, world, officer)


def test_vote_cast_for_the_case_reporter_is_refused_as_a_conflict(api, officer):
    """The reporter can never vote, and the conflict rule outranks the roster.

    Rank 26 sits above rank 35 in PRD §2.9, so the reporter — who is also not a
    panelist — reports the conflict, not the roster miss.
    PRD §3.7: "a panelist who is the case's reporter can never vote, which is
    `ERR_PANEL_CONFLICT_OF_INTEREST`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_convened_session(client=api)

    response = api.create_panel_vote(
        factories.panel_vote_payload(
            world["session"]["id"], world["reporter"]["id"], "RESPONSIBLE", 3
        ),
        world["chair_h"],
    )
    validate_error(response, ApiErrorId.ERR_PANEL_CONFLICT_OF_INTEREST.value, 409)
    _assert_no_votes(api, world, officer)


def test_responsible_verdict_without_a_recommendation_is_refused(api, officer):
    """A responsible ballot must name a severity.

    PRD §3.7: "a missing recommendation on a responsible verdict is
    `ERR_SEVERITY_RECOMMENDATION_REQUIRED`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_convened_session(client=api)

    response = api.create_panel_vote(
        factories.panel_vote_payload(
            world["session"]["id"], world["panelists"][0]["id"], "RESPONSIBLE"
        ),
        world["chair_h"],
    )
    validate_error(response, ApiErrorId.ERR_SEVERITY_RECOMMENDATION_REQUIRED.value, 409)
    _assert_no_votes(api, world, officer)


def test_abstain_verdict_with_a_recommendation_is_refused(api, officer):
    """An abstention may not carry a severity.

    PRD §3.7: "a surplus one on the other verdicts is
    `ERR_SEVERITY_RECOMMENDATION_NOT_ALLOWED`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_convened_session(client=api)

    response = api.create_panel_vote(
        factories.panel_vote_payload(
            world["session"]["id"], world["panelists"][0]["id"], "ABSTAIN", 5
        ),
        world["chair_h"],
    )
    validate_error(
        response, ApiErrorId.ERR_SEVERITY_RECOMMENDATION_NOT_ALLOWED.value, 409
    )
    _assert_no_votes(api, world, officer)


def test_not_responsible_verdict_with_a_recommendation_is_refused(api, officer):
    """Neither of the two non-responsible verdicts may carry a severity.

    PRD §3.7: "a `severity_recommendation` from 1 to 8 that is required exactly
    when the verdict is `RESPONSIBLE` and must be omitted for the other two
    verdicts."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_convened_session(client=api)

    response = api.create_panel_vote(
        factories.panel_vote_payload(
            world["session"]["id"], world["panelists"][1]["id"], "NOT_RESPONSIBLE", 5
        ),
        world["chair_h"],
    )
    validate_error(
        response, ApiErrorId.ERR_SEVERITY_RECOMMENDATION_NOT_ALLOWED.value, 409
    )
    _assert_no_votes(api, world, officer)


def test_sanction_above_the_office_band_is_refused(api, officer):
    """Rank 5 sits one step above the [2, 4] band of a rank-3 case.

    PRD §3.8: "`ladder_rank` must lie inside the office band, which runs from
    the case's `recommended_ladder_rank` minus 1 clamped up to 1, through that
    rank plus 1 clamped down to 8; a rank above the upper bound is
    `ERR_SANCTION_ABOVE_LADDER_BAND`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_decided_case(client=api)
    assert world["case"]["recommended_ladder_rank"] == 3, world["case"]
    version = fixtures.case_version(world["case"]["id"], officer, api)

    response = _propose_sanction_response(api, world, officer, 5)
    validate_error(response, ApiErrorId.ERR_SANCTION_ABOVE_LADDER_BAND.value, 409)
    _assert_no_sanction(api, world, officer, version)


def test_sanction_below_the_office_band_is_refused(api, officer):
    """Rank 1 sits one step below the [2, 4] band of a rank-3 case.

    PRD §3.8: "a rank below the lower bound is
    `ERR_SANCTION_BELOW_LADDER_BAND`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_decided_case(client=api)
    version = fixtures.case_version(world["case"]["id"], officer, api)

    response = _propose_sanction_response(api, world, officer, 1)
    validate_error(response, ApiErrorId.ERR_SANCTION_BELOW_LADDER_BAND.value, 409)
    _assert_no_sanction(api, world, officer, version)


def test_sanction_kind_that_does_not_match_the_rank_is_refused(api, officer):
    """An in-band rank carrying the wrong kind is refused on the mapping.

    PRD §2.12 maps rank 1 to `WARNING` and rank 3 to `GRADE_PENALTY_COURSE`, so
    rank 3 with a `WARNING` kind clears the band and fails the mapping.
    PRD §3.8: "`kind` must be the kind the rank maps to, otherwise
    `ERR_SANCTION_KIND_RANK_MISMATCH`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_decided_case(client=api)
    version = fixtures.case_version(world["case"]["id"], officer, api)

    response = _propose_sanction_response(api, world, officer, 3, kind="WARNING")
    validate_error(response, ApiErrorId.ERR_SANCTION_KIND_RANK_MISMATCH.value, 409)
    _assert_no_sanction(api, world, officer, version)


def test_assignment_grade_penalty_without_a_component_code_is_refused(api, officer):
    """`GRADE_PENALTY_ASSIGNMENT` cannot be proposed without naming a component.

    PRD §3.8: "`grade_component_code` ... is required when the kind is
    `GRADE_PENALTY_ASSIGNMENT` and forbidden for every other kind, otherwise
    `ERR_GRADE_COMPONENT_REQUIRED`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_decided_case(client=api)
    version = fixtures.case_version(world["case"]["id"], officer, api)

    response = _propose_sanction_response(api, world, officer, 2)
    validate_error(response, ApiErrorId.ERR_GRADE_COMPONENT_REQUIRED.value, 409)
    _assert_no_sanction(api, world, officer, version)


def test_course_grade_penalty_with_a_component_code_is_refused(api, officer):
    """The same error guards the surplus direction, with a real component code.

    `ESSAY` is declared by the offering, so the rank-32 lookup passes and only
    the required/forbidden rule can fire.
    PRD §3.8: "`grade_component_code` ... is required when the kind is
    `GRADE_PENALTY_ASSIGNMENT` and forbidden for every other kind, otherwise
    `ERR_GRADE_COMPONENT_REQUIRED`."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_decided_case(client=api)
    version = fixtures.case_version(world["case"]["id"], officer, api)

    response = _propose_sanction_response(
        api, world, officer, 3, grade_component_code="ESSAY"
    )
    validate_error(response, ApiErrorId.ERR_GRADE_COMPONENT_REQUIRED.value, 409)
    _assert_no_sanction(api, world, officer, version)


def test_an_in_band_sanction_proposal_is_created(api, officer):
    """The positive control: the tally fixes the band, and rank 3 sits inside it.

    PRD §3.8: "On success the sanction is created in `PROPOSED` with `origin`
    `OFFICE_PROPOSAL`, `imposed_at` null, `completed_at` null, `vacated_reason`
    null, and `baseline_course_grade_pct`, `adjusted_course_grade_pct` and
    `grade_penalty_delta_pct` at 0.00."
    Design: Corner/validations/panel_vote_and_sanction_proposal_gates_each_return_their_own_error
    """
    world = fixtures.seed_decided_case(client=api)
    session = validate_success(
        api.get_hearing_session(world["session"]["id"], officer)
    )
    assertions.assert_hearing_session(
        session,
        {
            "status": "DECIDED",
            "panel_finding": "RESPONSIBLE",
            "effective_vote_count": 3,
            "panel_severity_recommendation": 3,
        },
    )
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "DECIDED", case
    assert case["recommended_ladder_rank"] == 3, case
    version = case["version"]

    sanction = validate_success(_propose_sanction_response(api, world, officer, 3), 201)
    assertions.assert_sanction(
        sanction,
        {
            "case_id": case["id"],
            "kind": "GRADE_PENALTY_COURSE",
            "ladder_rank": 3,
            "status": "PROPOSED",
            "origin": "OFFICE_PROPOSAL",
            "grade_component_code": None,
            "replaces_sanction_id": None,
            "imposed_at": None,
            "completed_at": None,
            "vacated_reason": None,
            "baseline_course_grade_pct": 0.00,
            "adjusted_course_grade_pct": 0.00,
            "grade_penalty_delta_pct": 0.00,
        },
    )
    assertions.assert_page(
        api.list_sanctions(officer, {"case_id": case["id"]}),
        [sanction["id"]],
        expected_total=1,
    )
    assert fixtures.case_version(case["id"], officer, api) == version + 1


# ---------------------------------------------------------------------------
# Corner/validations/report_creation_requires_exactly_one_score_per_declared_grade_component
# ---------------------------------------------------------------------------


def test_report_missing_a_declared_grade_component_is_refused(api, officer):
    """Three scores against a four-component gradebook is an incomplete join.

    PRD §3.3: "the array must contain exactly one entry per code declared in
    the offering's `grade_components`, and a missing, duplicated or unknown code
    is rejected with `ERR_COMPONENT_SCORES_INCOMPLETE`."
    Design: Corner/validations/report_creation_requires_exactly_one_score_per_declared_grade_component
    """
    world = fixtures.seed_actors(client=api)

    response = api.create_report(
        factories.report_payload(
            world["offering"]["id"],
            world["student"]["id"],
            component_scores=[
                {"code": "ESSAY", "earned_points": 156},
                {"code": "MIDTERM", "earned_points": 68},
                {"code": "PROJECT", "earned_points": 56},
            ],
        ),
        world["reporter_h"],
    )
    validate_error(response, ApiErrorId.ERR_COMPONENT_SCORES_INCOMPLETE.value, 409)
    assertions.assert_page(
        api.list_reports(officer, {"offering_id": world["offering"]["id"]}),
        [],
        expected_total=0,
    )


def test_report_with_an_undeclared_grade_component_is_refused(api, officer):
    """All four declared codes plus one the gradebook never declared is refused.

    PRD §2.9 rank 34: "the report's `component_scores` array does not contain
    exactly one entry per code in the offering's `grade_components`, or contains
    a code the gradebook does not declare ... →
    `ERR_COMPONENT_SCORES_INCOMPLETE` (409)."
    Design: Corner/validations/report_creation_requires_exactly_one_score_per_declared_grade_component
    """
    world = fixtures.seed_actors(client=api)

    response = api.create_report(
        factories.report_payload(
            world["offering"]["id"],
            world["student"]["id"],
            component_scores=[
                {"code": "ESSAY", "earned_points": 156},
                {"code": "MIDTERM", "earned_points": 68},
                {"code": "PROJECT", "earned_points": 56},
                {"code": "FINAL", "earned_points": 113},
                {"code": "QUIZ", "earned_points": 10},
            ],
        ),
        world["reporter_h"],
    )
    validate_error(response, ApiErrorId.ERR_COMPONENT_SCORES_INCOMPLETE.value, 409)
    assertions.assert_page(
        api.list_reports(officer, {"offering_id": world["offering"]["id"]}),
        [],
        expected_total=0,
    )


def test_report_with_a_duplicated_grade_component_is_refused(api, officer):
    """Two entries for `ESSAY` is refused even though every code is declared.

    PRD §3.3: "exactly one entry per code declared in the offering's
    `grade_components`, and a missing, duplicated or unknown code is rejected
    with `ERR_COMPONENT_SCORES_INCOMPLETE`."
    Design: Corner/validations/report_creation_requires_exactly_one_score_per_declared_grade_component
    """
    world = fixtures.seed_actors(client=api)

    response = api.create_report(
        factories.report_payload(
            world["offering"]["id"],
            world["student"]["id"],
            component_scores=[
                {"code": "ESSAY", "earned_points": 156},
                {"code": "ESSAY", "earned_points": 150},
                {"code": "MIDTERM", "earned_points": 68},
                {"code": "PROJECT", "earned_points": 56},
                {"code": "FINAL", "earned_points": 113},
            ],
        ),
        world["reporter_h"],
    )
    validate_error(response, ApiErrorId.ERR_COMPONENT_SCORES_INCOMPLETE.value, 409)
    assertions.assert_page(
        api.list_reports(officer, {"offering_id": world["offering"]["id"]}),
        [],
        expected_total=0,
    )


def test_report_with_every_declared_component_in_any_order_is_created(api, officer):
    """The join is by code, not by position, so a reversed array is accepted.

    PRD §3.3: "A newly created report has `status` `DRAFT`, `submitted_at` null,
    `returned_at` null, `triaged_at` null, `triage_note` null,
    `resubmission_count` 0, `evidence_strength_score` 0.00 and
    `evidence_complete` false."
    Design: Corner/validations/report_creation_requires_exactly_one_score_per_declared_grade_component
    """
    world = fixtures.seed_actors(client=api)

    report = validate_success(
        api.create_report(
            factories.report_payload(
                world["offering"]["id"],
                world["student"]["id"],
                component_scores=[
                    {"code": "FINAL", "earned_points": 113},
                    {"code": "PROJECT", "earned_points": 56},
                    {"code": "MIDTERM", "earned_points": 68},
                    {"code": "ESSAY", "earned_points": 156},
                ],
            ),
            world["reporter_h"],
        ),
        201,
    )
    assertions.assert_integrity_report(
        report,
        {
            "offering_id": world["offering"]["id"],
            "student_id": world["student"]["id"],
            "reporter_id": world["reporter"]["id"],
            "status": "DRAFT",
            "submitted_at": None,
            "returned_at": None,
            "triaged_at": None,
            "triage_note": None,
            "resubmission_count": 0,
            "evidence_strength_score": 0.00,
            "evidence_complete": False,
        },
    )
    assert len(report["component_scores"]) == 4, report["component_scores"]
    assert sorted(s["code"] for s in report["component_scores"]) == [
        "ESSAY",
        "FINAL",
        "MIDTERM",
        "PROJECT",
    ], report["component_scores"]
    assertions.assert_page(
        api.list_reports(officer, {"offering_id": world["offering"]["id"]}),
        [report["id"]],
        expected_total=1,
    )


# ---------------------------------------------------------------------------
# Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
# ---------------------------------------------------------------------------


def test_appeal_filed_at_the_ten_day_boundary_is_inside_the_window(api, officer):
    """Filing exactly at `decided_at` + 10 days is accepted.

    PRD §3.9: "The filing window is ten days: the current logical clock must not
    have passed the case's `decided_at` plus 10 days ... Filing exactly at
    `decided_at` plus ten days is inside the window; one second later is
    outside."
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    assertions.assert_instant_equals(
        world["case"]["decided_at"], fixtures.DECIDED_AT, "decided_at"
    )
    fixtures.set_clock("2026-08-30T10:00:00Z", officer, api)

    appeal = validate_success(
        api.create_appeal(
            factories.appeal_payload(world["case"]["id"], grounds="SANCTION_SEVERITY"),
            world["student_h"],
        ),
        201,
    )
    assertions.assert_appeal(
        appeal,
        {
            "case_id": world["case"]["id"],
            "grounds": "SANCTION_SEVERITY",
            "status": "SUBMITTED",
            "hearing_round_at_filing": 1,
            "reduced_ladder_rank": None,
            "decision_reason": None,
            "decided_at": None,
        },
    )
    assertions.assert_instant_equals(
        appeal["filed_at"], "2026-08-30T10:00:00Z", "filed_at"
    )
    assertions.assert_page(
        api.list_case_appeals(world["case"]["id"], officer),
        [appeal["id"]],
        expected_total=1,
    )


def test_appeal_filed_one_second_past_the_window_is_refused(api, officer):
    """One second past `decided_at` + 10 days closes the window.

    PRD §3.9: "Filing exactly at `decided_at` plus ten days is inside the
    window; one second later is outside."
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    fixtures.set_clock("2026-08-30T10:00:01Z", officer, api)

    response = api.create_appeal(
        factories.appeal_payload(world["case"]["id"], grounds="SANCTION_SEVERITY"),
        world["student_h"],
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, 409)
    assertions.assert_page(
        api.list_case_appeals(world["case"]["id"], officer), [], expected_total=0
    )
    reread = fixtures.read_case(world["case"]["id"], officer, api)
    assert reread["adjudication_status"] == "SANCTION_IMPOSED", reread


def test_second_appeal_while_one_is_open_is_refused(api, officer):
    """Only one appeal may be open at a time.

    PRD §3.9: "An appeal is rejected with `ERR_APPEAL_ALREADY_FILED` when the
    case already has an appeal in `SUBMITTED` or `UNDER_REVIEW`."
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    fixtures.file_appeal(world, "SANCTION_SEVERITY", api)
    assert world["appeal"]["status"] == "SUBMITTED", world["appeal"]

    response = api.create_appeal(
        factories.appeal_payload(world["case"]["id"], grounds="PROCEDURE"),
        world["student_h"],
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_ALREADY_FILED.value, 409)
    assertions.assert_page(
        api.list_case_appeals(world["case"]["id"], officer),
        [world["appeal"]["id"]],
        expected_total=1,
    )


def test_deciding_an_appeal_before_it_is_screened_is_refused(api, officer, dean):
    """A SUBMITTED appeal has not reached review, so it cannot be decided.

    PRD §3.9: "The dean decides an `UNDER_REVIEW` appeal ... Deciding an appeal
    in any other status is `ERR_APPEAL_STATE_INVALID`."
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    fixtures.file_appeal(world, "SANCTION_SEVERITY", api)

    response = api.decide_appeal(
        world["appeal"]["id"],
        factories.appeal_decision_payload("UPHELD_ORIGINAL"),
        dean,
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_STATE_INVALID.value, 409)
    reread = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert reread["status"] == "SUBMITTED", reread
    assert reread["decided_at"] is None, reread
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "SANCTION_IMPOSED", case
    assert case["pre_appeal_adjudication_status"] is None, case


def test_screening_an_appeal_twice_is_refused(api, officer, dean):
    """Screening is a one-shot transition out of SUBMITTED.

    PRD §3.9: "The appeals dean screens a `SUBMITTED` appeal ... Screening an
    appeal in any other status is `ERR_APPEAL_STATE_INVALID`."

    The first screening is a denial for want of grounds, because that is the one
    screening outcome that "leaves the case's `adjudication_status` untouched"
    (PRD §3.9).  The case therefore stays in `SANCTION_IMPOSED`, which §3.9
    still admits, so the rank-13 case-state gate of PRD §2.9 is clear and the
    rank-20 appeal-state gate is the only one the replay can trip.
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    fixtures.file_appeal(world, "SANCTION_SEVERITY", api)
    fixtures.screen_appeal(
        world, "DENY_NO_GROUNDS", "No procedural defect identified.", client=api
    )
    assert world["appeal"]["status"] == "DENIED_NO_GROUNDS", world["appeal"]
    assert world["case"]["adjudication_status"] == "SANCTION_IMPOSED", world["case"]
    assert world["case"]["pre_appeal_adjudication_status"] is None, world["case"]

    response = api.screen_appeal(
        world["appeal"]["id"], factories.screen_payload("ACCEPT_FOR_REVIEW"), dean
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_STATE_INVALID.value, 409)
    reread = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert reread["status"] == "DENIED_NO_GROUNDS", reread
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "SANCTION_IMPOSED", case


def test_remand_on_sanction_severity_grounds_is_refused(api, officer, dean):
    """A remand needs procedural or evidentiary grounds, not severity grounds.

    PRD §3.9: "The grounds must match the outcome: `SANCTION_REDUCED` requires
    `grounds` `SANCTION_SEVERITY`, while `REMANDED` and `OVERTURNED` require
    `grounds` `PROCEDURE` or `EVIDENCE`; a mismatch is
    `ERR_APPEAL_GROUNDS_MISMATCH`."
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    fixtures.file_appeal(world, "SANCTION_SEVERITY", api)
    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)

    response = api.decide_appeal(
        world["appeal"]["id"], factories.appeal_decision_payload("REMANDED"), dean
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_GROUNDS_MISMATCH.value, 409)
    reread = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert reread["status"] == "UNDER_REVIEW", reread
    assert reread["decided_at"] is None, reread
    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "IMPOSED", sanction
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "APPEAL_UNDER_REVIEW", case


def test_reduced_rank_equal_to_the_governing_rank_is_refused(api, officer, dean):
    """A "reduction" to the same rank is not a reduction.

    PRD §3.9: "`reduced_ladder_rank` must be at least 1 and strictly less than
    the governing sanction's `ladder_rank`, otherwise
    `ERR_REDUCED_RANK_INVALID`."
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    assert world["sanction"]["ladder_rank"] == 3, world["sanction"]
    fixtures.file_appeal(world, "SANCTION_SEVERITY", api)
    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)

    response = api.decide_appeal(
        world["appeal"]["id"],
        factories.appeal_decision_payload("SANCTION_REDUCED", reduced_ladder_rank=3),
        dean,
    )
    validate_error(response, ApiErrorId.ERR_REDUCED_RANK_INVALID.value, 409)
    reread = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert reread["status"] == "UNDER_REVIEW", reread
    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "IMPOSED", sanction
    assert sanction["vacated_reason"] is None, sanction
    assertions.assert_page(
        api.list_sanctions(officer, {"case_id": world["case"]["id"]}),
        [world["sanction"]["id"]],
        expected_total=1,
    )
    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["active_sanction_points"] == 3, student


def test_reduction_to_rank_one_vacates_and_replaces_the_governing_sanction(
    api, officer, dean
):
    """The positive control for the reduced-rank gate, with its full cascade.

    PRD §3.9: "the governing sanction moves to `VACATED` with `vacated_reason`
    `APPEAL_REDUCED`; and a replacement sanction is created with `origin`
    `APPEAL_REDUCTION`, `replaces_sanction_id` pointing at the vacated row,
    `ladder_rank` equal to `reduced_ladder_rank`, the `kind` that rank maps to,
    and a `status` of `IMPOSED` when the vacated sanction was `IMPOSED`."
    Design: Corner/validations/appeal_gates_stack_window_duplication_state_grounds_and_reduced_rank
    """
    world = fixtures.seed_case_with_imposed_sanction(client=api)
    original_id = world["sanction"]["id"]
    fixtures.file_appeal(world, "SANCTION_SEVERITY", api)
    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)

    appeal = validate_success(
        api.decide_appeal(
            world["appeal"]["id"],
            factories.appeal_decision_payload(
                "SANCTION_REDUCED", reduced_ladder_rank=1
            ),
            dean,
        )
    )
    assertions.assert_appeal(
        appeal, {"status": "SANCTION_REDUCED", "reduced_ladder_rank": 1}
    )
    assertions.assert_instant_equals(
        appeal["decided_at"], fixtures.CLOCK_AT_SESSION, "decided_at"
    )

    rows, meta = assertions.validate_list(
        api.list_sanctions(officer, {"case_id": world["case"]["id"]})
    )
    assert meta["total_count"] == 2, meta
    vacated = [r for r in rows if r["id"] == original_id][0]
    replacement = [r for r in rows if r["id"] != original_id][0]
    assertions.assert_sanction(
        vacated, {"status": "VACATED", "vacated_reason": "APPEAL_REDUCED"}
    )
    assertions.assert_sanction(
        replacement,
        {
            "origin": "APPEAL_REDUCTION",
            "replaces_sanction_id": original_id,
            "ladder_rank": 1,
            "kind": "WARNING",
            "status": "IMPOSED",
        },
    )

    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["active_sanction_points"] == 1, student
    assert student["standing"] == "GOOD_STANDING", student
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "SANCTION_IMPOSED", case
    assert case["pre_appeal_adjudication_status"] is None, case


# ---------------------------------------------------------------------------
# Corner/validations/an_accepted_informal_resolution_is_appealable_only_on_procedure_grounds
# ---------------------------------------------------------------------------


def test_evidence_grounds_appeal_on_an_accepted_informal_resolution_is_not_reviewable(
    api, officer, dean
):
    """The waiver bites at screening, not at filing: the appeal files, then dies.

    PRD §3.9: "One extra rule applies to a case whose `pathway` is `INFORMAL`
    and whose `adjudication_status` is `INFORMAL_ACCEPTED`: its `grounds` must be
    `PROCEDURE`, otherwise `ERR_INFORMAL_RESOLUTION_NOT_APPEALABLE`."
    Design: Corner/validations/an_accepted_informal_resolution_is_appealable_only_on_procedure_grounds
    """
    world = fixtures.seed_informal_accepted_case(client=api)
    assert world["case"]["adjudication_status"] == "INFORMAL_ACCEPTED", world["case"]
    assert world["case"]["pathway"] == "INFORMAL", world["case"]

    appeal = validate_success(
        api.create_appeal(
            factories.appeal_payload(world["case"]["id"], grounds="EVIDENCE"),
            world["student_h"],
        ),
        201,
    )
    assert appeal["status"] == "SUBMITTED", appeal

    response = api.screen_appeal(
        appeal["id"], factories.screen_payload("ACCEPT_FOR_REVIEW"), dean
    )
    validate_error(
        response, ApiErrorId.ERR_INFORMAL_RESOLUTION_NOT_APPEALABLE.value, 409
    )
    reread = validate_success(api.get_appeal(appeal["id"], officer))
    assert reread["status"] == "SUBMITTED", reread
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "INFORMAL_ACCEPTED", case
    assert case["pre_appeal_adjudication_status"] is None, case


def test_evidence_grounds_appeal_on_an_accepted_informal_resolution_cannot_be_denied(
    api, officer, dean
):
    """The grounds rule outranks the screening decision, so denial fails too.

    PRD §2.9 rank 30: "the case is on the `INFORMAL` pathway in
    `INFORMAL_ACCEPTED` and the appeal's `grounds` is not `PROCEDURE`, on `POST
    /integrity/appeals/{id}/screen` → `ERR_INFORMAL_RESOLUTION_NOT_APPEALABLE`."
    Design: Corner/validations/an_accepted_informal_resolution_is_appealable_only_on_procedure_grounds
    """
    world = fixtures.seed_informal_accepted_case(client=api)
    fixtures.file_appeal(world, "EVIDENCE", api)

    response = api.screen_appeal(
        world["appeal"]["id"],
        factories.screen_payload("DENY_NO_GROUNDS", "No procedural defect alleged."),
        dean,
    )
    validate_error(
        response, ApiErrorId.ERR_INFORMAL_RESOLUTION_NOT_APPEALABLE.value, 409
    )
    reread = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert reread["status"] == "SUBMITTED", reread
    assert reread["decided_at"] is None, reread
    assert reread["decision_reason"] is None, reread


def test_severity_grounds_appeal_on_an_accepted_informal_resolution_is_refused(
    api, officer, dean
):
    """Accepting the resolution waived the severity ground as well.

    PRD §3.9: "A student who accepted an informal resolution waived the evidence
    and severity grounds but never the procedural one."
    Design: Corner/validations/an_accepted_informal_resolution_is_appealable_only_on_procedure_grounds
    """
    world = fixtures.seed_informal_accepted_case(client=api)
    fixtures.file_appeal(world, "SANCTION_SEVERITY", api)

    response = api.screen_appeal(
        world["appeal"]["id"], factories.screen_payload("ACCEPT_FOR_REVIEW"), dean
    )
    validate_error(
        response, ApiErrorId.ERR_INFORMAL_RESOLUTION_NOT_APPEALABLE.value, 409
    )
    reread = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert reread["status"] == "SUBMITTED", reread
    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "ACCEPTED", sanction


def test_procedure_grounds_appeal_on_an_accepted_informal_resolution_is_reviewed(
    api, officer
):
    """The procedural ground survives the waiver and screens through to review.

    PRD §3.9: "its `grounds` must be `PROCEDURE`, otherwise
    `ERR_INFORMAL_RESOLUTION_NOT_APPEALABLE`. A student who accepted an informal
    resolution waived the evidence and severity grounds but never the procedural
    one."
    Design: Corner/validations/an_accepted_informal_resolution_is_appealable_only_on_procedure_grounds
    """
    world = fixtures.seed_informal_accepted_case(client=api)
    fixtures.file_appeal(world, "PROCEDURE", api)
    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)

    assert world["appeal"]["status"] == "UNDER_REVIEW", world["appeal"]
    assert world["case"]["adjudication_status"] == "APPEAL_UNDER_REVIEW", world["case"]
    assert world["case"]["pre_appeal_adjudication_status"] == "INFORMAL_ACCEPTED", (
        world["case"]
    )

    fixtures.decide_appeal(world, "UPHELD_ORIGINAL", client=api)
    assert world["appeal"]["status"] == "UPHELD_ORIGINAL", world["appeal"]
    case = fixtures.read_case(world["case"]["id"], officer, api)
    assert case["adjudication_status"] == "INFORMAL_ACCEPTED", case
    assert case["pre_appeal_adjudication_status"] is None, case
    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "ACCEPTED", sanction


def test_a_third_appeal_on_the_same_case_is_refused(api, officer):
    """Two appeals of any status exhaust the case, even when both are closed.

    PRD §3.9: "An appeal is rejected with `ERR_APPEAL_ALREADY_FILED` when the
    case already has an appeal in `SUBMITTED` or `UNDER_REVIEW`, or when the case
    already has two appeals of any status — only one appeal may be open at a time
    and no more than two may ever be filed."
    Design: Corner/validations/an_accepted_informal_resolution_is_appealable_only_on_procedure_grounds
    """
    world = fixtures.seed_informal_accepted_case(client=api)
    filed = []
    for _ in range(2):
        fixtures.file_appeal(world, "PROCEDURE", api)
        fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)
        fixtures.decide_appeal(world, "UPHELD_ORIGINAL", client=api)
        assert world["appeal"]["status"] == "UPHELD_ORIGINAL", world["appeal"]
        filed.append(world["appeal"]["id"])

    response = api.create_appeal(
        factories.appeal_payload(world["case"]["id"], grounds="PROCEDURE"),
        world["student_h"],
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_ALREADY_FILED.value, 409)
    assertions.assert_page(
        api.list_case_appeals(world["case"]["id"], officer),
        filed,
        expected_total=2,
    )
