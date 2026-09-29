"""One call, several hops: a proficiency score that suspends an examiner and empties their
bench, and a peer disagreement that reaches across cases to strip only the statutory work.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_two_decimal_value,
)
from test_helpers.fixtures import (
    accept_case,
    assign_proficiency_test,
    assign_request,
    carry_to_tech_review,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    score_proficiency_test,
    set_clock,
    submit_case,
    submit_proficiency_test,
    technical_review,
)
from test_helpers.test_users import CASE_MANAGER_HEADERS, QUALITY_MANAGER_HEADERS


def _chemistry_examiner(api, full_name="Ada Nakamura"):
    return register_analyst(
        api,
        full_name=full_name,
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )


def _gcms_method(api):
    return create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
    )


def _examiner_suspended_by_a_second_failing_mark(api):
    """A routine-class request held by an examiner who fails a first proficiency test — which
    spares that routine work — and then fails a second, which does not.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = _chemistry_examiner(api)
    method = _gcms_method(api)
    case = submit_case(
        api,
        agency_case_number="D-2026-0707",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=3)
    assignment = assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )

    first = assign_proficiency_test(
        api,
        analyst_id=examiner["id"],
        method_id=method["id"],
        test_cycle="2026-Q3",
        due_utc="2026-09-01T00:00:00Z",
    )
    submit_proficiency_test(api, first["id"], examiner["id"])
    score_proficiency_test(api, first["id"], 50.00)

    second = assign_proficiency_test(
        api,
        analyst_id=examiner["id"],
        method_id=method["id"],
        test_cycle="2026-Q4",
        due_utc="2026-09-01T00:00:00Z",
    )
    submit_proficiency_test(api, second["id"], examiner["id"])
    score_proficiency_test(api, second["id"], 40.00)

    return {
        "examiner": examiner,
        "method": method,
        "case": case,
        "request": request,
        "assignment": assignment,
        "first_test": first,
        "second_test": second,
    }


