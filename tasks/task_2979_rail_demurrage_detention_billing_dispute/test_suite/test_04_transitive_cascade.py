"""Queue A - rule ``transitive_cascade``.

Two instances, each following one write three or four hops outwards and pinning
every intermediate row, including the hops that are not simple copies of the
hop before them.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_charge_money_invariant,
    assert_instant_eq,
    assert_invoice_money_invariant,
    assert_subset_equal,
)
from test_helpers.constants import (
    AGREEMENT_MONTH,
    AGREEMENT_OPEN,
    BILLING_ADJUSTED,
    BILLING_UNBILLED,
    CHARGE_ADJUSTED,
    CHARGE_DISPUTED,
    CHARGE_FINAL,
    CHARGE_PROVISIONAL,
    CLOCK_BASIS_ACTUAL,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_ACTUAL_EXPIRY,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_RELEASE_AT,
    CYCLE_B_GROSS_CENTS,
    DECISION_ALLOWED,
    DECISION_PARTIALLY_ALLOWED,
    DISPUTE_POSTURE_CLEAR,
    DISPUTE_POSTURE_UNDER_REVIEW,
    DISPUTE_UNDER_REVIEW,
    INVOICE_ADJUSTED,
    INVOICE_PARTIALLY_DISPUTED,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_RELEASED,
    SCOPE_WHOLE_INVOICE,
    TWO_LINE_ALLOWANCE_PCT,
)

# --- instance 10 literals --------------------------------------------------
ADJUDICATOR_R4I1 = "adj-r4i1-a"
HOP2_CREDIT_CENTS = 30908  # ROUND_HALF_UP(47550 x 0.65)
HOP2_NET_CENTS = 16642
PERIOD_ONE_START = "2026-08-01T00:00:00.000Z"
PERIOD_ONE_END = "2026-08-10T23:59:59.999Z"
PERIOD_TWO_START = "2026-08-11T00:00:00.000Z"
PERIOD_TWO_END = "2026-08-31T23:59:59.999Z"
BALANCE_ACROSS_TWO_INVOICES = HOP2_CREDIT_CENTS + CYCLE_B_GROSS_CENTS  # 43458

# --- instance 11 literals --------------------------------------------------
PROVISIONAL_CLOCK = "2026-08-05T12:00:00.000Z"
RELEASE_DEBIT_DAYS = 3
RELEASE_NET_DAYS = -3


def _under_review_whole_invoice_dispute(api):
    """One 47550-cent charge, one ISSUED invoice, one dispute at UNDER_REVIEW."""
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    dispute = fx.under_review_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        ADJUDICATOR_R4I1,
        scope=SCOPE_WHOLE_INVOICE,
    )
    return world, cycle, invoice, dispute


# ===========================================================================
# instance: decide_cascades_charge_to_invoice_to_customer_four_hops
# ===========================================================================
def test_decide_cascades_four_hops_and_re_derives_the_consignee_posture(api):
    """One decision walks charge, cycle, invoice and consignee in one request.

    PRD 3.8: "Deciding cascades outward. Each target cycle's `billing_status`
    moves to `ADJUSTED`, or back to `INVOICED` when its line's credit is 0. The
    invoice's `total_credit_cents`, `total_net_cents` and derived status are
    rewritten and its `version` increments by 1. The consignee's
    `credit_balance_cents` - the sum of `credit_applied_cents` over every charge
    on that consignee's cycles whose status is `FINAL` or `ADJUSTED` - and
    `dispute_posture` are re-derived and its `version` increments by 1."

    Design: Difficulty/transitive_cascade/decide_cascades_charge_to_invoice_to_customer_four_hops
    """
    world, cycle, invoice, dispute = _under_review_whole_invoice_dispute(api)

    invoice_before = fx.get_invoice(api, invoice["id"])
    customer_before = fx.get_customer(api, world["customer_id"])
    charge_before = fx.charge_of_cycle(api, cycle["id"])
    car_before = fx.get_car(api, cycle["rail_car_id"])
    tariff_before = fx.get_tariff(api, world["tariff_id"])

    assert dispute["status"] == DISPUTE_UNDER_REVIEW
    assert charge_before["status"] == CHARGE_DISPUTED
    assert charge_before["credit_applied_cents"] == 0
    assert invoice_before["status"] == INVOICE_PARTIALLY_DISPUTED
    assert_subset_equal(
        customer_before,
        {
            "credit_balance_cents": 0,
            "dispute_posture": DISPUTE_POSTURE_UNDER_REVIEW,
        },
    )

    # hop 1 - the dispute itself
    decided = fx.decide(
        api,
        dispute["id"],
        ADJUDICATOR_R4I1,
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
    )
    assert decided["allowed_credit_cents"] == HOP2_CREDIT_CENTS

    # hop 2 - the charge line
    charge_after = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge_after,
        {
            "status": CHARGE_ADJUSTED,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
            "credit_applied_cents": HOP2_CREDIT_CENTS,
            "net_amount_cents": HOP2_NET_CENTS,
        },
    )
    assert_charge_money_invariant(charge_after)

    # hop 2b - the cycle's billing axis only
    cycle_after = fx.get_cycle(api, cycle["id"])
    assert cycle_after["billing_status"] == BILLING_ADJUSTED
    assert cycle_after["movement_status"] == MOVEMENT_RELEASED

    # hop 3 - the invoice
    invoice_after = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        invoice_after,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "total_credit_cents": HOP2_CREDIT_CENTS,
            "total_net_cents": HOP2_NET_CENTS,
        },
    )
    assert invoice_after["version"] == invoice_before["version"] + 1
    assert_invoice_money_invariant(invoice_after)

    # hop 4 - the consignee, which carries an enum re-derivation as well as money
    customer_after = fx.get_customer(api, world["customer_id"])
    assert_subset_equal(
        customer_after,
        {
            "credit_balance_cents": HOP2_CREDIT_CENTS,
            "dispute_posture": DISPUTE_POSTURE_CLEAR,
        },
    )
    assert customer_after["version"] == customer_before["version"] + 1

    # Nothing outside the money model moved.
    assert fx.get_car(api, cycle["rail_car_id"])["version"] == car_before["version"]
    assert fx.get_tariff(api, world["tariff_id"])["version"] == tariff_before["version"]


def test_consignee_balance_sums_charge_credit_across_every_invoice(api):
    """The fourth hop is not a copy of the third: it spans both invoices.

    PRD 3.1: "`credit_balance_cents` is the sum of `credit_applied_cents` across
    every charge line whose placement cycle belongs to this consignee and whose
    own status is either `FINAL` or `ADJUSTED`."

    Design: Difficulty/transitive_cascade/decide_cascades_charge_to_invoice_to_customer_four_hops
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b = fx.released_pair(api, world)

    invoice_one = fx.issued_invoice(
        api,
        world,
        billing_period_start=PERIOD_ONE_START,
        billing_period_end=PERIOD_ONE_END,
    )
    invoice_two = fx.issued_invoice(
        api,
        world,
        billing_period_start=PERIOD_TWO_START,
        billing_period_end=PERIOD_TWO_END,
    )
    assert invoice_one["total_gross_cents"] == CYCLE_A_GROSS_CENTS
    assert invoice_two["total_gross_cents"] == CYCLE_B_GROSS_CENTS

    fx.decided_dispute(
        api,
        invoice_one,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        "adj-r4i1-one",
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
        scope=SCOPE_WHOLE_INVOICE,
    )
    fx.decided_dispute(
        api,
        invoice_two,
        world["customer_id"],
        CYCLE_B_GROSS_CENTS,
        "adj-r4i1-two",
        DECISION_ALLOWED,
        1,
        scope=SCOPE_WHOLE_INVOICE,
    )

    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    charge_b = fx.charge_of_cycle(api, cycle_b["id"])
    assert charge_a["credit_applied_cents"] == HOP2_CREDIT_CENTS
    assert charge_b["credit_applied_cents"] == CYCLE_B_GROSS_CENTS

    rolled_one = fx.get_invoice(api, invoice_one["id"])
    rolled_two = fx.get_invoice(api, invoice_two["id"])
    assert rolled_one["total_credit_cents"] == HOP2_CREDIT_CENTS
    assert rolled_two["total_credit_cents"] == CYCLE_B_GROSS_CENTS

    customer = fx.get_customer(api, world["customer_id"])
    assert customer["credit_balance_cents"] == BALANCE_ACROSS_TWO_INVOICES
    # The balance is neither invoice's total, which is the whole point.
    assert customer["credit_balance_cents"] != rolled_one["total_credit_cents"]
    assert customer["credit_balance_cents"] != rolled_two["total_credit_cents"]
    assert customer["dispute_posture"] == DISPUTE_POSTURE_CLEAR


