"""Pricing a damage finding, disputing it, and the append-only fee ledger.

A damage claim is where an inspection turns into money.  The price is built by a
three-term composition over the style's retail price, the unit's freshly written
condition grade and the finding's severity; the waiver then absorbs what it can;
and only what is left is billed.  From there the claim can be absorbed, charged,
disputed, downgraded, overturned or settled, and every one of those moves is
recorded by appending to a ledger that is never rewritten.  These tests pin the
arithmetic at both of its winning terms, the two conserved quantities that an
overturned dispute must restore, the bounded dispute loop, the settlement
bounds, and the cascade that a single charge fires across four entities.
"""

from __future__ import annotations

from typing import Optional

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_DISPUTE_ROUNDS_EXHAUSTED,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_NOTHING_TO_CHARGE,
    ERR_SETTLEMENT_EXCEEDS_BALANCE,
    ERR_WAIVER_NOT_AVAILABLE,
)
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_instant,
    assert_list,
    assert_money,
    assert_null,
    assert_ok,
    assert_unit_position,
)
from test_helpers.fixtures import (
    Catalog,
    Scenario,
    Turn,
    inspected_turn,
    standard_catalog,
)

JsonDict = dict

# The short circuit in this module runs 08-05..08-09 and is received on 08-10,
# inside the two-day grace period, so no late fee ever muddies the balance.
RECEIPT_CLOCK = K.CLOCK_AUG_10_0900

# The long circuit runs 08-10..08-16 and is received exactly on its grace date,
# so it too posts no late fee.
GRACE_EDGE_RECEIPT_CLOCK = K.CLOCK_AUG_18_0900


def _assessed_claim(
    scenario: Scenario,
    damage_severity: str,
    condition_grade_after: str,
    waiver_active: bool = False,
    soil_level: str = K.SOIL_LIGHT,
):
    """One short turn, inspected with damage, whose claim has been priced."""
    catalog = standard_catalog(scenario, waiver_active=waiver_active)
    turn = inspected_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_09,
        soil_level,
        damage_severity,
        condition_grade_after,
    )
    assert_fields(turn.claim, state=K.CLAIM_OPEN, severity=damage_severity)
    claim = scenario.assess(turn.claim_id)
    assert_fields(claim, state=K.CLAIM_ASSESSED, severity=damage_severity)
    return catalog, turn, claim


def _grace_edge_turn(
    scenario: Scenario,
    catalog: Catalog,
    damage_severity: str,
    condition_grade_after: str,
    window=K.WINDOW_AUG_10_16,
    planned_ship_date: str = K.SHIP_DATE_AUG_08,
    carrier_reference: str = K.CARRIER_OUT_AUG_08,
    dispatch_clock: str = K.CLOCK_AUG_10_0900,
    return_clock: str = K.CLOCK_AUG_16_0900,
    receipt_clock: str = GRACE_EDGE_RECEIPT_CLOCK,
) -> Turn:
    """A longer turn whose receipt lands exactly on the grace date, fee-free."""
    return inspected_turn(
        scenario,
        catalog,
        window,
        K.SOIL_NONE,
        damage_severity,
        condition_grade_after,
        planned_ship_date=planned_ship_date,
        carrier_reference=carrier_reference,
        dispatch_clock=dispatch_clock,
        return_clock=return_clock,
        receipt_clock=receipt_clock,
    )


def _dispute(
    scenario: Scenario, member: JsonDict, claim_id: str, reason: str
) -> JsonDict:
    """The owning member files a dispute against their own claim."""
    return assert_ok(
        scenario.client.dispute_claim(
            claim_id, F.dispute_payload(reason), Scenario.member_headers(member)
        )
    )


def _resolve(scenario: Scenario, claim_id: str, resolution: str) -> JsonDict:
    """The adjuster returns a verdict on a disputed claim."""
    return assert_ok(
        scenario.client.resolve_dispute(
            claim_id, F.dispute_resolution_payload(resolution), scenario.adjuster
        )
    )


def _settle(
    scenario: Scenario, member: JsonDict, amount_cents: int, memo: Optional[str] = None
):
    """A raw settlement attempt, so a test can inspect a refusal itself."""
    return scenario.client.settle_fees(
        member["id"],
        F.settlement_payload(amount_cents, memo),
        Scenario.member_headers(member),
    )


