"""Towing compatibility gates, damage claim lifecycle, protection plans, and
agreement settlement mechanics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_confirmed_reservation,
    create_quoted_reservation,
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


# ---------------------------------------------------------------------------
# Towing compatibility boundary
# ---------------------------------------------------------------------------

def _setup_tow_scenario(vehicle_pass_kwargs, vehicle_fail_kwargs):
    """Two customers, two TOW_DOLLY reservations, identical except tow vehicle."""
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a, equipment_type="TOW_DOLLY", code_prefix="U-T1")
    setup_unit(dealer_a, equipment_type="TOW_DOLLY", code_prefix="U-T2")
    setup_active_rate(loc_a, loc_b, equipment_type="TOW_DOLLY", base_rate_cents=2000)
    cust_pass, _ = setup_customer(
        verify_dealer=dealer_a, email_prefix="tow-pass", **vehicle_pass_kwargs)
    cust_fail, _ = setup_customer(
        verify_dealer=dealer_a, email_prefix="tow-fail", **vehicle_fail_kwargs)
    rsv_pass = create_quoted_reservation(
        cust_pass, dealer_a, loc_b, equipment_type="TOW_DOLLY")
    rsv_fail = create_quoted_reservation(
        cust_fail, dealer_a, loc_b, equipment_type="TOW_DOLLY")
    return cust_pass, cust_fail, rsv_pass, rsv_fail


def test_tow_capacity_exactly_at_80_percent_boundary_passes():
    """PRD §3.4: "Gate two, tow capacity: the vehicle's `tow_capacity_lbs` must
    be at least the equipment's gross vehicle weight rating multiplied by 0.8."

    Design: Difficulty/boundary_precision_check/tow_capacity_exactly_at_80_percent_boundary
    """
    # TOW_DOLLY GVWR 3450 * 0.8 = 2760 exactly: 2760 passes (>= semantics).
    cust_pass, cust_fail, rsv_pass, rsv_fail = _setup_tow_scenario(
        dict(curb_weight_lbs=3000, tow_capacity_lbs=2760, hitch_class="CLASS_II"),
        dict(curb_weight_lbs=3000, tow_capacity_lbs=2759, hitch_class="CLASS_II"),
    )
    confirmed = validate_success(api_client.confirm_reservation(
        rsv_pass["id"], {"expected_reservation_version": rsv_pass["version"]},
        make_customer_headers(cust_pass["id"])))
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["tow_check_result"] == "PASS"
    resp = api_client.confirm_reservation(
        rsv_fail["id"], {"expected_reservation_version": rsv_fail["version"]},
        make_customer_headers(cust_fail["id"]))
    validate_error(resp, ApiErrorId.ERR_TOW_INCOMPATIBLE, expected_status=422)


def test_tow_capacity_one_pound_below_boundary_fails():
    """PRD §3.4: "Gate two, tow capacity: the vehicle's `tow_capacity_lbs` must
    be at least the equipment's gross vehicle weight rating multiplied by 0.8."
    PRD §3.4: "Passing all three gates records `PASS`; failing any gate records
    `FAIL` and the confirm is rejected with `ERR_TOW_INCOMPATIBLE`."

    Design: Difficulty/boundary_precision_check/tow_capacity_exactly_at_80_percent_boundary
    """
    cust_pass, cust_fail, rsv_pass, rsv_fail = _setup_tow_scenario(
        dict(curb_weight_lbs=3000, tow_capacity_lbs=2760, hitch_class="CLASS_II"),
        dict(curb_weight_lbs=3000, tow_capacity_lbs=2759, hitch_class="CLASS_II"),
    )
    resp = api_client.confirm_reservation(
        rsv_fail["id"], {"expected_reservation_version": rsv_fail["version"]},
        make_customer_headers(cust_fail["id"]))
    validate_error(resp, ApiErrorId.ERR_TOW_INCOMPATIBLE, expected_status=422)
    # The failed reservation is unchanged.
    after = validate_success(api_client.get_reservation(
        rsv_fail["id"], TEST_USERS["admin"]))
    assert after["status"] == "QUOTED"


def test_state_precondition_beats_business_safety_tow_check():
    """PRD §2.8: "The ordering matters: on a reservation confirm, for instance,
    a towing failure surfaces as `ERR_TOW_INCOMPATIBLE` rather than being masked
    by a later license or availability check, and a state-layer rejection (not
    `QUOTED`, or a stale `expected_reservation_version`) always precedes every
    one of the domain checks."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_safety_tow_check
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a, equipment_type="TRAILER_6X12")
    setup_active_rate(loc_a, loc_b, equipment_type="TRAILER_6X12",
                      base_rate_cents=3000)
    # Under-classed vehicle: hitch CLASS_I fails the TRAILER_6X12 hitch gate,
    # tow_capacity 3000 < 4400*0.8 = 3520 would fail the capacity gate too.
    customer, _ = setup_customer(
        verify_dealer=dealer_a, email_prefix="c9",
        curb_weight_lbs=3000, tow_capacity_lbs=3000, hitch_class="CLASS_I")
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b, equipment_type="TRAILER_6X12",
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    validate_success(api_client.cancel_reservation(
        rsv["id"], make_customer_headers(customer["id"])))
    # The CANCELLED state must mask the tow failure: state layer precedes it.
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_state_precondition_beats_tow_check_on_expired_reservation():
    """PRD §2.8: "The ordering matters: on a reservation confirm, for instance,
    a towing failure surfaces as `ERR_TOW_INCOMPATIBLE` rather than being masked
    by a later license or availability check, and a state-layer rejection (not
    `QUOTED`, or a stale `expected_reservation_version`) always precedes every
    one of the domain checks."
    PRD §2.9: "A `Reservation` is `QUOTED`, `CONFIRMED`, `REASSIGNED`,
    `FULFILLED`, `CANCELLED`, `EXPIRED`, or `NO_SHOW` (the last four terminal)."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_safety_tow_check
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a, equipment_type="TRAILER_6X12")
    setup_active_rate(loc_a, loc_b, equipment_type="TRAILER_6X12",
                      base_rate_cents=3000)
    customer, _ = setup_customer(
        verify_dealer=dealer_a, email_prefix="c9b",
        curb_weight_lbs=3000, tow_capacity_lbs=3000, hitch_class="CLASS_I")
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b, equipment_type="TRAILER_6X12",
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    validate_success(api_client.expire_reservation(rsv["id"], TEST_USERS["admin"]))
    # EXPIRED is terminal; the tow failure must stay masked by the state layer.
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api_client.get_reservation(rsv["id"], TEST_USERS["admin"]))
    assert after["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Claims, plans, agreement settlement
# ---------------------------------------------------------------------------

def test_damage_claim_deny_reopen_approve_cycle():
    """PRD §3.8: "A denied claim is not necessarily dead: while its agreement
    remains unsettled, reopening moves it `DENIED → FILED`, and the appeal loop
    of filing, adjudication, and reopening may repeat until the agreement
    settles, which seals the loop."
    PRD §3.8: "Approval sets `approved_amount_cents` to the lesser of the
    claimed amount and the coverage cap of the agreement's active plan tier —
    with a cap of zero when the agreement has no active plan at all — then runs
    the agreement's damage reconciliation: `damage_charge_cents` becomes the
    sum of `approved_amount_cents` over every claim on the agreement in
    `APPROVED` or `PAID` status, and the agreement's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/damage_claim_deny_reopen_approve_cycle
    """
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z",
        with_dest_dealer=True)
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["agreement"]
    plan = validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "STANDARD"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    # The deny/reopen/approve loop runs while the agreement is ACTIVE — still
    # unsettled, and the plan is still ACTIVE so its tier cap governs the
    # approved amount (PRD §3.7: a plan expires automatically at return, after
    # which the cap would be zero).
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 500000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    # FILED -> DENIED -> FILED -> APPROVED while the agreement is unsettled.
    denied = validate_success(api_client.deny_damage_claim(
        claim["id"], {"resolution_note": "not our damage"},
        make_dealer_agent_headers(dealer_b["id"])))
    assert denied["status"] == "DENIED"
    reopened = validate_success(api_client.reopen_damage_claim(
        claim["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert reopened["status"] == "FILED"
    approved = validate_success(api_client.approve_damage_claim(
        claim["id"], {"resolution_note": "upheld on appeal"},
        make_dealer_agent_headers(dealer_b["id"])))
    assert approved["status"] == "APPROVED"
    # 500000 is below the STANDARD cap 750000.
    assert approved["approved_amount_cents"] == 500000
    agr_after = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    assert agr_after["damage_charge_cents"] == 500000


def test_damage_claim_cycle_preserves_claim_identity():
    """PRD §3.8: "A denied claim is not necessarily dead: while its agreement
    remains unsettled, reopening moves it `DENIED → FILED`, and the appeal loop
    of filing, adjudication, and reopening may repeat until the agreement
    settles, which seals the loop."
    PRD §3.8: "Either decision may carry an optional free-text
    `resolution_note`."

    Design: Difficulty/non_linear_state_machine/damage_claim_deny_reopen_approve_cycle
    """
    scenario = setup_agreement(with_dest_dealer=True)
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["agreement"]
    validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "STANDARD"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    validate_success(api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 500000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    denied = validate_success(api_client.deny_damage_claim(
        claim["id"], {"resolution_note": "first pass denied"},
        make_dealer_agent_headers(dealer_b["id"])))
    assert denied["resolution_note"] == "first pass denied"
    validate_success(api_client.reopen_damage_claim(
        claim["id"], make_dealer_agent_headers(dealer_a["id"])))
    # Second denial round: still the same claim row, new note.
    denied2 = validate_success(api_client.deny_damage_claim(
        claim["id"], {"resolution_note": "denied again"},
        make_dealer_agent_headers(dealer_b["id"])))
    assert denied2["id"] == claim["id"]
    assert denied2["status"] == "DENIED"
    validate_success(api_client.reopen_damage_claim(
        claim["id"], make_dealer_agent_headers(dealer_a["id"])))
    approved = validate_success(api_client.approve_damage_claim(
        claim["id"], {"resolution_note": "finally approved"},
        make_dealer_agent_headers(dealer_b["id"])))
    assert approved["id"] == claim["id"]
    assert approved["status"] == "APPROVED"
    assert approved["claimed_amount_cents"] == 500000


def test_claim_amount_capped_by_plan_tier():
    """PRD §3.8: "Approval sets `approved_amount_cents` to the lesser of the
    claimed amount and the coverage cap of the agreement's active plan tier —
    with a cap of zero when the agreement has no active plan at all — then runs
    the agreement's damage reconciliation: `damage_charge_cents` becomes the
    sum of `approved_amount_cents` over every claim on the agreement in
    `APPROVED` or `PAID` status, and the agreement's `version` increments by 1."
    PRD §3.7: "The tiers carry coverage caps that the claims workflow consults:
    200000 cents for `BASIC`, 750000 for `STANDARD`, and 2500000 for `PREMIUM`."

    Design: Corner/calculations/claim_amount_capped_by_plan_tier
    """
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z",
        with_dest_dealer=True)
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["agreement"]
    plan = validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "BASIC"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    # BASIC 2-day premium: 2 * 1400 = 2800.
    assert plan["premium_cents"] == 2800
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 900000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    approved = validate_success(api_client.approve_damage_claim(
        claim["id"], {}, make_dealer_agent_headers(dealer_b["id"])))
    assert approved["status"] == "APPROVED"
    # min(claimed 900000, BASIC cap 200000) = 200000.
    assert approved["approved_amount_cents"] == 200000


def test_protection_premium_long_rental_discount():
    """PRD §3.7: "The premium is the tier's daily price — 1400 cents per day
    for `BASIC`, 2400 for `STANDARD`, 3900 for `PREMIUM` — multiplied by the
    reservation's frozen `rental_days`; when the rental runs at least 7 days,
    the whole premium (not the per-day amount) is discounted by 15 percent and
    rounded half-up to integer cents, and the result is stored as
    `premium_cents`."

    Design: Corner/calculations/protection_premium_long_rental_discount
    """
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-18T10:00:00Z")
    dealer_a = scenario["dealer_a"]
    agreement = scenario["agreement"]
    plan = validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "PREMIUM"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    # round_half_up(8 * 3900 * 0.85) = round_half_up(26520.0) = 26520.
    assert plan["premium_cents"] == 26520


def test_claim_amount_zero_rejected():
    """PRD §3.8: "Damage claims may be filed against an agreement by a
    `DealerAgent`, supplying the `agreement_id` and a `claimed_amount_cents`
    strictly greater than zero — a non-positive amount is
    `ERR_INVALID_CLAIM_AMOUNT` (HTTP 422)."

    Design: Corner/validations/claim_amount_zero_rejected
    """
    scenario = setup_agreement()
    dealer_a = scenario["dealer_a"]
    agreement = scenario["agreement"]
    resp = api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 0},
        make_dealer_agent_headers(dealer_a["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_AMOUNT, expected_status=422)


def test_plan_cancel_auto_denies_filed_claims():
    """PRD §3.7: "A plan may be cancelled while its agreement is still
    `ACTIVE` — cancellation moves the plan `ACTIVE → CANCELLED` and, because
    coverage is withdrawn, every claim on the same agreement still `FILED` is
    moved to `DENIED` in the same act."

    Design: Corner/cross_cutting_layers/plan_cancel_auto_denies_filed_claims
    """
    scenario = setup_agreement()
    dealer_a = scenario["dealer_a"]
    agreement = scenario["agreement"]
    plan = validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "BASIC"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 5000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    cancelled = validate_success(api_client.cancel_damage_protection_plan(
        plan["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert cancelled["status"] == "CANCELLED"
    claim_after = validate_success(api_client.get_damage_claim(
        claim["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert claim_after["status"] == "DENIED"


# ---------------------------------------------------------------------------
# Damage-charge reconciliation invariant
# ---------------------------------------------------------------------------

def test_claim_approve_deny_compensation_conserves_damage_charge():
    """PRD §3.8: "Approval sets `approved_amount_cents` to the lesser of the
    claimed amount and the coverage cap of the agreement's active plan tier —
    with a cap of zero when the agreement has no active plan at all — then runs
    the agreement's damage reconciliation: `damage_charge_cents` becomes the
    sum of `approved_amount_cents` over every claim on the agreement in
    `APPROVED` or `PAID` status, and the agreement's `version` increments by 1."
    PRD §3.8: "Sixth, `total_settled_cents` is the base charge plus the late
    fee plus the reconciled damage charges, and it is frozen onto the
    agreement, whose `version` increments as it moves to `SETTLED` — terminal."

    Design: Difficulty/compensating_invariant/claim_approve_plan_cancel_compensation_conserves_damage_charge
    """
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z",
        with_dest_dealer=True)
    dealer_a, dealer_b = scenario["dealer_a"], scenario["dealer_b"]
    agreement = scenario["agreement"]
    # A STANDARD plan (cap 750000) covers CL1; it must be ACTIVE at approval
    # time, so CL1 is approved before the return (PRD §3.7: plans expire at
    # return, after which the cap would be zero).
    validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "STANDARD"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    claim_1 = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 100000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    validate_success(api_client.approve_damage_claim(
        claim_1["id"], {}, make_dealer_agent_headers(dealer_b["id"])))
    validate_success(api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    claim_2 = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 50000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    validate_success(api_client.deny_damage_claim(
        claim_2["id"], {}, make_dealer_agent_headers(dealer_b["id"])))
    # The denial compensates nothing: the ledger sum stays exactly CL1's amount.
    agr_mid = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    assert agr_mid["damage_charge_cents"] == 100000
    settled = validate_success(api_client.settle_rental_agreement(
        agreement["id"], {"expected_agreement_version": agr_mid["version"]},
        make_dealer_agent_headers(dealer_b["id"])))
    assert settled["status"] == "SETTLED"
    # base 2 * 5000 + late 0 + damage 100000 = 110000.
    assert settled["total_settled_cents"] == 110000
    claim_2_after = validate_success(api_client.get_damage_claim(
        claim_2["id"], make_dealer_agent_headers(dealer_b["id"])))
    assert claim_2_after["status"] == "DENIED"


def test_claim_approve_plan_cancel_compensation_conserves_damage_charge():
    """PRD §3.7: "A plan may be cancelled while its agreement is still
    `ACTIVE` — cancellation moves the plan `ACTIVE → CANCELLED` and, because
    coverage is withdrawn, every claim on the same agreement still `FILED` is
    moved to `DENIED` in the same act."
    PRD §3.8: "Approval sets `approved_amount_cents` to the lesser of the
    claimed amount and the coverage cap of the agreement's active plan tier —
    with a cap of zero when the agreement has no active plan at all — then runs
    the agreement's damage reconciliation: `damage_charge_cents` becomes the
    sum of `approved_amount_cents` over every claim on the agreement in
    `APPROVED` or `PAID` status, and the agreement's `version` increments by 1."

    Design: Difficulty/compensating_invariant/claim_approve_plan_cancel_compensation_conserves_damage_charge
    """
    scenario = setup_agreement(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    dealer_a = scenario["dealer_a"]
    agreement = scenario["agreement"]
    plan = validate_success(api_client.create_damage_protection_plan(
        {"agreement_id": agreement["id"], "tier": "STANDARD"},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    claim_1 = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 100000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    claim_2 = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 50000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    # Approve CL1 while the plan is ACTIVE: 100000 under the 750000 cap.
    # A second agent identity approves to satisfy segregation of duties.
    from test_helpers import build_user_headers
    validate_success(api_client.approve_damage_claim(
        claim_1["id"], {}, build_user_headers("agent-second", "DealerAgent")))
    # The compensating plan-cancel auto-denies the still-FILED CL2.
    validate_success(api_client.cancel_damage_protection_plan(
        plan["id"], make_dealer_agent_headers(dealer_a["id"])))
    claim_2_after = validate_success(api_client.get_damage_claim(
        claim_2["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert claim_2_after["status"] == "DENIED"
    # The reconcile sum is exactly CL1's approved amount; CL2 contributes 0.
    agr_after = validate_success(api_client.get_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert agr_after["damage_charge_cents"] == 100000
