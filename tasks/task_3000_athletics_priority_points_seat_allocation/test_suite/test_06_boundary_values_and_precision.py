"""Thresholds evaluated at exactly the boundary and one step away from it.

A five-year streak is the first that earns the loyalty multiplier, and an
eligibility floor is inclusive - a donor sitting exactly on it is admitted
while a floor one hundredth of a point higher excludes them.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_NO_ELIGIBLE_DONORS
from test_helpers.assertions import (
    assert_donor_points,
    assert_ledger_component,
    assert_page_meta,
    validate_error,
    validate_list,
)
from test_helpers.constants import (
    ENTRY_CONSECUTIVE_YEARS,
    ENTRY_CUMULATIVE_GIVING,
    EVENT_DRAFT,
    EVENT_SLOTS_PUBLISHED,
    NON_ALUMNUS,
    SLOT_SCHEDULED,
    VARIANT_CERTIFIED,
)
from test_helpers.fixtures import (
    add_received_gift,
    certified_cycle,
    create_event,
    ledger_entries,
    list_event_slots,
    open_cycle,
    publish_slots,
    read_donor,
    read_event,
    register_donor,
    run_cycle,
    set_clock,
)
from test_helpers.test_users import OFFICER


def _five_versus_four_year_streaks(client):
    """Two donors with identical giving totals and streaks of 5 and 4."""
    set_clock(client, f.instant(2026, 4, 1))
    loyal_five = register_donor(client, alumni_status=NON_ALUMNUS)
    for gift_date in (
        f.instant(2022, 5, 1),
        f.instant(2023, 5, 1),
        f.instant(2024, 5, 1),
        f.instant(2025, 5, 1),
        f.instant(2026, 3, 1),
    ):
        add_received_gift(client, loyal_five["id"], 1000000, gift_date)

    loyal_four = register_donor(client, alumni_status=NON_ALUMNUS)
    for gift_date in (
        f.instant(2023, 4, 1),
        f.instant(2023, 9, 1),
        f.instant(2024, 5, 1),
        f.instant(2025, 5, 1),
        f.instant(2026, 3, 1),
    ):
        add_received_gift(client, loyal_four["id"], 1000000, gift_date)

    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])
    return loyal_five, loyal_four


class TestLoyaltyMultiplierAtFiveConsecutiveYears:
    """Five years earns the uplift; four does not."""

    def test_a_streak_of_exactly_five_earns_the_uplift(self, client):
        """The threshold is "at least 5 years", so five qualifies.

        PRD 3.3: "When the donor's consecutive-giving streak is at least 5
        years, the giving component is multiplied by 1.10; otherwise it is
        multiplied by 1.00."

        Design: Difficulty/boundary_precision_check/loyalty_multiplier_at_exactly_five_consecutive_years
        """
        loyal_five, _loyal_four = _five_versus_four_year_streaks(client)

        scored = read_donor(client, loyal_five["id"])
        assert_donor_points(
            scored,
            cumulative_giving_cents=5000000,
            consecutive_giving_years=5,
            certified_points="93.75",
        )

    def test_a_streak_of_four_earns_none_on_identical_giving(self, client):
        """A single missing year costs the multiplier and one streak year.

        PRD 3.3: "A donor whose most recent qualifying gift is two years old
        therefore has a streak of zero, because the single grace step is not
        enough to reach it."

        Design: Difficulty/boundary_precision_check/loyalty_multiplier_at_exactly_five_consecutive_years
        """
        _loyal_five, loyal_four = _five_versus_four_year_streaks(client)

        scored = read_donor(client, loyal_four["id"])
        assert_donor_points(
            scored,
            cumulative_giving_cents=5000000,
            consecutive_giving_years=4,
            certified_points="82.50",
        )

    def test_the_giving_rows_differ_only_by_the_multiplier(self, client):
        """62.50 uplifted to 68.75 against a flat 62.50.

        PRD 3.3: "The multiplier is applied to the **already-rounded** giving
        component, not to the raw band products, and the product is itself
        rounded half up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/loyalty_multiplier_at_exactly_five_consecutive_years
        """
        loyal_five, loyal_four = _five_versus_four_year_streaks(client)

        assert_ledger_component(
            ledger_entries(client, donor_id=loyal_five["id"]),
            ENTRY_CUMULATIVE_GIVING,
            VARIANT_CERTIFIED,
            "68.75",
        )
        assert_ledger_component(
            ledger_entries(client, donor_id=loyal_four["id"]),
            ENTRY_CUMULATIVE_GIVING,
            VARIANT_CERTIFIED,
            "62.50",
        )

    def test_the_consecutive_year_rows_price_each_streak_at_five_points(self, client):
        """Five points per year, so 25.00 against 20.00.

        PRD 3.3: "Third, the **consecutive-year component**: the donor's
        consecutive-giving streak, or 20 if the streak exceeds 20, multiplied by
        5 points per year."

        Design: Difficulty/boundary_precision_check/loyalty_multiplier_at_exactly_five_consecutive_years
        """
        loyal_five, loyal_four = _five_versus_four_year_streaks(client)

        assert_ledger_component(
            ledger_entries(client, donor_id=loyal_five["id"]),
            ENTRY_CONSECUTIVE_YEARS,
            VARIANT_CERTIFIED,
            "25.00",
        )
        assert_ledger_component(
            ledger_entries(client, donor_id=loyal_four["id"]),
            ENTRY_CONSECUTIVE_YEARS,
            VARIANT_CERTIFIED,
            "20.00",
        )


def _floor_at_and_above_the_only_donor(client):
    """One certified 90.00-point donor, one event at 90.00 and one at 90.01."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 6500000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)

    event_in = create_event(
        client,
        cycle["id"],
        f.instant(2026, 9, 1),
        f.instant(2026, 9, 5),
        2880,
        eligible_donor_min_points=90.00,
    )
    event_out = create_event(
        client,
        cycle["id"],
        f.instant(2026, 9, 10),
        f.instant(2026, 9, 14),
        2880,
        eligible_donor_min_points=90.01,
    )
    return donor, event_in, event_out


