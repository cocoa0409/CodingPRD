"""Difficulty-queue tests for the money and classification arithmetic.

Every test here drives the logical clock rather than wall-clock time and builds
its own preconditions from the public endpoints.
"""
import pytest

from test_helpers import (
    api_client,
    assert_penalty_allocation,
    award_contract,
    complete_work_order,
    create_standard,
    employee_payload,
    get_success_data,
    penalty_allocation_payload,
    permit_payload,
    raise_started_work_order,
    register_municipality,
    setup_operating_contract,
    staffing_commitment_payload,
    validate_success,
    work_order_payload,
)


def test_penalty_allocation_separates_forward_looking_and_chronological_shares(api):
    """PRD §3.4: "The forward-looking operator share is the default and is written to `operator_share_cents`."
    PRD §3.4: "It begins with a base share: the regulator's `total_penalty_cents` multiplied by the contract's `operator_penalty_share_pct`, rounded half-up to a whole cent."
    PRD §3.4: "It then counts the standards under the contract whose status is `BREACHED`; when that count is at least one, an uplift equal to the total penalty multiplied by 0.15, rounded half-up to a whole cent, is added to the base; when the count is zero, the uplift is zero."
    PRD §3.4: "The municipality share is the total penalty minus the operator share — it is the exact remainder and is never independently rounded."
    PRD §3.4: "The second computation is the chronological comparator written to `state_baseline_share_cents`, and it applies no breach uplift at all."
    PRD §3.4: "The tier rate is the contract's `operator_penalty_share_pct` plus the smaller of 0.15 multiplied by n minus one, and a cap of 0.40."

    Design: Difficulty/dual_variant_calc/penalty_share_forward_looking_vs_chronological_recidivist
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    # A standard that is still DRAFT keeps the contract's BREACHED count at zero.
    create_standard(contract["id"], contract_headers, activate=False)
    permit = get_success_data(
        api_client.create_permit(contract["id"], permit_payload(), contract_headers)
    )

    response = api_client.create_penalty_allocation(
        permit["id"],
        penalty_allocation_payload(total_penalty_cents=2000000),
        municipality_headers,
    )
    allocation = validate_success(response, 201)

    # Forward-looking basis: 2000000 * 0.45 = 900000, no uplift, no cap.
    assert allocation["operator_share_cents"] == 900000, (
        "the forward-looking operator share must be the base share plus a zero uplift"
    )
    # Chronological comparator: the row being created is the first under the permit,
    # so the tier rate is 0.45 + min(0.15 * 0, 0.40) = 0.45.
    assert allocation["state_baseline_share_cents"] == 900000, (
        "the chronological comparator applies no breach uplift to the first allocation"
    )
    assert allocation["municipality_share_cents"] == 1100000, (
        "the municipality share is the exact remainder of the total penalty"
    )
    assert_penalty_allocation(allocation)


def test_penalty_allocation_of_an_unbreached_contract_applies_no_uplift(api):
    """PRD §3.4: "As a worked illustration, with a total of 1,800,000 cents, an operator share percentage of 0.40 and no breached standards, the base share is 720,000 and the operator share is exactly 720,000"
    PRD §3.4: "when the count is zero, the uplift is zero"
    PRD §3.4: "The municipality share is the total penalty minus the operator share — it is the exact remainder and is never independently rounded."

    Design: Difficulty/dual_variant_calc/penalty_share_forward_looking_vs_chronological_recidivist
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(
        municipality, municipality_headers, operator_penalty_share_pct=0.40
    )
    create_standard(contract["id"], contract_headers, activate=False)
    permit = get_success_data(
        api_client.create_permit(contract["id"], permit_payload(), contract_headers)
    )

    response = api_client.create_penalty_allocation(
        permit["id"],
        penalty_allocation_payload(total_penalty_cents=1800000),
        municipality_headers,
    )
    allocation = validate_success(response, 201)

    assert allocation["operator_share_cents"] == 720000
    assert allocation["municipality_share_cents"] == 1080000
    assert allocation["status"] == "ALLOCATED"


def test_penalty_allocation_caps_the_operator_share_at_the_total_penalty(api):
    """PRD §3.1: "`operator_penalty_share_pct`, a fraction between 0.0 and 1.0 inclusive of a permit penalty borne by the operator"
    PRD §3.4: "The operator share is the base plus the uplift, capped at the total penalty."
    PRD §3.4: "The municipality share is the total penalty minus the operator share — it is the exact remainder and is never independently rounded."

    Design: Difficulty/dual_variant_calc/penalty_share_forward_looking_vs_chronological_recidivist
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(
        municipality, municipality_headers, operator_penalty_share_pct=1.0
    )
    permit = get_success_data(
        api_client.create_permit(contract["id"], permit_payload(), contract_headers)
    )

    response = api_client.create_penalty_allocation(
        permit["id"],
        penalty_allocation_payload(total_penalty_cents=1000000),
        municipality_headers,
    )
    allocation = validate_success(response, 201)

    assert allocation["operator_share_cents"] == 1000000, (
        "a share of 1.0 puts the whole penalty on the operator, capped at the total"
    )
    assert allocation["municipality_share_cents"] == 0, (
        "the municipality share is the remainder and may legitimately be zero"
    )
    assert_penalty_allocation(allocation)


def test_employee_offer_selects_enhanced_vesting_tier_and_offset_from_years(api):
    """PRD §3.3: "The vesting tier splits on years of service, computed as the span from `municipal_hire_date` to the contract's `contract_start_date` divided by 365 days and rounded half-up to two decimal places."
    PRD §3.3: "at least 10 but below 20 years is `ENHANCED`"
    PRD §3.3: "The tier boundaries are inclusive at the lower edge — exactly 10.00 years is `ENHANCED`, not `STANDARD`."
    PRD §3.3: "An `ENHANCED` employee's offset is 250000 cents multiplied by the years of service, rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/benefit_vesting_vs_tiered_band_from_running_total
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    create_standard(contract["id"], contract_headers, activate=True)
    get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=2.0), contract_headers
        )
    )
    response = api_client.mobilize_contract(contract["id"], contract_headers)
    assert response.status_code in (200, 201), (
        f"Setup failed: mobilize: {response.status_code} {response.text}"
    )

    # Hired exactly 3650 days before the 2026-05-01 contract start: 10.00 years.
    employee = get_success_data(
        api_client.register_employee(
            contract["id"],
            employee_payload(
                municipal_hire_date="2016-05-03T00:00:00Z", transfer_offer_fte=1.0
            ),
            contract_headers,
        )
    )
    response = api_client.offer_transfer(contract["id"], employee["id"], contract_headers)
    offered = validate_success(response)

    assert offered["municipal_years_of_service"] == pytest.approx(10.0, abs=0.01), (
        "ten years of municipal service must be reported to two decimal places"
    )
    assert offered["benefit_tier"] == "ENHANCED", (
        "the tier boundary is inclusive at the lower edge: exactly 10.00 years is ENHANCED"
    )
    assert offered["pension_offset_cents"] == 2500000, (
        "an ENHANCED employee's offset is 250000 cents per year of service"
    )
    assert offered["status"] == "OFFERED"


