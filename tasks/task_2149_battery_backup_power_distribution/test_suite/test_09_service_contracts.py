"""UPS service contracts: runtime sizing, coverage pricing and attachment."""
import pytest

from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    create_account, create_battery_model, create_service_contract, size_service_contract,
    read_service_contract,
)

REP = TEST_USERS["sales_rep_headers"]


def _draft_contract_with_two_candidate_models():
    account = create_account(name="Metro Data Halls", account_tier="GOLD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=3)
    agm = create_battery_model("IB-AGM-95")
    lfp = create_battery_model("IB-LFP-100")
    contract = create_service_contract(
        account["id"], coverage_tier="GOLD", load_watts=2400,
        required_runtime_minutes=90, system_voltage=48, ambient_temp_c=10.0,
        allowed_chemistries=["AGM", "LITHIUM_IRON_PHOSPHATE"],
    )
    return {"account": account, "agm": agm, "lfp": lfp, "contract": contract}


def test_sizing_derives_the_load_the_derate_and_the_peukert_requirement():
    """PRD §3.8: "The `dc_load_amps` is the AC load divided by the product of
    the bus voltage and an inverter efficiency of 0.90, rounded half up to three
    decimals."
    PRD §3.8: "The `temp_derate_factor` is selected from the design ambient by a
    descending ladder: 1.00 at 25.0 degrees Celsius or warmer, 0.95 at 15.0
    degrees or warmer but below 25.0, 0.87 at 5.0 degrees or warmer but below
    15.0, and 0.75 below 5.0 degrees."
    PRD §3.8: "The Peukert-adjusted requirement is the direct-current load in
    amps multiplied by the runtime in hours raised to the power of that model's
    `peukert_exponent`, rounded half up to three decimals."

    Design: Difficulty/combinatorial_formula/runtime_sizing_peukert_derate_and_unit_count_tiebreak
    """
    ctx = _draft_contract_with_two_candidate_models()
    sized = size_service_contract(ctx["contract"]["id"])

    assert sized["dc_load_amps"] == pytest.approx(55.556, abs=0.0005)
    assert sized["temp_derate_factor"] == pytest.approx(0.87, abs=1e-9)
    assert sized["required_peukert_ah"] == pytest.approx(86.782, abs=0.0005)


def test_sizing_picks_the_cheaper_design_when_the_unit_counts_tie():
    """PRD §3.8: "The units wired in series inside one string is the bus voltage
    divided by the model's nominal voltage, rounded **up** to a whole number.
    The number of parallel strings is the Peukert-adjusted requirement divided
    by the usable capacity of one unit, again rounded **up** to a whole number;
    both ceilings are taken on the already-rounded three-decimal values. The
    model's total unit count is the string count multiplied by the units per
    string."
    PRD §3.8: "Candidates are ranked by total unit count ascending; ties are
    broken by the total unit count multiplied by the model's `list_price_cents`
    ascending, which prefers the cheaper of two equally compact designs; and any
    remaining tie is broken by the earlier `created_at`, compared at millisecond
    precision."
    PRD §3.8: "The `prepay_total_cents` is the monthly fee multiplied by 12, a
    full year prepaid, and that is the amount that will be booked onto an order.
    Sizing moves the contract `DRAFT → SIZED`."

    Design: Difficulty/combinatorial_formula/runtime_sizing_peukert_derate_and_unit_count_tiebreak
    """
    ctx = _draft_contract_with_two_candidate_models()
    sized = size_service_contract(ctx["contract"]["id"])

    assert sized["sized_battery_model_id"] == ctx["agm"]["id"], \
        "Eight units of AGM cost less than eight units of lithium"
    assert sized["sized_units_per_string"] == 4
    assert sized["sized_string_count"] == 2
    assert sized["sized_unit_count"] == 8
    assert sized["covered_value_cents"] == 208000
    assert sized["monthly_fee_cents"] == 9900, \
        f"The GOLD floor lifts the fee to 9900, got {sized['monthly_fee_cents']}"
    assert sized["prepay_total_cents"] == 118800
    assert sized["status"] == "SIZED"


def _order_with_a_gold_contract_attached():
    from test_helpers import (create_warehouse, create_order, add_line, submit_order,
                              attach_service_contract, read_order)
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Metro Data Halls", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=3)
    agm = create_battery_model("IB-AGM-95")
    lfp = create_battery_model("IB-LFP-100")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-11")
    add_line(order["id"], agm["id"], 4, core_expected_count=0)
    order = submit_order(order["id"])
    gold = create_service_contract(account["id"], coverage_tier="GOLD")
    gold = size_service_contract(gold["id"])
    attach_service_contract(gold["id"], order["id"], order["version"])
    return {"warehouse": warehouse, "account": account, "agm": agm, "lfp": lfp,
            "order": read_order(order["id"]), "order_at_submit": order, "gold": gold}


def test_attaching_a_second_contract_supersedes_the_first_and_replaces_the_fee():
    """PRD §3.8: "Any other contract already sitting on that same order in
    `ATTACHED` or `ACTIVE` moves to `SUPERSEDED`; the order's
    `service_contract_fee_cents` is **set to** the new contract's
    `prepay_total_cents`, replacing rather than adding to the superseded
    contract's contribution, so an order never carries two coverage fees at
    once."
    PRD §3.8: "The order's `total_cents` is then re-derived — re-running only
    the final assembly step, reusing the waiver decision made at submission
    verbatim and leaving `hazmat_fee_cents` untouched — and the account's
    `open_receivable_cents` is adjusted by the difference between the new order
    total and the previous one."
    PRD §3.8: "The `monthly_fee_cents` is then whichever is larger, that rounded
    figure or the tier floor — 2500 cents for `BRONZE`, 4900 cents for `SILVER`
    and 9900 cents for `GOLD`."

    Design: Corner/state_machines/contract_attach_supersedes_the_prior_contract_on_the_same_order
    """
    from test_helpers import attach_service_contract, read_order, read_account
    ctx = _order_with_a_gold_contract_attached()
    assert ctx["order_at_submit"]["total_cents"] == 118080
    assert ctx["gold"]["prepay_total_cents"] == 118800
    assert ctx["order"]["total_cents"] == 236880

    bronze = create_service_contract(ctx["account"]["id"], coverage_tier="BRONZE")
    bronze = size_service_contract(bronze["id"])
    assert bronze["monthly_fee_cents"] == 2500, \
        f"The BRONZE floor lifts the fee to 2500, got {bronze['monthly_fee_cents']}"
    assert bronze["prepay_total_cents"] == 30000

    attached = attach_service_contract(bronze["id"], ctx["order"]["id"],
                                       ctx["order"]["version"])
    assert attached["status"] == "ATTACHED"
    assert read_service_contract(ctx["gold"]["id"])["status"] == "SUPERSEDED"

    order = read_order(ctx["order"]["id"])
    assert order["service_contract_fee_cents"] == 30000
    assert order["total_cents"] == 148080
    assert read_account(ctx["account"]["id"])["open_receivable_cents"] == 148080


def test_an_attached_contract_activates_when_its_order_is_delivered():
    """PRD §3.8: "When that order reaches `DELIVERED`, an `ATTACHED` contract
    moves to `ACTIVE` and coverage begins, with no ledger movement."
    PRD §3.8: "On success the platform writes the contract's `order_id` and
    stamps `attached_at` from the logical clock, and moves the contract `SIZED →
    ATTACHED`."

    Design: Corner/state_machines/attached_contract_becomes_active_when_its_order_is_delivered
    """
    from test_helpers import (create_warehouse, create_carrier, receive_lot, create_order,
                              add_line, submit_order, allocate_order, pack_shipment,
                              certify_shipment, dispatch_shipment, deliver_shipment,
                              attach_service_contract, set_clock, read_order)
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    carrier = create_carrier()
    account = create_account(name="Metro Data Halls", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=3)
    agm = create_battery_model("IB-AGM-95")
    create_battery_model("IB-LFP-100")
    receive_lot(agm["id"], warehouse["id"], manufactured_on="2026-06-01",
                quantity_on_hand=30)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-05")
    add_line(order["id"], agm["id"], 2, core_expected_count=0)
    order = submit_order(order["id"])

    contract = create_service_contract(account["id"], coverage_tier="GOLD")
    contract = size_service_contract(contract["id"])
    assert contract["prepay_total_cents"] == 118800
    attached = attach_service_contract(contract["id"], order["id"], order["version"])
    assert attached["status"] == "ATTACHED"

    allocate_order(order["id"])
    shipment = pack_shipment(order["id"], carrier["id"])
    certify_shipment(shipment["id"], "APPROVE")
    set_clock("2026-08-05T09:00:00Z")
    dispatch_shipment(shipment["id"])
    deliver_shipment(shipment["id"])

    covered = read_service_contract(contract["id"])
    assert covered["status"] == "ACTIVE", "Coverage begins by cascade, not by a call"
    assert covered["order_id"] == order["id"]

    delivered = read_order(order["id"])
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["service_contract_fee_cents"] == 118800
    assert delivered["total_cents"] == 179753


def test_monthly_fee_uses_the_computed_product_when_it_clears_the_floor():
    """PRD §3.8: "The raw monthly figure is the covered value multiplied by the
    coverage rate for the tier — 0.0075 for `BRONZE`, 0.0125 for `SILVER` and
    0.0200 for `GOLD` — multiplied by a chemistry service multiplier reflecting
    how much attention that chemistry needs in the field: 1.30 for
    `FLOODED_LEAD_ACID`, 1.10 for `AGM`, 1.15 for `GEL`, 0.90 for
    `LITHIUM_IRON_PHOSPHATE` and 1.25 for `NICKEL_CADMIUM`. Both multipliers are
    applied to the unrounded product and the result is rounded half up to whole
    cents exactly once, at the very end."
    PRD §3.8: "The usable capacity of one unit is the model's
    `amp_hour_capacity` multiplied by the depth-of-discharge limit for its
    chemistry — 0.50 for `FLOODED_LEAD_ACID`, 0.60 for `AGM`, 0.60 for `GEL`,
    0.90 for `LITHIUM_IRON_PHOSPHATE` and 0.70 for `NICKEL_CADMIUM` —
    multiplied by the temperature derate factor, rounded half up to three
    decimals."

    Design: Corner/calculations/service_fee_uses_the_product_when_it_clears_the_tier_floor
    """
    account = create_account(name="Metro Data Halls", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=3)
    create_battery_model("IB-AGM-95")
    contract = create_service_contract(
        account["id"], coverage_tier="GOLD", load_watts=12000,
        required_runtime_minutes=240, system_voltage=48, ambient_temp_c=25.0,
        allowed_chemistries=["AGM"],
    )

    sized = size_service_contract(contract["id"])
    assert sized["dc_load_amps"] == pytest.approx(277.778, abs=0.0005)
    assert sized["temp_derate_factor"] == pytest.approx(1.0, abs=1e-9)
    assert sized["required_peukert_ah"] == pytest.approx(1276.333, abs=0.0005)
    assert sized["sized_units_per_string"] == 4
    assert sized["sized_string_count"] == 23
    assert sized["sized_unit_count"] == 92
    assert sized["covered_value_cents"] == 2392000
    assert sized["monthly_fee_cents"] == 52624, \
        f"The product clears the GOLD floor, got {sized['monthly_fee_cents']}"
    assert sized["prepay_total_cents"] == 631488


def test_attaching_a_contract_to_another_accounts_order_is_refused(api):
    """PRD §3.8: "Three preconditions apply beyond the version check: the
    contract must stand in `SIZED`; the order's `account_id` must equal the
    contract's `account_id`, with a mismatch refused as `ERR_ACCOUNT_MISMATCH`;
    and the order's `fulfillment_status` must be `SUBMITTED` or `ALLOCATED`, so
    a contract cannot be hung on a draft, a shipped order or a cancelled one."

    Design: Corner/validations/contract_attach_to_another_accounts_order_is_refused
    """
    from test_helpers import (validate_error, ApiErrorId, create_warehouse, create_order,
                              add_line, submit_order, read_order)
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account_a = create_account(name="Account A", account_tier="STANDARD", state_code="TX",
                               credit_limit_cents=100000000, storm_priority_rank=5)
    account_b = create_account(name="Account B", account_tier="STANDARD", state_code="TX",
                               credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model("IB-AGM-95")

    order = create_order(account_a["id"], warehouse["id"], requested_ship_date="2026-08-11")
    add_line(order["id"], model["id"], 4, core_expected_count=0)
    order = submit_order(order["id"])
    assert order["total_cents"] == 118080

    contract = create_service_contract(account_b["id"], coverage_tier="GOLD",
                                       allowed_chemistries=["AGM"])
    contract = size_service_contract(contract["id"])
    assert contract["prepay_total_cents"] == 118800

    resp = api.attach_service_contract(contract["id"], {
        "order_id": order["id"], "expected_order_version": order["version"],
    }, REP)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_MISMATCH.value)

    stored = read_service_contract(contract["id"])
    assert stored["status"] == "SIZED"
    assert stored["order_id"] is None
    unchanged = read_order(order["id"])
    assert unchanged["service_contract_fee_cents"] == 0
    assert unchanged["total_cents"] == 118080


def test_sizing_with_no_eligible_chemistry_is_refused(api):
    """PRD §3.8: "A catalog model is a candidate only when all three of these
    hold: the model's `status` is `ACTIVE`; the model's `chemistry` is a member
    of the contract's `allowed_chemistries`; and the model's `nominal_voltage`
    is no greater than the contract's `system_voltage`. When no model qualifies,
    the request is refused with `ERR_NO_ELIGIBLE_BATTERY_MODEL` (HTTP 422) and
    nothing is written."
    PRD §3.8: "A new contract opens with `status` at `DRAFT` and every sized
    field at zero or null."

    Design: Corner/validations/size_contract_with_no_eligible_chemistry_returns_no_eligible_model
    """
    from test_helpers import validate_error, ApiErrorId
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    create_battery_model("IB-AGM-95")
    contract = create_service_contract(account["id"], coverage_tier="SILVER",
                                       allowed_chemistries=["GEL"])

    resp = api.size_service_contract(contract["id"], REP)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BATTERY_MODEL.value)

    stored = read_service_contract(contract["id"])
    assert stored["status"] == "DRAFT"
    assert stored["sized_battery_model_id"] is None
    assert stored["sized_unit_count"] == 0
    assert stored["monthly_fee_cents"] == 0


