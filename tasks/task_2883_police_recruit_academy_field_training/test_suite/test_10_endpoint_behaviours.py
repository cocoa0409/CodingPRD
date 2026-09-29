"""What each endpoint does when it is used exactly as the contract describes.

The lesson-plan review loop, the graduation run, the remedial branch of rotation
completion, the phase chain and the recomputed progress report are all read here
through the endpoints themselves rather than through any stored mirror.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_PRIOR_ROTATION_MISMATCH,
    ERR_ROTATION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_hours_equals,
    assert_instant_equals,
    assert_key_order,
    assert_score_equals,
    count_entries,
    find_entry,
)
from test_helpers.test_users import (
    coordinator_headers,
    custodian_headers,
    director_headers,
    make_academy_instructor_headers,
    make_recruit_headers,
)

PATROL = "PATROL"
ETHICS = "ETHICS"
MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _patrol_standard(world, min_total_hours=2.0, required_hours=2.0,
                     exam_required=False, **standard_kwargs):
    """A single-topic standard with a cohort on it, an FTO-less instructor and a plan."""
    standard = world.create_standard(
        min_total_hours=min_total_hours,
        topic_requirements=[f.topic_requirement(PATROL, required_hours,
                                               exam_required)],
        **standard_kwargs)
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL)
    return {"standard": standard, "cohort": cohort, "instructor": instructor,
            "lesson_plan": plan, "topic_code": PATROL}


def _teach(world, built, cohort_id=None, day="2026-08-10", starts="09:00:00",
           ends="11:00:00", min_enrollment=1):
    return world.schedule_session(cohort_id or built["cohort"]["id"],
                                  built["lesson_plan"]["id"],
                                  built["instructor"]["id"], room_code="R1",
                                  starts_at=f"{day}T{starts}Z",
                                  ends_at=f"{day}T{ends}Z",
                                  min_enrollment=min_enrollment)


def test_the_review_loop_walks_submit_read_list_revise_and_approve(world):
    """One plan travels the whole loop and every read agrees with the last write.

    PRD: "A plan begins at `status` `SUBMITTED` with `revision_number` 1, a null
    `approved_revision_number`, a null `approved_at`, a null
    `approved_by_user_id` and null `reviewer_notes`."

    Design: Corner/endpoints/standard_crud_lesson_plan_walks_submit_read_list_revise_and_approve
    """
    instructor = world.create_certified_instructor(topics=[PATROL])
    author = make_academy_instructor_headers(instructor["id"])
    world.set_clock("2026-08-05T10:00:00Z")

    created = validate_success(world.client.create_lesson_plan(
        f.lesson_plan_payload(instructor["id"], PATROL, "Patrol Operations",
                              2.0), author), 201)
    assert created["status"] == "SUBMITTED"
    assert created["revision_number"] == 1
    assert created["version"] == 1
    for absent in ("approved_revision_number", "approved_at",
                   "approved_by_user_id", "reviewer_notes"):
        assert created[absent] is None, f"{absent} must start null"

    read = validate_success(world.client.get_lesson_plan(created["id"],
                                                        custodian_headers()))
    assert read["id"] == created["id"]
    assert read["version"] == 1

    mine, mine_meta = validate_paginated(world.client.list_lesson_plans(
        director_headers(), {"instructor_id": instructor["id"]}))
    assert mine_meta["total_count"] == 1
    assert mine_meta["limit"] == 10
    assert mine_meta["offset"] == 0
    assert mine_meta["has_more"] is False
    assert mine[0]["id"] == created["id"]

    # An empty filtered page is a success, not a 404.
    none_yet, none_meta = validate_paginated(world.client.list_lesson_plans(
        director_headers(), {"status": "APPROVED"}))
    assert none_meta["total_count"] == 0
    assert none_yet == []

    # The revision verb has no SUBMITTED source state.
    validate_error(world.client.create_lesson_plan_revision(
        created["id"], f.lesson_plan_revision_payload(1, 3.0, "premature edit"),
        author), ERR_INVALID_STATE, 409)

    sent_back = validate_success(world.client.request_lesson_plan_revision(
        created["id"], f.request_revision_payload("add a use-of-force block"),
        director_headers()))
    assert sent_back["status"] == "REVISION_REQUESTED"
    assert sent_back["reviewer_notes"] == "add a use-of-force block"
    assert sent_back["revision_number"] == 1
    assert sent_back["version"] == 2

    revised = validate_success(world.client.create_lesson_plan_revision(
        created["id"],
        f.lesson_plan_revision_payload(2, 3.0, "use-of-force block added"),
        author))
    assert revised["status"] == "SUBMITTED"
    assert revised["revision_number"] == 2
    assert_hours_equals(revised["contact_hours"], "3.00", "contact_hours")
    assert revised["reviewer_notes"] is None
    assert revised["version"] == 3

    approved = validate_success(world.client.approve_lesson_plan(
        created["id"], director_headers()))
    assert approved["status"] == "APPROVED"
    assert approved["approved_revision_number"] == 2
    assert_instant_equals(approved["approved_at"], "2026-08-05T10:00:00Z",
                          "approved_at")
    assert approved["approved_by_user_id"] == "dir-1"
    assert approved["version"] == 4

    # No verb in the chain overwrote an immutable input field.
    final = validate_success(world.client.get_lesson_plan(created["id"], author))
    assert final["title"] == "Patrol Operations"
    assert final["instructor_id"] == instructor["id"]

    _rows, approved_meta = validate_paginated(world.client.list_lesson_plans(
        director_headers(), {"status": "APPROVED"}))
    assert approved_meta["total_count"] == 1


def test_sending_a_plan_back_is_legal_only_from_submitted(world):
    """An approved plan is never sent back, and asking twice is not idempotent.

    PRD: "This route is legal from `SUBMITTED` **only**: an approved plan is
    never sent back this way, and asking for it answers `ERR_INVALID_STATE`."

    Design: Corner/endpoints/action_endpoint_request_revision_is_legal_only_from_submitted
    """
    built = _patrol_standard(world)
    author = make_academy_instructor_headers(built["instructor"]["id"])
    plan = built["lesson_plan"]
    session = _teach(world, built)

    validate_error(world.client.request_lesson_plan_revision(
        plan["id"], f.request_revision_payload("reviewer wants a rewrite"),
        director_headers()), ERR_INVALID_STATE, 409)

    # The author may supersede an approved revision; the approval stamp stays.
    superseded = validate_success(world.client.create_lesson_plan_revision(
        plan["id"],
        f.lesson_plan_revision_payload(plan["version"], 2.0,
                                       "author supersedes the approved revision"),
        author))
    assert superseded["status"] == "SUBMITTED"
    assert superseded["revision_number"] == 2
    assert superseded["approved_revision_number"] == 1

    sent_back = validate_success(world.client.request_lesson_plan_revision(
        plan["id"], f.request_revision_payload("now it is reviewable"),
        director_headers()))
    assert sent_back["status"] == "REVISION_REQUESTED"
    assert sent_back["reviewer_notes"] == "now it is reviewable"
    # PRD: sending a plan back "clears `approved_revision_number`, `approved_at`
    # and `approved_by_user_id` to null".
    assert sent_back["approved_revision_number"] is None
    assert sent_back["approved_at"] is None
    assert sent_back["approved_by_user_id"] is None

    validate_error(world.client.request_lesson_plan_revision(
        plan["id"], f.request_revision_payload("asking twice"),
        director_headers()), ERR_INVALID_STATE, 409)

    # One version bump per accepted write, none for the two rejects.
    final = validate_success(world.client.get_lesson_plan(plan["id"],
                                                         director_headers()))
    assert final["revision_number"] == 2
    assert final["approved_revision_number"] is None
    assert final["reviewer_notes"] == "now it is reviewable"
    assert final["version"] == 4

    # The session's pin still resolves to a revision number that exists.
    pinned = validate_success(world.client.get_course_session(
        session["id"], coordinator_headers()))
    assert pinned["pinned_lesson_plan_revision"] == 1
    assert pinned["status"] == "SCHEDULED"


def test_a_graduation_run_that_certifies_nobody_is_a_success(world):
    """An all-ineligible cohort answers 200 with a zero count and keeps its posture.

    PRD: "A run in which zero recruits qualify leaves the cohort posture
    completely unchanged and reports a `certified_count` of zero: the empty-set
    edge is a success, not an error."

    Design: Corner/endpoints/bulk_action_certify_graduates_certifies_the_eligible_and_reports_each_skip_reason
    """
    built = _patrol_standard(world)
    idle = world.create_recruit(built["cohort"]["id"], applicant_number="A-900")
    session = _teach(world, built, day="2026-08-09")
    world.set_clock("2026-08-09T13:00:00Z")
    world.deliver_session(session["id"])

    run = world.certify_graduates(built["cohort"]["id"])
    assert run["academy_class_id"] == built["cohort"]["id"]
    assert run["certified_count"] == 0
    assert run["certified_recruit_ids"] == []
    assert run["class_status"] == "IN_SESSION"
    assert len(run["skipped"]) == 1
    assert run["skipped"][0]["recruit_id"] == idle["id"]
    assert run["skipped"][0]["reason_code"] == "PROBATION_NOT_PASSED"
    assert set(run["skipped"][0]) == {"recruit_id", "reason_code"}

    untouched = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert untouched["status"] == "IN_SESSION"
    assert untouched["graduated_count"] == 0

    # The cohort was not consumed: it may be run again later.
    again = world.certify_graduates(built["cohort"]["id"])
    assert again["certified_count"] == 0


def test_the_graduation_run_certifies_the_eligible_and_names_each_skip(world):
    """One of four recruits graduates and the other three each get one reason.

    PRD: "The `reason_code` is the **first applicable** of exactly four values,
    evaluated in exactly this order: `PROBATION_NOT_PASSED` when `pipeline_stage`
    is not `PROBATION` or `probation_status` is not `PASSED`; `HOURS_SHORTFALL`
    when the recruit's own attended-basis `credited_hours_total` is below
    `min_total_hours`."

    Design: Corner/endpoints/bulk_action_certify_graduates_certifies_the_eligible_and_reports_each_skip_reason
    """
    built = _patrol_standard(world, min_total_hours=4.0, required_hours=2.0,
                             exam_required=True)
    cohort_id = built["cohort"]["id"]

    # Created an hour apart, so the skipped array's created_at order is pinned.
    roster = {}
    for index, code in enumerate(("A-001", "A-002", "A-003", "A-004"), start=1):
        world.set_clock(f"2026-08-01T0{index}:00:00Z")
        roster[code] = world.create_recruit(cohort_id, applicant_number=code)
    graduate, applicant = roster["A-001"], roster["A-002"]
    still_active, short_hours = roster["A-003"], roster["A-004"]

    for recruit in (graduate, still_active, short_hours):
        world.clear_all_four_screenings(recruit["id"])
        world.advance(recruit["id"], "ACADEMY")

    morning = _teach(world, built, day="2026-08-10")
    afternoon = _teach(world, built, day="2026-08-10", starts="11:00:00",
                       ends="13:00:00")
    world.record_attendance(morning["id"], graduate["id"], "PRESENT", 2.0)
    world.record_attendance(afternoon["id"], graduate["id"], "PRESENT", 2.0)
    world.record_attendance(morning["id"], still_active["id"], "PRESENT", 2.0)
    world.record_attendance(morning["id"], short_hours["id"], "PRESENT", 2.0)
    world.set_clock("2026-08-10T13:00:00Z")
    world.deliver_session(morning["id"])
    world.deliver_session(afternoon["id"])

    for recruit in (graduate, still_active, short_hours):
        exam = world.schedule_examination(recruit["id"], PATROL)
        world.grade_examination(exam["id"], 80.0)
        world.advance(recruit["id"], "FIELD_TRAINING")

    rotations = {}
    for recruit in (graduate, still_active, short_hours):
        officer = world.create_certified_fto()
        rotations[recruit["id"]] = (
            officer,
            world.plan_rotation(world.read_recruit(recruit["id"]), officer["id"],
                                phase_number=1, start_date="2026-08-20",
                                end_date="2026-08-26"))
    world.set_clock("2026-08-20T08:00:00Z")
    for officer, rotation in rotations.values():
        world.activate_rotation(rotation["id"])
    world.set_clock("2026-08-21T18:00:00Z")
    for officer, rotation in rotations.values():
        world.file_report(rotation["id"], officer["id"], "2026-08-21",
                          f.dimension_ratings(5))
    world.set_clock("2026-08-26T08:00:00Z")
    for _officer, rotation in rotations.values():
        world.complete_rotation(rotation["id"])
    for recruit in (graduate, still_active, short_hours):
        world.advance(recruit["id"], "PROBATION", probation_start="2026-09-02",
                      probation_base_days=20)

    world.set_clock("2026-09-12T08:00:00Z")
    world.probation_decision(graduate["id"], "PASS")
    world.probation_decision(short_hours["id"], "PASS")

    run = world.certify_graduates(cohort_id)
    assert run["certified_count"] == 1
    assert run["certified_recruit_ids"] == [graduate["id"]]
    assert run["class_status"] == "GRADUATED"
    # A-002 breaks all four preconditions and still reports only the first.
    # A-003 is at PROBATION but only ACTIVE, which the same code covers.
    # A-004 met the 2.00 topic minimum, so only the 4.00 aggregate is short.
    assert [(entry["recruit_id"], entry["reason_code"])
            for entry in run["skipped"]] == [
        (applicant["id"], "PROBATION_NOT_PASSED"),
        (still_active["id"], "PROBATION_NOT_PASSED"),
        (short_hours["id"], "HOURS_SHORTFALL"),
    ]

    # GRADUATED is terminal, so a repeat run is a conflict, not a zero count.
    validate_error(world.client.certify_graduates(cohort_id, director_headers()),
                   ERR_INVALID_STATE, 409)

    cohort = validate_success(world.client.get_academy_class(
        cohort_id, director_headers()))
    assert cohort["status"] == "GRADUATED"
    assert cohort["graduated_count"] == 1

    certified = world.read_recruit(graduate["id"])
    assert certified["pipeline_stage"] == "CERTIFIED"
    assert_hours_equals(certified["credited_hours_total"], "4.00",
                        "credited_hours_total")
    assert certified["probation_status"] == "PASSED"

    # A skip is not a mutation.
    skipped_read = world.read_recruit(short_hours["id"])
    assert skipped_read["pipeline_stage"] == "PROBATION"
    assert_hours_equals(skipped_read["credited_hours_total"], "2.00",
                        "credited_hours_total")

    entries = world.training_record_entries(recruit_id=graduate["id"])
    assert count_entries(entries, kind="CERTIFICATION_ISSUED") == 1
    issued = find_entry(entries, kind="CERTIFICATION_ISSUED")
    assert issued["stage_code"] == "PROBATION"
    assert_hours_equals(issued["hours_delta"], "0.00", "hours_delta")


def _remedial_probation(world):
    """A probationary trainee whose phase-two rotation slumped into REMEDIAL."""
    built = _patrol_standard(world)
    recruit = world.recruit_in_field_training(built)
    first_fto = world.create_certified_fto()
    second_fto = world.create_certified_fto()

    phase_one = world.plan_rotation(recruit, first_fto["id"], phase_number=1,
                                    start_date="2026-08-20",
                                    end_date="2026-09-02")
    world.set_clock("2026-08-20T08:00:00Z")
    world.activate_rotation(phase_one["id"])
    world.set_clock("2026-08-21T18:00:00Z")
    world.file_report(phase_one["id"], first_fto["id"], "2026-08-21",
                      f.dimension_ratings(5))
    world.set_clock("2026-09-03T08:00:00Z")
    world.complete_rotation(phase_one["id"])
    world.advance(recruit["id"], "PROBATION", probation_start="2026-09-05")

    phase_two = world.plan_rotation(world.read_recruit(recruit["id"]),
                                    second_fto["id"], phase_number=2,
                                    start_date="2026-09-10",
                                    end_date="2026-09-23",
                                    prior_rotation_id=phase_one["id"])
    world.set_clock("2026-09-10T08:00:00Z")
    world.activate_rotation(phase_two["id"])
    world.set_clock("2026-09-11T18:00:00Z")
    world.file_report(phase_two["id"], second_fto["id"], "2026-09-11",
                      f.dimension_ratings(3), narrative="not meeting standard")
    return {"built": built, "recruit": recruit, "first_fto": first_fto,
            "second_fto": second_fto, "phase_one": phase_one,
            "phase_two": phase_two}


def test_closing_a_remedial_rotation_does_not_forgive_the_extension(world):
    """A 3.00 phase costs 60 days, and completing that phase gives none of them back.

    PRD: "Completing a remedial rotation is legal - the 4.00 threshold gates the
    `ACTIVE` <-> `REMEDIAL` loop, not this transition - and it does **not** clear
    a trainee's `EXTENSION_REQUIRED` posture."

    Design: Corner/endpoints/conditional_action_completion_branches_on_whether_the_rotation_was_remedial
    """
    scene = _remedial_probation(world)
    recruit_id = scene["recruit"]["id"]

    flipped = world.read_rotation(scene["phase_two"]["id"])
    assert flipped["status"] == "REMEDIAL"

    extended = world.read_recruit(recruit_id)
    assert extended["probation_status"] == "EXTENSION_REQUIRED"
    assert extended["probation_milestone_due_date"] == "2027-03-06"
    assert_score_equals(extended["probation_milestone_score"], "3.00",
                        "probation_milestone_score")
    assert extended["probation_extension_days"] == 60
    assert extended["probation_scheduled_end"] == "2027-11-04"

    world.set_clock("2026-09-24T08:00:00Z")
    closed = world.complete_rotation(scene["phase_two"]["id"])
    assert closed["status"] == "COMPLETED"

    unforgiven = world.read_recruit(recruit_id)
    assert unforgiven["probation_status"] == "EXTENSION_REQUIRED"
    assert unforgiven["probation_extension_days"] == 60
    assert unforgiven["probation_scheduled_end"] == "2027-11-04"

    # The extension decision re-derives the schedule to the same numbers,
    # because rotation two is still the top-ranked qualifying row.
    decided = world.probation_decision(recruit_id, "EXTEND",
                                       "one more phase authorised")
    assert decided["probation_status"] == "ACTIVE"
    assert decided["probation_extension_days"] == 60
    assert decided["probation_scheduled_end"] == "2027-11-04"
    assert decided["probation_milestone_due_date"] == "2027-03-06"


def test_a_later_completed_rotation_outranks_the_earlier_remedial_one(world):
    """Phase three clears the extension only once it is COMPLETED, not while ACTIVE.

    PRD: "Eligible rows are those of this recruit whose `status` is `COMPLETED`
    or `REMEDIAL`, whose `end_date` is at or before
    `probation_milestone_due_date`, and whose `competency_score` is not null;
    `PLANNED`, `ACTIVE` and `ABORTED` rotations are excluded."

    Design: Corner/endpoints/conditional_action_completion_branches_on_whether_the_rotation_was_remedial
    """
    scene = _remedial_probation(world)
    recruit_id = scene["recruit"]["id"]
    third_fto = world.create_certified_fto()

    world.set_clock("2026-09-24T08:00:00Z")
    world.complete_rotation(scene["phase_two"]["id"])
    world.probation_decision(recruit_id, "EXTEND", "one more phase authorised")

    phase_three = world.plan_rotation(world.read_recruit(recruit_id),
                                      third_fto["id"], phase_number=3,
                                      start_date="2026-10-01",
                                      end_date="2026-10-14",
                                      prior_rotation_id=scene["phase_two"]["id"])
    world.set_clock("2026-10-01T08:00:00Z")
    world.activate_rotation(phase_three["id"])
    world.set_clock("2026-10-02T18:00:00Z")
    world.file_report(phase_three["id"], third_fto["id"], "2026-10-02",
                      f.dimension_ratings(5), narrative="standard met")

    # An ACTIVE rotation is outside the selector's input set, however strong.
    mid_phase = world.read_recruit(recruit_id)
    assert mid_phase["probation_extension_days"] == 60
    assert_score_equals(mid_phase["probation_milestone_score"], "3.00",
                        "probation_milestone_score")

    world.set_clock("2026-10-15T08:00:00Z")
    closed = world.complete_rotation(phase_three["id"])
    assert closed["status"] == "COMPLETED"

    final = world.read_recruit(recruit_id)
    assert final["probation_status"] == "ACTIVE"
    assert_score_equals(final["probation_milestone_score"], "5.00",
                        "probation_milestone_score")
    assert final["probation_extension_days"] == 0
    assert final["probation_scheduled_end"] == "2027-09-05"
    # Step 1 reads probation_base_days only, so the milestone never moved.
    assert final["probation_milestone_due_date"] == "2027-03-06"

    rows, meta = validate_paginated(world.client.list_field_training_rotations(
        coordinator_headers(), {"recruit_id": recruit_id}))
    assert meta["total_count"] == 3
    assert [row["status"] for row in rows] == ["COMPLETED"] * 3

    released = validate_success(world.client.get_instructor(
        scene["first_fto"]["id"], director_headers()))
    assert released["active_trainee_count"] == 0


def test_the_phase_chain_is_validated_at_creation_and_filterable_afterwards(world):
    """A successor names its predecessor, and the listing walks the link both ways.

    PRD: "`prior_rotation_id` optionally names the rotation this phase follows,
    which must belong to the same recruit and whose `phase_number` must be
    exactly one less than this one."

    Design: Corner/endpoints/cross_reference_link_prior_rotation_id_chains_phases_and_is_filterable
    """
    built = _patrol_standard(world)
    recruit = world.recruit_in_field_training(built)
    first_fto = world.create_certified_fto()
    second_fto = world.create_certified_fto()
    idle_fto = world.create_certified_fto()

    phase_one = world.plan_rotation(recruit, first_fto["id"], phase_number=1,
                                    start_date="2026-08-20",
                                    end_date="2026-09-02")
    world.set_clock("2026-08-20T08:00:00Z")
    world.activate_rotation(phase_one["id"])
    world.set_clock("2026-08-21T18:00:00Z")
    world.file_report(phase_one["id"], first_fto["id"], "2026-08-21",
                      f.dimension_ratings(5))
    world.set_clock("2026-09-03T08:00:00Z")
    world.complete_rotation(phase_one["id"])
    current = world.read_recruit(recruit["id"])

    def plan(phase_number, prior_rotation_id):
        return world.client.create_field_training_rotation(
            f.rotation_payload(recruit["id"], second_fto["id"],
                               current["version"], phase_number=phase_number,
                               start_date="2026-09-10", end_date="2026-09-23",
                               prior_rotation_id=prior_rotation_id),
            coordinator_headers())

    # 3 is not exactly one more than 1.
    validate_error(plan(3, phase_one["id"]), ERR_PRIOR_ROTATION_MISMATCH, 422)
    # The self-referencing foreign key is resolved before the semantic check.
    validate_error(plan(2, MISSING_ID), ERR_ROTATION_NOT_FOUND, 404)

    phase_two = validate_success(plan(2, phase_one["id"]), 201)
    assert phase_two["prior_rotation_id"] == phase_one["id"]
    assert phase_two["phase_number"] == 2

    successors, successors_meta = validate_paginated(
        world.client.list_field_training_rotations(
            coordinator_headers(), {"prior_rotation_id": phase_one["id"]}))
    assert successors_meta["total_count"] == 1
    assert successors[0]["id"] == phase_two["id"]

    _none, unchained_meta = validate_paginated(
        world.client.list_field_training_rotations(
            coordinator_headers(), {"prior_rotation_id": phase_two["id"]}))
    assert unchained_meta["total_count"] == 0

    # Neither rejected create left a row behind.
    chain, chain_meta = validate_paginated(
        world.client.list_field_training_rotations(
            coordinator_headers(), {"recruit_id": recruit["id"]}))
    assert chain_meta["total_count"] == 2
    head = [row for row in chain if row["id"] == phase_one["id"]][0]
    assert head["prior_rotation_id"] is None

    _empty, idle_meta = validate_paginated(
        world.client.list_field_training_rotations(
            coordinator_headers(), {"fto_instructor_id": idle_fto["id"]}))
    assert idle_meta["total_count"] == 0


def test_the_progress_report_is_recomputed_on_every_read_and_stored_nowhere(world):
    """Two reads with no write between them differ once a delivery lands between them.

    PRD: "A recruit's curriculum progress is available as a report that is
    recomputed from current state on every read and persisted nowhere."

    Design: Corner/endpoints/computed_read_certification_progress_is_recomputed_and_stored_nowhere
    """
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 4.0, True),
                            f.topic_requirement(ETHICS, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL, ETHICS])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    recruit = world.recruit_in_academy(cohort["id"])

    attended = world.schedule_session(cohort["id"], plan["id"], instructor["id"],
                                      room_code="R1",
                                      starts_at="2026-08-10T09:00:00Z",
                                      ends_at="2026-08-10T11:00:00Z",
                                      min_enrollment=1)
    world.record_attendance(attended["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock("2026-08-10T12:00:00Z")
    world.deliver_session(attended["id"])

    excused = world.schedule_session(cohort["id"], plan["id"], instructor["id"],
                                     room_code="R1",
                                     starts_at="2026-08-11T09:00:00Z",
                                     ends_at="2026-08-11T11:00:00Z",
                                     min_enrollment=1)
    world.record_attendance(excused["id"], recruit["id"], "ABSENT_EXCUSED", 0.0)

    first = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers()))
    assert first["recruit_id"] == recruit["id"]
    assert first["basis"] == "ATTENDED"
    assert_hours_equals(first["total_hours"], "2.00", "total_hours")
    # The untouched topic is present with 0.00, not absent.
    assert_key_order(first["per_topic_hours"], [PATROL, ETHICS],
                     "per_topic_hours")
    assert_hours_equals(first["per_topic_hours"][PATROL], "2.00", PATROL)
    assert_hours_equals(first["per_topic_hours"][ETHICS], "0.00", ETHICS)
    assert_key_order(first["unmet_topic_hours"], [PATROL, ETHICS],
                     "unmet_topic_hours")
    assert_hours_equals(first["unmet_topic_hours"][PATROL], "2.00", PATROL)
    assert_hours_equals(first["unmet_topic_hours"][ETHICS], "2.00", ETHICS)
    # ETHICS requires no exam, so it has no exam_status entry at all.
    assert first["exam_status"] == {PATROL: "NOT_TAKEN"}
    assert_hours_equals(first["make_up_hours_owed"], "0.00",
                        "make_up_hours_owed")
    assert first["eligible_for_certification"] is False

    scheduled = validate_success(world.client.get_certification_progress(
        recruit["id"], custodian_headers(), {"basis": "SCHEDULED"}))
    assert scheduled["basis"] == "SCHEDULED"
    assert_hours_equals(scheduled["total_hours"], "2.00", "total_hours")
    assert scheduled["eligible_for_certification"] is False

    world.set_clock("2026-08-11T12:00:00Z")
    world.deliver_session(excused["id"])
    before_reads = world.read_recruit(recruit["id"])

    # An excused row credits 0.00 attended hours but does owe make-up time.
    third = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers()))
    assert_hours_equals(third["total_hours"], "2.00", "total_hours")
    assert_hours_equals(third["make_up_hours_owed"], "2.00",
                        "make_up_hours_owed")

    # The recruit may read their own progress, and the excused block counts in
    # full on the scheduled basis only.
    own = validate_success(world.client.get_certification_progress(
        recruit["id"], make_recruit_headers(recruit["id"]),
        {"basis": "SCHEDULED"}))
    assert own["recruit_id"] == recruit["id"]
    assert_hours_equals(own["total_hours"], "4.00", "total_hours")

    mirror = world.read_recruit(recruit["id"])
    assert_hours_equals(mirror["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert_hours_equals(mirror["scheduled_basis_hours_total"], "4.00",
                        "scheduled_basis_hours_total")
    for absent in ("unmet_topic_hours", "exam_status",
                   "eligible_for_certification"):
        assert absent not in mirror, f"the recruit entity must not carry {absent}"
    # No progress read is a write.
    assert mirror["version"] == before_reads["version"]
