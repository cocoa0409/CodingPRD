"""Two depth-four cascades that end in the accrual ledger.

The first is triggered by unwinding a validated delivery and is a full reversal:
the claim is charged back, the chargeback is minted by the transition rather than
by the caller, the ledger gains a gross REVERSAL row and the program's accrued
budget goes negative by exactly the reserve that had been withheld. The second is
triggered by upholding a protest against a finalized, already-paid objective and
is a partial recovery: the claim stays PAID while its approved amount is cut.
"""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, AUG_31, SEP_01, iso_day

AUG_02 = iso_day(2026, 8, 2)
AUG_03 = iso_day(2026, 8, 3)
AUG_04 = iso_day(2026, 8, 4)
AUG_05 = iso_day(2026, 8, 5)
AUG_24 = iso_day(2026, 8, 24)
AUG_25 = iso_day(2026, 8, 25)
SEP_10 = iso_day(2026, 9, 10)

STAIR_TIER_SCHEDULE = [
    {"tier_index": 1, "threshold_bps": 5000, "per_unit_bonus_cents": 30000},
    {"tier_index": 2, "threshold_bps": 10000, "per_unit_bonus_cents": 50000},
]

PROTEST_REASON = (
    "Four fleet units were omitted from the historical basis; the objective was "
    "set too low."
)


# --- Shared setup for the unwind cascade --------------------------------------


def _setup_scheduled_claim_with_accrual() -> dict:
    """An ACTIVE UNIT_BASED customer-cash program paying 150000 cents per unit,
    one VALIDATED delivery sold on 2026-08-05, its claim approved for 150000 and
    SCHEDULED inside an OPEN WEST batch, and one ACCRUAL row already run for
    2026-08. The clock ends at 2026-08-25, the instant the unwind fires."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Ironwood Auto Center",
        region_code="WEST",
        historical_volume_units=9,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            name="August Cascade Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=150000,
            budget_cents=100000000,
            stack_group="AUG-CASH",
            priority_rank=12,
            accrual_method="UNIT_BASED",
        )
    )
    batch = fx.open_batch(
        region_code="WEST",
        period_start=AUG_01,
        period_end=AUG_31,
        scheduled_pay_date=SEP_10,
    )
    fx.set_clock(AUG_05)
    delivery = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date=iso_day(2026, 6, 6),
        msrp_cents=3300000,
        sale_date=AUG_05,
        customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 150000)
    fx.adjudicate_claim(claim["id"], "APPROVE")
    scheduled_batch = fx.schedule_claims(batch["id"], [claim["id"]])
    fx.set_clock(AUG_24)
    accrual = fx.run_accrual(program["id"], "2026-08")
    fx.set_clock(AUG_25)
    return {
        "program": program,
        "dealer": dealer,
        "batch": scheduled_batch,
        "delivery": delivery,
        "claim": claim,
        "accrual": accrual,
    }


def _assert_unwind_preconditions(ctx: dict) -> None:
    """One validated unit accrued net of the 275 bps cancellation reserve, and
    that unit's money queued in the batch."""
    a.assert_accrual_shape(ctx["accrual"])
    assert ctx["accrual"]["entry_type"] == "ACCRUAL", ctx["accrual"]
    a.assert_money(ctx["accrual"], "accrued_cents", 145875)
    a.assert_int_field(ctx["batch"], "claim_count", 1)
    a.assert_money(ctx["batch"], "total_cents", 150000)


# --- The unwind cascade: claim, chargeback, accrual row -----------------------


