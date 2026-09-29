"""Composite money formulas whose evaluation order is part of the answer.

Two arithmetic chains are exercised here.  A renewal invoice rounds each of its
four components to the cent on its own and only then adds them up, which lands a
cent above the reading that adds at full precision and rounds once; the payment
gate then charges the repriced figure rather than the provisional one.  A bond's
three money steps run base premium, then ceiling from that base, then annual
premium loading a fraction of the ceiling, so the ceiling can never be
re-derived from the annual figure.
"""

from test_helpers import (
    BOND_ACTIVE,
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_WOOD_TO_GROUND,
    ERR_PAYMENT_INSUFFICIENT,
    MANAGER_HEADERS,
    RENEWAL_PAID,
    RENEWAL_PENDING,
    TIER_REPAIR_AND_RETREAT,
    TIER_RETREAT_ONLY,
    assert_bond_money,
    assert_money,
    assert_renewal_invoice,
    assert_repair_liability_conserved,
    assert_status,
    bonded_property,
    complete_renewal,
    conducive_finding_payload,
    open_renewal,
    renewal_completion_payload,
    renewal_graph,
    set_clock,
    validate_error,
    validate_success,
)

# --- the shared structure and its bond ----------------------------------------
#
# One FL slab of 2000 heated square feet and 180 linear feet, treated with a
# liquid barrier and bonded on 2026-09-01, so the first term ends 2027-09-01 and
# the renewal window opens 2027-07-03.

CLOCK_START = "2026-08-01T00:00:00Z"
BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"

QUOTED_PRICE_USD = 1080.00
TARGET_GALLONS = 190
BASE_PREMIUM_USD = 194.40
REPAIR_CAP_USD = 11664.00
REPAIR_ANNUAL_PREMIUM_USD = 241.06
RETREAT_CAP_USD = 0.00
RETREAT_ANNUAL_PREMIUM_USD = 194.40
CAP_REDERIVED_FROM_ANNUAL_USD = 14463.60

FIRST_TERM_END = "2027-09-01"
FIRST_WINDOW_OPENS_ON = "2027-07-03"

# --- the renewal invoice ------------------------------------------------------
#
# Opened 2027-08-20 and completed 2027-09-04, three whole UTC days past the term
# end and well inside the 30-day grace.  The renewal graph carries two
# conducive-condition rows.

RENEWAL_OPEN_INSTANT = "2027-08-20T09:00:00Z"
RENEWAL_COMPLETE_INSTANT = "2027-09-04T00:00:00Z"

BASE_RENEWAL_FEE_USD = 83.17
INSPECTION_FEE_USD = 128.10
CONDUCIVE_SURCHARGE_USD = 14.67
LATE_FEE_USD = 1.25
PROVISIONAL_TOTAL_USD = 211.27
FINAL_TOTAL_USD = 227.19
SINGLE_ROUNDING_TOTAL_USD = 227.18

ROLLED_TERM_START = "2027-09-01"
ROLLED_TERM_END = "2028-08-31"
ROLLED_WINDOW_OPENS_ON = "2028-07-02"


def _bonded_chain(api, coverage_tier=TIER_REPAIR_AND_RETREAT):
    """A clean FL slab carried all the way to an ACTIVE bond issued 2026-09-01."""
    set_clock(api, CLOCK_START)
    return bonded_property(
        api, state_code="FL", coverage_tier=coverage_tier, issue_instant=BOND_ISSUE_INSTANT
    )


def _pending_invoice(api, chain):
    """Open a PENDING invoice inside the renewal window."""
    set_clock(api, RENEWAL_OPEN_INSTANT)
    return open_renewal(api, chain["bond"]["id"])


def _renewal_graph_with_two_conducive_rows(api, chain):
    """A signed RENEWAL graph carrying exactly two conducive-condition rows."""
    return renewal_graph(
        api,
        chain["property"]["id"],
        chain["inspector"]["id"],
        chain["inspection"]["id"],
        findings=[
            conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE, severity=2),
            conducive_finding_payload("B3", CONDUCIVE_WOOD_TO_GROUND, severity=1),
        ],
    )


def _invoice_ready_to_pay(api):
    """A bonded structure, a PENDING invoice, a renewal graph and a late clock."""
    chain = _bonded_chain(api)
    invoice = _pending_invoice(api, chain)
    graph = _renewal_graph_with_two_conducive_rows(api, chain)
    set_clock(api, RENEWAL_COMPLETE_INSTANT)
    return chain, invoice, graph


