"""Who may act, who may only look, and when the answer becomes visible.

The refusals of this module are the ones that never look at the substance of a
request: the acting role, the acting user's identity, the row's owner.  The last
two tests widen from a single call to a sequence, and ask whether a token the
caller never touched has been retired underneath it and whether every aggregate
a write moved is already visible to the next reader.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ATTENDANCE_ALREADY_RECORDED,
    ERR_DOR_AUTHOR_NOT_ASSIGNED_FTO,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_INSTRUCTOR_NOT_AUTHORIZED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_RECRUIT_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SAME_ACTOR_ADJUDICATION,
    ERR_STALE_LESSON_PLAN_VERSION,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_hours_equals,
    assert_is_instant,
    assert_ladder_precedence,
    assert_version_is,
)
from test_helpers.test_users import (
    DIRECTOR_USER_ID,
    INVESTIGATOR_ALT_USER_ID,
    INVESTIGATOR_USER_ID,
    coordinator_alt_headers,
    coordinator_headers,
    custodian_headers,
    director_headers,
    examiner_alt_headers,
    examiner_headers,
    headers_empty_role,
    investigator_alt_headers,
    investigator_headers,
    make_academy_instructor_headers,
    make_fto_headers,
    make_recruit_headers,
)

PATROL = "PATROL"
ETHICS = "ETHICS"
MISSING_ID = "00000000-0000-4000-8000-000000000000"
CERT_EXPIRES_AT = "2028-08-01T00:00:00Z"

SESSION_DAY_STARTS = "2026-08-10T09:00:00Z"
SESSION_DAY_ENDS = "2026-08-10T11:00:00Z"
SESSION_DAY_AFTER = "2026-08-10T12:00:00Z"


def _error_envelope(response, expected_status, expected_error_id):
    """Assert the declared error envelope of the contract and return the error."""
    error = validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"an error response's meta carries only the two request keys: "
        f"{sorted(body['meta'])}")
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {body['meta']['api_request_id']!r}")
    assert_is_instant(body["meta"]["api_request_timestamp"],
                      "api_request_timestamp")
    assert body["response_type"] == "error", (
        f"response_type must read error, got {body['response_type']!r}")
    assert set(body["data"]) == {"error_id", "message"}, (
        f"an error body carries exactly error_id and message: "
        f"{sorted(body['data'])}")
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"message must be a non-empty human-readable string: "
        f"{error['message']!r}")
    return error


def _patrol_academy(world, min_total_hours=2.0, required_hours=2.0,
                    exam_required=False, fto_certified=False,
                    **standard_kwargs):
    """A one-topic standard, its cohort, a credentialled instructor and a plan."""
    standard = world.create_standard(
        min_total_hours=min_total_hours,
        topic_requirements=[f.topic_requirement(PATROL, required_hours,
                                               exam_required)],
        **standard_kwargs)
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(
        topics=[PATROL], expires_at=CERT_EXPIRES_AT,
        fto_certified=fto_certified)
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL, 2.0)
    return {
        "standard": standard,
        "cohort": cohort,
        "instructor": instructor,
        "lesson_plan": plan,
        "topic_code": PATROL,
        "session_starts_at": SESSION_DAY_STARTS,
        "session_ends_at": SESSION_DAY_ENDS,
        "after_session": SESSION_DAY_AFTER,
    }


def _block(world, built, starts=SESSION_DAY_STARTS, ends=SESSION_DAY_ENDS,
           min_enrollment=1):
    """One scheduled two-hour block of the cohort's single topic in room R1."""
    return world.schedule_session(
        built["cohort"]["id"], built["lesson_plan"]["id"],
        built["instructor"]["id"], room_code="R1", starts_at=starts,
        ends_at=ends, min_enrollment=min_enrollment)


