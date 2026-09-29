"""Cross-cutting layers: the three optimistic-concurrency guards, the version
token's movement, the reliability rate threshold, and the immediacy of every
cross-aggregate derivation.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC, TEST_DEFAULTS
from test_helpers.factories import (
    create_aid_disbursement_payload,
    create_blueprint_payload,
    create_mentor_assignment_payload,
    dimension_score,
)

ONE_DIMENSION = [{"code": "D1", "weight": 1.0000, "max_score": 100,
                  "critical": False}]


def _a_dependent_competency_moved_by_a_prerequisite_edge():
    """IT-101 and IT-201 on a published program. The client's view of IT-201 is
    captured at version 1, and then a prerequisite edge is added behind its back."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    ancestor = fx.create_competency(program["id"], code="IT-101",
                                    title="Relational Data Modeling",
                                    unit_value=4, level="FOUNDATION")
    dependent = fx.create_competency(program["id"], code="IT-201",
                                     title="Distributed Query Engines",
                                     unit_value=4, level="CORE")
    fx.publish_program(program["id"])
    assert dependent["version"] == 1

    linked = fx.set_prerequisite(dependent["id"], ancestor["id"])
    assert linked["prerequisite_competency_id"] == ancestor["id"]
    A.assert_common_fields(linked, expected_version=2)
    return {"program": program, "ancestor": ancestor, "dependent": dependent,
            "linked": linked}


