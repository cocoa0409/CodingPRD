"""Computed reads, no-op operations and every child collection reached through
its own list endpoint."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    QA_HEADERS,
    assert_fee_ledger_consistent,
    assert_instant,
    assert_integer,
    assert_money,
    assert_pagination_window,
    assert_plan_counter_partition,
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_paginated_list,
)

GUESTROOM_MAJOR_LINE = {
    "category": "GUESTROOM",
    "priority": "MAJOR",
    "description": "Guestroom soft goods and case goods replacement",
    "estimated_cost": 2_400_000.00,
}
LIFE_SAFETY_CRITICAL_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "CRITICAL",
    "description": "Stairwell pressurisation and emergency lighting",
    "estimated_cost": 480_000.00,
}
FRINGE_UNIT = {
    "unit_name": "Solaris Fairhaven",
    "market_code": "SEAWE",
    "x_miles": 4.50,
    "y_miles": 0.00,
    "room_count": 140,
    "adr_amount": 225.00,
    "occupancy_pct": 66.00,
    "territory_start_date": "2017-05-01",
    "territory_end_date": "2026-09-30",
}


def test_the_fee_summary_read_reproduces_the_stored_ledger_exactly(api):
    """PRD §3.8: the fee summary is a computed read over the same surviving
    entries the agreement's own ledger totals are built from, so the two must
    agree field for field - the two frozen rates, the surviving period count
    and all four running totals.

    Design: Corner/endpoints/fee_summary_computed_read_reproduces_the_two_period_ledger
    """
    world = fixtures.setup_agreement_with_two_revenue_periods(api)
    owner_headers = make_owner_headers(world["owner_id"])
    summary = get_success_data(api.get_fee_summary(world["agreement_id"], owner_headers))

    assert summary["agreement_id"] == world["agreement_id"]
    assert_money(summary["royalty_rate_pct"], 5.25, "royalty_rate_pct")
    assert_money(summary["marketing_fund_rate_pct"], 2.50, "marketing_fund_rate_pct")
    assert_integer(summary["reported_period_count"], 2, "reported_period_count")
    assert_money(summary["royalty_fee_to_date"], 44_000.02, "royalty_fee_to_date")
    assert_money(
        summary["marketing_fund_contributed_total"], 20_000.00, "marketing_fund_contributed_total"
    )
    assert_money(summary["reservation_fee_to_date"], 14_000.00, "reservation_fee_to_date")
    assert_money(summary["total_fees_assessed"], 78_000.02, "total_fees_assessed")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    for field in (
        "royalty_fee_to_date",
        "marketing_fund_contributed_total",
        "reservation_fee_to_date",
        "total_fees_assessed",
        "reported_period_count",
    ):
        assert summary[field] == agreement[field], (
            f"the computed read and the stored ledger disagree on {field}: "
            f"{summary[field]!r} vs {agreement[field]!r}"
        )
    assert_fee_ledger_consistent(agreement)


def test_a_sweep_with_nothing_past_due_changes_nothing_at_all(api):
    """PRD §3.7: a sweep takes only lines whose due_date is strictly before the
    clock, so a sweep run six months early moves no line, defaults no plan and
    raises no default notice - the plan's counters and the agreement's whole
    compliance axis are exactly as acceptance left them.

    Design: Corner/endpoints/compliance_sweep_with_nothing_overdue_changes_nothing
    """
    world = fixtures.setup_accepted_plan(api, scope_lines=[GUESTROOM_MAJOR_LINE])
    fixtures.set_clock(api, "2026-10-06T00:00:00Z")
    plan = fixtures.run_compliance_sweep(api, world["plan_id"])

    assert plan["status"] == "ACCEPTED"
    assert_integer(plan["items_total_count"], 1, "items_total_count")
    assert_integer(plan["items_pending_count"], 1, "items_pending_count")
    assert_integer(plan["items_submitted_count"], 0, "items_submitted_count")
    assert_integer(plan["items_verified_count"], 0, "items_verified_count")
    assert_integer(plan["items_overdue_count"], 0, "items_overdue_count")
    assert_plan_counter_partition(plan)

    rows, _ = validate_paginated_list(
        api.list_pip_items(world["plan_id"], BSD_HEADERS, {"limit": 100})
    )
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["overdue_at"] is None
    assert_instant(rows[0]["due_date"], "2027-04-03T00:00:00.000Z", "due_date")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["compliance_status"] == "COMPLIANT"
    assert agreement["default_notice_issued_at"] is None
    assert agreement["pip_cure_deadline"] is None
    assert agreement["transfer_consent_blocked"] is False


def test_the_licenses_of_an_application_are_listed_under_that_application(api):
    """PRD §2.3 and §3.6: the licenses drafted from one application are reached
    through the application's own collection, which the applicant may read, and
    the status filter narrows it - so a lone DRAFT license is the only row under
    the DRAFT filter and there is nothing at all under EXECUTED.  The row
    carries the terms frozen at drafting.

    Design: Corner/endpoints/agreements_are_listed_under_their_parent_application
    """
    world = fixtures.setup_drafted_agreement(api)
    owner_headers = make_owner_headers(world["owner_id"])

    rows, meta = validate_paginated_list(
        api.list_application_agreements(
            world["application_id"], owner_headers,
            {"status": "DRAFT", "limit": 10, "offset": 0},
        )
    )
    assert_pagination_window(meta, 10, 0, 1)
    assert rows[0]["id"] == world["agreement_id"]
    assert rows[0]["application_id"] == world["application_id"]
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["brand_code"] == "SOLARIS"
    assert_money(rows[0]["royalty_rate_pct"], 5.25, "royalty_rate_pct")
    assert_money(rows[0]["marketing_fund_rate_pct"], 2.50, "marketing_fund_rate_pct")
    assert_integer(rows[0]["term_years"], 20, "term_years")
    assert rows[0]["expiry_date"] == "2046-10-01"

    executed_rows, executed_meta = validate_paginated_list(
        api.list_application_agreements(
            world["application_id"], owner_headers, {"status": "EXECUTED"}
        )
    )
    assert_integer(executed_meta["total_count"], 0, "total_count")
    assert executed_rows == [], f"nothing is executed yet, got {len(executed_rows)} rows"


def test_a_refinance_consent_may_be_sought_before_the_hotel_even_opens(api):
    """PRD §3.9: consent is meaningful from the moment the license is signed, so
    an EXECUTED agreement accepts a filing.  A refinance is priced at the flat
    15,000.00 that ignores the room-count base entirely, carries no incoming
    owner to snapshot, and a compliant hotel pays no surcharge.  Filing alone
    consents to nothing.

    Design: Corner/endpoints/refinance_consent_is_accepted_while_the_agreement_is_only_executed
    """
    world = fixtures.setup_executed_agreement(api)
    response = api.file_transfer_request(
        world["agreement_id"],
        factories.build_refinance_request_payload("Cascade Mutual Bank"),
        make_owner_headers(world["owner_id"]),
    )
    request = get_success_data(response, 201)

    assert request["status"] == "SUBMITTED"
    assert request["request_type"] == "REFINANCE"
    assert request["agreement_id"] == world["agreement_id"]
    assert request["submitted_by_user_id"] == world["owner_id"]
    assert_money(request["transfer_fee"], 15_000.00, "transfer_fee")
    assert_money(request["non_compliance_surcharge"], 0.00, "non_compliance_surcharge")
    assert_money(request["total_consent_fee"], 15_000.00, "total_consent_fee")
    assert request["proposed_owner_id"] is None
    assert request["proposed_owner_capacity_band"] is None
    assert request["lender_name"] == "Cascade Mutual Bank"

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["status"] == "EXECUTED"
    assert_integer(agreement["transfer_consent_count"], 0, "transfer_consent_count")


def _full_estate(api):
    """One of everything: a brand with an operating hotel, an application
    carrying an overruled claim, an executed license, a two-line plan and a
    submitted refinance consent - and no inspections at all."""
    world = fixtures.setup_reviewable_application(
        api,
        existing_units=[FRINGE_UNIT],
        application_overrides={
            "property_name": "Origin Point Hotel",
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 16,
        },
    )
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_financial_review(api, world["application_id"], "PORTFOLIO_ADJUSTED")
    fixtures.run_impact_analysis(api, world["application_id"])
    claim = fixtures.file_claim(
        api, world["application_id"], world["units"][0]["id"],
        narrative="Fairhaven reports shoulder-season rate compression.",
    )
    world["claim_id"] = claim["id"]
    fixtures.resolve_claim(
        api, claim["id"], "OVERRULE",
        resolution_notes="Separation is at the edge of the protected area; claim overruled.",
    )
    world["application"] = fixtures.finalize_impact(api, world["application_id"])
    world = fixtures.setup_approved_application(api, world)
    world = fixtures.setup_drafted_agreement(api, world)
    world = fixtures.setup_executed_agreement(api, world)
    world = fixtures.setup_scoped_plan(
        api, world, scope_lines=[LIFE_SAFETY_CRITICAL_LINE, GUESTROOM_MAJOR_LINE]
    )
    fixtures.file_refinance_request(api, world, lender_name="Cascade Mutual Bank")
    return world


def test_every_child_collection_is_reachable_through_its_own_list_endpoint(api):
    """PRD §2.3 and §4: every child collection is a windowed list under its own
    parent, an empty collection lists as zero rows rather than a 404, and a
    limit of one over two scope lines pages cleanly without repeating a row.
    The overruled claim left the study at its CLEAR base score of 4.62 with no
    penalty points.

    Design: Corner/endpoints/every_child_collection_is_readable_through_its_own_list_endpoint
    """
    world = _full_estate(api)
    owner_headers = make_owner_headers(world["owner_id"])

    units, units_meta = validate_paginated_list(
        api.list_brand_existing_units(
            world["brand_id"], BSD_HEADERS, {"status": "OPERATING", "limit": 10, "offset": 0}
        )
    )
    assert_pagination_window(units_meta, 10, 0, 1)
    assert units[0]["id"] == world["units"][0]["id"]
    assert units[0]["status"] == "OPERATING"
    assert_money(units[0]["x_miles"], 4.50, "x_miles")

    claims, claims_meta = validate_paginated_list(
        api.list_encroachment_claims(
            FDM_HEADERS, {"application_id": world["application_id"], "limit": 10, "offset": 0}
        )
    )
    assert_pagination_window(claims_meta, 10, 0, 1)
    assert claims[0]["id"] == world["claim_id"]
    assert claims[0]["status"] == "OVERRULED"
    assert_money(claims[0]["penalty_points_applied"], 0.00, "penalty_points_applied")

    plans, plans_meta = validate_paginated_list(
        api.list_agreement_pips(world["agreement_id"], FDM_HEADERS, {"limit": 10, "offset": 0})
    )
    assert_pagination_window(plans_meta, 10, 0, 1)
    assert plans[0]["id"] == world["plan_id"]
    assert plans[0]["status"] == "SCOPED"
    assert_integer(plans[0]["items_total_count"], 2, "items_total_count")

    first_page, first_meta = validate_paginated_list(
        api.list_pip_items(world["plan_id"], BSD_HEADERS, {"limit": 1, "offset": 0})
    )
    assert_pagination_window(first_meta, 1, 0, 2)
    assert len(first_page) == 1
    second_page, second_meta = validate_paginated_list(
        api.list_pip_items(world["plan_id"], BSD_HEADERS, {"limit": 1, "offset": 1})
    )
    assert_pagination_window(second_meta, 1, 1, 2)
    assert len(second_page) == 1
    assert {first_page[0]["id"], second_page[0]["id"]} == {
        item["id"] for item in world["items"]
    }, "the two windows must cover both scope lines without repeating one"

    inspections, inspections_meta = validate_paginated_list(
        api.list_agreement_qa_inspections(
            world["agreement_id"], QA_HEADERS, {"limit": 10, "offset": 0}
        )
    )
    assert_pagination_window(inspections_meta, 10, 0, 0)
    assert inspections == [], "an agreement with no inspections lists empty rather than 404"

    requests, requests_meta = validate_paginated_list(
        api.list_transfer_requests(
            FDM_HEADERS, {"agreement_id": world["agreement_id"], "limit": 10, "offset": 0}
        )
    )
    assert_pagination_window(requests_meta, 10, 0, 1)
    assert requests[0]["id"] == world["transfer_request_id"]
    assert requests[0]["status"] == "SUBMITTED"
    assert_money(requests[0]["transfer_fee"], 15_000.00, "transfer_fee")
    assert_money(requests[0]["non_compliance_surcharge"], 0.00, "non_compliance_surcharge")
    assert_money(requests[0]["total_consent_fee"], 15_000.00, "total_consent_fee")

    agreements, agreements_meta = validate_paginated_list(
        api.list_application_agreements(
            world["application_id"], owner_headers, {"limit": 10, "offset": 0}
        )
    )
    assert_pagination_window(agreements_meta, 10, 0, 1)
    assert agreements[0]["id"] == world["agreement_id"]
    assert agreements[0]["status"] == "EXECUTED", (
        "the applicant reaches its own license through the application channel"
    )

    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert_integer(application["sustained_claim_count"], 0, "sustained_claim_count")
    assert_money(application["final_impact_score"], 4.62, "final_impact_score")
    assert application["encroachment_verdict"] == "CLEAR"
    assert_instant(
        application["decided_at"], "2026-09-01T00:00:00.000Z", "decided_at"
    )
