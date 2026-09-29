"""What the fleet reads back: fit personalization, demand signal and unit economics.

Three computed reads close the loop between the physical circuit and the next
merchandising decision, and none of them mutates anything.  A single fit-feedback
row feeds two different weightings at once — the member's confidence and the
style's demand — and the two economics reads and the two damage-risk reads each
answer the same question twice from deliberately disjoint inputs.  These tests
pin the accumulate-not-average shape of the confidence score, the tie-break on
`dominant_fit_rating`, the eligibility ladder on filing, the pinned
round-per-unit-then-average order of the realized averages, and the two
variant pairs where the same stored rows must yield two different numbers.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_FEEDBACK_ALREADY_EXISTS,
    ERR_FEEDBACK_NOT_ELIGIBLE,
)
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_event_fields,
    assert_fields,
    assert_list,
    assert_money,
    assert_ok,
    canonical_instant,
)
from test_helpers.fixtures import (
    Catalog,
    Scenario,
    Turn,
    completed_turn,
    finish_reconditioning,
    inspected_turn,
    received_turn,
    standard_catalog,
    turn_to_delivery,
    turn_to_receipt,
)

JsonDict = dict

# The first turn of the module is received on 2026-08-10 and the second on
# 2026-08-18, so feedback is filed at whichever clock the receipt left behind.
FIRST_FEEDBACK_CLOCK = K.CLOCK_AUG_10_0900
SECOND_FEEDBACK_CLOCK = K.CLOCK_AUG_18_0900
RISK_READ_CLOCK = K.CLOCK_AUG_25_0000


def _styling_catalog(
    scenario: Scenario, unit_codes: Sequence[str] = (K.UNIT_GOWN_001,)
) -> Catalog:
    """The standard world plus the two declared styling preferences."""
    return standard_catalog(
        scenario,
        unit_codes=unit_codes,
        preferred_categories=[K.CATEGORY_GOWN, K.CATEGORY_DRESS],
        size_profile=K.SIZE_M,
    )


def _file_feedback(
    scenario: Scenario,
    catalog: Catalog,
    reservation_id: str,
    fit_rating: str,
    occasion_match_score: int,
    keep_intent: Optional[bool] = None,
    comment: Optional[str] = None,
) -> JsonDict:
    """The holding member rates the turn."""
    return assert_created(
        scenario.client.file_fit_feedback(
            reservation_id,
            F.fit_feedback_payload(
                fit_rating, occasion_match_score, keep_intent, comment
            ),
            Scenario.member_headers(catalog.member),
        )
    )


def _feedback_attempt(
    scenario: Scenario,
    catalog: Catalog,
    reservation_id: str,
    fit_rating: str,
    occasion_match_score: int,
):
    """A raw filing attempt, so a test can inspect a refusal itself."""
    return scenario.client.file_fit_feedback(
        reservation_id,
        F.fit_feedback_payload(fit_rating, occasion_match_score),
        Scenario.member_headers(catalog.member),
    )


def _summary(scenario: Scenario, catalog: Catalog) -> JsonDict:
    return assert_ok(
        scenario.client.get_personalization_summary(
            catalog.member["id"], Scenario.member_headers(catalog.member)
        )
    )


def _feedback_rows(scenario: Scenario, params: JsonDict, total_count: int):
    rows, _meta = assert_list(
        scenario.client.list_fit_feedback(scenario.planner, params),
        total_count=total_count,
    )
    return rows


def _economics(scenario: Scenario, style_id: str, variant: str) -> JsonDict:
    return assert_ok(
        scenario.client.get_unit_economics(style_id, scenario.planner, {"variant": variant})
    )


def _risk(scenario: Scenario, catalog: Catalog, variant: str) -> JsonDict:
    return assert_ok(
        scenario.client.get_damage_risk(
            catalog.member["id"], scenario.adjuster, {"variant": variant}
        )
    )


def _rated_turn(scenario: Scenario) -> Tuple[Catalog, Turn, JsonDict]:
    """One returned turn, rated SLIGHTLY_SMALL with a 4 and a keep intent."""
    catalog = _styling_catalog(scenario)
    turn = received_turn(scenario, catalog, K.WINDOW_AUG_05_09)
    row = _file_feedback(
        scenario,
        catalog,
        turn.reservation_id,
        K.FIT_SLIGHTLY_SMALL,
        4,
        keep_intent=True,
        comment=K.FEEDBACK_COMMENT_SHOULDER,
    )
    return catalog, turn, row


def _two_rated_turns(scenario: Scenario) -> Tuple[Catalog, JsonDict, JsonDict]:
    """Two returned turns on two garments of one style, rated in that order."""
    catalog = _styling_catalog(scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002))
    first = received_turn(scenario, catalog, K.WINDOW_AUG_05_09)
    row_one = _file_feedback(
        scenario,
        catalog,
        first.reservation_id,
        K.FIT_SLIGHTLY_SMALL,
        4,
        keep_intent=True,
        comment=K.FEEDBACK_COMMENT_SHOULDER,
    )
    # The second leg is planned for 2026-08-13, clear of the closed seven-day
    # cadence window that opened at the first leg's 2026-08-05.
    second = received_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_13_17,
        planned_ship_date=K.SHIP_DATE_AUG_13,
        carrier_reference=K.CARRIER_OUT_AUG_13,
        dispatch_clock=K.CLOCK_AUG_13_0800,
        return_clock=K.CLOCK_AUG_17_0900,
        receipt_clock=SECOND_FEEDBACK_CLOCK,
    )
    row_two = _file_feedback(
        scenario,
        catalog,
        second.reservation_id,
        K.FIT_TOO_SMALL,
        2,
        keep_intent=False,
        comment=K.FEEDBACK_COMMENT_LENGTH,
    )
    return catalog, row_one, row_two


def _fleet_with_one_closed_turn(scenario: Scenario) -> Tuple[Catalog, Turn]:
    """Three garments of one style, exactly one of which has finished a clean turn."""
    catalog = standard_catalog(
        scenario,
        unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002, K.UNIT_GOWN_003),
    )
    turn = completed_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_09,
        soil_level=K.SOIL_LIGHT,
        damage_severity=K.DAMAGE_NONE,
    )
    return catalog, turn


def _turns_fourteen_months_apart(scenario: Scenario) -> Tuple[Catalog, Turn, Turn]:
    """A charged MODERATE claim in June 2025 and a clean turn in August 2026."""
    catalog = standard_catalog(scenario, clock=K.CLOCK_JUN_01_2025)
    first = inspected_turn(
        scenario,
        catalog,
        K.WINDOW_JUN_05_11_2025,
        K.SOIL_NONE,
        K.DAMAGE_MODERATE,
        K.GRADE_B,
        planned_ship_date=K.SHIP_DATE_JUN_05_2025,
        carrier_reference=K.CARRIER_OUT_JUN_05_2025,
        dispatch_clock=K.CLOCK_JUN_05_2025,
        return_clock=K.CLOCK_JUN_11_2025,
        receipt_clock=K.CLOCK_JUN_13_2025,
    )
    scenario.assess(first.claim_id)
    assert_fields(scenario.charge(first.claim_id), state=K.CLAIM_CHARGED)
    # The money is settled, so reconditioning may finish and the turn may close.
    finish_reconditioning(scenario, catalog, first)

    scenario.set_clock(K.CLOCK_AUG_03)
    second = completed_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_10_16,
        soil_level=K.SOIL_LIGHT,
        damage_severity=K.DAMAGE_NONE,
        planned_ship_date=K.SHIP_DATE_AUG_08,
        carrier_reference=K.CARRIER_OUT_AUG_08,
        dispatch_clock=K.CLOCK_AUG_10_0900,
        return_clock=K.CLOCK_AUG_16_0900,
        receipt_clock=SECOND_FEEDBACK_CLOCK,
    )
    scenario.set_clock(RISK_READ_CLOCK)
    return catalog, first, second


def test_one_feedback_row_scores_the_member_and_the_style_differently(
    scenario: Scenario,
) -> None:
    """The same row is worth 53 to the member's confidence and 11 to the style's demand.

    PRD §3.9: "Each `fit_rating` carries a signed size delta: `TOO_SMALL` is −2, `SLIGHTLY_SMALL` is −1, `TRUE_TO_SIZE` is 0, `SLIGHTLY_LARGE` is 1 and `TOO_LARGE` is 2. The mismatch penalty is the sum of the **absolute values** of those deltas across the member's rows, so a garment that ran two sizes small and one that ran two sizes large both count 2 against confidence rather than cancelling each other out."
    PRD §3.9: "The occasion bonus is the sum, over the member's rows, of `occasion_match_score` minus 3, so a score of 5 contributes positive 2, a score of 3 contributes nothing and a score of 1 contributes negative 2. The keep bonus is 5 for each row whose `keep_intent` is true. The raw score is a baseline of 50, plus 6 times the occasion bonus, plus the keep bonus, minus 8 times the mismatch penalty."
    PRD §3.1: "It sums three contributions: four points for every reservation ever raised against the style whose `state` is anything other than `SUPERSEDED`, three points for every fit-feedback record on the style whose `keep_intent` is true, and one point for each point of `occasion_match_score` across every fit-feedback record on the style."

    Design: Corner/calculations/calc_fit_confidence_and_demand_score_after_the_first_feedback
    """
    catalog, turn, row = _rated_turn(scenario)

    # A feedback row is an immutable event, and its three foreign keys are
    # copied from the reservation rather than supplied by the member.
    assert_event_fields(row)
    assert_fields(
        row,
        fit_rating=K.FIT_SLIGHTLY_SMALL,
        occasion_match_score=4,
        keep_intent=True,
        comment=K.FEEDBACK_COMMENT_SHOULDER,
        reservation_id=turn.reservation_id,
        member_id=catalog.member["id"],
        style_id=catalog.style_id,
    )

    # Mismatch penalty 1, occasion bonus 4 - 3 = 1, keep bonus 5:
    # 50 + 6 x 1 + 5 - 8 x 1 = 53.
    assert_fields(_summary(scenario, catalog), fit_confidence_score=53)
    assert_fields(scenario.read_member(catalog.member), fit_confidence_score=53)

    # The identical row read through the merchandising weighting: 4 points for
    # the one reservation, 3 for the keep intent, 4 for the occasion score.
    assert_fields(scenario.read_style(catalog.style_id), demand_score=11)


def test_the_summary_aggregates_two_rows_and_breaks_the_tie_on_created_at(
    scenario: Scenario,
) -> None:
    """One row each for two ratings, so the older row decides the dominant one.

    PRD §3.9: "The personalization read returns the member's `member_id`, `fit_confidence_score`, `feedback_count` as the number of rows, `keep_intent_count` as the number of rows whose `keep_intent` is true, and `dominant_fit_rating` as the `fit_rating` value occurring most often across the rows."
    PRD §3.9: "When two or more ratings tie on count, the winner is the tied rating whose earliest row has the smallest `created_at` — the member's oldest expressed preference breaks the tie."
    PRD §3.9: "The member's own `preferred_categories` and `size_profile` are echoed back unchanged; as §3.2 notes, `size_profile` is a declared free-form string and is never used as an allocation filter, the allocation filter being the reservation's own `requested_size`."

    Design: Corner/endpoints/endpoint_personalization_summary_aggregates_two_feedback_rows
    """
    catalog, row_one, row_two = _two_rated_turns(scenario)
    # The SLIGHTLY_SMALL row was filed on 2026-08-10 and the TOO_SMALL row on
    # 2026-08-18, so the counts tie at one apiece and the older row wins.
    assert canonical_instant(row_one["created_at"]) < canonical_instant(
        row_two["created_at"]
    )

    summary = _summary(scenario, catalog)
    assert_fields(
        summary,
        member_id=catalog.member["id"],
        feedback_count=2,
        keep_intent_count=1,
        dominant_fit_rating=K.FIT_SLIGHTLY_SMALL,
        size_profile=K.SIZE_M,
    )
    assert summary["preferred_categories"] == [K.CATEGORY_GOWN, K.CATEGORY_DRESS]

    rows = _feedback_rows(scenario, {"member_id": catalog.member["id"]}, total_count=2)
    assert {found["id"] for found in rows} == {row_one["id"], row_two["id"]}


def test_two_rows_accumulate_rather_than_average_the_confidence_score(
    scenario: Scenario,
) -> None:
    """31 is the accumulation of both rows; averaging their own scores gives 40 or 41.

    PRD §3.9: "Each `fit_rating` carries a signed size delta: `TOO_SMALL` is −2, `SLIGHTLY_SMALL` is −1, `TRUE_TO_SIZE` is 0, `SLIGHTLY_LARGE` is 1 and `TOO_LARGE` is 2. The mismatch penalty is the sum of the **absolute values** of those deltas across the member's rows, so a garment that ran two sizes small and one that ran two sizes large both count 2 against confidence rather than cancelling each other out."
    PRD §3.9: "The occasion bonus is the sum, over the member's rows, of `occasion_match_score` minus 3, so a score of 5 contributes positive 2, a score of 3 contributes nothing and a score of 1 contributes negative 2. The keep bonus is 5 for each row whose `keep_intent` is true. The raw score is a baseline of 50, plus 6 times the occasion bonus, plus the keep bonus, minus 8 times the mismatch penalty."
    PRD §3.1: "It sums three contributions: four points for every reservation ever raised against the style whose `state` is anything other than `SUPERSEDED`, three points for every fit-feedback record on the style whose `keep_intent` is true, and one point for each point of `occasion_match_score` across every fit-feedback record on the style."

    Design: Corner/endpoints/endpoint_personalization_summary_aggregates_two_feedback_rows
    """
    catalog, _row_one, _row_two = _two_rated_turns(scenario)

    # Mismatch penalty 1 + 2 = 3, occasion bonus (4 - 3) + (2 - 3) = 0, keep
    # bonus 5 for the single keep intent: 50 + 0 + 5 - 24 = 31.
    summary = _summary(scenario, catalog)
    assert_fields(summary, fit_confidence_score=31)
    assert_fields(scenario.read_member(catalog.member), fit_confidence_score=31)
    # Scoring each row on its own gives 53 and 28, whose mean is 40 or 41
    # depending on the rounding; neither is the accumulated answer.
    assert summary["fit_confidence_score"] not in (40, 41)

    # Two reservations at 4 points, one keep intent at 3, occasion scores 4 + 2.
    assert_fields(scenario.read_style(catalog.style_id), demand_score=17)


def test_fit_feedback_is_refused_before_the_return_and_on_the_replay(
    scenario: Scenario,
) -> None:
    """Rank 36 waits for the garment to come back; rank 37 allows only one rating.

    PRD §3.9: "At rank 36, the reservation's `state` must be `RETURNED` or `CLOSED`, otherwise `ERR_FEEDBACK_NOT_ELIGIBLE` (409) — a member cannot rate the fit of a garment they have not yet sent back, and rows in `MATCHED`, `SHIPPED`, `IN_POSSESSION`, `RETURN_INITIATED`, `RELEASED`, `CANCELLED` and `SUPERSEDED` are all refused."
    PRD §3.9: "At rank 37, no feedback row may already exist for this reservation, otherwise `ERR_FEEDBACK_ALREADY_EXISTS` (409): one rating per turn, so a member cannot stack ratings to move a style's demand score."

    Design: Corner/validations/validation_fit_feedback_is_refused_before_the_return_and_refused_a_second_time
    """
    catalog = _styling_catalog(scenario)
    turn = turn_to_delivery(scenario, catalog, K.WINDOW_AUG_05_09)
    assert_fields(
        scenario.read_reservation(turn.reservation_id), state=K.RES_IN_POSSESSION
    )

    early = _feedback_attempt(
        scenario, catalog, turn.reservation_id, K.FIT_TRUE_TO_SIZE, 3
    )
    assert_error(early, ERR_FEEDBACK_NOT_ELIGIBLE)
    _feedback_rows(scenario, {"reservation_id": turn.reservation_id}, total_count=0)

    turn_to_receipt(scenario, catalog, turn)
    assert_fields(scenario.read_reservation(turn.reservation_id), state=K.RES_RETURNED)

    # The identical body is now accepted, and the optional flag defaults false.
    accepted = _file_feedback(
        scenario, catalog, turn.reservation_id, K.FIT_TRUE_TO_SIZE, 3
    )
    assert_fields(
        accepted,
        fit_rating=K.FIT_TRUE_TO_SIZE,
        occasion_match_score=3,
        keep_intent=False,
    )

    replay = _feedback_attempt(
        scenario, catalog, turn.reservation_id, K.FIT_TRUE_TO_SIZE, 3
    )
    assert_error(replay, ERR_FEEDBACK_ALREADY_EXISTS)
    rows = _feedback_rows(
        scenario, {"reservation_id": turn.reservation_id}, total_count=1
    )
    assert rows[0]["id"] == accepted["id"]


def test_the_average_margin_per_turn_rounds_per_unit_before_averaging(
    scenario: Scenario,
) -> None:
    """Three garments, one finished turn, and only one evaluation order gives -20556.

    PRD §3.9: "That unit's margin is revenue plus recovery plus end-of-life value, minus the unit's `acquisition_cost_cents`, minus servicing. The unit's margin per turn is its margin divided by its `turns_completed`, with the divisor floored at 1, rounded half up."
    PRD §3.9: "The rounding order for the fleet-level figure is **pinned**: round per unit first, then average. `avg_margin_per_turn_cents` is the sum of the per-unit rounded margins-per-turn, divided by the number of units, rounded half up."
    PRD §3.9: "Summing all unit margins and dividing once by total turns is a different number and is explicitly not what this field means; nor is `avg_margin_per_turn_cents` derived from any of the other averaged fields."

    Design: Difficulty/combinatorial_formula/unit_economics_round_per_unit_then_average_order_pinned
    """
    catalog, turn = _fleet_with_one_closed_turn(scenario)

    # The one garment that worked: 3333 cents attributed, 1200 cleaning plus
    # 800 photography of servicing, one completed turn.
    rented = scenario.read_unit(turn.unit_id)
    assert_fields(rented, turns_completed=1)
    assert_money(
        rented,
        realized_revenue_cents=K.PLAN_SIG4_BASE_REVENUE_PER_TURN_CENTS,
        cumulative_servicing_cost_cents=2000,
        acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
    )
    for unit in catalog.units:
        if unit["id"] == turn.unit_id:
            continue
        idle = scenario.read_unit(unit["id"])
        assert_fields(idle, turns_completed=0)
        assert_money(
            idle,
            realized_revenue_cents=0,
            cumulative_servicing_cost_cents=0,
            acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
        )

    realized = _economics(scenario, catalog.style_id, K.VARIANT_REALIZED)
    assert_fields(realized, unit_count=3)
    # Per-unit margins are 3333 - 2000 - 21000 = -19667 and -21000 twice, each
    # over one chargeable turn, and (-19667 - 21000 - 21000) / 3 is -20556.
    assert_money(realized, avg_margin_per_turn_cents=-20556)
    # Aggregating the margins over the three chargeable turns first would give
    # -61667, and truncating toward zero instead of rounding would give -20555.
    assert realized["avg_margin_per_turn_cents"] not in (-61667, -20555)


def test_every_realized_average_divides_by_the_unit_count(
    scenario: Scenario,
) -> None:
    """The two never-rented garments sit in every denominator, including servicing.

    PRD §3.9: "For each unit, revenue is the unit's `realized_revenue_cents`, itself the sum of `revenue_attributed_cents` over that unit's `CLOSED` reservations; recovery is the sum of `net_fee_cents` over the damage claims on that unit whose `state` is `CHARGED`; end-of-life value is the sum of `net_recovery_cents` over the resale listings on that unit whose `state` is `SOLD`; and servicing is the unit's `cumulative_servicing_cost_cents`."
    PRD §3.9: "That unit's margin is revenue plus recovery plus end-of-life value, minus the unit's `acquisition_cost_cents`, minus servicing. The unit's margin per turn is its margin divided by its `turns_completed`, with the divisor floored at 1, rounded half up."
    PRD §3.9: "The `REALIZED` response reports `style_id`, the `variant`, `unit_count` as the number of units, and five further averages each computed as a sum over units divided by the unit count and rounded half up: `avg_acquisition_cost_cents` over `acquisition_cost_cents`; `avg_revenue_per_unit_cents` over revenue **plus recovery** for each unit, so charged damage fees are counted as revenue recovered rather than as a separate line; `avg_servicing_cost_per_unit_cents` over servicing; `avg_eol_value_cents` over end-of-life value; and `avg_margin_per_unit_cents` over the per-unit margins."

    Design: Difficulty/combinatorial_formula/unit_economics_round_per_unit_then_average_order_pinned
    """
    catalog, _turn = _fleet_with_one_closed_turn(scenario)

    realized = _economics(scenario, catalog.style_id, K.VARIANT_REALIZED)
    assert_fields(realized, style_id=catalog.style_id, variant=K.VARIANT_REALIZED, unit_count=3)
    # 3333 / 3 = 1111 exactly; 2000 / 3 = 666.67 which rounds half up to 667;
    # 63000 / 3 = 21000; no unit is SOLD, so there is no end-of-life value.
    assert_money(
        realized,
        avg_acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
        avg_revenue_per_unit_cents=1111,
        avg_servicing_cost_per_unit_cents=667,
        avg_eol_value_cents=0,
        avg_margin_per_unit_cents=-20556,
    )


def test_the_realized_variant_reads_the_whole_persisted_fleet(
    scenario: Scenario,
) -> None:
    """Three stored garments answer REALIZED where PROJECTED sees one notional one.

    PRD §3.9: "The `REALIZED` variant, which is the default, is chronological actuals. Its unit set is every `RentalUnit` of the style in **any** `availability_state`, including `RETIRED` and `SOLD` — a fleet's economics must not improve merely because its worst garments were written off."
    PRD §3.9: "Because the two variants read disjoint inputs, the same stored data yields two different numbers under the same field names, and a planner comparing them is comparing plan against outcome."

    Design: Difficulty/dual_variant_calc/style_unit_economics_realized_vs_projected_diverge
    """
    catalog, _turn = _fleet_with_one_closed_turn(scenario)

    realized = _economics(scenario, catalog.style_id, K.VARIANT_REALIZED)
    projected = _economics(scenario, catalog.style_id, K.VARIANT_PROJECTED)

    assert_fields(realized, variant=K.VARIANT_REALIZED, unit_count=3)
    assert_money(realized, avg_margin_per_turn_cents=-20556)

    # Omitting the parameter altogether must land on the same read.
    default_read = assert_ok(
        scenario.client.get_unit_economics(catalog.style_id, scenario.planner)
    )
    assert_fields(default_read, variant=K.VARIANT_REALIZED, unit_count=3)

    # Same field names, disjoint inputs, different answers.
    assert projected["unit_count"] == 1
    for field in (
        "avg_revenue_per_unit_cents",
        "avg_servicing_cost_per_unit_cents",
        "avg_eol_value_cents",
        "avg_margin_per_unit_cents",
        "avg_margin_per_turn_cents",
    ):
        assert realized[field] != projected[field], (
            f"{field} is {realized[field]} under both variants, "
            "so one variant is reading the other's inputs"
        )


def test_the_projected_variant_amortises_the_plan_over_twelve_turns(
    scenario: Scenario,
) -> None:
    """PROJECTED reads no stored garment at all: 2400 over 12 planned turns is 200.

    PRD §3.9: "The `PROJECTED` variant is forward-looking plan arithmetic over a single notional garment, and it reads no `RentalUnit`, `DamageClaim` or `ResaleListing` row whatsoever."
    PRD §3.9: "The projected unit margin is the reference revenue of 3,200 cents per turn multiplied by the planned turns, plus the style's `planned_eol_value_cents`, minus the style's `acquisition_cost_cents`, minus a flat projected servicing cost of 2,000 cents per turn multiplied by the planned turns."
    PRD §3.9: "The response reports `unit_count` as exactly 1; `avg_acquisition_cost_cents` as the style's `acquisition_cost_cents`; `avg_revenue_per_unit_cents` as 3,200 multiplied by the planned turns; `avg_servicing_cost_per_unit_cents` as 2,000 multiplied by the planned turns; `avg_eol_value_cents` as the style's `planned_eol_value_cents`; `avg_margin_per_unit_cents` as the projected unit margin; and `avg_margin_per_turn_cents` as the projected unit margin divided by the planned turns, rounded half up."

    Design: Difficulty/dual_variant_calc/style_unit_economics_realized_vs_projected_diverge
    """
    catalog, _turn = _fleet_with_one_closed_turn(scenario)

    projected = _economics(scenario, catalog.style_id, K.VARIANT_PROJECTED)
    assert_fields(projected, variant=K.VARIANT_PROJECTED, unit_count=1)
    # 3200 x 12 = 38400 revenue, 2000 x 12 = 24000 servicing, 9000 planned
    # end-of-life value, 21000 acquisition: 38400 + 9000 - 21000 - 24000 = 2400.
    assert_money(
        projected,
        avg_acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
        avg_revenue_per_unit_cents=38400,
        avg_servicing_cost_per_unit_cents=24000,
        avg_eol_value_cents=K.STYLE_GOWN_EOL_VALUE_CENTS,
        avg_margin_per_unit_cents=2400,
        avg_margin_per_turn_cents=200,
    )

    # The three persisted garments and their one finished turn are invisible here.
    realized = _economics(scenario, catalog.style_id, K.VARIANT_REALIZED)
    assert realized["avg_margin_per_turn_cents"] != projected["avg_margin_per_turn_cents"]
    assert realized["unit_count"] == 3


def test_the_lifetime_damage_risk_counts_the_fourteen_month_old_claim(
    scenario: Scenario,
) -> None:
    """Two closed turns and one charged MODERATE claim compose to exactly 40.

    PRD §3.9: "Under `LIFETIME`, which is the default, the scope is every reservation of the member whose `state` is `CLOSED`, with no date filter."
    PRD §3.9: "The severity index is the sum of severity weights over the claims in scope — 1 for `MINOR`, 2 for `MODERATE`, 3 for `SEVERE` and 4 for `LOSS` — divided by the number of claims in scope, again with the divisor floored at 1."
    PRD §3.9: "The raw score is 100 multiplied by the sum of three weighted terms: 0.5 times the claim rate, plus 0.3 times the smaller of 1.0 and the severity index divided by 4.0, plus 0.2 times the late rate."

    Design: Difficulty/dual_variant_calc/member_damage_risk_lifetime_vs_rolling_12m_diverge
    """
    catalog, first, second = _turns_fourteen_months_apart(scenario)
    for turn in (first, second):
        assert_fields(scenario.read_reservation(turn.reservation_id), state=K.RES_CLOSED)
    assert_fields(scenario.read_claim(first.claim_id), state=K.CLAIM_CHARGED)

    lifetime = _risk(scenario, catalog, K.VARIANT_LIFETIME)
    assert_fields(
        lifetime,
        member_id=catalog.member["id"],
        variant=K.VARIANT_LIFETIME,
        claim_count=1,
        severity_points=2,
        late_return_count=0,
    )
    # Claim rate 1/2 = 0.5, severity index 2 capped at 1.0 by 2/4 = 0.5, late
    # rate 0: 100 x (0.5 x 0.5 + 0.3 x 0.5 + 0.2 x 0) = 40.
    assert_fields(lifetime, damage_risk_score=40)

    # Omitting the parameter must land on the same read.
    default_read = assert_ok(
        scenario.client.get_damage_risk(catalog.member["id"], scenario.adjuster)
    )
    assert_fields(default_read, variant=K.VARIANT_LIFETIME, damage_risk_score=40)


def test_the_rolling_window_drops_the_old_turn_and_its_claim(
    scenario: Scenario,
) -> None:
    """The 2025 turn falls out of both the numerator and the denominator, so 0 and LOW.

    PRD §3.9: "Under `ROLLING_12M`, the scope is those `CLOSED` reservations whose `returned_at` falls in the half-open window that begins 365 days before the current logical clock, inclusive, and ends at the current logical clock, exclusive."
    PRD §3.9: "`damage_risk_band` is `LOW` when the score is at most 20, `ELEVATED` when it is at most 49, and `HIGH` otherwise, so 20 is `LOW`, 21 is `ELEVATED`, 49 is `ELEVATED` and 50 is `HIGH`."
    PRD §3.9: "Because `ROLLING_12M` drops an old turn from both the numerator and the denominator, the same stored rows yield a different score under the two variants and can yield a different band."

    Design: Difficulty/dual_variant_calc/member_damage_risk_lifetime_vs_rolling_12m_diverge
    """
    catalog, _first, _second = _turns_fourteen_months_apart(scenario)

    # The clock is 2026-08-25, so the window opens on 2025-08-25: the June 2025
    # turn and its claim are outside it and the August 2026 turn is inside.
    rolling = _risk(scenario, catalog, K.VARIANT_ROLLING_12M)
    assert_fields(
        rolling,
        variant=K.VARIANT_ROLLING_12M,
        claim_count=0,
        severity_points=0,
        late_return_count=0,
        damage_risk_score=0,
        damage_risk_band=K.RISK_LOW,
    )

    lifetime = _risk(scenario, catalog, K.VARIANT_LIFETIME)
    assert_fields(lifetime, damage_risk_band=K.RISK_ELEVATED)
    assert K.RISK_BAND_LOW_CEILING < lifetime["damage_risk_score"] <= K.RISK_BAND_ELEVATED_CEILING
    # One set of stored rows, two scopes, two scores and two bands.
    assert lifetime["damage_risk_score"] != rolling["damage_risk_score"]
    assert lifetime["damage_risk_band"] != rolling["damage_risk_band"]
