"""Return authorizations: the pinned five-step credit chain, the inspection fork
and the money and unit conservation invariants around them."""

from test_helpers import (
    ApiErrorId, add_part_line, api_client, approve_rma,
    assert_ledger_balances_stock, assert_ledger_entry,
    assert_return_authorization, assert_return_credit_chain, consume_line,
    create_return_authorization_payload, create_rma, create_work_order,
    inspect_rma, list_ledger, make_dealer_headers, read_dealer, read_part,
    read_part_line, read_return_authorization, receive_rma, set_clock,
    setup_catalogue, setup_consumed_line, setup_received_rma,
    setup_scenario_with_work_order, TEST_USERS, validate_error,
    validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]


def test_rebate_tier_is_keyed_on_the_pre_rebate_net(api):
    """PRD 3.9: "`rebate_pct` is a loyalty tier keyed on `net_before_rebate_cents` —
    five percent when that net is 500000 cents or more, two percent when it is at least
    200000 cents but below 500000, and nothing below that. `loyalty_rebate_cents` is
    `net_before_rebate_cents` multiplied by `rebate_pct`, rounded half up to a whole
    cent, and `final_credit_cents` is `net_before_rebate_cents` plus
    `loyalty_rebate_cents`."
    PRD 3.9: "The circularity in step 5 is only apparent, and the resolution is
    normative: the rebate tier is keyed on the step-4 value and **never** on the final
    credit that the rebate itself produces. Even when adding the rebate pushes
    `final_credit_cents` across a higher tier boundary, the tier is not re-opened."
    PRD 3.9: "`gross_credit_cents` is the pro-rated share of what the dealer was
    actually charged: the line's `charged_amount_cents` multiplied by `qty_returned`,
    divided by the line's `qty_consumed`, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/restocking_rebate_tier_pinned_to_pre_rebate_net
    """
    scenario = setup_consumed_line(
        part_number="CIRC-1", qty=8, stock_units=8, unit_cost_cents=46111,
        lead_time_days=60, weight_kg=1.0, dealer_code="D-GOLD-4",
        model_code="EM-400", serial_prefix="SN-400",
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    assert scenario["line"]["charged_amount_cents"] == 497999
    set_clock("2026-08-06T00:00:00Z")

    rma = validate_success(api.create_return_authorization(
        create_return_authorization_payload(scenario["line"]["id"], 8, "DEFECTIVE"),
        make_dealer_headers(scenario["dealer"]["id"])), 201)
    assert_return_authorization(rma)

    assert rma["age_days"] == 5
    assert rma["gross_credit_cents"] == 497999
    assert rma["fee_pct"] == 0.0
    assert rma["restocking_fee_cents"] == 0
    assert rma["net_before_rebate_cents"] == 497999
    assert rma["rebate_pct"] == 0.02, \
        "the tier is keyed on the pre-rebate net of 497999, not on the final credit"
    assert rma["loyalty_rebate_cents"] == 9960
    assert rma["final_credit_cents"] == 507959
    assert_return_credit_chain(rma)


def test_raising_a_return_moves_no_money_yet(api):
    """PRD 3.9: "None of that money moves yet. A newly raised return has computed
    `age_days`, `gross_credit_cents`, `fee_pct`, `restocking_fee_cents`,
    `net_before_rebate_cents`, `rebate_pct`, `loyalty_rebate_cents` and
    `final_credit_cents`, but no stock has moved, no ledger row exists and
    `credit_posted_cents` remains 0."
    PRD 3.9: "The return's own `part_id` and `dealer_id` are copied from the line and
    its parent work order rather than supplied by the caller, and it starts in `status`
    `REQUESTED` with a `disposition` of null and a `credit_posted_cents` of 0."

    Design: Difficulty/combinatorial_formula/restocking_rebate_tier_pinned_to_pre_rebate_net
    """
    scenario = setup_consumed_line(
        part_number="CIRC-1", qty=8, stock_units=8, unit_cost_cents=46111,
        lead_time_days=60, weight_kg=1.0, dealer_code="D-GOLD-4",
        model_code="EM-400", serial_prefix="SN-400",
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    set_clock("2026-08-06T00:00:00Z")
    before = read_dealer(scenario["dealer"]["id"])

    rma = validate_success(api.create_return_authorization(
        create_return_authorization_payload(scenario["line"]["id"], 8, "DEFECTIVE"),
        make_dealer_headers(scenario["dealer"]["id"])), 201)

    assert rma["status"] == "REQUESTED"
    assert rma["disposition"] is None
    assert rma["credit_posted_cents"] == 0
    assert rma["part_id"] == scenario["part"]["id"]
    assert rma["dealer_id"] == scenario["dealer"]["id"]

    after = read_dealer(scenario["dealer"]["id"])
    assert after["outstanding_balance_cents"] == before["outstanding_balance_cents"]
    assert after["lifetime_restocking_fee_cents"] == 0
    assert after["lifetime_rebate_cents"] == 0
    part = read_part(scenario["part"]["id"])
    assert part["quarantine_units"] == 0
    _, meta = list_ledger(scenario["part"]["id"])
    assert meta["total_count"] == 2, "one RECEIPT and one ISSUE, nothing from the RMA"


def _inspection_fork_scenario():
    """Two consumed lines of 3 and 4 units, each with an approved-and-received
    UNUSED_SURPLUS return raised ten days later."""
    scenario = setup_catalogue(
        part_number="FORK-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=2.0, dealer_code="D-FORK", model_code="EM-600",
        serial_prefix="SN-600", qty_per_unit=1, stock_units=20,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_id = scenario["dealer"]["id"]
    wo = create_work_order(scenario["unit"]["id"], dealer_id,
                           "SCHEDULED_MAINTENANCE", "PLANNED")
    line1 = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], 3)
    line2 = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], 4)
    line1 = consume_line(line1["id"], dealer_id, 3)
    line2 = consume_line(line2["id"], dealer_id, 4)
    assert line1["charged_amount_cents"] == 5399, "setup precondition"
    assert line2["charged_amount_cents"] == 7198, "setup precondition"
    set_clock("2026-08-11T00:00:00Z")
    rma1 = create_rma(line1["id"], dealer_id, 3, "UNUSED_SURPLUS")
    rma2 = create_rma(line2["id"], dealer_id, 4, "UNUSED_SURPLUS")
    for rma in (rma1, rma2):
        approve_rma(rma["id"])
        receive_rma(rma["id"])
    scenario.update({"rma1": rma1, "rma2": rma2})
    return scenario


