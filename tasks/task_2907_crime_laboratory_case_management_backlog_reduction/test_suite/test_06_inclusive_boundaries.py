"""Boundaries that are inclusive on the admitting side: a utilisation ceiling met exactly, an
outsourcing floor reached exactly, and two grading cut points sitting on their own values.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ERR_ANALYST_CAPACITY_EXCEEDED
from test_helpers.assertions import (
    assert_backlog_report,
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_two_decimal_value,
    assert_workload,
)
from test_helpers.factories import assignment_payload
from test_helpers.fixtures import (
    accept_case,
    assign_proficiency_test,
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


def _two_examiners_with_sixteen_available_hours_each(api):
    """Two identically contracted examiners — twenty contracted hours less four of training —
    and two requests, one worth exactly their available hours and one worth half an hour more.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    exact = register_analyst(
        api,
        full_name="Exact Boundary Examiner",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=20.00,
        training_hours_per_week=4.00,
    )
    over = register_analyst(
        api,
        full_name="Over Boundary Examiner",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=20.00,
        training_hours_per_week=4.00,
    )
    eight_hour_method = create_validated_method(
        api,
        name="Quantitative Ethanol Headspace",
        discipline="CHEMISTRY",
        standard_hours_per_item=8.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-HS-01",
    )
    long_method = create_validated_method(
        api,
        name="Comprehensive Toxicology Panel",
        discipline="CHEMISTRY",
        standard_hours_per_item=16.50,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-TOX-01",
        precision_cv_pct=3.00,
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-1212",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    first_item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    second_item = log_evidence(
        api, case["id"], item_number="2", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    exact_request = raise_request(
        api, case["id"], first_item["id"], eight_hour_method["id"], item_count=2
    )
    over_request = raise_request(
        api, case["id"], second_item["id"], long_method["id"], item_count=1
    )
    return exact, over, exact_request, over_request


def test_an_assignment_landing_on_exactly_one_hundred_percent_is_admitted(api):
    """Sixteen encumbered hours over sixteen available reads as 100.00 percent, which the gate
    admits, and the workload read shows the ceiling met rather than breached.

    PRD §3.4: "The assignment is admitted only when that post-assignment figure is at most
    100.00 percent. Exactly 100.00 is admitted; 100.01 is refused with
    `ERR_ANALYST_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/assignment_admitted_at_exactly_100_pct_projected_utilization
    """
    exact, _over, exact_request, _over_request = _two_examiners_with_sixteen_available_hours_each(
        api
    )

    created = validate_success(
        api.create_assignment(
            exact_request["id"],
            assignment_payload(exact["id"], exact_request["version"]),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(created, status="ACTIVE", estimated_hours=16.00)
    assert_fields(read_request(api, exact_request["id"]), estimated_hours=16.00)

    reread = validate_success(api.get_analyst(exact["id"], QUALITY_MANAGER_HEADERS))
    assert_two_decimal_value(
        reread["assigned_casework_hours"], 16.00, "assigned_casework_hours"
    )

    workload = validate_success(
        api.get_analyst_workload(exact["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_workload(
        workload,
        available_hours=16.00,
        projected_load_hours=16.00,
        projected_utilization_pct=100.00,
        casework_training_ratio=4.00,
    )


def test_a_request_computing_one_hundred_and_three_percent_is_refused_and_writes_nothing(api):
    """Sixteen and a half hours over sixteen available recomputes as 103.13 percent, past the
    ceiling, so the request stays queued and the examiner's ledger is untouched.

    PRD §3.4: "Before any assignment is admitted, the projected variant is recomputed as though
    the new work were already encumbered: the examiner's current `projected_load_hours` plus the
    request's `estimated_hours`, divided by their available hours, multiplied by 100 and rounded
    half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/assignment_admitted_at_exactly_100_pct_projected_utilization
    """
    _exact, over, _exact_request, over_request = _two_examiners_with_sixteen_available_hours_each(
        api
    )

    response = api.create_assignment(
        over_request["id"],
        assignment_payload(over["id"], over_request["version"]),
        CASE_MANAGER_HEADERS,
    )
    validate_error(response, ERR_ANALYST_CAPACITY_EXCEEDED, expected_status=409)

    reread_request = read_request(api, over_request["id"])
    assert_fields(reread_request, estimated_hours=16.50, status="QUEUED")
    assert reread_request["assigned_analyst_id"] is None, (
        "A refused assignment must leave the request unheld"
    )

    reread = validate_success(api.get_analyst(over["id"], QUALITY_MANAGER_HEADERS))
    assert_two_decimal_value(
        reread["assigned_casework_hours"], 0.00, "assigned_casework_hours"
    )
    _rows, meta = validate_paginated(
        api.list_assignments(CASE_MANAGER_HEADERS, {"analyst_id": over["id"]})
    )
    assert_list_meta(meta, expected_total=0)


def _one_statutory_request_raised_on_the_first_of_august(api):
    """A homicide case in custody with a statutory deadline, carrying the only open request in
    the laboratory, raised at the pinned instant.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
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
        agency_case_number="H-2026-1313",
        submitting_agency="METRO PD",
        offense_category="HOMICIDE",
        suspect_in_custody=True,
        statutory_deadline_utc="2026-08-20T00:00:00Z",
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    return case, request


def test_the_backlog_read_one_hundredth_below_the_floor_recommends_nothing(api):
    """Aged 29.99 days and weighted at statutory urgency the index reads 44.99, a hundredth
    short of the floor, so no outsourcing is recommended and the request is still in the first
    aging bucket.

    PRD §3.9: "Alongside them, `p1_open_count` counts the open requests whose case
    `priority_class` is `P1_STATUTORY`, and `outsourcing_recommended` is true exactly when
    `backlog_index` is at least 45.00 — at exactly 45.00 the recommendation is already true."

    Design: Difficulty/boundary_precision_check/backlog_outsourcing_trigger_fires_at_exactly_index_45
    """
    case, request = _one_statutory_request_raised_on_the_first_of_august(api)
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        priority_class="P1_STATUTORY",
    )

    report = validate_success(
        api.get_backlog_report(DIRECTOR_HEADERS, {"as_of_utc": "2026-08-30T23:45:36Z"})
    )
    assert_backlog_report(
        report,
        open_request_count=1,
        backlog_index=44.99,
        bucket_0_29_count=1,
        bucket_30_59_count=0,
        bucket_60_89_count=0,
        bucket_90_plus_count=0,
        p1_open_count=1,
        outsourcing_recommended=False,
    )
    assert_fields(read_request(api, request["id"]), status="QUEUED")


def test_the_backlog_read_at_the_floor_recommends_outsourcing_and_flips_the_bucket(api):
    """Fourteen minutes and twenty-four seconds later the age rounds to 30.00, the index lands
    exactly on 45.00 — which already recommends outsourcing — and the same request moves out of
    the first bucket into the thirty-to-fifty-nine one.

    PRD §3.9: "A request whose rounded age is exactly 30.00 therefore lands in the 30-to-59
    bucket, not the first one, and the four counts always sum to `open_request_count`."

    Design: Difficulty/boundary_precision_check/backlog_outsourcing_trigger_fires_at_exactly_index_45
    """
    _case, _request = _one_statutory_request_raised_on_the_first_of_august(api)

    report = validate_success(
        api.get_backlog_report(DIRECTOR_HEADERS, {"as_of_utc": "2026-08-31T00:00:00Z"})
    )
    assert_backlog_report(
        report,
        open_request_count=1,
        backlog_index=45.00,
        bucket_0_29_count=0,
        bucket_30_59_count=1,
        bucket_60_89_count=0,
        bucket_90_plus_count=0,
        p1_open_count=1,
        outsourcing_recommended=True,
    )


def _two_examiners_who_have_each_submitted_a_test_on_time(api):
    """Two qualified chemists with a submitted proficiency test apiece, both inside the
    deadline so the mark alone decides the grade.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    first = register_analyst(
        api,
        full_name="Ada Nakamura",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    second = register_analyst(
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
    first_test = assign_proficiency_test(
        api,
        analyst_id=first["id"],
        method_id=method["id"],
        test_cycle="2026-Q3",
        due_utc="2026-09-01T00:00:00Z",
    )
    submit_proficiency_test(api, first_test["id"], first["id"])
    second_test = assign_proficiency_test(
        api,
        analyst_id=second["id"],
        method_id=method["id"],
        test_cycle="2026-Q3",
        due_utc="2026-09-01T00:00:00Z",
    )
    submit_proficiency_test(api, second_test["id"], second["id"])
    return first, second, first_test, second_test


def test_a_mark_of_exactly_ninety_passes_and_raises_no_finding(api):
    """The pass cut point is inclusive, so 90.00 grades as a pass, leaves the examiner qualified
    with a clean counter, and documents nothing against her.

    PRD §3.8: "Both thresholds are inclusive at the boundary: 90.00 passes while 89.99 is
    inconclusive, and 70.00 is inconclusive while 69.99 fails."

    Design: Difficulty/boundary_precision_check/proficiency_grade_boundaries_at_exact_pass_and_inconclusive_floors
    """
    first, _second, first_test, _second_test = _two_examiners_who_have_each_submitted_a_test_on_time(
        api
    )

    scored = score_proficiency_test(api, first_test["id"], 90.00)
    assert_fields(scored, result="PASS", status="SCORED", late_submission=False)
    assert_instant_equals(
        scored["scored_at_utc"], "2026-08-01T00:00:00Z", "scored_at_utc"
    )

    reread = validate_success(api.get_analyst(first["id"], QUALITY_MANAGER_HEADERS))
    assert_fields(reread, qualification_state="QUALIFIED", consecutive_pt_failures=0)

    _rows, meta = validate_paginated(
        api.list_nonconformances(QUALITY_MANAGER_HEADERS, {"analyst_id": first["id"]})
    )
    assert_list_meta(meta, expected_total=0)


def test_a_mark_of_eighty_nine_ninety_nine_is_inconclusive_and_files_a_minor_finding(api):
    """One hundredth below the same cut the mark is inconclusive rather than a failure: the
    examiner keeps her standing and her counter, but a minor finding is opened against her with
    a sixty-day corrective-action deadline.

    PRD §3.8: "An `INCONCLUSIVE` result creates a nonconformance with `source` `PT_INCONCLUSIVE`
    and `severity` `MINOR` naming that `analyst_id`; being `MINOR`, it never itself moves a
    qualification state, which is why an inconclusive mark leaves the examiner exactly where they
    were while still creating a documented finding."

    Design: Difficulty/boundary_precision_check/proficiency_grade_boundaries_at_exact_pass_and_inconclusive_floors
    """
    _first, second, _first_test, second_test = _two_examiners_who_have_each_submitted_a_test_on_time(
        api
    )

    scored = score_proficiency_test(api, second_test["id"], 89.99)
    assert_fields(scored, result="INCONCLUSIVE")

    reread = validate_success(api.get_analyst(second["id"], QUALITY_MANAGER_HEADERS))
    assert_fields(reread, qualification_state="QUALIFIED", consecutive_pt_failures=0)
    assert reread["probation_entered_at_utc"] is None, (
        "An inconclusive mark never starts a probation"
    )

    findings, meta = validate_paginated(
        api.list_nonconformances(
            QUALITY_MANAGER_HEADERS,
            {"analyst_id": second["id"], "source": "PT_INCONCLUSIVE"},
        )
    )
    assert_list_meta(meta, expected_total=1)
    assert_fields(
        findings[0], severity="MINOR", status="OPEN", capa_rejection_count=0
    )
    assert_instant_equals(findings[0]["due_utc"], "2026-09-30T00:00:00Z", "due_utc")
