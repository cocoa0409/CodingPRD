"""Corner-queue tests for transition guards, terminal-state lockdown and cascades."""
from test_helpers import (
    SETUP_CLOCK,
    api_client,
    award_contract,
    complete_work_order,
    create_standard,
    employee_payload,
    freeze_baseline,
    get_success_data,
    raise_and_schedule_work_order,
    read_contract,
    register_asset,
    register_municipality,
    set_clock,
    setup_operating_contract,
    staffing_commitment_payload,
    submit_baseline_assessment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_employee_headers


def test_contract_review_from_awarded_state_is_an_invalid_transition(api):
    """PRD §3.4: "Opening a review moves the contract from `OPERATING` to `UNDER_REVIEW`; it requires the logical clock to have reached `contract_start_date`"
    PRD §3.10: "Any request whose path names a resource in the wrong from-state for the transition being attempted is rejected with that entity's invalid-state error: `ERR_CONTRACT_INVALID_STATE` for a contract transition"
    PRD §2.4: "Every operation that changes a resource's own `status` bumps that resource's `version`."

    Design: Corner/state_machines/contract_review_from_awarded_state_is_an_invalid_transition
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    create_standard(contract["id"], contract_headers, activate=True)

    before = read_contract(contract["id"], contract_headers)
    assert before["status"] == "AWARDED"

    response = api_client.open_or_close_review(
        contract["id"],
        {"expected_contract_version": before["version"], "review_outcome": "OPEN"},
        municipality_headers,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_INVALID_STATE)

    after = read_contract(contract["id"], contract_headers)
    assert after["status"] == "AWARDED", "the refused review leaves the contract untouched"
    assert after["version"] == before["version"], (
        "no status change means no version bump"
    )


def test_closed_work_order_refuses_a_re_schedule_and_keeps_its_closure_costs(api):
    """PRD §3.10: "More generally, any operation acting on a resource that has already reached a terminal state for that operation is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) — this covers closed and cancelled work orders, retired assets and schedules, separated employees, accepted assessments, and settled or voided allocations."
    PRD §3.6: "A `CLOSED` work order is immutable: any later mutation of it is rejected with `ERR_CLOSED_WORK_ORDER_IMMUTABLE` (HTTP 409)."
    PRD §3.6: "The labour component is `labour_hours` multiplied by 8450 cents per hour, rounded half-up to a whole cent."

    Design: Corner/state_machines/work_order_schedule_from_closed_state_is_rejected
    """
    scenario = setup_operating_contract()
    order = raise_and_schedule_work_order(
        scenario.asset["id"],
        scenario.con_h,
        work_type="CORRECTIVE",
        estimated_cost_cents=400000,
    )
    validate_success(api_client.start_work_order(order["id"], scenario.con_h))
    completed = complete_work_order(
        order["id"],
        scenario.con_h,
        labour_hours=4.0,
        materials_cents=300000,
        closure_narrative=(
            "Replaced the pump mechanical seal and verified shaft alignment after "
            "reassembly."
        ),
    )
    # 4.0 * 8450 + 300000 * 1.0875 = 33800 + 326250.
    assert completed["actual_cost_cents"] == 360050

    validate_success(
        api_client.verify_work_order(order["id"], {"condition_delta": 0.0}, scenario.mun_h)
    )
    set_clock("2026-09-20T00:00:00Z")
    closed = validate_success(api_client.close_work_order(order["id"], scenario.mun_h))
    assert closed["status"] == "CLOSED"

    response = api_client.schedule_work_order(order["id"], scenario.con_h)
    # A closed work order is terminal and immutable: either named guard may answer.
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_CLOSED_WORK_ORDER_IMMUTABLE],
    )

    unchanged = get_success_data(api_client.get_work_order(order["id"], scenario.con_h))
    assert unchanged["status"] == "CLOSED", "the terminal state is not left"
    assert unchanged["actual_cost_cents"] == 360050, (
        "the immutable closure fields keep their values"
    )


def test_termination_cascades_every_employee_to_separated(api):
    """PRD §3.9: "Both entries take a `termination_reason`, set the contract's status to `TERMINATED`, and increment its version."
    PRD §3.9: "from `OPERATING`, every employee under the contract in `TRANSFERRED`, `INDUCTION`, `ACTIVE`, `OFFERED` or `ACCEPTED` state moves to the terminal `SEPARATED`"
    PRD §3.9: "`TRANSITIONED` and `TERMINATED` are the two terminal states of the contract."

    Design: Corner/state_machines/contract_termination_cascades_employees_to_separated
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    set_clock(SETUP_CLOCK)
    create_standard(contract["id"], contract_headers, activate=True)
    get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=1.0), contract_headers
        )
    )
    asset = register_asset(
        contract["id"],
        municipality_headers,
        asset_tag="PMP-104",
        asset_class="PUMP",
        install_year=2019,
        useful_life_years=15,
        criticality_rank=1,
    )
    submit_baseline_assessment(
        asset["id"], contract_headers, municipality_headers=municipality_headers
    )
    # PRD §3.1: mobilization requires `baseline_frozen` to still be false, so the
    # freeze follows it; PRD §3.3: the transfer below requires the frozen baseline.
    get_success_data(api_client.mobilize_contract(contract["id"], contract_headers))
    freeze_baseline(contract["id"], municipality_headers)

    employee = get_success_data(
        api_client.register_employee(
            contract["id"],
            employee_payload(
                municipal_hire_date="2018-05-01T00:00:00Z", transfer_offer_fte=1.0
            ),
            contract_headers,
        )
    )
    get_success_data(api_client.offer_transfer(contract["id"], employee["id"], contract_headers))
    get_success_data(
        api_client.accept_transfer_offer(employee["id"], make_employee_headers(employee["id"]))
    )
    get_success_data(api_client.transfer_employee(employee["id"], contract_headers))
    get_success_data(api_client.begin_induction(employee["id"], contract_headers))
    active = get_success_data(api_client.complete_induction(employee["id"], contract_headers))
    assert active["status"] == "ACTIVE"

    response = api_client.commence_operating(contract["id"], contract_headers)
    assert response.status_code in (200, 201), (
        f"Setup failed: commence: {response.status_code} {response.text}"
    )

    terminated = validate_success(
        api_client.terminate_contract(
            contract["id"],
            {"termination_reason": "Material breach of the permit compliance standard."},
            municipality_headers,
        )
    )
    assert terminated["status"] == "TERMINATED"

    separated = get_success_data(api_client.get_employee(employee["id"], contract_headers))
    assert separated["status"] == "SEPARATED", (
        "an ACTIVE employee is separated by the termination cascade"
    )