def test_restock_branch_credits_the_dealer_and_writes_no_ledger_row(api):
    """PRD 3.9: "On the **`RESTOCK`** branch the return's `disposition` is set to
    `RESTOCK` and its `status` becomes `CREDITED`. The part's `quarantine_units` falls
    by `qty_returned` and its `on_hand_units` rises by the same amount; because the
    combined on-hand-plus-quarantine total is unchanged by that move, **no ledger entry
    is appended at all**. The dealer is made whole: `credit_posted_cents` is set to
    `final_credit_cents`, the dealer's `outstanding_balance_cents` is reduced by
    `final_credit_cents`, the dealer's `lifetime_restocking_fee_cents` rises by
    `restocking_fee_cents`, the dealer's `lifetime_rebate_cents` rises by
    `loyalty_rebate_cents`, and the dealer's `credit_hold` is recomputed."
    PRD 3.9: "The base component depends on `return_reason`: fifteen percent for
    `UNUSED_SURPLUS`, and nothing at all for `WRONG_PART`, for `DEFECTIVE` and for
    `CORE_RETURN`."

    Design: Difficulty/non_linear_state_machine/return_fork_restock_credits_versus_scrap_writes_off
    """
    scenario = _inspection_fork_scenario()
    credited = inspect_rma(scenario["rma1"]["id"], "RESTOCK")
    inspect_rma(scenario["rma2"]["id"], "SCRAP")

    assert credited["restocking_fee_cents"] == 810
    assert credited["final_credit_cents"] == 4589
    assert credited["status"] == "CREDITED"
    assert credited["disposition"] == "RESTOCK"
    assert credited["credit_posted_cents"] == 4589

    dealer = read_dealer(scenario["dealer"]["id"])
    assert dealer["outstanding_balance_cents"] == 8008
    assert dealer["lifetime_restocking_fee_cents"] == 810
    assert dealer["lifetime_rebate_cents"] == 0

    part = read_part(scenario["part"]["id"])
    assert part["on_hand_units"] == 16
    assert part["quarantine_units"] == 0