def test_every_status_family_of_the_catalogue_is_reachable_with_one_envelope(world):
    """Seven refusals spanning 400, 401, 403, 404, 409, 412 and 422 share one shape.

    PRD: "All error API responses (4xx status codes) follow this standard
    envelope format", in which "The `meta` object for error responses contains
    only `api_request_id` and `api_request_timestamp`", `response_type` is
    `error`, and `data` carries an `error_id` and "a human-readable explanation
    of what went wrong".

    Design: Corner/errors/triggerable_every_http_status_family_of_the_catalog_is_reachable_with_the_declared_envelope
    """
    built = _patrol_academy(world, fitness_event_floor_points=10,
                            fitness_pass_score=60)
    instructor = built["instructor"]
    plan = built["lesson_plan"]
    assert_version_is(plan, 2, "the approved lesson plan")
    pre_approval_version = plan["version"] - 1

    ethics_plan = validate_success(world.client.create_lesson_plan(
        f.lesson_plan_payload(instructor["id"], ETHICS, "Ethics and Conduct",
                              2.0),
        make_academy_instructor_headers(instructor["id"])), 201)
    recruit = world.create_recruit(built["cohort"]["id"],
                                   applicant_number="A-001",
                                   full_name="Rae Ortiz",
                                   date_of_birth="1999-04-12")

    # 400 -- a required body field is absent, which is rung 20.
    nameless = f.recruit_payload(built["cohort"]["id"],
                                 applicant_number="A-002")
    del nameless["full_name"]
    _error_envelope(world.client.create_recruit(nameless, coordinator_headers()),
                    400, ERR_INVALID_REQUEST)

    # 401 -- both identity headers present but blank.
    _error_envelope(world.client.list_recruits(headers_empty_role("")),
                    401, ERR_UNAUTHENTICATED)

    # 403 -- a recruit is not among the roster listing's declared roles.
    _error_envelope(world.client.list_recruits(make_recruit_headers(recruit["id"])),
                    403, ERR_ROLE_NOT_PERMITTED)

    # 404 -- the path identifier resolves to nothing.
    _error_envelope(world.client.get_recruit(MISSING_ID, coordinator_headers()),
                    404, ERR_RECRUIT_NOT_FOUND)

    # 409 -- applicant_number is unique across all recruits.
    _error_envelope(world.client.create_recruit(
        f.recruit_payload(built["cohort"]["id"], applicant_number="A-001",
                          full_name="Rae Ortiz", date_of_birth="1999-04-12"),
        coordinator_headers()), 409, ERR_DUPLICATE_IDENTIFIER)

    # 412 -- the approval has already moved the plan past the snapshot the
    # author is writing against.
    _error_envelope(world.client.create_lesson_plan_revision(
        plan["id"],
        f.lesson_plan_revision_payload(pre_approval_version, 3.0,
                                       "written against the pre-approval snapshot"),
        make_academy_instructor_headers(instructor["id"])),
        412, ERR_STALE_LESSON_PLAN_VERSION)

    # 422 -- the author of the ETHICS plan is authorized for PATROL only, and
    # rung 50 answers ahead of the rung-56 segregation check, which the
    # approving director does not violate.
    _error_envelope(world.client.approve_lesson_plan(ethics_plan["id"],
                                                     director_headers()),
                    422, ERR_INSTRUCTOR_NOT_AUTHORIZED)

    _rows, meta = validate_paginated(world.client.list_recruits(
        coordinator_headers()))
    assert meta["total_count"] == 1, (
        "not one of the seven refusals created, mutated or deleted a row")