def test_a_moderate_finding_on_a_grade_b_unit_is_billed_at_the_severity_floor(
    scenario: Scenario,
) -> None:
    """The flat floor beats the percentage term, and no waiver flag means no credit.

    PRD §3.7: "First the residual value: take the style's `retail_price_cents`, multiply by the residual rate for the unit's current `condition_grade` — which the inspection has already overwritten, so the assessment always prices the garment as it is now, not as it was — and round half up."
    PRD §3.7: "Then `gross_fee_cents` is the larger of the severity floor and the percentage component, but never more than the residual value — the floor pushes small claims up, the percentage pushes expensive garments up, and the residual value is a hard ceiling that no combination may pierce."
    PRD §3.7: "If the member's `waiver_active` is true, `waiver_applied_cents` is the smaller of `gross_fee_cents` and that remaining coverage; if `waiver_active` is false it is 0."

    Design: Corner/calculations/calc_damage_fee_moderate_on_a_grade_b_unit_takes_the_severity_floor
    """
    catalog, turn, claim = _assessed_claim(
        scenario, K.DAMAGE_MODERATE, K.GRADE_B, waiver_active=False
    )

    residual = K.STYLE_GOWN_RETAIL_CENTS * 40 // 100
    assert residual == 19200, "grade B prices the 48000-cent gown at 19200"
    percentage = 19200 * 35 // 100
    assert percentage == 6720, "the percentage term is the loser in this arm"

    assert_instant(claim["assessed_at"], RECEIPT_CLOCK, "assessed_at")
    assert_money(
        claim,
        residual_value_cents=residual,
        gross_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MODERATE],
        waiver_applied_cents=0,
        net_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MODERATE],
    )

    # Pricing writes no money anywhere else: no ledger row, no coverage used.
    member = scenario.read_member(catalog.member)
    assert_money(member, outstanding_fee_cents=0, waiver_coverage_used_cents=0)
    assert scenario.ledger_rows(catalog.member) == [], "assessment posts no ledger entry"

    # The grade the assessment priced against is the grade the inspection wrote.
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_REPAIR,
        condition_grade=K.GRADE_B,
    )


def test_the_ledger_replays_a_running_balance_across_two_settlements(
    scenario: Scenario,
) -> None:
    """Two credits walk the balance 9000 → 5000 → 0 without touching the debit row.

    PRD §3.7: "The settlement appends a `SETTLEMENT_PAYMENT` entry in the `CREDIT` direction whose `amount_cents` is the negation of the amount supplied, recomputes `outstanding_fee_cents`, and, when the balance falls below 15,000 cents and the member's `status` is `DELINQUENT`, returns the member `DELINQUENT → ACTIVE`."
    PRD §2.7: "Each entry's `balance_after_cents` records the running signed sum over that member's entries ordered by `created_at` ascending, evaluated immediately after the entry was appended."

    Design: Corner/calculations/calc_fee_ledger_running_balance_after_two_settlements
    """
    catalog, _turn, claim = _assessed_claim(scenario, K.DAMAGE_MODERATE, K.GRADE_B)
    charged = scenario.charge(claim["id"])
    assert_money(charged, net_fee_cents=9000)
    assert_money(scenario.read_member(catalog.member), outstanding_fee_cents=9000)

    first = scenario.settle(catalog.member, 4000, K.SETTLEMENT_MEMO_PART)
    assert_fields(
        first,
        kind=K.LEDGER_SETTLEMENT_PAYMENT,
        direction=K.DIRECTION_CREDIT,
        memo=K.SETTLEMENT_MEMO_PART,
    )
    assert_money(first, amount_cents=-4000, balance_after_cents=5000)

    second = scenario.settle(catalog.member, 5000, K.SETTLEMENT_MEMO_BALANCE)
    assert_fields(second, kind=K.LEDGER_SETTLEMENT_PAYMENT, direction=K.DIRECTION_CREDIT)
    assert_money(second, amount_cents=-5000, balance_after_cents=0)

    rows, _meta = assert_list(
        scenario.client.list_fee_ledger_entries(
            Scenario.member_headers(catalog.member), {"member_id": catalog.member["id"]}
        ),
        total_count=3,
    )
    # Nothing was rewritten: the original debit still reads as it was appended.
    assert_fields(rows[0], kind=K.LEDGER_DAMAGE_FEE, direction=K.DIRECTION_DEBIT)
    assert_money(rows[0], amount_cents=9000, balance_after_cents=9000)
    assert [row["balance_after_cents"] for row in rows] == [9000, 5000, 0]
    assert sum(row["amount_cents"] for row in rows) == 0

    settled = scenario.read_member(catalog.member)
    assert_money(settled, outstanding_fee_cents=0)
    assert_fields(settled, status=K.MEMBER_ACTIVE)


