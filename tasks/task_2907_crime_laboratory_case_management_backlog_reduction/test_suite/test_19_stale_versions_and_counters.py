"""Two writes that supersede something the client may not have observed, and one counter whose reset
is a property of the run rather than of the standing it drives.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_STALE_CASE_VERSION,
    ERR_STALE_EXAM_REQUEST_VERSION,
)
from test_helpers.assertions import (
    assert_absent,
    assert_fields,
    assert_list_meta,
    assert_workload,
)
from test_helpers.factories import (
    assignment_payload,
    capa_decision_payload,
    closure_payload,
    priority_override_payload,
    root_cause_payload,
    score_payload,
)
from test_helpers.fixtures import (
    accept_case,
    assign_proficiency_test,
    assign_request,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    set_clock,
    submit_case,
    submit_proficiency_test,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
)


def test_an_override_must_carry_the_version_the_intake_already_moved(api):
    """Acceptance bumps the case version behind the director's back, so the version seen at submission
    is already stale and the override carrying it is refused with nothing written. The re-read version
    lands the override, bumps the version again, and leaves the intake score alone — so the superseding
    override has to re-read once more rather than reuse the value it just sent.

    PRD §2.7: "Recording a priority override on a case requires `expected_case_version` in the request
    body, carrying the client's last observed `version` of that `Case`. A mismatch with the case's
    current `version` is refused with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on
    every mutation, and `version`, a system-managed integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of that row."

    PRD §3.1: "Each override replaces both fields outright and re-derives `priority_class` with the
    override winning; the `priority_score` is deliberately left untouched, and the case's open
    examination requests are simply re-weighted in the backlog index the next time it is read."

    Design: Corner/cross_cutting_complexity_layers/priority_override_with_a_stale_case_version_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0511",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed swab",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accepted = accept_case(api, case["id"])
    assert accepted["version"] > case["version"], (
        "Accepting the submission is a mutation of the case row"
    )

    validate_error(
        api.override_case_priority(
            case["id"],
            priority_override_payload(
                "P1_STATUTORY",
                case["version"],
                priority_override_reason="District attorney trial setting",
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_STALE_CASE_VERSION,
        412,
    )
    untouched = validate_success(api.get_case(case["id"], DIRECTOR_HEADERS))
    assert_absent(untouched, "priority_override_class", "priority_override_reason")
    assert_fields(untouched, version=accepted["version"])

    overridden = validate_success(
        api.override_case_priority(
            case["id"],
            priority_override_payload(
                "P1_STATUTORY",
                accepted["version"],
                priority_override_reason="District attorney trial setting",
            ),
            DIRECTOR_HEADERS,
        )
    )
    assert_fields(
        overridden,
        priority_override_class="P1_STATUTORY",
        priority_class="P1_STATUTORY",
        priority_score=4.00,
        version=accepted["version"] + 1,
    )

    validate_error(
        api.override_case_priority(
            case["id"],
            priority_override_payload(
                "P3_ROUTINE",
                accepted["version"],
                priority_override_reason="Trial continued; returned to routine",
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_STALE_CASE_VERSION,
        412,
    )
    assert_fields(
        validate_success(api.get_case(case["id"], DIRECTOR_HEADERS)),
        priority_override_class="P1_STATUTORY",
    )

    superseding = validate_success(
        api.override_case_priority(
            case["id"],
            priority_override_payload(
                "P3_ROUTINE",
                overridden["version"],
                priority_override_reason="Trial continued; returned to routine",
            ),
            DIRECTOR_HEADERS,
        )
    )
    assert_fields(
        superseding,
        priority_override_class="P3_ROUTINE",
        priority_override_reason="Trial continued; returned to routine",
        priority_class="P3_ROUTINE",
        priority_score=4.00,
    )


def test_a_reassignment_must_carry_the_version_the_first_assignment_moved(api):
    """A writer working from the version it saw before anyone held the request would displace a holder
    it never observed, so the stale reassignment is refused and the incumbent keeps their active row and
    their committed hours. The re-read version performs the supersede, moving the four hours from one
    examiner to the other and pointing the displaced row at its replacement.

    PRD §2.7: "If the value does not equal the request's current `version`, the write is refused with
    `ERR_STALE_EXAM_REQUEST_VERSION` (HTTP 412) and nothing is created."

    PRD §3.4: "On success the incumbent's `ACTIVE` assignment moves to `SUPERSEDED` with `closed_at_utc`
    stamped and `superseded_by_assignment_id` pointing at the newly created row, and the outgoing
    examiner's `assigned_casework_hours` is decreased by exactly that superseded assignment's
    snapshotted `estimated_hours` — not by the request's current estimate."

    PRD §3.4: "The incoming examiner receives a fresh `ACTIVE` assignment and their
    `assigned_casework_hours` rises by the request's `estimated_hours`."

    Design: Corner/cross_cutting_complexity_layers/reassignment_with_a_stale_request_version_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    incumbent = register_analyst(
        api,
        full_name="OCC Incumbent",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    successor = register_analyst(
        api,
        full_name="OCC Successor",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Touch DNA Recovery",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        max_items_per_request=6,
        accreditation_scope_code="BIO-TDR-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0512",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed swab",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    first_assignment = assign_request(
        api,
        request["id"],
        incumbent["id"],
        expected_version=request["version"],
        assignment_reason="MANUAL",
    )

    validate_error(
        api.create_assignment(
            request["id"],
            assignment_payload(
                successor["id"], request["version"], assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_STALE_EXAM_REQUEST_VERSION,
        412,
    )
    after_refusal = read_request(api, request["id"])
    assert_fields(after_refusal, assigned_analyst_id=incumbent["id"])
    held = validate_success(
        api.get_assignment(first_assignment["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(held, status="ACTIVE")
    assert_absent(held, "superseded_by_assignment_id")
    assert after_refusal["version"] != request["version"], (
        "The first assignment had already moved the request version"
    )

    second_assignment = validate_success(
        api.create_assignment(
            request["id"],
            assignment_payload(
                successor["id"], after_refusal["version"], assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        second_assignment,
        analyst_id=successor["id"],
        status="ACTIVE",
        estimated_hours=4.00,
    )
    assert_fields(
        validate_success(
            api.get_assignment(first_assignment["id"], CASE_MANAGER_HEADERS)
        ),
        status="SUPERSEDED",
        superseded_by_assignment_id=second_assignment["id"],
    )

    assert_workload(
        validate_success(
            api.get_analyst_workload(incumbent["id"], CASE_MANAGER_HEADERS)
        ),
        assigned_casework_hours=0.00,
        active_assignment_count=0,
    )
    assert_workload(
        validate_success(
            api.get_analyst_workload(successor["id"], CASE_MANAGER_HEADERS)
        ),
        assigned_casework_hours=4.00,
        projected_utilization_pct=12.50,
    )
    assert_fields(
        read_request(api, request["id"]),
        assigned_analyst_id=successor["id"],
        status="ASSIGNED",
    )


def test_a_passing_round_resets_the_run_so_the_next_failure_does_not_suspend(api):
    """The suspension trigger counts consecutive failures, not failures. A failure, a closed finding, a
    pass and a second failure leave the examiner on a fresh probation with a run of exactly one and no
    suspension instant, even though two rounds have now been failed in total.

    PRD §3.8: "First the failure counter moves: a `FAIL` increases `consecutive_pt_failures` by 1, a
    `PASS` resets it to 0, and an `INCONCLUSIVE` leaves it exactly as it was — an inconclusive result
    neither punishes nor absolves."

    PRD §3.8: "An examiner who was `QUALIFIED` and has just failed moves to `PROBATION`,
    `probation_entered_at_utc` is stamped, and the probation release of §2.10 sheds their
    priority-restricted work."

    PRD §3.8: "An examiner already on `PROBATION` whose `consecutive_pt_failures` has reached 2 moves to
    `SUSPENDED`, `suspended_at_utc` is stamped, and the full release sheds all of their open work."

    PRD §3.8: "Closure can also restore an examiner: when the finding names an `analyst_id`, that
    examiner is on `PROBATION`, and no other nonconformance against them remains with `status` `OPEN`,
    `ROOT_CAUSE_SUBMITTED` or `CAPA_APPROVED`, they move `PROBATION` → `QUALIFIED`,
    `consecutive_pt_failures` resets to 0 and `probation_entered_at_utc` is cleared."

    PRD §3.8: "Otherwise a `score_pct` of at least 90.00 is `PASS`, a `score_pct` of at least 70.00 is
    `INCONCLUSIVE`, and anything below 70.00 is `FAIL`."

    Design: Corner/cross_cutting_complexity_layers/consecutive_failure_counter_resets_on_a_pass_so_the_third_failure_does_not_suspend
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Counter Reset Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Quantitation Proficiency Method",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        max_items_per_request=6,
        accreditation_scope_code="BIO-QPM-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )

    def _sit(cycle: str, due_utc: str, score_pct: float):
        test = assign_proficiency_test(
            api,
            analyst_id=examiner["id"],
            method_id=method["id"],
            test_cycle=cycle,
            due_utc=due_utc,
        )
        submit_proficiency_test(api, test["id"], examiner["id"])
        return validate_success(
            api.score_proficiency_test(
                test["id"], score_payload(score_pct), QUALITY_MANAGER_HEADERS
            )
        )

    def _standing():
        return validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS))

    first_round = _sit("2026-C1", "2026-08-15T00:00:00Z", 50.00)
    assert_fields(first_round, result="FAIL")
    assert_fields(
        _standing(), qualification_state="PROBATION", consecutive_pt_failures=1
    )

    findings, meta = validate_paginated(
        api.list_nonconformances(
            QUALITY_MANAGER_HEADERS,
            {"analyst_id": examiner["id"], "source": "PT_FAILURE"},
        )
    )
    assert_list_meta(meta, expected_total=1)
    finding_id = findings[0]["id"]

    validate_success(
        api.submit_root_cause(
            finding_id,
            root_cause_payload(
                root_cause_category="TRAINING",
                corrective_action_plan="Refresher on quantitation calibration",
            ),
            CASE_MANAGER_HEADERS,
        )
    )
    validate_success(
        api.capa_decision(
            finding_id,
            capa_decision_payload("APPROVE", "Plan accepted"),
            QUALITY_MANAGER_HEADERS,
        )
    )
    closed = validate_success(
        api.verify_close_nonconformance(
            finding_id,
            closure_payload("Refresher completed and witnessed"),
            QUALITY_MANAGER_HEADERS,
        )
    )
    assert_fields(closed, status="CLOSED")
    restored = _standing()
    assert_fields(restored, qualification_state="QUALIFIED")
    assert_absent(restored, "probation_entered_at_utc")

    second_round = _sit("2026-C2", "2026-08-20T00:00:00Z", 90.00)
    assert_fields(second_round, result="PASS")
    assert_fields(
        _standing(), qualification_state="QUALIFIED", consecutive_pt_failures=0
    )

    third_round = _sit("2026-C3", "2026-08-25T00:00:00Z", 60.00)
    assert_fields(third_round, result="FAIL", late_submission=False)
    final = _standing()
    assert_fields(
        final, qualification_state="PROBATION", consecutive_pt_failures=1
    )
    assert_absent(final, "suspended_at_utc")
