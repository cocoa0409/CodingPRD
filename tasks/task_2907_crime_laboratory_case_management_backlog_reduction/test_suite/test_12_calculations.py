"""The laboratory's arithmetic read one figure at a time: the estimate a request is priced at, the
input set the backlog report draws from, the corrective-action deadlines, the volume tier at its own
threshold, merged vendor custody, and the balancer's ranking figure.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_backlog_report,
    assert_fields,
    assert_instant_equals,
    assert_pricing_chain,
    assert_two_decimal_value,
    assert_vendor_ledger,
    assert_workload,
)
from test_helpers.factories import method_retirement_payload
from test_helpers.fixtures import (
    accept_case,
    administrative_review,
    assign_request,
    auto_assign_request,
    award_engagement,
    complete_analysis,
    create_validated_method,
    log_evidence,
    open_nonconformance,
    raise_request,
    read_request,
    register_analyst,
    register_vendor,
    release_request,
    report_case,
    return_engagement,
    set_clock,
    ship_engagement,
    start_analysis,
    submit_case,
    technical_review,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
)


def test_the_estimate_is_the_method_rate_times_the_count_and_is_snapshotted_once(api):
    """Three lifts under a 2.50-hour method price at 7.50 hours, and that one figure is what the
    assignment snapshots and what the examiner's encumbered ledger moves by.

    PRD §3.3: "On success the request copies its `discipline` from the method — that copy is the
    queue it will sit in for the rest of its life, unaffected by any later method edit — and computes
    its `estimated_hours` as the method's `standard_hours_per_item` multiplied by the `item_count`,
    rounded half up to 2 decimal places."

    PRD §3.4: "Creating the assignment writes an **Assignment** row with `status` `ACTIVE`, its own
    `estimated_hours` snapshotted from the request, `assigned_at_utc` stamped from the logical clock,
    `closed_at_utc` null and `superseded_by_assignment_id` null."

    PRD §3.4: "The examiner's `assigned_casework_hours` is increased by the request's
    `estimated_hours`, which is itself a mutation of the examiner's record and increments their
    `version`."

    Design: Corner/calculations/estimated_hours_is_the_method_rate_times_the_item_count
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Estimate Analyst",
        disciplines=["LATENT_PRINTS"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Cyanoacrylate Fuming and Comparison",
        discipline="LATENT_PRINTS",
        standard_hours_per_item=2.50,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="LP-CA-01",
        validation_study_item_count=20,
        precision_cv_pct=3.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0201",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Three tape lifts in one sealed envelope",
        item_type="LATENT_LIFT",
        seal_intact=True,
    )
    accept_case(api, case["id"])

    request = raise_request(api, case["id"], item["id"], method["id"], item_count=3)
    assert_fields(
        request, estimated_hours=7.50, discipline="LATENT_PRINTS", item_count=3
    )

    assignment = assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )
    assert_fields(assignment, estimated_hours=7.50, status="ACTIVE")
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=7.50,
    )


