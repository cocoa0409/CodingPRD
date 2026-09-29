"""The deposit-obligation report, its two variants and the probation cascade."""

from test_helpers import (
    assert_instant_equals,
    bank_deposit,
    factories,
    list_ledger_entries,
    list_matching_runs,
    read_compliance,
    read_deposit,
    read_member,
    read_resort,
    run_matching,
    set_clock,
    setup_market,
    withdraw_deposit,
)


def _pine_hollow_market(required_annual_deposit_units):
    """Resort C on a year-long SILVER band with one dues-paid member."""
    market = setup_market(
        member_count=1,
        resort_overrides=dict(
            factories.RESORT_C,
            required_annual_deposit_units=required_annual_deposit_units,
        ),
        band_code="SILVER",
        band_start_month_day="01-01",
        band_end_month_day="12-31",
    )
    market["member"] = market["members"][0]
    resort = market["resort"]
    assert_instant_equals(
        resort["affiliated_on"], "2026-08-01T00:00:00Z", "affiliated_on"
    )
    return market


def _split_year_inventory():
    """One week stayed inside the affiliation year and one banked inside it for later."""
    market = _pine_hollow_market(2)
    member, resort_id = market["member"], market["resort"]["id"]

    in_year = bank_deposit(
        member["id"], resort_id, unit_size="STUDIO", check_in_date="2027-06-15"
    )
    set_clock("2027-06-01T00:00:00Z")
    out_of_year = bank_deposit(
        member["id"], resort_id, unit_size="TWO_BR", check_in_date="2027-10-15"
    )
    market["in_year"] = in_year
    market["out_of_year"] = out_of_year
    return market


def _expiring_single_week_market():
    """Resort C meeting its obligation of one with a week about to expire."""
    market = _pine_hollow_market(1)
    market["deposit"] = bank_deposit(
        market["member"]["id"], market["resort"]["id"], unit_size="STUDIO",
        check_in_date="2026-11-01",
    )
    assert market["deposit"]["awarded_power"] == 27
    assert_instant_equals(
        market["deposit"]["expires_at"], "2028-10-31T00:00:00Z", "expires_at"
    )
    return market


class TestObligationShortfallVariants:
    def test_the_two_variants_disagree_on_a_week_banked_in_year_for_a_later_stay(
        self, api
    ):
        """One report, two answers: 1 week of stayable inventory, 2 transactions filed.

        PRD §3.1: "The first measurement, reported as `counted_by_stay_year` with
        its shortfall as `shortfall_by_stay_year`, keys on each deposit's
        `check_in_date` and answers how many weeks of stayable inventory the
        resort actually put into the year. The second, reported as
        `counted_by_deposit_date` with its shortfall as
        `shortfall_by_deposit_date`, keys on the calendar date each deposit row
        was created and answers how many deposit transactions the resort filed
        during the year, regardless of when the stay falls."

        Design: Difficulty/dual_variant_calc/resort_obligation_shortfall_stay_year_vs_deposit_date
        """
        market = _split_year_inventory()

        compliance = read_compliance(market["resort"]["id"])
        assert compliance["affiliation_year_start"] == "2026-08-01"
        assert compliance["affiliation_year_end"] == "2027-08-01", (
            "365 days after the start, exclusive"
        )
        assert compliance["obligation_units"] == 2
        assert compliance["deposits_committed_count"] == 2
        assert compliance["committed_nights"] == 16

        assert compliance["counted_by_stay_year"] == 1, (
            "only the 2027-06-15 stay falls inside the affiliation year"
        )
        assert compliance["shortfall_by_stay_year"] == 1
        assert compliance["counted_by_deposit_date"] == 2, (
            "both rows were filed inside the year"
        )
        assert compliance["shortfall_by_deposit_date"] == 0

        assert market["in_year"]["awarded_power"] == 32, (
            "30 * 1.00 * 0.90 = 27, no bonus, lead 318 gives 1.20, 32.4 -> 32"
        )
        assert market["out_of_year"]["awarded_power"] == 54, (
            "60 * 1.00 * 0.90 = 54.0 -> 54, no bonus, lead 136 gives 1.00"
        )

    def test_a_stay_year_shortfall_on_its_own_does_not_probate_the_resort(self, api):
        """Only the step 1 expiry cascade ever evaluates the shortfall.

        PRD §3.5: "Only resorts that lost at least one week to step 1 of *this*
        run are evaluated, in `created_at` ascending order. ... Resorts untouched
        by step 1 are not evaluated at all, so a run that expires nothing puts
        nobody on probation, however far behind its obligation a resort may be."

        Design: Difficulty/dual_variant_calc/resort_obligation_shortfall_stay_year_vs_deposit_date
        """
        market = _split_year_inventory()
        assert read_compliance(market["resort"]["id"])["shortfall_by_stay_year"] == 1

        run = run_matching("checkpoint with nothing to expire")
        assert run["expired_deposit_count"] == 0
        assert run["probation_resort_count"] == 0

        assert read_resort(market["resort"]["id"])["affiliation_status"] == "ACTIVE"