def test_unwind_charges_back_the_claim_and_mints_a_system_raised_chargeback():
    """Links one and two: the unwind moves the scheduled claim to CHARGED_BACK
    and the transition itself mints the full-recovery UNWOUND_DEAL chargeback,
    whose created_by_user_id is null because no auditor raised it directly.

    PRD: "Link one moves every claim on this delivery whose `payment_status` is
    `SCHEDULED` or `PAID` to `payment_status` `CHARGED_BACK` and clears each one's
    `payment_batch_id` to null, which also forces recomputation of the former
    batch's `claim_count` and `total_cents`. Link two, caused by link one, creates
    one chargeback per charged-back claim with `reason` `UNWOUND_DEAL`." "A
    directly raised chargeback records the raising auditor's `X-User-ID` in
    `created_by_user_id`, while a chargeback born from a cascade — an unwind, an
    upheld protest or a retroactive repricing — leaves `created_by_user_id` null."

    Design: Difficulty/transitive_cascade/unwound_delivery_cascades_four_links_to_the_accrual_ledger
    """
    ctx = _setup_scheduled_claim_with_accrual()
    _assert_unwind_preconditions(ctx)

    unwound = fx.unwind_delivery(ctx["delivery"]["id"], headers=fx.ADJUDICATOR)
    a.assert_delivery_shape(unwound)
    a.assert_status(unwound, "UNWOUND")
    assert unwound["unwound_at"] == AUG_25, unwound

    claim = fx.read_claim(ctx["claim"]["id"])
    assert claim["payment_status"] == "CHARGED_BACK", claim
    a.assert_null_fields(claim, ["payment_batch_id"])
    # The historical approved amount is preserved on the charged-back claim.
    a.assert_money(claim, "approved_amount_cents", 150000)

    rows, meta = validate_paginated(
        api_client.list_chargebacks(ctx["claim"]["id"], fx.ADJUDICATOR)
    )
    a.assert_list_length(rows, 1, "chargebacks")
    assert meta["total_count"] == 1, meta
    chargeback = rows[0]
    a.assert_chargeback_shape(chargeback)
    assert chargeback["claim_id"] == ctx["claim"]["id"], chargeback
    assert chargeback["reason"] == "UNWOUND_DEAL", chargeback
    a.assert_money(chargeback, "amount_cents", 150000)
    a.assert_status(chargeback, "PENDING")
    a.assert_null_fields(chargeback, ["created_by_user_id", "recovered_at"])


def test_unwind_appends_one_gross_reversal_row_and_never_edits_the_accrual_row():
    """Link three: exactly one REVERSAL row is appended, carrying the
    chargeback's amount as reversal_cents and zero accrued_cents, while the
    original ACCRUAL row is left untouched beside it.

    PRD: "Link three, caused by link two, appends for each created chargeback
    exactly one accrual-ledger row with `entry_type` `REVERSAL` whose
    `reversal_cents` equals that chargeback's `amount_cents`, and recomputes the
    program's `accrued_budget_cents`." "The row's `accrued_cents` is the sum of
    the rounded line amounts, its `unit_basis` is the sum of the line unit counts,
    and its `reversal_cents` is 0 — an accrual row never carries a reversal, just
    as a reversal row always carries an `accrued_cents` of 0."

    Design: Difficulty/transitive_cascade/unwound_delivery_cascades_four_links_to_the_accrual_ledger
    """
    ctx = _setup_scheduled_claim_with_accrual()
    _assert_unwind_preconditions(ctx)

    fx.unwind_delivery(ctx["delivery"]["id"], headers=fx.ADJUDICATOR)

    reversals, reversal_meta = validate_paginated(
        api_client.list_accruals(
            ctx["program"]["id"], fx.CONTROLLER, {"entry_type": "REVERSAL"}
        )
    )
    a.assert_list_length(reversals, 1, "REVERSAL accrual rows")
    assert reversal_meta["total_count"] == 1, reversal_meta
    reversal = reversals[0]
    a.assert_accrual_shape(reversal)
    assert reversal["entry_type"] == "REVERSAL", reversal
    a.assert_money(reversal, "reversal_cents", 150000)
    a.assert_money(reversal, "accrued_cents", 0)

    every_row, every_meta = validate_paginated(
        api_client.list_accruals(ctx["program"]["id"], fx.CONTROLLER)
    )
    a.assert_list_length(every_row, 2, "accrual ledger rows")
    assert every_meta["total_count"] == 2, every_meta
    entry_types = [row["entry_type"] for row in every_row]
    assert entry_types == ["ACCRUAL", "REVERSAL"], every_row
    original = every_row[0]
    a.assert_money(original, "accrued_cents", 145875)
    a.assert_money(original, "reversal_cents", 0)


