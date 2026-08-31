"""Checkout, return and settlement: the chronological price and the state gates
that guard it."""


from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_east_branch,
    add_trailer,
    list_units,
    make_branch_manager_headers,
    open_agreement,
    read_agreement,
    read_agreement_unit,
    read_branch,
    read_customer,
    read_trailer,
    return_unit,
    setup_agreement_active,
    setup_agreement_pending_allocation,
    setup_agreement_reserved,
    setup_approved_chargeback,
    setup_reference_data,
    setup_returned_unit,
    settle_agreement,
    validate_error,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def test_returning_a_line_that_never_went_out_is_rejected(api):
    """PRD §3.6: "A line whose status is not `OUT` is rejected with
    `ERR_UNIT_NOT_OUT`."
    PRD §3.6: "A successful return stamps `return_branch_id`, `return_date` and
    `return_hub_miles` onto the line, then pushes those facts down onto the
    physical unit: the trailer's `hub_miles` is set to the reported
    `return_hub_miles`, its `current_branch_id` is set to the reported
    `return_branch_id`, and its availability moves `ON_RENT → AVAILABLE` or
    `ON_LEASE → AVAILABLE`."

    Design: Corner/state_machines/unit_return_from_allocated_reports_unit_not_out
    """
    scn = setup_agreement_reserved()
    unit_id = list_units(agreement_id=scn["agreement_id"])[0]["id"]

    response = api.return_agreement_unit(
        unit_id,
        {"return_branch_id": scn["branch_id"], "return_hub_miles": 42000,
         "return_date": "2026-09-03"},
        make_branch_manager_headers(scn["branch_id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNIT_NOT_OUT.value)

    line = read_agreement_unit(unit_id)
    assert line["status"] == "ALLOCATED"
    assert line.get("return_branch_id") is None
    assert line.get("return_date") is None
    assert read_trailer(scn["trailer_id"])["hub_miles"] == 41000


def test_emptying_the_out_set_bubbles_the_contract_to_pending_settlement(api):
    """PRD §3.6: "Finally the server evaluates a bubble-up: when the contract has
    no line left in status `OUT` and has at least one line in status `RETURNED`,
    the contract advances `ACTIVE → PENDING_SETTLEMENT` and its `version`
    increments by 1."

    Design: Corner/state_machines/last_unit_return_bubbles_agreement_to_pending_settlement
    """
    ctx = setup_reference_data()
    second = add_trailer(ctx, "second", unit_number="T-1002", hub_miles=52000)
    scn = setup_agreement_active(ctx=ctx, unit_count=2)

    first_line = list_units(agreement_id=scn["agreement_id"],
                            trailer_id=ctx["trailer_id"])[0]
    second_line = list_units(agreement_id=scn["agreement_id"],
                             trailer_id=second["id"])[0]

    return_unit(scn, unit_id=first_line["id"], return_hub_miles=42000,
                return_date="2026-09-03")
    assert read_agreement(scn["agreement_id"])["status"] == "ACTIVE", (
        "one line is still out with the customer"
    )

    return_unit(scn, unit_id=second_line["id"], return_hub_miles=53000,
                return_date="2026-09-04")
    assert read_agreement(scn["agreement_id"])["status"] == "PENDING_SETTLEMENT"

    assert read_agreement_unit(first_line["id"])["status"] == "RETURNED"
    assert read_agreement_unit(second_line["id"])["status"] == "RETURNED"
    assert read_branch(scn["branch_id"])["on_hand_count"] == 2


def test_cancelling_a_closed_contract_is_rejected(api):
    """PRD §3.4: "It is permitted only while the contract is in `DRAFT`,
    `PENDING_INSURANCE`, `PENDING_ALLOCATION` or `RESERVED`; a contract already in
    `ACTIVE`, `PENDING_SETTLEMENT`, `CLOSED` or `CANCELLED` is rejected with
    `ERR_AGREEMENT_TERMINAL`."

    Design: Corner/state_machines/agreement_cancel_from_closed_reports_agreement_terminal
    """
    scn = setup_returned_unit()
    closed = settle_agreement(scn)
    final_total = closed["final_total_cents"]

    response = api.cancel_agreement(
        scn["agreement_id"], {"reason": "customer changed their mind"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_AGREEMENT_TERMINAL.value)

    stored = read_agreement(scn["agreement_id"])
    assert stored["status"] == "CLOSED"
    assert stored.get("cancel_reason") is None
    assert stored["final_total_cents"] == final_total
    assert read_agreement_unit(scn["unit_id"])["status"] == "SETTLED"


def test_settling_a_draft_contract_is_rejected(api):
    """PRD §3.6: "Settlement is a `FleetAdmin` privilege and closes the contract,
    advancing it `PENDING_SETTLEMENT → CLOSED`; a contract in any other status is
    rejected with `ERR_AGREEMENT_NOT_SETTLEABLE`."

    Design: Corner/errors/settle_on_draft_agreement_reports_not_settleable
    """
    ctx = setup_reference_data()
    agreement = open_agreement(ctx)

    response = api.settle_agreement(agreement["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_SETTLEABLE.value)

    assert read_agreement(agreement["id"]).get("final_total_cents") is None


def _early_return_at_a_foreign_yard():
    """A 21-day rental over the peak boundary that comes home early, over its
    mileage inclusion and at a yard other than the one that hired it out."""
    ctx = setup_reference_data()
    add_east_branch(ctx)
    scn = setup_agreement_active(ctx=ctx, checkout_date="2026-08-20")
    unit = return_unit(scn, return_branch_id=ctx["east_branch_id"],
                       return_hub_miles=44000, return_date="2026-09-03")
    scn["unit"] = unit
    scn["unit_id"] = unit["id"]
    return scn


def test_forward_quote_prices_the_whole_planned_window(api):
    """PRD §3.5: "The forward-looking quote is computed once, at the moment the
    contract first reaches `RESERVED`, and it reads nothing but the contract itself
    and its pinned card — it never looks at contract unit lines."
    PRD §3.5: "The quote is deliberately optimistic in three fixed ways: it assumes
    zero excess mileage, zero drop charge, and that every one of the `unit_count`
    units runs the full planned window."

    Design: Difficulty/dual_variant_calc/agreement_quoted_forward_vs_final_chronological_diverge
    """
    ctx = setup_reference_data()
    add_east_branch(ctx)
    scn = setup_agreement_reserved(ctx=ctx)

    agreement = read_agreement(scn["agreement_id"])
    assert agreement["quoted_total_cents"] == 123240, (
        "twelve off-peak days at 5200 plus nine peak days at 6760"
    )
    assert agreement["status"] == "RESERVED"
    assert agreement.get("final_total_cents") is None


def test_final_chronological_total_diverges_from_the_forward_quote(api):
    """PRD §3.6: "The line's `line_charge_cents` is the base charge plus the
    mileage charge plus the drop charge, rounded half-up to whole cents."
    PRD §3.6: "The line's `drop_charge_cents` is 35000 cents — a flat
    three-hundred-fifty-dollar one-way drop fee — whenever the line's
    `return_branch_id` differs from the contract's own `branch_id`, and 0 when the
    unit came home to the yard that hired it out."
    PRD §3.6: "The line's `excess_miles` is the distance actually run, namely
    `return_hub_miles` less `checkout_hub_miles`, less that allowance, floored at
    zero so a unit that stays inside its allowance contributes no excess."

    Design: Difficulty/dual_variant_calc/agreement_quoted_forward_vs_final_chronological_diverge
    """
    scn = _early_return_at_a_foreign_yard()
    quoted = read_agreement(scn["agreement_id"])["quoted_total_cents"]
    assert quoted == 123240

    agreement = settle_agreement(scn)
    assert agreement["final_total_cents"] == 151268
    assert agreement["final_total_cents"] != quoted
    assert agreement["status"] == "CLOSED"

    line = read_agreement_unit(scn["unit_id"])
    assert line["line_charge_cents"] == 151268
    assert line["peak_days"] == 2
    assert line["excess_miles"] == 1834
    assert line["drop_charge_cents"] == 35000
    assert line["status"] == "SETTLED"


def _split_cent_rate_scenario():
    """Two units on a card whose peak daily rate is exactly 5595.375 cents, so the
    rounding order is observable in the last cent."""
    ctx = setup_reference_data(
        rate_card={"daily_rate_cents": 5205, "peak_uplift_pct": 0.075},
        trailer={"unit_number": "T-2001", "hub_miles": 10000},
    )
    add_trailer(ctx, "second", unit_number="T-2002", hub_miles=20000)
    scn = setup_agreement_active(
        ctx=ctx, unit_count=2, start_date="2026-09-01", end_date="2026-09-03",
        checkout_date="2026-09-01",
    )
    first_line = list_units(agreement_id=scn["agreement_id"],
                            trailer_id=ctx["trailer_id"])[0]
    second_line = list_units(agreement_id=scn["agreement_id"],
                             trailer_id=ctx["second_id"])[0]
    return_unit(scn, unit_id=first_line["id"], return_hub_miles=10000,
                return_date="2026-09-02")
    return_unit(scn, unit_id=second_line["id"], return_hub_miles=20000,
                return_date="2026-09-02")
    scn["line_ids"] = [first_line["id"], second_line["id"]]
    return scn


def test_each_unit_line_is_rounded_to_whole_cents_before_summing(api):
    """PRD §3.6: "The order of rounding here is pinned and is not interchangeable:
    each line is rounded to whole cents first, and `final_total_cents` is then the
    plain sum of those already-rounded line charges. Summing the unrounded lines
    and rounding once at the end produces a different and incorrect number."

    Design: Difficulty/combinatorial_formula/final_total_rounds_each_unit_line_before_summing
    """
    scn = _split_cent_rate_scenario()

    agreement = settle_agreement(scn)
    for line_id in scn["line_ids"]:
        line = read_agreement_unit(line_id)
        assert line["line_charge_cents"] == 5595, (
            "5595.375 cents rounds half-up to 5595 per line"
        )
        assert line["peak_days"] == 1

    assert agreement["final_total_cents"] == 11190
    assert agreement["final_total_cents"] != 11191, (
        "11191 is what summing first and rounding once would give"
    )


def test_the_forward_quote_rounds_the_whole_per_unit_charge_once(api):
    """PRD §3.5: "A per-unit charge is then formed by multiplying the pinned card's
    `daily_rate_cents` by the off-peak day count, multiplying the peak daily rate
    by the peak day count, adding the two, and rounding that sum half-up to whole
    cents. `quoted_total_cents` is that per-unit charge multiplied by the
    contract's `unit_count`."
    PRD §3.3: "Wherever this document refers to a **peak daily rate**, it means the
    card's `daily_rate_cents` multiplied by the quantity one plus its
    `peak_uplift_pct`."

    Design: Difficulty/combinatorial_formula/final_total_rounds_each_unit_line_before_summing
    """
    scn = _split_cent_rate_scenario()

    agreement = read_agreement(scn["agreement_id"])
    assert agreement["quoted_total_cents"] == 22382, (
        "two peak days at 5595.375 cents is 11190.75, rounded half-up to 11191 "
        "per unit, times two units"
    )


def _over_limit_lessee_with_a_pending_allocation_contract():
    """A lessee whose approved damage exposure is more than double its credit
    limit, carrying a second contract that has not yet been filled with equipment."""
    ctx = setup_reference_data(
        customer={"legal_name": "Thin Margin Freight", "dot_number": "DOT-902",
                  "credit_tier": "B", "credit_limit_cents": 50000},
        certificate={"policy_number": "P-9"},
    )
    setup_approved_chargeback(ctx=ctx)
    assert read_customer(ctx["customer_id"])["outstanding_chargeback_cents"] == 108000

    return setup_agreement_pending_allocation(
        ctx=ctx, start_date="2026-10-01", end_date="2026-10-11"
    )


def test_checkout_reports_the_state_error_before_the_credit_limit_error(api):
    """PRD §2.9: "The target record's from-state for the transition being
    requested, or the state code belonging to that transition (the full list
    appears in section 5, and each is named in section 3 beside the workflow it
    guards)."
    PRD §3.6: "A contract in any status other than `RESERVED` is rejected with
    `ERR_AGREEMENT_NOT_RESERVED`."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_precondition_outranks_credit_limit_fiscal_check
    """
    scn = _over_limit_lessee_with_a_pending_allocation_contract()

    response = api.activate_agreement(
        scn["agreement_id"], {"checkout_date": "2026-10-05"}, ADMIN
    )
    error = validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_RESERVED.value)
    assert error["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, (
        "the from-state check outranks the fiscal check"
    )
    assert read_agreement(scn["agreement_id"])["status"] == "PENDING_ALLOCATION"


def test_the_over_limit_balance_that_was_not_reported_is_really_present(api):
    """PRD §3.6: "The lessee's `outstanding_chargeback_cents` must be no greater
    than its `credit_limit_cents`, and a balance strictly above the limit is
    rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) — a balance exactly equal
    to the limit passes."
    PRD §3.4: "A successful submission freezes that score into
    `underwriting_risk_score` on the contract — the number is a snapshot and is
    never re-evaluated afterwards — and increments the contract's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_precondition_outranks_credit_limit_fiscal_check
    """
    scn = _over_limit_lessee_with_a_pending_allocation_contract()

    lessee = read_customer(scn["customer_id"])
    assert lessee["outstanding_chargeback_cents"] == 108000
    assert lessee["credit_limit_cents"] == 50000
    assert lessee["outstanding_chargeback_cents"] > lessee["credit_limit_cents"], (
        "the fiscal rule the state check pre-empted really is violated"
    )
    assert read_agreement(scn["agreement_id"])["underwriting_risk_score"] == 48