def test_the_command_verbs_answer_only_to_the_academy_director(world):
    """Six director-exclusive verbs are all accepted for the director who holds them.

    PRD: "An **`AcademyDirector`** is the commanding officer of the academy:
    sole authority for certification standards, cohort creation, instructor
    certification and revocation, lesson plan approval and revision requests,
    adverse actions (dismissal, probation decisions, delivery voids) and
    graduation certification."

    Design: Corner/rbac/exclusive_operations_the_academy_director_alone_holds_the_command_verbs
    """
    world.set_clock("2026-08-01T00:00:00Z")
    statuses = []

    standard_response = world.client.create_certification_standard(
        f.certification_standard_payload(
            state_code="TX", min_total_hours=2.0,
            topic_requirements=[f.topic_requirement(PATROL, 2.0, False)],
            fitness_event_floor_points=10, fitness_pass_score=60),
        director_headers())
    statuses.append(standard_response.status_code)
    standard = validate_success(standard_response, 201)

    cohort_response = world.client.create_academy_class(
        f.academy_class_payload(standard["id"], start_date="2026-08-03",
                                planned_seats=30),
        director_headers())
    statuses.append(cohort_response.status_code)
    cohort = validate_success(cohort_response, 201)
    assert cohort["status"] == "FORMING"

    instructor_response = world.client.create_instructor(
        f.instructor_payload(full_name="Ivy Nash"), director_headers())
    statuses.append(instructor_response.status_code)
    instructor = validate_success(instructor_response, 201)
    assert instructor["certification_status"] == "UNCERTIFIED"
    assert instructor["certification_expires_at"] is None
    assert instructor["authorized_topic_codes"] == []
    assert instructor["fto_certified"] is False

    certify_response = world.client.certify_instructor(
        instructor["id"],
        f.certify_instructor_payload(CERT_EXPIRES_AT, [PATROL], True),
        director_headers())
    statuses.append(certify_response.status_code)
    certified = validate_success(certify_response)
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["fto_certified"] is True
    assert certified["authorized_topic_codes"] == [PATROL]

    plan = validate_success(world.client.create_lesson_plan(
        f.lesson_plan_payload(instructor["id"], PATROL, "Patrol Operations",
                              2.0),
        make_academy_instructor_headers(instructor["id"])), 201)

    sent_back_response = world.client.request_lesson_plan_revision(
        plan["id"], f.request_revision_payload("tighten the scenario section"),
        director_headers())
    statuses.append(sent_back_response.status_code)
    sent_back = validate_success(sent_back_response)
    assert sent_back["status"] == "REVISION_REQUESTED"

    revised = validate_success(world.client.create_lesson_plan_revision(
        plan["id"],
        f.lesson_plan_revision_payload(sent_back["version"], 2.0,
                                       "scenario section tightened"),
        make_academy_instructor_headers(instructor["id"])))
    assert revised["revision_number"] == 2

    approve_response = world.client.approve_lesson_plan(plan["id"],
                                                        director_headers())
    statuses.append(approve_response.status_code)
    approved = validate_success(approve_response)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == DIRECTOR_USER_ID
    assert approved["approved_revision_number"] == 2

    assert statuses == [201, 201, 201, 200, 200, 200], (
        f"the six command verbs are all accepted for the director: {statuses}")
    assert 403 not in statuses, (
        "the director's user id is unrelated to every row it touches and none "
        "of these endpoints is scoped by the ownership gate")