def test_a_prerequisite_edge_added_behind_the_clients_back_defeats_the_publication():
    """The guarded parent is the competency rather than the blueprint being created,
    so a rubric published against the pre-edge view of IT-201 is refused outright.

    PRD: "If that value does not equal the competency's current `version`, the
    publication is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_competency_version_blocks_blueprint_publication
    """
    ctx = _a_dependent_competency_moved_by_a_prerequisite_edge()

    response = api_client.create_blueprint(
        create_blueprint_payload(ctx["dependent"]["id"], 1,
                                 dimensions=ONE_DIMENSION,
                                 required_evaluator_count=1),
        fx.REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    A.assert_page(
        api_client.list_blueprints(
            fx.REGISTRAR, params={"competency_id": ctx["dependent"]["id"]}
        ),
        0,
    )
    competency = fx.refresh_competency(ctx["dependent"]["id"])
    assert competency["effective_blueprint_id"] is None
    A.assert_common_fields(competency, expected_version=2)


def test_the_same_rubric_publishes_untouched_once_the_client_refreshes_its_view():
    """Nothing about the payload changes but the version token, and the publication
    then lands as the competency's first rubric with an open-ended window.

    PRD: "If there is no such blueprint, this is the competency's first rubric: any
    requested `effective_from_utc` is accepted, no notice period applies, and the new
    row is stored with `effective_to_utc` null."

    Design: Corner/cross_cutting_layers/stale_competency_version_blocks_blueprint_publication
    """
    ctx = _a_dependent_competency_moved_by_a_prerequisite_edge()

    blueprint = validate_success(
        api_client.create_blueprint(
            create_blueprint_payload(ctx["dependent"]["id"], 2,
                                     dimensions=ONE_DIMENSION,
                                     required_evaluator_count=1),
            fx.REGISTRAR,
        ),
        201,
    )
    assert blueprint["version_label"] == "BP-1"
    assert blueprint["status"] == "PUBLISHED"
    assert blueprint["effective_to_utc"] is None

    competency = fx.refresh_competency(ctx["dependent"]["id"])
    assert competency["effective_blueprint_id"] == blueprint["id"]
    A.assert_common_fields(competency, expected_version=3)


def _an_applicant_read_before_the_activation_that_moved_it():
    """A student the client read as an APPLICANT at version 1, activated behind its
    back, beside one ACTIVE mentor with four free caseload slots."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    fx.create_competency(program["id"], code="IT-101",
                         title="Relational Data Modeling",
                         unit_value=4, level="FOUNDATION")
    fx.publish_program(program["id"])
    stale = fx.create_student(program["id"], full_name="Ada Learner",
                              email="ada@example.edu")
    assert stale["enrollment_status"] == "APPLICANT"
    assert stale["version"] == 1
    mentor = fx.create_mentor(full_name="Mentor Meg", email="meg@example.edu")

    activated = fx.activate_student(stale["id"])
    assert activated["enrollment_status"] == "ACTIVE"
    A.assert_common_fields(activated, expected_version=2)
    return {"stale": stale, "activated": activated, "mentor": mentor}


def test_the_activation_itself_is_the_intervening_write_that_stales_the_pairing():
    """The assignment payload is otherwise perfect — an active student, an active
    mentor with room — and it is still refused, because the version it declares is
    the one from before the activation.

    PRD: "A mismatch against the student's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_student_version_blocks_mentor_assignment
    """
    ctx = _an_applicant_read_before_the_activation_that_moved_it()

    response = api_client.create_mentor_assignment(
        create_mentor_assignment_payload(ctx["stale"]["id"], 1,
                                         mentor_id=ctx["mentor"]["id"]),
        fx.REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    mentor = fx.refresh_mentor(ctx["mentor"]["id"])
    assert mentor["current_caseload"] == 0
    A.assert_common_fields(mentor, expected_version=1)
    A.assert_page(api_client.list_mentor_assignments(fx.REGISTRAR), 0)


def test_the_refreshed_student_version_pairs_the_mentee_and_takes_a_caseload_slot():
    """Declaring the post-activation version turns the identical payload into an
    explicit pairing, and the caseload figure moves in the same request.

    PRD: "When `mentor_id` is supplied the pairing is explicit and the resulting
    record has `selection_mode` `EXPLICIT`; the named mentor must be `ACTIVE` and must
    have a `current_caseload` strictly below their `max_caseload`, or the request is
    refused with `ERR_MENTOR_CASELOAD_FULL`."

    Design: Corner/cross_cutting_layers/stale_student_version_blocks_mentor_assignment
    """
    ctx = _an_applicant_read_before_the_activation_that_moved_it()

    assignment = validate_success(
        api_client.create_mentor_assignment(
            create_mentor_assignment_payload(ctx["stale"]["id"], 2,
                                             mentor_id=ctx["mentor"]["id"]),
            fx.REGISTRAR,
        ),
        201,
    )
    assert assignment["status"] == "ACTIVE"
    assert assignment["selection_mode"] == "EXPLICIT"

    assert fx.refresh_mentor(ctx["mentor"]["id"])["current_caseload"] == 1
    A.assert_common_fields(fx.refresh_student(ctx["stale"]["id"]),
                           expected_version=3)


def _a_term_activated_after_the_aid_officer_read_it():
    """A subscription term the aid officer read as PENDING at version 1, activated
    behind its back."""
    ctx = fx.base_chain(activate_the_term=False)
    assert ctx["term"]["status"] == "PENDING"
    assert ctx["term"]["version"] == 1
    active = fx.activate_term(ctx["term"]["id"])
    assert active["status"] == "ACTIVE"
    A.assert_common_fields(active, expected_version=2)
    ctx["stale_term"] = ctx["term"]
    ctx["term"] = active
    return ctx


def test_the_pending_era_term_version_defeats_the_aid_scheduling():
    """The aid officer's guarded parent is the term, because its credit equivalency
    moves underneath them; the award is refused and the student's scheduled total
    never leaves zero.

    PRD: "A mismatch against the term's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_term_version_blocks_aid_scheduling
    """
    ctx = _a_term_activated_after_the_aid_officer_read_it()

    response = api_client.create_aid_disbursement(
        create_aid_disbursement_payload(ctx["student"]["id"],
                                        ctx["stale_term"]["id"], 1),
        fx.AID_OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    A.assert_cents(fx.refresh_student(ctx["student"]["id"])
                     ["aid_scheduled_total_cents"],
                   0, "aid_scheduled_total_cents")
    A.assert_page(api_client.list_aid_disbursements(fx.AID_OFFICER), 0)


def test_the_current_term_version_schedules_the_award_and_moves_the_student_total():
    """With the post-activation version the award is created against a full
    outstanding balance and the student's scheduled roll-up follows immediately.

    PRD: "Creation increases the student's `aid_scheduled_total_cents` and increments
    both the student's and the term's `version`."

    Design: Corner/cross_cutting_layers/stale_term_version_blocks_aid_scheduling
    """
    ctx = _a_term_activated_after_the_aid_officer_read_it()

    award = validate_success(
        api_client.create_aid_disbursement(
            create_aid_disbursement_payload(ctx["student"]["id"],
                                            ctx["term"]["id"], 2),
            fx.AID_OFFICER,
        ),
        201,
    )
    assert award["status"] == "SCHEDULED"
    A.assert_cents(award["outstanding_amount_cents"],
                   TEST_DEFAULTS["AID_SCHEDULED_CENTS"],
                   "outstanding_amount_cents")
    A.assert_aid_ledger_identity(award)

    A.assert_cents(fx.refresh_student(ctx["student"]["id"])
                     ["aid_scheduled_total_cents"],
                   TEST_DEFAULTS["AID_SCHEDULED_CENTS"],
                   "aid_scheduled_total_cents")


def _a_published_program_with_one_mentor():
    """A published program with one active competency and one active mentor, ready
    to have a student walked through its whole enrollment axis."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    fx.create_competency(program["id"], code="IT-101",
                         title="Relational Data Modeling",
                         unit_value=4, level="FOUNDATION")
    program = fx.publish_program(program["id"])
    mentor = fx.create_mentor(full_name="Mentor Meg", email="meg@example.edu")
    return {"program": program, "mentor": mentor}


