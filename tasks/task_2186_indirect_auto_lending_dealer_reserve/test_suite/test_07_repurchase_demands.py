"""Repurchase demands, settlement, withdrawal, and the termination cascade."""
from test_helpers import (
    ADMIN, ApiErrorId, CLOCK_START, api_client, assert_buyback_demand, book_contract,
    act_on_buyback_demand, issue_buyback_demand, make_dealer_principal_headers,
    read_application, read_contract, read_dealer, set_clock, setup_funded_contract,
    setup_program, submit_and_approve, submit_application, validate_error,
    validate_paginated, validate_success,
)


def test_issuing_a_demand_freezes_reserve_without_moving_funding_status(api):
    """PRD 3.7: "Issuance copies the contract's `dealer_id` onto the demand and
    moves the contract's `reserve_status` `ACCRUED → HELD` — the entitlement is
    frozen, not yet clawed back, and no ledger entry is written."
    PRD 3.7: "The contract's `funding_status` stays `FUNDED` throughout, which is the
    clearest demonstration of the two dimensions' independence."

    Design: Difficulty/non_linear_state_machine/contract_parallel_funding_and_reserve_dimensions
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-par")
    contract_id = funded["contract"]["id"]
    before = read_contract(contract_id)
    assert before["funding_status"] == "FUNDED"
    assert before["reserve_status"] == "ACCRUED"

    demand = validate_success(
        api.create_buyback_demand(
            {"contract_id": contract_id, "reason": "DOC_DEFECT"}, ADMIN
        ),
        201,
    )
    assert_buyback_demand(demand)
    assert demand["dealer_id"] == program["dealer_id"]

    held = read_contract(contract_id)
    assert held["reserve_status"] == "HELD"
    assert held["funding_status"] == "FUNDED"
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 161058


def test_withdrawing_a_demand_returns_reserve_status_to_accrued(api):
    """PRD 3.7: "A `PortfolioAdmin` may withdraw a demand from `ISSUED`, from
    `ACKNOWLEDGED`, or from `DISPUTED`, moving it to `WITHDRAWN`. No ledger entry is
    written; the contract's `reserve_status` simply reverts `HELD → ACCRUED`,
    restoring the cycle `ACCRUED → HELD → ACCRUED`, and the contract remains `FUNDED`
    and fully eligible for the ordinary chargeback treatment of §3.6."

    Design: Difficulty/non_linear_state_machine/contract_parallel_funding_and_reserve_dimensions
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-par2")
    contract_id = funded["contract"]["id"]
    demand = issue_buyback_demand(contract_id, "DOC_DEFECT")

    withdrawn = validate_success(
        api.buyback_demand_action(demand["id"], {"action": "WITHDRAW"}, ADMIN), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"

    contract = read_contract(contract_id)
    assert contract["reserve_status"] == "ACCRUED"
    assert contract["funding_status"] == "FUNDED"
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 161058, (
        "neither dimension change posts a ledger entry"
    )


def test_settling_a_demand_that_was_never_acknowledged_is_refused(api):
    """PRD 3.7: "Settlement is the `PortfolioAdmin`'s act and is permitted **only**
    from `ACKNOWLEDGED` — a disputed demand must be acknowledged before it can settle
    — and only while the contract is still `FUNDED`."
    PRD 3.7: "an action attempted from a status that does not permit it is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/buyback_settle_from_issued_without_acknowledge_returns_invalid_state
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-bs")
    demand = issue_buyback_demand(funded["contract"]["id"], "FRAUD")

    response = api.buyback_demand_action(
        demand["id"], {"action": "SETTLE", "settlement_date": CLOCK_START}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_buyback_demand(demand["id"], ADMIN), 200)
    assert unchanged["status"] == "ISSUED"
    assert unchanged["settled_at"] is None

    contract = read_contract(funded["contract"]["id"])
    assert contract["funding_status"] == "FUNDED"
    assert contract["reserve_status"] == "HELD"
    dealer = read_dealer(program["dealer_id"])
    assert dealer["reserve_balance_cents"] == 161058
    assert dealer["repurchase_count"] == 0


def test_dispute_and_acknowledgement_may_alternate_indefinitely(api):
    """PRD 3.7: "Acknowledgement, by the `DealerPrincipal` whose `X-User-ID` matches
    the demand's `dealer_id`, is accepted from `ISSUED` or from `DISPUTED` and moves
    the demand to `ACKNOWLEDGED` with no ledger movement."
    PRD 3.7: "Dispute, by the same principal, is accepted from `ISSUED` or from
    `ACKNOWLEDGED`, moves the demand to `DISPUTED`, and records the supplied
    `dispute_reason`, which is retained on the record even after the dispute is later
    resolved."
    PRD 3.7: "The cycle `ISSUED → DISPUTED → ACKNOWLEDGED → DISPUTED` is permitted to
    run indefinitely until the demand is settled or withdrawn"

    Design: Corner/state_machines/buyback_dispute_then_acknowledge_completes_cycle
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-bc")
    demand = issue_buyback_demand(funded["contract"]["id"], "EARLY_DEFAULT")
    dealer_headers = make_dealer_principal_headers(program["dealer_id"])

    disputed = validate_success(
        api.buyback_demand_action(
            demand["id"],
            {"action": "DISPUTE", "dispute_reason": "TITLE_CLEARED_LATE"},
            dealer_headers,
        ),
        200,
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "TITLE_CLEARED_LATE"

    acknowledged = validate_success(
        api.buyback_demand_action(demand["id"], {"action": "ACKNOWLEDGE"}, dealer_headers),
        200,
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["dispute_reason"] == "TITLE_CLEARED_LATE"

    again = validate_success(
        api.buyback_demand_action(
            demand["id"],
            {"action": "DISPUTE", "dispute_reason": "SECOND_LOOK"},
            dealer_headers,
        ),
        200,
    )
    assert again["status"] == "DISPUTED"
    assert again["dispute_reason"] == "SECOND_LOOK"
    assert read_contract(funded["contract"]["id"])["reserve_status"] == "HELD"


def test_demand_snapshot_amortizes_principal_on_a_straight_line(api):
    """PRD 3.7: "Elapsed seasoning is taken as the whole days between the contract's
    `funded_at` and the **current logical instant**, divided by 30 and rounded down,
    then capped at the contract's `term_months`. The demand's
    `unpaid_principal_cents` is `amount_financed_cents` less the straight-line repaid
    principal — `amount_financed_cents` multiplied by those capped months, divided by
    `term_months`, rounded half up to whole cents."
    PRD 3.7: "Its `admin_fee_cents` is the flat repurchase administration fee of
    25,000 cents. And its `buyback_amount_cents` is `unpaid_principal_cents` plus
    `reserve_offset_cents` plus `admin_fee_cents`."

    Design: Corner/calculations/buyback_unpaid_principal_amortizes_straight_line_at_six_months
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-am")
    set_clock("2027-02-01T00:00:00Z")

    demand = validate_success(
        api.create_buyback_demand(
            {"contract_id": funded["contract"]["id"], "reason": "FRAUD"}, ADMIN
        ),
        201,
    )
    assert_buyback_demand(demand)
    assert demand["unpaid_principal_cents"] == 2520900
    assert demand["reserve_offset_cents"] == 161058
    assert demand["admin_fee_cents"] == 25000
    assert demand["buyback_amount_cents"] == 2706958
    assert read_contract(funded["contract"]["id"])["reserve_status"] == "HELD"


def test_a_demand_against_an_unfunded_contract_is_refused(api):
    """PRD 3.7: "The named contract must have `funding_status` `FUNDED` and must not
    already carry another demand in `ISSUED`, `ACKNOWLEDGED`, or `DISPUTED`; either
    failure is `ERR_CONTRACT_NOT_FUNDED` (HTTP 409)."

    Design: Corner/endpoints/buyback_demand_on_unfunded_contract_returns_contract_not_funded
    """
    program = setup_program()
    application = submit_and_approve(program["dealer_id"], applicant_reference="APP-uf")
    contract = book_contract(application["id"], program["dealer_id"])

    response = api.create_buyback_demand(
        {"contract_id": contract["id"], "reason": "DOC_DEFECT"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FUNDED.value, 409)

    refreshed = read_contract(contract["id"])
    assert refreshed["reserve_status"] == "NONE"
    assert refreshed["funding_status"] == "PENDING_DOCS"
    _, meta = validate_paginated(
        api.list_buyback_demands(ADMIN, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0


def _setup_two_funded_contracts(program):
    small = setup_funded_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-c2", "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
        },
        doc_prefix="IMG-c2",
    )
    large = setup_funded_contract(
        program,
        application_overrides={"applicant_reference": "APP-c1"},
        doc_prefix="IMG-c1",
    )
    return small, large


def test_settlement_repurchases_the_contract_and_offsets_its_reserve(api):
    """PRD 3.7: "The contract advances `FUNDED → REPURCHASED` on the first dimension
    and `HELD → CHARGED_BACK` on the second. A single ledger entry of `entry_type`
    `BUYBACK_OFFSET` is posted for the negative of the demand's frozen
    `reserve_offset_cents`, clawing back everything the contract ever credited."
    PRD 3.7: "The admin supplies a `settlement_date`, which is recorded as the
    demand's `settled_at`, and the demand moves `ACKNOWLEDGED → SETTLED`."

    Design: Difficulty/compensating_invariant/fund_then_buyback_settlement_conserves_portfolio_exposure
    """
    program = setup_program()
    _, large = _setup_two_funded_contracts(program)
    contract_id = large["contract"]["id"]

    demand = issue_buyback_demand(contract_id, "DOC_DEFECT")
    assert demand["unpaid_principal_cents"] == 2801000
    assert demand["reserve_offset_cents"] == 161058
    assert demand["admin_fee_cents"] == 25000
    assert demand["buyback_amount_cents"] == 2987058

    act_on_buyback_demand(demand["id"], "ACKNOWLEDGE", dealer_id=program["dealer_id"])
    settled = validate_success(
        api.buyback_demand_action(
            demand["id"], {"action": "SETTLE", "settlement_date": CLOCK_START}, ADMIN
        ),
        200,
    )
    assert settled["status"] == "SETTLED"

    contract = read_contract(contract_id)
    assert contract["funding_status"] == "REPURCHASED"
    assert contract["reserve_status"] == "CHARGED_BACK"
    assert contract["unpaid_principal_cents"] == 0

    entries, meta = validate_paginated(
        api.list_reserve_entries(
            ADMIN,
            params={"contract_id": contract_id, "entry_type": "BUYBACK_OFFSET"},
        )
    )
    assert meta["total_count"] == 1
    assert entries[0]["amount_cents"] == -161058


def test_settlement_returns_portfolio_exposure_to_its_pre_funding_position(api):
    """PRD 3.7: "the dealership's `repurchase_count` increases by one;
    `reserve_balance_cents`, `outstanding_principal_cents`, and
    `funded_contract_count` are recomputed; and `Dealer.version` advances by one."
    PRD 2.8: "`funded_contract_count` is the number of this dealership's contracts
    whose `funding_status` is `FUNDED`."

    Design: Difficulty/compensating_invariant/fund_then_buyback_settlement_conserves_portfolio_exposure
    """
    program = setup_program()
    small, large = _setup_two_funded_contracts(program)
    assert read_dealer(program["dealer_id"])["outstanding_principal_cents"] == 3801000

    demand = issue_buyback_demand(large["contract"]["id"], "DOC_DEFECT")
    act_on_buyback_demand(demand["id"], "ACKNOWLEDGE", dealer_id=program["dealer_id"])
    act_on_buyback_demand(demand["id"], "SETTLE", settlement_date=CLOCK_START)

    dealer = read_dealer(program["dealer_id"])
    assert dealer["outstanding_principal_cents"] == 1000000
    assert dealer["funded_contract_count"] == 1
    assert dealer["repurchase_count"] == 1
    assert dealer["reserve_balance_cents"] == 57500

    sibling = read_contract(small["contract"]["id"])
    assert sibling["funding_status"] == "FUNDED"
    assert sibling["unpaid_principal_cents"] == 1000000


def _setup_termination_scenario():
    program = setup_program()
    funded = setup_funded_contract(
        program, application_overrides={"applicant_reference": "APP-c1"},
        doc_prefix="IMG-tc",
    )
    open_file = submit_application(
        program["dealer_id"], applicant_reference="APP-hold",
        monthly_debt_cents=180000, amount_financed_cents=1000000,
        collateral_value_cents=1000000,
    )
    return program, funded, open_file


def test_termination_terminates_the_agreement_and_withdraws_open_files(api):
    """PRD 3.9: "**Link one:** the dealership advances to `TERMINATED`, which is
    terminal and from which nothing returns, and `suspension_reason` is set to the
    supplied `reason` or to the sentinel `TERMINATION`."
    PRD 3.9: "**Link two, caused by link one:** every agreement of this dealership
    whose `status` is `PENDING_COUNTERSIGN` or `ACTIVE` transitions to `TERMINATED`;
    no ledger movement accompanies this."
    PRD 3.9: "**Link three, caused by link two:** every application pinned to an
    agreement that link two just terminated — together with every application of this
    dealership whose `agreement_id` is still null — whose `status` is `SUBMITTED`,
    `CONDITIONED`, `RESUBMITTED`, `APPROVED`, or `ON_HOLD` transitions to `WITHDRAWN`,
    with `held_from_status` cleared to null."

    Design: Difficulty/transitive_cascade/dealer_termination_cascade_to_buyback_and_reserve_hold
    """
    program, funded, open_file = _setup_termination_scenario()

    terminated = validate_success(
        api.dealer_status_action(
            program["dealer_id"], {"action": "TERMINATE", "reason": "PROGRAM_EXIT"}, ADMIN
        ),
        200,
    )
    assert terminated["status"] == "TERMINATED"

    agreement = validate_success(
        api.get_agreement(program["agreement"]["id"], ADMIN), 200
    )
    assert agreement["status"] == "TERMINATED"

    withdrawn = read_application(open_file["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["held_from_status"] is None


def test_termination_issues_a_dealer_termination_demand_and_holds_reserve(api):
    """PRD 3.9: "**Link four, also caused by link two:** for every contract of this
    dealership whose `funding_status` is `FUNDED` and whose seasoning is strictly less
    than the window implied by its pinned agreement's `chargeback_window_days`, a
    repurchase demand is issued with `reason` `DEALER_TERMINATION`, and those demands
    are issued in ascending contract `funded_at` order, tie-broken by ascending
    contract `created_at`, each taking the same frozen settlement snapshot §3.7
    describes."
    PRD 3.9: "**Link five, caused by link four:** each demand so issued moves its
    contract's `reserve_status` `ACCRUED → HELD`."

    Design: Difficulty/transitive_cascade/dealer_termination_cascade_to_buyback_and_reserve_hold
    """
    program, funded, _ = _setup_termination_scenario()
    contract_id = funded["contract"]["id"]

    validate_success(
        api.dealer_status_action(
            program["dealer_id"], {"action": "TERMINATE", "reason": "PROGRAM_EXIT"}, ADMIN
        ),
        200,
    )

    demands, meta = validate_paginated(
        api.list_buyback_demands(ADMIN, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == 1
    demand = demands[0]
    assert demand["reason"] == "DEALER_TERMINATION"
    assert demand["status"] == "ISSUED"
    assert demand["unpaid_principal_cents"] == 2801000
    assert demand["reserve_offset_cents"] == 161058
    assert demand["admin_fee_cents"] == 25000
    assert demand["buyback_amount_cents"] == 2987058

    contract = read_contract(contract_id)
    assert contract["reserve_status"] == "HELD"
    assert contract["funding_status"] == "FUNDED"
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 161058, (
        "termination alone posts no ledger entry"
    )


def test_the_termination_cascade_is_visible_immediately(api):
    """PRD 3.9: "**Link one:** the dealership advances to `TERMINATED`, which is
    terminal and from which nothing returns"
    PRD 3.9: "**Link two, caused by link one:** every agreement of this dealership
    whose `status` is `PENDING_COUNTERSIGN` or `ACTIVE` transitions to `TERMINATED`"
    PRD 3.9: "**Link five, caused by link four:** each demand so issued moves its
    contract's `reserve_status` `ACCRUED → HELD`."

    Design: Corner/consistency_model/termination_cascade_is_visible_in_the_same_request_and_immediately_after
    """
    program, funded, _ = _setup_termination_scenario()

    response = api.dealer_status_action(
        program["dealer_id"], {"action": "TERMINATE", "reason": "PROGRAM_EXIT"}, ADMIN
    )
    body = validate_success(response, 200)
    assert body["status"] == "TERMINATED", (
        "the response body itself already reports the terminal status"
    )

    agreement = validate_success(
        api.get_agreement(program["agreement"]["id"], ADMIN), 200
    )
    assert agreement["status"] == "TERMINATED"

    demands, _ = validate_paginated(
        api.list_buyback_demands(
            ADMIN, params={"contract_id": funded["contract"]["id"]}
        )
    )
    assert demands[0]["status"] == "ISSUED"
    assert demands[0]["reason"] == "DEALER_TERMINATION"
    assert read_contract(funded["contract"]["id"])["reserve_status"] == "HELD"