def test_provisional_invoice_prices_only_the_first_two_components(api):
    """A freshly opened invoice charges the premium share and the area fee alone.

    PRD 3.8: "`base_renewal_fee_usd` is the bond's `annual_premium_usd`
    multiplied by 0.345. `inspection_fee_usd` is a flat 85.00 plus 2.155 for each
    100 square feet of heated area... At creation `conducive_surcharge_usd` and
    `late_fee_usd` are both forced to 0.00, because no renewal graph has been
    attached yet and nothing is past due yet."

    Design: Difficulty/combinatorial_formula/renewal_invoice_round_each_component_then_sum
    """
    chain = _bonded_chain(api)
    assert_money(chain["bond"]["annual_premium_usd"], REPAIR_ANNUAL_PREMIUM_USD)
    assert chain["bond"]["current_term_end"] == FIRST_TERM_END
    assert chain["bond"]["renewal_window_opens_on"] == FIRST_WINDOW_OPENS_ON

    invoice = _pending_invoice(api, chain)

    assert_status(invoice, RENEWAL_PENDING, "renewal")
    assert invoice["term_index"] == 1
    assert invoice["due_on"] == FIRST_TERM_END
    assert_renewal_invoice(
        invoice,
        base_renewal_fee_usd=BASE_RENEWAL_FEE_USD,
        inspection_fee_usd=INSPECTION_FEE_USD,
        conducive_surcharge_usd=0.00,
        late_fee_usd=0.00,
        invoice_total_usd=PROVISIONAL_TOTAL_USD,
    )


def test_completion_reprices_the_conducive_and_late_components(api):
    """Paying the invoice recomputes two components and sums four rounded cents figures.

    PRD 3.8: "`conducive_surcharge_usd` becomes 7.335 for each conducive-condition
    notation on the attached renewal graph... `late_fee_usd` becomes 0.415 for
    each whole UTC day by which the clock's date has passed the bond's
    `current_term_end`... and `invoice_total_usd` is again the exact sum of the
    four rounded components."

    Design: Difficulty/combinatorial_formula/renewal_invoice_round_each_component_then_sum
    """
    _chain, invoice, graph = _invoice_ready_to_pay(api)

    paid = complete_renewal(api, invoice["id"], graph["id"], FINAL_TOTAL_USD)

    assert_status(paid, RENEWAL_PAID, "renewal")
    assert paid["inspection_id"] == graph["id"]
    assert_renewal_invoice(
        paid,
        base_renewal_fee_usd=BASE_RENEWAL_FEE_USD,
        inspection_fee_usd=INSPECTION_FEE_USD,
        conducive_surcharge_usd=CONDUCIVE_SURCHARGE_USD,
        late_fee_usd=LATE_FEE_USD,
        invoice_total_usd=FINAL_TOTAL_USD,
    )
    assert_money(paid["amount_paid_usd"], FINAL_TOTAL_USD)


def test_payment_gate_charges_the_repriced_total_not_the_provisional_one(api):
    """The provisional figure stored at creation no longer buys the renewal.

    PRD 3.8: "The payment check compares `amount_usd` against **this** recomputed
    total, not the provisional figure stored earlier; a shortfall is
    `ERR_PAYMENT_INSUFFICIENT`."

    Design: Difficulty/combinatorial_formula/renewal_invoice_round_each_component_then_sum
    """
    _chain, invoice, graph = _invoice_ready_to_pay(api)
    assert_money(invoice["invoice_total_usd"], PROVISIONAL_TOTAL_USD)

    refused = api.complete_renewal(
        invoice["id"],
        renewal_completion_payload(graph["id"], PROVISIONAL_TOTAL_USD),
        MANAGER_HEADERS,
    )
    validate_error(refused, ERR_PAYMENT_INSUFFICIENT)

    still_pending = validate_success(api.get_renewal(invoice["id"], MANAGER_HEADERS))
    assert_status(still_pending, RENEWAL_PENDING, "renewal")

    paid = complete_renewal(api, invoice["id"], graph["id"], FINAL_TOTAL_USD)
    assert_status(paid, RENEWAL_PAID, "renewal")
    assert FINAL_TOTAL_USD > PROVISIONAL_TOTAL_USD


def test_a_total_summed_at_full_precision_is_one_cent_short(api):
    """Adding the components before rounding underpays the invoice by a cent.

    PRD 3.8: "Rounding each component before summing, rather than summing at full
    precision and rounding once, is mandatory: the two orders differ by a cent on
    many inputs, and only the first is correct."

    Design: Difficulty/combinatorial_formula/renewal_invoice_round_each_component_then_sum
    """
    _chain, invoice, graph = _invoice_ready_to_pay(api)

    refused = api.complete_renewal(
        invoice["id"],
        renewal_completion_payload(graph["id"], SINGLE_ROUNDING_TOTAL_USD),
        MANAGER_HEADERS,
    )
    validate_error(refused, ERR_PAYMENT_INSUFFICIENT)

    paid = complete_renewal(api, invoice["id"], graph["id"], FINAL_TOTAL_USD)
    assert_status(paid, RENEWAL_PAID, "renewal")
    assert_money(paid["invoice_total_usd"], FINAL_TOTAL_USD)
    assert paid["invoice_total_usd"] != SINGLE_ROUNDING_TOTAL_USD


