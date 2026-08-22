"""Pricing the move: the five buckets, the two variants, the waterfall, the
invoice and the payment that closes the account."""
from test_helpers import (
    ApiErrorId,
    STANDARD_DISCHARGES,
    add_assignment,
    arrive_tow,
    assert_charge_breakdown_shape,
    assert_waterfall_consistent,
    create_active_contract,
    create_barge,
    create_tow,
    depart_tow,
    discharge_assignment,
    issue_invoice,
    make_contract_manager_headers,
    read_assignment,
    read_breakdown,
    read_contract,
    read_shipper,
    seal_tow,
    setup_grain_movement,
    setup_grain_reference,
    setup_invoiced_movement,
    validate_error,
    validate_success,
)

BILLER = make_contract_manager_headers()

FROZEN_BUCKETS = (
    "linehaul_cents", "fuel_surcharge_cents", "fleeting_fee_cents",
    "cleaning_fee_cents", "demurrage_cents", "subtotal_cents",
    "volume_rebate_cents", "total_cents",
)


def _two_cut_discharged_movement(**kwargs):
    return setup_grain_movement(
        loads=(1700, 1650), contracted_tons=3400, stage="DISCHARGED", **kwargs)


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / demurrage read two ways
# ---------------------------------------------------------------------------
def test_provisional_demurrage_charges_each_barge_its_own_free_laytime(api):
    """PRD §3.7: "The `gross_laytime_hours` is the elapsed time from the barge's
    `arrived_at` to its `unload_finished_at`, divided into hours of 3,600
    seconds and rounded **up** to a whole hour — this is the tender-to-finish
    clock, and it runs while the barge waits in line."
    PRD §3.8: "Under the `PROVISIONAL` variant, each barge carries its own
    free-laytime allowance and its clock starts the moment it is tendered: for
    each line, the chargeable hours are that line's `gross_laytime_hours` minus
    the contract's `laytime_hours`, floored at zero; those chargeable hours are
    summed across the lines and the sum is multiplied by the rate."

    Design: Difficulty/dual_variant_calc/demurrage_pooled_net_versus_per_barge_gross_on_freight_contract
    """
    movement = _two_cut_discharged_movement()
    first = read_assignment(movement["assignments"][0]["id"])
    second = read_assignment(movement["assignments"][1]["id"])
    assert first["gross_laytime_hours"] == 32 and first["net_laytime_hours"] == 20, (
        f"cut 1 clocks 32 gross and 20 net hours, got "
        f"{first['gross_laytime_hours']} and {first['net_laytime_hours']}")
    assert second["gross_laytime_hours"] == 26 and second["net_laytime_hours"] == 8, (
        f"cut 2 clocks 26 gross and 8 net hours, got "
        f"{second['gross_laytime_hours']} and {second['net_laytime_hours']}")

    breakdown = read_breakdown(movement["contract_id"], "PROVISIONAL")
    assert_charge_breakdown_shape(breakdown, "PROVISIONAL")
    assert breakdown["demurrage_cents"] == 1_105_000, (
        f"(32-12) + (26-12) = 34 chargeable hours at 32500, "
        f"got {breakdown['demurrage_cents']}")
    assert breakdown["linehaul_cents"] == 1_658_652, (
        "the provisional lines carry the bill-of-lading weights")
    assert breakdown["total_cents"] == 2_795_717
    assert_waterfall_consistent(breakdown)


