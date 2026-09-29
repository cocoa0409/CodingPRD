"""The six ordered gates a drafted offer must clear on its way to SENT: curfew
first, then buffered stage-slot exclusivity, the artist radius clause, genre
adjacency, the fair-wide per-day capacity ceiling and, last of all, the edition's
talent budget cap.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CANONICAL_CLOCK_UTC
from test_helpers.fixtures import (
    create_agent,
    create_artist,
    create_edition,
    create_offer,
    create_stage,
    get_edition,
    get_offer,
    get_stage,
    set_clock,
)
from test_helpers.test_users import TALENT_BUYER_HEADERS

INCUMBENT_GUARANTEE_CENTS = 9_000_000
CANDIDATE_GUARANTEE_CENTS = 4_000_000


def _send(offer_id):
    """The buyer's send, returned unvalidated so each test judges the outcome."""
    return api_client.send_offer(offer_id, TALENT_BUYER_HEADERS)


# ---------------------------------------------------------------------------
# Curfew ahead of the buffered stage-slot rule
# ---------------------------------------------------------------------------
def _world_with_a_curfew_and_a_buffer_breach():
    """One COUNTRY hold from 14:00 to 23:00 on the grandstand, plus two drafted
    offers for a ROCK act on the same date: one that runs past the 23:30 curfew
    and collides inside the 120-minute changeover buffer, and one that respects
    the curfew while still colliding.
    """
    set_clock(CANONICAL_CLOCK_UTC)
    edition = create_edition(
        name="Priority Pair Fair A",
        talent_budget_cap_cents=40_000_000,
        refund_reserve_cents=15_000_000,
        max_shows_per_day=2,
        curfew_utc_time="23:30",
    )
    stage = create_stage(
        edition["id"],
        name="Grandstand",
        changeover_buffer_minutes=120,
        slot_soft_cap=4,
    )
    agent = create_agent()
    incumbent_artist = create_artist(
        agent["id"],
        name="Dust Road Revival",
        genre="COUNTRY",
        audience_segment="FAMILY",
        base_draw_score=62.50,
    )
    candidate_artist = create_artist(
        agent["id"],
        name="Nine Volt Sermon",
        genre="ROCK",
        audience_segment="YOUNG_ADULT",
        base_draw_score=55.00,
    )
    incumbent = create_offer(
        edition["id"],
        incumbent_artist["id"],
        stage["id"],
        offered_guarantee_cents=INCUMBENT_GUARANTEE_CENTS,
        backend_split_pct=0.8500,
        backend_breakeven_cents=6_000_000,
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-22T14:00:00.000Z",
        load_out_end_utc="2026-08-22T23:00:00.000Z",
    )
    validate_success(_send(incumbent["id"]))
    past_curfew = create_offer(
        edition["id"],
        candidate_artist["id"],
        stage["id"],
        offered_guarantee_cents=CANDIDATE_GUARANTEE_CENTS,
        backend_split_pct=0.8000,
        backend_breakeven_cents=3_000_000,
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-22T22:00:00.000Z",
        load_out_end_utc="2026-08-23T02:00:00.000Z",
    )
    inside_curfew = create_offer(
        edition["id"],
        candidate_artist["id"],
        stage["id"],
        offered_guarantee_cents=CANDIDATE_GUARANTEE_CENTS,
        backend_split_pct=0.8000,
        backend_breakeven_cents=3_000_000,
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-22T20:00:00.000Z",
        load_out_end_utc="2026-08-22T23:00:00.000Z",
    )
    return {
        "edition": edition,
        "stage": stage,
        "incumbent": incumbent,
        "past_curfew": past_curfew,
        "inside_curfew": inside_curfew,
    }


