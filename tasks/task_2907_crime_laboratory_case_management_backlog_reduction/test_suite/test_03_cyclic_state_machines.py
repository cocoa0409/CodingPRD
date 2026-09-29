"""State machines that are cyclic rather than linear: a file returned to the bench and
sent round again, a corrective action rejected twice, and a case advancing on two
independent axes at once.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_two_decimal_value,
)
from test_helpers.factories import (
    discovery_request_payload,
    discovery_response_payload,
)
from test_helpers.fixtures import (
    accept_case,
    administrative_review,
    assign_request,
    carry_to_tech_review,
    close_nonconformance,
    complete_analysis,
    create_validated_method,
    decide_capa,
    log_evidence,
    open_nonconformance,
    raise_request,
    read_request,
    register_analyst,
    release_request,
    report_case,
    set_clock,
    submit_case,
    submit_root_cause,
    technical_review,
)
from test_helpers.test_users import CASE_MANAGER_HEADERS, QUALITY_MANAGER_HEADERS


def _request_returned_by_administrative_review_and_sent_round_again(api):
    """A request taken to administrative review, returned for revision, reworked by the
    same examiner, agreed again and finally released.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Ada Nakamura",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Bo Ferreira",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-0505",
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
    carry_to_tech_review(api, request["id"], examiner["id"], actual_hours=5.00)
    technical_review(api, request["id"], reviewer["id"], "AGREE")

    administrative_review(api, request["id"], "RETURN")
    complete_analysis(api, request["id"], examiner["id"], actual_hours=7.50)
    technical_review(api, request["id"], reviewer["id"], "AGREE")
    administrative_review(api, request["id"], "APPROVE")

    return {
        "examiner": examiner,
        "reviewer": reviewer,
        "case": case,
        "item": item,
        "request": request,
        "assignment": assignment,
    }