def test_final_demurrage_pools_free_laytime_across_the_discharged_barges(api):
    """PRD §3.8: "Under the `FINAL` variant, free laytime is pooled across the
    contract's discharged barges and the clock runs only while cargo is actually
    moving, plus a fixed notice grace of 6 hours per barge: the hours used are
    the sum, over the lines, of each line's `net_laytime_hours` plus 6; the
    pooled allowance is the contract's `laytime_hours` multiplied by the number
    of lines; and `demurrage_cents` is the used hours minus the pooled
    allowance, floored at zero, multiplied by the rate."
    PRD §3.8: "That read is a pure computation: nothing is persisted and no
    `version` anywhere is incremented."

    Design: Difficulty/dual_variant_calc/demurrage_pooled_net_versus_per_barge_gross_on_freight_contract
    """
    movement = _two_cut_discharged_movement()
    before = read_contract(movement["contract_id"])

    breakdown = read_breakdown(movement["contract_id"], "FINAL")
    assert_charge_breakdown_shape(breakdown, "FINAL")
    assert breakdown["demurrage_cents"] == 520_000, (
        f"(20+6) + (8+6) = 40 used hours against a 24-hour pool at 32500, "
        f"got {breakdown['demurrage_cents']}")
    assert breakdown["linehaul_cents"] == 1_648_749, (
        "the final lines carry the outturn weights")
    assert breakdown["total_cents"] == 2_209_299
    assert_waterfall_consistent(breakdown)

    after = read_contract(movement["contract_id"])
    assert after["version"] == before["version"], (
        "the breakdown read must not increment any version")
    for field in FROZEN_BUCKETS:
        assert after[field] == before[field], (
            f"the breakdown read must persist nothing, but {field} moved")


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / line-level rounding
# ---------------------------------------------------------------------------
def test_linehaul_rounds_each_line_before_summing(api):
    """PRD §3.8: "Each billable line contributes its tonnage multiplied by
    `distance_miles` multiplied by the rate, rounded half up to whole cents —
    **each line individually, before any summation**. Summing raw line values
    and rounding once at the end is expressly not the rule and yields a
    different total."
    PRD §3.8: "Under the `FINAL` variant, the billable lines are the contract's
    assignments whose `discharge_status` is `COMPLETED` or `DISPUTED`, and each
    contributes its `discharged_tons`, the outturn weight."

    Design: Difficulty/combinatorial_formula/linehaul_rounds_each_barge_line_before_summing
    """
    movement = _two_cut_discharged_movement()
    breakdown = read_breakdown(movement["contract_id"], "FINAL")
    assert breakdown["billable_line_count"] == 2
    assert breakdown["linehaul_cents"] == 1_648_749, (
        f"835267 + 813482 with each line rounded first, "
        f"got {breakdown['linehaul_cents']}")
    assert breakdown["linehaul_cents"] != 1_648_750, (
        "summing the raw line values and rounding once is the wrong order")


def test_fuel_surcharge_rides_on_the_rounded_linehaul(api):
    """PRD §3.8: "**The fuel surcharge** rides on the linehaul and on nothing
    else — never on demurrage, never on fleeting, never on cleaning, and never
    on the rebate."
    PRD §3.8: "It is the `linehaul_cents` figure multiplied by the contract's
    `pinned_fuel_surcharge_pct`, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/linehaul_rounds_each_barge_line_before_summing
    """
    movement = _two_cut_discharged_movement()
    breakdown = read_breakdown(movement["contract_id"], "FINAL")
    assert breakdown["fuel_surcharge_cents"] == 74_194, (
        f"1648749 * 0.045 rounded half up, got {breakdown['fuel_surcharge_cents']}")
    assert breakdown["fleeting_fee_cents"] == 0
    assert breakdown["cleaning_fee_cents"] == 0


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / the rebate tier is keyed on the subtotal
# ---------------------------------------------------------------------------
def _long_haul_invoiced_movement():
    return setup_invoiced_movement(
        loads=(1700, 1650), contracted_tons=3400,
        contract_kwargs={"origin_mile": 1252, "destination_mile": 200},
        tow_kwargs={"origin_mile": 1252, "destination_mile": 200})


