"""Declared transitions and the guards around them: where each machine starts, which calls a
terminal state refuses, what one call cascades to its children, and which preconditions must hold
before a state may be left at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_CASE_HAS_NO_EVIDENCE,
    ERR_CASE_HAS_OPEN_REQUESTS,
    ERR_CASE_INVALID_STATE,
    ERR_EVIDENCE_SEAL_BROKEN,
    ERR_PROBATION_PRIORITY_RESTRICTED,
)
from test_helpers.assertions import (
    assert_absent,
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_workload,
    collect_ids,
)
from test_helpers.factories import (
    assignment_payload,
    case_acceptance_payload,
    case_rejection_payload,
    case_report_payload,
    complete_analysis_payload,
    evidence_item_payload,
    method_retirement_payload,
)
from test_helpers.fixtures import (
    accept_case,
    assign_request,
    create_validated_method,
    log_evidence,
    open_nonconformance,
    raise_request,
    read_request,
    register_analyst,
    release_request,
    set_clock,
    start_analysis,
    submit_case,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
    make_analyst_headers,
)


def test_a_freshly_logged_exhibit_starts_in_the_vault_with_no_checkouts(api):
    """Logging property records it into the vault and nothing more: the item begins IN_VAULT with a
    checkout counter of zero and a logging stamp taken from the logical clock.

    PRD §3.1: "A newly logged item has `custody_status` `IN_VAULT`, a `checkout_count` of 0 and a
    `logged_at_utc` stamped from the logical clock."

    Design: Corner/state_machines/evidence_item_initial_custody_status_is_in_vault
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0101",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )

    item = validate_success(
        api.create_evidence_item(
            evidence_item_payload(
                case["id"],
                item_number="1",
                item_description="Sealed fibre tape lift",
                item_type="TRACE_MEDIA",
                seal_intact=True,
            ),
            TECHNICIAN_HEADERS,
        ),
        201,
    )

    assert_fields(
        item,
        custody_status="IN_VAULT",
        checkout_count=0,
        seal_intact=True,
        version=1,
    )
    assert_instant_equals(item["logged_at_utc"], "2026-08-01T00:00:00Z", "logged_at_utc")


def test_a_refused_submission_can_never_be_accepted_afterwards(api):
    """Refusal is terminal on the casework axis, so acceptance has no transition to make from it:
    the case keeps its refusal reason, never earns an acceptance stamp, and the property stays
    returned to the agency.

    PRD §3.1: "Accepting a submission moves `workflow_status` from `SUBMITTED` to `ACCEPTED` and
    stamps `accepted_at_utc`; the technician may attach an optional `acceptance_note`."

    PRD §2.8: "**State guard.** The target row is in a state from which the requested transition is
    declared, else that entity's own invalid-state code (409): `ERR_CASE_INVALID_STATE` for a case's
    `workflow_status`, ..."

    Design: Corner/state_machines/case_accept_from_the_rejected_state_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0102",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed envelope",
        item_type="TRACE_MEDIA",
        seal_intact=True,
    )
    validate_success(
        api.reject_case(
            case["id"],
            case_rejection_payload("Submitting agency withdrew the request for examination."),
            TECHNICIAN_HEADERS,
        )
    )

    validate_error(
        api.accept_case(case["id"], case_acceptance_payload(), TECHNICIAN_HEADERS),
        ERR_CASE_INVALID_STATE,
        409,
    )

    read = validate_success(api.get_case(case["id"], TECHNICIAN_HEADERS))
    assert_fields(
        read,
        workflow_status="REJECTED",
        rejection_reason="Submitting agency withdrew the request for examination.",
    )
    assert_absent(read, "accepted_at_utc")
    assert_fields(
        validate_success(api.get_evidence_item(item["id"], TECHNICIAN_HEADERS)),
        custody_status="RETURNED",
    )


def test_refusing_a_submission_returns_every_exhibit_in_the_vault(api):
    """The refusal cascade fans out over all of the case's property rather than stopping at the
    first exhibit: both sealed envelopes come back to the agency, and neither was ever checked out.

    PRD §3.1: "Refusal cascades to the property: every one of the case's items still `IN_VAULT`
    moves to `RETURNED`."

    Design: Corner/state_machines/case_rejection_cascades_every_vault_item_to_returned
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0103",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed envelope one",
        item_type="TRACE_MEDIA",
        seal_intact=True,
    )
    second_item = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed envelope two",
        item_type="TRACE_MEDIA",
        seal_intact=True,
    )

    refused = validate_success(
        api.reject_case(
            case["id"],
            case_rejection_payload("Chain-of-custody paperwork incomplete at the counter."),
            TECHNICIAN_HEADERS,
        )
    )

    assert_fields(refused, workflow_status="REJECTED")
    for item in (first_item, second_item):
        assert_fields(
            validate_success(api.get_evidence_item(item["id"], TECHNICIAN_HEADERS)),
            custody_status="RETURNED",
            checkout_count=0,
        )

    rows, meta = validate_paginated(
        api.list_evidence_items(
            TECHNICIAN_HEADERS, {"case_id": case["id"], "custody_status": "RETURNED"}
        )
    )
    assert set(collect_ids(rows)) == {first_item["id"], second_item["id"]}
    assert_list_meta(meta, expected_total=2)


