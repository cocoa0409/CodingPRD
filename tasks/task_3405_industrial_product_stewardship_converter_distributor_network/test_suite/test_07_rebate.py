"""Rebate programs and accrual settlement (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    advance_rebate_program,
    build_user_headers,
    create_active_rebate_program,
    create_agreement,
    create_converter,
    create_distributor,
    create_rebate_program,
    get_accrual,
    get_accrual_for_program,
    get_order,
    make_converter_headers,
    make_distributor_headers,
    place_order,
    rebate_program_payload,
    set_clock,
    setup_active_formulation,
    setup_rebate_flagged_scenario,
    ship_order,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = TEST_USERS["channel_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


def test_program_activation_creates_zero_provisional_accrual(api):
    """PRD §3.7: "Activation spawns the program's single **rebate accrual** for
    the designated partner: the accrual references its program through
    `program_id`, carries the partner in `converter_id` or `distributor_id`
    according to `partner_type`, and starts `PROVISIONAL` with
    `provisional_amount_cents` 0, `excluded_order_count` 0, and
    `final_amount_cents` null."

    Design: Corner/state_machines/program_activation_creates_zero_provisional_accrual
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    prog = create_rebate_program(ctx["formulation"]["id"], partner_type="DISTRIBUTOR",
                                 distributor_id=dist["id"])
    advance_rebate_program(prog["id"])
    assert get_accrual_for_program(prog["id"]) is not None
    rows, meta = validate_paginated(
        api.list_rebate_accruals(FC, params={"program_id": prog["id"]})
    )
    assert meta["total_count"] == 1 and len(rows) == 1
    acc = rows[0]
    assert acc["distributor_id"] == dist["id"]
    assert acc["status"] == "PROVISIONAL"
    assert acc["provisional_amount_cents"] == 0
    assert acc["excluded_order_count"] == 0
    assert acc["final_amount_cents"] is None
    program = validate_success(api.get_rebate_program(prog["id"], FC), 200)
    assert program["status"] == "ACTIVE"


def test_claim_provisional_accrual_rejected(api):
    """PRD §3.7: "a claim attempted on an accrual in any other status is rejected
    with the dedicated `ERR_ACCRUAL_NOT_FINALIZED` (409), which sits at the same
    precedence tier as the generic state error."

    Design: Corner/state_machines/claim_provisional_accrual_rejected
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    prog, acc = create_active_rebate_program(ctx["formulation"]["id"],
                                             distributor_id=dist["id"])
    resp = api.claim_accrual(acc["id"], make_distributor_headers(dist["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCRUAL_NOT_FINALIZED)
    assert get_accrual(acc["id"])["status"] == "PROVISIONAL"


def test_program_close_before_period_end_rejected(api):
    """PRD §3.7: "Closing an `ACTIVE` program requires the logical clock to have
    reached `period_end`; at that moment the accrual's `final_amount_cents` is
    computed over the final input set and the accrual moves to `FINALIZED`."

    Design: Corner/validations/program_close_before_period_end_rejected
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    prog, acc = create_active_rebate_program(ctx["formulation"]["id"],
                                             distributor_id=dist["id"])
    set_clock("2026-12-15T00:00:00Z")
    early = api.advance_rebate_program(prog["id"], FC)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)
    program = validate_success(api.get_rebate_program(prog["id"], FC), 200)
    assert program["status"] == "ACTIVE"
    set_clock("2027-01-01T00:00:00Z")
    closed = validate_success(api.advance_rebate_program(prog["id"], FC), 200)
    assert closed["status"] == "CLOSED", "clock at exactly period_end closes the program"