def test_invoice_freezes_the_five_buckets_and_the_subtotal(api):
    """PRD §3.8: "Step one: `subtotal_cents` is `linehaul_cents` plus
    `fuel_surcharge_cents` plus `fleeting_fee_cents` plus `cleaning_fee_cents`
    plus `demurrage_cents`."
    PRD §3.8: "Issue runs every charge rule in its `FINAL` form and fixes
    `linehaul_cents`, `fuel_surcharge_cents`, `fleeting_fee_cents`,
    `cleaning_fee_cents`, `demurrage_cents`, `subtotal_cents`,
    `volume_rebate_cents` and `total_cents` onto the contract, where they are
    never re-derived afterwards."

    Design: Difficulty/combinatorial_formula/volume_rebate_tier_keyed_on_subtotal_not_on_post_rebate_total
    """
    movement = _long_haul_invoiced_movement()
    contract = read_contract(movement["contract_id"])
    assert contract["linehaul_cents"] == 4_336_211, (
        f"2196753 + 2139458 over a 1052-mile haul, got {contract['linehaul_cents']}")
    assert contract["fuel_surcharge_cents"] == 195_129
    assert contract["demurrage_cents"] == 520_000
    assert contract["subtotal_cents"] == 5_051_340
    assert contract["billing_status"] == "INVOICED"


def test_volume_rebate_tier_is_keyed_on_the_subtotal_not_the_post_rebate_total(api):
    """PRD §3.8: "Step two: the rebate tier is selected on `subtotal_cents`
    alone, taking the highest tier whose floor it reaches — a subtotal below
    1,000,000 cents earns 0.000, a subtotal of at least 1,000,000 cents but
    below 5,000,000 earns 0.015, and a subtotal of at least 5,000,000 cents
    earns 0.030."
    PRD §3.8: "Step four: `total_cents` is `subtotal_cents` minus
    `volume_rebate_cents` minus `claim_credit_cents`, floored at zero."

    Design: Difficulty/combinatorial_formula/volume_rebate_tier_keyed_on_subtotal_not_on_post_rebate_total
    """
    movement = _long_haul_invoiced_movement()
    contract = read_contract(movement["contract_id"])
    assert contract["volume_rebate_cents"] == 151_540, (
        f"5051340 * 0.030 rounded once, got {contract['volume_rebate_cents']}")
    assert contract["total_cents"] == 4_899_800
    assert contract["total_cents"] != 4_977_843, (
        "the tier must not be keyed on the post-rebate total")
    assert read_shipper(movement["shipper_id"])["outstanding_balance_cents"] == 4_899_800


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / the empty billable-line set
# ---------------------------------------------------------------------------
def test_final_variant_with_no_billable_lines_yields_zero(api):
    """PRD §3.8: "Finally, and only when at least one billable line exists, the
    contract-level floor applies: `linehaul_cents` is the greater of that sum
    and the pinned filing's `min_charge_cents`. A contract with no billable
    lines at all yields `linehaul_cents` of 0, and the minimum charge is not
    applied to it."

    Design: Difficulty/boundary_precision_check/empty_final_billable_line_set_yields_zero_without_minimum_charge
    """
    movement = setup_grain_movement(loads=(1700,), stage="UNDERWAY")
    breakdown = read_breakdown(movement["contract_id"], "FINAL")
    assert breakdown["billable_line_count"] == 0, (
        "nothing has discharged, so the final variant has no lines")
    assert breakdown["linehaul_cents"] == 0, (
        "the 250000-cent minimum charge is not applied to an empty line set")
    assert breakdown["fuel_surcharge_cents"] == 0
    assert breakdown["demurrage_cents"] == 0
    assert breakdown["subtotal_cents"] == 0
    assert breakdown["volume_rebate_cents"] == 0
    assert breakdown["total_cents"] == 0