def test_a_full_waiver_absorption_leaves_the_charge_with_nothing_to_bill(
    scenario: Scenario,
) -> None:
    """On grade A the percentage term wins, and the coverage swallows all of it.

    PRD §3.7: "Absorption raises `waiver_applied_cents` to the full `gross_fee_cents`, sets `net_fee_cents` to 0, and adjusts the member's `waiver_coverage_used_cents` so the total consumed by this claim equals `gross_fee_cents`."
    PRD §3.7: "An adjuster charges an `ASSESSED` claim, which requires the member's `status` not to be `CANCELLED` and, at rank 53, `net_fee_cents` to be strictly greater than zero, otherwise `ERR_NOTHING_TO_CHARGE` (409) — a fully waived or fully reversed claim has nothing left to bill."
    PRD §3.7: "A `WAIVER_CREDIT` entry of amount 0 is written for audit; the member's balance does not move, because nothing was ever charged."

    Design: Corner/calculations/calc_waiver_absorbs_the_whole_fee_and_charge_finds_nothing_to_charge
    """
    catalog, _turn, claim = _assessed_claim(
        scenario, K.DAMAGE_MODERATE, K.GRADE_A, waiver_active=True
    )
    # 48000 x 0.55 = 26400, and 26400 x 0.35 = 9240 now beats the 9000 floor.
    assert_money(
        claim,
        residual_value_cents=26400,
        gross_fee_cents=9240,
        waiver_applied_cents=9240,
        net_fee_cents=0,
    )

    nothing = scenario.client.charge_claim(claim["id"], scenario.adjuster)
    assert_error(nothing, ERR_NOTHING_TO_CHARGE)
    unbilled = scenario.read_claim(claim["id"])
    assert_fields(unbilled, state=K.CLAIM_ASSESSED)
    assert_null(unbilled, "charged_at")

    waived = scenario.waive(claim["id"])
    assert_fields(waived, state=K.CLAIM_WAIVED)
    assert_money(
        waived, gross_fee_cents=9240, waiver_applied_cents=9240, net_fee_cents=0
    )
    assert_money(
        scenario.read_member(catalog.member),
        waiver_coverage_used_cents=9240,
        outstanding_fee_cents=0,
    )

    # The audit row is the one exception to the signed-amount rule: it is zero.
    rows = scenario.ledger_rows(catalog.member)
    assert len(rows) == 1, f"expected one audit entry, got {rows}"
    assert_fields(rows[0], kind=K.LEDGER_WAIVER_CREDIT, damage_claim_id=claim["id"])
    assert_money(rows[0], amount_cents=0, balance_after_cents=0)


def test_a_charge_publishes_the_new_balance_in_the_very_same_response(
    scenario: Scenario,
) -> None:
    """The claim, the member and the ledger all agree the instant the debit lands.

    PRD §2.9: "Derived values are never stale in a response: any computed field of any entity touched by a cascade is recomputed before the response is written, including a style's `floor_ready_unit_count`, `active_unit_count`, `required_depth_units`, `depth_gap_units`, `replenishment_flag` and `demand_score`; a member's `outstanding_fee_cents`, `units_out_count`, `swaps_used_current_month`, `late_return_count`, `fit_confidence_score`, `damage_risk_score` and `damage_risk_band`; a unit's `cumulative_servicing_cost_cents`, `realized_revenue_cents` and `occupied_until_date`; and a reservation's `waitlist_position`."
    PRD §3.7: "Hop two appends a `FeeLedgerEntry` of `kind` `DAMAGE_FEE` whose `amount_cents` is the full `gross_fee_cents` and, when `waiver_applied_cents` is greater than zero, a second entry of `kind` `WAIVER_CREDIT` whose `amount_cents` is the negation of `waiver_applied_cents`; the member's `outstanding_fee_cents` is then recomputed, so the balance rises by exactly `net_fee_cents` while the ledger still shows the gross charge and the credit separately."

    Design: Corner/consistency_model/consistency_charge_updates_the_balance_inside_the_same_response
    """
    catalog, turn, claim = _assessed_claim(scenario, K.DAMAGE_MODERATE, K.GRADE_B)
    assert scenario.ledger_rows(catalog.member) == [], "the ledger is empty before the charge"

    charged = scenario.charge(claim["id"])
    assert_fields(charged, state=K.CLAIM_CHARGED)
    assert_instant(charged["charged_at"], RECEIPT_CLOCK, "charged_at")
    assert_money(charged, net_fee_cents=9000, waiver_applied_cents=0)

    # The very next read, with no further writes in between.
    member = scenario.read_member(catalog.member)
    assert_money(member, outstanding_fee_cents=charged["net_fee_cents"])
    assert_fields(member, status=K.MEMBER_ACTIVE)

    rows, _meta = assert_list(
        scenario.client.list_fee_ledger_entries(
            scenario.adjuster, {"member_id": catalog.member["id"]}
        ),
        total_count=1,
    )
    assert_fields(
        rows[0],
        kind=K.LEDGER_DAMAGE_FEE,
        direction=K.DIRECTION_DEBIT,
        damage_claim_id=claim["id"],
        member_id=catalog.member["id"],
    )
    assert_money(rows[0], amount_cents=9000, balance_after_cents=9000)
    assert_null(rows[0], "reservation_id")

    # The garment's own position is untouched by the money cascade.
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_REPAIR,
    )


