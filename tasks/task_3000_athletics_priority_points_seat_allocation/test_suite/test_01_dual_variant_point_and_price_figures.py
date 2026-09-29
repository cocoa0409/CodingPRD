"""The two places where one set of facts yields two different figures.

The recalculation writes a PROVISIONAL and a CERTIFIED score from the same
gifts, and a pick prices a seat either at the market rate or at a
grandfathered renewal rate.  Both divergences are exercised here.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_donor_points,
    assert_ledger_component,
    validate_success,
)
from test_helpers.constants import (
    ALUMNUS,
    ENTRY_ALUMNI_STATUS,
    ENTRY_CONSECUTIVE_YEARS,
    ENTRY_CUMULATIVE_GIVING,
    EVENT_CLOSED,
    GIFT_RECEIVED,
    INDIVIDUAL,
    NON_ALUMNUS,
    PRICING_MARKET,
    PRICING_RENEWAL,
    RECALC_COMPUTED,
    VARIANT_CERTIFIED,
    VARIANT_PROVISIONAL,
)
from test_helpers.fixtures import (
    add_gift,
    add_received_gift,
    certified_cycle,
    communicate_cycle,
    create_section_with_seats,
    gate_event,
    ledger_entries,
    open_cycle,
    pick_through_event,
    publish_and_open,
    read_cycle,
    read_donor,
    register_donor,
    reprice_section,
    run_cycle,
    seated_donor,
    set_clock,
)
from test_helpers.test_users import OFFICER


def _pledge_and_gift_scenario(client):
    """One donor with a settled 2026 gift and an unsettled 2026 pledge."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=ALUMNUS, entity_type=INDIVIDUAL)
    add_received_gift(client, donor["id"], 4500000, f.instant(2026, 3, 1))
    pledge = add_gift(client, donor["id"], 500000, f.instant(2026, 4, 1))
    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])
    return donor, pledge, cycle


class TestProvisionalAndCertifiedDiverge:
    """One gift set, two annual figures."""

    def test_unsettled_pledge_lifts_only_the_provisional_figure(self, client):
        """The pledge raises PROVISIONAL while CERTIFIED stays on settled money.

        PRD 3.4: "The consequence is deliberate and worth stating plainly:
        whenever a donor has any qualifying pledge still unsettled, the same
        underlying data yields a strictly lower CERTIFIED score than
        PROVISIONAL score, and the donor is told the higher number first."

        Design: Difficulty/dual_variant_calc/provisional_vs_certified_points_diverge_on_pledged_gift
        """
        donor, _pledge, _cycle = _pledge_and_gift_scenario(client)

        scored = read_donor(client, donor["id"])
        assert_donor_points(
            scored,
            provisional_points="92.50",
            certified_base_points="85.00",
            certified_points="85.00",
            cumulative_giving_cents=4500000,
            consecutive_giving_years=1,
        )

    def test_only_settled_money_reaches_cumulative_giving(self, client):
        """cumulative_giving_cents follows the CERTIFIED input set alone.

        PRD 3.3: "Every donor's `cumulative_giving_cents` and
        `consecutive_giving_years` are refreshed by the run to the values the
        CERTIFIED input set produced, so those two stored fields always
        describe the last completed run."

        Design: Difficulty/dual_variant_calc/provisional_vs_certified_points_diverge_on_pledged_gift
        """
        donor, _pledge, cycle = _pledge_and_gift_scenario(client)

        scored = read_donor(client, donor["id"])
        assert_cents(
            scored["cumulative_giving_cents"], 4500000, "cumulative_giving_cents"
        )

        computed = read_cycle(client, cycle["id"])
        assert computed["status"] == RECALC_COMPUTED
        assert computed["donors_processed_count"] == 1

    def test_the_giving_component_is_ledgered_once_per_variant(self, client):
        """Each variant contributes its own tiered-giving row.

        PRD 3.3: "Because a run writes both variants, it appends **two
        generations of ledger rows per donor**: one row per formula component
        per variant."

        Design: Difficulty/dual_variant_calc/provisional_vs_certified_points_diverge_on_pledged_gift
        """
        donor, _pledge, _cycle = _pledge_and_gift_scenario(client)

        entries = ledger_entries(client, donor_id=donor["id"])
        assert_ledger_component(
            entries, ENTRY_CUMULATIVE_GIVING, VARIANT_PROVISIONAL, "62.50"
        )
        assert_ledger_component(
            entries, ENTRY_CUMULATIVE_GIVING, VARIANT_CERTIFIED, "55.00"
        )
        assert_ledger_component(
            entries, ENTRY_ALUMNI_STATUS, VARIANT_CERTIFIED, "25.00"
        )
        assert_ledger_component(
            entries, ENTRY_CONSECUTIVE_YEARS, VARIANT_CERTIFIED, "5.00"
        )

    def test_settling_the_pledge_closes_the_gap_on_a_re_run(self, client):
        """Once the pledge is RECEIVED the two variants agree.

        PRD 3.2: "Settling `PLEDGED → RECEIVED` requires the gift to be
        `PLEDGED`; it stamps `settled_at` with the current logical clock
        instant, adds `amount_cents` to the donor's `cumulative_giving_cents`,
        sets `counts_toward_points` to true when `designation` is
        `ATHLETICS_ANNUAL` or `CAPITAL`, makes the gift eligible for the
        CERTIFIED point variant in addition to the PROVISIONAL one, and
        advances both the gift's `version` and the donor's `version` by 1."

        Design: Difficulty/dual_variant_calc/provisional_vs_certified_points_diverge_on_pledged_gift
        """
        donor, pledge, cycle = _pledge_and_gift_scenario(client)

        settled = validate_success(
            client.settle_gift(
                pledge["id"], f.settle_gift_payload(GIFT_RECEIVED), headers=OFFICER
            )
        )
        assert settled["gift_status"] == GIFT_RECEIVED

        communicate_cycle(client, cycle["id"])
        run_cycle(client, cycle["id"])

        rescored = read_donor(client, donor["id"])
        assert_donor_points(
            rescored,
            provisional_points="92.50",
            certified_base_points="92.50",
            certified_points="92.50",
            cumulative_giving_cents=5000000,
        )