def test_the_backlog_report_draws_only_on_requests_still_owed_to_somebody(api):
    """Three requests raised on the same instant, one released and one cancelled: the report counts
    the single survivor and its index is that survivor's own weighted age of ten days, not an average
    over three rows.

    PRD §3.9: "The population is every examination request whose `status` is not `RELEASED` and not
    `CANCELLED` — that is, every request still owed to somebody, including those sitting at a vendor
    — restricted to the named discipline when one is given, and its size is reported as
    `open_request_count`."

    PRD §3.9: "That rounded age is then weighted by the urgency of its case: 1.50 for
    `P1_STATUTORY`, 1.25 for `P2_VIOLENT` and 1.00 for `P3_ROUTINE`, and the product is itself
    rounded half up to 2 decimal places."

    PRD §3.9: "The `backlog_index` is the mean of those weighted ages — their sum divided by
    `open_request_count`, rounded half up to 2 decimal places — and is exactly 0.00 when there are no
    open requests at all, with no division attempted."

    PRD §3.9: "Alongside them, `p1_open_count` counts the open requests whose case `priority_class`
    is `P1_STATUTORY`, and `outsourcing_recommended` is true exactly when `backlog_index` is at least
    45.00 — at exactly 45.00 the recommendation is already true."

    Design: Corner/calculations/backlog_report_counts_only_the_requests_that_are_still_open
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    author = register_analyst(
        api,
        full_name="Filter Author",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Filter Reviewer",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    kept_method = create_validated_method(
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
    retired_method = create_validated_method(
        api,
        name="Presumptive Colour Test Battery",
        discipline="CHEMISTRY",
        standard_hours_per_item=1.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-COL-01",
        validation_study_item_count=20,
        precision_cv_pct=4.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0202",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    items = [
        log_evidence(
            api,
            case["id"],
            item_number=str(number),
            item_description=f"Sealed packet {number}",
            item_type="CHEMICAL",
            seal_intact=True,
        )
        for number in (1, 2, 3)
    ]
    accept_case(api, case["id"])
    released = raise_request(api, case["id"], items[0]["id"], kept_method["id"], item_count=1)
    cancelled = raise_request(api, case["id"], items[1]["id"], retired_method["id"], item_count=1)
    survivor = raise_request(api, case["id"], items[2]["id"], kept_method["id"], item_count=1)
    assign_request(api, released["id"], author["id"], expected_version=released["version"])
    release_request(api, released["id"], author["id"], reviewer["id"], actual_hours=1.00)
    validate_success(
        api.retire_method(
            retired_method["id"],
            method_retirement_payload("Withdrawn from the accredited scope."),
            QUALITY_MANAGER_HEADERS,
        )
    )
    set_clock(api, "2026-08-11T00:00:00Z")

    assert_fields(read_request(api, released["id"]), status="RELEASED")
    assert_fields(read_request(api, cancelled["id"]), status="CANCELLED")
    assert_fields(read_request(api, survivor["id"]), status="QUEUED")

    report = validate_success(api.get_backlog_report(QUALITY_MANAGER_HEADERS))
    assert_backlog_report(
        report,
        as_of_utc="2026-08-11T00:00:00Z",
        open_request_count=1,
        backlog_index=10.00,
        bucket_0_29_count=1,
        bucket_30_59_count=0,
        bucket_60_89_count=0,
        bucket_90_plus_count=0,
        p1_open_count=0,
        outsourcing_recommended=False,
    )


def test_each_severity_tier_reads_its_own_corrective_action_allowance(api):
    """Three findings opened on the same instant take three different deadlines — sixty, thirty and
    ten days — and none of them is overdue on the day it is raised.

    PRD §3.8: "Every finding carries a corrective-action deadline. Its `due_utc` is its
    `opened_at_utc` advanced by the service-level allowance for its severity: 60 days for `MINOR`, 30
    days for `MAJOR`, 10 days for `CRITICAL`."

    PRD §3.8: "A new finding has `status` `OPEN`, `capa_rejection_count` 0, `overdue` false,
    `opened_at_utc` stamped from the logical clock, and no `root_cause_category`,
    `corrective_action_plan` or `closed_at_utc`."

    Design: Corner/calculations/capa_due_date_reads_the_sla_constant_for_each_severity_tier
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    minor = open_nonconformance(
        api,
        source="ACCREDITATION_AUDIT",
        severity="MINOR",
        description="Balance calibration record filed late.",
    )
    major = open_nonconformance(
        api,
        source="ACCREDITATION_AUDIT",
        severity="MAJOR",
        description="Uncontrolled copy of a procedure in use at the bench.",
    )
    critical = open_nonconformance(
        api,
        source="ACCREDITATION_AUDIT",
        severity="CRITICAL",
        description="Reference standard used past its expiry.",
    )

    assert_instant_equals(minor["due_utc"], "2026-09-30T00:00:00Z", "due_utc")
    assert_instant_equals(major["due_utc"], "2026-08-31T00:00:00Z", "due_utc")
    assert_instant_equals(critical["due_utc"], "2026-08-11T00:00:00Z", "due_utc")
    for finding in (minor, major, critical):
        assert_instant_equals(
            finding["opened_at_utc"], "2026-08-01T00:00:00Z", "opened_at_utc"
        )
        assert_fields(finding, status="OPEN", capa_rejection_count=0, overdue=False)
        assert finding["analyst_id"] is None, (
            "A finding raised against no examiner names none"
        )
        assert finding["examination_request_id"] is None, (
            "A finding raised against no piece of work names none"
        )