class TestEligiblePoolFloorIsInclusive:
    """The floor admits an exact match and excludes one hundredth above it."""

    def test_a_donor_exactly_on_the_floor_is_admitted(self, client):
        """An "at least" floor is inclusive, so 90.00 clears 90.00.

        PRD 3.5: "The candidate pool for a selection event admits a donor when
        the donor's `donor_status` is `ACTIVE` or `LAPSED`, when their
        `certified_points` is at least the event's `eligible_donor_min_points`,
        and — for a `POSTSEASON` or `AWAY_GAME` event — when the donor holds at
        least one seat assignment whose `occupancy_status` is `ASSIGNED`."

        Design: Difficulty/boundary_precision_check/eligible_pool_floor_inclusive_at_exact_points_match
        """
        donor, event_in, _event_out = _floor_at_and_above_the_only_donor(client)

        assert_donor_points(read_donor(client, donor["id"]), certified_points="90.00")

        published = publish_slots(client, event_in["id"])
        assert published["status"] == EVENT_SLOTS_PUBLISHED
        assert published["published_slot_count"] == 1
        assert published["scheduled_slot_count"] == 1

        slots = list_event_slots(client, event_in["id"])
        assert len(slots) == 1
        assert slots[0]["donor_id"] == donor["id"]
        assert slots[0]["rank_at_publish"] == 1
        assert slots[0]["slot_status"] == SLOT_SCHEDULED

    def test_a_floor_one_hundredth_higher_empties_the_pool(self, client):
        """90.00 does not reach 90.01, so the publication has nobody to rank.

        PRD 3.5: "An empty pool is treated as an error rather than as an empty
        publication: publishing slots against an empty pool is rejected with
        `ERR_NO_ELIGIBLE_DONORS`."

        Design: Difficulty/boundary_precision_check/eligible_pool_floor_inclusive_at_exact_points_match
        """
        _donor, _event_in, event_out = _floor_at_and_above_the_only_donor(client)

        refused = client.publish_slots(event_out["id"], headers=OFFICER)
        validate_error(refused, ERR_NO_ELIGIBLE_DONORS, 422)

    def test_the_rejected_publication_leaves_the_event_untouched(self, client):
        """A refused publish neither advances the event nor writes slot rows.

        PRD 3.6: "It starts in `DRAFT` with `published_slot_count` and
        `scheduled_slot_count` both zero."

        Design: Difficulty/boundary_precision_check/eligible_pool_floor_inclusive_at_exact_points_match
        """
        _donor, _event_in, event_out = _floor_at_and_above_the_only_donor(client)

        client.publish_slots(event_out["id"], headers=OFFICER)

        after = read_event(client, event_out["id"])
        assert after["status"] == EVENT_DRAFT
        assert after["published_slot_count"] == 0
        assert after["scheduled_slot_count"] == 0

        listed = client.list_selection_slots(
            headers=OFFICER, params={"selection_event_id": event_out["id"]}
        )
        rows, meta = validate_list(listed)
        assert rows == []
        assert_page_meta(meta, total_count=0, limit=10, offset=0, has_more=False)