def _agreement_and_spotted_cycle(api):
    """An OPEN, empty 2026-08 agreement and one ACTUALLY_PLACED cycle.

    The clock is parked at 2026-08-05T12:00:00Z so that the provisional line is
    genuinely zero before the release: PRD 3.5's provisional variant walks from
    the day after the 2026-08-07 expiry through the reference date, which is
    still 2026-08-05, so the walk is empty.
    """
    world = fx.reference_world(api, clock=PROVISIONAL_CLOCK)
    agreement = fx.open_agreement(
        api, world["customer_id"], agreement_month=AGREEMENT_MONTH
    )
    assert_subset_equal(
        agreement,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": 0,
            "debit_days_incurred": 0,
            "net_days": 0,
            "agreement_credit_cents": 0,
        },
    )
    cycle = fx.actually_placed_cycle(api, world)
    assert_subset_equal(
        cycle,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "billing_status": BILLING_UNBILLED,
            "clock_basis": CLOCK_BASIS_ACTUAL,
        },
    )
    assert_instant_eq(
        cycle["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )
    return world, agreement, cycle


# ===========================================================================
# instance: release_cascades_cycle_to_charge_to_average_agreement_three_hops
# ===========================================================================
def test_release_finalises_the_charge_and_the_agreement_reads_the_new_day_count(api):
    """Hop three reads the ``chargeable_days`` hop two has only just written.

    PRD 3.5: "It also reaches into the consignee's average agreement: if the
    consignee has an agreement in status `OPEN` whose month matches the release
    month, that agreement's `credit_days_earned`, `debit_days_incurred` and
    `net_days` are re-derived and its `version` increments by 1."

    Design: Difficulty/transitive_cascade/release_cascades_cycle_to_charge_to_average_agreement_three_hops
    """
    world, agreement, cycle = _agreement_and_spotted_cycle(api)

    provisional = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        provisional,
        {
            "status": CHARGE_PROVISIONAL,
            "chargeable_days": 0,
            "gross_amount_cents": 0,
            "invoice_id": None,
        },
    )

    fx.set_clock(api, CYCLE_A_RELEASE_AT)
    fx.release_cycle(api, cycle["id"], CYCLE_A_RELEASE_AT, world["customer_id"])

    # hop 1 - the cycle
    released = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        released,
        {
            "movement_status": MOVEMENT_RELEASED,
            "billing_status": BILLING_UNBILLED,
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "early_release_days": 0,
        },
    )
    assert_instant_eq(released["released_at"], CYCLE_A_RELEASE_AT, "released_at")

    # hop 2 - the charge line
    final = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        final,
        {
            "status": CHARGE_FINAL,
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "billable_days": CYCLE_A_CHARGEABLE_DAYS,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
            "credit_applied_cents": 0,
            "net_amount_cents": CYCLE_A_GROSS_CENTS,
            "invoice_id": None,
        },
    )
    assert_charge_money_invariant(final)

    # hop 3 - the agreement, which must have seen hop 2's figure
    settled = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert_subset_equal(
        settled,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": 0,
            "debit_days_incurred": RELEASE_DEBIT_DAYS,
            "net_days": RELEASE_NET_DAYS,
            "agreement_credit_cents": 0,
        },
    )
    assert settled["version"] == agreement["version"] + 1
    # It is the charge's own chargeable_days that the agreement summed.
    assert settled["debit_days_incurred"] == final["chargeable_days"]


