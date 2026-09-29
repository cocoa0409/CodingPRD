"""Corner cases: authentication, RBAC, optimistic concurrency and immediacy.

Translated from the `errors`, `rbac`, `cross_cutting_complexity_layers` and
`consistency_model` sections of the corner design index.  Every test carries
the `Design:` tag of the single instance it translates.

The harness restarts the server before every individual test, so each test
rebuilds all of its preconditions through public endpoints; the logical clock
starts at `2026-08-01T00:00:00Z` (PRD §2.4).
"""
from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures, test_users
from test_helpers.api_errors import ApiErrorId

# ---------------------------------------------------------------------------
# Shared world builders.  These are plain module functions, not fixtures: the
# server is restarted before every test, so nothing here may be cached.
# ---------------------------------------------------------------------------


def _seed_rank_eight_completed_notation(client):
    """A CONTRACT_CHEATING case that lands at severity 108.60 and rank 8.

    Two closed priors in two other courses give 2 distinct other course codes
    (10 cross-course points) and a `prior_upheld_count` of 2.  The SEED-B
    exhibit pair freezes `evidence_strength_score` at 81.50, so the case
    reaches a provisional 82.60, takes 26 escalation points and lands at
    108.60 -> tier 8 (PRD §3.4).  A five-member panel then votes RESPONSIBLE
    at 8 five times, and the rank-8 sanction is proposed, imposed, its
    notation posted, and finally completed.
    """
    world = fixtures.seed_actors(client=client)
    fixtures.seed_legacy_prior_case(
        world,
        decided_at="2025-06-01T00:00:00Z",
        completed_at="2025-07-01T00:00:00Z",
        imposed_ladder_rank=2,
        course_code="HIST-110",
        client=client,
    )
    fixtures.seed_legacy_prior_case(
        world,
        decided_at="2025-09-01T00:00:00Z",
        completed_at="2025-10-01T00:00:00Z",
        imposed_ladder_rank=3,
        course_code="PHIL-220",
        client=client,
    )
    fixtures.seed_draft_report(
        world, client=client, alleged_violation_type="CONTRACT_CHEATING"
    )
    world["evidence"].append(
        fixtures.attach_proctor_log(world["report"]["id"], world["reporter_h"], client)
    )
    fixtures.seed_submitted_report(world, client=client)
    fixtures.seed_accepted_report(world, client=client)
    fixtures.seed_case(world, client=client)
    fixtures.seed_notified_case(world, response_window_days=5, client=client)
    fixtures.set_pathway(world, "FORMAL", client)
    fixtures.acknowledge_notice(world, client)
    fixtures.seed_panel(world, panel_size=5, client=client)
    fixtures.schedule_hearing(world, client=client)
    fixtures.convene_hearing(world, client=client)
    for index in range(5):
        fixtures.cast_vote(world, index, "RESPONSIBLE", 8, client)
    fixtures.decide_hearing(world, client)
    fixtures.propose_sanction(world, ladder_rank=8, client=client)
    fixtures.impose_sanction(world, client=client)
    fixtures.post_notation(world, client)
    fixtures.complete_sanction(world, client=client)
    return world


def _seed_auth_world(client):
    """One department, one faculty member and one student — nothing else."""
    officer = test_users.make_officer_headers()
    fixtures.set_clock(constants.DEFAULT_CLOCK_UTC, officer, client)
    dept = fixtures.create_department(officer, client)
    faculty = fixtures.create_faculty(
        dept["id"], trained=False, headers=officer, client=client
    )
    student = fixtures.create_student(officer, client, class_year=3)
    return {
        "officer": officer,
        "dept": dept,
        "faculty": faculty,
        "student": student,
    }


def _seed_rbac_world(client):
    """A FORMAL case on Sam with a SCHEDULED session, plus unrelated Lee.

    The allegation notice is deliberately left unacknowledged so the wrong-chair
    convene probe has a live response-window precondition behind the 403.
    """
    world = fixtures.seed_hearing_scheduled(client=client, response_window_days=5)
    world["other_student"] = fixtures.create_student(
        world["officer"],
        client,
        class_year=2,
        program_code="BA-HIS",
    )
    world["other_student_h"] = test_users.make_student_headers(
        world["other_student"]["id"]
    )
    return world


