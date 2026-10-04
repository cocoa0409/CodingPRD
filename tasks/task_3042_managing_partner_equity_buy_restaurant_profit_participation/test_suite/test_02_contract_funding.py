"""Contract lifecycle tests: creation, funding, activation, OCC, escrow
conservation, sweeps, overpayment, transfer, and close blocking."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_partner,
    create_active_restaurant,
    create_draft_contract,
    submit_contract,
    fund_contract,
    setup_active_contract,
    setup_buyout_pending_contract,
    set_clock,
    TEST_USERS,
    make_managing_partner_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HR = TEST_USERS["hr_recruiter_headers"]
CONTROLLER = TEST_USERS["corporate_controller_headers"]


def test_contract_get_unknown_id_returns_contract_not_found(api):
    """PRD §2.5 item 3: "Path existence — each identifier in the URL path must
    resolve, validated left to right; the first unresolvable identifier yields
    its specific not-found error (for example ERR_PARTNER_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND ...)."

    Design: Corner/entities/contract_get_unknown_id_returns_contract_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.get_contract("00000000-0000-0000-0000-000000000000", CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)


def test_contract_and_period_inverted_dates_rejected(api):
    """PRD §3.3: "The term is a half-open interval: it begins on
    `term_start_date` and ends just before `term_end_date`, so `term_end_date`
    is exclusive and must be strictly after `term_start_date`."
    PRD §3.5: "An `OperationsAuditor` opens a profit period for a restaurant by
    supplying a `restaurant_id`, a `period_start_date` (inclusive), and a
    `period_end_date` (exclusive, and strictly after the start)."
    PRD §2.5 item 8: "Structural constraints — malformed fields, bad enums,
    inverted date intervals, non-positive amounts, out-of-range percentages
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/contract_create_dates_inverted_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    resp_contract = api.create_contract(
        {
            "partner_id": partner["id"],
            "restaurant_id": restaurant["id"],
            "term_start_date": "2032-01-01",
            "term_end_date": "2027-01-01",
            "buy_in_required_cents": 2500000,
        },
        CONTROLLER,
    )
    validate_error(resp_contract, ApiErrorId.ERR_INVALID_REQUEST)
    resp_period = api.create_profit_period(
        {
            "restaurant_id": restaurant["id"],
            "period_start_date": "2027-05-01",
            "period_end_date": "2027-04-01",
        },
        TEST_USERS["operations_auditor_headers"],
    )
    validate_error(resp_period, ApiErrorId.ERR_INVALID_REQUEST)


def test_contract_initial_state_and_submit_transitions(api):
    """PRD §3.3: "A new contract begins in `DRAFT` with `buy_in_escrow_cents`
    at 0, `capital_account_cents` at 0, `renewed_count` at 0, and `submitted_at`
    and `departure_date` unset."
    PRD §3.3: "Submitting a contract moves it from `DRAFT` to `PENDING_FUNDING`
    and stamps `submitted_at` with the logical clock."

    Design: Corner/state_machines/contract_initial_state_is_draft_and_submit_moves_to_pending_funding
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    assert contract["status"] == "DRAFT"
    assert contract["version"] == 1
    assert contract["buy_in_escrow_cents"] == 0
    assert contract["capital_account_cents"] == 0
    assert contract["renewed_count"] == 0
    assert contract["submitted_at"] is None

    submitted = submit_contract(contract["id"])
    assert submitted["status"] == "PENDING_FUNDING"
    assert submitted["submitted_at"] == "2026-09-01T00:00:00.000Z"
    assert submitted["version"] == 2


