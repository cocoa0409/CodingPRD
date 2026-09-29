"""Compensating cascades and the quantities they must conserve.

Two conserved quantities are exercised here. The first is MONEY — a program's
`committed_cents` — whose compensation is deliberately asymmetric: recovering a
chargeback returns the commitment to exactly its pre-approval value while
writing the same chargeback off leaves the amount committed forever. The second
is UNITS — an objective's `achieved_units` — whose compensation is symmetric and
must drag every derived stair-step figure back with it.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, AUG_31, BUILD_FROM, BUILD_TO, SEP_01

SEP_10 = "2026-09-10T00:00:00.000Z"
AUG_05 = "2026-08-05T00:00:00.000Z"
CLAIM_AMOUNT_CENTS = 150000

MX5_WEST_CASH = {
    "model_code": "MX5",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["CASH"],
}


# --- MONEY: committed_cents ---------------------------------------------------


def _setup_money_conservation_case():
    """An ACTIVE per-unit cash program, an ACTIVE WEST dealer, an OPEN WEST batch
    that is never disbursed, and two VALIDATED MX5 cash deliveries. No accrual is
    ever run, so every accrual row observed later is a cascade reversal."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-890",
        name="Copperfield Motors",
        region_code="WEST",
        historical_volume_units=9,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CMP-CASH",
            name="Compensating Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=CLAIM_AMOUNT_CENTS,
            budget_cents=40000000,
            stack_group="CMP",
            priority_rank=141,
            accrual_method="UNIT_BASED",
        ),
        rules=[dict(MX5_WEST_CASH)],
    )
    batch = fx.open_batch(
        batch_code="CMP-B1",
        region_code="WEST",
        period_start=AUG_01,
        period_end=AUG_31,
        scheduled_pay_date=SEP_10,
    )
    fx.set_clock(AUG_05)
    deliveries = []
    for build_date in ("2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z"):
        delivery = fx.report_delivery(
            dealer["id"],
            model_code="MX5",
            trim_code="BASE",
            build_date=build_date,
            msrp_cents=3200000,
            sale_date=AUG_05,
            customer_region_code="WEST",
            deal_type="CASH",
        )
        deliveries.append(fx.validate_delivery(delivery["id"]))
    return {
        "dealer": dealer,
        "program": program,
        "batch": batch,
        "deliveries": deliveries,
    }


def _approve_queue_and_unwind(ctx, delivery):
    """Submit one claim on the delivery, approve it, queue it in the open batch and
    then unwind the delivery, which is the only payment state from which the
    cascade can charge the claim back. Returns the observations along the way."""
    claim = fx.submit_claim(
        ctx["dealer"]["id"],
        delivery["id"],
        ctx["program"]["id"],
        CLAIM_AMOUNT_CENTS,
    )
    approved = fx.adjudicate_claim(claim["id"])
    fx.schedule_claims(ctx["batch"]["id"], [claim["id"]])
    committed_after_approve = fx.read_spend_summary(ctx["program"]["id"])
    fx.unwind_delivery(delivery["id"], headers=fx.ADJUDICATOR)
    chargebacks = fx.list_chargebacks(claim["id"])
    a.assert_list_length(chargebacks, 1, "chargebacks of the charged-back claim")
    return {
        "claim": approved,
        "committed_after_approve": committed_after_approve,
        "chargeback": chargebacks[0],
        "committed_after_unwind": fx.read_spend_summary(ctx["program"]["id"]),
    }