def test_scrap_branch_writes_a_negative_ledger_row_and_withholds_credit(api):
    """PRD 3.9: "On the **`SCRAP`** branch the return's `disposition` is set to `SCRAP`
    and its `status` becomes `SCRAPPED`. The part's `quarantine_units` falls by
    `qty_returned` and its `on_hand_units` is **not** increased; because the combined
    total has genuinely fallen, one ledger entry **is** appended, with `entry_type`
    `SCRAP`, a negative `delta_units` equal to `qty_returned`, and a `source_ref_type` of
    `RETURN_AUTHORIZATION`."
    PRD 3.9: "Money is conditional on this branch and only on this branch: when
    `return_reason` is `DEFECTIVE` the dealer is still made whole exactly as on the
    restock branch — `credit_posted_cents` is set to `final_credit_cents` and
    `outstanding_balance_cents`, `lifetime_restocking_fee_cents`, `lifetime_rebate_cents`
    and `credit_hold` are all updated identically — whereas for `WRONG_PART`,
    `UNUSED_SURPLUS` and `CORE_RETURN` the scrap is at the dealer's expense:
    `credit_posted_cents` stays 0 and not one dealer field changes."

    Design: Difficulty/non_linear_state_machine/return_fork_restock_credits_versus_scrap_writes_off
    """
    scenario = _inspection_fork_scenario()
    inspect_rma(scenario["rma1"]["id"], "RESTOCK")
    scrapped = inspect_rma(scenario["rma2"]["id"], "SCRAP")

    assert scrapped["restocking_fee_cents"] == 1080
    assert scrapped["final_credit_cents"] == 6118
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["disposition"] == "SCRAP"
    assert scrapped["credit_posted_cents"] == 0, \
        "an UNUSED_SURPLUS scrap is at the dealer's expense"

    entries, meta = list_ledger(scenario["part"]["id"])
    assert meta["total_count"] == 6
    assert [e["delta_units"] for e in entries] == [20, -3, -4, 3, 4, -4]
    scrap_rows = [e for e in entries if e["entry_type"] == "SCRAP"]
    assert len(scrap_rows) == 1
    assert scrap_rows[0]["delta_units"] == -4
    assert scrap_rows[0]["source_ref_type"] == "RETURN_AUTHORIZATION"
    for entry in entries:
        assert_ledger_entry(entry)
    assert_ledger_balances_stock(entries, read_part(scenario["part"]["id"]))