def test_the_two_acceptance_preconditions_report_two_distinct_refusals(api):
    """Acceptance demands property and demands that its seals be intact, and the two shortfalls are
    reported differently: an exhibit-less submission is refused for having no evidence, a torn bag
    is refused for the broken seal, and a third case with an intact seal is accepted, so neither
    refusal is a blanket block.

    PRD §3.1: "Acceptance demands two things of the evidence: the case must carry at least one
    logged item, else `ERR_CASE_HAS_NO_EVIDENCE`, and every one of those items must have
    `seal_intact` true, else `ERR_EVIDENCE_SEAL_BROKEN`."

    Design: Corner/state_machines/case_accept_preconditions_reject_empty_and_broken_seal_submissions
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    empty_case = submit_case(
        api,
        agency_case_number="O-2026-0104",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    broken_case = submit_case(
        api,
        agency_case_number="O-2026-0105",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    broken_item = log_evidence(
        api,
        broken_case["id"],
        item_number="1",
        item_description="Torn evidence bag",
        item_type="TRACE_MEDIA",
        seal_intact=False,
    )
    good_case = submit_case(
        api,
        agency_case_number="O-2026-0106",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    good_item = log_evidence(
        api,
        good_case["id"],
        item_number="1",
        item_description="Intact sealed bag",
        item_type="TRACE_MEDIA",
        seal_intact=True,
    )

    validate_error(
        api.accept_case(empty_case["id"], case_acceptance_payload(), TECHNICIAN_HEADERS),
        ERR_CASE_HAS_NO_EVIDENCE,
        409,
    )
    validate_error(
        api.accept_case(broken_case["id"], case_acceptance_payload(), TECHNICIAN_HEADERS),
        ERR_EVIDENCE_SEAL_BROKEN,
        409,
    )
    for refused in (empty_case, broken_case):
        assert_fields(
            validate_success(api.get_case(refused["id"], TECHNICIAN_HEADERS)),
            workflow_status="SUBMITTED",
        )

    accepted = validate_success(
        api.accept_case(
            good_case["id"],
            case_acceptance_payload("Seals verified against the submission form."),
            TECHNICIAN_HEADERS,
        )
    )
    assert_fields(accepted, workflow_status="ACCEPTED")
    assert_instant_equals(accepted["accepted_at_utc"], "2026-08-01T00:00:00Z", "accepted_at_utc")
    for untouched in (broken_item, good_item):
        assert_fields(
            validate_success(api.get_evidence_item(untouched["id"], TECHNICIAN_HEADERS)),
            custody_status="IN_VAULT",
        )


def test_a_second_acceptance_of_the_same_case_changes_nothing(api):
    """Acceptance is not idempotent: the second call finds the case already past SUBMITTED and is
    refused, so the first acceptance stamp stands and the row's version does not move again.

    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed
    on every mutation, and `version`, a system-managed integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of that row."

    PRD §2.8: "**State guard.** The target row is in a state from which the requested transition is
    declared, else that entity's own invalid-state code (409): `ERR_CASE_INVALID_STATE` for a case's
    `workflow_status`, ..."

    Design: Corner/state_machines/second_accept_of_the_same_case_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0107",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Intact sealed bag",
        item_type="TRACE_MEDIA",
        seal_intact=True,
    )
    accepted = accept_case(api, case["id"])

    validate_error(
        api.accept_case(case["id"], case_acceptance_payload(), TECHNICIAN_HEADERS),
        ERR_CASE_INVALID_STATE,
        409,
    )

    read = validate_success(api.get_case(case["id"], TECHNICIAN_HEADERS))
    assert_fields(read, workflow_status="ACCEPTED", version=accepted["version"])
    assert_instant_equals(read["accepted_at_utc"], "2026-08-01T00:00:00Z", "accepted_at_utc")


