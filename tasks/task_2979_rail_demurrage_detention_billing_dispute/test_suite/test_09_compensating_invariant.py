"""Queue A - rule ``compensating_invariant``.

Two instances in which a real business reversal - an appeal, a void - must undo
the *effect* of a forward action without undoing the forward action itself, and
in which the surviving invariant is checked at all three checkpoints.
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
    CHARGE_ADJUSTED,
    CHARGE_DISPUTED,
    CHARGE_FINAL,
    CHARGE_VOIDED,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_RELEASE_AT,
    DECISION_PARTIALLY_ALLOWED,
    DECISION_PENDING,
    DISPUTE_APPEALED,
    DISPUTE_DECIDED,
    DISPUTE_POSTURE_CLEAR,
    DISPUTE_POSTURE_UNDER_REVIEW,
    DISPUTE_UNDER_REVIEW,
    DUE_AT_BASE_20_MULT_1_00_WEIGHT_3,
    EVIDENCE_SWITCH_LIST,
    GROUNDS_RAILROAD_CAUSED_DELAY,
    INVOICE_ADJUSTED,
    INVOICE_PARTIALLY_DISPUTED,
    MOVEMENT_RELEASED,
    MOVEMENT_VOIDED,
    SCOPE_WHOLE_INVOICE,
    TWO_LINE_ALLOWANCE_PCT,
)

# --- instance 23 literals ---------------------------------------------------
ADJUDICATOR_R9I1 = "adj-r9i1-a"
ISSUE_CLOCK_R9I1 = "2026-08-15T00:00:00.000Z"
SUBMIT_CLOCK_R9I1 = "2026-08-15T10:00:00.000Z"
APPEAL_CLOCK_R9I1 = "2026-09-01T09:00:00.000Z"
FORWARD_CREDIT_CENTS = 30908  # ROUND_HALF_UP(47550 x 0.65)
FORWARD_NET_CENTS = 16642
EVIDENCE_WEIGHT_THREE = 3
ROUND_ONE_DUE_AT = DUE_AT_BASE_20_MULT_1_00_WEIGHT_3  # 19 business dates
ROUND_TWO_DUE_AT = "2026-09-15T23:59:59.999Z"  # MAX(5, CEIL(20 x 0.50)) = 10

# --- instance 24 literals ---------------------------------------------------
CYCLE_P_ACTUAL_AT = "2026-08-04T10:00:00.000Z"
CYCLE_P_RELEASE_AT = "2026-08-04T15:00:00.000Z"
CYCLE_P_EARLY_DAYS = 2  # 2026-08-05 and 2026-08-06, up to the expiry date
LEDGER_STATE_ZERO = {"credit_days_earned": 2, "debit_days_incurred": 0, "net_days": 2}
LEDGER_STATE_ONE = {"credit_days_earned": 2, "debit_days_incurred": 3, "net_days": -1}


def _money_snapshot(api, customer_id, invoice_id, charge_id):
    """Every money field of the three entities the credit passes through."""
    charge = fx.get_charge(api, charge_id)
    invoice = fx.get_invoice(api, invoice_id)
    customer = fx.get_customer(api, customer_id)
    assert_charge_money_invariant(charge)
    assert_invoice_money_invariant(invoice)
    # The identity of PRD 2.6, restated at this checkpoint.
    assert (
        invoice["total_net_cents"] + invoice["total_credit_cents"]
        == invoice["total_gross_cents"]
        == CYCLE_A_GROSS_CENTS
    )
    return {
        "charge_status": charge["status"],
        "charge_gross_cents": charge["gross_amount_cents"],
        "charge_credit_cents": charge["credit_applied_cents"],
        "charge_net_cents": charge["net_amount_cents"],
        "invoice_status": invoice["status"],
        "invoice_gross_cents": invoice["total_gross_cents"],
        "invoice_credit_cents": invoice["total_credit_cents"],
        "invoice_net_cents": invoice["total_net_cents"],
        "customer_credit_balance_cents": customer["credit_balance_cents"],
        "customer_dispute_posture": customer["dispute_posture"],
    }


def _credited_then_appealed_world(api):
    """An UNDER_REVIEW whole-invoice dispute on one 47550-cent ISSUED invoice."""
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_R9I1)
    dispute = fx.under_review_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        ADJUDICATOR_R9I1,
        SUBMIT_CLOCK_R9I1,
        [EVIDENCE_SWITCH_LIST],
        scope=SCOPE_WHOLE_INVOICE,
        grounds=GROUNDS_RAILROAD_CAUSED_DELAY,
    )
    assert dispute["status"] == DISPUTE_UNDER_REVIEW
    assert dispute["evidence_weight"] == EVIDENCE_WEIGHT_THREE
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert charge["status"] == CHARGE_DISPUTED
    return world, invoice, dispute, charge


# ===========================================================================
# instance: appeal_fully_reverses_dispute_credit_and_preserves_total_gross
# ===========================================================================
def test_the_appeal_returns_all_three_entities_to_their_pre_decision_money(api):
    """State 2 is byte-identical to state 0 on every money field of every hop.

    PRD 3.8: "The appeal sets `round_number` to 2, returns `decision` to
    `PENDING`, `allowance_pct` to null and `allowed_credit_cents` to 0, and
    **fully reverses** the first-level credit: every target charge returns to
    `DISPUTED` with its `credit_applied_cents` restored to the pre-decision value
    it held, the invoice's totals and derived status return to their pre-decision
    values with its `version` incremented by 1, and the consignee's
    `credit_balance_cents` returns to its pre-decision value while
    `dispute_posture` re-derives to `UNDER_REVIEW`."

    Design: Difficulty/compensating_invariant/appeal_fully_reverses_dispute_credit_and_preserves_total_gross
    """
    world, invoice, dispute, charge = _credited_then_appealed_world(api)
    customer_id = world["customer_id"]

    state_zero = _money_snapshot(api, customer_id, invoice["id"], charge["id"])
    assert state_zero == {
        "charge_status": CHARGE_DISPUTED,
        "charge_gross_cents": CYCLE_A_GROSS_CENTS,
        "charge_credit_cents": 0,
        "charge_net_cents": CYCLE_A_GROSS_CENTS,
        "invoice_status": INVOICE_PARTIALLY_DISPUTED,
        "invoice_gross_cents": CYCLE_A_GROSS_CENTS,
        "invoice_credit_cents": 0,
        "invoice_net_cents": CYCLE_A_GROSS_CENTS,
        "customer_credit_balance_cents": 0,
        "customer_dispute_posture": DISPUTE_POSTURE_UNDER_REVIEW,
    }

    # The forward action: 30908 cents of credit posted through three entities.
    fx.decide(
        api,
        dispute["id"],
        ADJUDICATOR_R9I1,
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
    )
    state_one = _money_snapshot(api, customer_id, invoice["id"], charge["id"])
    assert state_one == {
        "charge_status": CHARGE_ADJUSTED,
        "charge_gross_cents": CYCLE_A_GROSS_CENTS,
        "charge_credit_cents": FORWARD_CREDIT_CENTS,
        "charge_net_cents": FORWARD_NET_CENTS,
        "invoice_status": INVOICE_ADJUSTED,
        "invoice_gross_cents": CYCLE_A_GROSS_CENTS,
        "invoice_credit_cents": FORWARD_CREDIT_CENTS,
        "invoice_net_cents": FORWARD_NET_CENTS,
        "customer_credit_balance_cents": FORWARD_CREDIT_CENTS,
        "customer_dispute_posture": DISPUTE_POSTURE_CLEAR,
    }

    # The compensating action: a real business operation, not a reset.
    fx.appealed_dispute(api, dispute["id"], customer_id, APPEAL_CLOCK_R9I1)
    state_two = _money_snapshot(api, customer_id, invoice["id"], charge["id"])
    assert state_two == state_zero
    assert state_two != state_one

    # The gross never moved at any of the three checkpoints.
    for state in (state_zero, state_one, state_two):
        assert state["charge_gross_cents"] == CYCLE_A_GROSS_CENTS
        assert state["invoice_gross_cents"] == CYCLE_A_GROSS_CENTS


def test_the_reversal_is_not_a_rollback_because_the_round_advanced(api):
    """The money is back where it started; the dispute is somewhere new.

    PRD 3.7: "An appeal filed against a line that was already credited walks the
    invoice from `ADJUSTED` back to `PARTIALLY_DISPUTED`, because the `DISPUTED`
    test is asked first and wins."

    Design: Difficulty/compensating_invariant/appeal_fully_reverses_dispute_credit_and_preserves_total_gross
    """
    world, invoice, dispute, _charge = _credited_then_appealed_world(api)
    customer_id = world["customer_id"]

    assert_instant_eq(
        dispute["adjudication_due_at"], ROUND_ONE_DUE_AT, "adjudication_due_at"
    )
    invoice_before = fx.get_invoice(api, invoice["id"])

    decided = fx.decide(
        api,
        dispute["id"],
        ADJUDICATOR_R9I1,
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
    )
    assert_subset_equal(
        decided,
        {
            "status": DISPUTE_DECIDED,
            "round_number": 1,
            "decision": DECISION_PARTIALLY_ALLOWED,
            "allowed_credit_cents": FORWARD_CREDIT_CENTS,
        },
    )
    invoice_credited = fx.get_invoice(api, invoice["id"])
    assert invoice_credited["version"] == invoice_before["version"] + 1

    appealed = fx.appealed_dispute(api, dispute["id"], customer_id, APPEAL_CLOCK_R9I1)
    assert_subset_equal(
        appealed,
        {
            "status": DISPUTE_APPEALED,
            "round_number": 2,
            "decision": DECISION_PENDING,
            "allowance_pct": None,
            "allowed_credit_cents": 0,
            "first_level_adjudicator_id": ADJUDICATOR_R9I1,
            "appeal_adjudicator_id": None,
        },
    )
    # The second round's clock starts at the appeal, not at the first submission.
    assert_instant_eq(appealed["submitted_at"], APPEAL_CLOCK_R9I1, "submitted_at")
    assert_end_of_day(appealed["adjudication_due_at"], "adjudication_due_at")
    assert_instant_eq(
        appealed["adjudication_due_at"], ROUND_TWO_DUE_AT, "adjudication_due_at"
    )
    assert appealed["adjudication_due_at"] != ROUND_ONE_DUE_AT

    # The invoice took a second write to come back, so its version rose twice.
    invoice_after = fx.get_invoice(api, invoice["id"])
    assert invoice_after["version"] == invoice_before["version"] + 2
    assert invoice_after["status"] == INVOICE_PARTIALLY_DISPUTED
    assert invoice_after["status"] == invoice_before["status"]
    assert invoice_after["dispute_count"] == invoice_before["dispute_count"]
    assert (
        fx.get_customer(api, customer_id)["dispute_posture"]
        == DISPUTE_POSTURE_UNDER_REVIEW
    )


def _assert_day_ledger_identity(ledger):
    """``net_days == credit_days_earned - debit_days_incurred``, at any checkpoint."""
    assert (
        ledger["net_days"]
        == ledger["credit_days_earned"] - ledger["debit_days_incurred"]
    )


def _ledger_holding_two_earned_credit_days(api):
    """An OPEN 2026-08 ledger reading (2, 0, 2), and one car about to be released.

    Cycle P is released on its own free-time date, so it hands back two free days;
    cycle A is standing on the track with three chargeable days ahead of it.  No
    invoice is ever opened, so the day ledger is the only aggregate in play.
    """
    world = fx.reference_world(api)
    agreement = fx.open_agreement(
        api, world["customer_id"], agreement_month=AGREEMENT_MONTH
    )
    cycle_p = fx.released_cycle(
        api, world, actual_at=CYCLE_P_ACTUAL_AT, released_at=CYCLE_P_RELEASE_AT
    )
    assert_subset_equal(
        cycle_p,
        {
            "movement_status": MOVEMENT_RELEASED,
            "chargeable_days": 0,
            "early_release_days": CYCLE_P_EARLY_DAYS,
        },
    )
    charge_p = fx.charge_of_cycle(api, cycle_p["id"])
    assert charge_p["status"] == CHARGE_FINAL
    assert charge_p["gross_amount_cents"] == 0

    cycle_a = fx.actually_placed_cycle(api, world, actual_at=CYCLE_A_ACTUAL_AT)
    fx.set_clock(api, CYCLE_A_RELEASE_AT)
    return world, agreement, cycle_p, cycle_a


# ===========================================================================
# instance: void_restores_average_agreement_day_ledger_identity
# ===========================================================================
def test_the_void_restores_the_day_ledger_to_its_pre_release_reading(api):
    """(2, 0, 2) -> (2, 3, -1) -> (2, 0, 2), with the identity true throughout.

    PRD 3.7: "The consignee's `OPEN` agreement has `credit_days_earned`,
    `debit_days_incurred` and `net_days` re-derived, which moves them downward, and
    `credit_balance_cents` is re-derived with them."

    Design: Difficulty/compensating_invariant/void_restores_average_agreement_day_ledger_identity
    """
    world, agreement, _cycle_p, cycle_a = _ledger_holding_two_earned_credit_days(api)
    customer_id = world["customer_id"]

    state_zero = fx.get_agreement(api, customer_id, agreement["id"])
    assert_subset_equal(state_zero, LEDGER_STATE_ZERO)
    assert_subset_equal(
        state_zero, {"status": AGREEMENT_OPEN, "agreement_credit_cents": 0}
    )
    _assert_day_ledger_identity(state_zero)

    # The forward action: three chargeable days land on the debit side.
    fx.release_cycle(api, cycle_a["id"], CYCLE_A_RELEASE_AT, customer_id)
    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    assert_subset_equal(
        charge_a,
        {
            "status": CHARGE_FINAL,
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    state_one = fx.get_agreement(api, customer_id, agreement["id"])
    assert_subset_equal(state_one, LEDGER_STATE_ONE)
    _assert_day_ledger_identity(state_one)
    assert state_one["version"] == state_zero["version"] + 1
    assert state_one["debit_days_incurred"] == charge_a["chargeable_days"]

    # The compensating action: the void takes the same three days back off.
    fx.void_cycle(api, cycle_a["id"])
    state_two = fx.get_agreement(api, customer_id, agreement["id"])
    assert_subset_equal(state_two, LEDGER_STATE_ZERO)
    _assert_day_ledger_identity(state_two)
    assert_subset_equal(
        state_two, {"status": AGREEMENT_OPEN, "agreement_credit_cents": 0}
    )

    # Exactly state 0 on both sides of the ledger, not merely on the net.
    for field in ("credit_days_earned", "debit_days_incurred", "net_days"):
        assert state_two[field] == state_zero[field]
    assert fx.get_customer(api, customer_id)["credit_balance_cents"] == 0


def test_both_sides_of_the_ledger_are_rebuilt_rather_than_decremented(api):
    """A counter-keeping implementation cannot land on 0 here, and the cycle stays voided.

    PRD 2.9: "A derived field is never patched incrementally; it is always
    recomputed from scratch from its source rows at every moment the narrative says
    it is re-derived."

    Design: Difficulty/compensating_invariant/void_restores_average_agreement_day_ledger_identity
    """
    world, agreement, cycle_p, cycle_a = _ledger_holding_two_earned_credit_days(api)
    customer_id = world["customer_id"]
    car_id = cycle_a["rail_car_id"]

    fx.release_cycle(api, cycle_a["id"], CYCLE_A_RELEASE_AT, customer_id)
    # PRD 3.1: active_cycle_count "is the number of placement cycles on this car
    # whose `movement_status` is neither `RELEASED` nor `VOIDED`", so the release
    # has already dropped the car's live count to zero.
    assert fx.get_car(api, car_id)["active_cycle_count"] == 0

    voided = fx.void_cycle(api, cycle_a["id"])
    assert voided["movement_status"] == MOVEMENT_VOIDED

    ledger = fx.get_agreement(api, customer_id, agreement["id"])
    assert ledger["debit_days_incurred"] == 0
    # Neither the stale 3 of an un-recomputed counter nor the -3 of a double debit.
    assert ledger["debit_days_incurred"] != LEDGER_STATE_ONE["debit_days_incurred"]
    assert ledger["debit_days_incurred"] >= 0
    assert ledger["credit_days_earned"] == CYCLE_P_EARLY_DAYS
    assert ledger["net_days"] == CYCLE_P_EARLY_DAYS

    # The compensation is not a rollback: the line is VOIDED, not deleted, and it
    # still remembers what it was worth.
    voided_charge = fx.charge_of_cycle(api, cycle_a["id"])
    assert_subset_equal(
        voided_charge,
        {"status": CHARGE_VOIDED, "gross_amount_cents": CYCLE_A_GROSS_CENTS},
    )
    assert fx.get_car(api, car_id)["active_cycle_count"] == 0

    # Cycle P never entered the reversal and is untouched in every state.
    still_there = fx.get_cycle(api, cycle_p["id"])
    assert_subset_equal(
        still_there,
        {
            "movement_status": MOVEMENT_RELEASED,
            "early_release_days": CYCLE_P_EARLY_DAYS,
        },
    )
    charge_p = fx.charge_of_cycle(api, cycle_p["id"])
    assert charge_p["status"] == CHARGE_FINAL
    assert charge_p["gross_amount_cents"] == 0