def test_cancelling_the_order_cancels_its_attached_contract():
    """PRD §3.8: "When that order is cancelled, a contract standing in
    `ATTACHED` or `ACTIVE` moves to `CANCELLED` and coverage ends."
    PRD §3.3: "From `SUBMITTED`, the account's `open_receivable_cents` is
    reduced by the order's `total_cents`, and any service contract attached to
    that order standing in `ATTACHED` or `ACTIVE` moves to `CANCELLED`."

    Design: Corner/state_machines/order_cancel_cancels_the_attached_service_contract
    """
    from test_helpers import cancel_order, read_order, read_account
    ctx = _order_with_a_gold_contract_attached()
    assert ctx["gold"]["prepay_total_cents"] == 118800
    assert read_service_contract(ctx["gold"]["id"])["status"] == "ATTACHED"
    assert ctx["order"]["total_cents"] == 236880

    cancelled = cancel_order(ctx["order"]["id"],
                             "Budget freeze; the whole standby project is on hold.")
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["credit_status"] == "CLOSED"

    contract = read_service_contract(ctx["gold"]["id"])
    assert contract["status"] == "CANCELLED"
    assert contract["order_id"] == ctx["order"]["id"]

    assert read_account(ctx["account"]["id"])["open_receivable_cents"] == 0
    assert read_order(ctx["order"]["id"])["total_cents"] == 236880