def test_a_dispute_filed_on_the_eighth_day_after_the_charge_is_refused(
    scenario: Scenario,
) -> None:
    """The seven-day clock starts at `charged_at`, not at the assessment sixteen days earlier.

    PRD §3.7: "At rank 30, when the claim's `state` is `CHARGED`, the current logical clock's calendar date must be no later than the calendar date of `charged_at` plus 7 days, otherwise `ERR_DISPUTE_WINDOW_CLOSED` (409); the boundary is inclusive, so a dispute filed exactly 7 days after the charge date is accepted and one filed on the eighth day is not, and the window is not applied at all to an `ASSESSED` claim, which has no charge date to measure from."

    Design: Corner/validations/validation_dispute_after_the_window_has_closed_is_refused
    """
    catalog, _turn, claim = _assessed_claim(scenario, K.DAMAGE_MODERATE, K.GRADE_B)
    assert_instant(claim["assessed_at"], RECEIPT_CLOCK, "assessed_at")

    scenario.set_clock(K.CLOCK_AUG_18_1000)
    charged = scenario.charge(claim["id"])
    assert_instant(charged["charged_at"], K.CLOCK_AUG_18_1000, "charged_at")
    assert_fields(charged, dispute_round=0)

    # 2026-08-18 plus 7 days closes on 2026-08-25, so 2026-08-26 is one day late.
    scenario.set_clock(K.CLOCK_AUG_26_0900)
    too_late = scenario.client.dispute_claim(
        claim["id"],
        F.dispute_payload(K.DISPUTE_REASON_MARK_AT_DELIVERY),
        Scenario.member_headers(catalog.member),
    )
    assert_error(too_late, ERR_DISPUTE_WINDOW_CLOSED)

    untouched = scenario.read_claim(claim["id"])
    assert_fields(untouched, state=K.CLAIM_CHARGED, dispute_round=0)
    assert_instant(untouched["charged_at"], K.CLOCK_AUG_18_1000, "charged_at")
    assert_null(untouched, "dispute_reason", "resolution")
    assert_money(scenario.read_member(catalog.member), outstanding_fee_cents=9000)
    assert len(scenario.ledger_rows(catalog.member)) == 1


def test_a_settlement_is_bounded_strictly_above_zero_and_by_the_balance(
    scenario: Scenario,
) -> None:
    """9001 overpays and 0 underpays; only the exact balance is accepted.

    PRD §3.7: "At rank 54 the amount must be strictly greater than zero and no greater than the member's current `outstanding_fee_cents`, otherwise `ERR_SETTLEMENT_EXCEEDS_BALANCE` (422); the API accepts no overpayment and no zero or negative payment, and note that this one is a request-content rejection at 422 rather than a state conflict."

    Design: Corner/validations/validation_settlement_above_the_outstanding_balance_is_rejected
    """
    catalog, _turn, claim = _assessed_claim(scenario, K.DAMAGE_MODERATE, K.GRADE_B)
    scenario.charge(claim["id"])
    assert_money(scenario.read_member(catalog.member), outstanding_fee_cents=9000)

    assert_error(_settle(scenario, catalog.member, 9001), ERR_SETTLEMENT_EXCEEDS_BALANCE)
    assert_error(_settle(scenario, catalog.member, 0), ERR_SETTLEMENT_EXCEEDS_BALANCE)
    # Neither refusal may have appended anything.
    assert len(scenario.ledger_rows(catalog.member)) == 1

    paid = scenario.settle(catalog.member, 9000)
    assert_fields(
        paid, kind=K.LEDGER_SETTLEMENT_PAYMENT, direction=K.DIRECTION_CREDIT
    )
    assert_money(paid, amount_cents=-9000, balance_after_cents=0)
    assert_null(paid, "memo")

    rows = scenario.ledger_rows(catalog.member)
    assert len(rows) == 2, f"expected the debit and the one accepted credit, got {rows}"
    cleared = scenario.read_member(catalog.member)
    assert_money(cleared, outstanding_fee_cents=0)
    assert_fields(cleared, status=K.MEMBER_ACTIVE)


def test_absorption_is_refused_when_the_member_carries_no_active_waiver(
    scenario: Scenario,
) -> None:
    """The plan's coverage is ample, but the member flag is the first thing read.

    PRD §3.7: "At rank 52 this requires the member's `waiver_active` to be true and the plan's `waiver_coverage_cents`, minus the member's `waiver_coverage_used_cents`, plus the coverage this same claim has already reserved through `waiver_applied_cents`, to be at least the claim's `gross_fee_cents`; otherwise the request is refused with `ERR_WAIVER_NOT_AVAILABLE` (409)."

    Design: Corner/validations/validation_waiver_is_unavailable_to_a_member_without_an_active_waiver
    """
    catalog, _turn, claim = _assessed_claim(
        scenario, K.DAMAGE_MODERATE, K.GRADE_A, waiver_active=False
    )
    # The tier would cover 9240 comfortably; the member simply did not buy it.
    assert catalog.plan["waiver_coverage_cents"] == K.PLAN_SIG4_WAIVER_COVERAGE_CENTS
    assert_money(claim, gross_fee_cents=9240, waiver_applied_cents=0, net_fee_cents=9240)

    refused = scenario.client.waive_claim(claim["id"], scenario.adjuster)
    assert_error(refused, ERR_WAIVER_NOT_AVAILABLE)

    intact = scenario.read_claim(claim["id"])
    assert_fields(intact, state=K.CLAIM_ASSESSED)
    assert_money(
        intact, gross_fee_cents=9240, waiver_applied_cents=0, net_fee_cents=9240
    )
    member = scenario.read_member(catalog.member)
    assert_fields(member, waiver_active=False)
    assert_money(member, waiver_coverage_used_cents=0, outstanding_fee_cents=0)
    assert scenario.ledger_rows(catalog.member) == []