def test_administrative_return_reopens_the_same_assignment_row(api):
    """The returned file goes back to the examiner who already held it: no second
    assignment row is created, the original one is reactivated, and the exhibit leaves
    the vault a second time.

    PRD §2.10: "On the reopen branch the candidate assignment's `status` returns to
    `ACTIVE`, its `closed_at_utc` is cleared to null, its snapshotted `estimated_hours` is
    added back to the examiner's `assigned_casework_hours`, the request returns to
    `IN_ANALYSIS`, and the evidence item is checked out of the vault again."

    Design: Difficulty/non_linear_state_machine/exam_request_administrative_return_reopens_same_assignment_row
    """
    state = _request_returned_by_administrative_review_and_sent_round_again(api)

    request = read_request(api, state["request"]["id"])
    assert_fields(
        request,
        status="RELEASED",
        revision_round=1,
        actual_hours_logged=7.50,
        assigned_analyst_id=state["examiner"]["id"],
    )

    rows, meta = validate_paginated(
        api.list_assignments(
            CASE_MANAGER_HEADERS, {"examination_request_id": state["request"]["id"]}
        )
    )
    assert_list_meta(meta, expected_total=1)
    assert len(rows) == 1, "The reopened round must not create a second assignment row"

    assignment = validate_success(
        api.get_assignment(state["assignment"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(assignment, status="COMPLETED", estimated_hours=6.00)
    assert assignment["superseded_by_assignment_id"] is None, (
        "Reopening is not a supersede, so no supersede pointer is written"
    )

    item = validate_success(api.get_evidence_item(state["item"]["id"], CASE_MANAGER_HEADERS))
    assert_fields(item, checkout_count=2, custody_status="IN_VAULT")


def test_each_revision_round_writes_its_own_pair_of_review_records(api):
    """Four immutable records survive the cycle, two stamped with round 0 and two with
    round 1, and the ledger of committed hours comes back to zero.

    PRD §3.6: "Every review record names the `examination_request_id` it concerns, its
    `review_type` — one of `TECHNICAL`, `ADMINISTRATIVE` or `DISAGREEMENT_RESOLUTION` —
    the `decision` recorded, a mandatory `rationale` of 1 to 500 characters, a
    `revision_round_snapshot` copying the request's `revision_round` at the instant of
    signing, and a `recorded_at_utc` stamped from the logical clock."

    Design: Difficulty/non_linear_state_machine/exam_request_administrative_return_reopens_same_assignment_row
    """
    state = _request_returned_by_administrative_review_and_sent_round_again(api)

    records, meta = validate_paginated(
        api.list_review_records(
            CASE_MANAGER_HEADERS, {"examination_request_id": state["request"]["id"]}
        )
    )
    assert_list_meta(meta, expected_total=4)
    first_round = [r for r in records if r["revision_round_snapshot"] == 0]
    second_round = [r for r in records if r["revision_round_snapshot"] == 1]
    assert len(first_round) == 2, f"Expected two records stamped round 0, got {len(first_round)}"
    assert len(second_round) == 2, f"Expected two records stamped round 1, got {len(second_round)}"

    examiner = validate_success(
        api.get_analyst(state["examiner"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_two_decimal_value(
        examiner["assigned_casework_hours"], 0.00, "assigned_casework_hours"
    )

    case = validate_success(api.get_case(state["case"]["id"], CASE_MANAGER_HEADERS))
    assert_fields(
        case, released_examination_request_count=1, open_examination_request_count=0
    )


def _finding_rejected_twice_then_approved_and_closed(api):
    """A MAJOR finding against an examiner that is bounced twice before the third plan is
    approved and the finding is verified closed, all at one frozen instant.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Ada Nakamura",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    finding = open_nonconformance(
        api,
        source="INTERNAL_QA",
        severity="MAJOR",
        description="Peer file review found an undocumented reagent lot substitution.",
        analyst_id=examiner["id"],
    )

    submit_root_cause(
        api,
        finding["id"],
        root_cause_category="DOCUMENTATION",
        corrective_action_plan="Add reagent lot fields to the bench sheet template.",
    )
    decide_capa(api, finding["id"], "REJECT")
    submit_root_cause(
        api,
        finding["id"],
        root_cause_category="TRAINING",
        corrective_action_plan="Retrain the examiner on reagent lot verification.",
    )
    decide_capa(api, finding["id"], "REJECT")
    submit_root_cause(
        api,
        finding["id"],
        root_cause_category="METHOD_DEFICIENCY",
        corrective_action_plan=(
            "Amend the method to require a second-person lot check plus quarterly audit."
        ),
    )
    decide_capa(api, finding["id"], "APPROVE")
    close_nonconformance(api, finding["id"])

    return examiner, finding


def test_second_capa_rejection_escalates_and_re_dates_the_deadline_from_the_opening(api):
    """Two trips round the rejection loop step the severity up one tier and re-date the
    corrective-action deadline from the instant the finding was opened, giving
    2026-08-11T00:00:00Z rather than ten days from the rejection.

    PRD §3.8: "A second rejection escalates: when `capa_rejection_count` reaches 2, the
    `severity` steps up one tier — `MINOR` becomes `MAJOR`, `MAJOR` becomes `CRITICAL`, and
    `CRITICAL` stays `CRITICAL` because there is no higher tier — and `due_utc` is
    recomputed from the **original** `opened_at_utc` using the new tier's allowance, never
    from the rejection instant."

    Design: Difficulty/non_linear_state_machine/nonconformance_capa_rejection_cycle_escalates_and_returns_analyst_to_qualified
    """
    _examiner, finding = _finding_rejected_twice_then_approved_and_closed(api)

    body = validate_success(api.get_nonconformance(finding["id"], QUALITY_MANAGER_HEADERS))
    assert_fields(body, capa_rejection_count=2, severity="CRITICAL")
    assert_instant_equals(body["opened_at_utc"], "2026-08-01T00:00:00Z", "opened_at_utc")
    assert_instant_equals(body["due_utc"], "2026-08-11T00:00:00Z", "due_utc")


def test_closing_the_last_live_finding_lifts_the_examiner_off_probation(api):
    """Verified closure ends the finding and, with nothing else live against her, hands the
    examiner back her qualified standing with a clean failure counter.

    PRD §3.8: "Closure can also restore an examiner: when the finding names an
    `analyst_id`, that examiner is on `PROBATION`, and no other nonconformance against them
    remains with `status` `OPEN`, `ROOT_CAUSE_SUBMITTED` or `CAPA_APPROVED`, they move
    `PROBATION` → `QUALIFIED`, `consecutive_pt_failures` resets to 0 and
    `probation_entered_at_utc` is cleared."

    Design: Difficulty/non_linear_state_machine/nonconformance_capa_rejection_cycle_escalates_and_returns_analyst_to_qualified
    """
    examiner, finding = _finding_rejected_twice_then_approved_and_closed(api)

    body = validate_success(api.get_nonconformance(finding["id"], QUALITY_MANAGER_HEADERS))
    assert_fields(
        body, status="CLOSED", overdue=False, root_cause_category="METHOD_DEFICIENCY"
    )
    assert_instant_equals(body["closed_at_utc"], "2026-08-01T00:00:00Z", "closed_at_utc")

    reread = validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS))
    assert_fields(reread, qualification_state="QUALIFIED", consecutive_pt_failures=0)
    assert reread["probation_entered_at_utc"] is None, (
        "Restoration to QUALIFIED clears probation_entered_at_utc"
    )


def _case_with_one_released_request(api):
    """A drug case whose single examination has been released, leaving the case in progress
    and its discovery axis untouched.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Ada Nakamura",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Bo Ferreira",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-0606",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )
    release_request(api, request["id"], examiner["id"], reviewer["id"], actual_hours=2.00)
    return case


def test_the_discovery_axis_moves_twice_without_disturbing_the_workflow_axis(api):
    """Recording the demand and answering it walk discovery from NONE to RECEIVED to
    FULFILLED while the case stays in progress on the workflow axis, with the response
    deadline set thirty days out.

    PRD §3.9: "A case's `discovery_status` starts at `NONE` and moves through `RECEIVED` to
    either `FULFILLED` or `DENIED` without ever disturbing the case's `workflow_status`; the
    two axes are orthogonal, so a case can be answering a discovery demand while its
    examinations are still in progress, and reporting a case does not resolve an outstanding
    demand."

    Design: Difficulty/non_linear_state_machine/case_workflow_and_discovery_axes_advance_independently
    """
    case = _case_with_one_released_request(api)

    received = validate_success(
        api.request_discovery(
            case["id"],
            discovery_request_payload("Office of the Public Defender"),
            CASE_MANAGER_HEADERS,
        )
    )
    assert_fields(received, discovery_status="RECEIVED", workflow_status="IN_PROGRESS")
    assert_instant_equals(
        received["discovery_requested_at_utc"],
        "2026-08-01T00:00:00Z",
        "discovery_requested_at_utc",
    )
    assert_instant_equals(
        received["discovery_due_utc"], "2026-08-31T00:00:00Z", "discovery_due_utc"
    )

    fulfilled = validate_success(
        api.respond_to_discovery(
            case["id"],
            discovery_response_payload(
                "FULFILL", "Bench notes, spectra and method SOP produced."
            ),
            CASE_MANAGER_HEADERS,
        )
    )
    assert_fields(fulfilled, discovery_status="FULFILLED", workflow_status="IN_PROGRESS")


def test_reporting_closes_the_workflow_axis_and_leaves_the_discovery_answer_standing(api):
    """The later workflow hop to REPORTED does not touch the discovery answer already given,
    both turnaround figures land on 0.00 for a case reported at the instant it arrived, and
    an answer given inside the window raises no missed-deadline finding.

    PRD §3.9: "Either way, if the current logical instant is strictly after
    `discovery_due_utc`, the laboratory has missed a statutory response deadline, and a
    nonconformance is opened with `source` `DEADLINE_MISS` and `severity` `MAJOR`, with both
    `examination_request_id` and `analyst_id` null and a `description` citing the case,
    because a missed disclosure deadline is an institutional failure rather than an
    individual examiner's."

    Design: Difficulty/non_linear_state_machine/case_workflow_and_discovery_axes_advance_independently
    """
    case = _case_with_one_released_request(api)
    validate_success(
        api.request_discovery(
            case["id"],
            discovery_request_payload("Office of the Public Defender"),
            CASE_MANAGER_HEADERS,
        )
    )
    validate_success(
        api.respond_to_discovery(
            case["id"],
            discovery_response_payload(
                "FULFILL", "Bench notes, spectra and method SOP produced."
            ),
            CASE_MANAGER_HEADERS,
        )
    )

    reported = report_case(api, case["id"])
    assert_fields(
        reported,
        workflow_status="REPORTED",
        discovery_status="FULFILLED",
        gross_turnaround_days=0.00,
        net_turnaround_days=0.00,
    )

    _rows, meta = validate_paginated(
        api.list_nonconformances(QUALITY_MANAGER_HEADERS, {"source": "DEADLINE_MISS"})
    )
    assert_list_meta(meta, expected_total=0)