def test_mobilization_is_refused_while_every_standard_is_still_draft(api):
    """PRD §3.1: "Three preconditions hold: the contract's `baseline_frozen` flag must still be false, at least one standard under the contract must be `ACTIVE`, and the logical clock must have reached the contract's `contract_start_date`."
    PRD §3.1: "Mobilization is a cascading operation. Every staffing commitment under the contract still in `DRAFT` transitions to `BINDING`."
    PRD §3.10: "Any request whose path names a resource in the wrong from-state for the transition being attempted is rejected with that entity's invalid-state error: `ERR_CONTRACT_INVALID_STATE` for a contract transition"

    Design: Corner/state_machines/contract_mobilization_requires_an_active_standard
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    standard = create_standard(contract["id"], contract_headers, activate=False)
    assert standard["status"] == "DRAFT"
    commitment = get_success_data(
        api_client.create_staffing_commitment(
            contract["id"], staffing_commitment_payload(committed_fte=4.0), contract_headers
        )
    )
    set_clock("2026-05-01T00:00:00Z")

    response = api_client.mobilize_contract(contract["id"], contract_headers)
    validate_error(response, ApiErrorId.ERR_CONTRACT_INVALID_STATE)

    after = read_contract(contract["id"], contract_headers)
    assert after["status"] == "AWARDED", "a refused mobilization does not advance the contract"
    commitment_after = get_success_data(
        api_client.get_staffing_commitment(commitment["id"], contract_headers)
    )
    assert commitment_after["status"] == "DRAFT", (
        "the binding cascade only runs on a successful mobilization"
    )