def test_provisional_variant_on_the_same_row_already_counts_the_loaded_cut(api):
    """PRD §3.8: "Under the `PROVISIONAL` variant, the billable lines are the
    contract's assignments whose makeup `status` is `CONFIRMED`, `LOADED` or
    `DISCHARGED`, and each contributes its `loaded_tons`, the bill-of-lading
    weight."
    PRD §3.8: "The two variants read different assignment sets, different
    tonnage fields and different demurrage algorithms; they legitimately
    disagree, and the disagreement is the point — the provisional view is what
    the line expects to bill from bill-of-lading weights, and the final view is
    what it actually bills from outturn weights."

    Design: Difficulty/boundary_precision_check/empty_final_billable_line_set_yields_zero_without_minimum_charge
    """
    movement = setup_grain_movement(loads=(1700,), stage="UNDERWAY")
    breakdown = read_breakdown(movement["contract_id"], "PROVISIONAL")
    assert breakdown["billable_line_count"] == 1
    assert breakdown["linehaul_cents"] == 841_704
    assert breakdown["fuel_surcharge_cents"] == 37_877
    assert breakdown["demurrage_cents"] == 0, (
        "a cut that has not finished unloading contributes no laytime")
    assert breakdown["subtotal_cents"] == 879_581
    assert breakdown["volume_rebate_cents"] == 0
    assert breakdown["total_cents"] == 879_581


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / the shipper ledger
# ---------------------------------------------------------------------------
def test_issuing_the_invoice_posts_the_total_to_the_shipper_balance(api):
    """PRD §3.3: "`outstanding_balance_cents` is the sum of `total_cents` across
    that shipper's contracts whose `billing_status` is `INVOICED` or
    `ADJUSTED`, and `open_claim_count` is the number of cargo claims against
    that shipper's contracts whose `status` is `SUBMITTED`, `UNDER_REVIEW`,
    `INFO_REQUESTED` or `ASSESSED`."
    PRD §3.8: "It then increases the shipper's `outstanding_balance_cents` by
    `total_cents`, and if that balance now exceeds the shipper's
    `credit_limit_cents` the shipper moves `status` `ACTIVE → CREDIT_HOLD`,
    which will block that customer's next contract activation until the balance
    comes down."

    Design: Difficulty/compensating_invariant/shipper_outstanding_balance_conserved_by_invoice_then_payment
    """
    movement = setup_invoiced_movement(loads=(1700,))
    contract = read_contract(movement["contract_id"])
    shipper = read_shipper(movement["shipper_id"])
    assert contract["total_cents"] == 1_307_936
    assert shipper["outstanding_balance_cents"] == 1_307_936, (
        "the balance carries exactly the invoiced total")
    assert shipper["status"] == "ACTIVE", "the 900000000-cent limit is untouched"


def test_paying_the_invoice_in_full_returns_the_balance_to_zero(api):
    """PRD §3.8: "Payment moves the billing axis to the terminal `PAID` from
    either of its two legal predecessors and simultaneously moves the movement
    axis `DISCHARGED → CLOSED`. The shipper's `outstanding_balance_cents`
    decreases by `total_cents`, and when that leaves the balance at or below the
    `credit_limit_cents` a shipper standing in `CREDIT_HOLD` returns to
    `ACTIVE`."
    PRD §3.8: "Issue runs every charge rule in its `FINAL` form and fixes
    `linehaul_cents`, `fuel_surcharge_cents`, `fleeting_fee_cents`,
    `cleaning_fee_cents`, `demurrage_cents`, `subtotal_cents`,
    `volume_rebate_cents` and `total_cents` onto the contract, where they are
    never re-derived afterwards."

    Design: Difficulty/compensating_invariant/shipper_outstanding_balance_conserved_by_invoice_then_payment
    """
    movement = setup_invoiced_movement(loads=(1700,))
    paid = validate_success(api.mark_contract_paid(
        movement["contract_id"], {"paid_amount_cents": 1_307_936}, BILLER))
    assert paid["billing_status"] == "PAID"
    assert paid["movement_status"] == "CLOSED"

    shipper = read_shipper(movement["shipper_id"])
    assert shipper["outstanding_balance_cents"] == 0, (
        f"the balance returns to exactly its pre-invoice value, "
        f"got {shipper['outstanding_balance_cents']}")
    assert shipper["status"] == "ACTIVE"

    contract = read_contract(movement["contract_id"])
    assert contract["subtotal_cents"] == 1_327_854, "frozen at its invoice-time value"
    assert contract["volume_rebate_cents"] == 19_918
    assert contract["claim_credit_cents"] == 0