def test_no_role_inherits_the_verbs_the_contract_gave_to_another(world):
    """Six calls by a role the endpoint never names are refused at the role gate.

    PRD: "The acting role is authorized for the target operation, including the
    subject-scoped screening authority of §2.1 - otherwise
    `ERR_ROLE_NOT_PERMITTED`, 403. Applies to every endpoint."

    Design: Corner/rbac/unauthorized_other_role_no_role_inherits_another_roles_exclusive_verbs
    """
    built = _patrol_academy(world, fitness_event_floor_points=10,
                            fitness_pass_score=60)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _block(world, built)

    # The pipeline verbs belong to the coordinator; the director does not
    # inherit them by outranking her.
    validate_error(world.client.advance_stage(
        recruit["id"], f.advance_stage_payload("FIELD_TRAINING"),
        director_headers()), ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(world.client.order_screening(
        recruit["id"], f.screening_payload("MEDICAL"), director_headers()),
        ERR_ROLE_NOT_PERMITTED, 403)

    # The adverse actions belong to the director, in the other direction.
    validate_error(world.client.dismiss_recruit(
        recruit["id"], f.dismiss_payload("INTEGRITY",
                                        "coordinator overstepping"),
        coordinator_headers()), ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(world.client.void_course_session_delivery(
        session["id"], f.void_delivery_payload("not my call"),
        coordinator_headers()), ERR_ROLE_NOT_PERMITTED, 403)

    # Read-everything does not imply write-anything.
    validate_error(world.client.create_certification_standard(
        f.certification_standard_payload(
            state_code="TX", min_total_hours=2.0,
            topic_requirements=[f.topic_requirement(PATROL, 2.0, False)]),
        custodian_headers()), ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(world.client.record_attendance(
        session["id"], f.attendance_payload(recruit["id"], "PRESENT", 2.0),
        custodian_headers()), ERR_ROLE_NOT_PERMITTED, 403)

    # The custodian's read surface is intact.
    seen = validate_success(world.client.get_recruit(recruit["id"],
                                                    custodian_headers()))
    assert seen["pipeline_stage"] == "ACADEMY"
    assert seen["clearance_status"] == "CLEARED"
    assert seen["academy_status"] == "IN_PROGRESS"

    untouched = validate_success(world.client.get_course_session(
        session["id"], coordinator_headers()))
    assert untouched["status"] == "SCHEDULED"
    assert untouched["enrolled_count"] == 0


def test_two_holders_of_one_shared_verb_produce_the_same_accounting(world):
    """A coordinator and an instructor roster and close out a block identically.

    PRD: the roster and close-out verbs are declared for `AcademyInstructor` and
    `TrainingCoordinator` alike - "Record one recruit's attendance for a session;
    the row is PROVISIONAL until the session is delivered" and "Close out a
    taught session: credit curriculum hours to every attendee and to the cohort
    ledger".

    Design: Corner/rbac/shared_operations_every_declared_holder_of_a_shared_verb_gets_the_same_result
    """
    built = _patrol_academy(world, fitness_event_floor_points=10,
                            fitness_pass_score=60)
    instructor_headers = make_academy_instructor_headers(
        built["instructor"]["id"])
    first = world.recruit_in_academy(built["cohort"]["id"])
    second = world.recruit_in_academy(built["cohort"]["id"])
    morning = _block(world, built)
    afternoon = _block(world, built, starts="2026-08-10T11:00:00Z",
                       ends="2026-08-10T13:00:00Z")

    by_coordinator = validate_success(world.client.record_attendance(
        morning["id"], f.attendance_payload(first["id"], "PRESENT", 2.0),
        coordinator_headers()), 201)
    by_instructor = validate_success(world.client.record_attendance(
        afternoon["id"], f.attendance_payload(second["id"], "PRESENT", 2.0),
        instructor_headers), 201)

    assert by_coordinator["ledger_status"] == "PROVISIONAL"
    assert by_instructor["ledger_status"] == "PROVISIONAL"
    assert set(by_coordinator) == set(by_instructor), (
        "the two writers produced rows with different field sets")
    for absent in ("actor_role", "actor_user_id", "recorded_by_user_id",
                   "recorded_by_role"):
        assert absent not in by_coordinator, (
            f"an attendance row must not record the acting role: {absent}")

    world.set_clock("2026-08-10T13:00:00Z")
    delivered_by_coordinator = validate_success(
        world.client.deliver_course_session(morning["id"],
                                            coordinator_headers()))
    delivered_by_instructor = validate_success(
        world.client.deliver_course_session(afternoon["id"],
                                           instructor_headers))
    assert delivered_by_coordinator["status"] == "DELIVERED"
    assert delivered_by_instructor["status"] == "DELIVERED"

    for recruit in (first, second):
        credited = world.read_recruit(recruit["id"])
        assert_hours_equals(credited["credited_hours_total"], "2.00",
                            "credited_hours_total")

    # The same row read by five different roles.  The field training officer is
    # left out of the comparison on purpose: an officer's claim on a recruit
    # runs through a rotation, and this scenario has none.
    readers = [
        validate_success(world.client.get_recruit(first["id"],
                                                  director_headers())),
        validate_success(world.client.get_recruit(first["id"],
                                                  coordinator_headers())),
        validate_success(world.client.get_recruit(first["id"],
                                                  custodian_headers())),
        validate_success(world.client.get_recruit(first["id"],
                                                  examiner_headers())),
        validate_success(world.client.get_recruit(
            first["id"], make_recruit_headers(first["id"]))),
    ]
    for seen in readers[1:]:
        assert seen == readers[0], (
            "the recruit entity is not projected per reading role")


def test_each_screening_writer_is_confined_to_its_own_subject(world):
    """Three peer roles share the findings verb and each owns only its own type.

    PRD: "A `BackgroundInvestigator` may act only on a screening record whose
    `screening_type` is `BACKGROUND`; a `MedicalExaminer` only on `MEDICAL` or
    `PSYCHOLOGICAL`; a `TrainingCoordinator` only on `PHYSICAL_FITNESS`. Acting
    outside one's own subject is `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/peer_roles_screening_writers_are_scoped_to_the_types_they_own
    """
    built = _patrol_academy(world, fitness_event_floor_points=10,
                            fitness_pass_score=60)
    recruit = world.create_recruit(built["cohort"]["id"])
    background = world.order_screening(recruit["id"], "BACKGROUND")
    medical = world.order_screening(recruit["id"], "MEDICAL")
    psychological = world.order_screening(recruit["id"], "PSYCHOLOGICAL")
    fitness = world.order_screening(recruit["id"], "PHYSICAL_FITNESS")

    # Each peer reaching across into a neighbour's subject.
    validate_error(world.client.record_findings(
        background["id"], f.findings_payload_for("BACKGROUND"),
        examiner_headers()), ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(world.client.record_findings(
        medical["id"], f.findings_payload_for("MEDICAL"),
        investigator_headers()), ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(world.client.record_findings(
        fitness["id"], f.findings_payload_for("PHYSICAL_FITNESS"),
        examiner_headers()), ERR_ROLE_NOT_PERMITTED, 403)

    # And each acting inside it.  The examiner owns two of the four subjects.
    own_subject = [
        validate_success(world.client.record_findings(
            background["id"], f.findings_payload_for("BACKGROUND"),
            investigator_headers())),
        validate_success(world.client.record_findings(
            medical["id"], f.findings_payload_for("MEDICAL"),
            examiner_headers())),
        validate_success(world.client.record_findings(
            psychological["id"], f.findings_payload_for("PSYCHOLOGICAL"),
            examiner_headers())),
        validate_success(world.client.record_findings(
            fitness["id"], f.findings_payload_for("PHYSICAL_FITNESS"),
            coordinator_headers())),
    ]
    for record in own_subject:
        assert record["status"] == "FINDINGS_RECORDED"
    assert own_subject[0]["findings_recorded_by_user_id"] == INVESTIGATOR_USER_ID

    # The adjudication half of the pipeline is scoped the same way.
    validate_error(world.client.adjudicate_screening(
        psychological["id"], f.adjudicate_payload("CLEAR"),
        investigator_alt_headers()), ERR_ROLE_NOT_PERMITTED, 403)

    adjudicated = validate_success(world.client.adjudicate_screening(
        psychological["id"], f.adjudicate_payload("CLEAR"),
        examiner_alt_headers()))
    assert adjudicated["status"] == "CLEARED"
    assert world.read_recruit(recruit["id"])["clearance_status"] == "PARTIAL"


def test_an_entity_backed_role_reaches_only_its_own_row(world):
    """A second instructor and a second recruit are turned away from row one.

    PRD: "An entity-backed role acting on a resource it does not own is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership gate is armed on
    exactly four operations: submitting a lesson plan revision, filing an
    observation report, reading a single recruit, and reading a recruit's
    certification progress."

    Design: Corner/rbac/peer_roles_entity_backed_roles_reach_only_their_own_row
    """
    built = _patrol_academy(world, fto_certified=True)
    author = built["instructor"]
    plan = built["lesson_plan"]
    stranger = world.create_certified_instructor(
        topics=[PATROL], expires_at=CERT_EXPIRES_AT, fto_certified=True)
    trainee = world.recruit_in_field_training(built)
    peer = world.create_recruit(built["cohort"]["id"], full_name="Kai Serrano")
    rotation = world.plan_rotation(trainee, author["id"], phase_number=1,
                                   start_date="2026-08-20",
                                   end_date="2026-09-02")
    world.activate_rotation(rotation["id"])
    world.set_clock("2026-08-21T18:00:00Z")

    # An instructor who did not author the plan cannot revise it.
    validate_error(world.client.create_lesson_plan_revision(
        plan["id"], f.lesson_plan_revision_payload(plan["version"], 2.0),
        make_academy_instructor_headers(stranger["id"])),
        ERR_NOT_RESOURCE_OWNER, 403)

    # An officer who is certified, but not this rotation's officer, cannot file
    # against it: ownership is decided before the author-matching rule.
    stranger_report = validate_error(world.client.create_observation_report(
        rotation["id"], f.observation_report_payload(stranger["id"],
                                                    "2026-08-21"),
        make_fto_headers(stranger["id"])), ERR_NOT_RESOURCE_OWNER, 403)
    assert_ladder_precedence(stranger_report["error_id"],
                             ERR_NOT_RESOURCE_OWNER,
                             ERR_DOR_AUTHOR_NOT_ASSIGNED_FTO)

    # A recruit is one row, and the two recruit-scoped reads are both gated.
    peer_headers = make_recruit_headers(peer["id"])
    validate_error(world.client.get_recruit(trainee["id"], peer_headers),
                   ERR_NOT_RESOURCE_OWNER, 403)
    validate_error(
        world.client.get_certification_progress(trainee["id"], peer_headers),
        ERR_NOT_RESOURCE_OWNER, 403)

    # The collection is not on the recruit's read surface at all, so the role
    # check answers before ownership is ever consulted.
    own_headers = make_recruit_headers(trainee["id"])
    listed = validate_error(world.client.list_recruits(own_headers),
                            ERR_ROLE_NOT_PERMITTED, 403)
    assert_ladder_precedence(listed["error_id"], ERR_ROLE_NOT_PERMITTED,
                             ERR_NOT_RESOURCE_OWNER)

    # Every one of those four calls succeeds for the row's own holder.
    mine = validate_success(world.client.get_recruit(trainee["id"], own_headers))
    assert mine["id"] == trainee["id"]
    progress = validate_success(
        world.client.get_certification_progress(trainee["id"], own_headers))
    assert progress["recruit_id"] == trainee["id"]

    revised = validate_success(world.client.create_lesson_plan_revision(
        plan["id"], f.lesson_plan_revision_payload(plan["version"], 2.0),
        make_academy_instructor_headers(author["id"])))
    assert revised["revision_number"] == 2
    assert revised["status"] == "SUBMITTED"
    assert_version_is(revised, plan["version"] + 1, "lesson plan")

    filed = world.file_report(rotation["id"], author["id"], "2026-08-21")
    assert filed["author_instructor_id"] == author["id"]
    assert world.read_rotation(rotation["id"])["dor_count"] == 1


def test_no_user_both_authors_and_signs_off(world):
    """The author's own approval and the finder's own adjudication both fail 422.

    PRD: "the adjudicating `X-User-ID` must differ from the record's
    `findings_recorded_by_user_id`, or the request is refused with
    `ERR_SAME_ACTOR_ADJUDICATION`" and "the approving `X-User-ID` differ from the
    authoring instructor's identifier, otherwise `ERR_SAME_ACTOR_ADJUDICATION`".

    Design: Corner/rbac/segregation_of_duties_one_user_may_not_both_author_and_sign_off
    """
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(
        topics=[PATROL], expires_at=CERT_EXPIRES_AT)
    plan = world.create_lesson_plan(instructor["id"], topic_code=PATROL,
                                    contact_hours=2.0)
    recruit = world.create_recruit(cohort["id"])
    screening = world.screening_at_findings_recorded(recruit["id"], "BACKGROUND")
    assert screening["findings_recorded_by_user_id"] == INVESTIGATOR_USER_ID

    # A director whose acting identity is the authoring instructor's own.
    _error_envelope(
        world.client.approve_lesson_plan(plan["id"],
                                         director_headers(instructor["id"])),
        422, ERR_SAME_ACTOR_ADJUDICATION)
    # The investigator who wrote the findings, deciding on them.
    _error_envelope(
        world.client.adjudicate_screening(screening["id"],
                                          f.adjudicate_payload("CLEAR"),
                                          investigator_headers()),
        422, ERR_SAME_ACTOR_ADJUDICATION)

    # Neither refusal moved anything.
    held = validate_success(world.client.get_lesson_plan(plan["id"],
                                                        coordinator_headers()))
    assert held["status"] == "SUBMITTED"
    assert held["approved_by_user_id"] is None
    assert held["approved_revision_number"] is None
    assert_version_is(held, 1, "lesson plan")
    waiting = validate_success(world.client.get_screening_record(
        screening["id"], coordinator_headers()))
    assert waiting["status"] == "FINDINGS_RECORDED"
    assert waiting["adjudicated_by_user_id"] is None

    # A second user of each role carries both acts through.
    cleared = validate_success(world.client.adjudicate_screening(
        screening["id"], f.adjudicate_payload("CLEAR"),
        investigator_alt_headers()))
    assert cleared["status"] == "CLEARED"
    approved = validate_success(world.client.approve_lesson_plan(
        plan["id"], director_headers()))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == DIRECTOR_USER_ID
    assert approved["approved_revision_number"] == 1

    final = validate_success(world.client.get_screening_record(
        screening["id"], custodian_headers()))
    assert final["findings_recorded_by_user_id"] == INVESTIGATOR_USER_ID
    assert final["adjudicated_by_user_id"] == INVESTIGATOR_ALT_USER_ID


def test_an_unguarded_write_retires_a_token_its_holder_never_touched(world):
    """Approval and a revision request both invalidate a plan token silently.

    PRD: "Approval, a revision request and the instructor-revocation cascade all
    advance a plan's `version`, so a revision written against a superseded
    snapshot is refused."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_the_plan_token_is_invalidated_by_writes_that_are_not_themselves_guarded
    """
    instructor = world.create_certified_instructor(
        topics=[PATROL], expires_at=CERT_EXPIRES_AT)
    plan = world.create_lesson_plan(instructor["id"], topic_code=PATROL,
                                    contact_hours=2.0)
    assert_version_is(plan, 1, "lesson plan")
    assert plan["revision_number"] == 1
    assert plan["status"] == "SUBMITTED"
    accepted = [plan["version"]]

    sent_back = validate_success(world.client.request_lesson_plan_revision(
        plan["id"], f.request_revision_payload(), director_headers()))
    assert sent_back["status"] == "REVISION_REQUESTED"
    accepted.append(sent_back["version"])

    # Two clients now hold the same token; neither performed a write to get it.
    token_a = validate_success(world.client.get_lesson_plan(
        plan["id"], coordinator_headers()))["version"]
    token_b = validate_success(world.client.get_lesson_plan(
        plan["id"], custodian_headers()))["version"]
    assert token_a == token_b == 2

    first = validate_success(world.client.create_lesson_plan_revision(
        plan["id"], f.lesson_plan_revision_payload(token_a, 2.5),
        coordinator_headers()))
    assert first["revision_number"] == 2
    assert first["status"] == "SUBMITTED"
    assert_hours_equals(first["contact_hours"], "2.50", "contact_hours")
    accepted.append(first["version"])

    # B's token was retired by a competing revision.  A revision is illegal from
    # SUBMITTED as well, and the concurrency guard answers first.
    lost_race = _error_envelope(world.client.create_lesson_plan_revision(
        plan["id"], f.lesson_plan_revision_payload(token_b, 4.0),
        coordinator_alt_headers()), 412, ERR_STALE_LESSON_PLAN_VERSION)
    assert_ladder_precedence(lost_race["error_id"],
                             ERR_STALE_LESSON_PLAN_VERSION, ERR_INVALID_STATE)

    token_b = validate_success(world.client.get_lesson_plan(
        plan["id"], custodian_headers()))["version"]
    assert token_b == 3

    # Now a write B never made, and which carries no token of its own, retires
    # the snapshot B just read.
    returned = validate_success(world.client.request_lesson_plan_revision(
        plan["id"], f.request_revision_payload("One more pass"),
        director_headers()))
    assert returned["status"] == "REVISION_REQUESTED"
    accepted.append(returned["version"])
    _error_envelope(world.client.create_lesson_plan_revision(
        plan["id"], f.lesson_plan_revision_payload(token_b, 4.0),
        coordinator_alt_headers()), 412, ERR_STALE_LESSON_PLAN_VERSION)

    token_b = validate_success(world.client.get_lesson_plan(
        plan["id"], custodian_headers()))["version"]
    assert token_b == 4
    second = validate_success(world.client.create_lesson_plan_revision(
        plan["id"], f.lesson_plan_revision_payload(token_b, 4.0),
        coordinator_alt_headers()))
    assert second["revision_number"] == 3
    assert second["status"] == "SUBMITTED"
    accepted.append(second["version"])

    # Approval is the other unguarded write, and it retires A's token too.
    approved = validate_success(world.client.approve_lesson_plan(
        plan["id"], director_headers()))
    assert approved["status"] == "APPROVED"
    assert approved["approved_revision_number"] == 3
    accepted.append(approved["version"])
    # Revising an APPROVED plan is legal on its own terms, so the only thing
    # standing in the way of this call is the token the approval retired.
    _error_envelope(world.client.create_lesson_plan_revision(
        plan["id"], f.lesson_plan_revision_payload(second["version"], 5.0),
        coordinator_headers()), 412, ERR_STALE_LESSON_PLAN_VERSION)

    assert accepted == list(range(1, len(accepted) + 1)), (
        f"an accepted write moved version by more than one: {accepted}")
    settled = validate_success(world.client.get_lesson_plan(plan["id"],
                                                           custodian_headers()))
    assert_version_is(settled, 6, "lesson plan")
    assert settled["revision_number"] == 3
    assert settled["status"] == "APPROVED"
    assert_hours_equals(settled["contact_hours"], "4.00", "contact_hours")


def test_the_next_reader_already_sees_everything_the_write_moved(world):
    """A delivery, a refusal and a void are each complete when their response returns.

    PRD: "a cascade is **immediate and complete within the triggering request** -
    there is no deferred reconciliation and no eventual consistency", and the
    delivery itself re-derives the cohort ledger, each attendee's aggregates and
    the session's own total inside the one request.

    Design: Corner/consistency_model/immediate_every_write_is_readable_and_every_aggregate_re_derived_before_the_response_returns
    """
    built = _patrol_academy(world, fitness_event_floor_points=10,
                            fitness_pass_score=60)
    cohort_id = built["cohort"]["id"]
    reader = make_academy_instructor_headers(built["instructor"]["id"])
    recruit = world.recruit_in_academy(cohort_id)
    session = _block(world, built)
    row = world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
    assert row["ledger_status"] == "PROVISIONAL"

    forming = validate_success(world.client.get_academy_class(cohort_id,
                                                            custodian_headers()))
    assert forming["status"] == "FORMING"
    assert_hours_equals(forming["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")

    # A refused write is visible nowhere.  The recruit is still IN_PROGRESS and
    # the session still SCHEDULED, so the duplicate-row rule is the only one the
    # request breaks.
    _error_envelope(world.client.record_attendance(
        session["id"], f.attendance_payload(recruit["id"], "PRESENT", 2.0),
        coordinator_headers()), 409, ERR_ATTENDANCE_ALREADY_RECORDED)
    _rows, before = validate_paginated(world.client.list_attendance_records(
        reader, {"course_session_id": session["id"]}))
    assert before["total_count"] == 1

    world.set_clock(SESSION_DAY_AFTER)
    delivered = validate_success(
        world.client.deliver_course_session(session["id"],
                                            coordinator_headers()))
    assert delivered["status"] == "DELIVERED"

    # The very next request, by a different role against a different entity.
    in_session = validate_success(world.client.get_academy_class(
        cohort_id, custodian_headers()))
    assert in_session["status"] == "IN_SESSION"
    assert_hours_equals(in_session["credited_topic_hours_total"], "2.00",
                        "credited_topic_hours_total")
    assert_hours_equals(in_session["unmet_topic_hours"][PATROL], "0.00",
                        f"unmet_topic_hours[{PATROL}]")

    credited = validate_success(world.client.get_recruit(recruit["id"],
                                                        custodian_headers()))
    assert_hours_equals(credited["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert_hours_equals(credited["per_topic_credited_hours"][PATROL], "2.00",
                        f"per_topic_credited_hours[{PATROL}]")
    assert credited["academy_status"] == "COMPLETE"

    progress = validate_success(world.client.get_certification_progress(
        recruit["id"], custodian_headers()))
    assert_hours_equals(progress["total_hours"], "2.00", "total_hours")
    assert_hours_equals(progress["unmet_topic_hours"][PATROL], "0.00",
                        f"unmet_topic_hours[{PATROL}]")
    assert progress["eligible_for_certification"] is True

    roster, promoted = validate_paginated(world.client.list_attendance_records(
        reader, {"course_session_id": session["id"]}))
    assert promoted["total_count"] == 1
    assert roster[0]["ledger_status"] == "CREDITED"
    assert_hours_equals(roster[0]["credited_hours"], "2.00", "credited_hours")

    # The duplicate attempt again, now that the delivery has closed the session
    # and satisfied the curriculum: the roster rule, the session's status and the
    # recruit's academy standing all answer 409, so only the family is pinned.
    repeated = world.client.record_attendance(
        session["id"], f.attendance_payload(recruit["id"], "PRESENT", 2.0),
        coordinator_headers())
    assert repeated.status_code == 409, (
        f"a second attendance row must be refused, got {repeated.status_code}")
    body = repeated.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}
    _still, unmoved = validate_paginated(world.client.list_attendance_records(
        reader, {"course_session_id": session["id"]}))
    assert unmoved["total_count"] == 1
    held = validate_success(world.client.get_academy_class(cohort_id,
                                                         custodian_headers()))
    assert_hours_equals(held["credited_topic_hours_total"], "2.00",
                        "credited_topic_hours_total")

    # The compensation is applied inside the void request, not swept up later.
    voided = validate_success(world.client.void_course_session_delivery(
        session["id"], f.void_delivery_payload("Instructor recalled to duty"),
        director_headers()))
    assert voided["status"] == "VOIDED"

    at_risk = validate_success(world.client.get_academy_class(
        cohort_id, custodian_headers()))
    assert_hours_equals(at_risk["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")
    assert_hours_equals(at_risk["unmet_topic_hours"][PATROL], "2.00",
                        f"unmet_topic_hours[{PATROL}]")
    assert at_risk["status"] == "AT_RISK"

    reverted = validate_success(world.client.get_recruit(recruit["id"],
                                                        custodian_headers()))
    assert_hours_equals(reverted["credited_hours_total"], "0.00",
                        "credited_hours_total")
    assert reverted["academy_status"] == "IN_PROGRESS"

    recomputed = validate_success(world.client.get_certification_progress(
        recruit["id"], custodian_headers()))
    assert_hours_equals(recomputed["total_hours"], "0.00", "total_hours")
    assert recomputed["eligible_for_certification"] is False