def _renewal_after_reprice_scenario(client):
    """A 2020 occupant and a 2026 newcomer picking in the same repriced section.

    The section is opened while the clock reads 2020 so that its opening
    requirement lands in `requirement_history` against cycle year 2020, which
    is the entry the renewal price is grandfathered from six years later.
    """
    set_clock(client, f.instant(2020, 1, 15))
    section, seats = create_section_with_seats(
        client,
        [("B", 1), ("B", 2), ("B", 3)],
        seat_capacity=3,
        per_seat_requirement_cents=250000,
        required_points_per_seat=0.00,
    )
    dana = register_donor(client, alumni_status=NON_ALUMNUS)

    cycle_2020 = certified_cycle(client, 2020)
    event_2020 = publish_and_open(
        client,
        cycle_2020["id"],
        f.instant(2020, 9, 1),
        f.instant(2020, 9, 5),
        2880,
    )
    set_clock(client, f.instant(2020, 9, 1, 12))
    seated_donor(client, event_2020["id"], seats[0]["id"], dana["id"])
    closed = gate_event(client, event_2020["id"], EVENT_CLOSED)
    assert closed["status"] == EVENT_CLOSED

    set_clock(client, f.instant(2026, 1, 15))
    blake = register_donor(client, alumni_status=NON_ALUMNUS)
    reprice_section(client, section["id"], 400000, 2026)

    cycle_2026 = certified_cycle(client, 2026)
    event_2026 = publish_and_open(
        client,
        cycle_2026["id"],
        f.instant(2026, 9, 1),
        f.instant(2026, 9, 10),
        2880,
    )

    set_clock(client, f.instant(2026, 9, 1, 12))
    renewal_row = pick_through_event(
        client, event_2026["id"], seats[1]["id"], dana["id"]
    )
    set_clock(client, f.instant(2026, 9, 3, 12))
    market_row = pick_through_event(
        client, event_2026["id"], seats[2]["id"], blake["id"]
    )
    return section, renewal_row, market_row


class TestRenewalAndMarketSeatRequirementsDiverge:
    """The same section charges two different prices in the same event."""

    def test_returning_occupant_is_priced_on_the_grandfathered_rate(self, client):
        """Six years of 1.03 escalation on the 2020 rate, capped at 85% of market.

        PRD 3.8: "Under `RENEWAL` pricing, let the years held be the cycle year
        of the recalculation that owns the event — or, during a reseating, the
        cycle year of the reseating recalculation — minus
        `first_occupied_cycle_year`."

        Design: Difficulty/dual_variant_calc/renewal_vs_market_seat_requirement_diverge_after_reprice
        """
        _section, renewal_row, _market_row = _renewal_after_reprice_scenario(client)

        assert renewal_row["pricing_mode"] == PRICING_RENEWAL
        assert renewal_row["first_occupied_cycle_year"] == 2020
        assert_cents(
            renewal_row["grandfathered_requirement_cents"],
            250000,
            "grandfathered_requirement_cents",
        )
        assert_cents(renewal_row["requirement_cents"], 298513, "requirement_cents")

    def test_first_time_occupant_pays_the_full_market_rate(self, client):
        """A newcomer in the same section is priced at the repriced rate.

        PRD 3.8: "Under `MARKET` pricing, `requirement_cents` is simply the
        section's current `per_seat_requirement_cents`, with no escalator and
        no ceiling."

        Design: Difficulty/dual_variant_calc/renewal_vs_market_seat_requirement_diverge_after_reprice
        """
        _section, _renewal_row, market_row = _renewal_after_reprice_scenario(client)

        assert market_row["pricing_mode"] == PRICING_MARKET
        assert market_row["first_occupied_cycle_year"] == 2026
        assert_cents(market_row["requirement_cents"], 400000, "requirement_cents")

    def test_a_season_ticket_event_adds_no_handling_fee_to_either_row(self, client):
        """Both rows owe exactly their requirement and nothing more.

        PRD 3.8: "For a `SEASON_TICKET` event, `handling_fee_cents` is 0 and
        `total_due_cents` equals `requirement_cents`."

        Design: Difficulty/dual_variant_calc/renewal_vs_market_seat_requirement_diverge_after_reprice
        """
        _section, renewal_row, market_row = _renewal_after_reprice_scenario(client)

        assert_cents(renewal_row["handling_fee_cents"], 0, "renewal handling_fee_cents")
        assert_cents(renewal_row["total_due_cents"], 298513, "renewal total_due_cents")
        assert_cents(market_row["handling_fee_cents"], 0, "market handling_fee_cents")
        assert_cents(market_row["total_due_cents"], 400000, "market total_due_cents")

    def test_the_renewal_price_is_strictly_below_the_market_price(self, client):
        """The repriced section charges the renewing donor materially less.

        PRD 3.8: "The practical effect is that a section which has just been
        repriced upward charges a renewing donor materially less than a
        brand-new donor, and never more than 85% of the current market rate."

        Design: Difficulty/dual_variant_calc/renewal_vs_market_seat_requirement_diverge_after_reprice
        """
        _section, renewal_row, market_row = _renewal_after_reprice_scenario(client)

        assert renewal_row["requirement_cents"] < market_row["requirement_cents"]
        assert renewal_row["requirement_cents"] <= int(
            round(market_row["requirement_cents"] * 0.85)
        )
