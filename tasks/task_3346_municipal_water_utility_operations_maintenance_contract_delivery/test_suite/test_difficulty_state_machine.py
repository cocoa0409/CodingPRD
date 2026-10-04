"""Difficulty-queue tests for the cyclic state machines and the conserved ledger.

Both tests walk a machine through a cycle that only exists because two entities
are coupled, and both drive the logical clock rather than wall-clock time.
"""
from test_helpers import (
    api_client,
    assert_obligation_invariants,
    award_contract,
    begin_hand_back,
    create_obligation,
    create_standard,
    get_success_data,
    penalty_allocation_payload,
    permit_payload,
    read_contract,
    register_municipality,
    set_clock,
    setup_under_review_contract,
    validate_success,
)


def test_obligation_dispute_cycle_returns_to_overdue_then_waives_into_renewal(api):
    """PRD §3.9: "Because dispute and uphold are both available, `DISPUTED` → `OVERDUE` → `DISPUTED` may repeat while the obligation remains outstanding."
    PRD §3.9: "Waiving is the municipality's act from `DISPUTED` or from `OVERDUE` and requires the obligation's `is_critical` to be false; a critical obligation cannot be waived and an attempt is rejected with `ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE` (HTTP 403)."
    PRD §3.9: "Waiving resets the withholding to 0 and moves the obligation to the terminal `WAIVED`."
    PRD §3.9: "Returning to renewal is the municipality's act and requires that every critical obligation under the contract be `SATISFIED` or `WAIVED`; on success every obligation still in `PENDING` or `IN_PROGRESS` is waived, `status_changed_at` is stamped, and the contract's version increments."
    PRD §3.9: "The `withholding_cents` for an obligation that is not `SATISFIED` and not `WAIVED` is `outstanding_days` multiplied by `penalty_per_day_cents`, capped at 4,000,000 cents"

    Design: Difficulty/non_linear_state_machine/hand_back_obligation_dispute_cycle_between_two_machines
    """
    scenario = setup_under_review_contract()
    begin_hand_back(scenario.con["id"], scenario.mun_h)
    scenario.refresh_contract()
    assert scenario.con["status"] == "HANDING_BACK", (
        "the hand-back must be reachable from UNDER_REVIEW"
    )

    target = create_obligation(
        scenario.con["id"],
        scenario.mun_h,
        obligation_type="RECORDS_TRANSFER",
        due_at="2026-06-01T00:00:00Z",
        is_critical=False,
        penalty_per_day_cents=25000,
    )
    # Clear every obligation the hand-back generated so that the renewal gate is
    # decided by the obligation under test alone.
    generated = get_success_data(
        api_client.list_contract_obligations(scenario.con["id"], scenario.con_h)
    )
    for obligation in generated:
        if obligation["id"] != target["id"] and obligation["status"] in (
            "PENDING",
            "IN_PROGRESS",
        ):
            get_success_data(
                api_client.satisfy_obligation(
                    obligation["id"],
                    {"evidence_reference": "Hand-over pack accepted by the municipality."},
                    scenario.con_h,
                )
            )

    # Four whole days past the due instant.
    set_clock("2026-06-05T00:00:00Z")
    overdue = get_success_data(
        api_client.evaluate_obligation(target["id"], scenario.mun_h)
    )
    assert overdue["status"] == "OVERDUE"
    assert overdue["outstanding_days"] == 4
    assert overdue["withholding_cents"] == 100000, (
        "withholding accrues at four elapsed whole days times the daily rate"
    )
    assert_obligation_invariants(overdue)

    disputed = get_success_data(
        api_client.dispute_obligation(
            target["id"],
            {"dispute_basis": "The records index was transferred on schedule."},
            scenario.con_h,
        )
    )
    assert disputed["status"] == "DISPUTED", "disputing an OVERDUE obligation suspends accrual"

    upheld = get_success_data(api_client.uphold_obligation(target["id"], scenario.mun_h))
    assert upheld["status"] == "OVERDUE", "upholding returns the obligation to OVERDUE"
    assert upheld["withholding_cents"] == 100000, (
        "upholding recomputes the withholding over the elapsed whole days"
    )

    disputed_again = get_success_data(
        api_client.dispute_obligation(
            target["id"],
            {"dispute_basis": "Second review of the transfer log is pending."},
            scenario.con_h,
        )
    )
    assert disputed_again["status"] == "DISPUTED", (
        "the DISPUTED to OVERDUE to DISPUTED cycle may repeat while the obligation is outstanding"
    )

    waived = get_success_data(
        api_client.waive_obligation(
            target["id"],
            {
                "waiver_basis": (
                    "Non-critical obligation waived to allow the renewal round to proceed."
                )
            },
            scenario.mun_h,
        )
    )
    assert waived["status"] == "WAIVED"
    assert waived["withholding_cents"] == 0, "waiving resets the withholding to 0"

    contract = get_success_data(api_client.enter_renewal(scenario.con["id"], scenario.mun_h))
    assert contract["status"] == "RENEWAL_PENDING", (
        "with every critical obligation cleared the contract returns to renewal"
    )


def test_voided_allocation_is_replaced_and_the_operator_penalty_total_is_conserved(api):
    """PRD §3.4: "Voiding is available from `CONTESTED` and requires that no allocation under the same permit already be `SETTLED`; it supplies a `void_basis`, and decreases the owning contract's penalty total by the previously allocated operator share."
    PRD §3.4: "creating one computes both share figures, increases the owning contract's `total_operator_penalty_cents` by the operator share, and increments the contract's version"
    PRD §3.9: "The penalty total is the sum of `operator_share_cents` over the contract's penalty allocations whose status is not `VOIDED`."

    Design: Difficulty/compensating_invariant/void_and_reallocate_conserve_total_operator_penalty
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)
    create_standard(contract["id"], contract_headers, activate=False)
    permit = get_success_data(
        api_client.create_permit(contract["id"], permit_payload(), contract_headers)
    )

    first = validate_success(
        api_client.create_penalty_allocation(
            permit["id"],
            penalty_allocation_payload(total_penalty_cents=2000000),
            municipality_headers,
        ),
        201,
    )
    assert first["operator_share_cents"] == 900000
    running = read_contract(contract["id"], contract_headers)
    assert running["total_operator_penalty_cents"] == 900000, (
        "recording an allocation raises the contract's operator penalty total"
    )

    contested = validate_success(
        api_client.contest_allocation(
            first["id"],
            {"contest_basis": "The bypass was caused by upstream municipal sewer surcharge."},
            municipality_headers,
        )
    )
    assert contested["status"] == "CONTESTED"
    voided = validate_success(
        api_client.void_allocation(
            first["id"],
            {"void_basis": "The regulator withdrew its citation on review."},
            municipality_headers,
        )
    )
    assert voided["status"] == "VOIDED"

    after_void = read_contract(contract["id"], contract_headers)
    assert after_void["total_operator_penalty_cents"] == 0, (
        "voiding removes the previously allocated operator share from the contract total"
    )

    second = validate_success(
        api_client.create_penalty_allocation(
            permit["id"],
            penalty_allocation_payload(
                violation_code="40CFR122-BYPASS-R", total_penalty_cents=2000000
            ),
            municipality_headers,
        ),
        201,
    )
    assert second["operator_share_cents"] == 900000, (
        "an equivalent replacement allocation carries the same forward-looking share"
    )

    conserved = read_contract(contract["id"], contract_headers)
    assert conserved["total_operator_penalty_cents"] == 900000, (
        "the contract total must equal the sum over allocations that are not VOIDED"
    )