def test_reads_and_refusals_leave_the_version_token_exactly_where_it_was():
    """Creation writes version 1 and activation writes version 2; a read in between
    moves nothing, and the refused second activation moves nothing either.

    PRD: "`version` is an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of the row, including mutations caused indirectly by a
    cascade rather than directly by the caller."

    Design: Corner/cross_cutting_layers/version_increments_on_every_accepted_write_only
    """
    ctx = _a_published_program_with_one_mentor()

    student = fx.create_student(ctx["program"]["id"], full_name="Ada Learner",
                                email="ada@example.edu")
    A.assert_common_fields(student, expected_version=1)
    A.assert_common_fields(fx.activate_student(student["id"]), expected_version=2)
    A.assert_common_fields(fx.refresh_student(student["id"]), expected_version=2)

    validate_error(api_client.activate_student(student["id"], fx.REGISTRAR),
                   ApiErrorId.ERR_STUDENT_NOT_APPLICANT.value, 409)
    A.assert_common_fields(fx.refresh_student(student["id"]), expected_version=2)


def test_a_cross_entity_write_moves_the_student_token_it_never_named():
    """The pairing is created at its own version 1 while the student it references
    climbs to 3, and the two later enrollment transitions carry it to 5.

    PRD: "Every row a cascade touches is a mutation of that row: its `updated_at`
    advances to the logical clock and its `version` increments by 1."

    Design: Corner/cross_cutting_layers/version_increments_on_every_accepted_write_only
    """
    ctx = _a_published_program_with_one_mentor()
    student = fx.activate_student(
        fx.create_student(ctx["program"]["id"], full_name="Ada Learner",
                          email="ada@example.edu")["id"]
    )

    assignment = fx.assign_mentor(student, ctx["mentor"]["id"])
    A.assert_common_fields(assignment, expected_version=1)
    A.assert_common_fields(fx.refresh_student(student["id"]), expected_version=3)

    A.assert_common_fields(fx.suspend_student(student["id"]), expected_version=4)
    A.assert_common_fields(fx.reinstate_student(student["id"]), expected_version=5)