def test_unwind_drives_the_accrued_budget_negative_and_empties_every_ledger():
    """Link four: a gross reversal of 150000 against 145875 booked net of the
    reserve leaves an accrued residue of -4125, the committed ledger and the batch
    return to zero, and the dealer carries the pending chargeback instead.

    PRD: "A program's `accrued_budget_cents` is the sum of `accrued_cents` over
    all of its accrual-ledger rows minus the sum of `reversal_cents` over all of
    those rows, across both entry types and all periods, computed exactly with no
    rounding. Because accrual amounts are booked net of the 2.75 percent
    cancellation reserve while reversals are booked gross, unwinding every
    delivery of a month drives `accrued_budget_cents` negative by exactly the
    reserve that had been withheld."

    Design: Difficulty/transitive_cascade/unwound_delivery_cascades_four_links_to_the_accrual_ledger
    """
    ctx = _setup_scheduled_claim_with_accrual()
    _assert_unwind_preconditions(ctx)

    fx.unwind_delivery(ctx["delivery"]["id"], headers=fx.ADJUDICATOR)

    summary = fx.read_spend_summary(ctx["program"]["id"])
    a.assert_money(summary, "accrued_budget_cents", -4125)
    a.assert_money(summary, "committed_cents", 0)
    a.assert_money(summary, "paid_cents", 0)
    a.assert_int_field(summary, "claimed_units", 0)
    a.assert_money(summary, "per_unit_spend_cents", 0)

    batch = fx.read_batch(ctx["batch"]["id"])
    a.assert_int_field(batch, "claim_count", 0)
    a.assert_money(batch, "total_cents", 0)

    dealer = fx.read_dealer(ctx["dealer"]["id"])
    a.assert_dealer_money(dealer, 0, 150000)


# --- Shared setup for the upheld-protest cascade ------------------------------


