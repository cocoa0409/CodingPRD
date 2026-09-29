"""Queue A - rule ``combinatorial_formula``.

Three instances, each pinning a multi-stage arithmetic pipeline end to end and
naming the wrong answer the obvious shortcut would produce.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_charge_money_invariant,
    assert_end_of_day,
    assert_instant_eq,
    assert_invoice_money_invariant,
    assert_subset_equal,
)
from test_helpers.constants import (
    AGREEMENT_MONTH,
    AGREEMENT_OPEN,
    BILLING_ADJUSTED,
    CHARGE_ADJUSTED,
    CHARGE_FINAL,
    CYCLE_A_CONSTRUCTIVE_AT,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_NOTICE_SENT_AT,
    DECISION_PARTIALLY_ALLOWED,
    DISPUTE_SUBMITTED,
    DUE_AT_BASE_20_MULT_1_00_WEIGHT_3,
    DUE_AT_BASE_20_MULT_1_50_WEIGHT_CAPPED,
    EVIDENCE_GATE_LOG,
    EVIDENCE_SWITCH_LIST,
    EVIDENCE_TRACK_EMBARGO_NOTICE,
    GROUNDS_RAILROAD_CAUSED_DELAY,
    GROUNDS_RATE_UNREASONABLE,
    INVOICE_ADJUSTED,
    INVOICE_PARTIALLY_DISPUTED,
    SCOPE_SINGLE_CHARGE,
    TWO_LINE_ALLOWANCE_PCT,
    TWO_LINE_CREDIT_ROUND_THE_SUM,
    TWO_LINE_CREDIT_TOTAL,
    TWO_LINE_GROSS_TOTAL,
    TWO_LINE_NET_TOTAL,
    TWO_LINE_PER_LINE_CREDIT,
)

# --- instance 4 literals ---------------------------------------------------
UNBOUND_CLAIM_CENTS = 60000  # above the 39066 the allowance produces
BINDING_CLAIM_CENTS = 39000  # below it, so the backwards waterfall runs
WATERFALL_EXCESS_CENTS = 66  # 39066 - 39000, taken off the last line only

# --- instance 5 literals ---------------------------------------------------
CYCLE_P_ACTUAL_AT = "2026-08-04T10:00:00.000Z"
CYCLE_P_RELEASE_AT = "2026-08-04T15:00:00.000Z"
CYCLE_P_EARLY_RELEASE_DAYS = 2
LEDGER_CREDIT_DAYS_EARNED = 2
LEDGER_DEBIT_DAYS_INCURRED = 3
LEDGER_NET_DAYS = -1
UNCAPPED_CREDIT_CENTS = 35000  # 22450 + 12550, most expensive day first
FIRST_DAY_FIRST_CREDIT_CENTS = 25100  # 12550 + 12550, the wrong waterfall
CAPPED_CREDIT_CENTS = 14265  # FLOOR(47550 * 0.30)
CAPPED_NET_CENTS = 33285
UNCAPPED_NET_CENTS = 12550
CREDIT_CAP_RATIO_DEFAULT = 0.30
CREDIT_CAP_RATIO_UNBOUND = 1.00

# --- instance 6 literals ---------------------------------------------------
CLOCK_AT_SUBMIT_TEN_HUNDRED = "2026-08-15T10:00:00.000Z"
WEIGHT_TEN_TYPES = (
    EVIDENCE_SWITCH_LIST,
    EVIDENCE_GATE_LOG,
    EVIDENCE_TRACK_EMBARGO_NOTICE,
)  # 3 + 3 + 4
EVIDENCE_WEIGHT_TEN = 10
EVIDENCE_WEIGHT_THREE = 3
WRONG_DUE_AT_CALENDAR_WALK = "2026-09-09T23:59:59.999Z"
WRONG_DUE_AT_TEN_BUSINESS_DATES = "2026-09-03T23:59:59.999Z"


# ===========================================================================
# instance: dispute_credit_per_line_round_half_up_beats_sum_then_round
# ===========================================================================
def test_partial_allowance_rounds_half_up_per_line_and_then_sums(api):
    """65 per cent of 47550 and 12550 is 39066 cents, never 39065.

    PRD 3.8: "Second, compute the raw credit **per line and then sum**, which as
    §2.6 warns is not the same number as rounding the sum: each line's credit is
    its `gross_amount_cents` times `allowance_pct` rounded half-up to a whole
    cent, then reduced to its own gross if it somehow exceeded it, and the total
    is the sum of those per-line figures."

    Design: Difficulty/combinatorial_formula/dispute_credit_per_line_round_half_up_beats_sum_then_round
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(api, world)
    assert invoice["total_gross_cents"] == TWO_LINE_GROSS_TOTAL

    decided = fx.decided_dispute(
        api,
        invoice,
        world["customer_id"],
        UNBOUND_CLAIM_CENTS,
        "adj-perline-a",
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
    )

    assert decided["decision"] == DECISION_PARTIALLY_ALLOWED
    assert decided["allowed_credit_cents"] == TWO_LINE_CREDIT_TOTAL
    assert decided["allowed_credit_cents"] != TWO_LINE_CREDIT_ROUND_THE_SUM

    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    charge_b = fx.charge_of_cycle(api, cycle_b["id"])
    assert_subset_equal(
        charge_a,
        {
            "status": CHARGE_ADJUSTED,
            "credit_applied_cents": TWO_LINE_PER_LINE_CREDIT[0],
            "net_amount_cents": 16642,
        },
    )
    assert_subset_equal(
        charge_b,
        {
            "status": CHARGE_ADJUSTED,
            "credit_applied_cents": TWO_LINE_PER_LINE_CREDIT[1],
            "net_amount_cents": 4392,
        },
    )
    assert_charge_money_invariant(charge_a)
    assert_charge_money_invariant(charge_b)
    assert (
        charge_a["credit_applied_cents"] + charge_b["credit_applied_cents"]
        == TWO_LINE_CREDIT_TOTAL
    )

    rolled_up = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        rolled_up,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": TWO_LINE_GROSS_TOTAL,
            "total_credit_cents": TWO_LINE_CREDIT_TOTAL,
            "total_net_cents": TWO_LINE_NET_TOTAL,
        },
    )
    assert_invoice_money_invariant(rolled_up)

    for cycle in (cycle_a, cycle_b):
        assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_ADJUSTED


