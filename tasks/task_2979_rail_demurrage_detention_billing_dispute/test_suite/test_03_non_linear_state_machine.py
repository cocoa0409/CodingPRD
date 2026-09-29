"""Queue A - rule ``non_linear_state_machine``.

Three instances, each walking a status graph that is not a line: two parallel
machines on one entity, two re-entrant loops through one status, and one endpoint
on one source status that forks on a computed sign into two different blast radii.
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
    AGREEMENT_FORFEITED,
    AGREEMENT_MONTH,
    AGREEMENT_OPEN,
    AGREEMENT_RECONCILED,
    BILLING_INVOICED,
    BILLING_UNBILLED,
    CHARGE_ADJUSTED,
    CHARGE_DISPUTED,
    CHARGE_FINAL,
    CHARGE_PROVISIONAL,
    CLOCK_BASIS_ACTUAL,
    CLOCK_BASIS_CONSTRUCTIVE,
    CLOCK_BASIS_NONE,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_ACTUAL_EXPIRY,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_CONSTRUCTIVE_AT,
    CYCLE_A_CONSTRUCTIVE_EXPIRY,
    CYCLE_A_CONSTRUCTIVE_START,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_NOTICE_SENT_AT,
    CYCLE_A_RELEASE_AT,
    DECISION_ALLOWED,
    DECISION_PARTIALLY_ALLOWED,
    DECISION_PENDING,
    DISPUTE_APPEALED,
    DISPUTE_DECIDED,
    DISPUTE_INFO_REQUESTED,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    DUE_AT_AFTER_INFO_REQUEST,
    DUE_AT_APPEAL_ROUND,
    DUE_AT_BASE_20_MULT_1_00_WEIGHT_3,
    EVIDENCE_GATE_LOG,
    EVIDENCE_SWITCH_LIST,
    GROUNDS_RAILROAD_CAUSED_DELAY,
    INVOICE_ADJUSTED,
    INVOICE_DRAFT,
    INVOICE_ISSUED,
    INVOICE_PARTIALLY_DISPUTED,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_CONSTRUCTIVELY_PLACED,
    MOVEMENT_RELEASED,
    SCOPE_WHOLE_INVOICE,
    TWO_LINE_ALLOWANCE_PCT,
)

# --- instance 7 literals ---------------------------------------------------
CLOCK_AT_REFUSAL = "2026-08-05T12:00:00.000Z"
REPLACEMENT_AT = "2026-08-05T14:00:00.000Z"
CLOCK_AT_INVOICE_CREATE = "2026-08-15T00:00:00.000Z"

# --- instance 8 literals ---------------------------------------------------
CLOCK_AT_ISSUE_R3I2 = "2026-08-15T00:00:00.000Z"
DISPUTE_DEADLINE_R3I2 = "2026-09-14T23:59:59.999Z"
CLOCK_AT_SUBMIT_R3I2 = "2026-08-15T10:00:00.000Z"
CLOCK_AT_INFO_REQUEST_R3I2 = "2026-08-20T09:00:00.000Z"
CLOCK_AT_RESUBMIT_R3I2 = "2026-08-25T09:00:00.000Z"
CLOCK_AT_DECIDE_R3I2 = "2026-08-28T09:00:00.000Z"
CLOCK_AT_APPEAL_R3I2 = "2026-09-01T09:00:00.000Z"
ADJUDICATOR_A = "adj-r3i2-a"
ADJUDICATOR_B = "adj-r3i2-b"
WEIGHT_ONE_EXHIBIT = 3
WEIGHT_TWO_EXHIBITS = 6
ROUND_1_CREDIT_CENTS = 30908  # ROUND_HALF_UP(47550 x 0.65)
ROUND_1_NET_CENTS = 16642
ROUND_2_CREDIT_CENTS = CYCLE_A_GROSS_CENTS
WRONG_DUE_AT_RECOMPUTED_FROM_RESUBMIT = "2026-09-16T23:59:59.999Z"
WRONG_DUE_AT_WEIGHT_SIX_FROM_RESUBMIT = "2026-09-08T23:59:59.999Z"

# --- instance 9 literals ---------------------------------------------------
CYCLE_EARLY_ACTUAL_AT = "2026-08-04T10:00:00.000Z"
CYCLE_EARLY_RELEASE_AT = "2026-08-04T15:00:00.000Z"
EARLY_RELEASE_DAYS = 2
FORFEIT_CREDIT_CENTS = 14265  # FLOOR(47550 x 0.30)
FORFEIT_NET_CENTS = 33285
RECONCILE_NET_DAYS = 2
FORFEIT_NET_DAYS = -1
FORFEIT_DEBIT_DAYS = 3


# ===========================================================================
# instance: placement_cycle_movement_and_billing_axes_advance_independently
# ===========================================================================
def test_refusal_walks_movement_backwards_and_leaves_billing_where_it_was(api):
    """Refusal retreats the movement axis and the expiry; billing does not move.

    PRD 3.4: "On success the cycle's `actual_placement_at` is set back to null,
    `refusal_count` increments by 1, the facility's `occupied_spot_count` is
    re-derived downward - freeing the spot for another car - the clock-basis
    election is re-run and reverts `clock_basis` to `CONSTRUCTIVE` with
    `clock_start_at` back at the constructive instant, the provisional charge is
    recomputed, and the cycle's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/placement_cycle_movement_and_billing_axes_advance_independently
    """
    world = fx.reference_world(api, clock=CLOCK_AT_REFUSAL)
    cycle = fx.make_cycle(api, world)
    fx.place_constructively(api, cycle["id"], CYCLE_A_CONSTRUCTIVE_AT)

    # First visit to (CONSTRUCTIVELY_PLACED, UNBILLED): no notice, so no clock.
    first_visit = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        first_visit,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "billing_status": BILLING_UNBILLED,
            "clock_basis": CLOCK_BASIS_NONE,
            "clock_start_at": None,
            "free_time_expires_at": None,
            "refusal_count": 0,
        },
    )

    fx.send_notice(api, cycle["id"], CYCLE_A_NOTICE_SENT_AT)
    fx.place_actually(api, cycle["id"], CYCLE_A_ACTUAL_AT)
    spotted = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        spotted,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "billing_status": BILLING_UNBILLED,
            "clock_basis": CLOCK_BASIS_ACTUAL,
            "refusal_count": 0,
        },
    )
    assert_instant_eq(spotted["actual_placement_at"], CYCLE_A_ACTUAL_AT)
    assert_instant_eq(
        spotted["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )
    assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 1

    refused = fx.refuse_cycle(api, cycle["id"], world["customer_id"])

    # Second visit to (CONSTRUCTIVELY_PLACED, UNBILLED) - a different clock basis.
    assert_subset_equal(
        refused,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "billing_status": BILLING_UNBILLED,
            "actual_placement_at": None,
            "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
            "refusal_count": 1,
        },
    )
    assert refused["clock_basis"] != first_visit["clock_basis"]
    assert_instant_eq(
        refused["clock_start_at"], CYCLE_A_CONSTRUCTIVE_START, "clock_start_at"
    )
    assert_instant_eq(
        refused["free_time_expires_at"],
        CYCLE_A_CONSTRUCTIVE_EXPIRY,
        "free_time_expires_at",
    )
    # The only derived expiry in this service that retreats.
    assert refused["free_time_expires_at"] < spotted["free_time_expires_at"]
    assert refused["version"] == spotted["version"] + 1
    assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 0

    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_PROVISIONAL,
            "chargeable_days": 0,
            "billable_days": 0,
            "gross_amount_cents": 0,
            "net_amount_cents": 0,
        },
    )
    assert_charge_money_invariant(charge)


def test_invoice_attachment_walks_billing_forward_and_freezes_movement(api):
    """Attachment moves ``billing_status`` alone; ``movement_status`` stays RELEASED.

    PRD 3.7: "Every charge line whose status is `FINAL`, whose `invoice_id` is
    still null, whose cycle belongs to this consignee, and whose cycle's
    `released_at` falls inside the closed billing period is attached - its
    `invoice_id` is set to the new invoice - and each attached cycle's
    `billing_status` moves `UNBILLED -> INVOICED`. Note that the movement
    dimension is untouched by this: the cycle stays `RELEASED`."

    Design: Difficulty/non_linear_state_machine/placement_cycle_movement_and_billing_axes_advance_independently
    """
    world = fx.reference_world(api, clock=CLOCK_AT_REFUSAL)
    cycle = fx.actually_placed_cycle(api, world)
    fx.refuse_cycle(api, cycle["id"], world["customer_id"])

    # Re-spot the car.  The refusal nulled ``actual_placement_at``, so PRD 3.5
    # re-derives the facility's ``last_switch_at`` to null and the switch buffer
    # cannot bite on the second attempt.
    fx.set_clock(api, CYCLE_A_RELEASE_AT)
    fx.place_actually(api, cycle["id"], REPLACEMENT_AT)
    respotted = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        respotted,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "billing_status": BILLING_UNBILLED,
            "clock_basis": CLOCK_BASIS_ACTUAL,
        },
    )
    assert_instant_eq(
        respotted["free_time_expires_at"],
        CYCLE_A_ACTUAL_EXPIRY,
        "free_time_expires_at",
    )

    fx.release_cycle(api, cycle["id"], CYCLE_A_RELEASE_AT, world["customer_id"])
    released = fx.get_cycle(api, cycle["id"])
    assert released["movement_status"] == MOVEMENT_RELEASED
    assert released["billing_status"] == BILLING_UNBILLED
    assert released["chargeable_days"] == CYCLE_A_CHARGEABLE_DAYS

    final_charge = fx.charge_of_cycle(api, cycle["id"])
    assert final_charge["status"] == CHARGE_FINAL
    assert final_charge["gross_amount_cents"] == CYCLE_A_GROSS_CENTS
    assert final_charge["invoice_id"] is None

    invoice = fx.draft_invoice(api, world, clock=CLOCK_AT_INVOICE_CREATE)
    assert_subset_equal(
        invoice,
        {
            "status": INVOICE_DRAFT,
            "attached_charge_count": 1,
            "total_gross_cents": 0,
            "total_credit_cents": 0,
            "total_net_cents": 0,
            "agreement_credit_cents": 0,
            "dispute_count": 0,
            "dispute_deadline_at": None,
        },
    )
    assert_invoice_money_invariant(invoice)

    billed = fx.get_cycle(api, cycle["id"])
    assert billed["billing_status"] == BILLING_INVOICED
    assert billed["movement_status"] == MOVEMENT_RELEASED
    assert fx.charge_of_cycle(api, cycle["id"])["invoice_id"] == invoice["id"]


def _issued_single_charge_invoice(api):
    """One RELEASED cycle worth 47550 cents on one ISSUED invoice."""
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(
        api,
        world,
        draft_clock=CLOCK_AT_ISSUE_R3I2,
        issue_clock=CLOCK_AT_ISSUE_R3I2,
    )
    assert invoice["status"] == INVOICE_ISSUED
    assert invoice["total_gross_cents"] == CYCLE_A_GROSS_CENTS
    assert_instant_eq(
        invoice["dispute_deadline_at"], DISPUTE_DEADLINE_R3I2, "dispute_deadline_at"
    )
    return world, cycle, invoice


def _through_the_information_loop(api, world, invoice):
    """Submit, take up the review, request information, resubmit, take it up again.

    Returns ``(dispute_after_submit, dispute_after_request, dispute_after_resubmit,
    dispute_under_review_again)`` so a caller can compare the four snapshots.
    """
    submitted = fx.submitted_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        CLOCK_AT_SUBMIT_R3I2,
        [EVIDENCE_SWITCH_LIST],
        scope=SCOPE_WHOLE_INVOICE,
        grounds=GROUNDS_RAILROAD_CAUSED_DELAY,
    )
    fx.begin_review(api, submitted["id"], ADJUDICATOR_A)
    requested = fx.request_more_info(
        api, submitted["id"], ADJUDICATOR_A, clock=CLOCK_AT_INFO_REQUEST_R3I2
    )
    fx.add_evidence(
        api,
        submitted["id"],
        world["customer_id"],
        evidence_type=EVIDENCE_GATE_LOG,
    )
    resubmitted = fx.resubmit(
        api, submitted["id"], world["customer_id"], clock=CLOCK_AT_RESUBMIT_R3I2
    )
    reviewed_again = fx.begin_review(api, submitted["id"], ADJUDICATOR_A)
    return submitted, requested, resubmitted, reviewed_again


# ===========================================================================
# instance: dispute_cycles_twice_through_under_review_with_non_monotonic_due_date
# ===========================================================================
def test_information_request_replaces_the_due_date_and_resubmit_leaves_it(api):
    """The first loop back into UNDER_REVIEW moves the deadline EARLIER, and stays.

    PRD 3.8: "Resubmission refreshes `submitted_at` to the logical clock and
    re-derives `evidence_weight` over the enlarged file, but it leaves
    `adjudication_due_at` exactly where the information request put it: the
    extension the adjudicator granted stands, and recomputing the deadline from
    the fresh `submitted_at` would silently hand the customer a second extension."

    Design: Difficulty/non_linear_state_machine/dispute_cycles_twice_through_under_review_with_non_monotonic_due_date
    """
    world, cycle, invoice = _issued_single_charge_invoice(api)
    submitted, requested, resubmitted, reviewed_again = _through_the_information_loop(
        api, world, invoice
    )

    assert_subset_equal(
        submitted,
        {
            "status": DISPUTE_SUBMITTED,
            "evidence_weight": WEIGHT_ONE_EXHIBIT,
            "round_number": 1,
            "target_charge_count": 1,
        },
    )
    assert_instant_eq(submitted["submitted_at"], CLOCK_AT_SUBMIT_R3I2, "submitted_at")
    assert_instant_eq(
        submitted["adjudication_due_at"],
        DUE_AT_BASE_20_MULT_1_00_WEIGHT_3,
        "adjudication_due_at",
    )

    assert_subset_equal(
        requested,
        {
            "status": DISPUTE_INFO_REQUESTED,
            "info_request_count": 1,
            "round_number": 1,
            "first_level_adjudicator_id": ADJUDICATOR_A,
        },
    )
    assert_end_of_day(requested["adjudication_due_at"], "adjudication_due_at")
    assert_instant_eq(
        requested["adjudication_due_at"],
        DUE_AT_AFTER_INFO_REQUEST,
        "adjudication_due_at",
    )
    # The replacement moved the deadline EARLIER, not later.
    assert requested["adjudication_due_at"] < submitted["adjudication_due_at"]

    # No money moved while the round was paused.
    paused_charge = fx.charge_of_cycle(api, cycle["id"])
    assert paused_charge["status"] == CHARGE_DISPUTED
    assert paused_charge["credit_applied_cents"] == 0
    paused_invoice = fx.get_invoice(api, invoice["id"])
    assert paused_invoice["total_credit_cents"] == 0
    assert paused_invoice["total_gross_cents"] == CYCLE_A_GROSS_CENTS

    assert_subset_equal(
        resubmitted,
        {
            "status": DISPUTE_SUBMITTED,
            "evidence_weight": WEIGHT_TWO_EXHIBITS,
            "info_request_count": 1,
            "round_number": 1,
        },
    )
    assert_instant_eq(
        resubmitted["submitted_at"], CLOCK_AT_RESUBMIT_R3I2, "submitted_at"
    )
    assert_instant_eq(
        resubmitted["adjudication_due_at"],
        DUE_AT_AFTER_INFO_REQUEST,
        "adjudication_due_at",
    )
    assert resubmitted["adjudication_due_at"] != WRONG_DUE_AT_RECOMPUTED_FROM_RESUBMIT
    assert resubmitted["adjudication_due_at"] != WRONG_DUE_AT_WEIGHT_SIX_FROM_RESUBMIT

    # The second entry into UNDER_REVIEW is still round one.
    assert_subset_equal(
        reviewed_again,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "round_number": 1,
            "first_level_adjudicator_id": ADJUDICATOR_A,
            "appeal_adjudicator_id": None,
        },
    )
    assert_instant_eq(
        reviewed_again["adjudication_due_at"],
        DUE_AT_AFTER_INFO_REQUEST,
        "adjudication_due_at",
    )


def test_appeal_loop_reverses_the_money_and_recomputes_from_the_appeal_date(api):
    """The second loop back into UNDER_REVIEW unwinds round one completely.

    PRD 3.8: "The appeal sets `round_number` to 2, returns `decision` to
    `PENDING`, `allowance_pct` to null and `allowed_credit_cents` to 0, and
    **fully reverses** the first-level credit: every target charge returns to
    `DISPUTED` with its `credit_applied_cents` restored to the pre-decision value
    it held, the invoice's totals and derived status return to their pre-decision
    values with its `version` incremented by 1, and the consignee's
    `credit_balance_cents` returns to its pre-decision value while
    `dispute_posture` re-derives to `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/dispute_cycles_twice_through_under_review_with_non_monotonic_due_date
    """
    world, cycle, invoice = _issued_single_charge_invoice(api)
    submitted, _requested, _resubmitted, _again = _through_the_information_loop(
        api, world, invoice
    )
    dispute_id = submitted["id"]

    fx.set_clock(api, CLOCK_AT_DECIDE_R3I2)
    decided = fx.decide(
        api,
        dispute_id,
        ADJUDICATOR_A,
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
    )
    assert_subset_equal(
        decided,
        {
            "status": DISPUTE_DECIDED,
            "decision": DECISION_PARTIALLY_ALLOWED,
            "allowance_pct": TWO_LINE_ALLOWANCE_PCT,
            "allowed_credit_cents": ROUND_1_CREDIT_CENTS,
            "round_number": 1,
        },
    )
    charge_after_round_1 = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge_after_round_1,
        {
            "status": CHARGE_ADJUSTED,
            "credit_applied_cents": ROUND_1_CREDIT_CENTS,
            "net_amount_cents": ROUND_1_NET_CENTS,
        },
    )
    invoice_after_round_1 = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        invoice_after_round_1,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "total_credit_cents": ROUND_1_CREDIT_CENTS,
            "total_net_cents": ROUND_1_NET_CENTS,
        },
    )
    assert_invoice_money_invariant(invoice_after_round_1)

    appealed = fx.appealed_dispute(
        api, dispute_id, world["customer_id"], appeal_clock=CLOCK_AT_APPEAL_R3I2
    )
    assert_subset_equal(
        appealed,
        {
            "status": DISPUTE_APPEALED,
            "round_number": 2,
            "decision": DECISION_PENDING,
            "allowance_pct": None,
            "allowed_credit_cents": 0,
        },
    )
    assert_instant_eq(appealed["submitted_at"], CLOCK_AT_APPEAL_R3I2, "submitted_at")
    assert_end_of_day(appealed["adjudication_due_at"], "adjudication_due_at")
    assert_instant_eq(
        appealed["adjudication_due_at"], DUE_AT_APPEAL_ROUND, "adjudication_due_at"
    )

    reversed_charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        reversed_charge,
        {
            "status": CHARGE_DISPUTED,
            "credit_applied_cents": 0,
            "net_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert_charge_money_invariant(reversed_charge)
    reversed_invoice = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        reversed_invoice,
        {
            "status": INVOICE_PARTIALLY_DISPUTED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "total_credit_cents": 0,
            "total_net_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert reversed_invoice["version"] > invoice_after_round_1["version"]
    assert fx.get_customer(api, world["customer_id"])["credit_balance_cents"] == 0

    # Round two is taken up by a genuinely different adjudicator.
    round_2_review = fx.begin_review(api, dispute_id, ADJUDICATOR_B)
    assert_subset_equal(
        round_2_review,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "round_number": 2,
            "appeal_adjudicator_id": ADJUDICATOR_B,
            "first_level_adjudicator_id": ADJUDICATOR_A,
        },
    )

    round_2 = fx.decide(api, dispute_id, ADJUDICATOR_B, DECISION_ALLOWED, 1)
    assert_subset_equal(
        round_2,
        {
            "status": DISPUTE_DECIDED,
            "allowed_credit_cents": ROUND_2_CREDIT_CENTS,
            "round_number": 2,
        },
    )
    final_charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        final_charge,
        {
            "status": CHARGE_ADJUSTED,
            "credit_applied_cents": ROUND_2_CREDIT_CENTS,
            "net_amount_cents": 0,
        },
    )
    final_invoice = fx.get_invoice(api, invoice["id"])
    assert final_invoice["total_credit_cents"] == ROUND_2_CREDIT_CENTS
    assert final_invoice["total_net_cents"] == 0
    # The gross is an invariant of the whole eleven-transition walk.
    assert final_invoice["total_gross_cents"] == CYCLE_A_GROSS_CENTS
    assert_invoice_money_invariant(final_invoice)


def _agreement_month_fork(api, with_late_cycle):
    """One consignee, an OPEN 2026-08 agreement, and an ISSUED invoice.

    Every consignee gets an early release worth 2 ``early_release_days`` and no
    money; ``with_late_cycle`` adds the 3-chargeable-day, 47550-cent cycle that
    drives ``debit_days_incurred`` past the credit side and makes ``net_days``
    negative.  The early cycle is built first so that its release instant never
    overtakes the later cycle's spot in the PRD 3.4 switch-buffer guard.
    """
    world = fx.reference_world(api)
    agreement = fx.open_agreement(
        api, world["customer_id"], agreement_month=AGREEMENT_MONTH
    )
    early = fx.released_cycle(
        api,
        world,
        actual_at=CYCLE_EARLY_ACTUAL_AT,
        released_at=CYCLE_EARLY_RELEASE_AT,
    )
    assert early["early_release_days"] == EARLY_RELEASE_DAYS
    assert early["chargeable_days"] == 0
    late = fx.released_cycle_a(api, world) if with_late_cycle else None
    invoice = fx.issued_invoice(api, world)
    return world, agreement, early, late, invoice


# ===========================================================================
# instance: average_agreement_fork_reconciled_versus_forfeited_side_effects
# ===========================================================================
def test_reconcile_on_a_non_negative_ledger_touches_no_money_at_all(api):
    """``net_days`` of 2 honours the credit and leaves the invoice untouched.

    PRD 3.7: "When `net_days` is zero or positive the agreement moves
    `OPEN -> RECONCILED` and its `agreement_credit_cents` is frozen at the value
    landed at issue time - the credit is honoured."

    Design: Difficulty/non_linear_state_machine/average_agreement_fork_reconciled_versus_forfeited_side_effects
    """
    world, agreement, _early, _late, invoice = _agreement_month_fork(api, False)

    before = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert_subset_equal(
        before,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": EARLY_RELEASE_DAYS,
            "debit_days_incurred": 0,
            "net_days": RECONCILE_NET_DAYS,
            "agreement_credit_cents": 0,
        },
    )
    assert_subset_equal(
        invoice,
        {
            "status": INVOICE_ISSUED,
            "total_gross_cents": 0,
            "total_credit_cents": 0,
            "total_net_cents": 0,
            "agreement_credit_cents": 0,
            "attached_charge_count": 1,
        },
    )

    reconciled = fx.reconcile(api, agreement["id"])
    assert_subset_equal(
        reconciled,
        {
            "status": AGREEMENT_RECONCILED,
            "credit_days_earned": EARLY_RELEASE_DAYS,
            "debit_days_incurred": 0,
            "net_days": RECONCILE_NET_DAYS,
            "agreement_credit_cents": 0,
        },
    )
    assert reconciled["version"] == before["version"] + 1

    # The RECONCILED branch has no blast radius: the invoice did not even move.
    after = fx.get_invoice(api, invoice["id"])
    assert after["version"] == invoice["version"]
    assert_subset_equal(
        after,
        {
            "status": INVOICE_ISSUED,
            "total_gross_cents": 0,
            "total_credit_cents": 0,
            "agreement_credit_cents": 0,
        },
    )
    assert fx.get_customer(api, world["customer_id"])["credit_balance_cents"] == 0


def test_forfeit_on_a_negative_ledger_unwinds_four_entities(api):
    """``net_days`` of -1 zeroes the credit and re-derives charge, invoice and consignee.

    PRD 3.7: "When `net_days` is negative the agreement moves `OPEN -> FORFEITED`:
    `agreement_credit_cents` is zeroed, the credit already landed on the month's
    charge lines is reversed, every invoice touched by that reversal is re-derived
    - totals and compound status alike - and has its `version` incremented, and
    the consignee's `credit_balance_cents` is re-derived downward."

    Design: Difficulty/non_linear_state_machine/average_agreement_fork_reconciled_versus_forfeited_side_effects
    """
    world, agreement, _early, late, invoice = _agreement_month_fork(api, True)

    before = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert_subset_equal(
        before,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": EARLY_RELEASE_DAYS,
            "debit_days_incurred": FORFEIT_DEBIT_DAYS,
            "net_days": FORFEIT_NET_DAYS,
            "agreement_credit_cents": FORFEIT_CREDIT_CENTS,
        },
    )
    assert_subset_equal(
        invoice,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "agreement_credit_cents": FORFEIT_CREDIT_CENTS,
            "total_credit_cents": FORFEIT_CREDIT_CENTS,
            "total_net_cents": FORFEIT_NET_CENTS,
        },
    )
    credited_line = fx.charge_of_cycle(api, late["id"])
    assert_subset_equal(
        credited_line,
        {
            "status": CHARGE_FINAL,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
            "credit_applied_cents": FORFEIT_CREDIT_CENTS,
            "net_amount_cents": FORFEIT_NET_CENTS,
        },
    )
    assert (
        fx.get_customer(api, world["customer_id"])["credit_balance_cents"]
        == FORFEIT_CREDIT_CENTS
    )

    forfeited = fx.reconcile(api, agreement["id"])
    assert_subset_equal(
        forfeited,
        {
            "status": AGREEMENT_FORFEITED,
            "agreement_credit_cents": 0,
            "credit_days_earned": EARLY_RELEASE_DAYS,
            "debit_days_incurred": FORFEIT_DEBIT_DAYS,
            "net_days": FORFEIT_NET_DAYS,
        },
    )

    reversed_line = fx.charge_of_cycle(api, late["id"])
    assert_subset_equal(
        reversed_line,
        {
            "status": CHARGE_FINAL,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
            "credit_applied_cents": 0,
            "net_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert_charge_money_invariant(reversed_line)

    unwound = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        unwound,
        {
            "status": INVOICE_ISSUED,
            "agreement_credit_cents": 0,
            "total_credit_cents": 0,
            "total_net_cents": CYCLE_A_GROSS_CENTS,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert unwound["version"] == invoice["version"] + 1
    assert_invoice_money_invariant(unwound)
    assert fx.get_customer(api, world["customer_id"])["credit_balance_cents"] == 0
