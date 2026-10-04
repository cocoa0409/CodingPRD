"""Corner-queue tests for optimistic concurrency, cascading reviews and derived fields."""
from test_helpers import (
    SETUP_CLOCK,
    activate_permit,
    api_client,
    award_contract,
    create_standard,
    employee_payload,
    enter_renewal_negotiation,
    freeze_baseline,
    get_success_data,
    measurement_payload,
    open_contract_review,
    penalty_allocation_payload,
    raise_and_schedule_work_order,
    read_contract,
    register_asset,
    register_municipality,
    set_clock,
    setup_operating_contract,
    staffing_commitment_payload,
    submit_baseline_assessment,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_employee_headers


def test_contract_review_with_a_stale_version_is_rejected_and_the_retry_succeeds(api):
    """PRD §2.8: "A request that opens or closes a contract review must carry `expected_contract_version` as a non-optional input. That value is compared to the target contract's current `version`. If the contract's version has advanced since the client last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and no review state change occurs."
    PRD §3.4: "Opening a review moves the contract from `OPERATING` to `UNDER_REVIEW`; it requires the logical clock to have reached `contract_start_date`"

    Design: Corner/cross_cutting_layers/contract_review_stale_version_is_rejected
    """
    scenario = setup_operating_contract()
    assert scenario.con["status"] == "OPERATING"

    stale_version = read_contract(scenario.con["id"], scenario.con_h)["version"]

    # Recording a penalty allocation is one of the operations that advances the
    # contract's version, so the version read above is now stale.
    permit = activate_permit(scenario.con["id"], scenario.mun_h, scenario.con_h)
    validate_success(
        api_client.create_penalty_allocation(
            permit["id"],
            penalty_allocation_payload(total_penalty_cents=2000000),
            scenario.mun_h,
        ),
        201,
    )
    fresh_version = read_contract(scenario.con["id"], scenario.con_h)["version"]
    assert fresh_version > stale_version

    response = api_client.open_or_close_review(
        scenario.con["id"],
        {"expected_contract_version": stale_version, "review_outcome": "OPEN"},
        scenario.mun_h,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    unchanged = read_contract(scenario.con["id"], scenario.con_h)
    assert unchanged["status"] == "OPERATING", (
        "no review state change occurs on a stale write"
    )
    assert unchanged["version"] == fresh_version

    retried = validate_success(
        api_client.open_or_close_review(
            scenario.con["id"],
            {"expected_contract_version": fresh_version, "review_outcome": "OPEN"},
            scenario.mun_h,
        )
    )
    assert retried["status"] == "UNDER_REVIEW", (
        "the same write succeeds once the fresh version is declared"
    )
    assert retried["version"] == fresh_version + 1, (
        "a status change bumps the contract version by exactly one"
    )


def test_hand_back_with_a_pre_renewal_version_is_rejected_and_the_fresh_one_succeeds(api):
    """PRD §2.8: "A request that begins the transition-back path must likewise carry `expected_contract_version` as a non-optional input, compared to the target contract's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.8: "Both entries stamp `status_changed_at` and increment the contract's version, and neither creates a proposal — proposals are submitted separately."
    PRD §3.9: "Beginning the hand-back is the municipality's exclusive act and is reachable from `RENEWAL_PENDING` and from `UNDER_REVIEW`."

    Design: Corner/cross_cutting_layers/hand_back_stale_version_is_rejected
    """
    scenario = setup_operating_contract()
    set_clock("2026-12-01T00:00:00Z")
    open_contract_review(scenario.con["id"], scenario.mun_h)
    scenario.refresh_contract()
    assert scenario.con["status"] == "UNDER_REVIEW"

    stale_version = read_contract(scenario.con["id"], scenario.con_h)["version"]

    # Entering renewal is the intervening write that advances the version.
    # `enter_renewal_negotiation` already validates the call and returns its data.
    renewed = enter_renewal_negotiation(scenario.con["id"], scenario.con_h)
    assert renewed["status"] == "RENEWAL_PENDING"
    fresh_version = read_contract(scenario.con["id"], scenario.con_h)["version"]
    assert fresh_version > stale_version

    response = api_client.begin_hand_back(
        scenario.con["id"], {"expected_contract_version": stale_version}, scenario.mun_h
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    unchanged = read_contract(scenario.con["id"], scenario.con_h)
    assert unchanged["status"] == "RENEWAL_PENDING"
    assert unchanged["version"] == fresh_version

    started = validate_success(
        api_client.begin_hand_back(
            scenario.con["id"], {"expected_contract_version": fresh_version}, scenario.mun_h
        )
    )
    assert started["status"] == "HANDING_BACK", (
        "the hand-back succeeds once the fresh version is declared"
    )


def test_review_cascade_promotes_only_the_standard_whose_latest_measurement_breaches(api):
    """PRD §3.4: "Opening a review moves the contract from `OPERATING` to `UNDER_REVIEW`; it requires the logical clock to have reached `contract_start_date`, and it cascades: every standard under the contract that is `ACTIVE` and whose latest measurement is in breach moves to `BREACHED`, each such standard's owning contract recomputes `total_operator_penalty_cents` through the penalty allocation arithmetic, and a standard whose recomputed operator share pushes that contract total above the review tolerance is left `BREACHED` with its next measurement auto-created in `RECORDED` state."
    PRD §3.4: "Recording also computes `in_breach` from the standard's `threshold_value` and `threshold_direction`: under `AT_LEAST` the measurement is in breach when the observed value falls short of the threshold, and under `AT_MOST` it is in breach when the observed value exceeds it."

    Design: Corner/cross_cutting_layers/review_cascade_recomputes_contract_penalty_total
    """
    scenario = setup_operating_contract(
        standards=[
            {
                "code": "EFF-01",
                "title": "Effluent ammonia",
                "metric_type": "TREATMENT_EFFLUENT",
                "criticality_weight": 0.5,
                "threshold_value": 10.0,
                "threshold_direction": "AT_MOST",
                "breach_penalty_cents": 500000,
            },
            {
                "code": "PM-01",
                "title": "PM completion",
                "metric_type": "PM_COMPLETION",
                "criticality_weight": 0.6,
                "threshold_value": 90.0,
                "threshold_direction": "AT_LEAST",
                "breach_penalty_cents": 400000,
            },
        ]
    )
    breaching, clean = scenario.stds[0], scenario.stds[1]
    validate_success(
        api_client.record_measurement(
            breaching["id"], measurement_payload(measured_value=12.5), scenario.con_h
        ),
        201,
    )
    validate_success(
        api_client.record_measurement(
            clean["id"], measurement_payload(measured_value=95.0), scenario.con_h
        ),
        201,
    )

    version = read_contract(scenario.con["id"], scenario.con_h)["version"]
    reviewed = validate_success(
        api_client.open_or_close_review(
            scenario.con["id"],
            {"expected_contract_version": version, "review_outcome": "OPEN"},
            scenario.mun_h,
        )
    )

    assert reviewed["status"] == "UNDER_REVIEW"
    breaching_after = get_success_data(
        api_client.get_standard(breaching["id"], scenario.con_h)
    )
    clean_after = get_success_data(api_client.get_standard(clean["id"], scenario.con_h))
    assert breaching_after["status"] == "BREACHED", (
        "a standard whose latest measurement is in breach is promoted by the cascade"
    )
    assert clean_after["status"] == "ACTIVE", (
        "a standard whose latest measurement is not in breach is left untouched"
    )


def test_short_closure_narrative_leaves_documentation_incomplete_and_blocks_completion(api):
    """PRD §3.6: "It is reachable from `IN_PROGRESS`, from `PAUSED` and from `RETURNED`, and it requires a `closure_narrative` of at least 40 characters."
    PRD §3.6: "If `documentation_complete` is false, the order is not advanced: the request is rejected with `ERR_WORK_ORDER_DOCUMENTATION_INCOMPLETE` (HTTP 409) and the record is returned with its computed documentation state."
    PRD §2.10: "For a work order closure that computes incomplete documentation, the rejection is `ERR_WORK_ORDER_DOCUMENTATION_INCOMPLETE` (HTTP 409) and the record is returned with its computed documentation state rather than being silently advanced."

    Design: Corner/cross_cutting_layers/work_order_documentation_completeness_gate
    """
    scenario = setup_operating_contract()
    order = raise_and_schedule_work_order(
        scenario.asset["id"],
        scenario.con_h,
        work_type="CORRECTIVE",
        estimated_cost_cents=400000,
    )
    validate_success(api_client.start_work_order(order["id"], scenario.con_h))

    response = api_client.complete_work_order(
        order["id"],
        {
            "labour_hours": 3.0,
            "materials_cents": 200000,
            "closure_narrative": "Seal replaced.",
        },
        scenario.con_h,
    )
    validate_error(response, ApiErrorId.ERR_WORK_ORDER_DOCUMENTATION_INCOMPLETE)

    unchanged = get_success_data(api_client.get_work_order(order["id"], scenario.con_h))
    assert unchanged["documentation_complete"] is False, (
        "a narrative shorter than 40 characters leaves documentation incomplete"
    )
    assert unchanged["status"] == "IN_PROGRESS", (
        "the order is not silently advanced to COMPLETED"
    )


def test_contract_version_increments_once_for_each_state_writing_call(api):
    """PRD §2.4: "`version` starts at 1 on creation and is incremented by exactly one on every mutation."
    PRD §3.1: "The contract's `status_changed_at` is stamped and its version increments."
    PRD §3.2: "on success it sets `baseline_frozen` to true, sets `baseline_asset_count` to the count of assessments under the contract that carry `is_baseline` of true and are `ACCEPTED`, and increments the contract's version."

    Design: Corner/cross_cutting_layers/contract_version_increments_on_every_state_writing_endpoint
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    set_clock(SETUP_CLOCK)
    create_standard(contract["id"], contract_headers, activate=True)
    asset = register_asset(
        contract["id"],
        municipality_headers,
        asset_tag="PMP-113",
        asset_class="PUMP",
        install_year=2020,
        useful_life_years=15,
        criticality_rank=1,
    )
    submit_baseline_assessment(
        asset["id"], contract_headers, municipality_headers=municipality_headers
    )
    get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=2.0), contract_headers
        )
    )

    start_version = read_contract(contract["id"], contract_headers)["version"]

    mobilized = validate_success(api_client.mobilize_contract(contract["id"], contract_headers))
    assert mobilized["version"] == start_version + 1, (
        "mobilizing the contract advances its version by exactly one"
    )

    frozen = validate_success(api_client.freeze_baseline(contract["id"], municipality_headers))
    assert frozen["version"] == start_version + 2, (
        "freezing the baseline advances the contract version by exactly one more"
    )
    assert frozen["baseline_frozen"] is True


def test_declined_offer_reconciles_the_commitment_vacancy_and_status(api):
    """PRD §3.3: "Declining from `OFFERED` requires only that the employee be `OFFERED`; it recomputes the matching commitment's `filled_fte` as the sum of `transfer_offer_fte` over employees under the contract in `TRANSFERRED`, `INDUCTION` or `ACTIVE` for that `role_code` and demotes the commitment from `BINDING` to `SHORTFALL` if that figure falls below `committed_fte`."
    PRD §3.3: "The derived fields are `filled_fte`, the FTE currently filled by operator-employed staff in that position class, and `vacancy_fte`, which is `committed_fte` minus `filled_fte` floored at zero."

    Design: Corner/consistency_model/derived_staffing_vacancy_reconciles_after_a_declined_offer
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    create_standard(contract["id"], contract_headers, activate=True)
    commitment = get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=1.0), contract_headers
        )
    )
    get_success_data(api_client.mobilize_contract(contract["id"], contract_headers))
    employee = get_success_data(
        api_client.register_employee(
            contract["id"], employee_payload(transfer_offer_fte=1.0), contract_headers
        )
    )
    offered = get_success_data(
        api_client.offer_transfer(contract["id"], employee["id"], contract_headers)
    )
    assert offered["status"] == "OFFERED"

    declined = validate_success(
        api_client.decline_transfer_offer(employee["id"], make_employee_headers(employee["id"]))
    )
    assert declined["status"] == "DECLINED"

    reconciled = get_success_data(
        api_client.get_staffing_commitment(commitment["id"], contract_headers)
    )
    assert reconciled["filled_fte"] == 0.0, (
        "a declined offer leaves no filled FTE in the position class"
    )
    assert reconciled["vacancy_fte"] == 1.0, (
        "the vacancy returns to the full committed level"
    )
    assert reconciled["status"] == "SHORTFALL", (
        "the commitment is demoted from BINDING when the filled level falls short"
    )