def test_the_second_failing_mark_suspends_and_takes_back_the_routine_bench_work(api):
    """Crossing two consecutive failures suspends the examiner, and the release that follows
    a suspension applies no queue-class filter, so the routine assignment the first failure
    left alone is handed back to the queue and the case falls to awaiting assignment.

    PRD §2.10: "When an examiner is suspended or decertified, the identical release runs with
    no queue-class filter at all: every `ACTIVE` assignment they hold is released, every
    affected request falls back to `QUEUED` with its `assigned_analyst_id` cleared, the hours
    come off `assigned_casework_hours`, and the case rollup runs per affected case."

    Design: Difficulty/transitive_cascade/second_pt_failure_suspends_analyst_releases_hours_and_requeues_case
    """
    state = _examiner_suspended_by_a_second_failing_mark(api)

    second = validate_success(
        api.get_proficiency_test(state["second_test"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(second, result="FAIL", status="SCORED")

    examiner = validate_success(
        api.get_analyst(state["examiner"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(
        examiner, consecutive_pt_failures=2, qualification_state="SUSPENDED"
    )
    assert_instant_equals(
        examiner["suspended_at_utc"], "2026-08-01T00:00:00Z", "suspended_at_utc"
    )
    assert_two_decimal_value(
        examiner["assigned_casework_hours"], 0.00, "assigned_casework_hours"
    )

    assignment = validate_success(
        api.get_assignment(state["assignment"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(assignment, status="RELEASED")
    assert_instant_equals(
        assignment["closed_at_utc"], "2026-08-01T00:00:00Z", "closed_at_utc"
    )
    assert assignment["superseded_by_assignment_id"] is None, (
        "A release is not a supersede, so no supersede pointer is written"
    )

    request = read_request(api, state["request"]["id"])
    assert_fields(request, status="QUEUED", estimated_hours=6.00)
    assert request["assigned_analyst_id"] is None, (
        "The released request must carry no examiner"
    )

    case = validate_success(api.get_case(state["case"]["id"], CASE_MANAGER_HEADERS))
    assert_fields(
        case, workflow_status="AWAITING_ASSIGNMENT", open_examination_request_count=1
    )


def test_each_failing_mark_files_its_own_major_finding(api):
    """Both failures are documented, not just the one that suspended: two MAJOR findings
    stand against the examiner, each due thirty days from the instant it was opened, and the
    first test still reads as a failure taken on time.

    PRD §3.8: "A `FAIL` creates a nonconformance with `source` `PT_FAILURE` and `severity`
    `MAJOR` naming that `analyst_id`, alongside the counter and qualification movements
    above."

    Design: Difficulty/transitive_cascade/second_pt_failure_suspends_analyst_releases_hours_and_requeues_case
    """
    state = _examiner_suspended_by_a_second_failing_mark(api)

    first = validate_success(
        api.get_proficiency_test(state["first_test"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(first, result="FAIL", late_submission=False)

    findings, meta = validate_paginated(
        api.list_nonconformances(
            QUALITY_MANAGER_HEADERS,
            {"analyst_id": state["examiner"]["id"], "source": "PT_FAILURE"},
        )
    )
    assert_list_meta(meta, expected_total=2)
    for finding in findings:
        assert_fields(finding, severity="MAJOR")
        assert_instant_equals(finding["due_utc"], "2026-08-31T00:00:00Z", "due_utc")


def _disagreement_that_puts_the_examiner_on_probation(api):
    """One examiner holds a routine file that has reached technical review and a statutory
    file still on the bench; the peer reviewer then disagrees with the routine file.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = _chemistry_examiner(api)
    reviewer = _chemistry_examiner(api, full_name="Bo Ferreira")
    method = _gcms_method(api)

    routine_case = submit_case(
        api,
        agency_case_number="D-2026-0808",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    routine_item = log_evidence(
        api, routine_case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, routine_case["id"])
    routine_request = raise_request(
        api, routine_case["id"], routine_item["id"], method["id"], item_count=3
    )
    routine_assignment = assign_request(
        api,
        routine_request["id"],
        examiner["id"],
        expected_version=routine_request["version"],
    )
    carry_to_tech_review(api, routine_request["id"], examiner["id"], actual_hours=6.00)

    statutory_case = submit_case(
        api,
        agency_case_number="H-2026-0809",
        submitting_agency="METRO PD",
        offense_category="HOMICIDE",
        suspect_in_custody=True,
        statutory_deadline_utc="2026-08-20T00:00:00Z",
    )
    statutory_item = log_evidence(
        api,
        statutory_case["id"],
        item_number="1",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, statutory_case["id"])
    statutory_request = raise_request(
        api, statutory_case["id"], statutory_item["id"], method["id"], item_count=2
    )
    statutory_assignment = assign_request(
        api,
        statutory_request["id"],
        examiner["id"],
        expected_version=statutory_request["version"],
    )

    technical_review(
        api,
        routine_request["id"],
        reviewer["id"],
        "DISAGREE",
        rationale=(
            "Confirmatory ion ratios fall outside the method acceptance window; "
            "conclusion not supported."
        ),
    )

    return {
        "examiner": examiner,
        "reviewer": reviewer,
        "routine_case": routine_case,
        "routine_request": routine_request,
        "routine_assignment": routine_assignment,
        "statutory_case": statutory_case,
        "statutory_request": statutory_request,
        "statutory_assignment": statutory_assignment,
    }


def test_a_peer_disagreement_documents_the_dispute_and_puts_the_examiner_on_probation(api):
    """The reviewer's dissent parks the file in dispute, signs one technical record against
    it, and opens a MAJOR finding naming the examiner, which is what moves her standing.

    PRD §3.8: "Opening a `MAJOR` or `CRITICAL` finding that names an `analyst_id` moves that
    examiner `QUALIFIED` → `PROBATION` immediately, with the probation release running; a
    `MINOR` finding never moves a qualification state."

    Design: Difficulty/transitive_cascade/technical_disagreement_probation_releases_p1_assignment_on_a_different_case
    """
    state = _disagreement_that_puts_the_examiner_on_probation(api)

    routine_request = read_request(api, state["routine_request"]["id"])
    assert_fields(routine_request, status="DISAGREEMENT")

    records, meta = validate_paginated(
        api.list_review_records(
            CASE_MANAGER_HEADERS,
            {
                "examination_request_id": state["routine_request"]["id"],
                "review_type": "TECHNICAL",
            },
        )
    )
    assert_list_meta(meta, expected_total=1)
    assert_fields(
        records[0], decision="DISAGREE", reviewer_analyst_id=state["reviewer"]["id"]
    )

    findings, finding_meta = validate_paginated(
        api.list_nonconformances(
            QUALITY_MANAGER_HEADERS,
            {
                "examination_request_id": state["routine_request"]["id"],
                "source": "TECHNICAL_DISAGREEMENT",
            },
        )
    )
    assert_list_meta(finding_meta, expected_total=1)
    assert_fields(
        findings[0],
        severity="MAJOR",
        status="OPEN",
        analyst_id=state["examiner"]["id"],
    )
    assert_instant_equals(
        findings[0]["opened_at_utc"], "2026-08-01T00:00:00Z", "opened_at_utc"
    )
    assert_instant_equals(findings[0]["due_utc"], "2026-08-31T00:00:00Z", "due_utc")

    examiner = validate_success(
        api.get_analyst(state["examiner"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_fields(examiner, qualification_state="PROBATION")
    assert_instant_equals(
        examiner["probation_entered_at_utc"],
        "2026-08-01T00:00:00Z",
        "probation_entered_at_utc",
    )


def test_probation_release_reaches_the_statutory_case_and_spares_the_routine_one(api):
    """The release triggered on the routine case strips work from a different case entirely:
    the statutory assignment goes back to the queue while the completed routine assignment,
    and the routine case itself, are left as they were.

    PRD §2.10: "When an examiner enters `PROBATION`, every `ACTIVE` assignment they hold whose
    request belongs to a case whose effective `priority_class` is `P1_STATUTORY` or
    `P2_VIOLENT` is released: the assignment's `status` becomes `RELEASED` with `closed_at_utc`
    stamped from the logical clock, the assignment's snapshotted `estimated_hours` is
    subtracted from the examiner's `assigned_casework_hours`, the request's
    `assigned_analyst_id` is cleared to null, the request's `status` falls back to `QUEUED`,
    and the case rollup then runs on each affected case."

    Design: Difficulty/transitive_cascade/technical_disagreement_probation_releases_p1_assignment_on_a_different_case
    """
    state = _disagreement_that_puts_the_examiner_on_probation(api)

    statutory_case = validate_success(
        api.get_case(state["statutory_case"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(
        statutory_case,
        priority_class="P1_STATUTORY",
        priority_score=82.50,
        workflow_status="AWAITING_ASSIGNMENT",
    )

    statutory_assignment = validate_success(
        api.get_assignment(state["statutory_assignment"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(statutory_assignment, status="RELEASED", estimated_hours=4.00)

    statutory_request = read_request(api, state["statutory_request"]["id"])
    assert_fields(statutory_request, status="QUEUED")
    assert statutory_request["assigned_analyst_id"] is None, (
        "The released statutory request must carry no examiner"
    )

    examiner = validate_success(
        api.get_analyst(state["examiner"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_two_decimal_value(
        examiner["assigned_casework_hours"], 0.00, "assigned_casework_hours"
    )

    routine_assignment = validate_success(
        api.get_assignment(state["routine_assignment"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(routine_assignment, status="COMPLETED")
    routine_case = validate_success(
        api.get_case(state["routine_case"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(routine_case, workflow_status="IN_PROGRESS")
