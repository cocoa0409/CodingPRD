"""Formulas whose answer depends on composing several rules in a fixed order.

Marginal giving bands feeding a loyalty multiplier, a reseating invoice that
rounds each seat share before summing, and a handling-fee band keyed on the
pre-fee figure are all arithmetic where a plausible shortcut gives a
different, wrong number.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_donor_points,
    assert_ledger_component,
)
from test_helpers.constants import (
    ENTRY_CUMULATIVE_GIVING,
    ENTRY_SEASON_TICKET_TENURE,
    EVENT_CLOSED,
    EVENT_POSTSEASON,
    FACULTY_STAFF,
    NON_ALUMNUS,
    OCCUPANCY_HELD,
    PAYMENT_INVOICED,
    PRICING_MARKET,
    RENOVATION_RESEATING,
    SECTION_UNDER_RENOVATION,
    VARIANT_CERTIFIED,
)
from test_helpers.fixtures import (
    add_received_gift,
    certified_cycle,
    create_section_with_seats,
    gate_event,
    ledger_entries,
    open_cycle,
    pick_through_event,
    publish_and_open,
    read_assignment,
    read_donor,
    read_event,
    register_donor,
    renew_season,
    reprice_renovation,
    run_cycle,
    seated_donor,
    set_clock,
    start_reseating,
    survey_section,
)


def _tiered_giving_scenario(client):
    """A five-year giver with tenure beside a single-year giver of the same total."""
    set_clock(client, f.instant(2026, 4, 1))
    steady = register_donor(client, alumni_status=FACULTY_STAFF)
    for year in (2022, 2023, 2024, 2025, 2026):
        add_received_gift(client, steady["id"], 3000000, f.instant(year, 3, 1))
    for year in (2024, 2025, 2026):
        renew_season(client, steady["id"], year)

    newcomer = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, newcomer["id"], 15000000, f.instant(2026, 3, 1))

    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])
    return steady, newcomer, cycle


class TestTieredGivingWithLoyaltyMultiplier:
    """Identical giving totals score differently once loyalty and tenure join."""

    def test_marginal_bands_and_loyalty_multiplier_compose(self, client):
        """The 1.10 uplift is applied to the already-rounded giving component.

        PRD 3.3: "The multiplier is applied to the **already-rounded** giving
        component, not to the raw band products, and the product is itself
        rounded half up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/priority_point_score_tiered_loyalty_nonlinear
        """
        steady, _newcomer, _cycle = _tiered_giving_scenario(client)

        scored = read_donor(client, steady["id"])
        assert_donor_points(
            scored,
            certified_base_points="310.25",
            certified_points="310.25",
            cumulative_giving_cents=15000000,
            consecutive_giving_years=5,
        )
        assert scored["season_ticket_seasons_purchased"] == 3

        entries = ledger_entries(client, donor_id=steady["id"])
        assert_ledger_component(
            entries, ENTRY_CUMULATIVE_GIVING, VARIANT_CERTIFIED, "261.25"
        )

    def test_the_same_total_without_a_streak_earns_no_uplift(self, client):
        """One year of giving reaches the same bands but not the multiplier.

        PRD 3.3: "When the donor's consecutive-giving streak is at least 5
        years, the giving component is multiplied by 1.10; otherwise it is
        multiplied by 1.00."

        Design: Difficulty/combinatorial_formula/priority_point_score_tiered_loyalty_nonlinear
        """
        _steady, newcomer, _cycle = _tiered_giving_scenario(client)

        scored = read_donor(client, newcomer["id"])
        assert_donor_points(
            scored,
            certified_base_points="242.50",
            cumulative_giving_cents=15000000,
            consecutive_giving_years=1,
        )

        entries = ledger_entries(client, donor_id=newcomer["id"])
        assert_ledger_component(
            entries, ENTRY_CUMULATIVE_GIVING, VARIANT_CERTIFIED, "237.50"
        )

    def test_tenure_contributes_three_points_per_recorded_season(self, client):
        """Three distinct renewal years become a nine-point tenure component.

        PRD 3.3: "Fourth, the **season-ticket tenure component**: the donor's
        `season_ticket_seasons_purchased`, or 30 if that count exceeds 30,
        multiplied by 3 points per season."

        Design: Difficulty/combinatorial_formula/priority_point_score_tiered_loyalty_nonlinear
        """
        steady, newcomer, _cycle = _tiered_giving_scenario(client)

        steady_entries = ledger_entries(client, donor_id=steady["id"])
        assert_ledger_component(
            steady_entries, ENTRY_SEASON_TICKET_TENURE, VARIANT_CERTIFIED, "9.00"
        )

        newcomer_entries = ledger_entries(client, donor_id=newcomer["id"])
        assert_ledger_component(
            newcomer_entries, ENTRY_SEASON_TICKET_TENURE, VARIANT_CERTIFIED, "0.00"
        )
        assert read_donor(client, newcomer["id"])["season_ticket_seasons_purchased"] == 0


def _reseating_scenario(client):
    """Three held seats in a section that is then reseated at the same rate."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("C", 1), ("C", 2), ("C", 3)],
        seat_capacity=3,
        per_seat_requirement_cents=250000,
        required_points_per_seat=0.00,
    )
    donors = [register_donor(client, alumni_status=NON_ALUMNUS) for _ in range(3)]

    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 8), 2880
    )

    assignments = []
    for index, (donor, seat) in enumerate(zip(donors, seats)):
        set_clock(client, f.instant(2026, 9, 1 + 2 * index, 12))
        assignments.append(
            pick_through_event(client, event["id"], seat["id"], donor["id"])
        )

    survey_section(client, section["id"])
    reprice_renovation(client, section["id"], 3, 250000)
    reseated = start_reseating(client, section["id"], cycle["id"])
    return reseated, assignments


