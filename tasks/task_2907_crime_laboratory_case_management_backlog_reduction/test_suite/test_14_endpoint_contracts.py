"""Endpoint contracts read end to end: the proficiency-test action chain in its declared order, the
junction row that needs both parents and a free cycle slot, and the capacity edit whose only effect
is on the next derived read.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_DUPLICATE_RESOURCE,
    ERR_METHOD_NOT_FOUND,
    ERR_PT_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_absent,
    assert_fields,
    assert_list_meta,
    assert_workload,
)
from test_helpers.factories import proficiency_test_payload, score_payload
from test_helpers.fixtures import (
    accept_case,
    assign_proficiency_test,
    assign_request,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    score_proficiency_test,
    set_clock,
    submit_case,
    submit_proficiency_test,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
)

# A syntactically valid identifier that names no persisted method.
UNPERSISTED_METHOD_ID = "00000000-0000-4000-8000-0000000000ff"


def test_a_proficiency_test_cannot_be_scored_before_it_has_been_sat(api):
    """The same 95.00 body is refused while the test is still ASSIGNED and accepted once the examiner
    has submitted, and because the submission landed well before the deadline the mark is graded on
    its own merits.

    PRD §3.8: "Submission carries no body, requires `status` `ASSIGNED` else `ERR_PT_INVALID_STATE`,
    and requires the `X-User-ID` of the caller to equal the test's `analyst_id` else
    `ERR_ANALYST_IDENTITY_MISMATCH`."

    PRD §3.8: "Scoring is the `QualityManager`'s act, admissible only from `SUBMITTED` else
    `ERR_PT_INVALID_STATE`."

    PRD §3.8: "It advances the test to `SUBMITTED`, stamps `submitted_at_utc` from the logical clock,
    and sets `late_submission` to true when that instant is strictly after `due_utc` — a submission
    landing exactly on `due_utc` is on time."

    PRD §3.8: "Otherwise a `score_pct` of at least 90.00 is `PASS`, a `score_pct` of at least 70.00
    is `INCONCLUSIVE`, and anything below 70.00 is `FAIL`."

    Design: Corner/endpoints/proficiency_test_action_endpoints_enforce_their_declared_order
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Proficiency Subject",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    test = assign_proficiency_test(
        api,
        analyst_id=examiner["id"],
        method_id=method["id"],
        test_cycle="2026-C1",
        due_utc="2026-08-15T00:00:00Z",
    )
    assert_fields(test, status="ASSIGNED", late_submission=False)

    validate_error(
        api.score_proficiency_test(
            test["id"], score_payload(95.00), QUALITY_MANAGER_HEADERS
        ),
        ERR_PT_INVALID_STATE,
        409,
    )
    untouched = validate_success(
        api.get_proficiency_test(test["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(untouched, status="ASSIGNED")
    assert_absent(untouched, "submitted_at_utc", "result", "score_pct", "scored_at_utc")

    submitted = submit_proficiency_test(api, test["id"], examiner["id"])
    assert_fields(
        submitted,
        status="SUBMITTED",
        submitted_at_utc="2026-08-01T00:00:00Z",
        late_submission=False,
    )

    scored = score_proficiency_test(api, test["id"], 95.00)
    assert_fields(
        scored,
        status="SCORED",
        result="PASS",
        score_pct=95.00,
        scored_at_utc="2026-08-01T00:00:00Z",
        late_submission=False,
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        qualification_state="QUALIFIED",
        consecutive_pt_failures=0,
    )


def test_a_proficiency_test_needs_both_parents_and_a_free_cycle_slot(api):
    """An unresolvable method is a not-found refusal before any row is written; once the round exists
    the examiner-method-cycle triple is taken, and only a different round is admitted.

    PRD §3.8: "The triple of `analyst_id`, `method_id` and `test_cycle` must be unique; a second test
    for the same examiner, method and cycle is `ERR_DUPLICATE_RESOURCE`."

    PRD §3.8: "A new test has `status` `ASSIGNED`, `late_submission` false and no `submitted_at_utc`,
    `score_pct`, `result` or `scored_at_utc`."

    PRD §2.8: "**Body foreign keys.** Every identifier carried in the body resolves to an existing
    row of its declared entity, else that entity's not-found code (404). Body foreign keys are
    resolved after the schema check so that a syntactically invalid identifier yields 400 rather than
    404."

    Design: Corner/endpoints/proficiency_test_creation_links_both_parents_and_is_unique_per_cycle
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Junction Subject",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="STR Autosomal Typing",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        is_consumptive=True,
        accreditation_scope_code="BIO-STR-01",
        validation_study_item_count=24,
        precision_cv_pct=2.00,
    )

    validate_error(
        api.create_proficiency_test(
            proficiency_test_payload(
                examiner["id"],
                UNPERSISTED_METHOD_ID,
                test_cycle="2026-C1",
                due_utc="2026-08-15T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_METHOD_NOT_FOUND,
        404,
    )

    first = validate_success(
        api.create_proficiency_test(
            proficiency_test_payload(
                examiner["id"],
                method["id"],
                test_cycle="2026-C1",
                due_utc="2026-08-15T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        first,
        analyst_id=examiner["id"],
        method_id=method["id"],
        status="ASSIGNED",
        test_cycle="2026-C1",
        due_utc="2026-08-15T00:00:00Z",
    )

    validate_error(
        api.create_proficiency_test(
            proficiency_test_payload(
                examiner["id"],
                method["id"],
                test_cycle="2026-C1",
                due_utc="2026-08-20T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_DUPLICATE_RESOURCE,
        409,
    )
    assert_fields(
        validate_success(api.get_proficiency_test(first["id"], QUALITY_MANAGER_HEADERS)),
        due_utc="2026-08-15T00:00:00Z",
    )

    second = validate_success(
        api.create_proficiency_test(
            proficiency_test_payload(
                examiner["id"],
                method["id"],
                test_cycle="2026-C2",
                due_utc="2026-09-15T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(second, test_cycle="2026-C2", status="ASSIGNED")

    _rows, meta = validate_paginated(
        api.list_proficiency_tests(
            QUALITY_MANAGER_HEADERS,
            {"analyst_id": examiner["id"], "method_id": method["id"]},
        )
    )
    assert_list_meta(meta, expected_total=2)


def test_lowering_an_examiners_capacity_moves_the_read_and_not_the_bench(api):
    """Halving the contracted week takes available hours from 32.00 to 16.00 and doubles the
    utilisation reading on an unchanged 8.00-hour commitment, while the assignment itself keeps both
    its ACTIVE status and its snapshotted estimate.

    PRD §3.4: "The director may later adjust an examiner's `weekly_capacity_hours`,
    `training_hours_per_week`, `competency_level`, `disciplines` set or `employment_status`. Such an
    adjustment re-derives the availability and utilisation figures on the next read, but it
    deliberately has no retroactive force: no existing assignment is released by it, and no
    snapshotted `estimated_hours` is re-priced by it."

    PRD §3.4: "An examiner's available hours are their `weekly_capacity_hours` minus their
    `training_hours_per_week`, floored at 0.00 and rounded half up to 2 decimal places — training
    time is carved out of capacity before casework is considered."

    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on
    every mutation, and `version`, a system-managed integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/analyst_patch_lowers_capacity_and_the_workload_read_follows
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Capacity Patch Subject",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="STR Autosomal Typing",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        is_consumptive=True,
        accreditation_scope_code="BIO-STR-01",
        validation_study_item_count=24,
        precision_cv_pct=2.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0401",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed swab box",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=2)
    assignment = assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )

    assert_workload(
        validate_success(
            api.get_analyst_workload(examiner["id"], QUALITY_MANAGER_HEADERS)
        ),
        available_hours=32.00,
        projected_utilization_pct=25.00,
    )
    before = validate_success(api.get_analyst(examiner["id"], DIRECTOR_HEADERS))

    patched = validate_success(
        api.update_analyst(
            examiner["id"], {"weekly_capacity_hours": 24.00}, DIRECTOR_HEADERS
        )
    )
    assert_fields(
        patched,
        weekly_capacity_hours=24.00,
        training_hours_per_week=8.00,
        competency_level=4,
        version=before["version"] + 1,
    )

    assert_workload(
        validate_success(
            api.get_analyst_workload(examiner["id"], QUALITY_MANAGER_HEADERS)
        ),
        available_hours=16.00,
        projected_load_hours=8.00,
        projected_utilization_pct=50.00,
        casework_training_ratio=1.00,
        active_assignment_count=1,
        assigned_casework_hours=8.00,
    )
    assert_fields(
        validate_success(api.get_assignment(assignment["id"], CASE_MANAGER_HEADERS)),
        status="ACTIVE",
        estimated_hours=8.00,
    )
    assert_fields(read_request(api, request["id"]), status="ASSIGNED")
