"""What each row looks like when it is first written, and how lists answer.

Creation shapes, declared defaults, server-derived fields, the scoped 404 of
every entity family, and the paging and filter contract of the list endpoints.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ACADEMY_CLASS_NOT_FOUND,
    ERR_ATTENDANCE_RECORD_NOT_FOUND,
    ERR_CERTIFICATION_STANDARD_NOT_FOUND,
    ERR_COURSE_SESSION_NOT_FOUND,
    ERR_EXAMINATION_NOT_FOUND,
    ERR_INSTRUCTOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LESSON_PLAN_NOT_FOUND,
    ERR_OBSERVATION_REPORT_NOT_FOUND,
    ERR_RECRUIT_NOT_FOUND,
    ERR_ROTATION_NOT_FOUND,
    ERR_SCREENING_RECORD_NOT_FOUND,
    ERR_TRAINING_RECORD_ENTRY_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_hours_equals,
    assert_instant_equals,
    assert_score_equals,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    DEFAULT_FITNESS_EVENT_FLOOR_POINTS,
    DEFAULT_FITNESS_PASS_SCORE,
    DEFAULT_MIN_ENROLLMENT,
)
from test_helpers.test_users import (
    coordinator_headers,
    custodian_headers,
    director_headers,
    make_academy_instructor_headers,
    make_fto_headers,
)

PATROL = "PATROL"
ETHICS = "ETHICS"


def _two_topic_standard_payload():
    return f.certification_standard_payload(
        state_code="TX", min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 4.0, True),
                            f.topic_requirement(ETHICS, 2.0, False)],
        fitness_event_floor_points=10, fitness_pass_score=60)


def test_registering_a_standard_returns_its_declared_curriculum_map(world):
    """The commission standard answers 201 carrying the curriculum it declared.

    PRD: "The heart of the standard is its `topic_requirements` array - the
    curriculum map. It carries between 1 and 20 entries, each shaped as a
    `topic_code` (1 to 24 uppercase characters, unique within the array), the
    `required_hours` for that topic (greater than zero) and an `exam_required`
    boolean."

    Design: Corner/entities/creation_certification_standard_returns_201_with_declared_curriculum_map
    """
    payload = f.certification_standard_payload(
        state_code="TX", min_total_hours=40.0, min_passing_score=70.0,
        max_remediation_attempts=1, max_absence_hours=4.0,
        topic_requirements=[f.topic_requirement(PATROL, 24.0, True),
                            f.topic_requirement(ETHICS, 16.0, False)],
        fitness_event_floor_points=12, fitness_pass_score=65)
    standard = validate_success(
        world.client.create_certification_standard(payload, director_headers()),
        201)

    assert standard["code"] == payload["code"]
    assert standard["state_code"] == "TX"
    assert_hours_equals(standard["min_total_hours"], "40.00", "min_total_hours")
    assert_score_equals(standard["min_passing_score"], "70.00",
                        "min_passing_score")
    assert standard["max_remediation_attempts"] == 1
    assert_hours_equals(standard["max_absence_hours"], "4.00",
                        "max_absence_hours")
    assert len(standard["topic_requirements"]) == 2
    first = standard["topic_requirements"][0]
    assert first["topic_code"] == PATROL
    assert_hours_equals(first["required_hours"], "24.00", "required_hours")
    assert first["exam_required"] is True
    assert standard["fitness_event_floor_points"] == 12
    assert standard["fitness_pass_score"] == 65
    assert standard["version"] == 1
    assert_common_fields(standard, "certification standard")


def test_a_new_cohort_opens_forming_with_a_full_topic_keyed_map(world):
    """Both derived maps carry one entry per declared topic from the first read.

    PRD: "A new cohort's `status` begins at `FORMING` and nothing else happens at
    creation."

    Design: Corner/entities/creation_academy_class_starts_forming_with_full_topic_keyed_derived_maps
    """
    standard = validate_success(world.client.create_certification_standard(
        _two_topic_standard_payload(), director_headers()), 201)
    cohort = validate_success(world.client.create_academy_class(
        f.academy_class_payload(standard["id"], planned_seats=30),
        director_headers()), 201)

    assert cohort["status"] == "FORMING"
    assert_hours_equals(cohort["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")
    assert_hours_equals(cohort["unmet_topic_hours"][PATROL], "4.00",
                        f"unmet_topic_hours[{PATROL}]")
    assert_hours_equals(cohort["unmet_topic_hours"][ETHICS], "2.00",
                        f"unmet_topic_hours[{ETHICS}]")
    assert_hours_equals(cohort["projected_topic_hours"][PATROL], "0.00",
                        f"projected_topic_hours[{PATROL}]")
    assert_hours_equals(cohort["projected_topic_hours"][ETHICS], "0.00",
                        f"projected_topic_hours[{ETHICS}]")
    assert cohort["graduated_count"] == 0
    assert cohort["planned_seats"] == 30
    assert cohort["version"] == 1


def test_a_new_recruit_starts_at_the_head_of_all_four_dimensions(world):
    """Stage, clearance, academy standing and probation each open at their start.

    PRD: "`pipeline_stage` tracks position in the selection and training pipeline
    and begins at `APPLICANT` ... `clearance_status` aggregates the recruit's four
    screening records and begins at `PENDING` ... `academy_status` tracks
    academy-phase standing and begins at `NOT_STARTED` ... `probation_status`
    tracks probationary standing and begins at `NOT_APPLICABLE`."

    Design: Corner/entities/creation_recruit_initialises_all_four_state_dimensions
    """
    standard = validate_success(world.client.create_certification_standard(
        _two_topic_standard_payload(), director_headers()), 201)
    cohort = validate_success(world.client.create_academy_class(
        f.academy_class_payload(standard["id"]), director_headers()), 201)
    recruit = validate_success(world.client.create_recruit(
        f.recruit_payload(cohort["id"], full_name="Rae Ortiz"),
        coordinator_headers()), 201)

    assert recruit["pipeline_stage"] == "APPLICANT"
    assert recruit["clearance_status"] == "PENDING"
    assert recruit["academy_status"] == "NOT_STARTED"
    assert recruit["probation_status"] == "NOT_APPLICABLE"
    assert_hours_equals(recruit["credited_hours_total"], "0.00",
                        "credited_hours_total")
    assert_hours_equals(recruit["scheduled_basis_hours_total"], "0.00",
                        "scheduled_basis_hours_total")
    assert_hours_equals(recruit["per_topic_credited_hours"][PATROL], "0.00",
                        f"per_topic_credited_hours[{PATROL}]")
    assert_hours_equals(recruit["per_topic_credited_hours"][ETHICS], "0.00",
                        f"per_topic_credited_hours[{ETHICS}]")
    assert_hours_equals(recruit["unexcused_absence_hours"], "0.00",
                        "unexcused_absence_hours")
    assert_hours_equals(recruit["make_up_hours_owed"], "0.00",
                        "make_up_hours_owed")
    assert recruit["remediation_attempts_used"] == 0
    assert recruit["probation_start"] is None
    assert recruit["probation_extension_days"] == 0
    assert recruit["probation_milestone_due_date"] is None
    assert recruit["probation_milestone_score"] is None
    assert recruit["probation_scheduled_end"] is None
    assert recruit["dismissal_reason_code"] is None
    assert recruit["version"] == 1


def test_reading_an_instructor_returns_the_stored_credential(world):
    """Certification replaces expiry, topics and the FTO mark wholesale.

    PRD: "It moves `certification_status` to `CERTIFIED` and replaces
    `certification_expires_at`, `authorized_topic_codes` and `fto_certified`
    *wholesale* from the request rather than merging them, and it increments the
    instructor's `version` by one."

    Design: Corner/entities/retrieval_instructor_get_returns_the_stored_certification_payload
    """
    instructor = world.create_instructor(full_name="Ivy Nash")
    world.certify_instructor(instructor["id"],
                             certification_expires_at="2027-08-01T00:00:00Z",
                             authorized_topic_codes=[PATROL, ETHICS],
                             fto_certified=True)

    stored = validate_success(world.client.get_instructor(instructor["id"],
                                                        director_headers()))
    assert stored["badge_number"] == instructor["badge_number"]
    assert stored["full_name"] == "Ivy Nash"
    assert stored["certification_status"] == "CERTIFIED"
    assert_instant_equals(stored["certification_expires_at"],
                          "2027-08-01T00:00:00Z", "certification_expires_at")
    assert stored["authorized_topic_codes"] == [PATROL, ETHICS]
    assert stored["fto_certified"] is True
    assert stored["active_trainee_count"] == 0
    assert stored["revocation_reason"] is None
    assert stored["version"] == 2


def test_paging_recruits_reports_the_total_and_whether_more_remain(world):
    """Three rows read over two pages of two, with the count and flag on each.

    PRD: "The response envelope's `meta` object carries `limit`, `offset`,
    `total_count` and `has_more` on every list response."

    Design: Corner/entities/listing_recruits_reports_total_count_and_has_more_across_offset_pages
    """
    standard = world.create_standard()
    cohort = world.create_cohort(standard["id"])
    for name in ("Rae Ortiz", "Sam Vega", "Tao Li"):
        world.create_recruit(cohort["id"], full_name=name)

    first_rows, first_meta = validate_paginated(world.client.list_recruits(
        coordinator_headers(),
        {"academy_class_id": cohort["id"], "limit": 2, "offset": 0}))
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(world.client.list_recruits(
        coordinator_headers(),
        {"academy_class_id": cohort["id"], "limit": 2, "offset": 2}))
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    default_rows, default_meta = validate_paginated(world.client.list_recruits(
        coordinator_headers(), {"academy_class_id": cohort["id"]}))
    assert default_meta["limit"] == 10
    assert len(default_rows) == 3
    assert default_meta["has_more"] is False

    first_ids = {row["id"] for row in first_rows}
    second_ids = {row["id"] for row in second_rows}
    assert not (first_ids & second_ids)


def _one_delivered_and_one_scheduled_session(world):
    """A cohort with one delivered PATROL session and one scheduled ETHICS one."""
    standard = validate_success(world.client.create_certification_standard(
        _two_topic_standard_payload(), director_headers()), 201)
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL, ETHICS])
    patrol_plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                                    contact_hours=2.0)
    ethics_plan = world.create_approved_lesson_plan(instructor["id"], ETHICS,
                                                    contact_hours=2.0)
    recruit = world.recruit_in_academy(cohort["id"])

    delivered = world.schedule_session(
        cohort["id"], patrol_plan["id"], instructor["id"], room_code="R1",
        starts_at="2026-08-10T09:00:00Z", ends_at="2026-08-10T11:00:00Z",
        min_enrollment=1)
    world.record_attendance(delivered["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock("2026-08-10T12:00:00Z")
    world.deliver_session(delivered["id"])

    scheduled = world.schedule_session(
        cohort["id"], ethics_plan["id"], instructor["id"], room_code="R1",
        starts_at="2026-08-12T09:00:00Z", ends_at="2026-08-12T11:00:00Z",
        min_enrollment=1)
    return {"cohort": cohort, "delivered": delivered, "scheduled": scheduled}


def test_sessions_can_be_filtered_by_status_and_by_topic(world):
    """Two additive filters each isolate exactly one of the cohort's sessions.

    PRD: "course sessions by `academy_class_id`, `lesson_plan_id`,
    `instructor_id`, `topic_code` and `status`"

    Design: Corner/entities/listing_course_sessions_filters_by_status_and_topic_code_together
    """
    built = _one_delivered_and_one_scheduled_session(world)

    rows, meta = validate_paginated(world.client.list_course_sessions(
        coordinator_headers(),
        {"academy_class_id": built["cohort"]["id"], "status": "DELIVERED"}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == built["delivered"]["id"]
    assert rows[0]["topic_code"] == PATROL
    assert rows[0]["status"] == "DELIVERED"

    rows, meta = validate_paginated(world.client.list_course_sessions(
        coordinator_headers(),
        {"academy_class_id": built["cohort"]["id"], "topic_code": ETHICS}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == built["scheduled"]["id"]
    assert rows[0]["topic_code"] == ETHICS
    assert rows[0]["status"] == "SCHEDULED"


def test_unknown_curriculum_identifiers_answer_their_own_404(world):
    """Standards, cohorts and lesson plans each carry a scoped not-found code.

    PRD: "Every identifier templated into the path resolves to an existing row,
    validated left to right - otherwise the 404 for the *first* unresolvable
    segment (§2.10)."

    Design: Corner/entities/entity_not_found_curriculum_ids_return_scoped_404_codes
    """
    validate_error(world.client.get_certification_standard(
        NON_EXISTENT_UUID, custodian_headers()),
        ERR_CERTIFICATION_STANDARD_NOT_FOUND, 404)
    validate_error(world.client.get_academy_class(
        NON_EXISTENT_UUID, custodian_headers()),
        ERR_ACADEMY_CLASS_NOT_FOUND, 404)
    validate_error(world.client.get_lesson_plan(
        NON_EXISTENT_UUID, custodian_headers()),
        ERR_LESSON_PLAN_NOT_FOUND, 404)


def test_unknown_people_identifiers_answer_their_own_404(world):
    """Recruits, instructors and screening records name themselves in the 404.

    PRD: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/entity_not_found_people_ids_return_scoped_404_codes
    """
    validate_error(world.client.get_recruit(NON_EXISTENT_UUID,
                                           custodian_headers()),
                   ERR_RECRUIT_NOT_FOUND, 404)
    validate_error(world.client.get_instructor(NON_EXISTENT_UUID,
                                              custodian_headers()),
                   ERR_INSTRUCTOR_NOT_FOUND, 404)
    validate_error(world.client.get_screening_record(NON_EXISTENT_UUID,
                                                    custodian_headers()),
                   ERR_SCREENING_RECORD_NOT_FOUND, 404)


def test_unknown_delivery_identifiers_answer_their_own_404(world):
    """Sessions, attendance rows and examinations each answer their own code.

    PRD: "Every identifier templated into the path resolves to an existing row,
    validated left to right - otherwise the 404 for the *first* unresolvable
    segment (§2.10)."

    Design: Corner/entities/entity_not_found_delivery_ids_return_scoped_404_codes
    """
    validate_error(world.client.get_course_session(NON_EXISTENT_UUID,
                                                  custodian_headers()),
                   ERR_COURSE_SESSION_NOT_FOUND, 404)
    validate_error(world.client.get_attendance_record(NON_EXISTENT_UUID,
                                                      custodian_headers()),
                   ERR_ATTENDANCE_RECORD_NOT_FOUND, 404)
    validate_error(world.client.get_examination(NON_EXISTENT_UUID,
                                                custodian_headers()),
                   ERR_EXAMINATION_NOT_FOUND, 404)


def test_unknown_field_training_identifiers_answer_their_own_404(world):
    """Rotations, reports and record entries complete the scoped 404 catalog.

    PRD: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/entity_not_found_field_training_ids_return_scoped_404_codes
    """
    validate_error(world.client.get_field_training_rotation(
        NON_EXISTENT_UUID, custodian_headers()), ERR_ROTATION_NOT_FOUND, 404)
    validate_error(world.client.get_observation_report(
        NON_EXISTENT_UUID, custodian_headers()),
        ERR_OBSERVATION_REPORT_NOT_FOUND, 404)
    validate_error(world.client.get_training_record_entry(
        NON_EXISTENT_UUID, custodian_headers()),
        ERR_TRAINING_RECORD_ENTRY_NOT_FOUND, 404)


def test_a_missing_required_field_is_a_bad_request_and_writes_nothing(world):
    """Three creates each omit one required field and none of them lands.

    PRD: "Request body shape: required fields present, types correct, enum
    members recognised, numeric ranges honoured, ISO 8601 dates and instants well
    formed, and `dimension_ratings` carrying exactly the five declared keys with
    integer values from 1 through 7 - otherwise `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/required_fields_missing_required_input_returns_invalid_request
    """
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL],
                                                  fto_certified=True)
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    recruit = world.create_recruit(cohort["id"])

    nameless = f.recruit_payload(cohort["id"])
    del nameless["full_name"]
    validate_error(world.client.create_recruit(nameless, coordinator_headers()),
                   ERR_INVALID_REQUEST, 400)

    endless = f.course_session_payload(cohort["id"], plan["id"],
                                       instructor["id"], min_enrollment=1)
    del endless["ends_at"]
    validate_error(world.client.create_course_session(endless,
                                                      coordinator_headers()),
                   ERR_INVALID_REQUEST, 400)

    unguarded = f.rotation_payload(recruit["id"], instructor["id"],
                                   recruit["version"])
    del unguarded["expected_recruit_version"]
    validate_error(world.client.create_field_training_rotation(
        unguarded, coordinator_headers()), ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(world.client.list_recruits(
        coordinator_headers(), {"academy_class_id": cohort["id"]}))
    assert meta["total_count"] == 1


def test_omitted_optional_inputs_take_their_declared_defaults(world):
    """The fitness tuning pair, the credential fields and the seat floor default.

    PRD: "`fitness_event_floor_points`, the per-event points floor, which defaults
    to 10 and must lie between 0 and 25 inclusive, and `fitness_pass_score`, the
    minimum fitness composite that clears the physical fitness screening, which
    defaults to 60 and must lie between 0 and 100 inclusive."

    Design: Corner/entities/defaults_omitted_optional_inputs_take_their_declared_values
    """
    bare = f.certification_standard_payload(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    assert "fitness_event_floor_points" not in bare
    standard = validate_success(world.client.create_certification_standard(
        bare, director_headers()), 201)
    assert standard["fitness_event_floor_points"] == DEFAULT_FITNESS_EVENT_FLOOR_POINTS
    assert standard["fitness_pass_score"] == DEFAULT_FITNESS_PASS_SCORE

    cohort = world.create_cohort(standard["id"])
    instructor = validate_success(world.client.create_instructor(
        f.instructor_payload(), director_headers()), 201)
    assert instructor["certification_status"] == "UNCERTIFIED"
    assert instructor["fto_certified"] is False
    assert instructor["certification_expires_at"] is None
    assert instructor["authorized_topic_codes"] == []
    assert instructor["active_trainee_count"] == 0
    assert instructor["revocation_reason"] is None

    plan = validate_success(world.client.create_lesson_plan(
        f.lesson_plan_payload(instructor["id"], topic_code=PATROL,
                              contact_hours=2.0),
        make_academy_instructor_headers(instructor["id"])), 201)
    assert plan["status"] == "SUBMITTED"
    assert plan["revision_number"] == 1
    assert plan["approved_revision_number"] is None
    assert plan["approved_at"] is None
    assert plan["approved_by_user_id"] is None
    assert plan["reviewer_notes"] is None

    world.certify_instructor(instructor["id"], authorized_topic_codes=[PATROL])
    world.approve_lesson_plan(plan["id"])

    payload = f.course_session_payload(cohort["id"], plan["id"],
                                       instructor["id"], room_code="R1")
    assert "min_enrollment" not in payload
    session = validate_success(world.client.create_course_session(
        payload, coordinator_headers()), 201)
    assert session["min_enrollment"] == DEFAULT_MIN_ENROLLMENT
    assert session["status"] == "SCHEDULED"
    assert session["void_reason"] is None
    assert session["enrolled_count"] == 0


def test_a_session_derives_its_hours_topic_and_pin_at_creation(world):
    """Eighty minutes read 1.33 hours, and the topic and pin come from the plan.

    PRD: "`scheduled_hours` is the elapsed time from `starts_at` to `ends_at`
    expressed in hours - the number of seconds between them divided by 3600,
    rounded half up to 2 decimal places."

    Design: Corner/entities/computed_fields_session_derives_hours_topic_and_pinned_revision_at_create
    """
    standard = world.create_standard(
        min_total_hours=4.0,
        topic_requirements=[f.topic_requirement(PATROL, 4.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)

    session = world.schedule_session(
        cohort["id"], plan["id"], instructor["id"], room_code="R1",
        starts_at="2026-08-10T09:00:00Z", ends_at="2026-08-10T10:20:00Z",
        min_enrollment=1)

    assert_hours_equals(session["scheduled_hours"], "1.33", "scheduled_hours")
    assert session["topic_code"] == PATROL
    assert session["pinned_lesson_plan_revision"] == 1
    assert session["enrolled_count"] == 0
    assert_hours_equals(session["credited_hours_total"], "0.00",
                        "credited_hours_total")
    assert session["version"] == 1


def test_a_client_supplied_id_version_or_timestamp_never_lands(world):
    """The row is minted by the server whatever the request body claims.

    PRD: "Every resource in this system carries a server-minted `id`, formatted as
    a UUID with no type prefix, and a `created_at` timestamp: an ISO 8601 UTC
    instant with three fractional digits, taken at the moment the row was first
    written."

    Design: Corner/entities/system_fields_client_supplied_id_version_and_timestamps_are_input_ignored
    """
    claimed_id = "11111111-1111-4111-8111-111111111111"
    payload = f.certification_standard_payload(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    payload.update({"id": claimed_id, "version": 99,
                    "created_at": "1999-01-01T00:00:00Z",
                    "updated_at": "1999-01-01T00:00:00Z"})

    standard = validate_success(world.client.create_certification_standard(
        payload, director_headers()), 201)
    assert is_valid_uuid(standard["id"])
    assert standard["id"] != claimed_id
    assert standard["version"] == 1
    assert_instant_equals(standard["created_at"], CLOCK_EPOCH, "created_at")
    assert standard["created_at"][-5] == ".", (
        f"created_at must carry three fractional digits: "
        f"{standard['created_at']!r}")
    assert_instant_equals(standard["updated_at"], standard["created_at"],
                          "updated_at")

    read_back = validate_success(world.client.get_certification_standard(
        standard["id"], custodian_headers()))
    assert read_back["id"] == standard["id"]

    validate_error(world.client.get_certification_standard(
        claimed_id, custodian_headers()),
        ERR_CERTIFICATION_STANDARD_NOT_FOUND, 404)


def test_bad_enum_members_and_out_of_range_numbers_are_all_bad_requests(world):
    """Four ill-typed bodies, including a nested rating, are each rejected at 400.

    PRD: "the `age_bracket` whose fitness standard applies to them: `AGE_20_29`,
    `AGE_30_39` or `AGE_40_49`."

    Design: Corner/entities/type_constraints_invalid_enum_and_out_of_range_numbers_are_rejected
    """
    curriculum = world.curriculum(topic_code=PATROL, required_hours=2.0,
                                  exam_required=False, min_total_hours=2.0,
                                  session_ends_at="2026-08-03T11:00:00Z",
                                  after_session="2026-08-03T11:00:00Z")
    built = world.active_rotation(curriculum)

    unknown_bracket = f.recruit_payload(curriculum["cohort"]["id"],
                                        full_name="Sam Vega")
    unknown_bracket["age_bracket"] = "AGE_50_59"
    validate_error(world.client.create_recruit(unknown_bracket,
                                               coordinator_headers()),
                   ERR_INVALID_REQUEST, 400)

    lowercase_state = f.certification_standard_payload(
        state_code="texas",
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    validate_error(world.client.create_certification_standard(
        lowercase_state, director_headers()), ERR_INVALID_REQUEST, 400)

    over_range = f.certification_standard_payload(
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)],
        fitness_pass_score=140)
    validate_error(world.client.create_certification_standard(
        over_range, director_headers()), ERR_INVALID_REQUEST, 400)

    over_rated = f.observation_report_payload(
        built["fto"]["id"], "2026-09-02",
        f.dimension_ratings(4, officer_safety=9))
    validate_error(world.client.create_observation_report(
        built["rotation"]["id"], over_rated,
        make_fto_headers(built["fto"]["id"])), ERR_INVALID_REQUEST, 400)

    untouched = world.read_rotation(built["rotation"]["id"])
    assert untouched["dor_count"] == 0
    assert untouched["competency_score"] is None


def test_a_training_record_entry_carries_no_version_and_no_updated_at(world):
    """The litigation record is append-only: id and created_at, nothing mutable.

    PRD: "a training record entry carries only an `id` and a `created_at` and has
    no `updated_at` or `version`."

    Design: Corner/entities/immutability_training_record_entries_are_append_only_and_carry_no_version
    """
    curriculum = world.curriculum(topic_code=PATROL, required_hours=2.0,
                                  exam_required=False, min_total_hours=2.0)
    recruit = world.recruit_in_academy(curriculum["cohort"]["id"])
    session = world.schedule_session(
        curriculum["cohort"]["id"], curriculum["lesson_plan"]["id"],
        curriculum["instructor"]["id"], room_code="R1",
        starts_at="2026-08-10T09:00:00Z", ends_at="2026-08-10T11:00:00Z",
        min_enrollment=1)
    world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock("2026-08-10T12:00:00Z")
    world.deliver_session(session["id"])

    rows, _meta = validate_paginated(world.client.list_training_record_entries(
        custodian_headers(), {"recruit_id": recruit["id"],
                              "kind": "HOURS_CREDIT"}))
    assert len(rows) >= 1
    assert all(row["kind"] == "HOURS_CREDIT" for row in rows)

    entry = validate_success(world.client.get_training_record_entry(
        rows[0]["id"], custodian_headers()))
    assert is_valid_uuid(entry["id"])
    assert entry["created_at"] is not None
    assert "version" not in entry
    assert "updated_at" not in entry
    assert_hours_equals(entry["hours_delta"], "2.00", "hours_delta")
    assert entry["topic_code"] == PATROL
    assert entry["recruit_id"] == recruit["id"]
    assert entry["academy_class_id"] == curriculum["cohort"]["id"]
    assert entry["actor_role"] is not None
    assert entry["actor_user_id"] is not None
    assert entry["subject_entity_id"] is not None


def test_a_body_foreign_key_is_checked_against_its_own_entity(world):
    """Each unresolvable body reference answers the 404 of the entity it named.

    PRD: "Every foreign-key identifier supplied in the request body resolves to an
    existing row - otherwise the matching 404."

    Design: Corner/entities/parent_relationships_body_fks_are_checked_against_their_own_entity
    """
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])

    validate_error(world.client.create_academy_class(
        f.academy_class_payload(NON_EXISTENT_UUID), director_headers()),
        ERR_CERTIFICATION_STANDARD_NOT_FOUND, 404)
    validate_error(world.client.create_recruit(
        f.recruit_payload(NON_EXISTENT_UUID, full_name="Zed Roe"),
        coordinator_headers()), ERR_ACADEMY_CLASS_NOT_FOUND, 404)
    validate_error(world.client.create_lesson_plan(
        f.lesson_plan_payload(NON_EXISTENT_UUID, topic_code=PATROL,
                              title="Orphan Plan", contact_hours=2.0),
        coordinator_headers()), ERR_INSTRUCTOR_NOT_FOUND, 404)

    still_there = validate_success(world.client.get_academy_class(
        cohort["id"], director_headers()))
    assert still_there["id"] == cohort["id"]

    _rows, meta = validate_paginated(world.client.list_academy_classes(
        director_headers(), {"certification_standard_id": standard["id"]}))
    assert meta["total_count"] == 1