class TestReseatingInvoiceRoundsPerSeat:
    """Seven twelfths of the new rate, rounded per seat then summed."""

    def test_each_seat_share_is_rounded_before_it_joins_the_total(self, client):
        """Three shares of 145,833 make 437,499, not 437,500.

        PRD 3.7: "Summing the unrounded shares and rounding once at the end
        produces a different figure and is wrong."

        Design: Difficulty/combinatorial_formula/reseating_invoice_rounds_per_seat_before_sum
        """
        section, _assignments = _reseating_scenario(client)

        assert section["renovation_status"] == RENOVATION_RESEATING
        assert section["reseated_donor_count"] == 3
        assert_cents(
            section["reseating_invoice_total_cents"],
            437499,
            "reseating_invoice_total_cents",
        )

    def test_every_reseated_row_carries_the_prorated_requirement(self, client):
        """The rounded per-seat share is written back onto each row.

        PRD 3.7: "visiting those assignments in `created_at` ascending order,
        each row's `requirement_cents` is multiplied by 7, divided by 12, and
        rounded half up to whole cents; that rounded per-seat share is written
        back as the row's new `requirement_cents` and added to a running
        total."

        Design: Difficulty/combinatorial_formula/reseating_invoice_rounds_per_seat_before_sum
        """
        _section, assignments = _reseating_scenario(client)

        for assignment in assignments:
            row = read_assignment(client, assignment["id"])
            assert_cents(row["requirement_cents"], 145833, "requirement_cents")
            assert_cents(row["total_due_cents"], 145833, "total_due_cents")

    def test_the_cascade_invoices_every_row_it_touched(self, client):
        """Payment moves to INVOICED while occupancy is left alone.

        PRD 3.7: "Every row the cascade touched has its `payment_status` moved
        to `INVOICED`, and this includes rows that had already been paid: an
        assignment in `payment_status` `PAID` whose `requirement_cents` changed
        during the cascade is dragged backwards `PAID → INVOICED`, with
        `total_due_cents` raised to the reseating amount while
        `amount_paid_cents` keeps the prior payment, so the outstanding balance
        is visible."

        Design: Difficulty/combinatorial_formula/reseating_invoice_rounds_per_seat_before_sum
        """
        _section, assignments = _reseating_scenario(client)

        for assignment in assignments:
            row = read_assignment(client, assignment["id"])
            assert row["payment_status"] == PAYMENT_INVOICED
            assert row["occupancy_status"] == OCCUPANCY_HELD

    def test_the_section_stays_closed_to_picks_while_reseating(self, client):
        """The renovation axis rests in RESEATING and status is UNDER_RENOVATION.

        PRD 3.7: "**`SURVEY`** moves `NONE → SURVEYED` and requires
        `renovation_status` to be `NONE` and `status` to be `OPEN`. Its side
        effect is to set `status` to `UNDER_RENOVATION`, which blocks every
        pick into this section for the duration."

        Design: Difficulty/combinatorial_formula/reseating_invoice_rounds_per_seat_before_sum
        """
        section, _assignments = _reseating_scenario(client)

        assert section["status"] == SECTION_UNDER_RENOVATION
        assert section["renovation_status"] == RENOVATION_RESEATING
        assert section["reseating_recalculation_id"] is not None