def test_release_re_derives_the_facility_occupancy_and_switch_instant(api):
    """The lateral hop: the spot is freed and the switch instant moves forward.

    PRD 3.5: "A successful release writes `released_at`, finalises the cycle's
    `chargeable_days` and `early_release_days`, moves the charge line
    `PROVISIONAL -> FINAL` with its amounts recomputed from `released_at` and its
    `computation_basis` frozen to the cycle's elected `clock_basis` or the
    facility's storage clock as appropriate, re-derives the facility's
    `occupied_spot_count` and `last_switch_at`, and increments the cycle's
    `version` by 1."

    Design: Difficulty/transitive_cascade/release_cascades_cycle_to_charge_to_average_agreement_three_hops
    """
    world, _agreement, cycle = _agreement_and_spotted_cycle(api)

    occupied = fx.probe_facility(api, world["facility_id"])
    assert occupied["occupied_spot_count"] == 1
    assert_instant_eq(occupied["last_switch_at"], CYCLE_A_ACTUAL_AT, "last_switch_at")

    fx.set_clock(api, CYCLE_A_RELEASE_AT)
    fx.release_cycle(api, cycle["id"], CYCLE_A_RELEASE_AT, world["customer_id"])

    freed = fx.probe_facility(api, world["facility_id"])
    assert freed["occupied_spot_count"] == 0
    assert_instant_eq(freed["last_switch_at"], CYCLE_A_RELEASE_AT, "last_switch_at")
    assert freed["last_switch_at"] > occupied["last_switch_at"]

    # No invoice exists, so the cascade stops at the agreement.
    assert fx.charge_of_cycle(api, cycle["id"])["invoice_id"] is None
    assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_UNBILLED
    assert fx.get_customer(api, world["customer_id"])["credit_balance_cents"] == 0
