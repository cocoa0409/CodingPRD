"""Corner cases: derived calculations and endpoint contracts.

Every test here translates exactly one non-stub instance of the `calculations`
or `endpoints` section of `SCAFFOLD_CORNER_DESIGN.yaml`; the instance's own
name is carried on the test's `Design:` line.

The harness restarts the API server before every individual test, so each test
rebuilds its entire world through public endpoints against an empty store with
the logical clock at `2026-08-01T00:00:00Z` (PRD §2.4).

Two local setup helpers mirror `test_helpers.fixtures.seed_actors` /
`seed_panel` instead of calling them:

* `factories.student_payload` sends `class_year: 2027`, while PRD §3.2 declares
  "a `class_year` from 1 to 8" — an integer outside its declared range is a
  §2.9 rank-5 shape violation, and `seed_actors` offers no injection point for
  the override, so `_actors` passes `class_year=3` itself.
* PRD §4 does not pin the status code of
  `POST /integrity/faculty-members/{id}/training-completions` (its response
  body is the recomputed FacultyMember, which §4's preamble routes to 200, but
  it also adds a completion to a collection, which §4 routes to 201).
  `fixtures.create_faculty` demands exactly 201, so `_trained_faculty` accepts
  either 2xx for setup and leaves the status question to the one test whose
  claim is about the response body.

`test_helpers/` is frozen, so both work-arounds live here.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_chair_headers,
    make_dean_headers,
    make_registrar_headers,
    make_reporter_headers,
    make_student_headers,
)

UNKNOWN = constants.UNKNOWN_ID

SEVERITY_ASSESSMENT_FIELDS = (
    "case_id",
    "pathway_basis",
    "evidence_strength_score",
    "base_points",
    "evidence_contribution",
    "cross_course_pattern_points",
    "distinct_other_course_codes",
    "prior_upheld_count_at_assessment",
    "provisional_severity_index",
    "prior_escalation_points",
    "severity_index",
    "tier_rank",
    "panel_severity_recommendation",
    "recommended_ladder_rank",
    "recommended_kind",
    "permitted_band_min",
    "permitted_band_max",
    "required_panel_size",
    "attorney_advisor_permitted",
    "informal_pathway_permitted",
)


# ---------------------------------------------------------------------------
# Local setup helpers (see the module docstring for why these exist)
# ---------------------------------------------------------------------------


def _trained_faculty(api, officer, department_id, completed_at=None):
    """A faculty member with one training completion on record (PRD §3.1)."""
    member = get_success_data(
        api.create_faculty_member(
            factories.faculty_member_payload(department_id), officer
        ),
        201,
    )
    get_success_data(
        api.create_training_completion(
            member["id"],
            factories.training_completion_payload(
                completed_at=completed_at
                or constants.TEST_DEFAULTS["TRAINING_COMPLETED_AT"]
            ),
            officer,
        )
    )
    return get_success_data(api.get_faculty_member(member["id"], officer))


def _actors(api, officer, **department_overrides):
    """Clock, department, trained reporter, student and offering."""
    fixtures.set_clock(fixtures.CLOCK_T0, officer, api)
    dept = fixtures.create_department(officer, api, **department_overrides)
    reporter = _trained_faculty(api, officer, dept["id"])
    student = fixtures.create_student(officer, api, class_year=3)
    offering = fixtures.create_offering(dept["id"], reporter["id"], officer, api)
    return {
        "clock": fixtures.CLOCK_T0,
        "officer": officer,
        "dean": make_dean_headers(),
        "registrar": make_registrar_headers(),
        "dept": dept,
        "reporter": reporter,
        "reporter_h": make_reporter_headers(reporter["id"]),
        "student": student,
        "student_h": make_student_headers(student["id"]),
        "offering": offering,
        "evidence": [],
        "votes": [],
        "panelists": [],
    }


def _case_world(api, officer, with_proctor_log=False, **department_overrides):
    """`_actors` carried through report -> submit -> triage -> open case."""
    world = _actors(api, officer, **department_overrides)
    fixtures.seed_draft_report(world, client=api)
    if with_proctor_log:
        world["evidence"].append(
            fixtures.attach_proctor_log(
                world["report"]["id"], world["reporter_h"], api
            )
        )
    fixtures.seed_submitted_report(world, client=api)
    fixtures.seed_accepted_report(world, client=api)
    fixtures.seed_case(world, client=api)
    return world


def _extra_case(api, world, class_year=2, sha256=None):
    """A second student on the same offering, carried to an open case."""
    officer = world["officer"]
    student = fixtures.create_student(officer, api, class_year=class_year)
    report = fixtures.create_report(
        world["offering"]["id"], student["id"], world["reporter_h"], api
    )
    evidence = [
        fixtures.attach_similarity_evidence(
            report["id"],
            world["reporter_h"],
            api,
            **({"sha256": sha256} if sha256 else {}),
        )
    ]
    fixtures.submit_report(report["id"], world["reporter_h"], api)
    fixtures.triage_report(report["id"], "ACCEPT", headers=officer, client=api)
    case = fixtures.open_case(report["id"], officer, api)
    return {"student": student, "report": report, "evidence": evidence, "case": case}


def _panel(api, world, panel_size=3):
    """A room, a trained chair and `panel_size` conflict-free panelists."""
    if "room" not in world:
        world["room"] = fixtures.create_room(world["officer"], api)
    world["chair"] = _trained_faculty(
        api, world["officer"], world["dept"]["id"], completed_at="2026-02-01T00:00:00Z"
    )
    world["chair_h"] = make_chair_headers(world["chair"]["id"])
    world["panelists"] = [
        fixtures.create_faculty(
            world["dept"]["id"], trained=False, headers=world["officer"], client=api
        )
        for _ in range(panel_size)
    ]
    return world


# ---------------------------------------------------------------------------
# calculations
# ---------------------------------------------------------------------------


def test_severity_assessment_read_exposes_every_intermediate_for_a_clean_first_offence(
    api, officer
):
    """The whole §3.4 chain is observable on one clean first-offence case.

    PRD §3.4: "This read takes an optional `pathway_basis` (`FORMAL` or
    `INFORMAL`, defaulting to `FORMAL`) and exposes every intermediate" ...
    "With `pathway_basis` set to `INFORMAL`, `cross_course_pattern_points` and
    `prior_escalation_points` are returned as 0 because the informal variant may
    not read them, and `severity_index` carries the informal index."

    Design: Corner/calculations/severity_assessment_read_exposes_every_intermediate_for_a_clean_first_offence
    """
    world = _case_world(api, officer)
    case = world["case"]

    # PRD §3.3: a single 45.00 similarity report over 4 pages scores 60.00.
    assertions.assert_pct_equals(
        world["report"]["evidence_strength_score"], 60.00, "evidence_strength_score"
    )

    formal = assertions.assert_object_envelope(
        api.get_severity_assessment(case["id"], officer)
    )
    for field in SEVERITY_ASSESSMENT_FIELDS:
        assert field in formal, f"severity assessment must expose {field!r}"
    assertions.assert_subset(
        formal,
        {
            "case_id": case["id"],
            "pathway_basis": "FORMAL",
            "evidence_strength_score": 60.00,
            "base_points": 20,
            "evidence_contribution": 24.00,
            "cross_course_pattern_points": 0,
            "distinct_other_course_codes": 0,
            "prior_upheld_count_at_assessment": 0,
            "provisional_severity_index": 44.00,
            "prior_escalation_points": 0,
            "severity_index": 44.00,
            "tier_rank": 3,
            "panel_severity_recommendation": None,
            "recommended_ladder_rank": 3,
            "recommended_kind": "GRADE_PENALTY_COURSE",
            "permitted_band_min": 2,
            "permitted_band_max": 4,
            "required_panel_size": 3,
            "attorney_advisor_permitted": False,
            "informal_pathway_permitted": True,
        },
    )
    for field in (
        "evidence_strength_score",
        "evidence_contribution",
        "provisional_severity_index",
        "severity_index",
    ):
        assertions.assert_two_decimals(formal[field], field)

    # PRD §3.4: the informal variant sees only the evidence score and the
    # violation type, and its band runs from 1 to the informal rank.
    informal = assertions.assert_object_envelope(
        api.get_severity_assessment(
            case["id"], world["reporter_h"], params={"pathway_basis": "INFORMAL"}
        )
    )
    assertions.assert_subset(
        informal,
        {
            "case_id": case["id"],
            "pathway_basis": "INFORMAL",
            "evidence_strength_score": 60.00,
            "base_points": 20,
            "cross_course_pattern_points": 0,
            "prior_escalation_points": 0,
            "severity_index": 44.00,
            "tier_rank": 3,
            "recommended_ladder_rank": 3,
            "recommended_kind": "GRADE_PENALTY_COURSE",
            "permitted_band_min": 1,
            "permitted_band_max": 3,
        },
    )

    # PRD §2.9 rank 5: an enum value outside its declared set is invalid.
    validate_error(
        api.get_severity_assessment(
            case["id"], officer, params={"pathway_basis": "SEMIFORMAL"}
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    stored = fixtures.read_case(case["id"], officer, api)
    assertions.assert_case(
        stored, {"severity_index": 44.00, "recommended_ladder_rank": 3}
    )


def test_reporting_metrics_window_is_inclusive_at_365_days_and_as_of_does_not_move_the_training_clock(
    api, officer, registrar
):
    """`as_of` moves only the reporting window, and 365 days is inside it.

    PRD §3.1: "A report submitted exactly 365 days before the evaluation
    instant is inside the window; one submitted 366 days before is outside." ...
    "`training_completion_pct` is always measured from the current logical clock
    and is never shifted by `as_of`, which moves only the reporting window."

    Design: Corner/calculations/reporting_metrics_window_is_inclusive_at_365_days_and_as_of_does_not_move_the_training_clock
    """
    world = _actors(api, officer)
    fixtures.seed_draft_report(world, client=api)
    fixtures.seed_submitted_report(world, client=api)
    dept_id = world["dept"]["id"]

    default = assertions.assert_object_envelope(
        api.get_department_reporting_metrics(dept_id, officer)
    )
    assertions.assert_subset(
        default,
        {
            "department_id": dept_id,
            "basis": "SUBMITTED",
            "window_days": 365,
            "numerator": 1,
            "enrolled_student_count": 2000,
            "reporting_rate_per_1k": 0.50,
            "faculty_current_count": 1,
            "faculty_headcount": 5,
            "training_completion_pct": 20.00,
        },
    )
    assertions.assert_instant_equals(default["as_of"], fixtures.CLOCK_T0, "as_of")

    # Exactly 365 days after the report's `submitted_at`: still inside the
    # inclusive window, so the numerator is unchanged.
    edge = assertions.assert_object_envelope(
        api.get_department_reporting_metrics(
            dept_id, officer, params={"as_of": "2027-08-01T00:00:00Z"}
        )
    )
    assertions.assert_subset(
        edge,
        {
            "basis": "SUBMITTED",
            "window_days": 365,
            "numerator": 1,
            "reporting_rate_per_1k": 0.50,
            "training_completion_pct": 20.00,
            "monitoring_flag": "TRAINING_DEFICIT",
        },
    )
    assertions.assert_instant_equals(
        edge["as_of"], "2027-08-01T00:00:00Z", "as_of"
    )

    # One day further on the report falls out of the window; the training
    # percentage is still read from the logical clock, which never moved.
    past = assertions.assert_object_envelope(
        api.get_department_reporting_metrics(
            dept_id, registrar, params={"as_of": "2027-08-02T00:00:00Z"}
        )
    )
    assertions.assert_subset(
        past,
        {
            "basis": "SUBMITTED",
            "window_days": 365,
            "numerator": 0,
            "reporting_rate_per_1k": 0.00,
            "faculty_current_count": 1,
            "faculty_headcount": 5,
            "training_completion_pct": 20.00,
            "monitoring_flag": "UNDER_REPORTING",
        },
    )
    assertions.assert_instant_equals(
        past["as_of"], "2027-08-02T00:00:00Z", "as_of"
    )
    for field in ("reporting_rate_per_1k", "training_completion_pct"):
        assertions.assert_two_decimals(past[field], field)


def test_reporting_metrics_basis_variant_and_peer_median_across_two_departments(
    api, officer
):
    """The basis switches the numerator; the peer median spans all departments.

    PRD §3.1: "It accepts an optional `basis` (`SUBMITTED` or `ADJUDICATED`,
    defaulting to `SUBMITTED`)" and "the peer median rate is computed as the
    median of `reporting_rate_per_1k_submitted` across all departments including
    this one ... for an even number of departments the median is the two middle
    values added together, divided by two, rounded to two decimals".

    Design: Corner/calculations/reporting_metrics_window_is_inclusive_at_365_days_and_as_of_does_not_move_the_training_clock
    """
    world = _actors(api, officer)
    fixtures.seed_draft_report(world, client=api)
    fixtures.seed_submitted_report(world, client=api)
    dept_id = world["dept"]["id"]

    alone = assertions.assert_object_envelope(
        api.get_department_reporting_metrics(dept_id, officer)
    )
    assertions.assert_subset(
        alone,
        {
            "numerator": 1,
            "reporting_rate_per_1k": 0.50,
            "peer_median_rate": 0.50,
            "elevated_threshold_rate": 1.00,
            "monitoring_flag": "TRAINING_DEFICIT",
        },
    )

    # No case has ever been decided, so the adjudicated numerator is 0.
    adjudicated = assertions.assert_object_envelope(
        api.get_department_reporting_metrics(
            dept_id, officer, params={"basis": "ADJUDICATED"}
        )
    )
    assertions.assert_subset(
        adjudicated,
        {
            "basis": "ADJUDICATED",
            "window_days": 365,
            "numerator": 0,
            "reporting_rate_per_1k": 0.00,
        },
    )

    # PRD §2.9 rank 5: an enum value outside its declared set is invalid.
    validate_error(
        api.get_department_reporting_metrics(
            dept_id, officer, params={"basis": "WEEKLY"}
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    # A second department at 0.00 pulls the median to (0.00 + 0.50) / 2 = 0.25,
    # so the elevated threshold becomes 0.50 and the strict comparison fails.
    hist = get_success_data(
        api.create_department(
            factories.hist_department_payload(faculty_headcount=2), officer
        ),
        201,
    )
    paired = assertions.assert_object_envelope(
        api.get_department_reporting_metrics(dept_id, officer)
    )
    assertions.assert_subset(
        paired,
        {
            "numerator": 1,
            "reporting_rate_per_1k": 0.50,
            "peer_median_rate": 0.25,
            "elevated_threshold_rate": 0.50,
            "monitoring_flag": "TRAINING_DEFICIT",
        },
    )

    quiet = assertions.assert_object_envelope(
        api.get_department_reporting_metrics(hist["id"], officer)
    )
    assertions.assert_subset(
        quiet,
        {
            "department_id": hist["id"],
            "numerator": 0,
            "enrolled_student_count": 1000,
            "reporting_rate_per_1k": 0.00,
            "faculty_current_count": 0,
            "faculty_headcount": 2,
            "training_completion_pct": 0.00,
            "monitoring_flag": "UNDER_REPORTING",
        },
    )


def test_decide_is_gated_first_by_quorum_then_by_effective_votes_then_computes_the_tally(
    api, officer
):
    """Quorum outranks the effective-vote gate, and only then does the tally run.

    PRD §3.7: "The number of votes cast for the session must be at least
    `quorum_required`, otherwise `ERR_QUORUM_NOT_MET`; abstentions **do** count
    toward quorum. Then at least one vote must be something other than
    `ABSTAIN`, otherwise `ERR_NO_EFFECTIVE_VOTES` ... The quorum check runs
    strictly before the effective-vote check".

    Design: Corner/calculations/decide_is_gated_first_by_quorum_then_by_effective_votes_then_computes_the_tally
    """
    world = _case_world(api, officer)
    fixtures.send_allegation_notice(world, 5, api)
    fixtures.set_pathway(world, "FORMAL", api)
    fixtures.acknowledge_notice(world, api)
    _panel(api, world, 3)
    fixtures.schedule_hearing(world, client=api)
    session_id = world["session"]["id"]

    # ceil(3 * 2 / 3) = 2 (PRD §3.7).
    assertions.assert_hearing_session(
        world["session"],
        {"status": "SCHEDULED", "quorum_required": 2, "round_number": 1},
    )

    fixtures.convene_hearing(world, client=api)

    # One ballot cast is short of the quorum of two.
    fixtures.cast_vote(world, 0, "ABSTAIN", client=api)
    validate_error(
        api.decide_hearing_session(session_id, world["chair_h"]),
        ApiErrorId.ERR_QUORUM_NOT_MET.value,
        409,
    )
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_id, officer)),
        {"status": "CONVENED", "effective_vote_count": 0},
    )

    # Two abstentions meet the quorum but leave no effective vote.
    fixtures.cast_vote(world, 1, "ABSTAIN", client=api)
    validate_error(
        api.decide_hearing_session(session_id, world["chair_h"]),
        ApiErrorId.ERR_NO_EFFECTIVE_VOTES.value,
        409,
    )
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_id, officer)),
        {"status": "CONVENED"},
    )

    # One responsible ballot: 1 * 2 > 1 effective vote, median of [3] is 3.
    fixtures.cast_vote(world, 2, "RESPONSIBLE", 3, client=api)
    decided = assertions.assert_object_envelope(
        api.decide_hearing_session(session_id, world["chair_h"])
    )
    assertions.assert_hearing_session(
        decided,
        {
            "status": "DECIDED",
            "effective_vote_count": 1,
            "panel_finding": "RESPONSIBLE",
            "panel_severity_recommendation": 3,
        },
    )

    case = fixtures.read_case(world["case"]["id"], officer, api)
    assertions.assert_case(
        case,
        {
            "adjudication_status": "DECIDED",
            "responsibility_finding": "RESPONSIBLE",
            "finding_basis": "PANEL",
            "panel_severity_recommendation": 3,
            "severity_index": 44.00,
            "recommended_ladder_rank": 3,
        },
    )
    assertions.assert_instant_equals(
        case["decided_at"], fixtures.SESSION_START, "decided_at"
    )

    rows, meta = assertions.validate_list(
        api.list_panel_votes(officer, params={"session_id": session_id})
    )
    assert meta["total_count"] == 3, f"expected 3 ballots, got {meta['total_count']}"
    for row in rows:
        assertions.assert_panel_vote(row)
    abstentions = [r for r in rows if r["verdict"] == "ABSTAIN"]
    assert len(abstentions) == 2, f"expected 2 abstentions, got {len(abstentions)}"
    for row in abstentions:
        assert row["severity_recommendation"] is None, (
            "an abstention carries no severity_recommendation, got "
            f"{row['severity_recommendation']!r}"
        )


def test_hearing_notice_period_boundary_is_exactly_ten_days(api, officer):
    """One second before the floor is refused; the floor instant itself is not.

    PRD §3.7: "`start_at` must be at or after that notice's `sent_at` plus 10
    days, otherwise `ERR_NOTICE_PERIOD_TOO_SHORT`."  PRD §2.9: "a rejected
    request leaves the store byte-identical to its pre-request state, including
    every derived counter and ledger."

    Design: Corner/calculations/hearing_notice_period_boundary_is_exactly_ten_days
    """
    world = _case_world(api, officer)
    fixtures.send_allegation_notice(world, client=api)
    fixtures.set_pathway(world, "FORMAL", api)
    _panel(api, world, 3)
    assertions.assert_instant_equals(
        world["notice"]["sent_at"], fixtures.CLOCK_T0, "sent_at"
    )
    panelist_ids = [p["id"] for p in world["panelists"]]

    # sent_at + 10 days is 2026-08-11T00:00:00Z; one second earlier is refused.
    validate_error(
        api.create_hearing_session(
            factories.hearing_session_payload(
                world["case"]["id"],
                world["room"]["id"],
                world["chair"]["id"],
                panelist_ids,
                "2026-08-10T23:59:59Z",
                "2026-08-11T01:29:59Z",
            ),
            officer,
        ),
        ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT.value,
        409,
    )
    assertions.assert_hearing_room(
        validate_success(api.get_hearing_room(world["room"]["id"], officer)),
        {"booked_minutes_total": 0},
    )
    assertions.assert_case(
        fixtures.read_case(world["case"]["id"], officer, api),
        {"adjudication_status": "NOTIFIED", "hearing_round": 0},
    )

    session = assertions.assert_object_envelope(
        api.create_hearing_session(
            factories.hearing_session_payload(
                world["case"]["id"],
                world["room"]["id"],
                world["chair"]["id"],
                panelist_ids,
                "2026-08-11T00:00:00Z",
                "2026-08-11T01:30:00Z",
            ),
            officer,
        ),
        201,
    )
    assertions.assert_hearing_session(
        session,
        {
            "status": "SCHEDULED",
            "round_number": 1,
            "quorum_required": 2,
            "required_panel_size": 3,
        },
    )
    assertions.assert_instant_equals(
        session["start_at"], "2026-08-11T00:00:00Z", "start_at"
    )

    # 90 whole minutes plus twice the room's 30-minute buffer (PRD §2.11).
    assertions.assert_hearing_room(
        validate_success(api.get_hearing_room(world["room"]["id"], officer)),
        {"booked_minutes_total": 150},
    )
    assertions.assert_case(
        fixtures.read_case(world["case"]["id"], officer, api),
        {"adjudication_status": "HEARING_SCHEDULED", "hearing_round": 1},
    )
    assertions.assert_page(
        api.list_hearing_sessions(officer, params={"case_id": world["case"]["id"]}),
        [session["id"]],
        expected_total=1,
    )


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


def _two_case_world(api, officer):
    """Case A on the FORMAL pathway; case B dismissed.  Distinct students."""
    world = _case_world(api, officer)
    fixtures.set_pathway(world, "FORMAL", api)
    other = _extra_case(api, world, class_year=2, sha256=constants.SHA256_B)
    other["case"] = validate_success(
        api.dismiss_case(other["case"]["id"], factories.dismiss_payload(), officer)
    )
    assertions.assert_case(other["case"], {"adjudication_status": "DISMISSED"})
    return world, other


def test_case_list_filters_are_conjunctive(api, officer):
    """Two filters narrow the result set together, never separately.

    PRD §2.3: "`total_count` counts every record matching the request's filters
    rather than only those on the current page."  PRD §3.4: "Cases may be listed
    with `report_id`, `student_id`, `offering_id`, `adjudication_status`,
    `notation_status` and `pathway` filters."

    Design: Corner/endpoints/list_filters_are_conjunctive_and_pagination_bounds_are_enforced_at_their_edges
    """
    world, other = _two_case_world(api, officer)
    case_a, case_b = world["case"], other["case"]

    assertions.assert_page(
        api.list_cases(officer, params={"pathway": "FORMAL"}),
        [case_a["id"]],
        expected_total=1,
    )
    assertions.assert_page(
        api.list_cases(officer, params={"adjudication_status": "DISMISSED"}),
        [case_b["id"]],
        expected_total=1,
    )
    # Case A is FORMAL but not dismissed; case B is dismissed but UNASSIGNED.
    assertions.assert_page(
        api.list_cases(
            officer, params={"pathway": "FORMAL", "adjudication_status": "DISMISSED"}
        ),
        [],
        expected_total=0,
        expected_has_more=False,
    )
    assertions.assert_page(
        api.list_cases(
            officer,
            params={
                "student_id": other["student"]["id"],
                "adjudication_status": "DISMISSED",
            },
        ),
        [case_b["id"]],
        expected_total=1,
    )


def test_case_list_pagination_bounds_are_enforced_at_their_edges(api, officer):
    """`limit` 1 and 100 are legal; 0, 101 and a negative offset are not.

    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10,
    may not be smaller than 1, and may not be larger than 100 ... A `limit` or
    `offset` that is not an integer, a `limit` below 1 or above 100, or a
    negative `offset` is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/endpoints/list_filters_are_conjunctive_and_pagination_bounds_are_enforced_at_their_edges
    """
    world, other = _two_case_world(api, officer)
    case_a, case_b = world["case"], other["case"]

    assertions.assert_page(
        api.list_cases(officer, params={"limit": 1}),
        [case_a["id"]],
        expected_total=2,
        expected_limit=1,
        expected_offset=0,
        expected_has_more=True,
    )
    assertions.assert_page(
        api.list_cases(officer, params={"limit": 100}),
        [case_a["id"], case_b["id"]],
        expected_total=2,
        expected_limit=100,
        expected_has_more=False,
    )
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_cases(officer, params=params),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            400,
        )


def test_case_list_pagination_defaults_are_limit_ten_offset_zero(api, officer):
    """An unparameterised list read reports the declared defaults.

    PRD §2.3: "`limit` ... defaults to 10" and "`offset` is the number of
    records to skip before the page begins; it defaults to 0".  "Unless a
    specific endpoint says otherwise, list results are ordered by `created_at`
    ascending."

    Design: Corner/endpoints/list_filters_are_conjunctive_and_pagination_bounds_are_enforced_at_their_edges
    """
    world, other = _two_case_world(api, officer)

    rows, meta = assertions.assert_page(
        api.list_cases(officer),
        [world["case"]["id"], other["case"]["id"]],
        expected_total=2,
        expected_limit=10,
        expected_offset=0,
        expected_has_more=False,
    )
    assertions.assert_created_at_ascending(rows)


def test_parent_scoped_sublists_return_only_their_own_children(api, officer):
    """A sub-resource listing is scoped to its parent and to nothing else.

    PRD §4: "Sub-resource listing of a report's evidence" and "Sub-resource
    listing of a case's notices".  PRD §2.3: "`total_count` counts every record
    matching the request's filters rather than only those on the current page."

    Design: Corner/endpoints/parent_scoped_sublists_return_only_their_own_children_and_404_on_an_unknown_parent
    """
    world = _case_world(api, officer, with_proctor_log=True)
    fixtures.send_allegation_notice(world, 5, api)
    fixtures.request_advisor(world, client=api)
    other = _extra_case(api, world, class_year=2, sha256=constants.SHA256_C)

    report_a, report_b = world["report"], other["report"]
    case_a, case_b = world["case"], other["case"]
    a_evidence = [e["id"] for e in world["evidence"]]
    assert len(a_evidence) == 2, f"report A should hold 2 exhibits, got {a_evidence}"

    rows, _ = assertions.assert_page(
        api.list_report_evidence_items(report_a["id"], officer),
        a_evidence,
        expected_total=2,
    )
    for row in rows:
        assertions.assert_evidence_item(row, {"report_id": report_a["id"]})
    assert sorted(r["kind"] for r in rows) == ["PROCTOR_LOG", "SIMILARITY_REPORT"], (
        f"unexpected kinds {[r['kind'] for r in rows]}"
    )

    # The flat listing under the same filter must agree with the sublist.
    assertions.assert_page(
        api.list_evidence_items(officer, params={"report_id": report_a["id"]}),
        a_evidence,
        expected_total=2,
    )
    assertions.assert_page(
        api.list_report_evidence_items(report_b["id"], officer),
        [other["evidence"][0]["id"]],
        expected_total=1,
    )

    notices, _ = assertions.assert_page(
        api.list_case_notifications(case_a["id"], officer),
        [world["notice"]["id"]],
        expected_total=1,
    )
    assertions.assert_notification(
        notices[0], {"case_id": case_a["id"], "kind": "ALLEGATION_NOTICE"}
    )
    assertions.assert_page(
        api.list_case_notifications(case_b["id"], officer),
        [],
        expected_total=0,
        expected_has_more=False,
    )

    engagements, _ = assertions.assert_page(
        api.list_case_advisor_engagements(case_a["id"], officer),
        [world["engagement"]["id"]],
        expected_total=1,
    )
    assertions.assert_advisor_engagement(
        engagements[0], {"case_id": case_a["id"], "status": "REQUESTED"}
    )
    assertions.assert_page(
        api.list_case_advisor_engagements(case_b["id"], officer),
        [],
        expected_total=0,
        expected_has_more=False,
    )
    assertions.assert_page(
        api.list_case_appeals(case_a["id"], officer),
        [],
        expected_total=0,
        expected_has_more=False,
    )


def test_parent_scoped_sublists_404_on_an_unknown_parent(api, officer):
    """An unknown parent id is the parent's own not-found error, not an empty page.

    PRD §2.6: "Asking for the evidence of a report that does not exist yields
    `ERR_REPORT_NOT_FOUND`; asking for the notices of a case that does not exist
    yields `ERR_CASE_NOT_FOUND`."

    Design: Corner/endpoints/parent_scoped_sublists_return_only_their_own_children_and_404_on_an_unknown_parent
    """
    world = _case_world(api, officer)

    # The same sublists resolve for the real parents, so the 404s below are
    # about the identifier and not about an empty store.
    assertions.assert_page(
        api.list_report_evidence_items(world["report"]["id"], officer),
        [world["evidence"][0]["id"]],
        expected_total=1,
    )
    assertions.assert_page(
        api.list_case_notifications(world["case"]["id"], officer),
        [],
        expected_total=0,
    )

    validate_error(
        api.list_report_evidence_items(UNKNOWN, officer),
        ApiErrorId.ERR_REPORT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_case_notifications(UNKNOWN, officer),
        ApiErrorId.ERR_CASE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_case_advisor_engagements(UNKNOWN, officer),
        ApiErrorId.ERR_CASE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_case_appeals(UNKNOWN, officer),
        ApiErrorId.ERR_CASE_NOT_FOUND.value,
        404,
    )


def test_action_endpoints_return_the_entity_they_create_not_the_entity_in_their_path(
    api, officer
):
    """A creating action answers with its child; a modifying one with its target.

    PRD §3.6: "The response carries the created sanction."  PRD §4: "Operations
    that create a new stand-alone resource, or add a new distinct resource to a
    collection, return a `201 Created` status code.  Operations that modify an
    existing resource — including every state transition ... return a `200 OK`
    status code."

    Design: Corner/endpoints/action_endpoints_return_the_entity_they_create_not_the_entity_in_their_path
    """
    world = _case_world(api, officer)
    case_id = world["case"]["id"]

    notice = assertions.assert_object_envelope(
        api.create_case_notification(
            case_id, factories.notification_payload("ALLEGATION_NOTICE", 5), officer
        ),
        201,
    )
    assertions.assert_notification(
        notice,
        {
            "case_id": case_id,
            "kind": "ALLEGATION_NOTICE",
            "response_window_days": 5,
            "acknowledged_at": None,
        },
    )
    assert notice["id"] != case_id, "the notice must not be identified by its case"
    assertions.assert_notification(
        validate_success(api.get_notification(notice["id"], officer)),
        {"id": notice["id"]},
    )

    # Acknowledgement modifies the notification named in the path.
    acknowledged = assertions.assert_object_envelope(
        api.acknowledge_notification(notice["id"], world["student_h"])
    )
    assert acknowledged["id"] == notice["id"], (
        "acknowledge must answer with the notification in its path"
    )
    assertions.assert_instant_equals(
        acknowledged["acknowledged_at"], fixtures.CLOCK_T0, "acknowledged_at"
    )

    fixtures.set_pathway(world, "INFORMAL", api)
    version_before = fixtures.case_version(case_id, officer, api)
    sanction = assertions.assert_object_envelope(
        api.create_informal_resolution(
            case_id,
            factories.informal_resolution_payload(
                version_before, 3, "2026-08-21T00:00:00Z"
            ),
            world["reporter_h"],
        ),
        201,
    )
    assertions.assert_sanction(
        sanction,
        {
            "case_id": case_id,
            "status": "PROPOSED",
            "origin": "INFORMAL_PROPOSAL",
            "ladder_rank": 3,
            "kind": "GRADE_PENALTY_COURSE",
        },
    )
    assert sanction["id"] != case_id, "the sanction must not be identified by its case"
    assertions.assert_sanction(
        validate_success(api.get_sanction(sanction["id"], officer)),
        {"id": sanction["id"]},
    )

    # The student's response modifies the case, so §4 pins it at 200 OK.
    # `assert_object_envelope` also re-checks `meta.api_request_id` and
    # `meta.api_request_timestamp` on every response asserted in this test.
    assertions.assert_object_envelope(
        api.create_informal_response(
            case_id, factories.informal_response_payload("ACCEPT"), world["student_h"]
        )
    )
    assertions.assert_case(
        fixtures.read_case(case_id, officer, api),
        {
            "adjudication_status": "INFORMAL_ACCEPTED",
            "responsibility_finding": "RESPONSIBLE",
            "finding_basis": "ADMISSION",
            "version": version_before + 2,
        },
    )
    assertions.assert_sanction(
        validate_success(api.get_sanction(sanction["id"], officer)),
        {"status": "ACCEPTED"},
    )


def test_training_completion_returns_the_recomputed_faculty_member_in_its_path(
    api, officer
):
    """Recording training answers with the member, and re-derives the department.

    PRD §3.1: "A member's `training_completed_at` and `training_module_code` are
    then re-derived from the newest completion on record ... Recording a
    completion also recomputes the department's `training_completion_pct` and
    `monitoring_flag`."

    Design: Corner/endpoints/action_endpoints_return_the_entity_they_create_not_the_entity_in_their_path
    """
    fixtures.set_clock(fixtures.CLOCK_T0, officer, api)
    dept = fixtures.create_department(officer, api)
    member = fixtures.create_faculty(
        dept["id"], trained=False, headers=officer, client=api
    )
    assertions.assert_faculty_member(member, {"training_status": "LAPSED"})

    response = api.create_training_completion(
        member["id"], factories.training_completion_payload(), officer
    )
    # §4's table gives no status for this row: the body is the recomputed member
    # (200 by §4's preamble) yet a completion joins a collection (201), so the
    # PRD admits either and only the body is asserted below.
    assert response.status_code in (200, 201), (
        f"expected 200 or 201, got {response.status_code}: {response.text}"
    )
    recomputed = get_success_data(response)
    assertions.assert_envelope_meta(response)
    assert response.json()["response_type"] == "object", (
        f"expected an object envelope, got {response.json()['response_type']!r}"
    )
    assertions.assert_faculty_member(
        recomputed,
        {
            "id": member["id"],
            "department_id": dept["id"],
            "training_status": "CURRENT",
            "training_module_code": constants.TEST_DEFAULTS["TRAINING_MODULE_CODE"],
        },
    )
    assertions.assert_instant_equals(
        recomputed["training_completed_at"],
        constants.TEST_DEFAULTS["TRAINING_COMPLETED_AT"],
        "training_completed_at",
    )

    # One current member against a census headcount of five is 20.00 (PRD §3.1).
    assertions.assert_department(
        validate_success(api.get_department(dept["id"], officer)),
        {
            "training_completion_pct": 20.00,
            "faculty_headcount": 5,
            "monitoring_flag": "UNDER_REPORTING",
        },
    )


def test_meeting_outcome_is_a_conditional_action_gated_on_the_clock_and_the_current_status(
    api, officer
):
    """The clock gate and the state gate are separate, and the state gate wins.

    PRD §3.5: "The outcome is recorded once, with an `outcome` of `HELD`,
    `NO_SHOW` or `CANCELLED`, and only from `SCHEDULED`; anything else is
    `ERR_MEETING_STATE_INVALID` ... `HELD` may not be recorded before `start_at`
    and `NO_SHOW` may not be recorded before `end_at`; an early attempt is
    `ERR_MEETING_WINDOW_INVALID`."

    Design: Corner/endpoints/meeting_outcome_is_a_conditional_action_gated_on_the_clock_and_the_current_status
    """
    world = _case_world(api, officer)
    fixtures.send_allegation_notice(world, client=api)
    fixtures.set_pathway(world, "INFORMAL", api)
    case_id = world["case"]["id"]

    meetings = []
    for day in ("05", "06", "07"):
        meeting = assertions.assert_object_envelope(
            api.create_case_meeting(
                factories.case_meeting_payload(
                    case_id,
                    world["reporter"]["id"],
                    f"2026-08-{day}T14:00:00Z",
                    f"2026-08-{day}T15:00:00Z",
                ),
                officer,
            ),
            201,
        )
        assertions.assert_case_meeting(
            meeting, {"status": "SCHEDULED", "duration_minutes": 60}
        )
        meetings.append(meeting)
    first, second, third = meetings

    # The clock is still at 2026-08-01, before the first meeting's start_at.
    validate_error(
        api.record_meeting_outcome(
            first["id"], factories.meeting_outcome_payload("HELD"), world["reporter_h"]
        ),
        ApiErrorId.ERR_MEETING_WINDOW_INVALID.value,
        409,
    )
    # Cancelling is an office action and carries no clock gate at all.
    assertions.assert_case_meeting(
        assertions.assert_object_envelope(
            api.record_meeting_outcome(
                third["id"], factories.meeting_outcome_payload("CANCELLED"), officer
            )
        ),
        {"status": "CANCELLED", "advisor_present": False},
    )

    fixtures.set_clock("2026-08-05T14:00:00Z", officer, api)
    assertions.assert_case_meeting(
        assertions.assert_object_envelope(
            api.record_meeting_outcome(
                first["id"],
                factories.meeting_outcome_payload("HELD"),
                world["reporter_h"],
            )
        ),
        {"status": "HELD", "advisor_present": False},
    )

    # HELD is terminal: the §2.9 rank-18 state gate now refuses every replay,
    # including a NO_SHOW that the rank-41 clock gate would also have refused.
    validate_error(
        api.record_meeting_outcome(
            first["id"], factories.meeting_outcome_payload("CANCELLED"), officer
        ),
        ApiErrorId.ERR_MEETING_STATE_INVALID.value,
        409,
    )
    validate_error(
        api.record_meeting_outcome(
            first["id"],
            factories.meeting_outcome_payload("NO_SHOW"),
            world["reporter_h"],
        ),
        ApiErrorId.ERR_MEETING_STATE_INVALID.value,
        409,
    )

    # NO_SHOW is gated on end_at, not start_at: one second short is refused.
    fixtures.set_clock("2026-08-06T14:59:59Z", officer, api)
    validate_error(
        api.record_meeting_outcome(
            second["id"],
            factories.meeting_outcome_payload("NO_SHOW"),
            world["reporter_h"],
        ),
        ApiErrorId.ERR_MEETING_WINDOW_INVALID.value,
        409,
    )
    fixtures.set_clock("2026-08-06T15:00:00Z", officer, api)
    assertions.assert_case_meeting(
        assertions.assert_object_envelope(
            api.record_meeting_outcome(
                second["id"],
                factories.meeting_outcome_payload("NO_SHOW"),
                world["reporter_h"],
            )
        ),
        {"status": "NO_SHOW", "advisor_present": False},
    )

    rows, meta = assertions.validate_list(
        api.list_case_meetings(officer, params={"case_id": case_id})
    )
    assert meta["total_count"] == 3, f"expected 3 meetings, got {meta['total_count']}"
    assert sorted(r["status"] for r in rows) == ["CANCELLED", "HELD", "NO_SHOW"], (
        f"unexpected statuses {[r['status'] for r in rows]}"
    )
    # Recording an outcome never touches the case's own state machine.
    assertions.assert_case(
        fixtures.read_case(case_id, officer, api), {"adjudication_status": "NOTIFIED"}
    )


def test_the_severity_assessment_read_is_side_effect_free_and_pathway_basis_never_persists(
    api, officer
):
    """Repeated reads agree, and an INFORMAL basis never leaks onto the case.

    PRD §3.4: "The read re-runs the assessment, so a case whose sibling history
    has changed reports fresh numbers" and "The office sets `pathway` to
    `INFORMAL` or `FORMAL` on a case in `INTAKE_REVIEW` or `NOTIFIED` ... The
    only other way `pathway` ever changes is the student declining an informal
    proposal".

    Design: Corner/endpoints/the_severity_assessment_read_is_side_effect_free_and_pathway_basis_never_persists
    """
    world = _case_world(api, officer)
    case_id = world["case"]["id"]
    formal_expected = {
        "pathway_basis": "FORMAL",
        "severity_index": 44.00,
        "tier_rank": 3,
        "recommended_ladder_rank": 3,
        "permitted_band_min": 2,
        "permitted_band_max": 4,
        "required_panel_size": 3,
    }

    first = assertions.assert_object_envelope(
        api.get_severity_assessment(case_id, officer)
    )
    assertions.assert_subset(first, formal_expected)

    second = assertions.assert_object_envelope(
        api.get_severity_assessment(case_id, officer)
    )
    assert second == first, "an unchanged case must report an identical assessment"

    informal = assertions.assert_object_envelope(
        api.get_severity_assessment(
            case_id, officer, params={"pathway_basis": "INFORMAL"}
        )
    )
    assertions.assert_subset(
        informal,
        {
            "pathway_basis": "INFORMAL",
            "severity_index": 44.00,
            "recommended_ladder_rank": 3,
            "permitted_band_min": 1,
            "permitted_band_max": 3,
        },
    )

    fourth = assertions.assert_object_envelope(
        api.get_severity_assessment(case_id, officer)
    )
    assert fourth == first, (
        "an INFORMAL-basis read must not change what a later FORMAL read returns"
    )

    # The case keeps the formal placement and its pathway is still unassigned.
    assertions.assert_case(
        fixtures.read_case(case_id, officer, api),
        {
            "pathway": "UNASSIGNED",
            "severity_index": 44.00,
            "recommended_ladder_rank": 3,
            "informal_recommended_ladder_rank": 3,
            "adjudication_status": "INTAKE_REVIEW",
        },
    )
    # A read creates nothing: no sanction, and no notice to the student.
    assertions.assert_page(
        api.list_sanctions(officer, params={"case_id": case_id}),
        [],
        expected_total=0,
        expected_has_more=False,
    )
    assertions.assert_page(
        api.list_case_notifications(case_id, officer), [], expected_total=0
    )
