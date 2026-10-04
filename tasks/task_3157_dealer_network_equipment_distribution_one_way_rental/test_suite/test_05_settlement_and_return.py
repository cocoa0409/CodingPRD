"""Agreement settlement, return gates, settlement-preview divergence, and the
maintained allocated_unit_count derived field."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_confirmed_reservation,
    make_customer_headers,
    make_dealer_agent_headers,
    setup_active_rate,
    setup_agreement,
    setup_customer,
    setup_dealer,
    setup_returned_agreement,
    setup_two_locations,
    setup_unit,
    validate_error,
    validate_success,
)


def test_settlement_evaluation_order_circular_dependency():
    """PRD §3.8: "Fourth, the late fee: late days are `actual_days` minus the
    reservation's `rental_days`, floored at zero; the per-day late rate is the
    frozen daily rate multiplied by 1.5 and rounded half-up to integer cents,
    and that rounded rate is then multiplied by the late-day count —
    multiplying the count first and the rate second would yield different cents
    and is not the rule."
    PRD §3.8: "Sixth, `total_settled_cents` is the base charge plus the late
    fee plus the reconciled damage charges, and it is frozen onto the
    agreement, whose `version` increments as it moves to `SETTLED` — terminal."

    Design: Difficulty/combinatorial_formula/settlement_evaluation_order_circular_dependency
    """
    # checkout_at is stamped from the logical clock (PRD §3.7), so place the
    # clock at the pickup instant before the agreement is created.
    validate_success(api_client.set_clock("2026-11-10T10:00:00Z", TEST_USERS["admin"]))
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z",
        base_rate_cents=3333, with_dest_dealer=True)
    dealer_b = scenario["dealer_b"]
    agreement = scenario["agreement"]
    # Return 73 hours after checkout: actual_days = ceil(73/24) = 4.
    validate_success(api_client.set_clock("2026-11-13T11:00:00Z", TEST_USERS["admin"]))
    returned = validate_success(api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    assert returned["actual_days"] == 4
    settled = validate_success(api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": returned["version"]},
        make_dealer_agent_headers(dealer_b["id"])))
    # Late: 2 days * round_half_up(3333 * 1.5) = 2 * 5000 = 10000.
    assert settled["late_fee_cents"] == 10000
    # Base 4 * 3333 = 13332 + late 10000 + damage 0 = 23332.
    assert settled["total_settled_cents"] == 23332
    assert settled["status"] == "SETTLED"


def test_settlement_late_fee_rounding_step_order_visible():
    """PRD §3.8: "Fourth, the late fee: late days are `actual_days` minus the
    reservation's `rental_days`, floored at zero; the per-day late rate is the
    frozen daily rate multiplied by 1.5 and rounded half-up to integer cents,
    and that rounded rate is then multiplied by the late-day count —
    multiplying the count first and the rate second would yield different cents
    and is not the rule."

    Design: Difficulty/combinatorial_formula/settlement_evaluation_order_circular_dependency
    """
    # 1 late day at 3333c: per-day-late rounding yields round_half_up(4999.5)
    # = 5000, not floor(4999.5) = 4999 — the step order is observable.
    validate_success(api_client.set_clock("2026-11-10T10:00:00Z", TEST_USERS["admin"]))
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z",
        base_rate_cents=3333, with_dest_dealer=True)
    dealer_b = scenario["dealer_b"]
    agreement = scenario["agreement"]
    validate_success(api_client.set_clock("2026-11-13T10:00:00Z", TEST_USERS["admin"]))
    returned = validate_success(api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    assert returned["actual_days"] == 3
    settled = validate_success(api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": returned["version"]},
        make_dealer_agent_headers(dealer_b["id"])))
    # 1 late day * round_half_up(3333 * 1.5) = 5000.
    assert settled["late_fee_cents"] == 5000
    # Base 3 * 3333 = 9999 + late 5000 + damage 0 = 14999.
    assert settled["total_settled_cents"] == 14999


def test_settle_blocked_by_open_damage_claim_and_location_close_blocked_by_fleet():
    """PRD §3.8: "Two further gates apply in order: the agreement must be
    `RETURNED`, and no claim on it may still be `FILED` — an open claim blocks
    settlement with `ERR_OPEN_CLAIMS` (HTTP 409), while `DENIED` or `PAID`
    claims do not block."
    PRD §3.1: "A `NetworkAdmin` may close a location only while no unit at that
    site is `AVAILABLE`, `HELD`, `OUT`, or `REPOSITIONING`, and while no
    reservation with that site as `origin_location_id` is `QUOTED`,
    `CONFIRMED`, or `REASSIGNED`; violating either condition leaves the
    location untouched."

    Design: Difficulty/cross_entity_state_dependency/settle_blocked_by_open_damage_claim_and_location_close_blocked_by_fleet
    """
    scenario = setup_returned_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    loc_a = scenario["loc_a"]
    agreement = scenario["returned_agreement"]
    # A second AVAILABLE unit keeps the origin location occupied.
    setup_unit(dealer_a, equipment_type="TRAILER_4X8", code_prefix="U-14B")
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 100000},
        make_dealer_agent_headers(dealer_b["id"])), expected_status=201)
    resp = api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": agreement["version"]},
        make_dealer_agent_headers(dealer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS, expected_status=409)
    agr_after = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    assert agr_after["status"] == "RETURNED"
    # The origin location still holds an AVAILABLE unit: close is rejected.
    resp_close = api_client.close_location(loc_a["id"], TEST_USERS["admin"])
    validate_error(resp_close, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    loc_after = validate_success(api_client.get_location(loc_a["id"], TEST_USERS["admin"]))
    assert loc_after["status"] == "OPEN"


def test_settle_unblocked_after_claim_denied():
    """PRD §3.8: "Two further gates apply in order: the agreement must be
    `RETURNED`, and no claim on it may still be `FILED` — an open claim blocks
    settlement with `ERR_OPEN_CLAIMS` (HTTP 409), while `DENIED` or `PAID`
    claims do not block."

    Design: Difficulty/cross_entity_state_dependency/settle_blocked_by_open_damage_claim_and_location_close_blocked_by_fleet
    """
    scenario = setup_returned_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["returned_agreement"]
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 100000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    resp = api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": agreement["version"]},
        make_dealer_agent_headers(dealer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS, expected_status=409)
    # Denying the claim unblocks settle (DENIED claims do not block).
    validate_success(api_client.deny_damage_claim(
        claim["id"], {}, make_dealer_agent_headers(dealer_b["id"])))
    fresh = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    settled = validate_success(api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": fresh["version"]},
        make_dealer_agent_headers(dealer_b["id"])))
    assert settled["status"] == "SETTLED"


def test_err_stale_version_triggerable_on_settle():
    """PRD §2.7: "Settling a rental agreement requires the request to carry
    `expected_agreement_version`, the client's last observed `version` of that
    agreement; if another writer has advanced the agreement's `version` since —
    for example a damage-claim approval that recomputed `damage_charge_cents` —
    the settle is rejected with `ERR_STALE_VERSION` (HTTP 412), so a settle
    carrying a pre-approval version cannot freeze a stale total."

    Design: Corner/errors/err_stale_version_triggerable_on_settle
    """
    # checkout_at/returned_at stamp from the logical clock (PRD §3.7/§3.8);
    # place it at the pickup instant so checkout and return coincide there.
    validate_success(api_client.set_clock("2026-11-10T10:00:00Z", TEST_USERS["admin"]))
    scenario = setup_returned_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["returned_agreement"]
    stale_version = agreement["version"]
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 30000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    # The approval recomputes damage charges and bumps the agreement version.
    validate_success(api_client.approve_damage_claim(
        claim["id"], {}, make_dealer_agent_headers(dealer_b["id"])))
    resp = api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": stale_version},
        make_dealer_agent_headers(dealer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    fresh = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    settled = validate_success(api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": fresh["version"]},
        make_dealer_agent_headers(dealer_b["id"])))
    assert settled["status"] == "SETTLED"
    # The agreement has no active plan at approval (none was ever created), so
    # the coverage cap is zero and the approved amount reconciles to 0
    # (PRD §3.8): base 2 days * 5000 + damage 0 = 10000.
    assert settled["total_settled_cents"] == 10000


def test_settlement_preview_vs_final_divergence():
    """PRD §3.8: "While an agreement is still `ACTIVE`, a provisional estimate
    of this same computation is available for counter conversations: it
    projects `actual_days` as the whole 24-hour periods from `checkout_at` to
    the current logical clock, rounded up and floored at one, excludes damage
    claims entirely since none have been reconciled, and persists nothing —
    the estimate and the final settled figure differ whenever the return
    happens after the estimate was taken or any claim is approved in between."

    Design: Corner/calculations/settlement_preview_vs_final_divergence
    """
    # checkout_at stamps from the logical clock (PRD §3.7); put the clock at
    # the pickup instant so the agreement's checkout coincides with pickup.
    validate_success(api_client.set_clock("2026-11-10T10:00:00Z", TEST_USERS["admin"]))
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z",
        with_dest_dealer=True)
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["agreement"]
    # Preview at checkout + 1 day: projected actual_days 1, but billable days
    # are max(actual_days, rental_days) = max(1, 2) = 2, so the provisional
    # figure is 2 * 5000 = 10000 with damage excluded entirely.
    validate_success(api_client.set_clock("2026-11-11T10:00:00Z", TEST_USERS["admin"]))
    preview = validate_success(api_client.get_settlement_preview(
        agreement["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert preview["total_settled_cents"] == 10000
    # Sell a plan and file a claim before the return; approve while the plan
    # is still ACTIVE so the tier cap applies (PRD §3.7: a plan expires
    # automatically when the agreement is returned).
    validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "STANDARD"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 20000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    validate_success(api_client.approve_damage_claim(
        claim["id"], {}, make_dealer_agent_headers(dealer_b["id"])))
    # Return at checkout + 2 days.
    validate_success(api_client.set_clock("2026-11-12T10:00:00Z", TEST_USERS["admin"]))
    returned = validate_success(api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    assert returned["actual_days"] == 2
    fresh = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    settled = validate_success(api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": fresh["version"]},
        make_dealer_agent_headers(dealer_b["id"])))
    # Final: base 2 * 5000 + damage 20000, no late = 30000.
    assert settled["damage_charge_cents"] == 20000
    assert settled["total_settled_cents"] == 30000
    # The provisional estimate diverged from the frozen final figure.
    assert preview["total_settled_cents"] != settled["total_settled_cents"]


def test_err_location_closed_on_return():
    """PRD §3.8: "Return lands the equipment at `return_location_id` and is the
    moment one-way accumulation physically happens. The agreement must be
    `ACTIVE` and the return location must be `OPEN`."
    PRD §2.8: "location posture (`ERR_LOCATION_CLOSED`, HTTP 409)"

    Design: Corner/errors/err_location_closed_on_return
    """
    scenario = setup_agreement()
    dealer_a = scenario["dealer_a"]
    loc_b = scenario["loc_b"]
    agreement = scenario["agreement"]
    # The destination site holds no units and no live reservations: closable.
    validate_success(api_client.close_location(loc_b["id"], TEST_USERS["admin"]))
    resp = api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_a["id"]))
    validate_error(resp, ApiErrorId.ERR_LOCATION_CLOSED, expected_status=409)
    agr_after = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert agr_after["status"] == "ACTIVE"


def test_err_no_active_dealer_at_location_on_return():
    """PRD §3.8: "The unit moves `OUT → AVAILABLE`, its `current_location_id`
    becomes the return location, and its `current_dealer_id` becomes the
    `ACTIVE` dealer operating at that location — if no active dealer exists
    there, the return cannot complete and fails with
    `ERR_NO_ACTIVE_DEALER_AT_LOCATION` (HTTP 409), because the unit would have
    nowhere to live."

    Design: Corner/errors/err_no_active_dealer_at_location_on_return
    """
    scenario = setup_agreement(with_dest_dealer=True)
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["agreement"]
    # The destination dealer leaves the ACTIVE pool; no other dealer is there.
    validate_success(api_client.suspend_dealer(dealer_b["id"], TEST_USERS["admin"]))
    resp = api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_DEALER_AT_LOCATION,
                   expected_status=409)
    agr_after = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert agr_after["status"] == "ACTIVE"


def test_derived_field_reconciliation_allocated_unit_count():
    """PRD §3.1: "Registering a unit takes a unique `unit_code`, an
    `equipment_type`, and the `dealer_id` of the dealer that will hold it; the
    unit is born `AVAILABLE`, its `current_dealer_id` is the registering
    dealer, its `current_location_id` mirrors that dealer's site, and the
    dealer's `allocated_unit_count` recomputes to count every unit whose
    `current_dealer_id` points at it. That count is a maintained derived field,
    not a stored counter the caller can write: it recomputes whenever a unit is
    registered, handed off at a return or reposition completion, or retired."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_allocated_unit_count
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a, code_prefix="D-L2A")
    dealer_b = setup_dealer(loc_b, code_prefix="D-L2B")
    unit_1 = setup_unit(dealer_a, code_prefix="U-L2-1")
    unit_2 = setup_unit(dealer_a, code_prefix="U-L2-2")
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    dealer_now = validate_success(api_client.get_dealer(
        dealer_a["id"], TEST_USERS["admin"]))
    assert dealer_now["allocated_unit_count"] == 2
    # One-way rental returned at B: the unit is handed off to dealer B.
    rsv = create_confirmed_reservation(customer, dealer_a, loc_b)
    agreement = validate_success(api_client.create_rental_agreement(
        {"reservation_id": rsv["id"], "equipment_unit_id": unit_1["id"],
         "return_location_id": loc_b["id"]},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    validate_success(api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    dealer_a_mid = validate_success(api_client.get_dealer(
        dealer_a["id"], TEST_USERS["admin"]))
    dealer_b_mid = validate_success(api_client.get_dealer(
        dealer_b["id"], TEST_USERS["admin"]))
    assert dealer_a_mid["allocated_unit_count"] == 1
    assert dealer_b_mid["allocated_unit_count"] == 1
    # Retiring the remaining unit at A drops its count to zero.
    validate_success(api_client.retire_equipment_unit(unit_2["id"], TEST_USERS["admin"]))
    dealer_a_end = validate_success(api_client.get_dealer(
        dealer_a["id"], TEST_USERS["admin"]))
    assert dealer_a_end["allocated_unit_count"] == 0
