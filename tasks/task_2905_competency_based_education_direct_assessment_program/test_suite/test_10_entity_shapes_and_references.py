"""Stored shape of each entity: server-minted system fields, declared defaults,
computed fields that start null, enum and window constraints, and foreign-key
resolution on a flat collection topology.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BASE_CLOCK_UTC,
    PHANTOM_UUID,
    PROGRAM_POLICY_DEFAULTS,
    SINGLE_DIMENSION_RUBRIC,
)
from test_helpers.factories import (
    create_blueprint_payload,
    create_competency_payload,
    create_program_payload,
    create_sap_review_payload,
    create_student_payload,
    create_subscription_term_payload,
)


def test_registering_a_program_mints_the_system_fields_and_returns_201():
    """Only code and title are supplied; the id, the two instants, version 1, the
    DRAFT status and the zero competency count all come from the server.

    PRD: "Operations that create a new resource return HTTP 201; every other
    successful operation, including all reads, all state transitions and all
    sub-resource recording actions, returns HTTP 200."

    Design: Corner/entities/program_create_returns_201_with_system_fields
    """
    fx.set_clock(BASE_CLOCK_UTC)

    program = validate_success(
        api_client.create_program(create_program_payload(), fx.REGISTRAR), 201
    )
    A.assert_program(program)
    A.assert_common_fields(program, expected_version=1)
    assert program["status"] == "DRAFT"
    assert program["competency_count"] == 0
    assert program["code"] == "CBE-BSIT"
    assert program["title"] == "BS Information Technology"
    assert program["published_at_utc"] is None
    A.assert_instant_equals(program["created_at"], BASE_CLOCK_UTC, "created_at")


def test_every_omitted_program_policy_field_materialises_at_its_declared_default():
    """Fourteen optional policy inputs are omitted, so each must come back carrying
    its documented default rather than null.

    PRD: "All of them are optional at registration and fall back to the documented
    default."

    Design: Corner/entities/program_create_omitted_policy_fields_take_declared_defaults
    """
    fx.set_clock(BASE_CLOCK_UTC)

    program = fx.create_program(code="CBE-DEF", title="Defaults Program")
    for field, expected in PROGRAM_POLICY_DEFAULTS.items():
        A.assert_number_equals(program[field], expected, field)
    assert program["sap_min_units_per_term"] == 12
    assert program["required_unit_total"] == 120
    assert program["irr_min_paired_reviews"] == 3
    assert program["attempt_cooloff_hours"] == 48
    assert program["attempts_before_endorsement"] == 3
    assert program["cadence_gate_overdue_days"] == 7
    assert program["blueprint_notice_days"] == 14
    assert program["aid_min_credit_equivalency"] == 1


def test_reading_a_competency_back_returns_the_inherited_threshold_and_no_rubric():
    """The competency supplied no threshold override, so the resolved figure is the
    program's, and the effective-rubric cache is null while no blueprint exists.

    PRD: "Either way the service publishes the resolved figure as
    `effective_mastery_threshold_pct`, which equals the competency's own
    `mastery_threshold_pct` when that is non-null and the owning program's
    `mastery_threshold_pct` otherwise."

    Design: Corner/entities/competency_get_returns_stored_row
    """
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    created = fx.create_competency(program["id"])

    response = api_client.get_competency(created["id"], fx.REGISTRAR)
    competency = validate_success(response, 200)
    A.assert_competency(competency)
    assert competency["code"] == "IT-101"
    A.assert_number_equals(competency["unit_value"], 4, "unit_value")
    assert competency["level"] == "FOUNDATION"
    assert competency["status"] == "ACTIVE"
    A.assert_number_equals(competency["effective_mastery_threshold_pct"], 80.00,
                           "effective_mastery_threshold_pct")
    assert competency["effective_blueprint_id"] is None
    assert competency["version"] == 1


def test_the_competency_list_filters_out_the_retired_row_and_pages_it():
    """Three competencies exist and one has been retired, so the ACTIVE filter
    reports two rows in code order, and a one-row page still reports the true total
    with more to come.

    PRD: "competencies are ordered by `code` ascending; assessment blueprints are
    ordered by `effective_from_utc` ascending with `created_at` ascending as the
    tie-break"

    Design: Corner/entities/competencies_list_filtered_by_program_and_status
    """
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program(code="CBE-LIST", title="Listing Program")
    fx.create_competency(program["id"], code="L-1", title="List One", unit_value=2,
                         level="FOUNDATION")
    fx.create_competency(program["id"], code="L-2", title="List Two", unit_value=2,
                         level="CORE")
    third = fx.create_competency(program["id"], code="L-3", title="List Three",
                                 unit_value=2, level="CAPSTONE")
    assert fx.retire_competency(third["id"])["status"] == "RETIRED"

    active = A.assert_page(
        api_client.list_competencies(
            fx.REGISTRAR, params={"program_id": program["id"], "status": "ACTIVE"}
        ),
        2, expected_count=2, expected_has_more=False,
    )
    assert [row["code"] for row in active] == ["L-1", "L-2"]

    first_page = A.assert_page(
        api_client.list_competencies(
            fx.REGISTRAR,
            params={"program_id": program["id"], "status": "ACTIVE",
                    "limit": 1, "offset": 0},
        ),
        2, expected_count=1, expected_has_more=True,
    )
    assert first_page[0]["code"] == "L-1"


def test_reading_a_student_that_never_existed_is_a_typed_404():
    """A syntactically valid identifier that no row carries yields the student
    collection's own not-found code inside the error envelope.

    PRD: "Path identifiers are resolved left to right, and each unresolved identifier
    yields the 404 error belonging to the entity that segment addresses:
    `ERR_PROGRAM_NOT_FOUND`, `ERR_COMPETENCY_NOT_FOUND`, `ERR_BLUEPRINT_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_TERM_NOT_FOUND`, `ERR_MENTOR_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`,
    `ERR_SCORE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SAP_REVIEW_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, and `ERR_TRANSCRIPT_NOT_FOUND`."

    Design: Corner/entities/student_get_unknown_id_returns_not_found
    """
    fx.set_clock(BASE_CLOCK_UTC)

    body = validate_error(
        api_client.get_student(PHANTOM_UUID, fx.REGISTRAR),
        ApiErrorId.ERR_STUDENT_NOT_FOUND.value, 404,
    )
    assert isinstance(body["message"], str) and body["message"]


def test_enrolling_without_an_email_is_a_shape_failure_and_writes_no_row():
    """The email is a required input with no default, so omitting it is refused at the
    body-shape gate and the collection stays empty.

    PRD: "Request-body shape: every required field is present, every enum field holds
    a declared value, integers are non-negative, percentages fall within 0.00 to
    100.00, ISO 8601 UTC instants parse, a term's `term_end_utc` is strictly after its
    `term_start_utc`, and the uniqueness constraints hold on a program's `code`, on a
    competency's `code` within its program, and on the `email` of a student, an
    evaluator, or a mentor — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/student_create_missing_email_returns_invalid_request
    """
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    fx.create_competency(program["id"])
    program = fx.publish_program(program["id"])

    payload = create_student_payload(program["id"])
    payload.pop("email")
    validate_error(api_client.create_student(payload, fx.REGISTRAR),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    A.assert_page(
        api_client.list_students(fx.REGISTRAR, params={"program_id": program["id"]}), 0
    )


def test_a_fresh_term_reports_zero_units_but_null_close_out_figures():
    """A zero in place of a null would falsely claim the term had already been closed
    with nothing attended, so the four close-out figures must be absent while the
    two roll-ups are genuinely zero.

    PRD: "Until a term is closed, `closed_effective_utc`, `attended_days`,
    `earned_pct`, `institutional_refund_cents`, and `net_institutional_charge_cents`
    are all null."

    Design: Corner/entities/term_create_computed_fields_start_null_and_zero
    """
    ctx = fx.base_chain(create_the_term=False)

    response = api_client.create_subscription_term(
        create_subscription_term_payload(ctx["student"]["id"]), fx.REGISTRAR
    )
    term = validate_success(response, 201)
    A.assert_subscription_term(term)
    assert term["status"] == "PENDING"
    assert term["units_mastered_in_term"] == 0
    assert term["credit_equivalency_earned"] == 0
    assert term["attended_days"] is None
    assert term["earned_pct"] is None
    assert term["institutional_refund_cents"] is None
    assert term["net_institutional_charge_cents"] is None
    assert term["closed_effective_utc"] is None
    A.assert_cents(term["tuition_cents"], 375000, "tuition_cents")


def test_registering_a_reader_mints_the_standing_and_the_empty_reliability_figures():
    """The client supplies three fields; the standing, the three counters, the
    empty-denominator reliability rate and the null demotion instant are all the
    server's to write.

    PRD: "A newly registered evaluator begins with `status` `CERTIFIED`,
    `irr_agreement_rate_pct` 100.00, `submitted_score_count`, `paired_review_count`
    and `agreeing_review_count` all zero, and `demoted_at_utc` null."

    Design: Corner/entities/evaluator_system_fields_are_server_minted
    """
    fx.set_clock(BASE_CLOCK_UTC)

    evaluator = validate_success(
        api_client.create_evaluator(
            {"full_name": "Reader One", "email": "r1@example.edu",
             "certification_level": "SENIOR"},
            fx.REGISTRAR,
        ),
        201,
    )
    A.assert_evaluator(evaluator)
    A.assert_common_fields(evaluator, expected_version=1)
    assert evaluator["status"] == "CERTIFIED"
    assert evaluator["submitted_score_count"] == 0
    assert evaluator["paired_review_count"] == 0
    assert evaluator["agreeing_review_count"] == 0
    A.assert_number_equals(evaluator["irr_agreement_rate_pct"], 100.00,
                           "irr_agreement_rate_pct")
    assert evaluator["demoted_at_utc"] is None
    assert evaluator["mentor_id"] is None


def test_a_level_outside_the_declared_three_is_refused_rather_than_stored():
    """MASTER is not one of the three declared map levels, so it is a body-shape
    failure and no competency row appears.

    PRD: "A competency is added to the map with a payload naming the owning
    `program_id`, a `code` that must be unique within that program, a `title`, a
    positive `unit_value` carrying two decimal places, and a `level` drawn from
    `FOUNDATION`, `CORE`, or `CAPSTONE`."

    Design: Corner/entities/competency_invalid_level_enum_rejected
    """
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()

    validate_error(
        api_client.create_competency(
            create_competency_payload(program["id"], code="IT-999",
                                      title="Bogus Level", level="MASTER"),
            fx.REGISTRAR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value, 400,
    )

    A.assert_page(
        api_client.list_competencies(fx.REGISTRAR,
                                     params={"program_id": program["id"]}), 0
    )


def test_a_zero_length_term_window_is_refused_before_any_row_exists():
    """An end bound equal to the start bound would make term_days zero and divide by
    zero in the close-out arithmetic, so it is refused at the body-shape gate.

    PRD: "The end bound must be strictly after the start bound."

    Design: Corner/entities/term_window_end_not_after_start_rejected
    """
    ctx = fx.base_chain(create_the_term=False)

    validate_error(
        api_client.create_subscription_term(
            create_subscription_term_payload(
                ctx["student"]["id"], term_end_utc=BASE_CLOCK_UTC
            ),
            fx.REGISTRAR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value, 400,
    )

    A.assert_page(
        api_client.list_subscription_terms(
            fx.REGISTRAR, params={"student_id": ctx["student"]["id"]}
        ),
        0,
    )


def test_a_progress_checkpoint_is_versionless_and_a_repeat_is_refused_not_edited():
    """The checkpoint row carries no version and no updated_at, and once the axis has
    reached its terminal value a second checkpoint is refused outright rather than
    rewriting the stored row.

    PRD: "A checkpoint against a student who is already dismissed is refused with
    `ERR_SAP_ALREADY_DISMISSED` and **no review row is written at all** — the
    append-only log records checkpoints that happened, not checkpoints that were
    refused."

    Design: Corner/entities/sap_review_is_immutable_and_versionless
    """
    ctx = fx.base_chain()

    review = validate_success(
        api_client.create_sap_review(
            create_sap_review_payload(ctx["student"]["id"], ctx["term"]["id"]),
            fx.REGISTRAR,
        ),
        201,
    )
    A.assert_sap_review(review)
    A.assert_number_equals(review["pace_pct"], 0.00, "pace_pct")
    assert review["pace_band"] == "FAIL"
    assert review["new_sap_status"] == "DISMISSED"

    stored = validate_success(api_client.get_sap_review(review["id"], fx.REGISTRAR), 200)
    A.assert_sap_review(stored)
    A.assert_number_equals(stored["pace_pct"], 0.00, "pace_pct")
    assert stored["new_sap_status"] == "DISMISSED"

    validate_error(
        api_client.create_sap_review(
            create_sap_review_payload(ctx["student"]["id"], ctx["term"]["id"]),
            fx.REGISTRAR,
        ),
        ApiErrorId.ERR_SAP_ALREADY_DISMISSED.value, 409,
    )
    A.assert_page(
        api_client.list_sap_reviews(fx.REGISTRAR,
                                    params={"student_id": ctx["student"]["id"]}),
        1,
    )


def test_opening_a_term_for_a_student_who_does_not_exist_cannot_orphan_a_row():
    """The student_id is a body foreign key, so an unresolvable value is a typed 404
    ahead of every window and lifecycle check.

    PRD: "Foreign keys arriving in a request body are subject to the same discipline,
    one level later in the precedence order. They are resolved in the order the fields
    are declared for that operation, and each unresolved reference yields the
    referenced entity's own 404 code"

    Design: Corner/entities/subscription_term_requires_existing_student_fk
    """
    fx.set_clock(BASE_CLOCK_UTC)

    validate_error(
        api_client.create_subscription_term(
            create_subscription_term_payload(PHANTOM_UUID), fx.REGISTRAR
        ),
        ApiErrorId.ERR_STUDENT_NOT_FOUND.value, 404,
    )

    A.assert_page(api_client.list_subscription_terms(fx.REGISTRAR), 0)


def test_publishing_a_rubric_against_an_unknown_competency_is_a_404_not_a_conflict():
    """The topology is flat, so cross-reference integrity is a body foreign-key check:
    it fires ahead of the concurrency token and the rubric-weight rules even though the
    quoted token is genuine.

    PRD: "The API is deliberately flat. Every entity is a peer collection addressed
    directly under the root — programs, competencies, assessment blueprints, students,
    subscription terms, mentors, mentor assignments, evaluators, assessment attempts,
    evaluator scores, integrity cases, satisfactory-academic-progress reviews, aid
    disbursements, and transcript records."

    Design: Corner/entities/blueprint_rejects_unknown_competency_reference
    """
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    real = fx.create_competency(program["id"])
    assert real["version"] == 1

    validate_error(
        api_client.create_blueprint(
            create_blueprint_payload(PHANTOM_UUID, real["version"],
                                     dimensions=SINGLE_DIMENSION_RUBRIC),
            fx.REGISTRAR,
        ),
        ApiErrorId.ERR_COMPETENCY_NOT_FOUND.value, 404,
    )

    A.assert_page(api_client.list_blueprints(fx.REGISTRAR), 0)
    assert fx.refresh_competency(real["id"])["effective_blueprint_id"] is None
