"""Transitive cascades: capacity breach and claim liability propagation.

Depth file (queue A).
"""

from test_helpers import (
    FTE_COST_CENTS,
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    create_appointment_payload,
    create_care_site,
    create_department,
    create_provider,
    create_open_region,
    current_member_version,
    enroll_member,
    get_capacity_plan,
    get_provider,
    get_region,
    get_referral,
    get_success_data,
    setup_capacity_breach_scenario,
    setup_region_with_negative_margin,
    submit_claim,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]


def _book_second_slot(department, provider, member, day=11):
    return api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"],
            current_member_version(member["id"]),
            start_utc=f"2026-09-{day:02d}T09:00:00Z",
        ),
        _AS,
    )


def test_capacity_breach_drives_the_plan_past_its_budgeted_supply(api):
    """PRD §3.3: "A plan in `ACTIVE` status whose `committed_slots` grows past
    its `budgeted_slots` is moved back to `UNDER_REVIEW` automatically".
    PRD §3.3: "`supply_shortfall_slots` is the amount by which
    `committed_slots` exceeds `budgeted_slots`, floored at zero".

    Design: Difficulty/transitive_cascade/cascade_capacity_plan_breach_to_region_posture_to_referral_hold
    """
    (region, department, provider, first_member, second_member, plan, referral,
     plan_period) = setup_capacity_breach_scenario(
        plan_budgeted_slots=1, department_slots=100
    )
    assert plan["budgeted_slots"] == 1
    assert plan["committed_slots"] == 1
    assert get_region(region["id"])["posture"] == "OPEN", (
        "the fiscal trigger is held off, so the region is OPEN before the breach"
    )

    booking = _book_second_slot(department, provider, second_member, day=11)
    assert booking.status_code == 201, booking.text

    plan_after = get_capacity_plan(plan["id"])
    assert plan_after["committed_slots"] == 2
    assert plan_after["committed_slots"] > plan_after["budgeted_slots"]
    assert plan_after["status"] == "UNDER_REVIEW", (
        "an ACTIVE plan whose committed supply passes its budgeted supply is returned to review"
    )
    assert plan_after["supply_shortfall_slots"] == 1


def test_capacity_breach_holds_the_pending_referral(api):
    """PRD §3.8: "It also sets the posture to `RESTRICTED` and also holds every
    `PENDING_TRIAGE` referral in the region".
    PRD §3.5: "When a referral's target department belongs to a region whose
    posture moves to `RESTRICTED`, a referral in `PENDING_TRIAGE` is moved to
    `HELD`".

    Design: Difficulty/transitive_cascade/cascade_capacity_plan_breach_to_region_posture_to_referral_hold
    """
    (region, department, provider, first_member, second_member, plan, referral,
     plan_period) = setup_capacity_breach_scenario(
        plan_budgeted_slots=1, department_slots=100
    )
    assert get_referral(referral["id"])["status"] == "PENDING_TRIAGE"

    booking = _book_second_slot(department, provider, second_member, day=11)
    assert booking.status_code == 201, booking.text

    region_after = get_region(region["id"])
    assert region_after["posture"] == "RESTRICTED", (
        "the capacity-driven posture branch runs from the booking hop"
    )
    assert get_referral(referral["id"])["status"] == "HELD", (
        "the hold is caused by the posture hop rather than by the booking directly"
    )


def test_capacity_breach_closes_the_regions_provider_panels(api):
    """PRD §3.8: "in place of the department reconciliation it closes every
    `ACTIVE` provider in the region by setting their status to `PANEL_CLOSED`".
    PRD §3.8: "it raises a `CAPACITY_SHORTFALL` alert at `WARNING` severity
    rather than a posture-change notice."

    Design: Difficulty/transitive_cascade/cascade_capacity_plan_breach_to_region_posture_to_referral_hold
    """
    (region, department, provider, first_member, second_member, plan, referral,
     plan_period) = setup_capacity_breach_scenario(
        plan_budgeted_slots=1, department_slots=100
    )
    assert get_provider(provider["id"])["status"] == "ACTIVE"
    assert get_region(region["id"])["posture"] == "OPEN"

    booking = _book_second_slot(department, provider, second_member, day=11)
    assert booking.status_code == 201, booking.text

    assert get_provider(provider["id"])["status"] == "PANEL_CLOSED", (
        "the capacity-driven branch closes the region's active providers"
    )

    alerts = api_client.list_region_alerts(region["id"], _RFO, {"status": "RAISED"})
    rows = alerts.json()["data"]
    assert any(
        a["alert_type"] == "CAPACITY_SHORTFALL" and a["severity"] == "WARNING"
        for a in rows
    ), "the capacity branch raises a capacity-shortfall notice at warning severity"
    assert get_region(region["id"])["open_alert_count"] >= 1