def test_expense_class_ordered_branches_split_on_install_year_plus_useful_life(api):
    """PRD §3.6: "The expense class boundary sorts every work order into one of `OPERATING`, `CAPITAL_THRESHOLD`, `CAPITAL_LIFE_EVENT`, `PENDING_CLASSIFICATION` and `REJECTED_AS_CAPITAL`, and the evaluation order is pinned: pending first, then reject, then life event, then threshold, then operating, with the first matching branch winning."
    PRD §3.6: "Otherwise, a work order whose estimated cost is at least 2,500,000 cents is a capital candidate: if the current calendar year is at or after the asset's `install_year` plus its `useful_life_years`, it is classified `CAPITAL_LIFE_EVENT`, and if not, it is classified `CAPITAL_THRESHOLD`."

    Design: Difficulty/combinatorial_formula/expense_class_boundary_ordered_branch_selection
    """
    scenario = setup_operating_contract(
        assets=[
            {
                "asset_tag": "PMP-101",
                "asset_class": "PUMP",
                "install_year": 2016,
                "useful_life_years": 15,
                "criticality_rank": 1,
            },
            {
                "asset_tag": "PMP-102",
                "asset_class": "PUMP",
                "install_year": 2011,
                "useful_life_years": 15,
                "criticality_rank": 2,
            },
        ]
    )
    asset_in_life, asset_past_life = scenario.assets[0], scenario.assets[1]

    response = api_client.raise_work_order(
        asset_past_life["id"],
        work_order_payload(work_type="CORRECTIVE", estimated_cost_cents=3000000),
        scenario.con_h,
    )
    past_life_order = validate_success(response, 201)
    response = api_client.raise_work_order(
        asset_in_life["id"],
        work_order_payload(work_type="CORRECTIVE", estimated_cost_cents=3000000),
        scenario.con_h,
    )
    in_life_order = validate_success(response, 201)

    assert past_life_order["estimated_cost_cents"] == 3000000
    assert in_life_order["estimated_cost_cents"] == 3000000
    assert past_life_order["expense_class"] == "CAPITAL_LIFE_EVENT", (
        "2026 is at or after 2011 + 15, so the capital candidate is a life event"
    )
    assert in_life_order["expense_class"] == "CAPITAL_THRESHOLD", (
        "2026 is before 2016 + 15, so the capital candidate is a threshold expense"
    )


def test_work_order_completion_rounds_each_cost_component_before_summing(api):
    """PRD §3.6: "The labour component is `labour_hours` multiplied by 8450 cents per hour, rounded half-up to a whole cent."
    PRD §3.6: "The materials component is `materials_cents` multiplied by an overhead factor of 1.0875, rounded half-up to a whole cent."
    PRD §3.6: "The finalized `actual_cost_cents` is those two rounded components added together — rounding each component separately and then summing is not the same as summing the raw components, because a fractional raw component rounds differently."
    PRD §3.6: "The `cost_variance_cents` is the finalized cost minus the `estimated_cost_cents`."

    Design: Difficulty/combinatorial_formula/cost_variance_per_component_then_sum_rounding_order
    """
    scenario = setup_operating_contract()
    work_order = raise_started_work_order(
        scenario.asset["id"],
        scenario.con_h,
        work_type="CORRECTIVE",
        estimated_cost_cents=500000,
    )
    assert work_order["status"] == "IN_PROGRESS"

    completed = complete_work_order(
        work_order["id"],
        scenario.con_h,
        labour_hours=12.01,
        materials_cents=483720,
        closure_narrative=(
            "Replaced the mechanical seal and flushed the volute; impeller "
            "clearances verified within tolerance."
        ),
    )

    # 12.01 * 8450 = 101484.5 -> 101485 ; 483720 * 1.0875 = 526045.5 -> 526046.
    assert completed["actual_cost_cents"] == 627531, (
        "each cost component is rounded half-up before the two are summed"
    )
    assert completed["cost_variance_cents"] == 127531, (
        "the cost variance is the finalized cost minus the estimated cost"
    )
    assert completed["status"] == "COMPLETED"
    assert completed["documentation_complete"] is True