def test_retiring_a_method_cancels_the_queued_work_and_spares_the_assigned_work(api):
    """Retirement withdraws the method from future work only: the queued request is cancelled while
    the assigned one on the same case and method runs on, so the case's open count falls to exactly
    one and the holder keeps the four hours already encumbered.

    PRD §3.2: "Retirement cascades in two hops: first, every examination request naming the retired
    method whose status is still `QUEUED` moves to `CANCELLED`; second, because those requests just
    became terminal, the case rollup of §2.10 runs on each affected case, refreshing its
    `open_examination_request_count`."

    PRD §3.2: "Requests already past `QUEUED` are untouched by retirement and may run to completion
    — retirement withdraws the method from *future* work, not from work in flight."

    Design: Corner/state_machines/method_retirement_cancels_only_the_queued_requests
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Retire Case Analyst",
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
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0108",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    second_item = log_evidence(
        api, case["id"], item_number="2", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    queued_request = raise_request(
        api, case["id"], first_item["id"], method["id"], item_count=2
    )
    assigned_request = raise_request(
        api, case["id"], second_item["id"], method["id"], item_count=2
    )
    assignment = assign_request(
        api,
        assigned_request["id"],
        examiner["id"],
        expected_version=assigned_request["version"],
    )

    retired = validate_success(
        api.retire_method(
            method["id"],
            method_retirement_payload("Superseded by an updated validated procedure."),
            QUALITY_MANAGER_HEADERS,
        )
    )

    assert_fields(retired, validation_status="RETIRED")
    assert_instant_equals(retired["retired_at_utc"], "2026-08-01T00:00:00Z", "retired_at_utc")
    assert_fields(read_request(api, queued_request["id"]), status="CANCELLED")
    assert_fields(read_request(api, assigned_request["id"]), status="ASSIGNED")

    rows, meta = validate_paginated(
        api.list_examination_requests(
            CASE_MANAGER_HEADERS, {"case_id": case["id"], "status": "CANCELLED"}
        )
    )
    assert collect_ids(rows) == [queued_request["id"]]
    assert_list_meta(meta, expected_total=1)
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        open_examination_request_count=1,
        workflow_status="IN_PROGRESS",
    )
    assert_fields(
        validate_success(api.get_assignment(assignment["id"], CASE_MANAGER_HEADERS)),
        status="ACTIVE",
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=4.00,
    )


def test_completing_bench_work_fires_all_three_declared_side_effects(api):
    """One completion call stores the reported 9.25 hours, closes the assignment and de-encumbers
    exactly the snapshotted 8.00 hours rather than the hours reported, and brings the exhibit back
    into the vault with its single checkout still on the record.

    PRD §3.5: "The holder's `ACTIVE` assignment moves to `COMPLETED` with `closed_at_utc` stamped
    from the logical clock, and the holder's `assigned_casework_hours` is decreased by exactly that
    assignment's snapshotted `estimated_hours`."

    PRD §3.4: "The **realized** variant answers "what did the work actually consume": its numerator,
    `realized_load_hours`, ranges over the examiner's assignments whose `status` is `ACTIVE` or
    `COMPLETED` and takes, for each one, the owning request's `actual_hours_logged` whenever that
    figure is not null and the assignment's snapshotted `estimated_hours` otherwise, summing and
    rounding half up to 2 decimal places; `realized_utilization_pct` is derived from it in the same
    way, and is likewise 0.00 when the available hours are 0.00."

    Design: Corner/state_machines/complete_analysis_releases_hours_and_checks_the_evidence_back_in
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Side Effect Analyst",
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
        agency_case_number="A-2026-0109",
        submitting_agency="COUNTY SO",
        offense_category="AGG_ASSAULT",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed reference swab",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=2)
    assignment = assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )
    start_analysis(api, request["id"], examiner["id"])

    completed = validate_success(
        api.complete_analysis(
            request["id"],
            complete_analysis_payload(actual_hours=9.25, evidence_consumed=False),
            make_analyst_headers(examiner["id"]),
        )
    )

    assert_fields(
        completed, status="TECH_REVIEW", actual_hours_logged=9.25, estimated_hours=8.00
    )
    closed = validate_success(api.get_assignment(assignment["id"], CASE_MANAGER_HEADERS))
    assert_fields(closed, status="COMPLETED", estimated_hours=8.00)
    assert_instant_equals(closed["closed_at_utc"], "2026-08-01T00:00:00Z", "closed_at_utc")
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=0.00,
    )
    assert_fields(
        validate_success(api.get_evidence_item(item["id"], TECHNICIAN_HEADERS)),
        custody_status="IN_VAULT",
        checkout_count=1,
    )
    assert_workload(
        validate_success(api.get_analyst_workload(examiner["id"], QUALITY_MANAGER_HEADERS)),
        projected_load_hours=0.00,
        projected_utilization_pct=0.00,
        realized_load_hours=9.25,
        realized_utilization_pct=28.91,
        active_assignment_count=0,
    )