def _postseason_fee_scenario(client):
    """One donor who already holds a confirmed seat, then picks in a postseason."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("D", 1), ("D", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=49000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)

    season_event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    set_clock(client, f.instant(2026, 9, 1, 12))
    season_row = seated_donor(client, season_event["id"], seats[0]["id"], donor["id"])
    gate_event(client, season_event["id"], EVENT_CLOSED)

    postseason_event = publish_and_open(
        client,
        cycle["id"],
        f.instant(2026, 9, 10),
        f.instant(2026, 9, 14),
        2880,
        event_type=EVENT_POSTSEASON,
    )
    set_clock(client, f.instant(2026, 9, 10, 12))
    postseason_row = pick_through_event(
        client, postseason_event["id"], seats[1]["id"], donor["id"]
    )
    return season_row, postseason_row, postseason_event


class TestPostseasonHandlingFeeBand:
    """The band is chosen on the pre-fee figure, never on the total."""

    def test_the_lowest_band_rate_applies_to_a_sub_five_hundred_dollar_seat(
        self, client
    ):
        """A 49,000-cent requirement takes the 6% band, giving a 2,940-cent fee.

        PRD 3.8: "For a `POSTSEASON` or `AWAY_GAME` event, a handling rate is
        selected by band on `requirement_cents` — and the band is keyed on
        `requirement_cents` alone, never on the fee-inclusive total: below $500
        (50,000 cents) the rate is 6%, at or above $500 but below $2,500
        (250,000 cents) the rate is 4%, and at or above $2,500 the rate is 2%."

        Design: Difficulty/combinatorial_formula/postseason_handling_fee_tier_keyed_on_base_total
        """
        _season_row, postseason_row, _event = _postseason_fee_scenario(client)

        assert postseason_row["pricing_mode"] == PRICING_MARKET
        assert_cents(postseason_row["requirement_cents"], 49000, "requirement_cents")
        assert_cents(postseason_row["handling_fee_cents"], 2940, "handling_fee_cents")
        assert_cents(postseason_row["total_due_cents"], 51940, "total_due_cents")

    def test_the_season_ticket_row_beside_it_carries_no_fee(self, client):
        """The same donor, same section, same rate - and no handling fee.

        PRD 3.8: "The second step is the handling fee, which exists only for
        the two out-of-season allocations."

        Design: Difficulty/combinatorial_formula/postseason_handling_fee_tier_keyed_on_base_total
        """
        season_row, _postseason_row, _event = _postseason_fee_scenario(client)

        assert_cents(season_row["requirement_cents"], 49000, "requirement_cents")
        assert_cents(season_row["handling_fee_cents"], 0, "handling_fee_cents")
        assert_cents(season_row["total_due_cents"], 49000, "total_due_cents")

    def test_the_postseason_pool_admits_only_confirmed_seat_holders(self, client):
        """One donor holds an ASSIGNED seat, so exactly one slot is published.

        PRD 3.5: "The candidate pool for a selection event admits a donor when
        the donor's `donor_status` is `ACTIVE` or `LAPSED`, when their
        `certified_points` is at least the event's `eligible_donor_min_points`,
        and — for a `POSTSEASON` or `AWAY_GAME` event — when the donor holds at
        least one seat assignment whose `occupancy_status` is `ASSIGNED`."

        Design: Difficulty/combinatorial_formula/postseason_handling_fee_tier_keyed_on_base_total
        """
        _season_row, _postseason_row, event = _postseason_fee_scenario(client)

        published = read_event(client, event["id"])
        assert published["published_slot_count"] == 1
        assert published["event_type"] == EVENT_POSTSEASON
