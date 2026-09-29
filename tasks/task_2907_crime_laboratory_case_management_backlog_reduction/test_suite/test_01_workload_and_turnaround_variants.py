"""The two paired read models that answer the same question two different ways:
an examiner's projected versus realized utilisation, and a case's gross versus net
turnaround.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.assertions import (
    assert_fields,
    assert_two_decimal_value,
    assert_workload,
)
from test_helpers.factories import (
    administrative_review_payload,
    case_report_payload,
)
from test_helpers.fixtures import (
    accept_case,
    assign_request,
    award_engagement,
    carry_to_tech_review,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    register_vendor,
    return_engagement,
    set_clock,
    ship_engagement,
    submit_case,
    technical_review,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    QUALITY_MANAGER_HEADERS,
)


def _one_completed_and_one_active_assignment(api):
    """An examiner holding one finished request that logged 24.00 hours against a
    6.00-hour estimate, plus one request still on the bench estimated at 6.00.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    analyst = register_analyst(
        api,
        full_name="Ada Nakamura",
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
        accreditation_scope_code="CHEM-GCMS-01",
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-0101",
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

    finished = raise_request(
        api, case["id"], first_item["id"], method["id"], item_count=3
    )
    completed_assignment = assign_request(
        api, finished["id"], analyst["id"], expected_version=finished["version"]
    )
    carry_to_tech_review(api, finished["id"], analyst["id"], actual_hours=24.00)

    open_request = raise_request(
        api, case["id"], second_item["id"], method["id"], item_count=3
    )
    active_assignment = assign_request(
        api, open_request["id"], analyst["id"], expected_version=open_request["version"]
    )
    return {
        "analyst": analyst,
        "finished_request": finished,
        "open_request": open_request,
        "completed_assignment": completed_assignment,
        "active_assignment": active_assignment,
    }


def test_projected_utilisation_counts_only_the_active_assignment(api):
    """The projected numerator drops the completed assignment out entirely, so
    6.00 encumbered hours over 32.00 available reads as 18.75 percent.

    PRD §3.4: "The **projected** variant answers "what is encumbered right now": its
    numerator, `projected_load_hours`, is the sum of the snapshotted `estimated_hours`
    of the examiner's assignments whose `status` is `ACTIVE`, rounded half up to 2
    decimal places, and `projected_utilization_pct` is that numerator divided by the
    available hours, multiplied by 100 and rounded half up to 2 decimal places — or
    exactly 0.00 when the available hours are 0.00."

    Design: Difficulty/dual_variant_calc/analyst_workload_projected_estimate_vs_realized_logged
    """
    state = _one_completed_and_one_active_assignment(api)

    workload = validate_success(
        api.get_analyst_workload(state["analyst"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_workload(
        workload,
        available_hours=32.00,
        projected_load_hours=6.00,
        projected_utilization_pct=18.75,
        active_assignment_count=1,
        assigned_casework_hours=6.00,
    )

    analyst = validate_success(
        api.get_analyst(state["analyst"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_two_decimal_value(
        analyst["assigned_casework_hours"], 6.00, "assigned_casework_hours"
    )

    completed = validate_success(
        api.get_assignment(state["completed_assignment"]["id"], CASE_MANAGER_HEADERS)
    )
    active = validate_success(
        api.get_assignment(state["active_assignment"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(completed, status="COMPLETED")
    assert_fields(active, status="ACTIVE")


def test_realized_utilisation_adds_the_completed_work_back_at_logged_hours(api):
    """The realized numerator reinstates the completed assignment at the 24.00 hours
    actually reported, so the same 32.00 available hours read as 93.75 percent.

    PRD §3.4: "The **realized** variant answers "what did the work actually consume":
    its numerator, `realized_load_hours`, ranges over the examiner's assignments whose
    `status` is `ACTIVE` or `COMPLETED` and takes, for each one, the owning request's
    `actual_hours_logged` whenever that figure is not null and the assignment's
    snapshotted `estimated_hours` otherwise, summing and rounding half up to 2 decimal
    places; `realized_utilization_pct` is derived from it in the same way, and is
    likewise 0.00 when the available hours are 0.00."

    Design: Difficulty/dual_variant_calc/analyst_workload_projected_estimate_vs_realized_logged
    """
    state = _one_completed_and_one_active_assignment(api)

    workload = validate_success(
        api.get_analyst_workload(state["analyst"]["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_workload(
        workload,
        available_hours=32.00,
        realized_load_hours=30.00,
        realized_utilization_pct=93.75,
        casework_training_ratio=0.75,
    )
    assert workload["projected_utilization_pct"] != workload["realized_utilization_pct"], (
        "The two utilisation variants must not collapse onto one figure"
    )

    finished = read_request(api, state["finished_request"]["id"])
    still_open = read_request(api, state["open_request"]["id"])
    assert_two_decimal_value(
        finished["actual_hours_logged"], 24.00, "actual_hours_logged"
    )
    assert still_open["actual_hours_logged"] is None, (
        "A request whose bench work has not been completed logs no hours"
    )


def _reported_case_with_one_returned_vendor_window(api):
    """A single-request case sent to a vendor for a closed fifteen-day window, brought
    back, released, and reported forty days after it arrived.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
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
        accreditation_scope_code="CHEM-GCMS-01",
    )
    vendor = register_vendor(
        api,
        name="Cascade Reference Laboratory",
        accredited_disciplines=["CHEMISTRY"],
        accreditation_expires_at_utc="2027-01-01T00:00:00Z",
        concurrent_case_capacity=2,
        unit_price_cents=45000,
        rush_surcharge_pct=0.00,
        contract_ceiling_cents=10000000,
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-0202",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=2)

    set_clock(api, "2026-08-05T00:00:00Z")
    engagement = award_engagement(
        api,
        request["id"],
        vendor["id"],
        window_start_utc="2026-08-05T00:00:00Z",
        window_end_utc="2026-08-20T00:00:00Z",
        rush_flag=False,
    )
    ship_engagement(api, engagement["id"])

    set_clock(api, "2026-08-20T00:00:00Z")
    return_engagement(api, engagement["id"], final_invoice_cents=90000)
    technical_review(api, request["id"], reviewer["id"], "AGREE")
    get_success_data(
        api.administrative_review(
            request["id"], administrative_review_payload("APPROVE"), CASE_MANAGER_HEADERS
        ),
        201,
    )

    set_clock(api, "2026-09-10T00:00:00Z")
    return {"case": case, "request": request, "engagement": engagement}


def test_gross_turnaround_counts_the_whole_calendar_wait(api):
    """From arrival on 2026-08-01 to the report on 2026-09-10 is forty calendar days,
    and the gross figure counts every one of them.

    PRD §3.9: "`gross_turnaround_days` is the elapsed calendar time the agency waited:
    the interval from the case's `received_at_utc` to its `reported_at_utc`, taken in
    whole seconds, divided by 86400, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/case_turnaround_gross_calendar_vs_net_lab_custody
    """
    state = _reported_case_with_one_returned_vendor_window(api)

    reported = validate_success(
        api.report_case(
            state["case"]["id"], case_report_payload(), CASE_MANAGER_HEADERS
        )
    )
    assert_fields(
        reported,
        workflow_status="REPORTED",
        reported_at_utc="2026-09-10T00:00:00Z",
        gross_turnaround_days=40.00,
    )


def test_net_turnaround_deducts_the_returned_vendor_custody_period(api):
    """The fifteen days the property spent in the vendor's hands come off the forty,
    leaving twenty-five days the laboratory is accountable for.

    PRD §3.9: "Then `net_turnaround_days` is `gross_turnaround_days` minus that figure,
    rounded half up to 2 decimal places, and floored at 0.00 so it is never negative."

    Design: Difficulty/dual_variant_calc/case_turnaround_gross_calendar_vs_net_lab_custody
    """
    state = _reported_case_with_one_returned_vendor_window(api)

    reported = validate_success(
        api.report_case(
            state["case"]["id"], case_report_payload(), CASE_MANAGER_HEADERS
        )
    )
    assert_fields(reported, gross_turnaround_days=40.00, net_turnaround_days=25.00)
    assert_two_decimal_value(
        reported["gross_turnaround_days"] - reported["net_turnaround_days"],
        15.00,
        "vendor custody deduction",
    )

    engagement = validate_success(
        api.get_vendor_engagement(state["engagement"]["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(engagement, status="RETURNED", custody_days=15.00, variance_cents=0)

    request = read_request(api, state["request"]["id"])
    assert_two_decimal_value(
        request["vendor_custody_days"], 15.00, "vendor_custody_days"
    )
    assert request["assigned_analyst_id"] is None, (
        "An outsourced request never had an in-house holder"
    )