def test_activate_from_draft_rejected(api):
    """PRD §3.3: "A new contract begins in DRAFT ... Contracts are immutable
    once created — there is no edit transition; a changed term requires a new
    contract."
    PRD §2.5 item 5: "State — the target resource must be in a from-state that
    permits the requested transition (ERR_INVALID_STATE) ..."

    Design: Corner/state_machines/activate_from_draft_is_an_invalid_transition
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    resp = api.activate_contract(contract["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["status"] == "DRAFT"
    assert fetched["version"] == 1


def test_buy_in_payment_on_draft_contract_rejected(api):
    """PRD §3.3: "Once a contract is pending funding, the managing partner
    funds the buy-in escrow by posting payments ..."
    PRD §2.5 item 5: "State — the target resource must be in a from-state that
    permits the requested transition (ERR_INVALID_STATE) ..."

    Design: Corner/state_machines/buy_in_payment_on_draft_contract_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    resp = api.post_buy_in_payment(
        contract["id"], {"amount_cents": 100}, make_managing_partner_headers(partner["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["buy_in_escrow_cents"] == 0
    _, meta = validate_paginated(api.list_buy_in_payments(contract["id"], CONTROLLER))
    assert meta["total_count"] == 0


def test_overpayment_beyond_required_buy_in_rejected(api):
    """PRD §3.3: "Overpayment is rejected: a payment that would push the
    escrow above buy_in_required_cents fails with ERR_BUY_IN_OVERPAYMENT, so
    the escrow never exceeds the requirement."

    Design: Corner/state_machines/overpayment_beyond_required_buy_in_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    submit_contract(contract["id"])
    fund_contract(contract["id"], partner["id"], 2000000)
    resp = api.post_buy_in_payment(
        contract["id"], {"amount_cents": 600000}, make_managing_partner_headers(partner["id"])
    )
    validate_error(resp, ApiErrorId.ERR_BUY_IN_OVERPAYMENT)
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["buy_in_escrow_cents"] == 2000000
    fund_contract(contract["id"], partner["id"], 500000)
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["buy_in_escrow_cents"] == 2500000


def test_activation_moves_escrow_to_capital_and_places_partner(api):
    """PRD §3.3: "When activation succeeds, the escrow balance moves
    wholesale: capital_account_cents takes the full escrow amount,
    buy_in_escrow_cents resets to 0, the partner's placed_restaurant_id is set
    to the contract's restaurant, and the partner moves from CERTIFIED to
    PLACED."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_escrow_and_version
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    assert contract["version"] == 1
    submit_contract(contract["id"])
    fund_contract(contract["id"], partner["id"], 1000000)
    mid = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert mid["buy_in_escrow_cents"] == 1000000
    fund_contract(contract["id"], partner["id"], 1500000)
    activated = validate_success(api.activate_contract(contract["id"], CONTROLLER))
    assert activated["status"] == "ACTIVE"
    assert activated["buy_in_escrow_cents"] == 0
    assert activated["capital_account_cents"] == 2500000
    assert activated["version"] >= 4
    partner_now = validate_success(api.get_partner(partner["id"], HR))
    assert partner_now["status"] == "PLACED"
    assert partner_now["placed_restaurant_id"] == restaurant["id"]


def test_funding_lapse_sweep_refunds_and_withdraws(api):
    """PRD §3.3: "If the funding window lapses before activation, the clock
    sweep moves the contract from PENDING_FUNDING to LAPSED and unwinds the
    escrow: every POSTED buy-in payment on the contract flips to REFUNDED,
    buy_in_escrow_cents resets to 0, and the partner moves to WITHDRAWN."
    PRD §2.10: "The funding window for a submitted contract is 14 days from
    submitted_at."

    Design: Corner/state_machines/funding_lapse_sweep_refunds_and_withdraws
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner(full_name="Sam Reed", email="sr@x.com")
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    submit_contract(contract["id"])
    payment = fund_contract(contract["id"], partner["id"], 1000000)

    set_clock("2026-09-16T00:00:00Z")  # past submitted_at + 14 days
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["status"] == "LAPSED"
    assert fetched["buy_in_escrow_cents"] == 0
    payments, _ = validate_paginated(api.list_buy_in_payments(contract["id"], CONTROLLER))
    by_id = {p["id"]: p for p in payments}
    assert by_id[payment["id"]]["status"] == "REFUNDED"
    partner_now = validate_success(api.get_partner(partner["id"], HR))
    assert partner_now["status"] == "WITHDRAWN"


def test_contract_expiry_sweep_returns_partner_to_certified_pool(api):
    """PRD §3.4: "Whether a contract is `ACTIVE` or `RENEWAL_OFFERED`, once the
    logical clock's date reaches the `term_end_date`, the sweep moves the
    contract to `EXPIRED` and returns the partner from `PLACED` to `CERTIFIED`,
    clearing their placement."

    Design: Corner/state_machines/contract_expiry_sweep_returns_partner_to_certified_pool
    """
    setup = setup_active_contract(term_start_date="2027-01-01", term_end_date="2028-01-01")
    set_clock("2027-12-31T00:00:00Z")
    fetched = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    assert fetched["status"] == "ACTIVE"
    set_clock("2028-01-01T00:00:00Z")
    fetched = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    assert fetched["status"] == "EXPIRED"
    partner_now = validate_success(api.get_partner(setup["partner"]["id"], HR))
    assert partner_now["status"] == "CERTIFIED"
    assert partner_now["placed_restaurant_id"] is None


def test_second_contract_on_same_restaurant_rejected(api):
    """PRD §3.3: "no other contract for the same restaurant may already exist
    in PENDING_FUNDING, ACTIVE, RENEWAL_OFFERED, or BUYOUT_PENDING (otherwise
    ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT) ..."

    Design: Corner/validations/second_contract_on_same_restaurant_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    partner1 = create_partner(full_name="Pat Morgan", email="pm@x.com")
    partner2 = create_partner(full_name="Sam Reed", email="sr@x.com")
    restaurant = create_active_restaurant()
    c1 = create_draft_contract(partner1["id"], restaurant["id"])
    submit_contract(c1["id"])
    fund_contract(c1["id"], partner1["id"], 2500000)
    validate_success(api.activate_contract(c1["id"], CONTROLLER))
    c2 = create_draft_contract(partner2["id"], restaurant["id"], buy_in_required_cents=1000000)
    resp = api.submit_contract(c2["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT)
    fetched = validate_success(api.get_contract(c2["id"], CONTROLLER))
    assert fetched["status"] == "DRAFT"


def test_transfer_creates_successor_draft_contract(api):
    """PRD §3.4: "A CorporateController transfers the contract by naming a
    successor_partner_id. The successor must exist with role_in_program of
    MANAGING_PARTNER and status CERTIFIED — otherwise ERR_SUCCESSOR_NOT_ELIGIBLE
    — and no buyout order may already exist on the contract in DRAFT or
    APPROVED, or the transfer is rejected with ERR_BUYOUT_ALREADY_OPEN. On
    transfer, the old partner moves from PLACED back to CERTIFIED with
    placed_restaurant_id cleared; the successor moves from CERTIFIED to PLACED
    with placed_restaurant_id set to the restaurant; and a brand-new contract
    row is created in DRAFT for the successor on the same restaurant with a
    fresh term starting at the logical clock's date."

    Design: Corner/endpoints/transfer_creates_successor_draft_contract
    """
    set_clock("2026-09-01T00:00:00Z")
    successor = create_partner(full_name="Succ Esor", email="su@x.com")
    validate_success(api.start_training(successor["id"], HR))
    set_clock("2027-09-07T00:00:00Z")  # 371 days -> 53 full weeks
    validate_success(api.certify_partner(successor["id"], HR))
    setup = setup_buyout_pending_contract(clock_at="2028-06-01T00:00:00Z")
    transferred = validate_success(
        api.transfer_contract(
            setup["contract"]["id"],
            {"successor_partner_id": successor["id"]},
            CONTROLLER,
        )
    )
    assert transferred["status"] == "TRANSFERRED"
    old_partner = validate_success(api.get_partner(setup["partner"]["id"], HR))
    assert old_partner["status"] == "CERTIFIED"
    assert old_partner["placed_restaurant_id"] is None
    successor_now = validate_success(api.get_partner(successor["id"], HR))
    assert successor_now["status"] == "PLACED"
    assert successor_now["placed_restaurant_id"] == setup["restaurant"]["id"]
    rows, meta = validate_paginated(
        api.list_contracts(CONTROLLER, params={"restaurant_id": setup["restaurant"]["id"]})
    )
    assert meta["total_count"] == 2
    by_status = {row["status"]: row for row in rows}
    assert setup["contract"]["id"] in [r["id"] for r in rows]
    new_contract = by_status["DRAFT"]
    assert new_contract["partner_id"] == successor["id"]


def test_restaurant_close_blocked_by_open_contract_then_succeeds_after_settlement(api):
    """PRD §3.2: "Closing a restaurant moves it from ACTIVE to CLOSED, but the
    close is blocked with ERR_RESTAURANT_HAS_OPEN_CONTRACTS while any contract
    on the restaurant sits in PENDING_FUNDING, ACTIVE, RENEWAL_OFFERED, or
    BUYOUT_PENDING."
    PRD §3.4: "Payment moves it from APPROVED to PAID and fires the depth-3
    cascade: the contract moves from BUYOUT_PENDING to SETTLED ..."

    Design: Corner/endpoints/restaurant_close_blocked_by_open_contract
    """
    setup = setup_active_contract()
    resp = api.close_restaurant(setup["restaurant"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESTAURANT_HAS_OPEN_CONTRACTS)

    set_clock("2028-06-01T00:00:00Z")
    validate_success(
        api.depart_contract(
            setup["contract"]["id"],
            make_managing_partner_headers(setup["partner"]["id"]),
        )
    )
    contract = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    order = validate_success(
        api.create_buyout_order(
            contract["id"],
            {"offset_cents": 0, "expected_contract_version": contract["version"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    validate_success(api.approve_buyout_order(order["id"], CONTROLLER))
    validate_success(api.pay_buyout_order(order["id"], CONTROLLER))
    closed = validate_success(api.close_restaurant(setup["restaurant"]["id"], ADMIN))
    assert closed["status"] == "CLOSED"


def test_occ_stale_version_on_buyout_create(api):
    """PRD §2.7: "Creating a buyout order against a contract requires
    `expected_contract_version`, matching the contract's current `version`. A
    departure, renewal, or any other contract mutation that has advanced the
    version since the writer priced the buyout causes the create to be
    rejected, preventing the writer from pricing against a contract state it
    has not observed."
    PRD §2.7: "a mismatch with the parent entity's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_layers/occ_stale_version_on_buyout_create
    """
    setup = setup_buyout_pending_contract(clock_at="2028-06-01T00:00:00Z")
    contract = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    current_version = contract["version"]
    resp = api.create_buyout_order(
        contract["id"],
        {"offset_cents": 0, "expected_contract_version": current_version - 1},
        CONTROLLER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    rows, meta = validate_paginated(
        api.list_buyout_orders(CONTROLLER, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0
    order = validate_success(
        api.create_buyout_order(
            contract["id"],
            {"offset_cents": 0, "expected_contract_version": current_version},
            CONTROLLER,
        ),
        expected_status=201,
    )
    assert order["status"] == "DRAFT"
