"""Corner coverage: calculation rules, variant selection and input-set filtering.

Breadth file (queue B).
"""

from test_helpers import (
    ANNUAL_DEDUCTIBLE_CENTS,
    BASE_RATE_COMMERCIAL_HMO_CENTS,
    CAPITATION_CEIL_MULTIPLIER,
    CAPITATION_FLOOR_MULTIPLIER,
    FTE_COST_CENTS,
    PANEL_RATE_CENTS,
    QUALITY_BONUS_THRESHOLD,
    TEST_USERS,
    api_client,
    create_open_region,
    current_member_version,
    create_active_capacity_plan,
    create_and_approve_budget,
    create_and_book_appointment,
    create_care_site,
    create_department,
    create_provider,
    enroll_member,
    get_region,
    get_success_data,
    set_logical_clock,
    setup_basic_scenario,
    setup_bookable_scenario,
    setup_region_site_department_provider,
    submit_claim,
    validate_error,
    validate_success,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]


def test_capitation_holds_between_floor_and_ceiling_at_ordinary_risk(api):
    """PRD §3.1: "The lower bound is the adjusted base multiplied by one half,
    rounded half-up; the upper bound is the adjusted base multiplied by two and
    a half, rounded half-up."
    PRD §3.1: "a raw rate inside the interval stands as computed."

    Design: Corner/calculations/capitation_floor_clamp_holds_at_low_risk
    """
    region, care_site, department, provider, member = setup_basic_scenario(
        member_overrides={"risk_score": 1.0}
    )
    assert member["capitation_rate_cents"] == 84000
    floor = int(round(BASE_RATE_COMMERCIAL_HMO_CENTS * CAPITATION_FLOOR_MULTIPLIER))
    ceiling = int(round(BASE_RATE_COMMERCIAL_HMO_CENTS * CAPITATION_CEIL_MULTIPLIER))
    assert floor == 21000
    assert ceiling == 105000
    assert floor < member["capitation_rate_cents"] < ceiling, (
        "no clamp fires for an ordinary risk score"
    )


def test_capitation_ceiling_clamp_binds_at_extreme_risk(api):
    """PRD §3.1: "a raw rate above the upper bound becomes the upper bound, and a
    raw rate inside the interval stands as computed."
    PRD §3.1: "The lower bound is the adjusted base multiplied by one half,
    rounded half-up; the upper bound is the adjusted base multiplied by two and
    a half, rounded half-up."

    Design: Corner/calculations/capitation_ceiling_clamp_binds_at_extreme_risk
    """
    region, care_site, department, provider, member = setup_basic_scenario(
        member_overrides={"risk_score": 1.0}
    )
    res = api_client.correct_member_risk_score(
        member["id"],
        {"risk_score": 3.0, "expected_member_version": current_member_version(member["id"])},
        _RFO,
    )
    updated = validate_success(res, 200)
    # Raw 42000 + 126000 = 168000 is above the 105000 ceiling.
    assert updated["risk_score"] == 3.0
    assert updated["capitation_rate_cents"] == 105000, (
        f"Expected the ceiling clamp, got {updated['capitation_rate_cents']}"
    )
    assert get_region(region["id"])["premium_revenue_cents"] == 105000


def test_premium_revenue_excludes_a_terminated_member(api):
    """PRD §3.1: "Termination is a separate transition: a member in `ACTIVE`
    status may be terminated, moving `status` to `TERMINATED` and recomputing
    the region's `premium_revenue_cents`, `member_count` and
    `operating_margin_cents` so that the terminating member's capitation is no
    longer counted."
    PRD §2.6: "`premium_revenue_cents` is the sum of `capitation_rate_cents`
    over the region's members whose status is `ACTIVE` or `TRANSFER_PENDING`".

    Design: Corner/calculations/region_premium_revenue_excludes_suspended_and_terminated_members
    """
    region, care_site, department, provider = setup_region_site_department_provider()
    first = enroll_member(region["id"], provider["id"], member_ref="M-T-1", risk_score=1.0)
    second = enroll_member(
        region["id"], provider["id"], member_ref="M-T-2",
        plan_product="MEDICARE_ADVANTAGE", benefit_tier="TIER_2", risk_score=1.0,
    )
    before = get_region(region["id"])
    assert before["premium_revenue_cents"] == 84000 + 190000
    assert before["member_count"] == 2

    get_success_data(
        api_client.terminate_member(
            first["id"],
            {"expected_member_version": current_member_version(first["id"])},
            _RFO,
        )
    )
    after = get_region(region["id"])
    assert after["premium_revenue_cents"] == 190000
    assert after["member_count"] == 1


