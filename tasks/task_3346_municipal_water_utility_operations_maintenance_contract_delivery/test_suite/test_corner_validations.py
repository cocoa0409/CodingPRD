"""Corner-queue tests for the constraint validations that reject a request."""
from test_helpers import (
    api_client,
    award_contract,
    begin_hand_back,
    contract_payload,
    create_obligation,
    get_success_data,
    permit_payload,
    register_municipality,
    set_clock,
    setup_under_review_contract,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def test_contract_award_rejects_an_operator_penalty_share_above_one(api):
    """PRD §3.1: "`operator_penalty_share_pct`, a fraction between 0.0 and 1.0 inclusive of a permit penalty borne by the operator"
    PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/validations/penalty_allocation_rejects_operator_share_over_total
    """
    municipality, municipality_headers = register_municipality()

    response = api_client.award_contract(
        municipality["id"],
        contract_payload(operator_penalty_share_pct=1.2),
        municipality_headers,
    )

    assert 400 <= response.status_code < 500, (
        f"a share above 1.0 must be refused, got {response.status_code}"
    )
    body = response.json()
    assert body["response_type"] == "error", (
        "the refusal is an error envelope, not a created contract body"
    )
    assert body["data"]["error_id"], "the refusal carries its own error identifier"

    contracts = get_success_data(
        api_client.list_municipality_contracts(municipality["id"], municipality_headers)
    )
    assert contracts == [], "no contract row is created by a refused award"


def test_second_non_expired_permit_of_the_same_type_is_rejected(api):
    """PRD §3.5: "A permit type that duplicates a non-expired permit's type on the same contract is rejected with `ERR_DUPLICATE_ACTIVE_PERMIT_TYPE` (HTTP 409)."

    Design: Corner/validations/permit_type_uniqueness_rejects_a_second_non_expired_permit
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)

    first = validate_success(
        api_client.create_permit(contract["id"], permit_payload(), contract_headers), 201
    )
    assert first["permit_type"] == "NPDES_DISCHARGE"

    duplicate = api_client.create_permit(
        contract["id"],
        permit_payload(
            permit_number="OH-2027-202",
            permit_type="NPDES_DISCHARGE",
            regulator="USEPA_REGION",
            effective_date="2026-06-01T00:00:00Z",
        ),
        contract_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ACTIVE_PERMIT_TYPE)

    # A different permit type under the same contract is still allowed.
    other = validate_success(
        api_client.create_permit(
            contract["id"],
            permit_payload(
                permit_number="OH-2027-203",
                permit_type="WATER_ALLOCATION",
                effective_date="2026-06-01T00:00:00Z",
            ),
            contract_headers,
        ),
        201,
    )
    assert other["permit_type"] == "WATER_ALLOCATION"

    permits = get_success_data(
        api_client.list_contract_permits(contract["id"], contract_headers)
    )
    assert len(permits) == 2, "the duplicate permit must not have been persisted"


def test_outstanding_critical_obligation_blocks_hand_back_completion(api):
    """PRD §3.9: "Completing the hand-back is the municipality's act and requires that no critical obligation be `PENDING`, `IN_PROGRESS`, `OVERDUE` or `ESCALATED`, and that the contract be in `HANDING_BACK`; a request that leaves critical obligations outstanding is rejected with `ERR_CRITICAL_OBLIGATIONS_OUTSTANDING` (HTTP 409)"
    PRD §3.9: "Waiving is the municipality's act from `DISPUTED` or from `OVERDUE` and requires the obligation's `is_critical` to be false"

    Design: Corner/validations/critical_obligations_block_hand_back_completion
    """
    scenario = setup_under_review_contract()
    begin_hand_back(scenario.con["id"], scenario.mun_h)
    scenario.refresh_contract()

    critical = create_obligation(
        scenario.con["id"],
        scenario.mun_h,
        obligation_type="ASSET_HANDOVER",
        due_at="2026-10-01T00:00:00Z",
        is_critical=True,
        penalty_per_day_cents=50000,
    )
    soft = create_obligation(
        scenario.con["id"],
        scenario.mun_h,
        obligation_type="SPARES_INVENTORY",
        due_at="2026-10-01T00:00:00Z",
        is_critical=False,
        penalty_per_day_cents=10000,
    )

    set_clock("2026-10-05T00:00:00Z")
    overdue = get_success_data(api_client.evaluate_obligation(soft["id"], scenario.mun_h))
    assert overdue["status"] == "OVERDUE"
    waived = validate_success(
        api_client.waive_obligation(
            soft["id"],
            {
                "waiver_basis": (
                    "The spares inventory was absorbed by the municipality's own stores."
                )
            },
            scenario.mun_h,
        )
    )
    assert waived["status"] == "WAIVED"

    response = api_client.complete_hand_back(scenario.con["id"], scenario.mun_h)
    validate_error(response, ApiErrorId.ERR_CRITICAL_OBLIGATIONS_OUTSTANDING)

    after = get_success_data(api_client.get_contract(scenario.con["id"], scenario.mun_h))
    assert after["status"] == "HANDING_BACK", (
        "the contract does not reach its terminal state while a critical obligation is open"
    )
    critical_after = get_success_data(
        api_client.get_obligation(critical["id"], scenario.mun_h)
    )
    assert critical_after["status"] == "PENDING"