def test_a_finding_becomes_overdue_only_one_second_past_its_deadline(api):
    """Read one second before its deadline and at the deadline itself the finding is not overdue; a
    second later it is, and the stored deadline never moves however the clock is wound.

    PRD §3.8: "Its `overdue` flag is true exactly when the current logical instant is strictly after
    `due_utc` and its `status` is neither `CLOSED` nor `VOIDED`; the comparison is strict, so a
    finding read at precisely its `due_utc` is not yet overdue, and a closed finding is never overdue
    however long it took."

    PRD §3.8: "Every finding carries a corrective-action deadline. Its `due_utc` is its
    `opened_at_utc` advanced by the service-level allowance for its severity: 60 days for `MINOR`, 30
    days for `MAJOR`, 10 days for `CRITICAL`."

    Design: Corner/calculations/capa_overdue_flag_turns_over_one_second_after_the_due_instant
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    finding = open_nonconformance(
        api,
        source="ACCREDITATION_AUDIT",
        severity="MINOR",
        description="Temperature log gap on the drying cabinet.",
    )
    assert_instant_equals(finding["due_utc"], "2026-09-30T00:00:00Z", "due_utc")

    readings = {}
    for label, instant in (
        ("before", "2026-09-29T23:59:59Z"),
        ("at", "2026-09-30T00:00:00Z"),
        ("after", "2026-09-30T00:00:01Z"),
    ):
        set_clock(api, instant)
        read = validate_success(
            api.get_nonconformance(finding["id"], QUALITY_MANAGER_HEADERS)
        )
        assert_instant_equals(read["due_utc"], "2026-09-30T00:00:00Z", "due_utc")
        assert_fields(read, status="OPEN")
        assert read["closed_at_utc"] is None, "An open finding carries no closure stamp"
        readings[label] = read["overdue"]

    assert readings["before"] is False, "A finding read before its deadline is not overdue"
    assert readings["at"] is False, "A finding read at its deadline is not yet overdue"
    assert readings["after"] is True, "A finding read past its deadline is overdue"


def test_the_volume_tier_is_taken_at_the_threshold_and_not_a_cent_below(api):
    """Two awards from one vendor straddle the first tier: a basis of exactly 100000 cents earns the
    four-percent discount, a basis of 75000 earns none, and the encumbrance is the sum of the two
    awarded figures.

    PRD §3.7: "**Step three:** `tier_basis_cents` is `base_amount_cents` plus `rush_surcharge_cents`
    — this rush-inclusive figure, and never the bare base, is the basis the tier is chosen from, and
    it is pinned onto the engagement so the choice is auditable."

    PRD §3.7: "**Step four:** `volume_discount_pct` is 0.12 when `tier_basis_cents` is at least
    500000 cents, otherwise 0.08 when it is at least 250000 cents, otherwise 0.04 when it is at least
    100000 cents, otherwise 0.00."

    PRD §3.7: "**Step six:** `award_amount_cents` is `tier_basis_cents` minus
    `discount_amount_cents`, and that is the figure the vendor's encumbrance carries."

    Design: Corner/calculations/vendor_award_selects_the_first_volume_tier_at_exactly_the_threshold
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    vendor = register_vendor(
        api,
        name="Tier Boundary Forensics LLC",
        accredited_disciplines=["DIGITAL"],
        accreditation_expires_at_utc="2027-08-01T00:00:00Z",
        concurrent_case_capacity=5,
        unit_price_cents=25000,
        rush_surcharge_pct=0.00,
        contract_ceiling_cents=1000000,
    )
    method = create_validated_method(
        api,
        name="Mobile Device Logical Extraction",
        discipline="DIGITAL",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="DF-MOB-01",
        validation_study_item_count=12,
        precision_cv_pct=1.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0203",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed handset bag one",
        item_type="DIGITAL_DEVICE",
        seal_intact=True,
    )
    second_item = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed handset bag two",
        item_type="DIGITAL_DEVICE",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    at_threshold = raise_request(
        api, case["id"], first_item["id"], method["id"], item_count=4
    )
    below_threshold = raise_request(
        api, case["id"], second_item["id"], method["id"], item_count=3
    )

    discounted = award_engagement(
        api,
        at_threshold["id"],
        vendor["id"],
        window_start_utc="2026-08-02T00:00:00Z",
        window_end_utc="2026-08-12T00:00:00Z",
        rush_flag=False,
    )
    undiscounted = award_engagement(
        api,
        below_threshold["id"],
        vendor["id"],
        window_start_utc="2026-08-03T00:00:00Z",
        window_end_utc="2026-08-13T00:00:00Z",
        rush_flag=False,
    )

    assert_pricing_chain(
        discounted,
        base_amount_cents=100000,
        rush_surcharge_cents=0,
        tier_basis_cents=100000,
        volume_discount_pct=0.04,
        discount_amount_cents=4000,
        award_amount_cents=96000,
    )
    assert_fields(discounted, item_count=4, status="AWARDED")
    assert_instant_equals(
        discounted["awarded_at_utc"], "2026-08-01T00:00:00Z", "awarded_at_utc"
    )
    assert_pricing_chain(
        undiscounted,
        base_amount_cents=75000,
        rush_surcharge_cents=0,
        tier_basis_cents=75000,
        volume_discount_pct=0.00,
        discount_amount_cents=0,
        award_amount_cents=75000,
    )
    assert_vendor_ledger(
        validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS)),
        encumbered_cents=171000,
        spent_cents=0,
    )
    assert_fields(read_request(api, at_threshold["id"]), status="OUTSOURCED")
    assert_fields(read_request(api, below_threshold["id"]), status="OUTSOURCED")