def _two_readers_on_two_two_reader_rubrics():
    """A program whose reliability floor is 50.00 over a single paired review, two
    two-reader competencies, and two CERTIFIED readers with a spotless rate."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program(irr_tolerance_pct=5.0, irr_min_paired_reviews=1,
                                irr_suspend_rate_pct=50.00)
    first = fx.create_competency(program["id"], code="IT-101",
                                 title="Relational Data Modeling",
                                 unit_value=4, level="FOUNDATION")
    second = fx.create_competency(program["id"], code="IT-102",
                                  title="Query Optimization",
                                  unit_value=4, level="FOUNDATION")
    program = fx.publish_program(program["id"])
    fx.create_blueprint(first, dimensions=ONE_DIMENSION,
                        required_evaluator_count=2)
    fx.create_blueprint(second, dimensions=ONE_DIMENSION,
                        required_evaluator_count=2)
    A.assert_number_equals(program["irr_tolerance_pct"], 5.0, "irr_tolerance_pct")
    assert program["irr_min_paired_reviews"] == 1
    A.assert_number_equals(program["irr_suspend_rate_pct"], 50.00,
                           "irr_suspend_rate_pct")

    student = fx.activate_student(
        fx.create_student(program["id"], full_name="Ada Learner",
                          email="ada@example.edu")["id"]
    )
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    eve = fx.create_evaluator(full_name="Eve Reader", email="eve@example.edu",
                              certification_level="SENIOR")
    ivan = fx.create_evaluator(full_name="Ivan Reader", email="ivan@example.edu",
                               certification_level="ASSOCIATE")
    assert eve["status"] == "CERTIFIED"
    assert ivan["status"] == "CERTIFIED"
    A.assert_number_equals(eve["irr_agreement_rate_pct"], 100.00,
                           "irr_agreement_rate_pct")

    attempt = fx.submit_attempt(
        fx.open_attempt(student["id"], first["id"])["id"], student["id"],
        artifact_hash="sha256:a1",
    )
    return {"program": program, "first": first, "second": second,
            "student": student, "term": term, "eve": eve, "ivan": ivan,
            "attempt": attempt}


def _one_disagreeing_pair(ctx):
    """Sixty against ninety: a thirty-point gap on a five-point tolerance."""
    low = fx.record_score(ctx["attempt"]["id"], ctx["eve"]["id"],
                          [dimension_score("D1", 60)])
    high = fx.record_score(ctx["attempt"]["id"], ctx["ivan"]["id"],
                           [dimension_score("D1", 90)])
    return low, high


def test_a_thirty_point_gap_on_a_five_point_tolerance_sends_the_attempt_to_adjudication():
    """Both readers are recorded in their own slots, and the provisional figure the
    first one produced is wiped rather than kept.

    PRD: "A difference strictly greater than the tolerance is disagreement, and the
    attempt moves from `UNDER_REVIEW` to `ADJUDICATION`; `final_score_pct` is cleared
    back to null, `is_provisional_score` is set to false, and `score_variant` is
    cleared to null."

    Design: Corner/cross_cutting_layers/one_disagreeing_pair_demotes_both_readers_at_the_rate_floor
    """
    ctx = _two_readers_on_two_two_reader_rubrics()

    low, high = _one_disagreeing_pair(ctx)
    A.assert_number_equals(low["weighted_score_pct"], 60.00, "weighted_score_pct")
    assert low["reader_ordinal"] == 1
    A.assert_number_equals(high["weighted_score_pct"], 90.00, "weighted_score_pct")
    assert high["reader_ordinal"] == 2

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "ADJUDICATION"
    assert attempt["final_score_pct"] is None
    assert attempt["score_variant"] is None
    assert attempt["is_provisional_score"] is False
    assert attempt["scores_received_count"] == 2


def test_the_single_disagreeing_pair_demotes_both_readers_and_not_just_the_outlier():
    """One pair is enough to reach a minimum sample of one, and a rate of 0.00 is
    strictly below the 50.00 floor for each of them, so both fall to PROVISIONAL with
    the demotion instant on the record.

    PRD: "Demotion applies to a `CERTIFIED` evaluator when **both** of two conditions
    hold: `paired_review_count` has reached the program's `irr_min_paired_reviews`,
    and `irr_agreement_rate_pct` is strictly below the program's
    `irr_suspend_rate_pct`."

    Design: Corner/cross_cutting_layers/one_disagreeing_pair_demotes_both_readers_at_the_rate_floor
    """
    ctx = _two_readers_on_two_two_reader_rubrics()
    _one_disagreeing_pair(ctx)

    for reader in ("eve", "ivan"):
        evaluator = fx.refresh_evaluator(ctx[reader]["id"])
        assert evaluator["paired_review_count"] == 1
        assert evaluator["agreeing_review_count"] == 0
        A.assert_number_equals(evaluator["irr_agreement_rate_pct"], 0.00,
                               "irr_agreement_rate_pct")
        assert evaluator["status"] == "PROVISIONAL"
        A.assert_instant_equals(evaluator["demoted_at_utc"], BASE_CLOCK_UTC,
                                "demoted_at_utc")


def test_a_second_pair_exactly_at_the_tolerance_agrees_and_lifts_the_rate_to_the_floor():
    """A gap of exactly five is agreement, so the pair resolves as a mean and the
    rate rises to 50.00 — which is not strictly below the floor, so nothing further
    happens and the original demotion instant is left untouched.

    PRD: "A difference less than or equal to the tolerance is agreement, and the
    variant is `TWO_READER_MEAN`: add the two figures, divide by two, and round half
    up to two decimals."

    Design: Corner/cross_cutting_layers/one_disagreeing_pair_demotes_both_readers_at_the_rate_floor
    """
    ctx = _two_readers_on_two_two_reader_rubrics()
    _one_disagreeing_pair(ctx)
    demoted_at = fx.refresh_evaluator(ctx["eve"]["id"])["demoted_at_utc"]

    second = fx.submit_attempt(
        fx.open_attempt(ctx["student"]["id"], ctx["second"]["id"])["id"],
        ctx["student"]["id"], artifact_hash="sha256:a2",
    )
    A.assert_number_equals(
        fx.record_score(second["id"], ctx["eve"]["id"],
                        [dimension_score("D1", 85)])["weighted_score_pct"],
        85.00, "weighted_score_pct",
    )
    A.assert_number_equals(
        fx.record_score(second["id"], ctx["ivan"]["id"],
                        [dimension_score("D1", 90)])["weighted_score_pct"],
        90.00, "weighted_score_pct",
    )

    resolved = fx.refresh_attempt(second["id"])
    assert resolved["status"] == "SCORED_MASTERED"
    A.assert_number_equals(resolved["final_score_pct"], 87.50, "final_score_pct")
    assert resolved["score_variant"] == "TWO_READER_MEAN"

    eve = fx.refresh_evaluator(ctx["eve"]["id"])
    assert eve["paired_review_count"] == 2
    assert eve["agreeing_review_count"] == 1
    A.assert_number_equals(eve["irr_agreement_rate_pct"], 50.00,
                           "irr_agreement_rate_pct")
    assert eve["status"] == "PROVISIONAL"
    A.assert_instant_equals(eve["demoted_at_utc"], demoted_at, "demoted_at_utc")


def test_a_single_scoring_call_lands_the_attempt_and_the_student_derivations_at_once():
    """Before the score the summary is all zeros; the one call that resolves the
    attempt also settles the student's unit totals and cumulative equivalency, with
    no second request and no delay.

    PRD: "When a single request causes a chain of consequences, every consequence
    lands inside that same request, and a caller who reads any affected row
    immediately afterwards sees the settled result."

    Design: Corner/consistency_model/cross_aggregate_derivations_are_visible_in_the_next_read
    """
    ctx = fx.attempt_under_review()
    before = fx.progress_summary(ctx["student"]["id"])
    assert before["mastered_unit_total"] == 0
    A.assert_number_equals(before["cumulative_credit_equivalency"], 0.0,
                           "cumulative_credit_equivalency")

    score = fx.record_score(ctx["attempt"]["id"], ctx["evaluator"]["id"],
                            [dimension_score("D1", 90)])
    A.assert_number_equals(score["weighted_score_pct"], 90.00,
                           "weighted_score_pct")

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "SCORED_MASTERED"
    A.assert_number_equals(attempt["final_score_pct"], 90.00, "final_score_pct")
    assert attempt["is_provisional_score"] is False
    A.assert_instant_equals(attempt["scored_at_utc"], BASE_CLOCK_UTC,
                            "scored_at_utc")
    A.assert_instant_equals(attempt["mastered_at_utc"], BASE_CLOCK_UTC,
                            "mastered_at_utc")

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 4
    assert student["mastered_competency_count"] == 1
    A.assert_number_equals(student["cumulative_credit_equivalency"], 1.3,
                           "cumulative_credit_equivalency")


def test_the_term_the_summary_and_the_competency_all_read_settled_in_the_same_breath():
    """Three further aggregates the scoring request never named — the term's unit and
    equivalency figures, the computed summary, and the competency's mastery count —
    are all recomputed from their source rows by the time the next read arrives.

    PRD: "Derived roll-ups are always recomputed from their source rows and never
    patched incrementally."

    Design: Corner/consistency_model/cross_aggregate_derivations_are_visible_in_the_next_read
    """
    ctx = fx.attempt_under_review()
    fx.record_score(ctx["attempt"]["id"], ctx["evaluator"]["id"],
                    [dimension_score("D1", 90)])

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["units_mastered_in_term"] == 4
    assert term["credit_equivalency_earned"] == 1
    assert term["attempts_used"] == 1

    summary = fx.progress_summary(ctx["student"]["id"])
    A.assert_progress_summary_shape(summary)
    assert summary["mastered_unit_total"] == 4
    assert summary["mastered_competency_count"] == 1
    A.assert_number_equals(summary["cumulative_credit_equivalency"], 1.3,
                           "cumulative_credit_equivalency")
    A.assert_number_equals(summary["aid_credit_equivalency_sum"], 1,
                           "aid_credit_equivalency_sum")
    A.assert_credit_equivalency_variance(summary)

    assert fx.refresh_competency(ctx["competency"]["id"])["mastered_by_student_count"] == 1