def test_rma_against_a_reserved_line_is_refused(api):
    """PRD 3.9: "The source line must be in `line_status` `CONSUMED`; anything else
    gives `ERR_LINE_STATE_INVALID`."
    PRD 2.10: "The target resource is in a state from which the requested transition
    is declared, including the cross-dimension guard on shipping a replenishment order
    and the cross-entity guards: submitting a campaign requires its part to be in
    `PHASE_OUT`; creating an allocation request requires the campaign to be in
    `APPROVED`; creating a return authorization requires the source line to be in
    `CONSUMED`; approving or receiving a replenishment order requires the part not to
    be `OBSOLETE`; and inspecting a return with a `RESTOCK` disposition requires the
    part not to be `OBSOLETE`."

    Design: Difficulty/cross_entity_state_dependency/return_authorization_gated_by_line_consumed
    """
    scenario = setup_scenario_with_work_order(
        part_number="RSV-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=2.0, dealer_code="D-RSV", model_code="EM-G10",
        serial_prefix="SN-G10", stock_units=10,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    line = add_part_line(scenario["work_order"]["id"], scenario["dealer"]["id"],
                         scenario["part"]["id"], 2)
    assert line["line_status"] == "RESERVED"

    resp = api.create_return_authorization(
        create_return_authorization_payload(line["id"], 1, "WRONG_PART"),
        scenario["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_LINE_STATE_INVALID.value)


def test_refused_rma_leaves_the_line_and_stock_untouched(api):
    """PRD 3.9: "A newly raised return has computed `age_days`, `gross_credit_cents`,
    `fee_pct`, `restocking_fee_cents`, `net_before_rebate_cents`, `rebate_pct`,
    `loyalty_rebate_cents` and `final_credit_cents`, but no stock has moved, no ledger
    row exists and `credit_posted_cents` remains 0."
    PRD 3.6: "A `STOCK` decision puts the line straight into `line_status` `RESERVED`,
    raises the part's `allocated_units` by `qty_requested`, recomputes `available_units`,
    and advances the part's `version`."
    PRD 3.9: "Returns can be listed and filtered by `part_id`, by `dealer_id`, by
    `work_order_part_line_id` and by `status`."

    Design: Difficulty/cross_entity_state_dependency/return_authorization_gated_by_line_consumed
    """
    scenario = setup_scenario_with_work_order(
        part_number="RSV-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=2.0, dealer_code="D-RSV", model_code="EM-G10",
        serial_prefix="SN-G10", stock_units=10,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    line = add_part_line(scenario["work_order"]["id"], scenario["dealer"]["id"],
                         scenario["part"]["id"], 2)
    api.create_return_authorization(
        create_return_authorization_payload(line["id"], 1, "WRONG_PART"),
        scenario["dealer_headers"])

    settled = read_part_line(line["id"])
    assert settled["line_status"] == "RESERVED"
    assert settled["charged_amount_cents"] == 0
    assert settled["consumed_at"] is None

    part = read_part(scenario["part"]["id"])
    assert part["on_hand_units"] == 10
    assert part["allocated_units"] == 2
    assert part["available_units"] == 8
    assert part["quarantine_units"] == 0

    _, meta = validate_paginated(api.list_return_authorizations(
        PLANNER, params={"work_order_part_line_id": line["id"]}))
    assert meta["total_count"] == 0


def _restocked_return_scenario(part_number, stock_units, clock_after,
                               dealer_code, model_code, serial_prefix):
    scenario = setup_received_rma(
        7, "UNUSED_SURPLUS", clock_after, part_number=part_number, qty=7,
        stock_units=stock_units, unit_cost_cents=1333, lead_time_days=30,
        weight_kg=2.0, dealer_code=dealer_code, model_code=model_code,
        serial_prefix=serial_prefix, qty_per_unit=1,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    return scenario


def test_consume_then_restock_return_conserves_physical_units(api):
    """PRD 2.8: "Physical movements are recorded in an append-only stock ledger, one
    entry per movement."
    PRD 3.9: "The part's `quarantine_units` falls by `qty_returned` and its
    `on_hand_units` rises by the same amount; because the combined
    on-hand-plus-quarantine total is unchanged by that move, **no ledger entry is
    appended at all**."
    PRD 2.8: "The derived counter `available_units` is always `on_hand_units` minus
    `allocated_units`, and it is recomputed after every movement that touches either
    operand."

    Design: Difficulty/compensating_invariant/physical_unit_conservation_consume_then_restock_return
    """
    scenario = _restocked_return_scenario("CONS-1", 100, "2026-08-11T00:00:00Z",
                                          "D-CONS", "EM-I10", "SN-I10")
    credited = inspect_rma(scenario["rma"]["id"], "RESTOCK")
    assert credited["status"] == "CREDITED"
    assert credited["disposition"] == "RESTOCK"

    part = read_part(scenario["part"]["id"])
    assert part["on_hand_units"] == 100
    assert part["quarantine_units"] == 0
    assert part["allocated_units"] == 0
    assert part["available_units"] == 100

    entries, _ = list_ledger(scenario["part"]["id"])
    assert_ledger_balances_stock(entries, part)


def test_restock_return_writes_exactly_three_ledger_rows(api):
    """PRD 2.8: "Each entry stores the `part_id` it belongs to, an `entry_type` of
    `RECEIPT`, `ISSUE`, `RETURN_RECEIPT` or `SCRAP`, a signed `delta_units` describing
    the change to the combined total of `on_hand_units` and `quarantine_units` —
    positive for `RECEIPT` and `RETURN_RECEIPT`, negative for `ISSUE` and `SCRAP` — and
    a `balance_after_units` recording the sum of `on_hand_units` and `quarantine_units`
    immediately after the entry is applied."
    PRD 3.9: "Receiving moves it from `APPROVED` to `RECEIVED`, raises the part's
    `quarantine_units` by `qty_returned`, and appends one ledger entry with `entry_type`
    `RETURN_RECEIPT`, a positive `delta_units` equal to `qty_returned` and a
    `source_ref_type` of `RETURN_AUTHORIZATION`; both the part's `version` and the
    return's `version` advance."
    PRD 2.3: "the stock ledger of a part is returned oldest first ordered by
    `occurred_at` and then by `created_at` as a tie-break"

    Design: Difficulty/compensating_invariant/physical_unit_conservation_consume_then_restock_return
    """
    scenario = _restocked_return_scenario("CONS-1", 100, "2026-08-11T00:00:00Z",
                                          "D-CONS", "EM-I10", "SN-I10")
    inspect_rma(scenario["rma"]["id"], "RESTOCK")

    entries, meta = list_ledger(scenario["part"]["id"])
    assert meta["total_count"] == 3, "the RESTOCK inspection itself appends nothing"
    assert [e["delta_units"] for e in entries] == [100, -7, 7]
    assert entries[-1]["entry_type"] == "RETURN_RECEIPT"
    assert entries[-1]["balance_after_units"] == 100
    assert entries[-1]["source_ref_type"] == "RETURN_AUTHORIZATION"
    for entry in entries:
        assert_ledger_entry(entry)


def test_forty_five_day_return_applies_the_ten_point_age_surcharge(api):
    """PRD 3.9: "The age surcharge is nothing when `age_days` is 30 or fewer, ten
    percentage points when `age_days` is more than 30 but no more than 90, and
    twenty-five percentage points beyond that."
    PRD 3.9: "The three are added, the total is capped at fifty percent — that is, the
    smaller of the cap and the sum is taken — and the result is rounded half up to four
    decimal places to give `fee_pct`. `restocking_fee_cents` is then
    `gross_credit_cents` multiplied by `fee_pct`, rounded half up to a whole cent."
    PRD 3.9: "`net_before_rebate_cents` is `gross_credit_cents` less
    `restocking_fee_cents`, floored at 0."
    PRD 3.9: "`age_days`, the number of whole days from the line's `consumed_at` to the
    current logical instant with any partial day discarded, may not exceed 180 days, and
    an older return is refused with `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Difficulty/compensating_invariant/dealer_money_conservation_charge_then_restock_credit
    """
    scenario = _restocked_return_scenario("MON-1", 20, "2026-09-15T00:00:00Z",
                                          "D-MON", "EM-J10", "SN-J10")
    rma = read_return_authorization(scenario["rma"]["id"])
    assert scenario["line"]["charged_amount_cents"] == 12597

    assert rma["age_days"] == 45
    assert rma["fee_pct"] == 0.25
    assert rma["gross_credit_cents"] == 12597
    assert rma["restocking_fee_cents"] == 3149
    assert rma["net_before_rebate_cents"] == 9448
    assert rma["rebate_pct"] == 0.0
    assert rma["loyalty_rebate_cents"] == 0
    assert rma["final_credit_cents"] == 9448
    assert_return_credit_chain(rma)


def test_charge_then_restock_credit_conserves_dealer_money(api):
    """PRD 3.9: "One invariant is worth stating as an acceptance property. For a
    consume followed by a full-quantity restock return of the same line, the dealer's
    `outstanding_balance_cents`, less its `lifetime_restocking_fee_cents`, plus its
    `lifetime_rebate_cents`, returns to exactly the value it held before the consume.
    Money is conserved across that pair."
    PRD 3.9: "The dealer is made whole: `credit_posted_cents` is set to
    `final_credit_cents`, the dealer's `outstanding_balance_cents` is reduced by
    `final_credit_cents`, the dealer's `lifetime_restocking_fee_cents` rises by
    `restocking_fee_cents`, the dealer's `lifetime_rebate_cents` rises by
    `loyalty_rebate_cents`, and the dealer's `credit_hold` is recomputed."
    PRD 3.1: "Derived from it is `credit_hold`, which is true exactly when
    `outstanding_balance_cents` is strictly greater than `credit_limit_cents`, and which
    is recomputed every single time the balance or the limit changes."

    Design: Difficulty/compensating_invariant/dealer_money_conservation_charge_then_restock_credit
    """
    scenario = _restocked_return_scenario("MON-1", 20, "2026-09-15T00:00:00Z",
                                          "D-MON", "EM-J10", "SN-J10")
    assert read_dealer(scenario["dealer"]["id"])["outstanding_balance_cents"] == 12597

    credited = inspect_rma(scenario["rma"]["id"], "RESTOCK")
    assert credited["credit_posted_cents"] == 9448

    dealer = read_dealer(scenario["dealer"]["id"])
    assert dealer["outstanding_balance_cents"] == 3149
    assert dealer["lifetime_restocking_fee_cents"] == 3149
    assert dealer["lifetime_rebate_cents"] == 0
    assert dealer["credit_hold"] is False
    conserved = (dealer["outstanding_balance_cents"]
                 - dealer["lifetime_restocking_fee_cents"]
                 + dealer["lifetime_rebate_cents"])
    assert conserved == 0, (
        f"balance less lifetime fees plus lifetime rebates must return to the "
        f"pre-consume 0, got {conserved}")


def test_return_after_ninety_days_uses_the_top_age_surcharge(api):
    """PRD 3.9: "The age surcharge is nothing when `age_days` is 30 or fewer, ten
    percentage points when `age_days` is more than 30 but no more than 90, and
    twenty-five percentage points beyond that."
    PRD 3.9: "The base component depends on `return_reason`: fifteen percent for
    `UNUSED_SURPLUS`, and nothing at all for `WRONG_PART`, for `DEFECTIVE` and for
    `CORE_RETURN`."
    PRD 3.9: "None of that money moves yet. A newly raised return has computed
    `age_days`, `gross_credit_cents`, `fee_pct`, `restocking_fee_cents`,
    `net_before_rebate_cents`, `rebate_pct`, `loyalty_rebate_cents` and
    `final_credit_cents`, but no stock has moved, no ledger row exists and
    `credit_posted_cents` remains 0."

    Design: Corner/calculations/restocking_fee_age_tier_over_ninety_days
    """
    scenario = setup_consumed_line(
        part_number="AGE-1", qty=7, stock_units=20, unit_cost_cents=1333,
        lead_time_days=30, weight_kg=1.0, dealer_code="D-AGE",
        model_code="EM-U10", serial_prefix="SN-U10", qty_per_unit=1,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    set_clock("2026-11-09T00:00:00Z")

    rma = create_rma(scenario["line"]["id"], scenario["dealer"]["id"], 7,
                     "UNUSED_SURPLUS")
    assert rma["age_days"] == 100
    assert rma["gross_credit_cents"] == 12597
    assert rma["fee_pct"] == 0.40
    assert rma["restocking_fee_cents"] == 5039
    assert rma["net_before_rebate_cents"] == 7558
    assert rma["rebate_pct"] == 0.0
    assert rma["final_credit_cents"] == 7558
    assert rma["status"] == "REQUESTED"
    assert read_dealer(scenario["dealer"]["id"])["outstanding_balance_cents"] == 12597


def test_return_quantity_over_the_consumed_quantity_is_rejected(api):
    """PRD 3.9: "And the return must not over-return: the requested `qty_returned` plus
    the `qty_returned` of every return authorization already raised against the same line
    and not in `REJECTED` may not exceed that line's `qty_consumed`, or the request is
    refused with `ERR_RETURN_QTY_EXCEEDS_CONSUMED`."

    Design: Corner/validations/return_qty_exceeding_consumed_is_rejected_inside_the_window
    """
    scenario = setup_consumed_line(
        part_number="RQT-1", qty=3, stock_units=10, unit_cost_cents=1333,
        lead_time_days=30, weight_kg=1.0, dealer_code="D-RQT",
        model_code="EM-Z10", serial_prefix="SN-Z10", qty_per_unit=1,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    set_clock("2026-08-11T00:00:00Z")

    resp = api.create_return_authorization(
        create_return_authorization_payload(scenario["line"]["id"], 5, "WRONG_PART"),
        make_dealer_headers(scenario["dealer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_CONSUMED.value)

    _, meta = validate_paginated(api.list_return_authorizations(
        PLANNER, params={"work_order_part_line_id": scenario["line"]["id"]}))
    assert meta["total_count"] == 0
    assert read_part(scenario["part"]["id"])["quarantine_units"] == 0


def test_inspecting_before_receiving_is_refused(api):
    """PRD 3.9: "Receiving moves it from `APPROVED` to `RECEIVED`, raises the part's
    `quarantine_units` by `qty_returned`, and appends one ledger entry with `entry_type`
    `RETURN_RECEIPT`, a positive `delta_units` equal to `qty_returned` and a
    `source_ref_type` of `RETURN_AUTHORIZATION`; both the part's `version` and the
    return's `version` advance. Any of these attempted from the wrong return state is
    refused with `ERR_RETURN_STATE_INVALID`."
    PRD 3.9: "Inspection is the fork, and the caller states which branch by supplying a
    `disposition`."

    Design: Corner/errors/return_inspect_before_receive_returns_return_state_invalid
    """
    scenario = setup_consumed_line(
        part_number="RSI-1", qty=2, stock_units=10, unit_cost_cents=1333,
        lead_time_days=30, weight_kg=1.0, dealer_code="D-RSI",
        model_code="EM-AF1", serial_prefix="SN-AF1", qty_per_unit=1,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    rma = create_rma(scenario["line"]["id"], scenario["dealer"]["id"], 2,
                     "WRONG_PART")
    approve_rma(rma["id"])

    resp = api.inspect_return_authorization(rma["id"], "RESTOCK", PLANNER)
    validate_error(resp, ApiErrorId.ERR_RETURN_STATE_INVALID.value)

    settled = read_return_authorization(rma["id"])
    assert settled["status"] == "APPROVED"
    assert settled["disposition"] is None
    assert settled["credit_posted_cents"] == 0

    part = read_part(scenario["part"]["id"])
    assert part["quarantine_units"] == 0
    assert part["on_hand_units"] == 8
    dealer = read_dealer(scenario["dealer"]["id"])
    assert dealer["outstanding_balance_cents"] == 3599
    assert dealer["lifetime_restocking_fee_cents"] == 0