def _chemistry_case_with_two_single_item_requests(api):
    """A two-exhibit chemistry case whose first request has been taken all the way to RELEASED
    while the second sits on the bench of the same examiner.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    author = register_analyst(
        api,
        full_name="Report Author",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Report Reviewer",
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
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0110",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet one",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    second_item = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed packet two",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    released = raise_request(api, case["id"], first_item["id"], method["id"], item_count=1)
    assign_request(api, released["id"], author["id"], expected_version=released["version"])
    release_request(api, released["id"], author["id"], reviewer["id"], actual_hours=1.00)

    open_one = raise_request(api, case["id"], second_item["id"], method["id"], item_count=1)
    assign_request(api, open_one["id"], author["id"], expected_version=open_one["version"])
    return author, reviewer, case, released, open_one


def test_a_case_cannot_be_reported_while_one_request_is_still_in_flight(api):
    """The parent waits for its last child: with one request released and one still on a bench the
    report is refused, and only once that second request is released too does the same call succeed
    and freeze a five-day turnaround.

    PRD §3.9: "Its `open_examination_request_count` must be exactly 0, else
    `ERR_CASE_HAS_OPEN_REQUESTS` — nothing may still be in a queue, on a bench, at a vendor or in
    review."

    PRD §2.10: "In every invocation, whether or not the status changed, the rollup refreshes
    `open_examination_request_count` to the number of the case's requests whose status is neither
    `RELEASED` nor `CANCELLED`, refreshes `released_examination_request_count` to the number whose
    status is `RELEASED`, refreshes `updated_at` and increments the case's `version` by 1."

    PRD §3.9: "`gross_turnaround_days` is the elapsed calendar time the agency waited: the interval
    from the case's `received_at_utc` to its `reported_at_utc`, taken in whole seconds, divided by
    86400, rounded half up to 2 decimal places."

    PRD §3.9: "Then `net_turnaround_days` is `gross_turnaround_days` minus that figure, rounded half
    up to 2 decimal places, and floored at 0.00 so it is never negative."

    Design: Corner/state_machines/case_report_requires_every_examination_request_to_be_released
    """
    author, reviewer, case, released, open_one = _chemistry_case_with_two_single_item_requests(api)
    set_clock(api, "2026-08-06T00:00:00Z")

    validate_error(
        api.report_case(case["id"], case_report_payload(), CASE_MANAGER_HEADERS),
        ERR_CASE_HAS_OPEN_REQUESTS,
        409,
    )

    refused = validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS))
    assert_fields(
        refused,
        workflow_status="IN_PROGRESS",
        open_examination_request_count=1,
        released_examination_request_count=1,
    )
    assert refused["reported_at_utc"] is None, (
        "A refused report must leave the case unstamped"
    )

    release_request(api, open_one["id"], author["id"], reviewer["id"], actual_hours=1.00)
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        open_examination_request_count=0,
        released_examination_request_count=2,
    )

    reported = validate_success(
        api.report_case(case["id"], case_report_payload(), CASE_MANAGER_HEADERS)
    )
    assert_fields(
        reported,
        workflow_status="REPORTED",
        gross_turnaround_days=5.00,
        net_turnaround_days=5.00,
    )
    assert_instant_equals(reported["reported_at_utc"], "2026-08-06T00:00:00Z", "reported_at_utc")
    assert_fields(read_request(api, released["id"]), status="RELEASED")


def test_a_reported_case_refuses_every_further_casework_call(api):
    """REPORTED closes the casework axis: a second report and a late acceptance are both refused
    with the case's own invalid-state code, the first report's stamp and turnaround stand, and the
    untouched discovery axis is still at NONE.

    PRD §3.9: "A case is reported once, by the `CaseManager`, optionally with a `report_note`. The
    case must be `IN_PROGRESS`, else `ERR_CASE_INVALID_STATE`."

    PRD §3.9: "On success the case moves `IN_PROGRESS` → `REPORTED`, which is terminal on the
    workflow axis, `reported_at_utc` is stamped from the logical clock, and both turnaround figures
    are computed and frozen onto the case."

    PRD §3.9: "A case's `discovery_status` starts at `NONE` and moves through `RECEIVED` to either
    `FULFILLED` or `DENIED` without ever disturbing the case's `workflow_status`; the two axes are
    orthogonal, so a case can be answering a discovery demand while its examinations are still in
    progress, and reporting a case does not resolve an outstanding demand."

    Design: Corner/state_machines/reported_case_is_terminal_on_the_casework_axis
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    author = register_analyst(
        api,
        full_name="Terminal Author",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Terminal Reviewer",
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
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0111",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet one",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(api, request["id"], author["id"], expected_version=request["version"])
    release_request(api, request["id"], author["id"], reviewer["id"], actual_hours=1.00)
    set_clock(api, "2026-08-06T00:00:00Z")
    validate_success(api.report_case(case["id"], case_report_payload(), CASE_MANAGER_HEADERS))

    validate_error(
        api.report_case(case["id"], case_report_payload(), CASE_MANAGER_HEADERS),
        ERR_CASE_INVALID_STATE,
        409,
    )
    validate_error(
        api.accept_case(case["id"], case_acceptance_payload(), TECHNICIAN_HEADERS),
        ERR_CASE_INVALID_STATE,
        409,
    )

    read = validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS))
    assert_fields(
        read,
        workflow_status="REPORTED",
        gross_turnaround_days=5.00,
        discovery_status="NONE",
    )
    assert_instant_equals(read["reported_at_utc"], "2026-08-06T00:00:00Z", "reported_at_utc")