class TestCurfewIsWeighedBeforeTheStageBuffer:
    """A send that breaches the municipal curfew and the changeover buffer at
    once reports the curfew, because public safety comes first.
    """

    def test_send_past_curfew_inside_the_buffer_reports_the_curfew_violation(self):
        """An occupation ending at 02:00 the following morning runs past the
        edition's 23:30 curfew and also lands inside the 120 minutes of
        changeover the grandstand demands between two occupations. The curfew
        gate is weighed first, so that is the failure reported.

        "The first is **curfew**, which is checked ahead of every scheduling-conflict and budget rule because public safety outranks convenience."

        Design: Difficulty/priority_pair_validation_conflict/curfew_safety_outranks_stage_slot_conflict
        """
        world = _world_with_a_curfew_and_a_buffer_breach()

        response = _send(world["past_curfew"]["id"])

        validate_error(response, ApiErrorId.ERR_CURFEW_VIOLATION.value)

    def test_curfew_compliant_send_overlapping_a_hold_reports_the_slot_conflict(self):
        """The same act on the same date, ending exactly at 23:00 and therefore
        inside the 23:30 curfew, still opens its load-in while the standing hold's
        buffered occupation is running, so the stage-slot gate refuses it.

        "the candidate's `load_in_start_utc` falls strictly before the existing hold's `load_out_end_utc` advanced by the stage's `changeover_buffer_minutes`"

        Design: Difficulty/priority_pair_validation_conflict/curfew_safety_outranks_stage_slot_conflict
        """
        world = _world_with_a_curfew_and_a_buffer_breach()

        response = _send(world["inside_curfew"]["id"])

        validate_error(response, ApiErrorId.ERR_STAGE_SLOT_CONFLICT.value)

    def test_neither_refused_send_takes_a_hold_or_encumbers_the_budget(self):
        """Both refused sends leave their offers drafted, so the grandstand still
        counts the single standing hold and the edition's encumbrance still shows
        only the guarantee of the offer that was actually sent.

        "It holds no stage slot and it encumbers no budget."

        Design: Difficulty/priority_pair_validation_conflict/curfew_safety_outranks_stage_slot_conflict
        """
        world = _world_with_a_curfew_and_a_buffer_breach()

        validate_error(
            _send(world["past_curfew"]["id"]), ApiErrorId.ERR_CURFEW_VIOLATION.value
        )
        validate_error(
            _send(world["inside_curfew"]["id"]),
            ApiErrorId.ERR_STAGE_SLOT_CONFLICT.value,
        )

        assert get_offer(world["past_curfew"]["id"])["status"] == "DRAFT"
        assert get_offer(world["inside_curfew"]["id"])["status"] == "DRAFT"
        assert get_stage(world["stage"]["id"])["held_show_count"] == 1
        edition = get_edition(world["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 9000000


# ---------------------------------------------------------------------------
# Genre adjacency ahead of the talent budget cap
# ---------------------------------------------------------------------------
def _world_with_an_adjacency_and_a_budget_breach():
    """A COUNTRY hold on 2026-08-22 leaving only 1,000,000 cents of headroom
    under a 10,000,000-cent budget cap, plus two drafted offers on 2026-08-23:
    a second COUNTRY act, which is adjacent as well as unaffordable, and a
    COMEDY act, which is merely unaffordable.
    """
    set_clock(CANONICAL_CLOCK_UTC)
    edition = create_edition(
        name="Priority Pair Fair B",
        talent_budget_cap_cents=10_000_000,
        refund_reserve_cents=5_000_000,
        max_shows_per_day=2,
        curfew_utc_time="23:30",
    )
    stage = create_stage(
        edition["id"],
        name="Grandstand",
        changeover_buffer_minutes=120,
        slot_soft_cap=4,
    )
    agent = create_agent()
    incumbent_artist = create_artist(
        agent["id"],
        name="Dust Road Revival",
        genre="COUNTRY",
        audience_segment="FAMILY",
        base_draw_score=62.50,
    )
    same_genre_artist = create_artist(
        agent["id"],
        name="Copper Creek Band",
        genre="COUNTRY",
        audience_segment="FAMILY",
        base_draw_score=48.00,
    )
    other_genre_artist = create_artist(
        agent["id"],
        name="Marsh Street Quartet",
        genre="COMEDY",
        audience_segment="ADULT_45_PLUS",
        base_draw_score=40.00,
    )
    incumbent = create_offer(
        edition["id"],
        incumbent_artist["id"],
        stage["id"],
        offered_guarantee_cents=INCUMBENT_GUARANTEE_CENTS,
        backend_split_pct=0.8500,
        backend_breakeven_cents=6_000_000,
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-22T14:00:00.000Z",
        load_out_end_utc="2026-08-22T23:00:00.000Z",
    )
    validate_success(_send(incumbent["id"]))
    same_genre_offer = create_offer(
        edition["id"],
        same_genre_artist["id"],
        stage["id"],
        offered_guarantee_cents=5_000_000,
        backend_split_pct=0.8000,
        backend_breakeven_cents=3_000_000,
        target_show_date="2026-08-23",
        load_in_start_utc="2026-08-23T14:00:00.000Z",
        load_out_end_utc="2026-08-23T23:00:00.000Z",
    )
    other_genre_offer = create_offer(
        edition["id"],
        other_genre_artist["id"],
        stage["id"],
        offered_guarantee_cents=5_000_000,
        backend_split_pct=0.8000,
        backend_breakeven_cents=3_000_000,
        target_show_date="2026-08-23",
        load_in_start_utc="2026-08-23T14:00:00.000Z",
        load_out_end_utc="2026-08-23T23:00:00.000Z",
    )
    return {
        "edition": edition,
        "stage": stage,
        "incumbent": incumbent,
        "same_genre_offer": same_genre_offer,
        "other_genre_offer": other_genre_offer,
    }


class TestGenreAdjacencyIsWeighedBeforeTheBudgetCap:
    """Programming variety is tested before fiscal capacity, which the service
    checks after everything else.
    """

    def test_adjacent_same_genre_send_over_budget_reports_the_adjacency_conflict(self):
        """A second COUNTRY act on the grandstand the calendar day after the
        standing COUNTRY hold breaks programming variety, and its 5,000,000-cent
        guarantee would also carry the edition past its 10,000,000-cent cap.
        Adjacency is the fourth gate and the budget the sixth, so adjacency wins.

        "is held on the same stage on the previous calendar day, on the same calendar day or on the next calendar day"

        Design: Difficulty/priority_pair_validation_conflict/genre_adjacency_constraint_outranks_talent_budget
        """
        world = _world_with_an_adjacency_and_a_budget_breach()

        response = _send(world["same_genre_offer"]["id"])

        validate_error(response, ApiErrorId.ERR_GENRE_ADJACENCY_CONFLICT.value)

    def test_send_breaching_only_the_cap_reports_the_talent_budget_error(self):
        """The same date, the same stage and the same guarantee for an act of a
        different genre clears programming variety, leaving the recomputed
        encumbrance of 14,000,000 cents against a 10,000,000-cent cap as the only
        live breach — which proves the cap was genuinely exceeded all along.

        "A recomputed total exactly equal to the cap is allowed; one cent above it is refused with `ERR_TALENT_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/genre_adjacency_constraint_outranks_talent_budget
        """
        world = _world_with_an_adjacency_and_a_budget_breach()

        response = _send(world["other_genre_offer"]["id"])

        validate_error(response, ApiErrorId.ERR_TALENT_BUDGET_EXCEEDED.value)

    def test_neither_refused_send_encumbers_the_budget_or_takes_a_hold(self):
        """After both refusals the encumbrance still reflects only the one offer
        that reached the agent, and the grandstand still counts one hold.

        "Offers sitting in `DRAFT`, `DECLINED`, `WITHDRAWN` or `EXPIRED` contribute nothing at all"

        Design: Difficulty/priority_pair_validation_conflict/genre_adjacency_constraint_outranks_talent_budget
        """
        world = _world_with_an_adjacency_and_a_budget_breach()

        validate_error(
            _send(world["same_genre_offer"]["id"]),
            ApiErrorId.ERR_GENRE_ADJACENCY_CONFLICT.value,
        )
        validate_error(
            _send(world["other_genre_offer"]["id"]),
            ApiErrorId.ERR_TALENT_BUDGET_EXCEEDED.value,
        )

        edition = get_edition(world["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 9000000
        assert get_offer(world["same_genre_offer"]["id"])["status"] == "DRAFT"
        assert get_offer(world["other_genre_offer"]["id"])["status"] == "DRAFT"
        assert get_stage(world["stage"]["id"])["held_show_count"] == 1


# ---------------------------------------------------------------------------
# The talent budget cap at its inclusive upper bound
# ---------------------------------------------------------------------------
def _world_at_the_talent_budget_boundary():
    """An edition authorised for 12,500,000 cents of guarantees with nothing yet
    committed, one drafted offer asking exactly that figure and a second asking a
    single cent, so the pair straddles the cap by one integer.
    """
    set_clock(CANONICAL_CLOCK_UTC)
    edition = create_edition(
        name="Budget Boundary Fair",
        talent_budget_cap_cents=12_500_000,
        refund_reserve_cents=5_000_000,
        max_shows_per_day=2,
        curfew_utc_time="23:30",
    )
    stage = create_stage(
        edition["id"],
        name="Grandstand",
        changeover_buffer_minutes=120,
        slot_soft_cap=4,
    )
    agent = create_agent()
    first_artist = create_artist(
        agent["id"],
        name="Dust Road Revival",
        genre="COUNTRY",
        audience_segment="FAMILY",
        base_draw_score=62.50,
    )
    second_artist = create_artist(
        agent["id"],
        name="Marsh Street Quartet",
        genre="COMEDY",
        audience_segment="ADULT_45_PLUS",
        base_draw_score=40.00,
    )
    at_cap = create_offer(
        edition["id"],
        first_artist["id"],
        stage["id"],
        offered_guarantee_cents=12_500_000,
        backend_split_pct=0.8500,
        backend_breakeven_cents=6_000_000,
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-22T14:00:00.000Z",
        load_out_end_utc="2026-08-22T23:00:00.000Z",
    )
    one_cent_over = create_offer(
        edition["id"],
        second_artist["id"],
        stage["id"],
        offered_guarantee_cents=1,
        backend_split_pct=0.8000,
        backend_breakeven_cents=0,
        target_show_date="2026-08-25",
        load_in_start_utc="2026-08-25T14:00:00.000Z",
        load_out_end_utc="2026-08-25T23:00:00.000Z",
    )
    return {
        "edition": edition,
        "stage": stage,
        "at_cap": at_cap,
        "one_cent_over": one_cent_over,
    }


class TestTalentBudgetCapIsInclusive:
    """The encumbrance may reach the authorised ceiling exactly; the next cent is
    refused.
    """

    def test_send_taking_the_encumbrance_exactly_to_the_cap_is_admitted(self):
        """A guarantee of 12,500,000 cents against an authorised ceiling of
        12,500,000 cents leaves the recomputed encumbrance sitting exactly on the
        cap, which the fiscal gate admits, and the offer reaches the agent.

        "A recomputed total exactly equal to the cap is allowed; one cent above it is refused with `ERR_TALENT_BUDGET_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/talent_budget_cap_exact_equality_then_one_cent_over
        """
        world = _world_at_the_talent_budget_boundary()

        offer = validate_success(_send(world["at_cap"]["id"]))

        assert offer["status"] == "SENT"
        edition = get_edition(world["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 12500000
        assert (
            edition["committed_guarantee_total_cents"]
            == edition["talent_budget_cap_cents"]
        )

    def test_send_taking_the_encumbrance_one_cent_past_the_cap_is_refused(self):
        """With the ceiling already reached to the cent, an offer asking a single
        further cent would carry the recomputed encumbrance to 12,500,001 cents,
        one cent past what the edition authorised, so the fiscal gate refuses it
        and the ledger is left where it stood.

        "The edition's `committed_guarantee_total_cents` is recomputed as though this offer were already sent, and the result must not exceed the edition's `talent_budget_cap_cents`."

        Design: Difficulty/boundary_precision_check/talent_budget_cap_exact_equality_then_one_cent_over
        """
        world = _world_at_the_talent_budget_boundary()
        validate_success(_send(world["at_cap"]["id"]))

        response = _send(world["one_cent_over"]["id"])

        validate_error(response, ApiErrorId.ERR_TALENT_BUDGET_EXCEEDED.value)
        assert get_offer(world["one_cent_over"]["id"])["status"] == "DRAFT"
        edition = get_edition(world["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 12500000


# ---------------------------------------------------------------------------
# The changeover buffer at minute granularity
# ---------------------------------------------------------------------------
def _world_at_the_changeover_buffer_boundary():
    """A COUNTRY hold clearing the grandstand at 23:00, so the buffered forbidden
    zone runs to 01:00 the next morning, plus two drafted offers for a ROCK act
    the following day: one loading in ninety minutes after the hold clears and
    one loading in exactly a full buffer later.
    """
    set_clock(CANONICAL_CLOCK_UTC)
    edition = create_edition(
        name="Buffer Boundary Fair",
        talent_budget_cap_cents=40_000_000,
        refund_reserve_cents=15_000_000,
        max_shows_per_day=2,
        curfew_utc_time="23:30",
    )
    stage = create_stage(
        edition["id"],
        name="Grandstand",
        changeover_buffer_minutes=120,
        slot_soft_cap=4,
    )
    agent = create_agent()
    incumbent_artist = create_artist(
        agent["id"],
        name="Dust Road Revival",
        genre="COUNTRY",
        audience_segment="FAMILY",
        base_draw_score=62.50,
    )
    candidate_artist = create_artist(
        agent["id"],
        name="Nine Volt Sermon",
        genre="ROCK",
        audience_segment="YOUNG_ADULT",
        base_draw_score=55.00,
    )
    incumbent = create_offer(
        edition["id"],
        incumbent_artist["id"],
        stage["id"],
        offered_guarantee_cents=INCUMBENT_GUARANTEE_CENTS,
        backend_split_pct=0.8500,
        backend_breakeven_cents=6_000_000,
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-22T14:00:00.000Z",
        load_out_end_utc="2026-08-22T23:00:00.000Z",
    )
    validate_success(_send(incumbent["id"]))
    gap_of_ninety_minutes = create_offer(
        edition["id"],
        candidate_artist["id"],
        stage["id"],
        offered_guarantee_cents=CANDIDATE_GUARANTEE_CENTS,
        backend_split_pct=0.8000,
        backend_breakeven_cents=3_000_000,
        target_show_date="2026-08-23",
        load_in_start_utc="2026-08-23T00:30:00.000Z",
        load_out_end_utc="2026-08-23T05:00:00.000Z",
    )
    gap_of_the_full_buffer = create_offer(
        edition["id"],
        candidate_artist["id"],
        stage["id"],
        offered_guarantee_cents=CANDIDATE_GUARANTEE_CENTS,
        backend_split_pct=0.8000,
        backend_breakeven_cents=3_000_000,
        target_show_date="2026-08-23",
        load_in_start_utc="2026-08-23T01:00:00.000Z",
        load_out_end_utc="2026-08-23T06:00:00.000Z",
    )
    return {
        "edition": edition,
        "stage": stage,
        "gap_of_ninety_minutes": gap_of_ninety_minutes,
        "gap_of_the_full_buffer": gap_of_the_full_buffer,
    }


class TestBufferedStageOccupationAtMinuteGranularity:
    """The forbidden zone is the standing occupation grown by the changeover
    buffer at each end, compared strictly, so a gap of exactly the buffer lands.
    """

    def test_send_leaving_only_ninety_minutes_of_changeover_is_refused(self):
        """A load-in at 00:30 leaves only ninety of the hundred and twenty minutes
        of changeover the grandstand demands after the standing hold clears at
        23:00, so the two occupations collide and the offer keeps its draft state
        while the stage keeps its single hold.

        "Because each comparison is strict, a gap of exactly `changeover_buffer_minutes` between two occupations is permitted; anything less is not."

        Design: Difficulty/resource_temporal_overlap/stage_buffered_minute_overlap_gap_exactly_at_buffer
        """
        world = _world_at_the_changeover_buffer_boundary()

        response = _send(world["gap_of_ninety_minutes"]["id"])

        validate_error(response, ApiErrorId.ERR_STAGE_SLOT_CONFLICT.value)
        assert get_offer(world["gap_of_ninety_minutes"]["id"])["status"] == "DRAFT"
        assert get_stage(world["stage"]["id"])["held_show_count"] == 1

    def test_send_leaving_exactly_the_changeover_buffer_is_admitted(self):
        """A load-in at 01:00 sits exactly one hundred and twenty minutes after
        the standing hold clears, which the strict comparison admits, so the send
        lands: the grandstand now counts two holds and the edition's encumbrance
        carries both guarantees.

        "Comparisons are made at minute granularity, and a collision is refused with `ERR_STAGE_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stage_buffered_minute_overlap_gap_exactly_at_buffer
        """
        world = _world_at_the_changeover_buffer_boundary()

        offer = validate_success(_send(world["gap_of_the_full_buffer"]["id"]))

        assert offer["status"] == "SENT"
        assert get_stage(world["stage"]["id"])["held_show_count"] == 2
        edition = get_edition(world["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 13000000


# ---------------------------------------------------------------------------
# The fair-wide per-day ceiling, counted across every stage
# ---------------------------------------------------------------------------
def _world_with_a_full_show_day_across_three_stages():
    """An edition permitting two shows a day over three stages, with 2026-08-24
    already carrying a COUNTRY hold on the grandstand and a ROCK hold in the
    pavilion, plus two drafted offers for a COMEDY act on the empty beer garden
    stage: one on that full day and one on an empty day.
    """
    set_clock(CANONICAL_CLOCK_UTC)
    edition = create_edition(
        name="Day Capacity Fair",
        talent_budget_cap_cents=40_000_000,
        refund_reserve_cents=15_000_000,
        max_shows_per_day=2,
        curfew_utc_time="23:30",
    )
    grandstand = create_stage(
        edition["id"],
        name="Grandstand",
        reserved_seat_capacity=4000,
        ga_capacity=6000,
        changeover_buffer_minutes=120,
        slot_soft_cap=4,
    )
    pavilion = create_stage(
        edition["id"],
        name="Pavilion",
        reserved_seat_capacity=500,
        ga_capacity=500,
        changeover_buffer_minutes=60,
        slot_soft_cap=4,
    )
    beer_garden = create_stage(
        edition["id"],
        name="Beer Garden Stage",
        reserved_seat_capacity=0,
        ga_capacity=800,
        changeover_buffer_minutes=30,
        slot_soft_cap=4,
    )
    agent = create_agent()
    country_artist = create_artist(
        agent["id"],
        name="Dust Road Revival",
        genre="COUNTRY",
        audience_segment="FAMILY",
        base_draw_score=62.50,
    )
    rock_artist = create_artist(
        agent["id"],
        name="Nine Volt Sermon",
        genre="ROCK",
        audience_segment="YOUNG_ADULT",
        base_draw_score=55.00,
    )
    third_artist = create_artist(
        agent["id"],
        name="Marsh Street Quartet",
        genre="COMEDY",
        audience_segment="ADULT_45_PLUS",
        base_draw_score=40.00,
    )
    first_hold = create_offer(
        edition["id"],
        country_artist["id"],
        grandstand["id"],
        offered_guarantee_cents=INCUMBENT_GUARANTEE_CENTS,
        backend_split_pct=0.8500,
        backend_breakeven_cents=6_000_000,
        target_show_date="2026-08-24",
        load_in_start_utc="2026-08-24T14:00:00.000Z",
        load_out_end_utc="2026-08-24T23:00:00.000Z",
    )
    validate_success(_send(first_hold["id"]))
    second_hold = create_offer(
        edition["id"],
        rock_artist["id"],
        pavilion["id"],
        offered_guarantee_cents=CANDIDATE_GUARANTEE_CENTS,
        backend_split_pct=0.8000,
        backend_breakeven_cents=3_000_000,
        target_show_date="2026-08-24",
        load_in_start_utc="2026-08-24T15:00:00.000Z",
        load_out_end_utc="2026-08-24T22:00:00.000Z",
    )
    validate_success(_send(second_hold["id"]))
    third_show_same_day = create_offer(
        edition["id"],
        third_artist["id"],
        beer_garden["id"],
        offered_guarantee_cents=2_000_000,
        backend_split_pct=0.7500,
        backend_breakeven_cents=1_000_000,
        radius_miles=50,
        radius_days_before=1,
        radius_days_after=1,
        target_show_date="2026-08-24",
        load_in_start_utc="2026-08-24T16:00:00.000Z",
        load_out_end_utc="2026-08-24T21:00:00.000Z",
    )
    same_show_on_an_empty_day = create_offer(
        edition["id"],
        third_artist["id"],
        beer_garden["id"],
        offered_guarantee_cents=2_000_000,
        backend_split_pct=0.7500,
        backend_breakeven_cents=1_000_000,
        radius_miles=50,
        radius_days_before=1,
        radius_days_after=1,
        target_show_date="2026-08-26",
        load_in_start_utc="2026-08-26T16:00:00.000Z",
        load_out_end_utc="2026-08-26T21:00:00.000Z",
    )
    return {
        "edition": edition,
        "beer_garden": beer_garden,
        "third_show_same_day": third_show_same_day,
        "same_show_on_an_empty_day": same_show_on_an_empty_day,
    }


class TestPerDayCapacityIsCountedAcrossTheWholeFair:
    """The per-day ceiling counts a calendar day's holds across every stage of the
    edition, so a show alone on its own stage can still be one show too many.
    """

    def test_third_show_of_the_day_on_an_empty_stage_is_refused(self):
        """The beer garden stage carries no hold at all and the candidate's own
        occupation touches nobody else's, yet 2026-08-24 already carries two holds
        across the other two stages, so the collective count of three breaches the
        edition's ceiling of two shows a day.

        "Each show may be individually schedulable on its own stage and the rule can still trip, because only the collective per-day count matters"

        Design: Difficulty/resource_temporal_overlap/edition_day_aggregate_capacity_across_stages
        """
        world = _world_with_a_full_show_day_across_three_stages()

        response = _send(world["third_show_same_day"]["id"])

        validate_error(response, ApiErrorId.ERR_DAY_SLOT_CAPACITY_EXCEEDED.value)
        assert get_offer(world["third_show_same_day"]["id"])["status"] == "DRAFT"
        assert get_stage(world["beer_garden"]["id"])["held_show_count"] == 0

    def test_same_show_moved_to_an_empty_day_is_admitted(self):
        """The identical act, stage and occupation times moved to 2026-08-26, a
        date whose bucket is empty, clear the per-day ceiling, so the send lands:
        the beer garden stage takes its first hold and the edition's encumbrance
        carries all three guarantees.

        "Counting holds and bookings on the candidate performance date across every stage of the edition, that count must remain at or below the edition's `max_shows_per_day`."

        Design: Difficulty/resource_temporal_overlap/edition_day_aggregate_capacity_across_stages
        """
        world = _world_with_a_full_show_day_across_three_stages()

        offer = validate_success(_send(world["same_show_on_an_empty_day"]["id"]))

        assert offer["status"] == "SENT"
        assert get_stage(world["beer_garden"]["id"])["held_show_count"] == 1
        edition = get_edition(world["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 15000000