def _seed_informal_case_for_other_student(world, client):
    """Open a second student's case on the INFORMAL pathway, NOTIFIED.

    No fixture composes a case for a second student, so the hops are inlined
    from the same public endpoints the fixtures use.
    """
    other_student = fixtures.create_student(
        world["officer"], client, class_year=2, program_code="BA-HIS"
    )
    report = fixtures.create_report(
        world["offering"]["id"],
        other_student["id"],
        world["reporter_h"],
        client,
        incident_at="2026-07-21T00:00:00Z",
    )
    fixtures.attach_similarity_evidence(
        report["id"], world["reporter_h"], client, sha256=constants.SHA256_B
    )
    fixtures.submit_report(report["id"], world["reporter_h"], client)
    fixtures.triage_report(
        report["id"], "ACCEPT", headers=world["officer"], client=client
    )
    case = fixtures.open_case(report["id"], world["officer"], client)
    validate_success(
        client.set_case_pathway(
            case["id"], factories.pathway_payload("INFORMAL"), world["officer"]
        )
    )
    validate_success(
        client.create_case_notification(
            case["id"],
            factories.notification_payload("ALLEGATION_NOTICE", 5),
            world["officer"],
        ),
        201,
    )
    return other_student, fixtures.read_case(case["id"], world["officer"], client)


# ---------------------------------------------------------------------------
# Corner/errors/an_expulsion_recommendation_notation_can_never_be_expunged_even_after_completion
# ---------------------------------------------------------------------------


def test_completed_rank_eight_notation_is_refused_as_not_expungeable(api, officer):
    """PRD §3.4: "A contract-cheating case with the same evidence and pattern
    points reaches a provisional 82.60, takes 26, and lands at 108.60, still
    under the cap."  PRD §3.10: "`expungement_eligible_at` is null ... when the
    governing sanction's `ladder_rank` is 8, because a notation arising from an
    expulsion recommendation is permanent", and the request "is rejected with
    `ERR_NOTATION_NOT_EXPUNGEABLE` when the governing sanction's `ladder_rank`
    is 8 and therefore carries no waiting period at all".

    Design: Corner/errors/an_expulsion_recommendation_notation_can_never_be_expunged_even_after_completion
    """
    world = _seed_rank_eight_completed_notation(api)
    case_id = world["case"]["id"]

    assessment = validate_success(api.get_severity_assessment(case_id, officer))
    assertions.assert_pct_equals(
        assessment["evidence_strength_score"], 81.50, "evidence_strength_score"
    )
    assert assessment["base_points"] == 40
    assertions.assert_pct_equals(
        assessment["evidence_contribution"], 32.60, "evidence_contribution"
    )
    assert assessment["distinct_other_course_codes"] == 2
    assert assessment["cross_course_pattern_points"] == 10
    assert assessment["prior_upheld_count_at_assessment"] == 2
    assertions.assert_pct_equals(
        assessment["provisional_severity_index"], 82.60, "provisional_severity_index"
    )
    assert assessment["prior_escalation_points"] == 26
    assertions.assert_pct_equals(
        assessment["severity_index"], 108.60, "severity_index"
    )
    assert assessment["tier_rank"] == 8
    assert assessment["panel_severity_recommendation"] == 8
    assert assessment["recommended_ladder_rank"] == 8
    assert assessment["recommended_kind"] == "EXPULSION_RECOMMENDATION"
    assert assessment["permitted_band_min"] == 7
    assert assessment["permitted_band_max"] == 8
    assert assessment["required_panel_size"] == 5

    session = validate_success(api.get_hearing_session(world["session"]["id"], officer))
    assert session["quorum_required"] == 4
    assert session["effective_vote_count"] == 5
    assert session["panel_finding"] == "RESPONSIBLE"
    assert session["panel_severity_recommendation"] == 8

    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["kind"] == "EXPULSION_RECOMMENDATION"
    assert sanction["ladder_rank"] == 8
    assert sanction["status"] == "COMPLETED"
    assertions.assert_instant_equals(
        sanction["completed_at"], "2026-08-20T10:00:00Z", "sanction.completed_at"
    )

    case = validate_success(api.get_case(case_id, officer))
    assert case["notation_status"] == "POSTED"
    assert case["adjudication_status"] == "CLOSED"
    assert case["expungement_eligible_at"] is None

    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["transcript_notation"] == "POSTED"
    assert student["active_sanction_points"] == 0

    version_before = case["version"]
    validate_error(
        api.request_expungement(
            case_id,
            factories.expungement_request_payload(
                request_statement="Three years have passed and I have completed every requirement."
            ),
            world["student_h"],
        ),
        ApiErrorId.ERR_NOTATION_NOT_EXPUNGEABLE,
        409,
    )

    after = validate_success(api.get_case(case_id, officer))
    assert after["notation_status"] == "POSTED"
    assert after["expungement_eligible_at"] is None
    assert after["version"] == version_before


