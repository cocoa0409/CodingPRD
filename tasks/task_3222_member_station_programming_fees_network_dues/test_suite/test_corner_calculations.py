"""Calculation results, rounding order and constants. Queue B, section `calculations`."""
from test_helpers import (
    AUDITOR,
    GOVERNANCE,
    ApiErrorId,
    api_client,
    compensation_credit_cents,
    create_schedule,
    create_station,
    duration_factor_bps,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    operations_score,
    provisional_fee_cents,
    set_clock,
    station_payload_for_class,
    validate_error,
    validate_paginated,
)


def test_operations_score_follows_the_weighted_indices():
    """PRD §3.1: "Operations score is then 40 percent of the coverage index, plus 35
    percent of the staffing index, plus 25 percent of the newsroom index — the
    three weights sum to exactly one whole unit — with each index capped
    individually *before* the weights are applied".
    PRD §3.1: "a station of 250000 persons has begun two steps and scores 18".

    A coverage input of 1000000 persons gives an index of 90, six staff give 30
    and nine newsroom staff give 90, so the weighted score is
    36 + 10.5 + 22.5 = 69.00.

    Design: Corner/calculations/classification_works_on_plain_strings
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(
        call_sign="KUT", licensee_name="Austin Licensee", state_code="TX",
        dma_market_rank=40, dma_households=1000000, coverage_population=1000000,
        full_time_staff_count=6, newsroom_staff_count=9,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH")

    assert station["operations_score"] == 69.00
    assert station["membership_class"] == "CLASS_B", (
        "a 100-household index clears the CLASS_B breadth gate"
    )


def test_a_thinned_newsroom_drops_both_the_score_and_the_class():
    """PRD §3.1: "The newsroom index credits ten points for each full-time newsroom
    staff member and is also capped at 100."

    Holding the coverage and staffing inputs fixed and thinning the newsroom to a
    single member removes 80 points of newsroom index, which is 20 points of
    weighted score, and the household index alone no longer carries the ladder.

    Design: Corner/calculations/classification_works_on_plain_strings
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(
        call_sign="KUT", licensee_name="Austin Licensee", state_code="TX",
        dma_market_rank=40, dma_households=1000000, coverage_population=1000000,
        full_time_staff_count=6, newsroom_staff_count=1,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH")

    expected = operations_score(1000000, 6, 1)
    assert station["operations_score"] == expected
    assert station["membership_class"] == "CLASS_C", (
        f"the reduced score with a 100 household index should take the next rung, "
        f"got {station['membership_class']}"
    )


def test_rate_component_rounds_half_up_to_the_cent():
    """PRD §3.2: "a value landing on a fractional part of one half cent or more
    rounds upward, so an unrounded rate component of 124999.975 cents becomes
    125000 cents and never 124999".

    Design: Corner/calculations/fee_provisional_component_rounding_order
    """
    set_clock("2026-09-01T00:00:00Z")
    schedule = create_schedule(schedule_code="FY2026T", revenue_rate_bps=250)
    station = make_station_eligible(
        call_sign="KUT", licensee_name="Austin Licensee", state_code="TX",
        dma_market_rank=2, dma_households=12000000, coverage_population=10000000,
        full_time_staff_count=20, newsroom_staff_count=10,
        annual_local_revenue_cents=4999999, board_seat_region="REGION_SOUTH")

    data = get_success_data(api_client.preview_schedule(
        schedule["id"], station["id"], AUDITOR))
    rate_component = round(4999999 * 250 / 10000)
    market_component = round(
        provisional_fee_cents(schedule, station, station["membership_class"])
        - rate_component)

    assert rate_component == 125000, (
        f"the half-up rate component should be 125000, derived {rate_component}"
    )
    assert data["provisional_fee_cents"] == rate_component + market_component, (
        "the provisional fee must be the sum of the two rounded components"
    )


def test_tier_one_uses_the_schedules_own_market_multiplier():
    """PRD §3.2: "Tier 1 uses the schedule's own `market_size_multiplier_bps`; tiers
    2, 3 and 4 use a pinned ladder of 14000, 15500 and 16500 basis points
    respectively, so a station in the smallest market is charged the largest
    multiplier and the ladder does not respond to the schedule's own figure."

    The same CLASS_B station is priced at rank 2 (tier 1) and at rank 60 (tier 2)
    under one schedule whose own multiplier is 12500, so the tier ladder is what
    separates the two figures.

    Design: Corner/calculations/fee_provisional_component_rounding_order
    """
    set_clock("2026-09-01T00:00:00Z")
    schedule = create_schedule(schedule_code="FY2026U", market_size_multiplier_bps=12500)
    station = make_station_eligible(**station_payload_for_class("CLASS_B"))
    revenue = station["annual_local_revenue_cents"]
    rate_component = round(revenue * 250 / 10000)

    tier_one = provisional_fee_cents(schedule, {"dma_market_rank": 2,
                                                "annual_local_revenue_cents": revenue},
                                     "CLASS_B")
    tier_two = provisional_fee_cents(schedule, {"dma_market_rank": 60,
                                                "annual_local_revenue_cents": revenue},
                                     "CLASS_B")

    assert tier_one == rate_component + round(1200000 * 12500 / 10000)
    assert tier_two == rate_component + round(1200000 * 14000 / 10000)
    assert tier_two > tier_one, "the pinned ladder must not reuse the schedule's figure"

def test_class_multiplier_scales_only_the_market_component():
    """PRD §3.2: "it is the only place a station's class touches its fee; the rate
    component is never scaled by class."
    PRD §3.2: "`CLASS_A` members pay a surcharge at 11500 basis points".

    A CLASS_A station priced against a 1200000-cent base fee takes a market
    component of 1200000 scaled by 11500 basis points, with the rate component
    left at 120000.

    Design: Corner/calculations/fee_class_multiplier_applies_to_market_component_only
    """
    set_clock("2026-09-01T00:00:00Z")
    schedule = create_schedule(schedule_code="FY2026U")
    station = make_station_eligible(**{
        **station_payload_for_class("CLASS_A", call_sign="WNYC"),
    })

    assert station["membership_class"] == "CLASS_A"
    data = get_success_data(api_client.preview_schedule(
        schedule["id"], station["id"], AUDITOR))

    rate_component = round(station["annual_local_revenue_cents"] * 250 / 10000)
    assert rate_component == 120000
    expected_market = round(1200000 * 12500 / 10000 * 11500 / 10000)
    assert data["provisional_fee_cents"] == rate_component + expected_market, (
        f"expected {rate_component} + {expected_market}, "
        f"got {data['provisional_fee_cents']}"
    )


def test_duration_factor_caps_above_the_nominal_runtime():
    """PRD §3.6: "a three-hundred-and-sixty-one-second piece computes 20055 before
    the cap and 20000 after it, while a three-hundred-and-fifty-nine-second piece
    computes 19944 and is not capped."

    Design: Corner/calculations/credit_calculation_variants_diverge_by_duration
    """
    assert duration_factor_bps(360) == 20000
    assert duration_factor_bps(361) == 20000
    assert duration_factor_bps(359) == 19944


def test_a_short_piece_is_worth_less_than_a_long_one():
    """PRD §3.6: "The base credit is 50000 cents scaled by the duration factor and
    divided by ten thousand, rounded half up."
    PRD §3.6: "The final figure is the greater value capped at 250000 cents, which
    is the ceiling on any single piece."

    The comparison is made on the shortlisted branch, where the shelf credit
    stands alone — on the published branch both runtimes are lifted to the
    60000-cent conference floor and the duration difference disappears.

    Design: Corner/calculations/credit_calculation_variants_diverge_by_duration
    """
    short = compensation_credit_cents("CLASS_A", 90, 0, published=False)
    long = compensation_credit_cents("CLASS_A", 180, 0, published=False)

    assert short < long <= 250000, (
        f"the ninety-second piece should be worth less than the nominal one, "
        f"got {short} against {long}"
    )


def setup_at_capacity_batch():
    """Two ELIGIBLE stations in one fiscal year, ready to receive a pool."""
    from test_helpers import first_station_assessment

    set_clock("2026-09-01T00:00:00Z")
    create_schedule(schedule_code="FY2026W", annual_adjustment_bps=0,
                    base_fee_cents=1200000, revenue_rate_bps=250,
                    market_size_multiplier_bps=12500, minimum_fee_cents=100000,
                    maximum_fee_cents=5000000,
                    effective_from="2026-06-01T00:00:00Z",
                    effective_to="2027-06-01T00:00:00Z")
    first = make_station_eligible(
        call_sign="WKAR", licensee_name="Michigan Licensee", state_code="MI",
        dma_market_rank=5, dma_households=2200000, coverage_population=130000,
        full_time_staff_count=9, newsroom_staff_count=5,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST")
    second = make_station_eligible(
        call_sign="WETA", licensee_name="Potomac Licensee", state_code="VA",
        dma_market_rank=22, dma_households=700000, coverage_population=60000,
        full_time_staff_count=6, newsroom_staff_count=3,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH")
    return {"stations": [first, second],
            "assessments": [first_station_assessment(first),
                            first_station_assessment(second)]}


def test_pool_one_cent_below_the_flat_shares_is_refused():
    """PRD §3.9: "a pool of 239999 cents with the same two stations leaves a
    remainder of negative one, which is below every rank index, so both stations
    receive the flat 120000 and the batch would distribute 240000 cents — one
    cent more than the pool. That case is not scaled down or absorbed; the batch
    is rejected outright with `ERR_POOL_OVER_ALLOCATED` (HTTP 422)".

    Design: Corner/calculations/dues_pool_allocation_overflow_rejected
    """
    ctx = setup_at_capacity_batch()
    resp = api_client.allocate_pool(
        ctx["assessments"][0]["id"], {"total_pot_cents": 239999}, GOVERNANCE)

    validate_error(resp, ApiErrorId.ERR_POOL_OVER_ALLOCATED)


def test_pool_exactly_covering_the_flat_shares_is_accepted():
    """PRD §3.9: "The invariant is that the allocated shares sum exactly to the pool."

    A pool of 240001 leaves a remainder of one cent, which is handed to the
    highest-ranked station, so the batch distributes the whole pot.

    Design: Corner/calculations/dues_pool_allocation_overflow_rejected
    """
    from test_helpers import STATION_TIER_SHARE_CENTS

    ctx = setup_at_capacity_batch()
    resp = api_client.allocate_pool(
        ctx["assessments"][0]["id"], {"total_pot_cents": 240001}, GOVERNANCE)
    data = get_success_data(resp)

    assert sum(a["allocated_dues_cents"] for a in data) == 240001
    assert max(a["allocated_dues_cents"] for a in data) == STATION_TIER_SHARE_CENTS + 1

def test_standings_rank_uses_the_creation_instant_as_the_final_tie_break():
    """PRD §3.10: "Ranking uses a four-key key: `dues_arrears_cents` descending,
    then `operations_score` descending, then membership class ascending, then
    `created_at` ascending."
    PRD §3.10: "`created_at` is the final tie-break and is server-stamped with
    microsecond resolution; `MemberStation.id` is never consulted as a ranking
    input, not even as a last resort."

    Two stations identical on arrears, score and class are created a month apart,
    so the server-stamped instant alone separates them.

    Design: Corner/calculations/score_calculation_deterministic_ranking
    """
    from test_helpers import GOVERNANCE, set_clock as pin_clock

    set_clock("2026-09-01T00:00:00Z")
    create_schedule(schedule_code="FY2026X", annual_adjustment_bps=0,
                    base_fee_cents=1200000, revenue_rate_bps=250,
                    market_size_multiplier_bps=12500, minimum_fee_cents=100000,
                    maximum_fee_cents=5000000,
                    effective_from="2026-06-01T00:00:00Z",
                    effective_to="2027-06-01T00:00:00Z")
    shared = dict(
        dma_market_rank=58, dma_households=12000000, coverage_population=10000000,
        full_time_staff_count=20, newsroom_staff_count=10,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST")
    first = make_station_eligible(call_sign="WAMC", licensee_name="Albany Licensee",
                                  **shared)
    pin_clock("2026-10-01T00:00:00Z")
    second = make_station_eligible(call_sign="WAMQ", licensee_name="Berkshire Licensee",
                                   **shared)

    resp = api_client.list_standings(GOVERNANCE)
    data, meta = validate_paginated(resp)

    assert first["operations_score"] == second["operations_score"] == 100.00
    assert first["membership_class"] == second["membership_class"] == "CLASS_A"
    assert data[0]["id"] == first["id"], (
        "the earlier-created station should take the better standing"
    )
    assert data[1]["id"] == second["id"]


def test_a_contribution_is_reachable_from_both_foreign_key_directions():
    """PRD §2.7: "the contributions and agreements under a program, the candidacies
    under an election, the votes under a proposal, and every collection filtered
    by `station_id` — are the intended way for a caller to walk the hierarchy
    downward from a parent it already holds."
    PRD §2.7: "a window listed under one agreement, a slot listed under one feed,
    a candidacy listed under one election, or a vote listed under one proposal is
    returned only when its parent reference matches the parent named in the path."

    Design: Corner/calculations/content_reachability_by_program_and_station
    """
    from test_helpers import EDITOR, create_contribution, create_program

    set_clock("2026-09-01T00:00:00Z")
    create_schedule(schedule_code="FY2027M", annual_adjustment_bps=0,
                    base_fee_cents=1200000, revenue_rate_bps=250,
                    market_size_multiplier_bps=12500, minimum_fee_cents=100000,
                    maximum_fee_cents=5000000,
                    effective_from="2026-06-01T00:00:00Z",
                    effective_to="2027-06-01T00:00:00Z")
    station = make_station_eligible(
        call_sign="WGBH", licensee_name="Charles Licensee", state_code="MA",
        dma_market_rank=10, dma_households=800000, coverage_population=70000,
        full_time_staff_count=8, newsroom_staff_count=4,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST")
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1021", program_title="Commonwealth Desk")
    contribution = create_contribution(station, program, headline="Transit funding gap")

    by_program = get_success_data(api_client.list_program_contributions(
        program["id"], EDITOR))
    by_station = get_success_data(api_client.list_contributions(
        headers, {"station_id": station["id"]}))

    assert [row["id"] for row in by_program] == [contribution["id"]]
    assert [row["id"] for row in by_station] == [contribution["id"]]