def test_adjudicating_a_claim_propagates_to_the_region_margin(api):
    """PRD §3.6: "adds the final liability to the region's
    `outside_services_spend_cents` and to the budget's
    `outside_services_committed_cents`, and recomputes the region's
    `operating_margin_cents`".
    PRD §3.6: "Payment requires the claim in `ADJUDICATED` status and the
    region's budget in `APPROVED` status".

    Design: Difficulty/transitive_cascade/cascade_claim_liability_to_region_margin_to_posture_to_provider_panel
    """
    region = create_open_region()
    site = create_care_site(
        region["id"], staffing_fte_budget=1.0, facility_investment_budget_cents=0
    )
    create_department(site["id"])
    provider = create_provider(
        site["id"], compensation_model="SALARY", base_component_cents=1250000
    )
    member = enroll_member(region["id"], provider["id"], member_ref="M-CG-1")
    budget = create_and_approve_budget(
        region["id"],
        staffing_budget_cents=1250000,
        outside_services_budget_cents=500000,
        facility_investment_cents=0,
    )

    margin_before = get_region(region["id"])["operating_margin_cents"]
    claim = submit_claim(
        region["id"], member["id"], member["version"],
        vendor_name="Echo Vendor", billed_amount_cents=420000,
    )
    adjudicated = get_success_data(api_client.adjudicate_claim(claim["id"], {}, _RFO))
    assert adjudicated["status"] == "ADJUDICATED"

    region_after = get_region(region["id"])
    assert region_after["outside_services_spend_cents"] == adjudicated["final_liability_cents"]
    assert region_after["operating_margin_cents"] == (
        margin_before - adjudicated["final_liability_cents"]
    ), "the settled margin carries exactly the newly booked liability"

    budget_after = api_client.get_regional_budget(budget["id"], _RFO).json()["data"]
    assert (
        budget_after["outside_services_committed_cents"]
        == adjudicated["final_liability_cents"]
    )


def test_negative_settled_margin_moves_the_region_to_restricted(api):
    """PRD §2.4: "A region moves from `OPEN` to `RESTRICTED` when its
    `operating_margin_cents` is below zero".
    PRD §3.7: "The settled margin is premium revenue minus employed delivery
    cost minus outside-services spend minus staffing and facility cost."

    Design: Difficulty/transitive_cascade/cascade_claim_liability_to_region_margin_to_posture_to_provider_panel
    """
    region, care_site, department, provider, member = setup_region_with_negative_margin(
        provider_base_cents=5000000
    )
    region_after = get_region(region["id"])
    assert region_after["operating_margin_cents"] < 0, (
        f"Expected a negative settled margin, got {region_after['operating_margin_cents']}"
    )
    assert region_after["posture"] == "RESTRICTED"
    assert region_after["operating_margin_cents"] == (
        region_after["premium_revenue_cents"]
        - region_after["employed_delivery_cost_cents"]
        - region_after["outside_services_spend_cents"]
        - region_after["staffing_and_facility_cents"]
    )
    assert FTE_COST_CENTS == 1250000


def test_region_returns_to_open_once_the_settled_margin_recovers(api):
    """PRD §2.4: "`RESTRICTED` returns to `OPEN` when `operating_margin_cents`
    is at or above zero."
    PRD §3.2: "A compensation-model change carries a `compensation_model` drawn
    from `SALARY`, `PANEL_CAPITATION` and `QUALITY_BONUS`, together with a
    `base_component_cents` and a `panel_size_target`".

    Design: Difficulty/transitive_cascade/cascade_claim_liability_to_region_margin_to_posture_to_provider_panel
    """
    region, care_site, department, provider, member = setup_region_with_negative_margin(
        provider_base_cents=5000000
    )
    assert get_region(region["id"])["posture"] == "RESTRICTED"

    # The provider's compensation is the only cost pushing the margin negative;
    # re-keying it to a zero base lifts the settled margin back above zero.
    get_success_data(
        api_client.change_compensation_model(
            provider["id"],
            {
                "compensation_model": "SALARY",
                "base_component_cents": 0,
                "panel_size_target": 1000,
            },
            _RFO,
        )
    )
    region_after = get_region(region["id"])
    assert region_after["operating_margin_cents"] >= 0, (
        f"Expected a recovered margin, got {region_after['operating_margin_cents']}"
    )
    assert region_after["posture"] == "OPEN"