# ---------------------------------------------------------------------------
# Queue B — the minimum charge, the default variant and the billing guards
# ---------------------------------------------------------------------------
def test_minimum_charge_floor_applies_once_a_single_line_exists(api):
    """PRD §3.8: "Finally, and only when at least one billable line exists, the
    contract-level floor applies: `linehaul_cents` is the greater of that sum
    and the pinned filing's `min_charge_cents`."
    PRD §3.8: "The minimum is a floor on the total, applied strictly after the
    summation, never per line."

    Design: Corner/calculations/minimum_charge_floor_applies_once_a_single_line_exists
    """
    movement = setup_grain_movement(loads=(100,), contracted_tons=100, stage="UNDERWAY")
    breakdown = read_breakdown(movement["contract_id"], "PROVISIONAL")
    assert breakdown["billable_line_count"] == 1
    assert breakdown["linehaul_cents"] == 250_000, (
        f"the raw 49512 is lifted to the minimum charge, "
        f"got {breakdown['linehaul_cents']}")
    assert breakdown["fuel_surcharge_cents"] == 11_250, (
        "the surcharge rides on the floored figure")
    assert breakdown["demurrage_cents"] == 0
    assert breakdown["subtotal_cents"] == 261_250
    assert breakdown["volume_rebate_cents"] == 0
    assert breakdown["total_cents"] == 261_250


def test_charge_breakdown_defaults_to_the_provisional_variant(api):
    """PRD §3.8: "It accepts an optional `variant` selecting `PROVISIONAL` or
    `FINAL`, defaulting to `PROVISIONAL` when omitted, and it answers with a
    payload carrying `variant`, `billable_line_count`, `linehaul_cents`,
    `fuel_surcharge_cents`, `fleeting_fee_cents`, `cleaning_fee_cents`,
    `demurrage_cents`, `subtotal_cents`, `volume_rebate_cents`,
    `claim_credit_cents` and `total_cents`."
    PRD §3.8: "That read is a pure computation: nothing is persisted and no
    `version` anywhere is incremented."

    Design: Corner/endpoints/charge_breakdown_defaults_to_provisional_when_variant_is_omitted
    """
    movement = setup_grain_movement(loads=(1700,), stage="UNDERWAY")
    before = read_contract(movement["contract_id"])

    breakdown = read_breakdown(movement["contract_id"])
    assert_charge_breakdown_shape(breakdown, "PROVISIONAL")
    assert breakdown["billable_line_count"] == 1
    assert breakdown["linehaul_cents"] == 841_704
    assert breakdown["fuel_surcharge_cents"] == 37_877
    assert breakdown["demurrage_cents"] == 0
    assert breakdown["subtotal_cents"] == 879_581
    assert breakdown["volume_rebate_cents"] == 0
    assert breakdown["claim_credit_cents"] == 0
    assert breakdown["total_cents"] == 879_581

    after = read_contract(movement["contract_id"])
    assert after["version"] == before["version"], "the read persists nothing"
    for field in FROZEN_BUCKETS:
        assert after[field] == before[field], f"the read must not write {field}"


