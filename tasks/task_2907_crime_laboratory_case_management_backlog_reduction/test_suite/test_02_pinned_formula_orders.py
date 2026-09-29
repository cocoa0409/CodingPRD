"""Three calculations whose stage order is pinned, each verified against the figure
the wrong order would produce.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_backlog_report,
    assert_fields,
    assert_pricing_chain,
    assert_vendor_ledger,
)
from test_helpers.factories import case_payload
from test_helpers.fixtures import (
    accept_case,
    award_engagement,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_vendor,
    set_clock,
    submit_case,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
)


def _submit_homicide_in_custody(api):
    """A homicide in custody, nineteen days from its statutory deadline and forty-five
    days from trial, submitted at the clock origin.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    return validate_success(
        api.create_case(
            case_payload(
                agency_case_number="H-2026-0001",
                submitting_agency="METRO PD",
                offense_category="HOMICIDE",
                suspect_in_custody=True,
                statutory_deadline_utc="2026-08-20T00:00:00Z",
                court_date_utc="2026-09-15T00:00:00Z",
            ),
            TECHNICIAN_HEADERS,
        ),
        201,
    )


def test_violence_multiplier_lifts_only_the_severity_and_custody_subtotal(api):
    """A homicide in custody nineteen days from its deadline and forty-five days from
    trial scores 85.00: the 1.10 multiplier is applied to the 55-point severity and
    custody subtotal alone, never to the blended temporal points.

    PRD §3.1: "The violence multiplier applies to the severity-plus-custody subtotal
    only; it never touches the temporal points."

    Design: Difficulty/combinatorial_formula/case_priority_score_violence_multiplier_before_temporal_blend
    """
    case = _submit_homicide_in_custody(api)

    assert_fields(case, violent_crime_flag=True, priority_score=85.00)
    assert abs(case["priority_score"] - 90.20) > 0.005, (
        "Multiplying the whole point total by 1.10 would score 90.20"
    )


def test_queue_class_of_a_scored_case_follows_the_deadline_distance(api):
    """The same submission lands in the statutory queue on the strength of its
    nineteen-day deadline, with no override in force and both status axes at their
    intake defaults.

    PRD §3.1: "Absent an override, the class is `P1_STATUTORY` when the days-to-deadline
    figure is not null and is at most 30 days; otherwise `P2_VIOLENT` when the
    `violent_crime_flag` is true; otherwise `P3_ROUTINE`."

    Design: Difficulty/combinatorial_formula/case_priority_score_violence_multiplier_before_temporal_blend
    """
    case = _submit_homicide_in_custody(api)

    assert_fields(
        case,
        priority_class="P1_STATUTORY",
        received_at_utc="2026-08-01T00:00:00Z",
        workflow_status="SUBMITTED",
        discovery_status="NONE",
    )
    assert case["priority_override_class"] is None, "No override is in force at intake"