def test_a_probationary_examiner_is_barred_from_statutory_work_only(api):
    """The assignment guard reads two other rows at once — the examiner's standing and the case's
    queue class — so the same probationary examiner is refused the statutory-class request under the
    probation restriction rather than a qualification failure, and admitted on the routine one.

    PRD §3.8: "Opening a `MAJOR` or `CRITICAL` finding that names an `analyst_id` moves that
    examiner `QUALIFIED` → `PROBATION` immediately, with the probation release running; a `MINOR`
    finding never moves a qualification state."

    PRD §2.8: "**Probation priority restriction.** A probationary examiner is offered only
    routine-class work, else `ERR_PROBATION_PRIORITY_RESTRICTED` (409)."

    Design: Corner/state_machines/probation_analyst_cannot_be_assigned_to_a_p1_statutory_request
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Probation Analyst",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    finding = open_nonconformance(
        api,
        source="ACCREDITATION_AUDIT",
        severity="MAJOR",
        description="Audit finding on documentation practice.",
        analyst_id=examiner["id"],
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
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    statutory_case = submit_case(
        api,
        agency_case_number="H-2026-0112",
        submitting_agency="METRO PD",
        offense_category="HOMICIDE",
        suspect_in_custody=False,
        statutory_deadline_utc="2026-08-20T00:00:00Z",
    )
    statutory_item = log_evidence(
        api,
        statutory_case["id"],
        item_number="1",
        item_description="Sealed residue swab",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, statutory_case["id"])
    statutory_request = raise_request(
        api, statutory_case["id"], statutory_item["id"], method["id"], item_count=1
    )
    routine_case = submit_case(
        api,
        agency_case_number="O-2026-0113",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    routine_item = log_evidence(
        api,
        routine_case["id"],
        item_number="1",
        item_description="Sealed packet",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, routine_case["id"])
    routine_request = raise_request(
        api, routine_case["id"], routine_item["id"], method["id"], item_count=1
    )

    probationary = validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS))
    assert_fields(probationary, qualification_state="PROBATION")
    assert_instant_equals(
        probationary["probation_entered_at_utc"],
        "2026-08-01T00:00:00Z",
        "probation_entered_at_utc",
    )
    assert_fields(
        validate_success(api.get_case(statutory_case["id"], CASE_MANAGER_HEADERS)),
        priority_class="P1_STATUTORY",
    )
    assert_fields(
        validate_success(api.get_case(routine_case["id"], CASE_MANAGER_HEADERS)),
        priority_class="P3_ROUTINE",
    )

    validate_error(
        api.create_assignment(
            statutory_request["id"],
            assignment_payload(
                examiner["id"],
                statutory_request["version"],
                assignment_reason="MANUAL",
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_PROBATION_PRIORITY_RESTRICTED,
        409,
    )
    refused = read_request(api, statutory_request["id"])
    assert_fields(refused, status="QUEUED")
    assert refused["assigned_analyst_id"] is None, (
        "A refused assignment must leave the request unheld"
    )

    admitted = validate_success(
        api.create_assignment(
            routine_request["id"],
            assignment_payload(
                examiner["id"], routine_request["version"], assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(admitted, status="ACTIVE", estimated_hours=2.00)
    assert_fields(
        read_request(api, routine_request["id"]),
        status="ASSIGNED",
        assigned_analyst_id=examiner["id"],
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=2.00,
    )
    assert_fields(
        validate_success(api.get_nonconformance(finding["id"], QUALITY_MANAGER_HEADERS)),
        status="OPEN",
        severity="MAJOR",
    )