def _setup_paid_stair_step_objective() -> dict:
    """A dealer whose historical basis of 4 units and zero market opportunity make
    basis_units and objective_units both 4, four VALIDATED August deliveries so the
    objective attains tier 2 and earns 110000, and a FINAL objective whose
    STAIR_STEP_BONUS claim has been approved, scheduled and paid out of a DISBURSED
    batch. No accrual has ever been run, so the accrued base starts at 0."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Harborview Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_stair_step_program_payload(
            name="August Stair Step Chargeback Path",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=50000000,
            stack_group="AUG-STAIR",
            priority_rank=43,
            tier_schedule=STAIR_TIER_SCHEDULE,
            tier_bonus_mode="MARGINAL",
        )
    )
    objective = fx.assign_objective(program["id"], dealer["id"], stretch_bps=0)
    fx.set_clock(AUG_04)
    deliveries = []
    for build_day, sale_date in ((1, AUG_02), (2, AUG_02), (3, AUG_03), (4, AUG_04)):
        deliveries.append(
            fx.report_delivery(
                dealer["id"],
                model_code="MX5",
                trim_code="BASE",
                build_date=iso_day(2026, 6, build_day),
                msrp_cents=3100000,
                sale_date=sale_date,
                customer_region_code="WEST",
                deal_type="CASH",
            )
        )
    for delivery in deliveries:
        fx.validate_delivery(delivery["id"])
    finalized = fx.finalize_objective(objective["id"])
    claim = fx.submit_claim(dealer["id"], deliveries[3]["id"], program["id"], 110000)
    approved = fx.adjudicate_claim(claim["id"], "APPROVE")
    batch = fx.open_batch(
        region_code="WEST",
        period_start=AUG_01,
        period_end=AUG_31,
        scheduled_pay_date=SEP_10,
    )
    fx.schedule_claims(batch["id"], [claim["id"]])
    fx.lock_batch(batch["id"])
    fx.disburse_batch(batch["id"], at=SEP_10)
    return {
        "program": program,
        "dealer": dealer,
        "objective": objective,
        "deliveries": deliveries,
        "finalized": finalized,
        "claim": claim,
        "approved": approved,
        "batch": batch,
        "paid": fx.read_objective(objective["id"]),
    }


def _assert_paid_stair_step_preconditions(ctx: dict) -> None:
    """The objective is FINAL at full attainment and its bonus has been paid:
    MARGINAL pays 2 units in band 1 at 30000 plus 1 unit in band 2 at 50000."""
    assert ctx["claim"]["claim_type"] == "STAIR_STEP_BONUS", ctx["claim"]
    a.assert_status(ctx["finalized"], "FINAL")
    a.assert_objective_attainment(ctx["finalized"], 4, 10000, 2, 110000)
    a.assert_money(ctx["approved"], "approved_amount_cents", 110000)
    a.assert_money(ctx["paid"], "paid_payout_cents", 110000)


def _uphold_the_protest(ctx: dict) -> dict:
    """The dealer contests the frozen objective with a basis of 8 units and the
    field manager upholds it — the FINAL -> PROTESTED -> REVISED walk."""
    objective_id = ctx["objective"]["id"]
    protest = fx.file_protest(
        objective_id, ctx["dealer"]["id"], 8, reason=PROTEST_REASON
    )
    protested = fx.read_objective(objective_id)
    resolved = fx.resolve_protest(
        objective_id,
        protest["id"],
        "UPHELD",
        expected_objective_version=protested["version"],
    )
    return {"protest": protest, "protested": protested, "resolved": resolved}


# --- The upheld-protest cascade: units, partial chargeback, ledgers ------------


def test_upheld_protest_rewrites_the_basis_and_recomputes_the_stair_step_payout():
    """Links one and two: the upheld basis of 8 units moves the denominator, so
    attainment floors to 5000 bps, the tier drops to 1 and the marginal payout
    falls from 110000 to 30000 with the objective left in REVISED.

    PRD: "**Upholding** the protest moves the protest `OPEN → UPHELD` and the
    objective `PROTESTED → REVISED`, and runs a four-link cascade." "First,
    `basis_units` is set to the dealer's `historical_volume_units` — this is the
    volume basis the objective actually rests on, and the only field that a later
    upheld protest rewrites." "`attainment_bps` is the
    objective's `achieved_units` multiplied by 10000, divided by its
    `objective_units`, and **floored**; because `objective_units` is at least 1 by
    construction, this division can never fail." "`tier_attained` is the highest
    `tier_index` among the program's `tier_schedule` entries whose `threshold_bps`
    is **at or below** `attainment_bps`, and it is 0 when no tier qualifies."

    Design: Difficulty/transitive_cascade/upheld_protest_on_finalized_objective_cascades_to_partial_chargeback
    """
    ctx = _setup_paid_stair_step_objective()
    _assert_paid_stair_step_preconditions(ctx)

    walk = _uphold_the_protest(ctx)
    a.assert_int_field(walk["protest"], "round_index", 1)
    a.assert_status(walk["protested"], "PROTESTED")
    a.assert_status(walk["resolved"], "UPHELD")
    a.assert_int_field(walk["resolved"], "resolved_units", 8)

    revised = fx.read_objective(ctx["objective"]["id"])
    a.assert_int_field(revised, "basis_units", 8)
    a.assert_int_field(revised, "objective_units", 8)
    # floor(4 * 10000 / 8) == 5000, and band 1 spans units 4..7 at 30000 each.
    a.assert_objective_attainment(revised, 4, 5000, 1, 30000)
    a.assert_status(revised, "REVISED")


def test_upheld_protest_raises_a_partial_chargeback_and_leaves_the_claim_paid():
    """Link three: the 80000 overpayment is recovered by an OBJECTIVE_REVISED
    chargeback while the claim deliberately stays PAID with its approved amount
    and the objective's paid payout both cut to 30000.

    PRD: "Link three follows from link two and only fires when the objective has
    already been paid more than it now earns: if `paid_payout_cents` is strictly
    greater than the newly computed `payout_cents`, a chargeback is raised against
    the objective's stair-step bonus claim with `reason` `OBJECTIVE_REVISED` and an
    `amount_cents` equal to `paid_payout_cents` minus the new `payout_cents`,
    entering in `status` `PENDING`; that claim's `approved_amount_cents` and the
    objective's `paid_payout_cents` are **both** reduced to the new
    `payout_cents`, and the claim deliberately **keeps** its `payment_status` of
    `PAID`, because this is a partial recovery of an overpayment rather than a full
    reversal of a payment."

    Design: Difficulty/transitive_cascade/upheld_protest_on_finalized_objective_cascades_to_partial_chargeback
    """
    ctx = _setup_paid_stair_step_objective()
    _assert_paid_stair_step_preconditions(ctx)

    _uphold_the_protest(ctx)

    rows, meta = validate_paginated(
        api_client.list_chargebacks(ctx["claim"]["id"], fx.ADJUDICATOR)
    )
    a.assert_list_length(rows, 1, "chargebacks")
    assert meta["total_count"] == 1, meta
    chargeback = rows[0]
    a.assert_chargeback_shape(chargeback)
    assert chargeback["reason"] == "OBJECTIVE_REVISED", chargeback
    # 110000 paid against 30000 now earned.
    a.assert_money(chargeback, "amount_cents", 80000)
    a.assert_status(chargeback, "PENDING")
    a.assert_null_fields(chargeback, ["created_by_user_id", "recovered_at"])

    claim = fx.read_claim(ctx["claim"]["id"])
    a.assert_claim_dimensions(claim, "VALIDATED", "PAID")
    a.assert_money(claim, "approved_amount_cents", 30000)

    revised = fx.read_objective(ctx["objective"]["id"])
    a.assert_money(revised, "paid_payout_cents", 30000)


def test_upheld_protest_recomputes_the_program_and_dealer_money_ledgers():
    """Link four: the reduced approved amount recomputes the program's committed
    and paid ledgers to 30000 and the single appended REVERSAL row of 80000 drives
    the accrued budget to -80000 against a zero accrual base.

    PRD: "Link four follows from link three: the reduced `approved_amount_cents`
    forces recomputation of the program's `committed_cents`, `paid_cents` and
    `per_unit_spend_cents`, and appends one accrual-ledger row with `entry_type`
    `REVERSAL` whose `reversal_cents` equals the chargeback's `amount_cents`, which
    in turn recomputes the program's `accrued_budget_cents`."

    Design: Difficulty/transitive_cascade/upheld_protest_on_finalized_objective_cascades_to_partial_chargeback
    """
    ctx = _setup_paid_stair_step_objective()
    _assert_paid_stair_step_preconditions(ctx)

    _uphold_the_protest(ctx)

    summary = fx.read_spend_summary(ctx["program"]["id"])
    a.assert_money(summary, "committed_cents", 30000)
    a.assert_money(summary, "paid_cents", 30000)
    a.assert_money(summary, "accrued_budget_cents", -80000)
    # A STAIR_STEP_BONUS claim is not a UNIT_INCENTIVE claim, so no unit is counted.
    a.assert_int_field(summary, "claimed_units", 0)
    a.assert_money(summary, "per_unit_spend_cents", 0)

    rows, meta = validate_paginated(
        api_client.list_accruals(
            ctx["program"]["id"], fx.CONTROLLER, {"entry_type": "REVERSAL"}
        )
    )
    a.assert_list_length(rows, 1, "REVERSAL accrual rows")
    assert meta["total_count"] == 1, meta
    a.assert_money(rows[0], "reversal_cents", 80000)
    a.assert_money(rows[0], "accrued_cents", 0)

    dealer = fx.read_dealer(ctx["dealer"]["id"])
    a.assert_dealer_money(dealer, 30000, 80000)