def _both_severity_arms(scenario: Scenario):
    """Two turns on one member, priced from the same retail price and the same grade."""
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002), waiver_active=False
    )
    floor_turn = _grace_edge_turn(scenario, catalog, K.DAMAGE_MODERATE, K.GRADE_B)
    ceiling_turn = _grace_edge_turn(
        scenario,
        catalog,
        K.DAMAGE_SEVERE,
        K.GRADE_B,
        window=K.WINDOW_AUG_20_26,
        planned_ship_date=K.SHIP_DATE_AUG_16,
        carrier_reference=K.CARRIER_OUT_AUG_16,
        dispatch_clock=K.CLOCK_AUG_20_0900,
        return_clock=K.CLOCK_AUG_26_0900,
        receipt_clock=K.CLOCK_AUG_28_0900,
    )
    return catalog, scenario.assess(floor_turn.claim_id), scenario.assess(ceiling_turn.claim_id)


def test_the_moderate_arm_is_decided_by_the_flat_severity_floor(
    scenario: Scenario,
) -> None:
    """Same retail price, same grade: here the 9000 floor beats the 6720 percentage term.

    PRD §3.7: "Second, a severity floor: when the claim's `severity` is `LOSS` the floor is the whole residual value, and otherwise it is a flat 2,500 cents for `MINOR`, 9,000 cents for `MODERATE` and 22,000 cents for `SEVERE`."
    PRD §3.7: "Third, a percentage component: multiply the residual value by 0.10 for `MINOR`, 0.35 for `MODERATE`, 0.75 for `SEVERE` or 1.00 for `LOSS`, rounding half up."

    Design: Difficulty/combinatorial_formula/damage_fee_three_input_nonlinear_composition
    """
    catalog, floor_claim, ceiling_claim = _both_severity_arms(scenario)

    # The two arms are priced off an identical residual value.
    assert_money(floor_claim, residual_value_cents=19200)
    assert_money(ceiling_claim, residual_value_cents=19200)

    assert_fields(floor_claim, state=K.CLAIM_ASSESSED, severity=K.DAMAGE_MODERATE)
    assert_money(
        floor_claim,
        gross_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MODERATE],
        waiver_applied_cents=0,
        net_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MODERATE],
    )
    # 9000 is the flat floor, strictly under the residual ceiling, and strictly
    # above the 6720 the percentage term would have produced.
    assert floor_claim["gross_fee_cents"] < floor_claim["residual_value_cents"]
    assert floor_claim["gross_fee_cents"] > 6720

    assert_money(
        scenario.read_member(catalog.member), outstanding_fee_cents=0
    )
    assert scenario.ledger_rows(catalog.member) == []


def test_the_severe_arm_is_decided_by_the_residual_ceiling(
    scenario: Scenario,
) -> None:
    """The 22000 floor for SEVERE is clipped to the 19200 the garment is still worth.

    PRD §3.7: "Then `gross_fee_cents` is the larger of the severity floor and the percentage component, but never more than the residual value — the floor pushes small claims up, the percentage pushes expensive garments up, and the residual value is a hard ceiling that no combination may pierce."
    PRD §3.7: "Note the consequence for cheap garments: a `MODERATE` finding on a grade-`D` piece whose residual value is below 9,000 cents is billed at exactly the residual value, because the 9,000-cent floor is clipped by the ceiling."

    Design: Difficulty/combinatorial_formula/damage_fee_three_input_nonlinear_composition
    """
    catalog, floor_claim, ceiling_claim = _both_severity_arms(scenario)

    assert_fields(ceiling_claim, state=K.CLAIM_ASSESSED, severity=K.DAMAGE_SEVERE)
    assert_money(
        ceiling_claim,
        residual_value_cents=19200,
        gross_fee_cents=19200,
        waiver_applied_cents=0,
        net_fee_cents=19200,
    )
    # The severity floor for SEVERE is 22000, above the ceiling, so the ceiling
    # is what the member is billed; the 14400 percentage term never mattered.
    assert K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_SEVERE] > ceiling_claim["gross_fee_cents"]
    assert ceiling_claim["gross_fee_cents"] == ceiling_claim["residual_value_cents"]

    # Two different winning terms of one expression, off identical inputs but
    # for the severity.
    assert ceiling_claim["residual_value_cents"] == floor_claim["residual_value_cents"]
    assert ceiling_claim["gross_fee_cents"] != floor_claim["gross_fee_cents"]

    member = scenario.read_member(catalog.member)
    assert_money(member, outstanding_fee_cents=0)
    assert_fields(member, status=K.MEMBER_ACTIVE)


def _charged_under_partial_coverage(scenario: Scenario):
    """A severe claim on a waiver-holding member, charged with coverage exhausted."""
    catalog = standard_catalog(scenario, waiver_active=True)
    turn = _grace_edge_turn(scenario, catalog, K.DAMAGE_SEVERE, K.GRADE_B)
    claim = scenario.assess(turn.claim_id)
    assert_money(
        claim,
        residual_value_cents=19200,
        gross_fee_cents=19200,
        waiver_applied_cents=K.PLAN_SIG4_WAIVER_COVERAGE_CENTS,
        net_fee_cents=9200,
    )
    assert_money(
        scenario.read_member(catalog.member),
        waiver_coverage_used_cents=K.PLAN_SIG4_WAIVER_COVERAGE_CENTS,
    )
    return catalog, turn, scenario.charge(claim["id"])