def test_rebate_program_partner_type_mismatch_rejected(api):
    """PRD §3.7: "exactly one partner id — `converter_id` or `distributor_id`,
    consistent with `partner_type`, with ambiguity rejected as
    `ERR_BUYER_AMBIGUOUS`."

    Design: Corner/validations/rebate_program_partner_type_mismatch_rejected
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    resp = api.create_rebate_program(
        rebate_program_payload(ctx["formulation"]["id"], partner_type="CONVERTER",
                               distributor_id=dist["id"]),
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_BUYER_AMBIGUOUS)


def _setup_claimed_accrual(api):
    """Program ACTIVATED then CLOSED at period end; accrual FINALIZED and
    CLAIMED by the distributor partner."""
    ctx = setup_active_formulation()
    dist = create_distributor()
    prog, acc = create_active_rebate_program(ctx["formulation"]["id"],
                                             distributor_id=dist["id"])
    set_clock("2027-01-01T00:00:00Z")
    advance_rebate_program(prog["id"])
    acc = get_accrual(acc["id"])
    assert acc["status"] == "FINALIZED"
    return ctx, dist, prog, acc


def test_channel_manager_cannot_pay_accrual(api):
    """PRD §2.1: "a request whose `X-User-Role` is not admitted by the endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: pay is a
    FinanceController operation.

    Design: Corner/rbac/channel_manager_cannot_pay_accrual
    """
    ctx, dist, prog, acc = _setup_claimed_accrual(api)
    claimed = validate_success(
        api.claim_accrual(acc["id"], make_distributor_headers(dist["id"])), 200
    )
    assert claimed["status"] == "CLAIMED"
    resp = api.pay_accrual(acc["id"], CM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_accrual(acc["id"])["status"] == "CLAIMED"


def test_converter_cannot_claim_distributor_accrual(api):
    """PRD §2.1: "An entity-backed actor who attempts to place, advance, or
    cancel an order — or claim a rebate accrual — belonging to a different
    partner is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/converter_cannot_claim_distributor_accrual
    """
    ctx, dist, prog, acc = _setup_claimed_accrual(api)
    conv2 = create_converter(name="Other Converter BV")
    resp = api.claim_accrual(acc["id"], make_converter_headers(conv2["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
    assert get_accrual(acc["id"])["status"] == "FINALIZED"


def test_sod_program_creator_cannot_activate_program(api):
    """PRD §3.7: "Activating a `DRAFT` program requires the activating user's
    `X-User-ID` to differ from the program's `created_by` — the
    segregation-of-duties guard, else `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/rbac/sod_program_creator_cannot_activate_program
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    prog = create_rebate_program(ctx["formulation"]["id"], partner_type="DISTRIBUTOR",
                                 distributor_id=dist["id"], creator="cm-7")
    resp = api.advance_rebate_program(
        prog["id"], build_user_headers("cm-7", "FinanceController")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    program = validate_success(api.get_rebate_program(prog["id"], FC), 200)
    assert program["status"] == "DRAFT"
    ok = api.advance_rebate_program(prog["id"], build_user_headers("fc-1", "FinanceController"))
    assert validate_success(ok, 200)["status"] == "ACTIVE"


def test_rebate_provisional_counts_flagged_shipped_orders(api):
    """PRD §3.7: "The input set for the provisional figure is the partner's
    orders on the program's formulation whose fulfillment stands `SHIPPED` and
    whose `shipped_at` falls inside the accrual window — regardless of whether
    the order is compliance-flagged" and "every subsequent flag or unflag event
    on a matching order recomputes both `provisional_amount_cents` and
    `excluded_order_count` — the latter counting the partner's `SHIPPED` orders
    inside the period whose compliance stands `FLAGGED`."

    Design: Difficulty/dual_variant_calc/rebate_provisional_includes_flagged_vs_final_rebaselines
    """
    ctx = setup_rebate_flagged_scenario()
    o1, o2 = ctx["order1"], ctx["order2"]
    assert o1["line_total_cents"] == 2500000
    assert o2["line_total_cents"] == 1000000
    o1_after = get_order(o1["id"])
    o2_after = get_order(o2["id"])
    assert (o1_after["fulfillment_status"], o1_after["compliance_status"]) == ("SHIPPED", "FLAGGED")
    assert (o2_after["fulfillment_status"], o2_after["compliance_status"]) == ("SHIPPED", "CLEAR")
    acc = get_accrual(ctx["accrual"]["id"])
    assert acc["provisional_amount_cents"] == 70000, (
        "provisional variant still counts the FLAGGED shipped order: "
        "O1 40000 = 100x10000x0.01 + 150x10000x0.02; "
        "O2 30000 = 50x10000x0.02 + 50x10000x0.04"
    )
    assert acc["excluded_order_count"] == 1
    assert acc["status"] == "PROVISIONAL"


def test_rebate_final_excludes_flagged_and_rebaselines(api):
    """PRD §3.7: "the final figure uses the same set but additionally excludes
    orders whose `compliance_status` is `FLAGGED` at close time." and "because
    the final computation re-baselines the cumulative quantity over the reduced,
    clear-only set, surviving orders can fall into **lower** brackets than they
    occupied provisionally".

    Design: Difficulty/dual_variant_calc/rebate_provisional_includes_flagged_vs_final_rebaselines
    """
    ctx = setup_rebate_flagged_scenario()
    acc_id = ctx["accrual"]["id"]
    provisional = get_accrual(acc_id)["provisional_amount_cents"]
    assert provisional == 70000
    set_clock("2027-01-02T00:00:00Z")
    advance_rebate_program(ctx["program"]["id"])
    acc = get_accrual(acc_id)
    assert acc["status"] == "FINALIZED"
    assert acc["final_amount_cents"] == 10000, (
        "final variant drops the flagged O1 and re-baselines O2 into the "
        "[0,100) bracket: 100 x 10000 x 0.01"
    )
    assert acc["final_amount_cents"] != acc["provisional_amount_cents"]


def test_rebate_rounding_single_order_portion_rounds_half_up(api):
    """PRD §3.7: "Rounding is pinned: each order's per-tier portion is rounded
    to cents **first**, and only then summed — raw fractional cents are never
    carried across orders and rounded once at the end."

    Design: Difficulty/combinatorial_formula/rebate_rounding_per_order_per_tier_then_sum
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=1,
                          effective_from="2026-10-01T00:00:00Z",
                          effective_to="2027-01-01T00:00:00Z")
    prog, acc = create_active_rebate_program(
        ctx["formulation"]["id"], distributor_id=dist["id"],
        rebate_tiers=[{"threshold_qty": 0, "rate_pct": 0.01}],
        budget_cap_cents=100000000)
    order = place_order(ag["id"], 33333, distributor_id=dist["id"],
                        requested_ship_date="2026-11-01T00:00:00Z")
    assert order["line_total_cents"] == 33333
    ship_order(order["id"], distributor_id=dist["id"])
    acc = get_accrual(acc["id"])
    assert acc["provisional_amount_cents"] == 333, "33333 x 1 x 0.01 = 333.33 rounds half-up to 333"
    assert acc["status"] == "PROVISIONAL"


def test_rebate_rounding_sums_per_order_portions_not_raw(api):
    """PRD §3.7: "each non-empty portion earns the portion size times the
    order's frozen `unit_price_cents` times that tier's `rate_pct`, rounded
    half-up to whole cents, and the order's accrual is the sum of its per-tier
    portions before the running total advances by the order's `quantity`."
    "Rounding is pinned: each order's per-tier portion is rounded to cents
    **first**, and only then summed — raw fractional cents are never carried
    across orders and rounded once at the end."

    Design: Difficulty/combinatorial_formula/rebate_rounding_per_order_per_tier_then_sum
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=1,
                          effective_from="2026-10-01T00:00:00Z",
                          effective_to="2027-01-01T00:00:00Z")
    prog, acc = create_active_rebate_program(
        ctx["formulation"]["id"], distributor_id=dist["id"],
        rebate_tiers=[{"threshold_qty": 0, "rate_pct": 0.01}],
        budget_cap_cents=100000000)
    for day in ("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z"):
        order = place_order(ag["id"], 33333, distributor_id=dist["id"],
                            requested_ship_date=day)
        ship_order(order["id"], distributor_id=dist["id"])
    acc = get_accrual(acc["id"])
    assert acc["provisional_amount_cents"] == 999, (
        "333 per order summed; the unpinned round-once alternative would give 1000"
    )
