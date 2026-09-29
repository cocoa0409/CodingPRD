"""Stabilization economics: the two valuation bases the capital stack argues over, the
developer-to-property-manager handover, and the loan-to-value covenant that guards both
the facility resize and the permanent conversion."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_ratio_equals,
    assert_valuation,
    create_household,
    create_plat_approved_community,
    draft_lease,
    facility_commitment_payload,
    get_success_data,
    make_household_headers,
    pm_transition_payload,
    read_community,
    setup_active_lease,
    setup_executed_lease,
    setup_pm_managed_stabilized_community,
    setup_stabilized_community,
    signature_payload,
    submit_lease,
    validate_error,
    validate_success,
)

# One published DETACHED asking rent of 285,000 cents takes the 300 bps fee bracket, so the
# fee is 8,550 + 4,500 and every lease in this module carries a gross charge of 298,050.
BASE_RENT_CENTS = 285_000
GROSS_MONTHLY_CHARGE_CENTS = 298_050

MIX_FOUR_DETACHED = {"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0}


def test_trailing_actual_valuation_of_one_active_lease_credits_no_unleased_income(
    api, asset_manager_headers
):
    """One ACTIVE lease in a four-unit community values the whole neighbourhood on the
    lender's basis: only the in-place charge counts and nothing unleased is credited.

    "On the `TRAILING_ACTUAL` basis — the conservative lender view, and the basis every covenant test in this specification is measured against — `in_place_monthly_cents` is the sum, over the community's leases whose `lease_status` is `ACTIVE`, of each lease's `gross_monthly_charge_cents` less its `monthly_concession_credit_cents`; concessions burden the income."
    "`pro_forma_monthly_cents` is 0, because nothing unleased is credited."
    "`vacancy_deduction_cents` is 0, because actual figures already carry their own vacancy."
    "`egi_cents` is `annual_gross_cents` minus the community's `construction_impact_credit_cents` — the resident-experience credits accrued during construction reduce effective gross income on this basis."
    "`covenant_satisfied` is true when `loan_to_value_bps` is at or below 6,500 and false otherwise."

    Design: Difficulty/dual_variant_calc/stabilized_valuation_trailing_actual_versus_forward_stabilized_same_state
    """
    scenario = setup_active_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-DFW",
        concession_budget_cents=5_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    lease = scenario["lease"]
    assert lease["lease_status"] == "ACTIVE"
    assert lease["gross_monthly_charge_cents"] == GROSS_MONTHLY_CHARGE_CENTS
    assert lease["concession_status"] == "NONE"
    assert lease["monthly_concession_credit_cents"] == 0
    assert scenario["community"]["construction_impact_credit_cents"] == 0

    valuation = validate_success(
        api.get_community_valuation(
            scenario["community"]["id"], asset_manager_headers, {"basis": "TRAILING_ACTUAL"}
        )
    )
    assert_valuation(valuation)
    assert valuation["basis"] == "TRAILING_ACTUAL"
    assert valuation["in_place_monthly_cents"] == 298050
    assert valuation["pro_forma_monthly_cents"] == 0
    assert valuation["annual_gross_cents"] == 3576600
    assert valuation["vacancy_deduction_cents"] == 0
    assert valuation["egi_cents"] == 3576600
    assert valuation["opex_cents"] == 1216044
    assert valuation["noi_cents"] == 2360556
    assert valuation["value_cents"] == 44962971
    assert valuation["loan_to_value_bps"] == 17792
    assert valuation["covenant_satisfied"] is False


def test_forward_stabilized_valuation_adds_pro_forma_rent_and_a_vacancy_allowance(
    api, asset_manager_headers
):
    """The same single ACTIVE lease read on the sponsor's basis credits the three unleased
    planned units at the blended market rent and then takes a stabilized vacancy allowance.

    "On the `FORWARD_STABILIZED` basis — the sponsor view — `in_place_monthly_cents` is the sum of `gross_monthly_charge_cents` over the community's leases whose `lease_status` is `EXECUTED` or `ACTIVE`, taken at unburdened gross with no concession credit deducted at all."
    "`pro_forma_monthly_cents` is `total_planned_units` minus `leased_unit_count`, multiplied by that blended market rent."
    "`vacancy_deduction_cents` is `annual_gross_cents` multiplied by 500 basis points — a 5 percent stabilized vacancy allowance — divided by 10,000 and rounded half up."
    "`egi_cents` is `annual_gross_cents` minus `vacancy_deduction_cents`."

    Design: Difficulty/dual_variant_calc/stabilized_valuation_trailing_actual_versus_forward_stabilized_same_state
    """
    scenario = setup_active_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-DFW",
        concession_budget_cents=5_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    community = scenario["community"]
    assert community["total_planned_units"] == 4
    assert community["leased_unit_count"] == 1

    valuation = validate_success(
        api.get_community_valuation(
            community["id"], asset_manager_headers, {"basis": "FORWARD_STABILIZED"}
        )
    )
    assert_valuation(valuation)
    assert valuation["basis"] == "FORWARD_STABILIZED"
    assert valuation["in_place_monthly_cents"] == 298050
    assert valuation["pro_forma_monthly_cents"] == 855000
    assert valuation["annual_gross_cents"] == 13836600
    assert valuation["vacancy_deduction_cents"] == 691830
    assert valuation["egi_cents"] == 13144770
    assert valuation["opex_cents"] == 4469222
    assert valuation["noi_cents"] == 8675548
    assert valuation["value_cents"] == 165248533
    assert valuation["loan_to_value_bps"] == 4841
    assert valuation["covenant_satisfied"] is True


def test_two_valuation_bases_diverge_from_identical_stored_data_without_mutating_it(
    api, asset_manager_headers
):
    """Read back to back against one unchanged community, the sponsor basis reports a far
    higher value and a far lower loan-to-value than the lender basis, and the covenant
    verdict flips between them while nothing in the community moves.

    "The two bases produce materially different numbers from identical stored data, which is exactly the argument between a lender and a sponsor."
    "It takes a single input, `basis`, whose value is either `TRAILING_ACTUAL` or `FORWARD_STABILIZED`, and it stores nothing — it computes and returns `basis`, `in_place_monthly_cents`, `pro_forma_monthly_cents`, `annual_gross_cents`, `vacancy_deduction_cents`, `egi_cents`, `opex_cents`, `noi_cents`, `value_cents`, `loan_to_value_bps` and a boolean `covenant_satisfied`."
    "`loan_to_value_bps` is the community's `facility_commitment_cents` multiplied by 10,000 and divided by `value_cents`, rounded half up."

    Design: Difficulty/dual_variant_calc/stabilized_valuation_trailing_actual_versus_forward_stabilized_same_state
    """
    scenario = setup_active_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-DFW",
        concession_budget_cents=5_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    community_id = scenario["community"]["id"]
    version_before = read_community(community_id)["version"]

    trailing = validate_success(
        api.get_community_valuation(
            community_id, asset_manager_headers, {"basis": "TRAILING_ACTUAL"}
        )
    )
    forward = validate_success(
        api.get_community_valuation(
            community_id, asset_manager_headers, {"basis": "FORWARD_STABILIZED"}
        )
    )

    assert trailing["value_cents"] == 44962971
    assert forward["value_cents"] == 165248533
    assert forward["value_cents"] > trailing["value_cents"]
    assert trailing["loan_to_value_bps"] == 17792
    assert forward["loan_to_value_bps"] == 4841
    assert forward["loan_to_value_bps"] < trailing["loan_to_value_bps"]
    assert trailing["covenant_satisfied"] is False
    assert forward["covenant_satisfied"] is True

    after = read_community(community_id)
    assert after["version"] == version_before
    assert after["lifecycle_status"] == "LEASE_UP"
    assert_ratio_equals(after["occupancy_ratio"], 0.2500, "occupancy_ratio")


def test_facility_conversion_is_refused_while_the_community_is_still_developer_self_managed(
    api, asset_manager_headers
):
    """A community at three-quarters occupancy already satisfies the lifecycle, facility and
    covenant halves of the conversion checklist, so the request fails purely on the
    management dimension that no leasing action ever moves.

    "The community's `lifecycle_status` must be `STABILIZED`, or the conversion is `ERR_INVALID_LIFECYCLE_STATE`."
    "Its `facility_status` must be `CONVERSION_PENDING`, or the conversion is `ERR_INVALID_FACILITY_STATE`."
    "Its `management_mode` must be `PM_MANAGED` — a lender will not convert a community the developer is still self-managing — and a conversion attempted before the handover is `ERR_INVALID_MANAGEMENT_STATE`."
    "And the loan-to-value ratio on the trailing-actual basis must be at or below 6,500 basis points, failing which the conversion is `ERR_LTV_COVENANT_BREACH`."

    Design: Difficulty/cross_entity_state_dependency/facility_conversion_blocked_until_management_mode_becomes_pm_managed
    """
    scenario = setup_stabilized_community(
        total_planned_units=4,
        leased_count=3,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-SAT",
        concession_budget_cents=4_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    community = scenario["community"]
    assert community["lifecycle_status"] == "STABILIZED"
    assert community["facility_status"] == "CONVERSION_PENDING"
    assert community["management_mode"] == "DEVELOPER_SELF_MANAGED"
    assert community["construction_impact_credit_cents"] == 0

    valuation = validate_success(
        api.get_community_valuation(
            community["id"], asset_manager_headers, {"basis": "TRAILING_ACTUAL"}
        )
    )
    assert valuation["in_place_monthly_cents"] == 894150
    assert valuation["annual_gross_cents"] == 10729800
    assert valuation["egi_cents"] == 10729800
    assert valuation["opex_cents"] == 3648132
    assert valuation["noi_cents"] == 7081668
    assert valuation["value_cents"] == 134888914
    assert valuation["loan_to_value_bps"] == 5931
    assert valuation["covenant_satisfied"] is True

    refusal = api.convert_facility(community["id"], {}, asset_manager_headers)
    validate_error(refusal, ApiErrorId.ERR_INVALID_MANAGEMENT_STATE.value)

    after = read_community(community["id"])
    assert after["facility_status"] == "CONVERSION_PENDING"
    assert after["management_mode"] == "DEVELOPER_SELF_MANAGED"


def test_property_management_handover_unblocks_the_identical_facility_conversion(
    api, asset_manager_headers, developer_principal_headers
):
    """Executing the handover with an effective instant at the clock lands the community on
    PM_MANAGED in the same request, and the conversion request that was just refused now
    succeeds against otherwise unchanged state.

    "An `effective_from` at or before the current clock converts the community straight to `PM_MANAGED` in the same request."
    "The two branches are chosen by comparing `effective_from` against the logical clock, and both record `pm_company_name` and store the supplied instant as `pm_effective_from`, incrementing the community's `version`."
    "On success `facility_status` becomes `PERM_CONVERTED`, which is terminal and is never reverted by any later occupancy loss, and the community's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/facility_conversion_blocked_until_management_mode_becomes_pm_managed
    """
    scenario = setup_stabilized_community(
        total_planned_units=4,
        leased_count=3,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-SAT",
        concession_budget_cents=4_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    community_id = scenario["community"]["id"]

    validate_error(
        api.convert_facility(community_id, {}, asset_manager_headers),
        ApiErrorId.ERR_INVALID_MANAGEMENT_STATE.value,
    )

    handed_over = get_success_data(
        api.create_pm_transition(
            community_id,
            pm_transition_payload(
                pm_company_name="Sablewood Residential Services",
                effective_from="2026-08-01T00:00:00Z",
            ),
            developer_principal_headers,
        )
    )
    assert handed_over["management_mode"] == "PM_MANAGED"
    assert handed_over["pm_company_name"] == "Sablewood Residential Services"
    assert_instant_equals(
        handed_over["pm_effective_from"], "2026-08-01T00:00:00Z", "pm_effective_from"
    )

    converted = get_success_data(api.convert_facility(community_id, {}, asset_manager_headers))
    assert converted["facility_status"] == "PERM_CONVERTED"
    assert read_community(community_id)["facility_status"] == "PERM_CONVERTED"


def test_permanently_converted_facility_cannot_be_converted_again(api, asset_manager_headers):
    """Once the construction facility has reached permanent financing the same request is
    refused on the facility dimension, confirming the terminal state.

    "Converting the construction facility to permanent financing is the terminal financing act, taken by an `AssetManager` with no payload, and it has four preconditions that read as a checklist of everything lease-up was for."
    "Its `facility_status` must be `CONVERSION_PENDING`, or the conversion is `ERR_INVALID_FACILITY_STATE`."

    Design: Difficulty/cross_entity_state_dependency/facility_conversion_blocked_until_management_mode_becomes_pm_managed
    """
    scenario = setup_pm_managed_stabilized_community(
        total_planned_units=4,
        leased_count=3,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-SAT",
        concession_budget_cents=4_000_000,
        facility_commitment_cents=80_000_000,
        maintenance_tech_headcount=2,
    )
    community_id = scenario["community"]["id"]
    assert scenario["community"]["management_mode"] == "PM_MANAGED"

    converted = get_success_data(api.convert_facility(community_id, {}, asset_manager_headers))
    assert converted["facility_status"] == "PERM_CONVERTED"

    repeat = api.convert_facility(community_id, {}, asset_manager_headers)
    validate_error(repeat, ApiErrorId.ERR_INVALID_FACILITY_STATE.value)
    assert read_community(community_id)["facility_status"] == "PERM_CONVERTED"


def test_pm_transition_on_a_planning_community_fails_the_maintenance_staffing_gate(
    api, developer_principal_headers
):
    """A plat-approved community that has not started construction is still PLANNING, so the
    handover fails on the lifecycle half of the staffing gate rather than on the occupancy
    threshold it also misses.

    "The community's `lifecycle_status` must be `LEASE_UP` or `STABILIZED` and its `maintenance_tech_headcount` must be at least 1 — a community with nobody staffed to run turns cannot be handed over — and a failure of either is `ERR_MAINTENANCE_STAFFING_REQUIRED`."
    "**Business safety gates** — in this order: `ERR_OCCUPANCY_CERTIFICATE_REQUIRED`, `ERR_SINGLE_OWNERSHIP_COVENANT_REQUIRED`, `ERR_MAINTENANCE_STAFFING_REQUIRED`, `ERR_LEASE_UP_THRESHOLD_NOT_MET`."

    Design: Corner/validations/pm_transition_on_a_planning_community_is_rejected_by_the_staffing_gate
    """
    community = create_plat_approved_community(
        market_code="TX-HOU",
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
    )
    assert community["lifecycle_status"] == "PLANNING"
    assert community["maintenance_tech_headcount"] == 2
    assert_ratio_equals(community["occupancy_ratio"], 0.0000, "occupancy_ratio")

    refusal = api.create_pm_transition(
        community["id"],
        pm_transition_payload(
            pm_company_name="Bluestem Property Management",
            effective_from="2026-08-01T00:00:00Z",
        ),
        developer_principal_headers,
    )
    validate_error(refusal, ApiErrorId.ERR_MAINTENANCE_STAFFING_REQUIRED.value)

    after = read_community(community["id"])
    assert after["management_mode"] == "DEVELOPER_SELF_MANAGED"
    assert after["pm_company_name"] is None
    assert after["pm_effective_from"] is None
    assert after["lifecycle_status"] == "PLANNING"


def test_pm_transition_below_half_occupancy_is_refused(api, developer_principal_headers):
    """One occupied home out of four planned units leaves occupancy at a quarter, short of
    the half the handover demands.

    "The community's `occupancy_ratio` must have reached at least 0.5000, half the planned units occupied, or the transition is `ERR_LEASE_UP_THRESHOLD_NOT_MET`."

    Design: Corner/validations/pm_transition_below_half_occupancy_is_refused_and_succeeds_at_exactly_half
    """
    scenario = setup_executed_lease(
        homesite_count=2,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-AUS",
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
    )
    community = scenario["community"]
    assert community["lifecycle_status"] == "LEASE_UP"
    assert community["leased_unit_count"] == 1
    assert_ratio_equals(community["occupancy_ratio"], 0.2500, "occupancy_ratio")

    refusal = api.create_pm_transition(
        community["id"],
        pm_transition_payload(
            pm_company_name="Northgate Residential",
            effective_from="2026-08-01T00:00:00Z",
        ),
        developer_principal_headers,
    )
    validate_error(refusal, ApiErrorId.ERR_LEASE_UP_THRESHOLD_NOT_MET.value)

    after = read_community(community["id"])
    assert after["management_mode"] == "DEVELOPER_SELF_MANAGED"
    assert after["pm_company_name"] is None


def test_pm_transition_at_exactly_half_occupancy_lands_directly_in_pm_managed(
    api, developer_principal_headers
):
    """Leasing the second of four homes puts occupancy exactly on 0.5000, and the handover
    that was refused a moment ago now converts the community in the same request.

    "The community's `occupancy_ratio` must have reached at least 0.5000, half the planned units occupied, or the transition is `ERR_LEASE_UP_THRESHOLD_NOT_MET`."
    "An `effective_from` at or before the current clock converts the community straight to `PM_MANAGED` in the same request."

    Design: Corner/validations/pm_transition_below_half_occupancy_is_refused_and_succeeds_at_exactly_half
    """
    scenario = setup_executed_lease(
        homesite_count=2,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="TX-AUS",
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
    )
    community_id = scenario["community"]["id"]

    second_household = create_household()
    second_lease = draft_lease(scenario["homesites"][1]["id"], second_household["id"])
    submit_lease(second_lease["id"])
    validate_success(
        api.sign_lease(
            second_lease["id"],
            signature_payload(second_household["primary_applicant_name"]),
            make_household_headers(second_household["id"]),
        ),
        expected_status=201,
    )

    at_threshold = read_community(community_id)
    assert at_threshold["leased_unit_count"] == 2
    assert_ratio_equals(at_threshold["occupancy_ratio"], 0.5000, "occupancy_ratio")

    handed_over = get_success_data(
        api.create_pm_transition(
            community_id,
            pm_transition_payload(
                pm_company_name="Northgate Residential",
                effective_from="2026-08-01T00:00:00Z",
            ),
            developer_principal_headers,
        )
    )
    assert handed_over["management_mode"] == "PM_MANAGED"
    assert handed_over["pm_company_name"] == "Northgate Residential"
    assert_instant_equals(
        handed_over["pm_effective_from"], "2026-08-01T00:00:00Z", "pm_effective_from"
    )
    assert handed_over["lifecycle_status"] == "LEASE_UP"


def test_facility_resize_breaching_the_trailing_actual_ltv_covenant_is_rejected(
    api, asset_manager_headers
):
    """One ACTIVE lease supports a lender value of 44,962,971 cents, so a commitment of
    40,000,000 would gear the community to 8,896 basis points and is refused without
    disturbing the stored commitment.

    "The new commitment must keep the community's loan-to-value ratio, measured on the trailing-actual basis described below, at or below 6,500 basis points — 65 percent — and a resize that would breach that covenant is `ERR_LTV_COVENANT_BREACH`."
    "`loan_to_value_bps` is the community's `facility_commitment_cents` multiplied by 10,000 and divided by `value_cents`, rounded half up."

    Design: Corner/validations/a_facility_commitment_that_breaches_the_ltv_covenant_is_rejected
    """
    scenario = setup_active_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="CO-COS",
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    community_id = scenario["community"]["id"]

    valuation = validate_success(
        api.get_community_valuation(
            community_id, asset_manager_headers, {"basis": "TRAILING_ACTUAL"}
        )
    )
    assert_valuation(valuation)
    assert valuation["annual_gross_cents"] == 3576600
    assert valuation["vacancy_deduction_cents"] == 0
    assert valuation["egi_cents"] == 3576600
    assert valuation["opex_cents"] == 1216044
    assert valuation["noi_cents"] == 2360556
    assert valuation["value_cents"] == 44962971
    assert valuation["loan_to_value_bps"] == 5560

    version_before = read_community(community_id)["version"]
    refusal = api.resize_facility_commitment(
        community_id, facility_commitment_payload(40_000_000), asset_manager_headers
    )
    validate_error(refusal, ApiErrorId.ERR_LTV_COVENANT_BREACH.value)

    after = read_community(community_id)
    assert after["facility_commitment_cents"] == 25_000_000
    assert after["version"] == version_before


def test_facility_resize_landing_exactly_at_the_ltv_cap_is_accepted(api, asset_manager_headers):
    """A commitment of 29,225,000 cents gears the same community to exactly 6,500 basis
    points, which is at the cap rather than above it, so the resize is stored.

    "The new commitment must keep the community's loan-to-value ratio, measured on the trailing-actual basis described below, at or below 6,500 basis points — 65 percent — and a resize that would breach that covenant is `ERR_LTV_COVENANT_BREACH`."
    "On success the stored `facility_commitment_cents` is replaced and the community's `version` increments."
    "`covenant_satisfied` is true when `loan_to_value_bps` is at or below 6,500 and false otherwise."

    Design: Corner/validations/a_facility_commitment_that_breaches_the_ltv_covenant_is_rejected
    """
    scenario = setup_active_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="CO-COS",
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    community_id = scenario["community"]["id"]
    version_before = read_community(community_id)["version"]

    resized = validate_success(
        api.resize_facility_commitment(
            community_id, facility_commitment_payload(29_225_000), asset_manager_headers
        ),
        expected_status=201,
    )
    assert resized["facility_commitment_cents"] == 29_225_000
    assert resized["version"] > version_before

    valuation = validate_success(
        api.get_community_valuation(
            community_id, asset_manager_headers, {"basis": "TRAILING_ACTUAL"}
        )
    )
    assert valuation["value_cents"] == 44962971
    assert valuation["loan_to_value_bps"] == 6500
    assert valuation["covenant_satisfied"] is True


def test_forward_stabilized_valuation_read_matches_the_computed_projection(
    api, asset_manager_headers
):
    """An EXECUTED lease that contributes nothing to the lender basis carries the sponsor
    projection on its own, alongside pro-forma income for the three unleased planned units.

    "On the `FORWARD_STABILIZED` basis — the sponsor view — `in_place_monthly_cents` is the sum of `gross_monthly_charge_cents` over the community's leases whose `lease_status` is `EXECUTED` or `ACTIVE`, taken at unburdened gross with no concession credit deducted at all."
    "`pro_forma_monthly_cents` is `total_planned_units` minus `leased_unit_count`, multiplied by that blended market rent."
    "`vacancy_deduction_cents` is `annual_gross_cents` multiplied by 500 basis points — a 5 percent stabilized vacancy allowance — divided by 10,000 and rounded half up."
    "`value_cents` capitalises that income at 525 basis points, a 5.25 percent capitalisation rate: it is `noi_cents` multiplied by 10,000 and divided by 525, rounded half up."

    Design: Corner/endpoints/valuation_read_on_the_forward_stabilized_basis_matches_the_computed_projection
    """
    scenario = setup_executed_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="WA-TAC",
        concession_budget_cents=1_000_000,
        facility_commitment_cents=80_000_000,
    )
    assert scenario["lease"]["lease_status"] == "EXECUTED"
    assert scenario["lease"]["gross_monthly_charge_cents"] == GROSS_MONTHLY_CHARGE_CENTS

    valuation = validate_success(
        api.get_community_valuation(
            scenario["community"]["id"], asset_manager_headers, {"basis": "FORWARD_STABILIZED"}
        )
    )
    assert_valuation(valuation)
    assert valuation["basis"] == "FORWARD_STABILIZED"
    assert valuation["in_place_monthly_cents"] == 298050
    assert valuation["pro_forma_monthly_cents"] == 855000
    assert valuation["annual_gross_cents"] == 13836600
    assert valuation["vacancy_deduction_cents"] == 691830
    assert valuation["egi_cents"] == 13144770
    assert valuation["opex_cents"] == 4469222
    assert valuation["noi_cents"] == 8675548
    assert valuation["value_cents"] == 165248533
    assert valuation["loan_to_value_bps"] == 4841
    assert valuation["covenant_satisfied"] is True


def test_both_authorised_roles_read_the_same_valuation_and_the_read_has_no_side_effects(
    api, asset_manager_headers, developer_principal_headers
):
    """The sponsor and the developer see byte-identical projections, and neither read moves
    the community's version.

    "The valuation itself is a computed read available to the `DeveloperPrincipal` and the `AssetManager`."
    "It takes a single input, `basis`, whose value is either `TRAILING_ACTUAL` or `FORWARD_STABILIZED`, and it stores nothing — it computes and returns `basis`, `in_place_monthly_cents`, `pro_forma_monthly_cents`, `annual_gross_cents`, `vacancy_deduction_cents`, `egi_cents`, `opex_cents`, `noi_cents`, `value_cents`, `loan_to_value_bps` and a boolean `covenant_satisfied`."

    Design: Corner/endpoints/valuation_read_on_the_forward_stabilized_basis_matches_the_computed_projection
    """
    scenario = setup_executed_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="WA-TAC",
        concession_budget_cents=1_000_000,
        facility_commitment_cents=80_000_000,
    )
    community_id = scenario["community"]["id"]
    version_before = read_community(community_id)["version"]

    by_developer = validate_success(
        api.get_community_valuation(
            community_id, developer_principal_headers, {"basis": "FORWARD_STABILIZED"}
        )
    )
    by_asset_manager = validate_success(
        api.get_community_valuation(
            community_id, asset_manager_headers, {"basis": "FORWARD_STABILIZED"}
        )
    )
    assert by_developer == by_asset_manager
    assert by_developer["value_cents"] == 165248533
    assert by_developer["loan_to_value_bps"] == 4841

    assert read_community(community_id)["version"] == version_before