def test_overlapping_vendor_custody_of_one_case_is_deducted_once(api):
    """Two engagements of the same case were out of house over overlapping periods, so the union of
    fifteen days comes off the twenty-four calendar days once — never the thirty days the two periods
    add up to — while each engagement still reports its own ten days.

    PRD §3.7: "The engagement moves to the terminal `RETURNED` with `returned_at_utc` stamped; its
    `custody_days` is the interval from `awarded_at_utc` to `returned_at_utc` expressed as a
    fractional-day figure — whole seconds divided by 86400, rounded half up to 2 decimal places — and
    its `variance_cents` is `final_invoice_cents` minus `award_amount_cents`, which is negative when
    the vendor under-billed."

    PRD §3.9: "Merge them as closed intervals: windows that overlap merge, and windows that merely
    touch — one ending at the exact instant the next begins — also merge into a single continuous
    period, because the property was in vendor hands throughout."

    PRD §3.9: "The merge is what makes the figure honest: two requests of the same case sent to
    vendors over overlapping windows spent one shared stretch of calendar out of house, and that
    stretch is subtracted once, never twice."

    Design: Corner/calculations/vendor_custody_windows_of_one_case_are_merged_not_summed
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    vendor = register_vendor(
        api,
        name="Union Window Trace Labs",
        accredited_disciplines=["TRACE"],
        accreditation_expires_at_utc="2027-08-01T00:00:00Z",
        concurrent_case_capacity=5,
        unit_price_cents=25000,
        rush_surcharge_pct=0.00,
        contract_ceiling_cents=1000000,
    )
    reviewer = register_analyst(
        api,
        full_name="Union Window Reviewer",
        disciplines=["TRACE"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="FTIR Fibre Comparison",
        discipline="TRACE",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="TR-FTIR-01",
        validation_study_item_count=16,
        precision_cv_pct=2.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0204",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed fibre lift A",
        item_type="TRACE_MEDIA",
        seal_intact=True,
    )
    second_item = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed fibre lift B",
        item_type="TRACE_MEDIA",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    first_request = raise_request(api, case["id"], first_item["id"], method["id"], item_count=1)
    second_request = raise_request(api, case["id"], second_item["id"], method["id"], item_count=1)

    set_clock(api, "2026-08-05T00:00:00Z")
    first_engagement = award_engagement(
        api,
        first_request["id"],
        vendor["id"],
        window_start_utc="2026-08-05T00:00:00Z",
        window_end_utc="2026-08-16T00:00:00Z",
        rush_flag=False,
    )
    ship_engagement(api, first_engagement["id"])

    set_clock(api, "2026-08-10T00:00:00Z")
    second_engagement = award_engagement(
        api,
        second_request["id"],
        vendor["id"],
        window_start_utc="2026-08-10T00:00:00Z",
        window_end_utc="2026-08-21T00:00:00Z",
        rush_flag=False,
    )
    ship_engagement(api, second_engagement["id"])

    set_clock(api, "2026-08-15T00:00:00Z")
    return_engagement(api, first_engagement["id"], final_invoice_cents=25000)
    set_clock(api, "2026-08-20T00:00:00Z")
    return_engagement(api, second_engagement["id"], final_invoice_cents=25000)
    for request_id in (first_request["id"], second_request["id"]):
        technical_review(api, request_id, reviewer["id"], "AGREE")
        administrative_review(api, request_id, "APPROVE")
    set_clock(api, "2026-08-25T00:00:00Z")

    reported = report_case(api, case["id"])
    assert_fields(reported, workflow_status="REPORTED", gross_turnaround_days=24.00)
    assert_instant_equals(
        reported["reported_at_utc"], "2026-08-25T00:00:00Z", "reported_at_utc"
    )
    assert_two_decimal_value(reported["net_turnaround_days"], 9.00, "net_turnaround_days")
    assert round(reported["net_turnaround_days"], 2) != 4.00, (
        "Summing the two custody periods instead of merging them would deduct thirty days"
    )

    for engagement_id in (first_engagement["id"], second_engagement["id"]):
        engagement = validate_success(
            api.get_vendor_engagement(engagement_id, CASE_MANAGER_HEADERS)
        )
        assert_fields(engagement, status="RETURNED", custody_days=10.00)
    assert_vendor_ledger(
        validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS)),
        encumbered_cents=0,
        spent_cents=50000,
    )


def test_the_balancer_ranks_on_utilisation_percent_not_on_free_hours(api):
    """The examiner with the larger denominator wins: the same eight-hour request would put one
    candidate at 25.00 percent and the other at 40.00, so the balancer takes the first and marks the
    assignment as its own choice.

    PRD §3.4: "An examiner's available hours are their `weekly_capacity_hours` minus their
    `training_hours_per_week`, floored at 0.00 and rounded half up to 2 decimal places — training
    time is carved out of capacity before casework is considered."

    PRD §3.4: "Surviving candidates are ordered by post-assignment projected utilisation ascending,
    compared at 2 decimal places."

    PRD §3.4: "The first candidate after ordering is selected, receives a new `ACTIVE` assignment
    with `assignment_reason` `AUTO_BALANCED`, and the request moves `QUEUED` → `ASSIGNED` with the
    same hour encumbrance, `assigned_analyst_id` write and case rollup as a manual assignment."

    PRD §3.4: "its numerator, `realized_load_hours`, ranges over the examiner's assignments whose
    `status` is `ACTIVE` or `COMPLETED` and takes, for each one, the owning request's
    `actual_hours_logged` whenever that figure is not null and the assignment's snapshotted
    `estimated_hours` otherwise, summing and rounding half up to 2 decimal places" — the fresh
    ACTIVE assignment has no logged hours yet, so it contributes its snapshotted 8.00 estimate and
    the realized variant reads the same 25.00 percent as the projected one.

    Design: Corner/calculations/auto_assign_picks_the_lowest_projected_utilization_candidate
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    roomy = register_analyst(
        api,
        full_name="Auto Big Capacity",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    tight = register_analyst(
        api,
        full_name="Auto Small Capacity",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=20.00,
        training_hours_per_week=0.00,
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
        agency_case_number="O-2026-0205",
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

    assignment = auto_assign_request(api, request["id"])

    assert_fields(
        assignment,
        analyst_id=roomy["id"],
        assignment_reason="AUTO_BALANCED",
        status="ACTIVE",
        estimated_hours=8.00,
    )
    assert assignment["analyst_id"] != tight["id"], (
        "The candidate with fewer available hours must not be chosen"
    )
    assert_fields(
        read_request(api, request["id"]),
        status="ASSIGNED",
        assigned_analyst_id=roomy["id"],
    )
    assert_fields(
        validate_success(api.get_analyst(roomy["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=8.00,
    )
    assert_fields(
        validate_success(api.get_analyst(tight["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=0.00,
    )
    assert_workload(
        validate_success(api.get_analyst_workload(roomy["id"], CASE_MANAGER_HEADERS)),
        available_hours=32.00,
        projected_load_hours=8.00,
        projected_utilization_pct=25.00,
        realized_load_hours=8.00,
        realized_utilization_pct=25.00,
    )


def test_completion_moves_the_hours_from_the_projected_variant_to_the_realized_one(api):
    """Before the bench work is closed both variants read the same twelve encumbered hours; the
    completion drops the finished eight out of the projected figure and puts the nine and a quarter
    actually logged into the realized one.

    PRD §3.4: "The **projected** variant answers "what is encumbered right now": its numerator,
    `projected_load_hours`, is the sum of the snapshotted `estimated_hours` of the examiner's
    assignments whose `status` is `ACTIVE`, rounded half up to 2 decimal places, and
    `projected_utilization_pct` is that numerator divided by the available hours, multiplied by 100
    and rounded half up to 2 decimal places — or exactly 0.00 when the available hours are 0.00."

    PRD §3.4: "The **realized** variant answers "what did the work actually consume": its numerator,
    `realized_load_hours`, ranges over the examiner's assignments whose `status` is `ACTIVE` or
    `COMPLETED` and takes, for each one, the owning request's `actual_hours_logged` whenever that
    figure is not null and the assignment's snapshotted `estimated_hours` otherwise, summing and
    rounding half up to 2 decimal places; `realized_utilization_pct` is derived from it in the same
    way, and is likewise 0.00 when the available hours are 0.00."

    Design: Corner/calculations/completing_analysis_moves_the_hours_from_the_projected_to_the_realized_variant
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Reconciliation Analyst",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0206",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet X",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    second_item = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed packet Y",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    finishing = raise_request(api, case["id"], first_item["id"], method["id"], item_count=2)
    surviving = raise_request(api, case["id"], second_item["id"], method["id"], item_count=1)
    finishing_assignment = assign_request(
        api, finishing["id"], examiner["id"], expected_version=finishing["version"]
    )
    surviving_assignment = assign_request(
        api, surviving["id"], examiner["id"], expected_version=surviving["version"]
    )
    start_analysis(api, finishing["id"], examiner["id"])

    before = validate_success(
        api.get_analyst_workload(examiner["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_workload(before, projected_load_hours=12.00, realized_load_hours=12.00)

    complete_analysis(
        api, finishing["id"], examiner["id"], actual_hours=9.25, evidence_consumed=False
    )

    after = validate_success(
        api.get_analyst_workload(examiner["id"], QUALITY_MANAGER_HEADERS)
    )
    assert_workload(
        after,
        available_hours=32.00,
        projected_load_hours=4.00,
        projected_utilization_pct=12.50,
        realized_load_hours=13.25,
        realized_utilization_pct=41.41,
        active_assignment_count=1,
    )
    assert round(after["realized_load_hours"], 2) != 12.00, (
        "The completed assignment must contribute its logged hours, not its estimate"
    )
    assert_fields(
        validate_success(api.get_assignment(finishing_assignment["id"], CASE_MANAGER_HEADERS)),
        status="COMPLETED",
        estimated_hours=8.00,
    )
    assert_fields(
        validate_success(api.get_assignment(surviving_assignment["id"], CASE_MANAGER_HEADERS)),
        status="ACTIVE",
        estimated_hours=4.00,
    )
    assert_fields(
        validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=4.00,
    )
    assert_fields(read_request(api, finishing["id"]), actual_hours_logged=9.25)
    assert read_request(api, surviving["id"])["actual_hours_logged"] is None, (
        "A request whose bench work has not been completed logs no hours"
    )