def test_a_charge_under_partial_coverage_posts_the_gross_and_the_credit_separately(
    scenario: Scenario,
) -> None:
    """Two rows, not one netted row, and the balance rises by exactly the net.

    PRD §3.7: "Hop two appends a `FeeLedgerEntry` of `kind` `DAMAGE_FEE` whose `amount_cents` is the full `gross_fee_cents` and, when `waiver_applied_cents` is greater than zero, a second entry of `kind` `WAIVER_CREDIT` whose `amount_cents` is the negation of `waiver_applied_cents`; the member's `outstanding_fee_cents` is then recomputed, so the balance rises by exactly `net_fee_cents` while the ledger still shows the gross charge and the credit separately."
    PRD §3.7: "Its `direction` is derived, not supplied: `DEBIT` when `amount_cents` is greater than zero and `CREDIT` when `amount_cents` is less than zero."

    Design: Difficulty/compensating_invariant/member_fee_balance_and_waiver_coverage_restored_by_overturned_dispute
    """
    catalog, _turn, charged = _charged_under_partial_coverage(scenario)
    assert_fields(charged, state=K.CLAIM_CHARGED)
    assert_money(charged, net_fee_cents=9200)

    rows = scenario.ledger_rows(catalog.member)
    assert len(rows) == 2, f"expected the gross debit and the waiver credit, got {rows}"
    assert_fields(
        rows[0],
        kind=K.LEDGER_DAMAGE_FEE,
        direction=K.DIRECTION_DEBIT,
        damage_claim_id=charged["id"],
    )
    assert_money(rows[0], amount_cents=19200, balance_after_cents=19200)
    assert_fields(
        rows[1],
        kind=K.LEDGER_WAIVER_CREDIT,
        direction=K.DIRECTION_CREDIT,
        damage_claim_id=charged["id"],
    )
    assert_money(rows[1], amount_cents=-10000, balance_after_cents=9200)

    member = scenario.read_member(catalog.member)
    assert_money(
        member,
        outstanding_fee_cents=charged["net_fee_cents"],
        waiver_coverage_used_cents=K.PLAN_SIG4_WAIVER_COVERAGE_CENTS,
    )
    # 9200 sits below the delinquency threshold, so no unwinding cascade fires.
    assert_fields(member, status=K.MEMBER_ACTIVE)


def test_an_overturned_dispute_restores_the_balance_and_the_waiver_coverage(
    scenario: Scenario,
) -> None:
    """One compensating row drives the claim's own amounts to a signed sum of zero.

    PRD §3.7: "Hop two, when a `DAMAGE_FEE` entry for this claim exists, appends a `DISPUTE_REVERSAL` entry whose `amount_cents` is the negation of the signed sum of this claim's prior entries and recomputes the member's `outstanding_fee_cents`, which therefore returns to exactly its pre-charge value."
    PRD §3.7: "Hop three decrements the member's `waiver_coverage_used_cents` by this claim's `waiver_applied_cents`, releasing the coverage a dismissed claim no longer needs."
    PRD §2.7: "The compensating-action invariant follows: for a claim that was charged and then overturned, the signed sum of that claim's own entries is exactly zero, so the member's `outstanding_fee_cents` returns to its exact pre-charge value and their `waiver_coverage_used_cents` returns to its exact pre-assessment value."

    Design: Difficulty/compensating_invariant/member_fee_balance_and_waiver_coverage_restored_by_overturned_dispute
    """
    catalog, _turn, charged = _charged_under_partial_coverage(scenario)

    disputed = _dispute(
        scenario,
        catalog.member,
        charged["id"],
        K.DISPUTE_REASON_RETURNED_AS_ARRIVED,
    )
    assert_fields(
        disputed,
        state=K.CLAIM_DISPUTED,
        dispute_round=1,
        dispute_reason=K.DISPUTE_REASON_RETURNED_AS_ARRIVED,
    )

    dismissed = _resolve(scenario, charged["id"], K.RESOLUTION_OVERTURNED)
    assert_fields(
        dismissed, state=K.CLAIM_DISMISSED, resolution=K.RESOLUTION_OVERTURNED
    )
    assert_money(dismissed, net_fee_cents=0)

    rows = scenario.ledger_rows(catalog.member)
    assert len(rows) == 3, f"the ledger is append-only, so it must still hold three rows: {rows}"
    assert_fields(
        rows[2],
        kind=K.LEDGER_DISPUTE_REVERSAL,
        direction=K.DIRECTION_CREDIT,
        damage_claim_id=charged["id"],
    )
    assert_money(rows[2], amount_cents=-9200, balance_after_cents=0)
    assert [row["balance_after_cents"] for row in rows] == [19200, 9200, 0]
    assert sum(row["amount_cents"] for row in rows) == 0

    member = scenario.read_member(catalog.member)
    assert_money(member, outstanding_fee_cents=0, waiver_coverage_used_cents=0)
    assert_fields(member, status=K.MEMBER_ACTIVE)


def _severe_claim_awaiting_a_dispute(scenario: Scenario):
    """A severe claim priced but never charged, so only the round cap constrains it."""
    catalog = standard_catalog(scenario, waiver_active=False)
    turn = _grace_edge_turn(scenario, catalog, K.DAMAGE_SEVERE, K.GRADE_B)
    claim = scenario.assess(turn.claim_id)
    assert_fields(claim, state=K.CLAIM_ASSESSED, severity=K.DAMAGE_SEVERE, dispute_round=0)
    assert_money(claim, gross_fee_cents=19200, net_fee_cents=19200)
    assert_null(claim, "charged_at", "resolution", "dispute_reason")
    return catalog, claim


