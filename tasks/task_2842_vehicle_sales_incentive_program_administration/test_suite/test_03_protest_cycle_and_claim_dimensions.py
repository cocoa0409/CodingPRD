"""Non-linear state machines on two different entities.

The dealer objective walks a bounded cycle — PROPOSED to PROTESTED to REVISED
and back into PROTESTED — whose exit state on a denial is decided by the
protest's round_index alone. The claim, by contrast, carries two dimensions
that advance independently on the same row, coupled only by the guard that
payment may not leave UNPAID before validation reaches VALIDATED.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ApiErrorId, api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, AUG_31, SEP_01, iso_day

AUG_05 = iso_day(2026, 8, 5)
SEP_10 = iso_day(2026, 9, 10)

CYCLE_TIER_SCHEDULE = [
    {"tier_index": 1, "threshold_bps": 5000, "per_unit_bonus_cents": 30000},
    {"tier_index": 2, "threshold_bps": 10000, "per_unit_bonus_cents": 50000},
]

ROUND_1_REASON = (
    "Two 2025 fleet deliveries were double counted in the historical basis."
)
ROUND_2_REASON = (
    "Second protest: two additional units were courtesy transfers, not retail."
)
ROUND_3_REASON = "Third protest, must be refused."


# --- Shared setup for the objective protest cycle ----------------------------


def _setup_protest_cycle_objective() -> dict:
    """A dealer with a historical basis of 16 units and a market opportunity of
    1500 bps, one ACTIVE stair-step program, and a PROPOSED objective carrying a
    stretch of 1000 bps. No delivery is ever reported, so achieved_units stays 0
    and the payout arithmetic never masks the state transitions."""
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Cascade Motor Sales",
        region_code="WEST",
        historical_volume_units=16,
        market_opportunity_bps=1500,
    )
    program = fx.create_active_program(
        payload=f.create_stair_step_program_payload(
            name="August Stair Step Cycle",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=50000000,
            stack_group="AUG-STAIR",
            priority_rank=42,
            tier_schedule=CYCLE_TIER_SCHEDULE,
            tier_bonus_mode="MARGINAL",
        )
    )
    objective = fx.assign_objective(program["id"], dealer["id"], stretch_bps=1000)
    return {"program": program, "dealer": dealer, "objective": objective}


def _drive_cycle_into_round_two(ctx: dict) -> dict:
    """File the round 1 protest, uphold it, then file the round 2 protest — the
    PROPOSED -> PROTESTED -> REVISED -> PROTESTED walk."""
    objective_id = ctx["objective"]["id"]
    dealer_id = ctx["dealer"]["id"]
    protest_1 = fx.file_protest(objective_id, dealer_id, 12, reason=ROUND_1_REASON)
    after_protest_1 = fx.read_objective(objective_id)
    resolved_1 = fx.resolve_protest(
        objective_id,
        protest_1["id"],
        "UPHELD",
        expected_objective_version=after_protest_1["version"],
    )
    after_uphold = fx.read_objective(objective_id)
    protest_2 = fx.file_protest(objective_id, dealer_id, 10, reason=ROUND_2_REASON)
    return {
        "protest_1": protest_1,
        "resolved_1": resolved_1,
        "after_protest_1": after_protest_1,
        "after_uphold": after_uphold,
        "protest_2": protest_2,
    }


# --- The bounded protest cycle on DealerObjective -----------------------------


def test_protest_cycle_reenters_protested_from_revised_with_round_index_two():
    """A round 2 protest re-enters the cycle from REVISED, and the upheld round 1
    protest has already rewritten the basis and the unit target.

    PRD: "Filing creates a protest row with `status` `OPEN`, an `objective_id`
    naming the objective from the path, and a `round_index` equal to the
    objective's `protest_round` plus one — so the first protest is round 1 and
    the second is round 2." "The objective's `protest_round` increments by 1, its
    own `version` increments by 1, and it moves into `PROTESTED` from whichever
    of the three admissible states it held: `PROPOSED → PROTESTED` for a
    first-round protest of a fresh objective, `REVISED → PROTESTED` for a
    second-round protest of an objective already once revised, and
    `FINAL → PROTESTED` when a dealer contests an objective that had been
    frozen."

    Design: Difficulty/non_linear_state_machine/objective_protest_cycle_with_denied_destination_pinned_by_round_index
    """
    ctx = _setup_protest_cycle_objective()
    objective = ctx["objective"]
    a.assert_objective_shape(objective)
    a.assert_status(objective, "PROPOSED")
    a.assert_int_field(objective, "protest_round", 0)
    # min(5000, 1500 + 1000) == 2500 bps of uplift on a basis of 16 units.
    a.assert_int_field(objective, "basis_units", 16)
    a.assert_int_field(objective, "objective_units", 20)

    walk = _drive_cycle_into_round_two(ctx)

    a.assert_protest_shape(walk["protest_1"])
    a.assert_int_field(walk["protest_1"], "round_index", 1)
    a.assert_status(walk["after_protest_1"], "PROTESTED")
    a.assert_int_field(walk["after_protest_1"], "protest_round", 1)

    a.assert_status(walk["resolved_1"], "UPHELD")
    a.assert_int_field(walk["resolved_1"], "resolved_units", 15)

    # The upheld basis of 12 units re-derives the target as 12 * 12500 / 10000.
    a.assert_status(walk["after_uphold"], "REVISED")
    a.assert_int_field(walk["after_uphold"], "basis_units", 12)
    a.assert_int_field(walk["after_uphold"], "objective_units", 15)

    a.assert_int_field(walk["protest_2"], "round_index", 2)
    after_protest_2 = fx.read_objective(objective["id"])
    a.assert_status(after_protest_2, "PROTESTED")
    a.assert_int_field(after_protest_2, "protest_round", 2)


def test_denied_round_two_protest_returns_the_objective_to_revised():
    """The denial's destination is pinned by round_index 2, so the objective
    lands in REVISED rather than in PROPOSED, and nothing is recomputed.

    PRD: "Denying a round 2 protest returns the objective `PROTESTED → REVISED`,
    which is likewise the state it held before round 2 was filed." "**Denying**
    the protest moves the protest `OPEN → DENIED`, leaves `resolved_units` null,
    and runs no cascade whatsoever — the objective's `basis_units`,
    `objective_units` and `payout_cents` are left byte-identical to their
    pre-protest values, and no chargeback, accrual row or ledger recomputation
    occurs."

    Design: Difficulty/non_linear_state_machine/objective_protest_cycle_with_denied_destination_pinned_by_round_index
    """
    ctx = _setup_protest_cycle_objective()
    objective_id = ctx["objective"]["id"]
    walk = _drive_cycle_into_round_two(ctx)
    before_denial = fx.read_objective(objective_id)

    denied = fx.resolve_protest(
        objective_id,
        walk["protest_2"]["id"],
        "DENIED",
        expected_objective_version=before_denial["version"],
    )
    a.assert_status(denied, "DENIED")
    a.assert_null_fields(denied, ["resolved_units"])

    after_denial = fx.read_objective(objective_id)
    a.assert_status(after_denial, "REVISED")
    a.assert_int_field(after_denial, "basis_units", 12)
    a.assert_int_field(after_denial, "objective_units", 15)
    # protest_round is not decremented by a denial.
    a.assert_int_field(after_denial, "protest_round", 2)
    # No delivery was ever reported, so the whole payout arithmetic stays at 0.
    a.assert_objective_attainment(after_denial, 0, 0, 0, 0)


def test_third_protest_is_refused_once_protest_round_stands_at_two():
    """With protest_round at 2 after the denied round 2, a third filing is
    refused and the cycle is closed.

    PRD: "And the objective's `protest_round` must be strictly less than two, the
    hard cap on protest rounds; a third filing against an objective whose
    `protest_round` already stands at 2 is refused with
    `ERR_PROTEST_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/objective_protest_cycle_with_denied_destination_pinned_by_round_index
    """
    ctx = _setup_protest_cycle_objective()
    objective_id = ctx["objective"]["id"]
    dealer_id = ctx["dealer"]["id"]
    walk = _drive_cycle_into_round_two(ctx)
    fx.resolve_protest(objective_id, walk["protest_2"]["id"], "DENIED")

    third = api_client.create_protest(
        objective_id,
        f.create_protest_payload(9, reason=ROUND_3_REASON),
        make_dealer_headers(dealer_id),
    )
    validate_error(third, ApiErrorId.ERR_PROTEST_LIMIT_REACHED.value)

    unchanged = fx.read_objective(objective_id)
    a.assert_status(unchanged, "REVISED")
    a.assert_int_field(unchanged, "protest_round", 2)
    rows, meta = validate_paginated(
        api_client.list_protests(objective_id, fx.FSM)
    )
    a.assert_list_length(rows, 2, "protests")
    assert meta["total_count"] == 2, meta


# --- Shared setup for the claim's two parallel dimensions ---------------------


def _setup_parallel_dimension_claim() -> dict:
    """An ACTIVE customer-cash program paying 150000 cents per unit, an ACTIVE
    WEST dealer, one VALIDATED delivery sold on 2026-08-05, one freshly submitted
    claim and one OPEN WEST batch over the closed period 2026-08-01..2026-08-31.
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        name="Parallel Auto Mall",
        region_code="WEST",
        historical_volume_units=8,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            name="August Parallel Dimension Cash",
            incentive_type="CUSTOMER_CASH",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=150000,
            budget_cents=100000000,
            stack_group="AUG-CASH",
            priority_rank=11,
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
        build_date=iso_day(2026, 6, 5),
        msrp_cents=3300000,
        sale_date=AUG_05,
        customer_region_code="WEST",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 150000)
    return {
        "program": program,
        "dealer": dealer,
        "batch": batch,
        "delivery": delivery,
        "claim": claim,
    }


def test_payment_dimension_cannot_leave_unpaid_before_validation_reaches_validated():
    """A freshly submitted claim sits at (SUBMITTED, UNPAID), and scheduling it
    is refused outright with the whole call left as a no-op.

    PRD: "Every named claim must exist, must have `validation_status` `VALIDATED`
    and must have `payment_status` `UNPAID` — this is the one coupling between the
    claim's two otherwise independent state dimensions, and the reason it exists
    is that unadjudicated money may never be queued for payment. A named claim
    that fails either half of that condition is refused with
    `ERR_CLAIM_NOT_VALIDATED` and **the whole call is a no-op**: no claim in the
    list is attached, no total is recomputed, and no version moves."

    Design: Difficulty/non_linear_state_machine/claim_validation_and_payment_dimensions_advance_independently
    """
    ctx = _setup_parallel_dimension_claim()
    claim = ctx["claim"]
    a.assert_claim_shape(claim)
    a.assert_claim_dimensions(claim, "SUBMITTED", "UNPAID")
    a.assert_null_fields(claim, ["payment_batch_id", "paid_at"])

    refused = api_client.schedule_claims(
        ctx["batch"]["id"], f.schedule_claims_payload([claim["id"]]), fx.CONTROLLER
    )
    validate_error(refused, ApiErrorId.ERR_CLAIM_NOT_VALIDATED.value)

    batch = fx.read_batch(ctx["batch"]["id"])
    a.assert_status(batch, "OPEN")
    a.assert_int_field(batch, "claim_count", 0)
    a.assert_money(batch, "total_cents", 0)

    untouched = fx.read_claim(claim["id"])
    a.assert_claim_dimensions(untouched, "SUBMITTED", "UNPAID")
    a.assert_null_fields(untouched, ["payment_batch_id"])


def test_approval_moves_only_validation_and_scheduling_moves_only_payment():
    """Approving advances the validation dimension alone; the later scheduling
    call advances the payment dimension alone, leaving the pair
    (VALIDATED, SCHEDULED) on one row.

    PRD: "Approval moves the claim `SUBMITTED → VALIDATED` on the validation
    dimension and computes `approved_amount_cents` and `rate_basis` in three
    pinned steps." "Attaching claims to an open batch moves each claim
    `UNPAID → SCHEDULED` on the payment dimension."

    Design: Difficulty/non_linear_state_machine/claim_validation_and_payment_dimensions_advance_independently
    """
    ctx = _setup_parallel_dimension_claim()
    claim_id = ctx["claim"]["id"]

    approved = fx.adjudicate_claim(claim_id, "APPROVE")
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")
    a.assert_money(approved, "approved_amount_cents", 150000)
    a.assert_null_fields(approved, ["payment_batch_id", "paid_at"])

    batch = fx.schedule_claims(ctx["batch"]["id"], [claim_id])
    a.assert_batch_shape(batch)
    a.assert_int_field(batch, "claim_count", 1)
    a.assert_money(batch, "total_cents", 150000)

    scheduled = fx.read_claim(claim_id)
    a.assert_claim_dimensions(scheduled, "VALIDATED", "SCHEDULED")
    assert scheduled["payment_batch_id"] == ctx["batch"]["id"], scheduled
    a.assert_null_fields(scheduled, ["paid_at"])


def test_suspended_dealer_holds_the_claim_at_scheduled_inside_a_disbursed_batch():
    """The batch reaches DISBURSED while the claim stays at
    (VALIDATED, SCHEDULED) — a combined state no single status column could
    represent — because the dealer was suspended before the money moved.

    PRD: "Every scheduled claim whose dealer has `status` `SUSPENDED` or
    `TERMINATED` is held instead: it stays in `SCHEDULED`, keeps its
    `payment_batch_id`, and is counted in the batch's `held_claim_count` as
    measured at the moment of this disbursement attempt."

    Design: Difficulty/non_linear_state_machine/claim_validation_and_payment_dimensions_advance_independently
    """
    ctx = _setup_parallel_dimension_claim()
    claim_id = ctx["claim"]["id"]
    batch_id = ctx["batch"]["id"]

    fx.adjudicate_claim(claim_id, "APPROVE")
    fx.schedule_claims(batch_id, [claim_id])
    fx.set_dealer_status(ctx["dealer"]["id"], "SUSPENDED", note="Floor-plan audit open.")
    fx.lock_batch(batch_id)
    disbursed = fx.disburse_batch(batch_id, at=SEP_10)

    a.assert_status(disbursed, "DISBURSED")
    a.assert_int_field(disbursed, "held_claim_count", 1)
    a.assert_money(disbursed, "total_cents", 150000)

    held = fx.read_claim(claim_id)
    a.assert_claim_dimensions(held, "VALIDATED", "SCHEDULED")
    assert held["payment_batch_id"] == batch_id, held
    a.assert_null_fields(held, ["paid_at"])

    program = fx.read_program(ctx["program"]["id"])
    a.assert_money(program, "committed_cents", 150000)
    a.assert_money(program, "paid_cents", 0)
    dealer = fx.read_dealer(ctx["dealer"]["id"])
    a.assert_money(dealer, "paid_cents", 0)
