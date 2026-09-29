"""Pinned orders of operation: rounding stages, band selection and the money
figures frozen at a single instant."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    QA_HEADERS,
    QA_SECOND_HEADERS,
    assert_fee_ledger_consistent,
    assert_instant,
    assert_integer,
    assert_money,
    assert_plan_counter_partition,
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_paginated_list,
)

LAKESIDE_UNIT = {
    "unit_name": "Solaris Lakeside",
    "market_code": "SEADT",
    "x_miles": 1.20,
    "y_miles": 1.60,
    "room_count": 100,
    "adr_amount": 310.00,
    "occupancy_pct": 72.00,
    "territory_start_date": "2016-06-01",
    "territory_end_date": "2026-09-30",
}
MIDTOWN_UNIT = {
    "unit_name": "Solaris Midtown",
    "market_code": "SEADT",
    "x_miles": 2.40,
    "y_miles": 0.00,
    "room_count": 90,
    "adr_amount": 265.00,
    "occupancy_pct": 70.00,
    "territory_start_date": "2017-02-01",
    "territory_end_date": "2026-09-30",
}
SINGLE_LIFE_SAFETY_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "CRITICAL",
    "description": "Stairwell pressurisation and emergency lighting",
    "estimated_cost": 480_000.00,
}


def test_the_final_study_admits_the_suspended_hotel_the_preliminary_pass_excluded(api):
    """PRD §3.4: the preliminary pass admits only OPERATING hotels while the
    final pass admits OPERATING or SUSPENDED, so a suspension recorded before
    the study runs legitimately produces a final base score above the
    preliminary one over the identical property.  Each contribution is rounded
    to two decimals on its own before the sum, giving 32.73 plus 29.71.

    Design: Corner/calculations/preliminary_study_excludes_the_suspended_unit_that_the_final_study_admits
    """
    world = fixtures.setup_reviewable_application(
        api,
        existing_units=[LAKESIDE_UNIT, MIDTOWN_UNIT],
        application_overrides={
            "property_name": "Origin Point Hotel",
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 16,
        },
    )
    fixtures.change_unit_status(
        api, world["units"][1]["id"], "SUSPENDED", "Guestroom tower renovation."
    )

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    preliminary = fixtures.run_impact_analysis(api, world["application_id"])
    assert_money(preliminary["preliminary_impact_score"], 32.73, "preliminary_impact_score")
    assert_integer(
        preliminary["impact_unit_count_preliminary"], 1, "impact_unit_count_preliminary"
    )

    final = fixtures.finalize_impact(api, world["application_id"])
    assert_money(final["base_impact_score"], 62.44, "base_impact_score")
    assert_money(final["final_impact_score"], 62.44, "final_impact_score")
    assert_integer(final["impact_unit_count_final"], 2, "impact_unit_count_final")
    assert final["encroachment_verdict"] == "ENCROACHMENT_CONFIRMED"
    assert final["impact_study_status"] == "FINAL"
    assert_integer(final["sustained_claim_count"], 0, "sustained_claim_count")

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["operating_unit_count"], 1, "operating_unit_count")

    rows, _ = validate_paginated_list(
        api.list_brand_existing_units(world["brand_id"], BSD_HEADERS)
    )
    by_name = {row["unit_name"]: row for row in rows}
    assert by_name["Solaris Midtown"]["status"] == "SUSPENDED"
    assert by_name["Solaris Lakeside"]["status"] == "OPERATING"


def test_royalty_straddles_all_three_revenue_slices_in_one_period(api):
    """PRD §3.8: the royalty schedule is a three-slice progressive scale and
    each slice charge is rounded on its own before the three are added, so
    600,000.00 of revenue at a frozen 5.25 rate charges 10,500.00 on the first
    200,000.00, 17,250.00 on the middle 300,000.00 at 5.75 and 6,250.00 on the
    top 100,000.00 at 6.25 - 34,000.00 in all.  The flat marketing and
    reservation components are assessed on the whole month.

    Design: Corner/calculations/royalty_straddles_all_three_revenue_tiers_in_one_period
    """
    world = fixtures.setup_open_agreement(api)
    agreement = world["agreement"]
    assert_money(agreement["royalty_rate_pct"], 5.25, "royalty_rate_pct")
    assert_money(agreement["marketing_fund_rate_pct"], 2.50, "marketing_fund_rate_pct")
    assert_integer(agreement["term_years"], 20, "term_years")
    assert agreement["expiry_date"] == "2046-10-01", (
        f"twenty calendar years from the effective date, got {agreement['expiry_date']}"
    )

    fixtures.set_clock(api, "2026-12-05T00:00:00Z")
    agreement = fixtures.report_revenue(
        api, world["agreement_id"], world["owner_id"], "2026-11", 600_000.00
    )
    period = agreement["revenue_periods"][0]
    assert period["period_month"] == "2026-11"
    assert_money(period["royalty_fee"], 34_000.00, "royalty_fee")
    assert_money(period["marketing_fee"], 15_000.00, "marketing_fee")
    assert_money(period["reservation_fee"], 10_500.00, "reservation_fee")
    assert_money(period["period_total_fee"], 59_500.00, "period_total_fee")
    assert period["superseded"] is False

    assert_money(agreement["royalty_fee_to_date"], 34_000.00, "royalty_fee_to_date")
    assert_money(
        agreement["marketing_fund_contributed_total"], 15_000.00, "marketing_fund_contributed_total"
    )
    assert_money(agreement["reservation_fee_to_date"], 10_500.00, "reservation_fee_to_date")
    assert_money(agreement["total_fees_assessed"], 59_500.00, "total_fees_assessed")
    assert_integer(agreement["reported_period_count"], 1, "reported_period_count")
    assert_fee_ledger_consistent(agreement)


def test_key_money_band_comes_from_the_gross_per_room_cost_then_is_capped(api):
    """PRD §3.7: cost allocation runs in a pinned order.  A 3,120,000.00
    programme over 120 rooms is 26,000.00 per room, which selects the 10 per
    cent band from the gross figure rather than the circular net one; the
    312,000.00 that follows is cut to the 250,000.00 ceiling, leaving
    2,870,000.00 net at 23,916.67 a room - above 20,000.00, so the programme
    escalates.  Each line's allowance is the smaller of its priority and
    category budgets.

    Design: Corner/calculations/key_money_band_is_selected_from_the_gross_cost_per_room_then_capped
    """
    world = fixtures.setup_accepted_plan(api)
    plan = world["plan"]

    assert plan["status"] == "ACCEPTED"
    assert_instant(plan["accepted_at"], "2026-10-05T00:00:00.000Z", "accepted_at")
    assert_money(plan["total_estimated_cost"], 3_120_000.00, "total_estimated_cost")
    assert_money(plan["cost_per_room"], 26_000.00, "cost_per_room")
    assert_integer(plan["key_money_pct"], 10, "key_money_pct")
    assert_money(plan["franchisor_key_money"], 250_000.00, "franchisor_key_money")
    assert_money(plan["owner_net_cost"], 2_870_000.00, "owner_net_cost")
    assert_money(
        plan["owner_net_cost"],
        plan["total_estimated_cost"] - plan["franchisor_key_money"],
        "gross less key money",
    )
    assert_money(plan["owner_net_cost_per_room"], 23_916.67, "owner_net_cost_per_room")
    assert plan["escalation_required"] is True
    assert_plan_counter_partition(plan)

    rows, _ = validate_paginated_list(
        api.list_pip_items(world["plan_id"], BSD_HEADERS, {"limit": 100})
    )
    due_dates = {row["category"]: row["due_date"] for row in rows}
    assert_instant(
        due_dates["LIFE_SAFETY"], "2026-11-19T00:00:00.000Z",
        "LIFE_SAFETY due_date (min(90, 45) days from acceptance)",
    )
    assert_instant(
        due_dates["GUESTROOM"], "2027-04-03T00:00:00.000Z",
        "GUESTROOM due_date (min(180, 210) days from acceptance)",
    )
    assert_instant(
        due_dates["EXTERIOR"], "2027-06-02T00:00:00.000Z",
        "EXTERIOR due_date (min(270, 240) days from acceptance)",
    )
    assert_instant(plan["overall_deadline"], "2027-06-02T00:00:00.000Z", "overall_deadline")


def test_all_three_consent_types_are_priced_off_the_same_room_count(api):
    """PRD §3.9: one base fee of 750.00 a room over 120 rooms prices all three
    consent types - the base itself for a TRANSFER, the base halved for a
    CHANGE_OF_CONTROL because no new franchisee is underwritten, and a flat
    15,000.00 for a REFINANCE that ignores the base entirely.  A COMPLIANT
    hotel pays no surcharge, and only the two owner-facing types snapshot the
    incoming entity's standalone band.

    Design: Corner/calculations/consent_fee_prices_transfer_change_of_control_and_refinance_off_one_room_count
    """
    world = fixtures.setup_open_agreement(api)
    owner_headers = make_owner_headers(world["owner_id"])
    fixtures.set_clock(api, "2026-11-05T00:00:00Z")
    transferee = fixtures.create_second_owner(api)
    assert transferee["capacity_band_standalone"] == "STRONG"

    transfer = get_success_data(
        api.file_transfer_request(
            world["agreement_id"],
            factories.build_transfer_request_payload(
                "TRANSFER", proposed_owner_id=transferee["id"]
            ),
            owner_headers,
        ),
        201,
    )
    control = get_success_data(
        api.file_transfer_request(
            world["agreement_id"],
            factories.build_transfer_request_payload(
                "CHANGE_OF_CONTROL", proposed_owner_id=transferee["id"]
            ),
            owner_headers,
        ),
        201,
    )
    refinance = get_success_data(
        api.file_transfer_request(
            world["agreement_id"],
            factories.build_refinance_request_payload("Puget Mezzanine Capital"),
            owner_headers,
        ),
        201,
    )

    assert_money(transfer["transfer_fee"], 90_000.00, "TRANSFER transfer_fee")
    assert_money(transfer["non_compliance_surcharge"], 0.00, "non_compliance_surcharge")
    assert_money(transfer["total_consent_fee"], 90_000.00, "TRANSFER total_consent_fee")
    assert_money(control["transfer_fee"], 45_000.00, "CHANGE_OF_CONTROL transfer_fee")
    assert_money(control["total_consent_fee"], 45_000.00, "CHANGE_OF_CONTROL total_consent_fee")
    assert_money(refinance["transfer_fee"], 15_000.00, "REFINANCE transfer_fee")
    assert_money(refinance["total_consent_fee"], 15_000.00, "REFINANCE total_consent_fee")

    assert transfer["proposed_owner_capacity_band"] == "STRONG"
    assert control["proposed_owner_capacity_band"] == "STRONG"
    assert refinance["proposed_owner_capacity_band"] is None, (
        "a refinance has no incoming owner to snapshot"
    )
    for request in (transfer, control, refinance):
        assert request["status"] == "SUBMITTED"
        assert request["submitted_by_user_id"] == world["owner_id"]

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["compliance_status"] == "COMPLIANT"
    assert agreement["transfer_consent_blocked"] is False
    assert_integer(agreement["transfer_consent_count"], 0, "transfer_consent_count")


def test_weighted_sections_then_the_defect_penalty_land_in_the_conditional_band(api):
    """PRD §3.8: the four sections are weighted 0.30, 0.25, 0.30 and 0.15 and
    rounded once to 83.40, then five points come off for each of the two
    critical defects, giving 73.40 - inside the CONDITIONAL band, which buys a
    sixty-day cure window and moves the compliance axis to CURE_PERIOD.  The
    channel is untouched, because only a failed cure suspends it, and the
    failure tally does not move on a mere inspection.

    Design: Corner/calculations/qa_weighted_sections_then_critical_defect_penalty_land_in_the_conditional_band
    """
    world = fixtures.setup_open_agreement(api)
    fixtures.set_clock(api, "2026-11-15T00:00:00Z")
    response = api.create_qa_inspection(
        world["agreement_id"],
        factories.build_qa_inspection_payload(
            cleanliness_score=88,
            condition_score=72,
            brand_standard_score=90,
            guest_experience_score=80,
            critical_defect_count=2,
            life_safety_defect=False,
        ),
        QA_HEADERS,
    )
    inspection = get_success_data(response, 201)

    assert_money(inspection["weighted_score"], 83.40, "weighted_score")
    assert_money(inspection["total_score"], 73.40, "total_score")
    assert inspection["grade"] == "CONDITIONAL"
    assert_integer(inspection["cure_period_days"], 60, "cure_period_days")
    assert_instant(inspection["cure_deadline"], "2027-01-14T00:00:00.000Z", "cure_deadline")
    assert inspection["status"] == "CURE_PENDING"
    assert_instant(inspection["inspection_at"], "2026-11-15T00:00:00.000Z", "inspection_at")
    assert inspection["inspector_user_id"] == "qai-first-01"

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["compliance_status"] == "CURE_PERIOD"
    assert agreement["channel_status"] == "CONNECTED", (
        "only a failed cure review suspends the channel"
    )
    assert_integer(
        agreement["consecutive_qa_failure_count"], 0, "consecutive_qa_failure_count"
    )
    assert_instant(
        agreement["last_inspection_at"], "2026-11-15T00:00:00.000Z", "last_inspection_at"
    )


def test_for_cause_qa_termination_prices_damages_on_the_contractual_multiple(api):
    """PRD §3.9: a third consecutive failed cure makes the hotel
    TERMINATION_ELIGIBLE, the only state a quality-assurance termination may be
    taken from.  The damages basis excludes the pass-through reservation fee, so
    64,000.02 of royalty and marketing over two months averages 32,000.01 a
    month; the 233-month remaining span is charged at the frozen 36-month cap,
    and CONTRACTUAL_MULTIPLE multiplies the two.  A COMPLETED plan is outside
    the suspension set and is left alone.

    Design: Corner/calculations/liquidated_damages_contractual_multiple_on_for_cause_qa_termination
    """
    world = fixtures.setup_open_agreement(api, scope_lines=[SINGLE_LIFE_SAFETY_LINE])
    fixtures.run_failing_cure_cycle(
        api, world, "2026-11-15T00:00:00Z", QA_HEADERS, QA_SECOND_HEADERS,
        cure_clock="2026-12-05T00:00:00Z",
    )
    fixtures.report_revenue(
        api, world["agreement_id"], world["owner_id"], "2026-11", 320_000.16
    )
    fixtures.set_clock(api, "2027-01-05T00:00:00Z")
    fixtures.report_revenue(
        api, world["agreement_id"], world["owner_id"], "2026-12", 480_000.16
    )
    fixtures.run_failing_cure_cycle(
        api, world, "2027-02-20T00:00:00Z", QA_HEADERS, QA_SECOND_HEADERS,
        cure_clock="2027-03-05T00:00:00Z",
    )
    fixtures.run_failing_cure_cycle(
        api, world, "2027-05-21T00:00:00Z", QA_HEADERS, QA_SECOND_HEADERS,
        cure_clock="2027-05-25T00:00:00Z",
    )

    before = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert before["compliance_status"] == "TERMINATION_ELIGIBLE"
    assert_integer(before["consecutive_qa_failure_count"], 3, "consecutive_qa_failure_count")

    agreement = get_success_data(
        api.terminate_agreement(
            world["agreement_id"],
            factories.build_termination_payload(
                "FOR_CAUSE_QA",
                termination_notes="Three consecutive failed cure reviews.",
            ),
            BSD_HEADERS,
        )
    )

    assert agreement["termination_cause"] == "FOR_CAUSE_QA"
    assert agreement["liquidated_damages_formula"] == "CONTRACTUAL_MULTIPLE"
    assert_money(agreement["trailing_avg_monthly_fee"], 32_000.01, "trailing_avg_monthly_fee")
    assert_integer(
        agreement["remaining_term_months_at_termination"], 233,
        "remaining_term_months_at_termination",
    )
    assert_integer(
        agreement["liquidated_damages_cap_months"], 36, "liquidated_damages_cap_months"
    )
    assert_money(agreement["liquidated_damages_amount"], 1_152_000.36, "liquidated_damages_amount")

    assert_money(agreement["royalty_fee_to_date"], 44_000.02, "royalty_fee_to_date")
    assert_money(
        agreement["marketing_fund_contributed_total"], 20_000.00, "marketing_fund_contributed_total"
    )
    assert_money(agreement["reservation_fee_to_date"], 14_000.00, "reservation_fee_to_date")
    assert_money(agreement["total_fees_assessed"], 78_000.02, "total_fees_assessed")
    assert_integer(agreement["reported_period_count"], 2, "reported_period_count")

    assert agreement["status"] == "TERMINATION_PENDING"
    assert_instant(agreement["terminated_at"], "2027-05-25T00:00:00.000Z", "terminated_at")
    assert agreement["post_termination_status"] == "OPEN"
    assert_instant(
        agreement["de_identification_deadline"], "2027-06-24T00:00:00.000Z",
        "de_identification_deadline",
    )
    assert agreement["channel_status"] == "SUSPENDED"

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "COMPLETED", (
        "a completed plan is outside the suspension set"
    )