def test_the_first_partial_verdict_returns_the_claim_to_assessed_one_step_cheaper(
    scenario: Scenario,
) -> None:
    """The loop leaves ASSESSED and comes back to it with a persistently lower severity.

    PRD §3.7: "A `resolution` of `PARTIAL` moves the claim `DISPUTED → ASSESSED`, records `resolution` as `PARTIAL`, and **persistently** downgrades `severity` one step: `LOSS` becomes `SEVERE`, `SEVERE` becomes `MODERATE`, `MODERATE` becomes `MINOR`, and `MINOR` stays `MINOR`."
    PRD §3.7: "All four money fields are then recomputed at the new severity by the assessment arithmetic above."

    Design: Difficulty/non_linear_state_machine/damage_claim_dispute_cycle_downgrades_twice_then_locks
    """
    catalog, claim = _severe_claim_awaiting_a_dispute(scenario)

    disputed = _dispute(
        scenario, catalog.member, claim["id"], K.DISPUTE_REASON_HEM_ALREADY_FRAYED
    )
    assert_fields(
        disputed,
        state=K.CLAIM_DISPUTED,
        dispute_round=1,
        severity=K.DAMAGE_SEVERE,
        dispute_reason=K.DISPUTE_REASON_HEM_ALREADY_FRAYED,
    )

    reassessed = _resolve(scenario, claim["id"], K.RESOLUTION_PARTIAL)
    assert_fields(
        reassessed,
        state=K.CLAIM_ASSESSED,
        resolution=K.RESOLUTION_PARTIAL,
        severity=K.DAMAGE_MODERATE,
        dispute_round=1,
    )
    # The residual value is unchanged; only the severity term moved.
    assert_money(
        reassessed,
        residual_value_cents=19200,
        gross_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MODERATE],
        waiver_applied_cents=0,
        net_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MODERATE],
    )
    assert_money(scenario.read_member(catalog.member), outstanding_fee_cents=0)


def test_two_partial_verdicts_compound_and_the_third_dispute_is_refused(
    scenario: Scenario,
) -> None:
    """The second downgrade starts from MODERATE, then rank 29 locks the loop shut.

    PRD §3.7: "Because the downgrade is written to the claim, a second `PARTIAL` verdict downgrades from the already-downgraded value rather than from the original finding, so two partial verdicts on a `LOSS` claim land on `MODERATE`."
    PRD §3.7: "At rank 29 `dispute_round` must be strictly below the cap of 2, otherwise `ERR_DISPUTE_ROUNDS_EXHAUSTED` (409): a member gets two bites, not an unbounded appeal."

    Design: Difficulty/non_linear_state_machine/damage_claim_dispute_cycle_downgrades_twice_then_locks
    """
    catalog, claim = _severe_claim_awaiting_a_dispute(scenario)

    _dispute(scenario, catalog.member, claim["id"], K.DISPUTE_REASON_HEM_ALREADY_FRAYED)
    once = _resolve(scenario, claim["id"], K.RESOLUTION_PARTIAL)
    assert_fields(once, severity=K.DAMAGE_MODERATE)

    second = _dispute(
        scenario, catalog.member, claim["id"], K.DISPUTE_REASON_INVOICE_MISMATCH
    )
    assert_fields(second, state=K.CLAIM_DISPUTED, dispute_round=2)

    twice = _resolve(scenario, claim["id"], K.RESOLUTION_PARTIAL)
    # MODERATE, not SEVERE, was the input to this downgrade.
    assert_fields(
        twice,
        state=K.CLAIM_ASSESSED,
        severity=K.DAMAGE_MINOR,
        resolution=K.RESOLUTION_PARTIAL,
        dispute_round=2,
    )
    assert_money(
        twice,
        residual_value_cents=19200,
        gross_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MINOR],
        net_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MINOR],
    )

    exhausted = scenario.client.dispute_claim(
        claim["id"],
        F.dispute_payload(K.DISPUTE_REASON_THIRD_ATTEMPT),
        Scenario.member_headers(catalog.member),
    )
    assert_error(exhausted, ERR_DISPUTE_ROUNDS_EXHAUSTED)

    locked = scenario.read_claim(claim["id"])
    assert_fields(
        locked,
        state=K.CLAIM_ASSESSED,
        dispute_round=K.DISPUTE_ROUND_CAP,
        severity=K.DAMAGE_MINOR,
        dispute_reason=K.DISPUTE_REASON_INVOICE_MISMATCH,
    )
    assert_money(locked, net_fee_cents=K.DAMAGE_FLOOR_BY_SEVERITY[K.DAMAGE_MINOR])
    # Nothing was ever charged, so the whole loop left the ledger empty.
    assert scenario.ledger_rows(catalog.member) == []
    assert_money(scenario.read_member(catalog.member), outstanding_fee_cents=0)