class TestExpiryShortfallProbationChain:
    def test_the_expiry_recounts_the_resort_and_step_six_probates_it(self, api):
        """Nothing in the request body names the resort, yet it lands on PROBATION.

        PRD §3.5: "For each, the authoritative stay-year shortfall of §3.1 is
        recomputed, and when that shortfall is at least 1 and the resort's
        `affiliation_status` is `ACTIVE`, the resort moves `ACTIVE` → `PROBATION`
        and `probation_resort_count` rises by 1."

        Design: Difficulty/transitive_cascade/deposit_expiry_resort_shortfall_probation_chain
        """
        market = _expiring_single_week_market()
        before = read_compliance(market["resort"]["id"])
        assert before["shortfall_by_stay_year"] == 0, "the obligation of one is met"
        assert before["deposits_committed_count"] == 1
        assert before["committed_nights"] == 8

        set_clock("2028-11-01T00:00:00Z")
        run = run_matching("expire the ageing week")

        week = read_deposit(market["deposit"]["id"])
        assert week["deposit_status"] == "EXPIRED"
        assert week["awarded_power"] == 27
        assert week["rental_status"] == "NOT_LISTED"

        assert read_member(market["member"]["id"])["trading_power_balance"] == 0
        rows, forfeits = list_ledger_entries(
            member_id=market["member"]["id"], entry_type="DEPOSIT_EXPIRY_FORFEIT"
        )
        assert forfeits["total_count"] == 1
        assert rows[0]["power_delta"] == -27

        resort = read_resort(market["resort"]["id"])
        assert resort["deposits_committed_count"] == 0
        assert resort["committed_nights"] == 0
        assert resort["affiliation_status"] == "PROBATION"

        after = read_compliance(market["resort"]["id"])
        assert after["obligation_units"] == 1
        assert after["counted_by_stay_year"] == 0
        assert after["shortfall_by_stay_year"] == 1

        assert run["expired_deposit_count"] == 1
        assert run["probation_resort_count"] == 1
        assert run["getaway_listed_count"] == 0, "an EXPIRED week is not listed"
        assert run["lapsed_member_count"] == 0

    def test_a_second_run_that_expires_nothing_re_evaluates_nobody(self, api):
        """The shortfall is still 1, but step 6 sees no resort touched by step 1.

        PRD §3.5: "Step 6 — resort probation. Only resorts that lost at least one
        week to step 1 of *this* run are evaluated, in `created_at` ascending
        order."

        Design: Difficulty/transitive_cascade/deposit_expiry_resort_shortfall_probation_chain
        """
        market = _expiring_single_week_market()
        set_clock("2028-11-01T00:00:00Z")
        run_matching("expire the ageing week")

        second = run_matching("checkpoint at the same instant")
        assert second["expired_deposit_count"] == 0
        assert second["probation_resort_count"] == 0

        assert read_resort(market["resort"]["id"])["affiliation_status"] == "PROBATION"
        assert read_compliance(market["resort"]["id"])["shortfall_by_stay_year"] == 1

        runs, meta = list_matching_runs()
        assert meta["total_count"] == 2
        assert [row["run_sequence"] for row in runs] == [1, 2]


class TestCountedDepositStatuses:
    def test_a_withdrawn_week_leaves_the_counted_set_without_leaving_the_table(
        self, api
    ):
        """The obligation count is a filtered aggregate, not a row count.

        PRD §3.1: "For both measurements, only deposits of that resort whose
        `deposit_status` is `BANKED`, `RESERVED` or `USED` are counted, and only
        those whose relevant date falls inside the half-open affiliation year — on
        or after the start, strictly before the end."

        Design: Corner/calculations/resort_compliance_counts_only_banked_reserved_and_used_deposits
        """
        market = setup_market(
            member_count=1,
            resort_overrides=dict(
                factories.RESORT_A, required_annual_deposit_units=3
            ),
        )
        member, resort_id = market["members"][0], market["resort"]["id"]

        one_br = bank_deposit(
            member["id"], resort_id, unit_size="ONE_BR", check_in_date="2027-06-15"
        )
        two_br = bank_deposit(
            member["id"], resort_id, unit_size="TWO_BR", check_in_date="2027-05-10"
        )
        studio = bank_deposit(
            member["id"], resort_id, unit_size="STUDIO", check_in_date="2027-06-15"
        )
        assert one_br["awarded_power"] == 82
        assert two_br["awarded_power"] == 107
        assert studio["awarded_power"] == 56, (
            "30 * 1.25 * 1.10 = 41.25 -> 41, plus 6 is 47, times 1.20 -> 56.4 -> 56"
        )

        withdraw_deposit(two_br["id"], member["id"])

        compliance = read_compliance(resort_id)
        assert compliance["affiliation_year_start"] == "2026-08-01"
        assert compliance["affiliation_year_end"] == "2027-08-01"
        assert compliance["obligation_units"] == 3
        assert compliance["counted_by_stay_year"] == 2, (
            "the WITHDRAWN week is excluded even though its check-in is inside the year"
        )
        assert compliance["shortfall_by_stay_year"] == 1
        assert compliance["counted_by_deposit_date"] == 2, (
            "the status filter applies to both variants"
        )
        assert compliance["shortfall_by_deposit_date"] == 1
        assert compliance["deposits_committed_count"] == 2
        assert compliance["committed_nights"] == 16, (
            "both counters were decremented by the withdrawal"
        )

        gone = read_deposit(two_br["id"])
        assert gone["deposit_status"] == "WITHDRAWN", (
            "filtered out of the aggregate, not deleted"
        )
        assert read_member(member["id"])["trading_power_balance"] == 138, (
            "82 and 56 remain after the withdrawn 107 is reversed"
        )