def test_billing_guards_reject_a_progress_bill_a_double_bill_and_a_short_payment(api):
    """PRD §3.8: "It requires that the contract's `billing_status` stand in
    `NOT_BILLED`, failing which it is refused with
    `ERR_CONTRACT_BILLING_INVALID_STATE`; that the contract's `movement_status`
    be `IN_TRANSIT` or `DISCHARGED`, failing which it is refused with
    `ERR_CONTRACT_MOVEMENT_INVALID_STATE`; that `expected_shipper_version` match
    the shipper's current `version` as described in §2.8; and that at least one
    assignment of the contract have a `discharge_status` of `COMPLETED` or
    `DISPUTED`, failing which it is refused with `ERR_NO_BILLABLE_LINES`."
    PRD §3.8: "It supplies `paid_amount_cents`, which must equal the contract's
    `total_cents` exactly — partial and over payments alike are refused with
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/billing_guards_reject_progress_bill_without_lines_double_invoice_and_wrong_payment
    """
    movement = setup_grain_movement(loads=(1700,), stage="ARRIVED")
    contract_id = movement["contract_id"]
    shipper_id = movement["shipper_id"]

    validate_error(api.issue_invoice(
        contract_id, {"expected_shipper_version": read_shipper(shipper_id)["version"]},
        BILLER),
        ApiErrorId.ERR_NO_BILLABLE_LINES.value)
    assert read_contract(contract_id)["billing_status"] == "NOT_BILLED"

    discharge_assignment(movement["assignments"][0]["id"], STANDARD_DISCHARGES[0])
    issued = issue_invoice(contract_id, shipper_id)
    assert issued["total_cents"] == 1_307_936
    assert issued["billing_status"] == "INVOICED"

    validate_error(api.issue_invoice(
        contract_id, {"expected_shipper_version": read_shipper(shipper_id)["version"]},
        BILLER),
        ApiErrorId.ERR_CONTRACT_BILLING_INVALID_STATE.value)

    validate_error(api.mark_contract_paid(
        contract_id, {"paid_amount_cents": 1_307_935}, BILLER),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)

    shipper = read_shipper(shipper_id)
    assert shipper["outstanding_balance_cents"] == 1_307_936, (
        "neither refused call moved the ledger")
    contract = read_contract(contract_id)
    assert contract["billing_status"] == "INVOICED"
    assert contract["movement_status"] == "DISCHARGED"


def test_second_invoice_for_the_same_shipper_with_a_stale_version_is_refused(api):
    """PRD §2.8: "**Issuing an invoice** requires `expected_shipper_version`,
    carrying the `version` of the `Shipper` row that owns the contract as the
    biller last read it."
    PRD §2.8: "Issuing an invoice moves the shipper's outstanding balance and
    may put the account on credit hold, so if another contract of the same
    shipper has been invoiced, paid, or credited by an approved claim since that
    read, the stored `version` no longer matches and the issue is rejected with
    `ERR_STALE_SHIPPER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/second_invoice_for_the_same_shipper_with_stale_version_returns_412
    """
    reference = setup_grain_reference()
    first_hull = create_barge(hull_number="BL-1001")
    second_hull = create_barge(hull_number="BL-1002")
    contract_a = create_active_contract(reference["shipper_id"],
                                        reference["commodity_id"], contracted_tons=1700)
    contract_b = create_active_contract(reference["shipper_id"],
                                        reference["commodity_id"], contracted_tons=1650)
    tow = create_tow(towboat_name="M/V Uniform")
    first_cut = add_assignment(tow["id"], first_hull["id"], contract_a["id"],
                               loaded_tons=1700, cut_position=1)
    second_cut = add_assignment(tow["id"], second_hull["id"], contract_b["id"],
                                loaded_tons=1650, cut_position=2)
    seal_tow(tow["id"])
    depart_tow(tow["id"])
    arrive_tow(tow["id"])
    discharge_assignment(first_cut["id"], STANDARD_DISCHARGES[0])
    discharge_assignment(second_cut["id"], STANDARD_DISCHARGES[1])

    observed_version = read_shipper(reference["shipper_id"])["version"]
    issue_invoice(contract_a["id"], reference["shipper_id"],
                  expected_shipper_version=observed_version)

    validate_error(api.issue_invoice(
        contract_b["id"], {"expected_shipper_version": observed_version}, BILLER),
        ApiErrorId.ERR_STALE_SHIPPER_VERSION.value)
    assert read_contract(contract_b["id"])["billing_status"] == "NOT_BILLED"
    assert read_shipper(reference["shipper_id"])["outstanding_balance_cents"] == 1_307_936
    assert read_contract(contract_a["id"])["total_cents"] == 1_307_936

    issued = issue_invoice(contract_b["id"], reference["shipper_id"])
    assert issued["billing_status"] == "INVOICED"
    assert issued["linehaul_cents"] == 813_482
    assert issued["fuel_surcharge_cents"] == 36_607
    assert issued["demurrage_cents"] == 65_000
    assert issued["subtotal_cents"] == 915_089
    assert issued["volume_rebate_cents"] == 0
    assert issued["total_cents"] == 915_089
    assert read_shipper(reference["shipper_id"])["outstanding_balance_cents"] == 2_223_025