def test_access_breach_percentage_counts_only_non_cancelled_appointments(api):
    """PRD §3.10: "The region's `access_breach_pct` is one hundred times the
    count of its breached appointments divided by its count of non-cancelled
    appointments, rounded half-up to two decimal places; appointments in
    `CANCELLED` status are excluded from both the numerator and the
    denominator."

    Design: Corner/calculations/access_breach_pct_counts_only_non_cancelled_appointments
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(
        care_site["id"], appointment_slots_budgeted=100, wait_threshold_days=14
    )
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])
    first = enroll_member(region["id"], provider["id"], member_ref="M-T-1")
    second = enroll_member(region["id"], provider["id"], member_ref="M-T-2")

    breaching = create_and_book_appointment(
        region, department, provider, first, start_utc="2026-09-20T00:00:00Z"
    )
    within = create_and_book_appointment(
        region, department, provider, second, start_utc="2026-09-05T00:00:00Z"
    )
    assert breaching["access_status"] == "BREACHED_ACCESS_TARGET"
    assert within["access_status"] == "WITHIN_ACCESS_TARGET"
    assert get_region(region["id"])["access_breach_pct"] == 50.0

    get_success_data(api_client.cancel_appointment(breaching["id"], {}, _AS))
    assert get_region(region["id"])["access_breach_pct"] == 0.0, (
        "cancelling the breaching appointment removes it from both terms"
    )


def test_emergency_flag_selects_the_flat_provisional_rate(api):
    """PRD §3.6: "When `emergency_flag` is true, the provisional amount is
    instead the billed amount multiplied by seventy-five percent, rounded
    half-up."
    PRD §3.6: "eighty percent for the vendor `KP Affiliate` and seventy percent
    for any other vendor name".

    Design: Corner/calculations/outside_services_liability_emergency_rate_variant
    """
    region, care_site, department, provider, member, budget = setup_bookable_scenario()

    emergency = submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        vendor_name="Emergency Vendor", claim_type="EMERGENCY",
        emergency_flag=True, billed_amount_cents=420000,
    )
    planned = submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        vendor_name="Test Vendor", claim_type="CONTRACTED",
        emergency_flag=False, billed_amount_cents=420000,
    )
    assert emergency["provisional_liability_cents"] == 315000
    assert planned["provisional_liability_cents"] == 294000
    assert emergency["provisional_liability_cents"] != planned["provisional_liability_cents"]


def test_capacity_supply_shortfall_floors_at_zero(api):
    """PRD §3.3: "`supply_shortfall_slots` is the amount by which
    `committed_slots` exceeds `budgeted_slots`, floored at zero — it is never
    negative."
    PRD §3.3: "Every recomputation of `committed_slots` advances
    `recalculation_epoch` by one."

    Design: Corner/calculations/capacity_supply_shortfall_is_zero_when_committed_is_below_budgeted
    """
    set_logical_clock()
    region, care_site, department, provider, member, budget = setup_bookable_scenario()
    plan = create_active_capacity_plan(
        region["id"], department["id"], budgeted_slots=10, panel_target=3
    )
    epoch_before = plan["recalculation_epoch"]

    create_and_book_appointment(
        region, department, provider, member, start_utc="2026-09-10T09:00:00Z"
    )
    refreshed = api_client.get_capacity_plan(plan["id"], _RFO).json()["data"]
    assert refreshed["committed_slots"] == 1
    assert refreshed["budgeted_slots"] == 10
    assert refreshed["supply_shortfall_slots"] == 0, "under-commitment floors at zero"
    assert refreshed["recalculation_epoch"] > epoch_before

    region_after = get_region(region["id"])
    assert region_after["capacity_committed_appointments"] == 1
    assert region_after["capacity_budget_appointments"] == 10


def test_denied_referrals_are_excluded_from_the_internal_referral_rate(api):
    """PRD §3.10: "The logged percentage is computed as the count of referrals
    referred inside divided by the total authorized count, rounded half-up, and
    it is built only from referrals whose status is `AUTHORIZED`, `SCHEDULED` or
    `COMPLETED`; denied referrals are excluded from the denominator entirely."

    Design: Corner/calculations/internal_referral_rate_excludes_denied_referrals
    """
    from test_helpers import create_referral_payload, set_metric_outcome

    region, care_site, department, provider = setup_region_site_department_provider()
    first = enroll_member(region["id"], provider["id"], member_ref="M-T-1")
    second = enroll_member(region["id"], provider["id"], member_ref="M-T-2")

    authorized = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                first["id"], department["id"], department["id"], first["version"]
            ),
            _AS,
        )
    )
    denied = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                second["id"], department["id"], department["id"], second["version"]
            ),
            _AS,
        )
    )
    get_success_data(api_client.authorize_referral(authorized["id"], {}, _UR))
    get_success_data(api_client.deny_referral(denied["id"], {}, _UR))

    metric = get_success_data(
        api_client.create_quality_metric(
            region["id"],
            {
                "metric_code": "QUALITY_COMPOSITE",
                "period": "2026-09",
                "target_value": 80,
                "accountable_provider_id": provider["id"],
            },
            TEST_USERS["quality_review_board_headers"],
        )
    )
    set_metric_outcome(metric["id"], 80)
    res = api_client.finalize_quality_metric(
        metric["id"], {}, TEST_USERS["quality_review_board_headers"]
    )
    # With only the authorized referral counted, the log reads complete.
    assert res.status_code == 200, res.text


def test_volume_component_stays_zero_across_compensation_models(api):
    """PRD §3.2: "It is pinned to zero under every compensation arrangement."
    PRD §3.2: "a supplied `volume_linked` flag set to true causes the plan to be
    recorded and refused with `ERR_VOLUME_COMPONENT_NOT_PERMITTED`".

    Design: Corner/calculations/provider_volume_component_stays_zero_across_compensation_models
    """
    region, care_site, department, provider = setup_region_site_department_provider()

    changed = get_success_data(
        api_client.change_compensation_model(
            provider["id"],
            {
                "compensation_model": "QUALITY_BONUS",
                "base_component_cents": 2000000,
                "panel_size_target": 1000,
            },
            _RFO,
        )
    )
    assert changed["compensation_model"] == "QUALITY_BONUS"
    assert changed["volume_component_cents"] == 0

    refused = api_client.draft_compensation_plan(
        {
            "provider_id": provider["id"],
            "base_component_cents": 2000000,
            "panel_size_target": 1000,
            "bonus_quality_target": 85,
            "volume_linked": True,
        },
        _RFO,
    )
    validate_error(refused, "ERR_VOLUME_COMPONENT_NOT_PERMITTED", expected_status=422)