def test_recovering_the_chargeback_restores_committed_cents_to_its_exact_baseline():
    """Approve, queue, unwind, recover — and the program's commitment is back at
    the exact figure it held before the claim was ever approved.

    PRD: "The program's `committed_cents` returns to exactly the value it held
    before the claim was approved: the charged-back claim leaves the committed
    input set, and a recovered chargeback contributes nothing."
    PRD: "Recovering it moves the chargeback `PENDING → RECOVERED`, stamps
    `recovered_at` from the logical clock, subtracts its `amount_cents` from the
    dealer's `open_chargeback_cents`, and recomputes the program's
    `committed_cents` — which, because the charged-back claim has already left the
    committed claim set and a recovered chargeback contributes nothing of its own,
    returns the program's commitment to exactly its pre-approval value."
    PRD: "Every chargeback created by a cascade appends exactly one accrual-ledger
    row of type `REVERSAL` whose `reversal_cents` equals that chargeback's
    `amount_cents` — never zero rows, never two rows, and never a different
    amount."

    Design: Difficulty/compensating_invariant/recovered_chargeback_restores_committed_cents_but_write_off_deliberately_does_not
    """
    ctx = _setup_money_conservation_case()
    a.assert_dealer_money(ctx["dealer"], paid_cents=0, open_chargeback_cents=0)
    baseline = fx.read_spend_summary(ctx["program"]["id"])
    a.assert_money(baseline, "committed_cents", 0)

    run = _approve_queue_and_unwind(ctx, ctx["deliveries"][0])

    a.assert_money(run["claim"], "approved_amount_cents", CLAIM_AMOUNT_CENTS)
    a.assert_money(run["committed_after_approve"], "committed_cents", 150000)
    # The full-recovery reason takes the claim's approved amount verbatim.
    a.assert_money(run["chargeback"], "amount_cents", 150000)
    a.assert_status(run["chargeback"], "PENDING")
    assert run["chargeback"]["recovered_at"] is None, run["chargeback"]
    a.assert_claim_dimensions(
        fx.read_claim(run["claim"]["id"]), "VALIDATED", "CHARGED_BACK"
    )
    # A PENDING chargeback contributes nothing, so the money is already released.
    a.assert_money(run["committed_after_unwind"], "committed_cents", 0)
    a.assert_dealer_money(
        fx.read_dealer(ctx["dealer"]["id"]), paid_cents=0, open_chargeback_cents=150000
    )

    recovered = fx.recover_chargeback(run["chargeback"]["id"])
    a.assert_status(recovered, "RECOVERED")
    assert recovered["recovered_at"] == AUG_05, recovered

    after = fx.read_spend_summary(ctx["program"]["id"])
    a.assert_money(after, "committed_cents", 0)
    assert after["committed_cents"] == baseline["committed_cents"], (
        "committed_cents must return to its pre-approval value exactly, not merely "
        f"decrease: baseline {baseline['committed_cents']}, got {after['committed_cents']}"
    )
    a.assert_money(after, "paid_cents", 0)
    a.assert_int_field(after, "claimed_units", 0)
    # The accrual ledger is append-only: the REVERSAL row survives the recovery.
    a.assert_money(after, "accrued_budget_cents", -150000)
    a.assert_dealer_money(
        fx.read_dealer(ctx["dealer"]["id"]), paid_cents=0, open_chargeback_cents=0
    )


def test_writing_the_chargeback_off_deliberately_leaves_the_money_committed():
    """The identical path ending in a write-off instead of a recovery leaves the
    amount inside `committed_cents` forever, while the dealer's open exposure
    still falls to zero on both branches.

    PRD: "A chargeback that is instead written off deliberately breaks that
    symmetry — the amount stays inside `committed_cents`, because written-off
    money is spend the automaker never gets back."
    PRD: "Writing it off moves the chargeback `PENDING → WRITTEN_OFF`, optionally
    recording a `write_off_note`, likewise stamps `recovered_at` and likewise
    subtracts `amount_cents` from the dealer's `open_chargeback_cents` — but it
    deliberately **leaves** the amount inside the program's `committed_cents`,
    because a written-off chargeback is money the automaker is never getting back
    and the program's books must keep carrying it."
    PRD: "A dealer's `open_chargeback_cents` is at all times the sum of
    `amount_cents` over the chargebacks of that dealer's claims whose `status` is
    `PENDING`."

    Design: Difficulty/compensating_invariant/recovered_chargeback_restores_committed_cents_but_write_off_deliberately_does_not
    """
    ctx = _setup_money_conservation_case()

    # Branch one, replayed only to establish that the ledger is back at zero and
    # that the two branches differ in nothing but the chargeback's terminal state.
    first = _approve_queue_and_unwind(ctx, ctx["deliveries"][0])
    fx.recover_chargeback(first["chargeback"]["id"])
    a.assert_money(fx.read_spend_summary(ctx["program"]["id"]), "committed_cents", 0)

    second = _approve_queue_and_unwind(ctx, ctx["deliveries"][1])
    a.assert_money(second["committed_after_approve"], "committed_cents", 150000)
    a.assert_money(second["committed_after_unwind"], "committed_cents", 0)
    a.assert_money(second["chargeback"], "amount_cents", 150000)

    written_off = fx.write_off_chargeback(second["chargeback"]["id"])
    a.assert_status(written_off, "WRITTEN_OFF")

    after = fx.read_spend_summary(ctx["program"]["id"])
    # The second summation term re-adds every WRITTEN_OFF chargeback, so the
    # compensation is incomplete here by exactly the written-off amount.
    a.assert_money(after, "committed_cents", 150000)
    assert (
        after["committed_cents"] - second["committed_after_unwind"]["committed_cents"]
        == second["chargeback"]["amount_cents"]
    ), after
    a.assert_money(after, "paid_cents", 0)
    a.assert_int_field(after, "claimed_units", 0)
    a.assert_money(after, "accrued_budget_cents", -300000)
    a.assert_dealer_money(
        fx.read_dealer(ctx["dealer"]["id"]), paid_cents=0, open_chargeback_cents=0
    )