def test_expulsion_notation_refusal_is_unconditional_in_time(api, officer):
    """PRD §3.10: the request "is rejected with `ERR_NOTATION_NOT_EXPUNGEABLE`
    when the governing sanction's `ladder_rank` is 8 and therefore carries no
    waiting period at all" — there is no instant after which it succeeds.

    Design: Corner/errors/an_expulsion_recommendation_notation_can_never_be_expunged_even_after_completion
    """
    world = _seed_rank_eight_completed_notation(api)
    case_id = world["case"]["id"]

    fixtures.set_clock("2036-08-20T10:00:00Z", officer, api)

    validate_error(
        api.request_expungement(
            case_id,
            factories.expungement_request_payload(
                request_statement="A full decade has now passed."
            ),
            world["student_h"],
        ),
        ApiErrorId.ERR_NOTATION_NOT_EXPUNGEABLE,
        409,
    )

    case = validate_success(api.get_case(case_id, officer))
    assert case["notation_status"] == "POSTED"
    assert case["expungement_eligible_at"] is None


# ---------------------------------------------------------------------------
# Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
# ---------------------------------------------------------------------------


def test_absent_role_header_is_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is absent ... the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_departments(test_users.headers_without_role("officer-001")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_empty_role_header_is_unauthenticated(api):
    """PRD §2.1: `X-User-Role` "present but carries an empty string ... is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_departments(test_users.headers_with_empty_role("officer-001")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_whitespace_only_role_header_is_unauthenticated(api):
    """PRD §2.1: `X-User-Role` carrying "a value consisting only of spaces" is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_departments(test_users.headers_with_whitespace_role("officer-001")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_unknown_role_name_is_unauthenticated_not_role_not_permitted(api):
    """PRD §2.1: "`ERR_UNAUTHENTICATED` is also the answer when `X-User-Role`
    names a value outside the six-role set" — it never reaches rank 3's
    `ERR_ROLE_NOT_PERMITTED` (PRD §2.9).

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_departments(build_user_headers("provost-001", "Provost")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_entity_backed_role_without_user_id_is_unauthenticated(api):
    """PRD §2.1: the rejection "applies when `X-User-ID` is absent, empty or
    whitespace-only, with one narrow tolerance: `IntegrityOfficer`,
    `AppealsDean` and `RegistrarOfficer` may omit `X-User-ID` on read-only
    endpoints" — a `FacultyReporter` enjoys no such tolerance.

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_reports(test_users.headers_without_user_id("FacultyReporter")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_entity_backed_role_with_empty_user_id_is_unauthenticated(api):
    """PRD §2.1: the same rejection "applies when `X-User-ID` is absent, empty
    or whitespace-only", and the tolerance covers only the three opaque roles.

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_reports(test_users.headers_with_empty_user_id("FacultyReporter")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_entity_backed_role_with_whitespace_user_id_is_unauthenticated(api):
    """PRD §2.1: the same rejection "applies when `X-User-ID` is absent, empty
    or whitespace-only", and the tolerance covers only the three opaque roles.

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_reports(test_users.headers_with_whitespace_user_id("FacultyReporter")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_entity_backed_role_with_unresolvable_user_id_is_unauthenticated(api):
    """PRD §2.1: `ERR_UNAUTHENTICATED` is the answer "when a role that is backed
    by a stored entity carries an `X-User-ID` that resolves to no such row."

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.list_reports(test_users.make_reporter_headers(constants.UNKNOWN_ID)),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_student_role_carrying_a_faculty_member_id_is_unauthenticated(api):
    """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the
    acting `Student` row" — an id that exists but not as a `Student` row
    "resolves to no such row" and is `ERR_UNAUTHENTICATED`.

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    world = _seed_auth_world(api)
    validate_error(
        api.get_student(
            world["student"]["id"],
            test_users.make_student_headers(world["faculty"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_unknown_role_pre_empts_the_path_existence_lookup(api):
    """PRD §2.9: authentication is "Ranks 1 and 2 ... on every endpoint" while
    "Rank 8 — **path existence**: an `{id}` in the path that matches no stored
    row → the resource's not-found error (404)" runs far later.

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    validate_error(
        api.get_department(
            constants.UNKNOWN_ID, build_user_headers("provost-001", "Provost")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_opaque_officer_id_is_never_resolved(api):
    """PRD §2.1: `IntegrityOfficer`, `AppealsDean` and `RegistrarOfficer` are not
    "tied to any stored record", so an office identifier matching no row still
    authenticates.

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    _seed_auth_world(api)
    rows, meta = assertions.validate_list(
        api.list_departments(test_users.make_officer_headers(constants.UNKNOWN_ID))
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_student_reading_its_own_row_authenticates(api):
    """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the
    acting `Student` row"; PRD §4 lists `Student` on
    `GET /integrity/students/{id}`.

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    world = _seed_auth_world(api)
    student_id = world["student"]["id"]
    data = validate_success(
        api.get_student(student_id, test_users.make_student_headers(student_id))
    )
    assert data["id"] == student_id


def test_authentication_failures_create_and_modify_no_rows(api, officer):
    """PRD §2.9: "Every rule is evaluated before any side effect is applied, and
    no partial write is ever observable: a rejected request leaves the store
    byte-identical to its pre-request state."

    Design: Corner/errors/every_authentication_failure_mode_returns_unauthenticated_before_any_other_check
    """
    world = _seed_auth_world(api)
    probes = [
        api.list_departments(test_users.headers_without_role("officer-001")),
        api.list_departments(test_users.headers_with_empty_role("officer-001")),
        api.list_departments(build_user_headers("provost-001", "Provost")),
        api.list_reports(test_users.headers_without_user_id("FacultyReporter")),
        api.list_reports(test_users.make_reporter_headers(constants.UNKNOWN_ID)),
        api.get_student(
            world["student"]["id"],
            test_users.make_student_headers(world["faculty"]["id"]),
        ),
    ]
    for response in probes:
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    _, student_meta = assertions.validate_list(api.list_students(officer))
    assert student_meta["total_count"] == 1
    _, faculty_meta = assertions.validate_list(api.list_faculty_members(officer))
    assert faculty_meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
# ---------------------------------------------------------------------------


def test_officer_may_not_file_an_appeal(api, officer):
    """PRD §2.9: "Rank 3 — **role authorization**, on every endpoint: the
    resolved role is absent from the endpoint's authorized set →
    `ERR_ROLE_NOT_PERMITTED` (403)."  PRD §4 authorizes only `Student` on
    `POST /integrity/appeals`.

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                world["case"]["id"],
                statement="The office filing an appeal on the student's behalf.",
            ),
            officer,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_officer_may_not_cast_a_panel_vote(api, officer):
    """PRD §4 authorizes only `PanelChair` on `POST /integrity/panel-votes`, and
    PRD §3.7 has votes "recorded only while the session is `CONVENED`, and only
    by that session's chair"; PRD §2.9 rank 3 gives `ERR_ROLE_NOT_PERMITTED`.

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.create_panel_vote(
            factories.panel_vote_payload(
                world["session"]["id"],
                world["panelists"][0]["id"],
                "RESPONSIBLE",
                3,
            ),
            officer,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_officer_may_not_post_a_notation(api, officer):
    """PRD §3.10: "The notation dimension belongs to the registrar and the
    student. No office or dean operation posts a notation" — PRD §2.9 rank 3
    answers with `ERR_ROLE_NOT_PERMITTED`.

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.post_notation(world["case"]["id"], officer),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_chair_may_not_propose_a_sanction(api, officer):
    """PRD §4 authorizes only `IntegrityOfficer` on `POST /integrity/sanctions`;
    PRD §2.9 rank 3 → `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    version = fixtures.case_version(world["case"]["id"], officer, api)
    validate_error(
        api.create_sanction(
            factories.sanction_payload(
                world["case"]["id"], version, 3, "2026-08-21T00:00:00Z"
            ),
            world["chair_h"],
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_dean_may_not_propose_a_sanction(api, officer, dean):
    """PRD §3.9: the dean's only sanction route is the `SANCTION_REDUCED`
    outcome; PRD §4 authorizes only `IntegrityOfficer` on
    `POST /integrity/sanctions`, so PRD §2.9 rank 3 gives
    `ERR_ROLE_NOT_PERMITTED`.

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    version = fixtures.case_version(world["case"]["id"], officer, api)
    validate_error(
        api.create_sanction(
            factories.sanction_payload(
                world["case"]["id"], version, 3, "2026-08-21T00:00:00Z"
            ),
            dean,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_dean_may_not_decide_a_hearing(api, dean):
    """PRD §4 authorizes only `PanelChair` on
    `POST /integrity/hearing-sessions/{id}/decide`; PRD §2.9 rank 3 →
    `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.decide_hearing_session(world["session"]["id"], dean),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_registrar_may_not_dismiss_a_case(api, registrar):
    """PRD §3.4: "The office may dismiss a case"; PRD §4 authorizes only
    `IntegrityOfficer` on `POST /integrity/cases/{id}/dismiss`, so PRD §2.9
    rank 3 gives `ERR_ROLE_NOT_PERMITTED`.

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.dismiss_case(
            world["case"]["id"],
            factories.dismiss_payload(
                dismiss_reason="The registrar attempting an adjudication write."
            ),
            registrar,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_officer_may_not_author_a_report_even_with_an_invalid_payload(api, officer):
    """PRD §2.9: rank 3 role authorization precedes "Ranks 5 and 6 — **request
    shape** ... a required body field that is missing or null ... Both ranks
    return `ERR_INVALID_REQUEST` (400)", so the 403 wins.

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.create_report(
            {
                "offering_id": world["offering"]["id"],
                "student_id": world["other_student"]["id"],
                "alleged_violation_type": "PLAGIARISM",
                "narrative": "The office attempting to author a report.",
            },
            officer,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_student_may_not_list_cases(api):
    """PRD §4 authorizes `IntegrityOfficer`, `RegistrarOfficer` and
    `AppealsDean` on `GET /integrity/cases`; PRD §2.9 rank 3 →
    `ERR_ROLE_NOT_PERMITTED` (403).

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.list_cases(world["student_h"]),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_unrelated_student_filing_an_appeal_is_an_ownership_failure(api):
    """PRD §2.9: "Rank 4 — **ownership**, on ... `POST /integrity/appeals` ...:
    the acting identity is not the owner the endpoint demands →
    `ERR_NOT_RESOURCE_OWNER` (403)" — the role is permitted, the identity is
    not (PRD §3.9: "The case's own student files an appeal").

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                world["case"]["id"],
                statement="An unrelated student filing on someone else's case.",
            ),
            world["other_student_h"],
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )


def test_unrelated_student_may_not_acknowledge_another_students_notice(api):
    """PRD §2.9 rank 4 covers `POST /integrity/notifications/{id}/acknowledge`
    with `ERR_NOT_RESOURCE_OWNER` (403); PRD §4: "Student acknowledges receipt".

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.acknowledge_notification(
            world["notice"]["id"], world["other_student_h"]
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )


def test_panelist_acting_as_chair_may_not_convene(api):
    """PRD §3.7: "The session's own chair convenes a `SCHEDULED` session"; PRD
    §2.9 rank 4 covers `POST /integrity/hearing-sessions/{id}/convene` with
    `ERR_NOT_RESOURCE_OWNER` (403), ahead of every state precondition.

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.convene_hearing_session(
            world["session"]["id"],
            test_users.make_chair_headers(world["panelists"][0]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )


def test_faculty_member_who_is_not_the_reporter_may_not_submit_the_report(api):
    """PRD §2.9 rank 4 covers `POST /integrity/reports/{id}/submit` with
    `ERR_NOT_RESOURCE_OWNER` (403); ownership "compare[s] that resource's
    faculty foreign key to `X-User-ID`" (PRD §2.1).

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    validate_error(
        api.submit_report(
            world["report"]["id"],
            test_users.make_reporter_headers(world["chair"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )


def test_refused_role_and_ownership_writes_leave_the_store_untouched(api, officer, dean, registrar):
    """PRD §2.9: "a rejected request leaves the store byte-identical to its
    pre-request state, including every derived counter and ledger."

    Design: Corner/rbac/exclusive_operations_are_closed_to_other_roles_and_ownership_is_checked_after_the_role
    """
    world = _seed_rbac_world(api)
    case_id = world["case"]["id"]
    session_id = world["session"]["id"]
    version_before = fixtures.case_version(case_id, officer, api)

    role_refusals = [
        api.create_appeal(factories.appeal_payload(case_id), officer),
        api.create_panel_vote(
            factories.panel_vote_payload(
                session_id, world["panelists"][0]["id"], "RESPONSIBLE", 3
            ),
            officer,
        ),
        api.post_notation(case_id, officer),
        api.create_sanction(
            factories.sanction_payload(
                case_id, version_before, 3, "2026-08-21T00:00:00Z"
            ),
            world["chair_h"],
        ),
        api.create_sanction(
            factories.sanction_payload(
                case_id, version_before, 3, "2026-08-21T00:00:00Z"
            ),
            dean,
        ),
        api.decide_hearing_session(session_id, dean),
        api.dismiss_case(case_id, factories.dismiss_payload(), registrar),
        api.list_cases(world["student_h"]),
    ]
    for response in role_refusals:
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    owner_refusals = [
        api.create_appeal(factories.appeal_payload(case_id), world["other_student_h"]),
        api.acknowledge_notification(world["notice"]["id"], world["other_student_h"]),
        api.convene_hearing_session(
            session_id, test_users.make_chair_headers(world["panelists"][0]["id"])
        ),
        api.submit_report(
            world["report"]["id"],
            test_users.make_reporter_headers(world["chair"]["id"]),
        ),
    ]
    for response in owner_refusals:
        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    assert fixtures.case_version(case_id, officer, api) == version_before
    _, appeal_meta = assertions.validate_list(api.list_case_appeals(case_id, officer))
    assert appeal_meta["total_count"] == 0
    _, vote_meta = assertions.validate_list(
        api.list_panel_votes(officer, {"session_id": session_id})
    )
    assert vote_meta["total_count"] == 0
    _, sanction_meta = assertions.validate_list(
        api.list_sanctions(officer, {"case_id": case_id})
    )
    assert sanction_meta["total_count"] == 0
    notice = validate_success(api.get_notification(world["notice"]["id"], officer))
    assert notice["acknowledged_at"] is None


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_expected_case_version_with_412_and_write_nothing
# ---------------------------------------------------------------------------


def test_formal_proposal_with_a_never_current_version_is_rejected(api, officer):
    """PRD §2.8: "the server compares the supplied value with the target case's
    current `version`; if they differ, the write is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is created."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_expected_case_version_with_412_and_write_nothing
    """
    world = fixtures.seed_decided_case(client=api)
    case_id = world["case"]["id"]
    version = fixtures.case_version(case_id, officer, api)

    validate_error(
        api.create_sanction(
            factories.sanction_payload(
                case_id, version - 1, 3, "2026-08-21T00:00:00Z"
            ),
            officer,
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION,
        412,
    )

    _, meta = assertions.validate_list(api.list_sanctions(officer, {"case_id": case_id}))
    assert meta["total_count"] == 0
    assert fixtures.case_version(case_id, officer, api) == version


def test_formal_version_that_just_worked_is_now_stale(api, officer):
    """PRD §3.8: "The case's `version` advances, which is what makes a second
    proposal written against the same snapshot fail", and any sanction already
    in `PROPOSED` "moves to `SUPERSEDED` with `vacated_reason`
    `SUPERSEDED_BY_NEWER_PROPOSAL`".

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_expected_case_version_with_412_and_write_nothing
    """
    world = fixtures.seed_decided_case(client=api)
    case_id = world["case"]["id"]
    version = fixtures.case_version(case_id, officer, api)

    first = validate_success(
        api.create_sanction(
            factories.sanction_payload(case_id, version, 3, "2026-08-21T00:00:00Z"),
            officer,
        ),
        201,
    )
    assert first["status"] == "PROPOSED"
    assert first["origin"] == "OFFICE_PROPOSAL"

    version_after_first = fixtures.case_version(case_id, officer, api)
    assert version_after_first == version + 1

    validate_error(
        api.create_sanction(
            factories.sanction_payload(
                case_id,
                version,
                2,
                "2026-08-21T00:00:00Z",
                grade_component_code="ESSAY",
            ),
            officer,
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION,
        412,
    )

    second = validate_success(
        api.create_sanction(
            factories.sanction_payload(
                case_id,
                version_after_first,
                2,
                "2026-08-21T00:00:00Z",
                grade_component_code="ESSAY",
            ),
            officer,
        ),
        201,
    )
    assert second["ladder_rank"] == 2
    assert second["status"] == "PROPOSED"
    assert second["replaces_sanction_id"] == first["id"]

    superseded = validate_success(api.get_sanction(first["id"], officer))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["vacated_reason"] == "SUPERSEDED_BY_NEWER_PROPOSAL"

    rows, meta = assertions.validate_list(
        api.list_sanctions(officer, {"case_id": case_id})
    )
    assert meta["total_count"] == 2
    assert len([row for row in rows if row["status"] == "PROPOSED"]) == 1
    assert fixtures.case_version(case_id, officer, api) == version + 2


def test_informal_proposal_with_a_never_current_version_is_rejected(api, officer):
    """PRD §2.8: `POST /integrity/cases/{id}/informal-resolution` "requires the
    same non-optional `expected_case_version` field" and a mismatch is rejected
    "with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is created"; PRD §3.6
    then moves an accepted proposal's case to `INFORMAL_PROPOSED` with `origin`
    `INFORMAL_PROPOSAL` and advances `version`.

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_a_stale_expected_case_version_with_412_and_write_nothing
    """
    world = fixtures.seed_actors(client=api)
    _, case = _seed_informal_case_for_other_student(world, api)
    case_id = case["id"]
    version = case["version"]

    validate_error(
        api.create_informal_resolution(
            case_id,
            factories.informal_resolution_payload(
                version - 1, 3, "2026-08-21T00:00:00Z"
            ),
            world["reporter_h"],
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION,
        412,
    )

    unchanged = validate_success(api.get_case(case_id, officer))
    assert unchanged["adjudication_status"] == "NOTIFIED"
    assert unchanged["version"] == version
    _, meta = assertions.validate_list(api.list_sanctions(officer, {"case_id": case_id}))
    assert meta["total_count"] == 0

    proposal = validate_success(
        api.create_informal_resolution(
            case_id,
            factories.informal_resolution_payload(version, 3, "2026-08-21T00:00:00Z"),
            world["reporter_h"],
        ),
        201,
    )
    assert proposal["origin"] == "INFORMAL_PROPOSAL"
    assert proposal["ladder_rank"] == 3
    assert proposal["status"] == "PROPOSED"

    after = validate_success(api.get_case(case_id, officer))
    assert after["adjudication_status"] == "INFORMAL_PROPOSED"
    assert after["version"] == version + 1


# ---------------------------------------------------------------------------
# Corner/consistency_model/every_write_is_immediately_visible_to_the_next_read_with_no_settling_period
# ---------------------------------------------------------------------------


def test_imposing_a_sanction_is_immediately_visible_across_every_touched_entity(
    api, officer
):
    """PRD §3.8: "Once every guard passes, five hops run in order, and all of
    them must complete before the response is returned" — hop two makes
    `notation_status` `PENDING_POSTING` "when the sanction's `ladder_rank` is 4
    or greater" and hop three re-derives the student's `standing`.

    Design: Corner/consistency_model/every_write_is_immediately_visible_to_the_next_read_with_no_settling_period
    """
    world = fixtures.seed_decided_case(client=api, panel_recommendation=5)
    fixtures.propose_sanction(
        world, ladder_rank=5, effective_from="2026-08-21T00:00:00Z", client=api
    )
    case_id = world["case"]["id"]
    sanction_id = world["sanction"]["id"]
    student_id = world["student"]["id"]
    dept_id = world["dept"]["id"]

    department_before = validate_success(api.get_department(dept_id, officer))
    assert department_before["open_case_count"] == 1
    student_before = validate_success(api.get_student(student_id, officer))
    assert student_before["active_sanction_points"] == 0

    imposed = validate_success(api.impose_sanction(sanction_id, officer))
    assert imposed["status"] == "IMPOSED"
    assertions.assert_instant_equals(
        imposed["imposed_at"], "2026-08-20T10:00:00Z", "sanction.imposed_at"
    )

    sanction_read = validate_success(api.get_sanction(sanction_id, officer))
    assert sanction_read["status"] == "IMPOSED"
    assert sanction_read["kind"] == "DISCIPLINARY_PROBATION"

    case_read = validate_success(api.get_case(case_id, officer))
    assert case_read["adjudication_status"] == "SANCTION_IMPOSED"
    assert case_read["notation_status"] == "PENDING_POSTING"
    assert case_read["expungement_eligible_at"] is None

    student_read = validate_success(api.get_student(student_id, officer))
    assert student_read["active_sanction_points"] == 5
    assert student_read["standing"] == "PROBATION"

    department_read = validate_success(api.get_department(dept_id, officer))
    assert department_read["open_case_count"] == 1


def test_posting_and_completing_are_immediately_visible_with_the_eligibility_instant(
    api, officer, registrar
):
    """PRD §3.10: "`notation_status` becomes `POSTED`, the student's
    `transcript_notation` becomes `POSTED`, `expungement_eligible_at` is
    computed — or left null when the governing sanction is not yet
    `COMPLETED`"; PRD §3.8 completion decrements `active_sanction_points` and
    the department's `open_case_count` and closes the case.

    Design: Corner/consistency_model/every_write_is_immediately_visible_to_the_next_read_with_no_settling_period
    """
    world = fixtures.seed_decided_case(client=api, panel_recommendation=5)
    fixtures.propose_sanction(
        world, ladder_rank=5, effective_from="2026-08-21T00:00:00Z", client=api
    )
    case_id = world["case"]["id"]
    sanction_id = world["sanction"]["id"]
    student_id = world["student"]["id"]
    dept_id = world["dept"]["id"]
    fixtures.impose_sanction(world, client=api)

    posted = validate_success(api.post_notation(case_id, registrar))
    assert posted["notation_status"] == "POSTED"
    assert posted["expungement_eligible_at"] is None

    case_after_post = validate_success(api.get_case(case_id, officer))
    assert case_after_post["notation_status"] == "POSTED"
    assert case_after_post["expungement_eligible_at"] is None
    student_after_post = validate_success(api.get_student(student_id, officer))
    assert student_after_post["transcript_notation"] == "POSTED"

    completed = validate_success(api.complete_sanction(sanction_id, officer))
    assert completed["status"] == "COMPLETED"
    assertions.assert_instant_equals(
        completed["completed_at"], "2026-08-20T10:00:00Z", "sanction.completed_at"
    )

    case_after_complete = validate_success(api.get_case(case_id, officer))
    assert case_after_complete["adjudication_status"] == "CLOSED"
    assert case_after_complete["notation_status"] == "POSTED"
    assertions.assert_instant_equals(
        case_after_complete["expungement_eligible_at"],
        "2027-08-20T10:00:00Z",
        "case.expungement_eligible_at",
    )

    student_after_complete = validate_success(api.get_student(student_id, officer))
    assert student_after_complete["active_sanction_points"] == 0
    assert student_after_complete["standing"] == "GOOD_STANDING"
    assert student_after_complete["transcript_notation"] == "POSTED"

    department_after_complete = validate_success(api.get_department(dept_id, officer))
    assert department_after_complete["open_case_count"] == 0


def test_a_create_is_immediately_visible_to_the_next_single_and_list_read(api, officer):
    """PRD §3.3: a new report carries "`evidence_strength_score` 0.00", and
    "Attaching an item recomputes the report's `evidence_strength_score` and
    `evidence_complete` immediately."

    Design: Corner/consistency_model/every_write_is_immediately_visible_to_the_next_read_with_no_settling_period
    """
    world = fixtures.seed_actors(client=api)
    report = fixtures.create_report(
        world["offering"]["id"], world["student"]["id"], world["reporter_h"], api
    )

    single = validate_success(api.get_report(report["id"], officer))
    assert single["id"] == report["id"]
    assert single["status"] == "DRAFT"
    assertions.assert_pct_equals(
        single["evidence_strength_score"], 0.00, "evidence_strength_score"
    )

    rows, meta = assertions.validate_list(
        api.list_reports(officer, {"student_id": world["student"]["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [report["id"]]

    fixtures.attach_similarity_evidence(report["id"], world["reporter_h"], api)

    rescored = validate_success(api.get_report(report["id"], officer))
    assertions.assert_pct_equals(
        rescored["evidence_strength_score"],
        constants.SEED_A_EVIDENCE_SCORE,
        "evidence_strength_score",
    )
    evidence_rows, evidence_meta = assertions.validate_list(
        api.list_evidence_items(officer, {"report_id": report["id"]})
    )
    assert evidence_meta["total_count"] == 1
    assert len(evidence_rows) == 1