def test_claim_ceiling_waterfalls_backwards_from_the_last_released_line(api):
    """A claim of 39000 clips only the later-released line, by exactly 66 cents.

    PRD 3.8: "Third, enforce the consignee's own `claimed_credit_cents` ceiling
    with a **backwards** waterfall: if the total exceeds the claim, take the
    excess off the last line in the resolved order first, then the
    second-to-last, and so on until the excess is exhausted, so the
    earliest-released line keeps its credit intact and the total lands exactly on
    the claim."

    Design: Difficulty/combinatorial_formula/dispute_credit_per_line_round_half_up_beats_sum_then_round
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(api, world)
    # The resolved order is the cycles' released_at ascending: A then B.
    assert cycle_a["released_at"] < cycle_b["released_at"]

    decided = fx.decided_dispute(
        api,
        invoice,
        world["customer_id"],
        BINDING_CLAIM_CENTS,
        "adj-perline-b",
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
    )
    assert decided["allowed_credit_cents"] == BINDING_CLAIM_CENTS

    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    charge_b = fx.charge_of_cycle(api, cycle_b["id"])
    # The earliest-released line keeps its whole per-line figure.
    assert charge_a["credit_applied_cents"] == TWO_LINE_PER_LINE_CREDIT[0]
    assert (
        charge_b["credit_applied_cents"]
        == TWO_LINE_PER_LINE_CREDIT[1] - WATERFALL_EXCESS_CENTS
    )
    assert (
        charge_a["credit_applied_cents"] + charge_b["credit_applied_cents"]
        == BINDING_CLAIM_CENTS
    )
    assert_charge_money_invariant(charge_a)
    assert_charge_money_invariant(charge_b)

    rolled_up = fx.get_invoice(api, invoice["id"])
    assert rolled_up["total_gross_cents"] == TWO_LINE_GROSS_TOTAL
    assert rolled_up["total_credit_cents"] == BINDING_CLAIM_CENTS
    assert rolled_up["total_net_cents"] == TWO_LINE_GROSS_TOTAL - BINDING_CLAIM_CENTS
    assert_invoice_money_invariant(rolled_up)


def _agreement_month_world(api, credit_cap_ratio):
    """One early release, one late release, and an OPEN agreement over the month.

    Cycle P is released the same day it is spotted and hands 2 free dates back;
    Cycle A runs 3 chargeable days for 47550 cents.  Both cycles sit at the same
    industry track, and P is built first so that its release instant never
    overtakes A's later actual placement in the PRD 3.4 switch-buffer guard.
    """
    world = fx.reference_world(api)
    agreement = fx.open_agreement(
        api,
        world["customer_id"],
        agreement_month=AGREEMENT_MONTH,
        credit_cap_ratio=credit_cap_ratio,
    )
    cycle_p = fx.released_cycle(
        api,
        world,
        constructive_at=CYCLE_A_CONSTRUCTIVE_AT,
        sent_at=CYCLE_A_NOTICE_SENT_AT,
        actual_at=CYCLE_P_ACTUAL_AT,
        released_at=CYCLE_P_RELEASE_AT,
    )
    cycle_a = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    return world, agreement, cycle_p, cycle_a, invoice


# ===========================================================================
# instance: average_agreement_credit_stages_with_floor_cap_on_gross
# ===========================================================================
def test_agreement_credit_spends_the_dearest_days_then_floors_at_the_cap(api):
    """Two spendable days buy 22450 + 12550, and the 30 per cent cap floors it.

    PRD 3.7: "Sixth, apply the contractual ceiling, which uses **floor** and not
    rounding: the cap is the month's gross multiplied by `credit_cap_ratio`,
    truncated to a whole cent."

    Design: Difficulty/combinatorial_formula/average_agreement_credit_stages_with_floor_cap_on_gross
    """
    world, agreement, cycle_p, cycle_a, invoice = _agreement_month_world(
        api, CREDIT_CAP_RATIO_DEFAULT
    )

    assert cycle_p["chargeable_days"] == 0
    assert cycle_p["early_release_days"] == CYCLE_P_EARLY_RELEASE_DAYS
    assert cycle_a["chargeable_days"] == 3
    assert cycle_a["early_release_days"] == 0

    settled = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert_subset_equal(
        settled,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": LEDGER_CREDIT_DAYS_EARNED,
            "debit_days_incurred": LEDGER_DEBIT_DAYS_INCURRED,
            "net_days": LEDGER_NET_DAYS,
            "agreement_credit_cents": CAPPED_CREDIT_CENTS,
        },
    )
    # The uncapped figure and the first-day-first figure are both wrong here.
    assert settled["agreement_credit_cents"] != UNCAPPED_CREDIT_CENTS
    assert settled["agreement_credit_cents"] != FIRST_DAY_FIRST_CREDIT_CENTS

    assert_subset_equal(
        invoice,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "agreement_credit_cents": CAPPED_CREDIT_CENTS,
            "total_credit_cents": CAPPED_CREDIT_CENTS,
            "total_net_cents": CAPPED_NET_CENTS,
        },
    )
    assert_invoice_money_invariant(invoice)

    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    assert_subset_equal(
        charge_a,
        {
            "status": CHARGE_FINAL,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
            "credit_applied_cents": CAPPED_CREDIT_CENTS,
            "net_amount_cents": CAPPED_NET_CENTS,
        },
    )
    assert_charge_money_invariant(charge_a)

    charge_p = fx.charge_of_cycle(api, cycle_p["id"])
    assert charge_p["gross_amount_cents"] == 0
    assert charge_p["credit_applied_cents"] == 0


def test_agreement_credit_without_a_binding_cap_is_the_dearest_days_first(api):
    """At a cap ratio of 1.00 the raw most-expensive-first sum survives.

    PRD 3.7: "Fifth, spend those days on the **most expensive days first**. Build
    one entry for every billable day across every attached charge line, tagging
    each entry with that day's rate taken from the per-day rate vector of §3.6,
    then sort the entries by rate descending, breaking ties by the owning charge
    line's `created_at` ascending and then by the day position within the line
    ascending, and take as many entries from the front as there are spendable
    credit days."

    Design: Difficulty/combinatorial_formula/average_agreement_credit_stages_with_floor_cap_on_gross
    """
    world, agreement, _cycle_p, cycle_a, invoice = _agreement_month_world(
        api, CREDIT_CAP_RATIO_UNBOUND
    )

    settled = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert settled["credit_days_earned"] == LEDGER_CREDIT_DAYS_EARNED
    assert settled["debit_days_incurred"] == LEDGER_DEBIT_DAYS_INCURRED
    assert settled["agreement_credit_cents"] == UNCAPPED_CREDIT_CENTS
    # A first-day-first waterfall would have spent two tier-one days instead.
    assert settled["agreement_credit_cents"] != FIRST_DAY_FIRST_CREDIT_CENTS

    assert invoice["agreement_credit_cents"] == UNCAPPED_CREDIT_CENTS
    assert invoice["total_gross_cents"] == CYCLE_A_GROSS_CENTS
    assert invoice["total_credit_cents"] == UNCAPPED_CREDIT_CENTS
    assert invoice["total_net_cents"] == UNCAPPED_NET_CENTS
    assert_invoice_money_invariant(invoice)

    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    assert charge_a["credit_applied_cents"] == UNCAPPED_CREDIT_CENTS
    assert charge_a["net_amount_cents"] == UNCAPPED_NET_CENTS
    assert_charge_money_invariant(charge_a)


def _single_charge_dispute(api, world, invoice, charge, grounds, evidence_types):
    """Submit one SINGLE_CHARGE dispute against one line of the two-line invoice.

    Each line is disputed by its own filing, because PRD 3.8 requires every
    target charge to be ``FINAL`` at submission and the first submission takes
    its own target to ``DISPUTED``.
    """
    return fx.submitted_dispute(
        api,
        invoice,
        world["customer_id"],
        charge["gross_amount_cents"],
        CLOCK_AT_SUBMIT_TEN_HUNDRED,
        list(evidence_types),
        scope=SCOPE_SINGLE_CHARGE,
        grounds=grounds,
        demurrage_charge_id=charge["id"],
    )


# ===========================================================================
# instance: adjudication_due_date_from_grounds_multiplier_and_evidence_weight
# ===========================================================================
def test_due_date_multiplies_before_subtracting_the_capped_evidence_credit(api):
    """20 x 1.50 ceils to 30, less the 5-day evidence cap, is 25 business dates.

    PRD 3.8: "On the first round, take the base times the multiplier and round it
    **up** to a whole day, then subtract the evidence credit, which is the
    evidence weight halved and rounded **down** and then capped at 5 days; the
    allowance is the larger of that result and a floor of 5 days."

    Design: Difficulty/combinatorial_formula/adjudication_due_date_from_grounds_multiplier_and_evidence_weight
    """
    world = fx.reference_world(api)
    cycle_a, _cycle_b, invoice = fx.two_line_invoice(api, world)
    charge_a = fx.charge_of_cycle(api, cycle_a["id"])

    dispute = _single_charge_dispute(
        api, world, invoice, charge_a, GROUNDS_RATE_UNREASONABLE, WEIGHT_TEN_TYPES
    )

    assert dispute["status"] == DISPUTE_SUBMITTED
    assert dispute["grounds"] == GROUNDS_RATE_UNREASONABLE
    assert dispute["evidence_weight"] == EVIDENCE_WEIGHT_TEN
    assert dispute["target_charge_count"] == 1
    assert_instant_eq(
        dispute["submitted_at"], CLOCK_AT_SUBMIT_TEN_HUNDRED, "submitted_at"
    )
    assert_end_of_day(dispute["adjudication_due_at"], "adjudication_due_at")
    assert_instant_eq(
        dispute["adjudication_due_at"],
        DUE_AT_BASE_20_MULT_1_50_WEIGHT_CAPPED,
        "adjudication_due_at",
    )
    assert dispute["adjudication_due_at"] != WRONG_DUE_AT_CALENDAR_WALK
    assert dispute["adjudication_due_at"] != WRONG_DUE_AT_TEN_BUSINESS_DATES


def test_due_date_at_multiplier_one_halves_a_weight_of_three_down_to_one(api):
    """20 x 1.00 less FLOOR(3 / 2) is 19 business dates, and the invoice sees both.

    PRD 3.8: "The deadline itself is the last millisecond of the allowance-th
    **business date** - Monday through Friday, unconditionally, and never the
    tariff's `weekend_excluded` calendar - counted forward from the date of
    `submitted_at`, at `23:59:59.999Z`."

    Design: Difficulty/combinatorial_formula/adjudication_due_date_from_grounds_multiplier_and_evidence_weight
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(api, world)
    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    charge_b = fx.charge_of_cycle(api, cycle_b["id"])

    first = _single_charge_dispute(
        api, world, invoice, charge_a, GROUNDS_RATE_UNREASONABLE, WEIGHT_TEN_TYPES
    )
    second = _single_charge_dispute(
        api,
        world,
        invoice,
        charge_b,
        GROUNDS_RAILROAD_CAUSED_DELAY,
        (EVIDENCE_SWITCH_LIST,),
    )

    assert second["status"] == DISPUTE_SUBMITTED
    assert second["evidence_weight"] == EVIDENCE_WEIGHT_THREE
    assert_instant_eq(
        second["submitted_at"], CLOCK_AT_SUBMIT_TEN_HUNDRED, "submitted_at"
    )
    assert_end_of_day(second["adjudication_due_at"], "adjudication_due_at")
    assert_instant_eq(
        second["adjudication_due_at"],
        DUE_AT_BASE_20_MULT_1_00_WEIGHT_3,
        "adjudication_due_at",
    )
    assert second["adjudication_due_at"] != WRONG_DUE_AT_TEN_BUSINESS_DATES
    # The two rounds ran from the same submission date and still differ.
    assert second["adjudication_due_at"] != first["adjudication_due_at"]

    rolled_up = fx.get_invoice(api, invoice["id"])
    assert rolled_up["dispute_count"] == 2
    assert rolled_up["status"] == INVOICE_PARTIALLY_DISPUTED
    assert rolled_up["total_gross_cents"] == TWO_LINE_GROSS_TOTAL
    assert rolled_up["total_credit_cents"] == 0