# --- UNITS: achieved_units and everything derived from it ---------------------

AUG_06 = "2026-08-06T00:00:00.000Z"
STAIR_TIERS = [
    {"tier_index": 1, "threshold_bps": 5000, "per_unit_bonus_cents": 30000},
    {"tier_index": 2, "threshold_bps": 10000, "per_unit_bonus_cents": 50000},
]


def _setup_unit_conservation_case():
    """A MARGINAL stair-step program, a dealer whose objective is 4 units, and
    three reported MX5 cash deliveries of which the first two are validated. The
    objective stays in PROPOSED throughout, which isolates the unit invariant from
    the protest cascade, and no claim is ever filed, which isolates it from the
    money invariant."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="D-900U",
        name="Unit Invariant Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CMP-STAIR",
            name="Compensating Stair Step",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=30000000,
            stack_group="CMPS",
            priority_rank=151,
            tier_schedule=STAIR_TIERS,
            tier_bonus_mode="MARGINAL",
        ),
        rules=[dict(MX5_WEST_CASH)],
    )
    objective = fx.assign_objective(program["id"], dealer["id"], stretch_bps=0)
    fx.set_clock(AUG_06)
    deliveries = []
    for build_date, sale_date in (
        ("2026-06-01T00:00:00.000Z", "2026-08-03T00:00:00.000Z"),
        ("2026-06-02T00:00:00.000Z", "2026-08-04T00:00:00.000Z"),
        ("2026-06-03T00:00:00.000Z", AUG_05),
    ):
        deliveries.append(
            fx.report_delivery(
                dealer["id"],
                model_code="MX5",
                trim_code="BASE",
                build_date=build_date,
                msrp_cents=3100000,
                sale_date=sale_date,
                customer_region_code="WEST",
                deal_type="CASH",
            )
        )
    fx.validate_delivery(deliveries[0]["id"])
    fx.validate_delivery(deliveries[1]["id"])
    return {
        "dealer": dealer,
        "program": program,
        "objective": objective,
        "deliveries": deliveries,
    }


def test_the_third_validated_unit_stays_in_band_one_and_doubles_the_payout():
    """Two validated units sit exactly on the first threshold; the third stays
    inside the same marginal band and therefore doubles the payout rather than
    re-rating anything.

    PRD: "`attainment_bps` is the objective's `achieved_units` multiplied by
    10000, divided by its `objective_units`, and **floored**; because
    `objective_units` is at least 1 by construction, this division can never
    fail."
    PRD: "`tier_attained` is the highest `tier_index` among the program's
    `tier_schedule` entries whose `threshold_bps` is **at or below**
    `attainment_bps`, and it is 0 when no tier qualifies."
    PRD: "Under `MARGINAL`, `payout_cents` starts at 0 and accumulates one band at
    a time over the tiers whose `tier_index` is at or below `tier_attained`, taken
    in ascending `tier_index`: the band's upper unit is one less than the unit
    threshold of the next tier in the schedule, or unbounded when the tier is the
    last one; the band's unit count is the smaller of `achieved_units` and that
    upper unit, minus the tier's own unit threshold, plus one; and the band
    contributes its unit count multiplied by that tier's `per_unit_bonus_cents`."

    Design: Difficulty/compensating_invariant/unwinding_a_delivery_restores_achieved_units_and_the_whole_stair_step_payout
    """
    ctx = _setup_unit_conservation_case()
    a.assert_int_field(ctx["objective"], "objective_units", 4)
    a.assert_objective_attainment(
        ctx["objective"],
        achieved_units=0,
        attainment_bps=0,
        tier_attained=0,
        payout_cents=0,
    )

    before = fx.read_objective(ctx["objective"]["id"])
    a.assert_objective_attainment(
        before,
        achieved_units=2,
        attainment_bps=5000,
        tier_attained=1,
        payout_cents=30000,
    )

    validated = validate_success(
        api_client.validate_delivery(ctx["deliveries"][2]["id"], fx.VALIDATOR)
    )
    a.assert_status(validated, "VALIDATED")

    after = fx.read_objective(ctx["objective"]["id"])
    a.assert_objective_attainment(
        after,
        achieved_units=3,
        attainment_bps=7500,
        tier_attained=1,
        payout_cents=60000,
    )


def test_unwinding_the_delivery_restores_the_units_and_every_derived_figure():
    """The unwind puts `achieved_units` back at its exact prior value and drags
    `attainment_bps`, `tier_attained` and `payout_cents` back with it — including
    all the way below the first threshold.

    PRD: "Validating a retail delivery and then unwinding it returns the affected
    objective's `achieved_units` to exactly its prior value, and therefore returns
    `attainment_bps`, `tier_attained` and `payout_cents` to their prior values as
    well."
    PRD: "Because `achieved_units` is recomputed from its defining input set
    rather than adjusted blindly, validating a delivery and then unwinding it
    returns the objective to exactly the position it held before."

    Design: Difficulty/compensating_invariant/unwinding_a_delivery_restores_achieved_units_and_the_whole_stair_step_payout
    """
    ctx = _setup_unit_conservation_case()
    prior = fx.read_objective(ctx["objective"]["id"])
    a.assert_objective_attainment(
        prior,
        achieved_units=2,
        attainment_bps=5000,
        tier_attained=1,
        payout_cents=30000,
    )

    fx.validate_delivery(ctx["deliveries"][2]["id"])
    crossed = fx.read_objective(ctx["objective"]["id"])
    a.assert_objective_attainment(
        crossed,
        achieved_units=3,
        attainment_bps=7500,
        tier_attained=1,
        payout_cents=60000,
    )

    unwound = fx.unwind_delivery(ctx["deliveries"][2]["id"], headers=fx.ADJUDICATOR)
    a.assert_status(unwound, "UNWOUND")

    restored = fx.read_objective(ctx["objective"]["id"])
    a.assert_objective_attainment(
        restored,
        achieved_units=2,
        attainment_bps=5000,
        tier_attained=1,
        payout_cents=30000,
    )
    for field in ("achieved_units", "attainment_bps", "tier_attained", "payout_cents"):
        assert restored[field] == prior[field], (
            f"{field} was not restored to its prior value: prior {prior[field]!r}, "
            f"got {restored[field]!r}"
        )
    # No transition and no chargeback happened: the unwound delivery carried no claim.
    a.assert_status(restored, "PROPOSED")
    a.assert_money(restored, "paid_payout_cents", 0)
    summary = fx.read_spend_summary(ctx["program"]["id"])
    a.assert_money(summary, "committed_cents", 0)
    a.assert_int_field(summary, "claimed_units", 0)
    a.assert_money(summary, "per_unit_spend_cents", 0)
    a.assert_money(summary, "accrued_budget_cents", 0)

    # The invariant holds below the first threshold too.
    fx.unwind_delivery(ctx["deliveries"][0]["id"], headers=fx.ADJUDICATOR)
    below = fx.read_objective(ctx["objective"]["id"])
    a.assert_objective_attainment(
        below,
        achieved_units=1,
        attainment_bps=2500,
        tier_attained=0,
        payout_cents=0,
    )