def _rush_award_of_five_items(api):
    """A five-item chemistry request awarded to a vendor whose rush surcharge is fifteen
    percent, under a rush flag.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
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
        rush_surcharge_pct=0.15,
        contract_ceiling_cents=10000000,
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-0303",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=5)
    engagement = award_engagement(
        api,
        request["id"],
        vendor["id"],
        window_start_utc="2026-08-05T00:00:00Z",
        window_end_utc="2026-08-25T00:00:00Z",
        rush_flag=True,
    )
    return {"vendor": vendor, "case": case, "request": request, "engagement": engagement}


def test_rush_surcharge_enters_the_tier_basis_before_the_volume_discount(api):
    """A five-item rush award prices at 238050 cents because the surcharge is added
    before the tier is chosen and the discount is taken last.

    PRD §3.7: "**Step three:** `tier_basis_cents` is `base_amount_cents` plus
    `rush_surcharge_cents` — this rush-inclusive figure, and never the bare base, is the
    basis the tier is chosen from, and it is pinned onto the engagement so the choice is
    auditable."

    Design: Difficulty/combinatorial_formula/vendor_award_rush_surcharge_enters_tier_basis_before_discount
    """
    state = _rush_award_of_five_items(api)
    engagement = state["engagement"]

    assert engagement["item_count"] == 5
    assert_pricing_chain(
        engagement,
        base_amount_cents=225000,
        rush_surcharge_cents=33750,
        tier_basis_cents=258750,
        volume_discount_pct=0.08,
        discount_amount_cents=20700,
        award_amount_cents=238050,
    )
    assert engagement["award_amount_cents"] != 248400, (
        "Discounting the base before surcharging would award 248400 cents"
    )


def test_award_encumbers_the_vendor_and_sends_the_request_out_of_house(api):
    """The figure the pricing chain produced is the figure the vendor's encumbrance
    carries, while the request leaves the queue for the vendor and the case moves into
    progress.

    PRD §3.7: "The award then increments the vendor's `encumbered_cents` by
    `award_amount_cents`."

    Design: Difficulty/combinatorial_formula/vendor_award_rush_surcharge_enters_tier_basis_before_discount
    """
    state = _rush_award_of_five_items(api)

    assert_fields(state["engagement"], status="AWARDED")
    assert_vendor_ledger(
        validate_success(api.get_vendor(state["vendor"]["id"], CASE_MANAGER_HEADERS)),
        encumbered_cents=238050,
        spent_cents=0,
    )
    assert_fields(read_request(api, state["request"]["id"]), status="OUTSOURCED")
    assert_fields(
        validate_success(api.get_case(state["case"]["id"], CASE_MANAGER_HEADERS)),
        workflow_status="IN_PROGRESS",
    )


def _one_statutory_request_aged_ten_and_a_bit_days(api):
    """A single open statutory request raised at the clock origin, which is the whole
    open population of the laboratory.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
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
        agency_case_number="H-2026-0404",
        submitting_agency="METRO PD",
        offense_category="HOMICIDE",
        suspect_in_custody=True,
        statutory_deadline_utc="2026-08-20T00:00:00Z",
        court_date_utc="2026-09-15T00:00:00Z",
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    return {"case": case, "request": request}


def test_backlog_index_rounds_each_age_before_it_is_weighted(api):
    """A single statutory request aged 10.005 days indexes at 15.02, because the age is
    rounded to 10.01 before the 1.50 weight is applied.

    PRD §3.9: "Both rounding steps are required and neither may be skipped: age is
    rounded before weighting, each weighted age is rounded before summing, and the mean
    is rounded at the end."

    Design: Difficulty/combinatorial_formula/backlog_index_rounds_each_request_age_before_weighting
    """
    _one_statutory_request_aged_ten_and_a_bit_days(api)

    report = validate_success(
        api.get_backlog_report(
            QUALITY_MANAGER_HEADERS, {"as_of_utc": "2026-08-11T00:07:12Z"}
        )
    )

    assert_backlog_report(
        report,
        as_of_utc="2026-08-11T00:07:12Z",
        open_request_count=1,
        backlog_index=15.02,
    )
    assert abs(report["backlog_index"] - 15.01) > 0.005, (
        "Weighting the unrounded age would index at 15.01"
    )


def test_the_rounded_age_also_decides_the_bucket_and_the_recommendation(api):
    """The very same rounded age places the request in the first bucket, and an index of
    15.02 is far short of the outsourcing threshold.

    PRD §3.9: "The same rounded ages populate four aging buckets, each half-open at its
    upper edge so every request falls in exactly one: `bucket_0_29_count` for ages from
    0.00 up to but excluding 30.00, `bucket_30_59_count` for 30.00 up to but excluding
    60.00, `bucket_60_89_count` for 60.00 up to but excluding 90.00, and
    `bucket_90_plus_count` for 90.00 and above."

    Design: Difficulty/combinatorial_formula/backlog_index_rounds_each_request_age_before_weighting
    """
    _one_statutory_request_aged_ten_and_a_bit_days(api)

    report = validate_success(
        api.get_backlog_report(
            QUALITY_MANAGER_HEADERS, {"as_of_utc": "2026-08-11T00:07:12Z"}
        )
    )

    assert_backlog_report(
        report,
        bucket_0_29_count=1,
        bucket_30_59_count=0,
        bucket_60_89_count=0,
        bucket_90_plus_count=0,
        p1_open_count=1,
        outsourcing_recommended=False,
    )