def test_paid_invoice_rolls_the_bond_coverage_window_forward(api):
    """Payment carries the bond into its next term without leaving ACTIVE.

    PRD 3.8: "`current_term_start` becomes the previous `current_term_end`,
    `current_term_end` becomes the previous `current_term_end` plus 365 days,
    `renewal_window_opens_on` becomes 60 days before the new term end, and
    `term_index` rises by one."

    Design: Difficulty/combinatorial_formula/renewal_invoice_round_each_component_then_sum
    """
    chain, invoice, graph = _invoice_ready_to_pay(api)
    assert chain["bond"]["term_index"] == 1

    complete_renewal(api, invoice["id"], graph["id"], FINAL_TOTAL_USD)

    rolled = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_status(rolled, BOND_ACTIVE, "bond")
    assert rolled["term_index"] == 2
    assert rolled["current_term_start"] == ROLLED_TERM_START
    assert rolled["current_term_end"] == ROLLED_TERM_END
    assert rolled["renewal_window_opens_on"] == ROLLED_WINDOW_OPENS_ON
    assert_money(rolled["annual_premium_usd"], REPAIR_ANNUAL_PREMIUM_USD)


def test_repair_ceiling_is_a_multiple_of_the_base_premium_only(api):
    """The ceiling comes off the base premium, and the annual figure loads it afterwards.

    PRD 3.7: "`repair_liability_cap_usd` is `base_premium_usd` multiplied by the
    tier's cap multiplier... For `REPAIR_AND_RETREAT` it is 60, so the ceiling is
    sixty times the base premium... `annual_premium_usd` is `base_premium_usd`
    plus a cap loading of 0.004 -- four tenths of one percent -- of
    `repair_liability_cap_usd`, the sum rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/bond_premium_and_cap_pinned_step_order
    """
    chain = _bonded_chain(api, coverage_tier=TIER_REPAIR_AND_RETREAT)

    assert_money(chain["plan"]["quoted_price_usd"], QUOTED_PRICE_USD)
    assert chain["plan"]["target_gallons"] == TARGET_GALLONS

    bond = chain["bond"]
    assert bond["coverage_tier"] == TIER_REPAIR_AND_RETREAT
    assert_bond_money(
        bond,
        base_premium_usd=BASE_PREMIUM_USD,
        repair_liability_cap_usd=REPAIR_CAP_USD,
        annual_premium_usd=REPAIR_ANNUAL_PREMIUM_USD,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=REPAIR_CAP_USD,
    )
    assert bond["repair_liability_cap_usd"] != CAP_REDERIVED_FROM_ANNUAL_USD
    assert_repair_liability_conserved(bond)


def test_retreat_only_tier_zeroes_the_ceiling_and_its_loading(api):
    """A labour-only bond has no ceiling, so its annual premium is the bare base.

    PRD 3.7: "For `RETREAT_ONLY` that multiplier is zero, so the ceiling is 0.00
    and the bond carries no monetary repair liability at all."

    Design: Difficulty/combinatorial_formula/bond_premium_and_cap_pinned_step_order
    """
    chain = _bonded_chain(api, coverage_tier=TIER_RETREAT_ONLY)

    assert_money(chain["plan"]["quoted_price_usd"], QUOTED_PRICE_USD)
    assert chain["plan"]["target_gallons"] == TARGET_GALLONS

    bond = chain["bond"]
    assert bond["coverage_tier"] == TIER_RETREAT_ONLY
    assert_bond_money(
        bond,
        base_premium_usd=BASE_PREMIUM_USD,
        repair_liability_cap_usd=RETREAT_CAP_USD,
        annual_premium_usd=RETREAT_ANNUAL_PREMIUM_USD,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=RETREAT_CAP_USD,
    )
    assert_money(bond["annual_premium_usd"], bond["base_premium_usd"])
    assert_repair_liability_conserved(bond)


def test_coverage_tier_is_the_only_input_that_moves_the_annual_premium(api):
    """Two bonds off identical 1080.00 quotes differ only where the loading enters.

    PRD 3.7: "Its money is computed here and frozen for the life of the bond, in
    three ordered steps that must not be reordered."

    Design: Difficulty/combinatorial_formula/bond_premium_and_cap_pinned_step_order
    """
    repair_chain = _bonded_chain(api, coverage_tier=TIER_REPAIR_AND_RETREAT)
    retreat_chain = _bonded_chain(api, coverage_tier=TIER_RETREAT_ONLY)

    repair_bond = repair_chain["bond"]
    retreat_bond = retreat_chain["bond"]

    assert_money(
        repair_chain["plan"]["quoted_price_usd"],
        retreat_chain["plan"]["quoted_price_usd"],
    )
    assert_money(repair_bond["base_premium_usd"], retreat_bond["base_premium_usd"])
    assert repair_bond["coverage_tier"] != retreat_bond["coverage_tier"]

    assert_money(repair_bond["repair_liability_cap_usd"], REPAIR_CAP_USD)
    assert_money(retreat_bond["repair_liability_cap_usd"], RETREAT_CAP_USD)
    assert_money(repair_bond["annual_premium_usd"], REPAIR_ANNUAL_PREMIUM_USD)
    assert_money(retreat_bond["annual_premium_usd"], RETREAT_ANNUAL_PREMIUM_USD)
    assert repair_bond["annual_premium_usd"] > retreat_bond["annual_premium_usd"]
    assert_repair_liability_conserved(repair_bond)
    assert_repair_liability_conserved(retreat_bond)