def _delinquency_stage(scenario: Scenario):
    """A priced 19200-cent claim plus one matched and one waitlisted forward booking."""
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002), waiver_active=False
    )
    # A second style with no physical depth at all, so a request against it can
    # only be waitlisted.
    dress = scenario.create_style(F.dress_style_payload())

    turn = _grace_edge_turn(scenario, catalog, K.DAMAGE_SEVERE, K.GRADE_B)
    claim = scenario.assess(turn.claim_id)
    assert_money(claim, gross_fee_cents=19200, waiver_applied_cents=0, net_fee_cents=19200)
    assert_fields(scenario.read_reservation(turn.reservation_id), state=K.RES_RETURNED)

    # The clock is at the receipt instant; the member is still ACTIVE and owes
    # nothing, so she may keep booking.
    matched = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_20_26
    )
    assert_fields(matched, state=K.RES_MATCHED)
    waitlisted = scenario.create_reservation(
        catalog.member, dress["id"], K.WINDOW_AUG_20_24
    )
    assert_fields(waitlisted, state=K.RES_WAITLISTED, waitlist_position=1)

    member = scenario.read_member(catalog.member)
    assert_fields(member, status=K.MEMBER_ACTIVE)
    assert_money(member, outstanding_fee_cents=0)
    return catalog, turn, claim, matched, waitlisted


def test_a_single_charge_tips_the_member_into_delinquency(
    scenario: Scenario,
) -> None:
    """One debit of 19200 crosses the threshold in the same request that posts it.

    PRD §3.7: "The claim moves `ASSESSED → CHARGED` with `charged_at` stamped."
    PRD §3.7: "Hop three checks delinquency: when the recomputed `outstanding_fee_cents` is greater than or equal to 15,000 cents and the member's `status` is `ACTIVE`, the member moves `ACTIVE → DELINQUENT` and `version` increments."

    Design: Difficulty/transitive_cascade/damage_charge_cascades_delinquency_to_unit_release
    """
    catalog, _turn, claim, _matched, _waitlisted = _delinquency_stage(scenario)
    before = scenario.read_member(catalog.member)

    charged = scenario.charge(claim["id"])
    assert_fields(charged, state=K.CLAIM_CHARGED)
    assert_instant(charged["charged_at"], GRACE_EDGE_RECEIPT_CLOCK, "charged_at")
    assert_money(charged, net_fee_cents=19200, waiver_applied_cents=0)

    rows = scenario.ledger_rows(catalog.member)
    assert len(rows) == 1, f"an unwaived charge posts one row only, got {rows}"
    assert_fields(
        rows[0],
        kind=K.LEDGER_DAMAGE_FEE,
        direction=K.DIRECTION_DEBIT,
        damage_claim_id=claim["id"],
    )
    assert_money(rows[0], amount_cents=19200, balance_after_cents=19200)

    after = scenario.read_member(catalog.member)
    assert_money(after, outstanding_fee_cents=19200)
    assert after["outstanding_fee_cents"] >= K.DELINQUENCY_THRESHOLD_CENTS
    assert_fields(after, status=K.MEMBER_DELINQUENT, version=before["version"] + 1)


def test_the_delinquency_cascade_unwinds_only_the_forward_commitments(
    scenario: Scenario,
) -> None:
    """The matched booking is released and its unit freed; the returned turn is left alone.

    PRD §3.7: "Hop four is the delinquency cascade of §3.2 — every `WAITLISTED` reservation of that member moves `WAITLISTED → CANCELLED` and every `MATCHED` reservation moves `MATCHED → RELEASED`, while an `IN_POSSESSION` reservation is left alone, because garments already in the member's hands are recovered through the normal return path."
    PRD §3.7: "Hop five returns each unit released by hop four `RESERVED → IN_STOCK`, recomputes the depth fields of each affected style, and re-evaluates waitlist promotion for those styles."
    PRD §3.3: "Outside the `WAITLISTED` state, `waitlist_position` is null."

    Design: Difficulty/transitive_cascade/damage_charge_cascades_delinquency_to_unit_release
    """
    catalog, turn, claim, matched, waitlisted = _delinquency_stage(scenario)
    freed_unit_id = matched["allocated_unit_id"]
    assert freed_unit_id is not None, "the forward booking must hold a unit to free"
    assert_unit_position(
        scenario.read_unit(freed_unit_id), availability_state=K.AVAIL_RESERVED
    )

    scenario.charge(claim["id"])

    assert_fields(scenario.read_reservation(matched["id"]), state=K.RES_RELEASED)
    cancelled = scenario.read_reservation(waitlisted["id"])
    assert_fields(cancelled, state=K.RES_CANCELLED)
    assert_null(cancelled, "waitlist_position")

    # Hop five hands the garment back to the floor.
    assert_unit_position(
        scenario.read_unit(freed_unit_id),
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
    )

    # The reservation that produced the claim is in none of the two states hop
    # four moves, so the cascade must have skipped it.
    assert_fields(scenario.read_reservation(turn.reservation_id), state=K.RES_RETURNED)
    # And its own garment is still in reconditioning, untouched by the money.
    assert_unit_position(
        scenario.read_unit(turn.unit_id),
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_NEEDS_REPAIR,
    )
