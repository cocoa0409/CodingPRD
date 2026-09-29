"""The two season-level policy switches and the figures they move.

PRD §3.1 puts both switches on the season: "Both switches are read from the
season, never from the request that triggers the calculation."
"""

from test_helpers import (
    BondPaymentPlan,
    DuesStatus,
    AccessStatus,
    GuestSettlementPolicy,
    ProrationBasis,
    fixtures as fx,
    validate_success,
)
from test_helpers.test_users import MEMBERSHIP_CHAIR, POOL_MANAGER
from test_helpers.factories import guest_visit_payload, membership_payload


def _two_season_dues_setup(api, basis_2027, basis_2028):
    """One FAMILY category and two identically shaped seasons, both OPEN."""
    fx.set_clock(api, "2027-07-06T09:00:00Z")
    category = fx.create_family_category(api)
    season_27 = fx.create_season(
        api, year=2027, open_date="2027-05-22", close_date="2027-09-06",
        dues_due_date="2027-04-15", baseline_bather_load=0,
        bather_load_capacity=120, proration_basis=basis_2027,
        guest_settlement_policy=GuestSettlementPolicy.PASS_FIRST,
    )
    fx.open_season(api, season_27["id"])
    season_28 = fx.create_season(
        api, year=2028, open_date="2028-05-20", close_date="2028-09-04",
        dues_due_date="2028-04-15", baseline_bather_load=0,
        bather_load_capacity=120, proration_basis=basis_2028,
        guest_settlement_policy=GuestSettlementPolicy.PASS_FIRST,
    )
    fx.open_season(api, season_28["id"])
    household = fx.create_household(
        api, primary_contact_name="Alvarez Household",
        address_line="14 Poolside Lane", member_count=4, prior_member=False,
    )
    return category, season_27, season_28, household


def _sell(api, household_id, category_id, season_id, join_date):
    payload = membership_payload(
        household_id=household_id, membership_category_id=category_id,
        season_id=season_id, join_date=join_date,
        bond_payment_plan=BondPaymentPlan.INSTALLMENTS,
    )
    return validate_success(api.create_membership(payload, MEMBERSHIP_CHAIR), 201)


class TestSeasonalDuesProrationVariants:
    """Both seasons span 108 inclusive days and 16 ceiling weeks, and both
    joiners have 64 inclusive days (10 ceiling weeks) left to swim.
    """

    def test_calendar_day_and_swim_week_stamp_different_assessments(self, api):
        """The proration basis alone moves assessed_dues_cents by 2528 cents.

        PRD §3.3: "under `CALENDAR_DAY` the assessment is the category's
        `seasonal_dues_cents` multiplied by the remaining calendar days and
        divided by the total calendar days, with the single final result rounded
        half up to a whole cent; under `SWIM_WEEK` it is `seasonal_dues_cents`
        multiplied by the remaining swim weeks and divided by the total swim
        weeks, again with one half-up rounding applied to the final result."

        Design: Difficulty/dual_variant_calc/seasonal_dues_calendar_day_vs_swim_week_on_membership
        """
        category, season_27, season_28, household = _two_season_dues_setup(
            api, ProrationBasis.CALENDAR_DAY, ProrationBasis.SWIM_WEEK
        )

        calendar_day = _sell(api, household["id"], category["id"],
                             season_27["id"], "2027-07-05")
        swim_week = _sell(api, household["id"], category["id"],
                          season_28["id"], "2028-07-03")

        assert calendar_day["assessed_dues_cents"] == 46222
        assert swim_week["assessed_dues_cents"] == 48750
        assert (
            swim_week["assessed_dues_cents"]
            - calendar_day["assessed_dues_cents"] == 2528
        )

    def test_both_assessments_are_stamped_on_an_unbilled_pending_membership(
        self, api
    ):
        """Each variant stamps its figure while the row is still UNBILLED.

        PRD §3.3: "`assessed_dues_cents` is stamped exactly once, while the
        membership is still `UNBILLED`, and is never re-derived."

        Design: Difficulty/dual_variant_calc/seasonal_dues_calendar_day_vs_swim_week_on_membership
        """
        category, season_27, season_28, household = _two_season_dues_setup(
            api, ProrationBasis.CALENDAR_DAY, ProrationBasis.SWIM_WEEK
        )

        calendar_day = _sell(api, household["id"], category["id"],
                             season_27["id"], "2027-07-05")
        swim_week = _sell(api, household["id"], category["id"],
                          season_28["id"], "2028-07-03")

        for membership in (calendar_day, swim_week):
            assert membership["dues_status"] == DuesStatus.UNBILLED
            assert membership["access_status"] == AccessStatus.PENDING

    def test_the_initiation_fee_line_fires_on_both_variant_memberships(self, api):
        """A household that has never been a member pays the one-time fee once.

        PRD §3.3: "`initiation_fee_cents` receives the category's
        `initiation_fee_cents` when the household's `prior_member` flag is false
        at that moment, and 0 when it is true."

        PRD §3.2: "`prior_member` may be supplied directly at registration and
        otherwise defaults to false; it becomes true when a bond is transferred
        in, and it becomes true once the household has ever held a membership."

        The first sale therefore bills the fee and the second escapes it: the
        household became a returning member the moment its first membership was
        created.

        Design: Difficulty/dual_variant_calc/seasonal_dues_calendar_day_vs_swim_week_on_membership
        """
        category, season_27, season_28, household = _two_season_dues_setup(
            api, ProrationBasis.CALENDAR_DAY, ProrationBasis.SWIM_WEEK
        )

        calendar_day = _sell(api, household["id"], category["id"],
                             season_27["id"], "2027-07-05")
        assert calendar_day["initiation_fee_cents"] == 45000

        swim_week = _sell(api, household["id"], category["id"],
                          season_28["id"], "2028-07-03")
        assert swim_week["initiation_fee_cents"] == 0


def _two_policy_visit_setup(api):
    """Two households, one active membership each, in seasons whose guest
    settlement policies differ. Each household is its own resource owner.
    """
    fx.set_clock(api, "2028-07-10T09:00:00Z")
    category = fx.create_family_category(api)

    season_27 = fx.create_season(
        api, year=2027, open_date="2027-05-22", close_date="2027-09-06",
        dues_due_date="2027-04-15", baseline_bather_load=0,
        bather_load_capacity=120,
        proration_basis=ProrationBasis.CALENDAR_DAY,
        guest_settlement_policy=GuestSettlementPolicy.PASS_FIRST,
    )
    fx.open_season(api, season_27["id"])
    season_28 = fx.create_season(
        api, year=2028, open_date="2028-05-20", close_date="2028-09-04",
        dues_due_date="2028-04-15", baseline_bather_load=0,
        bather_load_capacity=120,
        proration_basis=ProrationBasis.CALENDAR_DAY,
        guest_settlement_policy=GuestSettlementPolicy.FEE_FIRST_ON_WEEKEND,
    )
    fx.open_season(api, season_28["id"])

    pass_first_household = fx.create_household(
        api, primary_contact_name="Pass First Household",
        address_line="2 Diving Board Way", member_count=4, prior_member=False,
    )
    pass_first_membership = _sell(api, pass_first_household["id"],
                                 category["id"], season_27["id"],
                                 "2027-07-05")
    fx.invoice_membership(api, pass_first_membership["id"])

    fee_first_household = fx.create_household(
        api, primary_contact_name="Fee First Household",
        address_line="3 Diving Board Way", member_count=4, prior_member=False,
    )
    fee_first_membership = _sell(api, fee_first_household["id"],
                                category["id"], season_28["id"],
                                "2028-07-03")
    fx.invoice_membership(api, fee_first_membership["id"])

    return {
        "pass_first": {
            "household": fx.read_household(api, pass_first_household["id"]),
            "membership": pass_first_membership,
            "visit_iso": "2027-07-10T11:00:00Z",
        },
        "fee_first": {
            "household": fx.read_household(api, fee_first_household["id"]),
            "membership": fee_first_membership,
            "visit_iso": "2028-07-08T11:00:00Z",
        },
    }


def _record_six_guests(api, arm):
    payload = guest_visit_payload(
        membership_id=arm["membership"]["id"],
        expected_household_version=arm["household"]["version"],
        sponsor_name="Rosa Alvarez", guest_count=6,
        visit_start_iso=arm["visit_iso"],
    )
    return validate_success(api.create_guest_visit(payload, POOL_MANAGER), 201)


class TestGuestSettlementVariantsOnAWeekend:
    """Six weekend guests against a four-pass balance, settled two ways."""

    def test_pass_first_burns_four_passes_and_bills_the_two_remaining_guests(
        self, api
    ):
        """PASS_FIRST spends passes on every day of the week alike.

        PRD §3.5: "Under the `PASS_FIRST` variant, `passes_used` is the smaller
        of the household's current `guest_pass_balance` and the visit's
        `guest_count`, on every day of the week alike."

        Design: Difficulty/dual_variant_calc/guest_visit_pass_first_vs_fee_first_on_weekend
        """
        arms = _two_policy_visit_setup(api)
        visit = _record_six_guests(api, arms["pass_first"])

        assert visit["settlement_variant"] == GuestSettlementPolicy.PASS_FIRST
        assert visit["is_weekend"] is True
        assert visit["passes_used"] == 4
        assert visit["fee_charged_cents"] == 1600

        household = fx.read_household(api, arms["pass_first"]["household"]["id"])
        assert household["guest_pass_balance"] == 0
        assert household["guest_passes_consumed"] == 4
        assert household["guest_fee_owed_cents"] == 1600

    def test_fee_first_on_weekend_spends_no_pass_and_bills_every_guest(self, api):
        """FEE_FIRST_ON_WEEKEND leaves the pass ledger untouched on a weekend.

        PRD §3.5: "Under the `FEE_FIRST_ON_WEEKEND` variant, a weekend visit
        consumes no pass at all — `passes_used` is 0 and every guest is charged
        the weekend fee — while a weekday visit behaves exactly as `PASS_FIRST`
        does."

        Design: Difficulty/dual_variant_calc/guest_visit_pass_first_vs_fee_first_on_weekend
        """
        arms = _two_policy_visit_setup(api)
        visit = _record_six_guests(api, arms["fee_first"])

        assert visit["settlement_variant"] == \
            GuestSettlementPolicy.FEE_FIRST_ON_WEEKEND
        assert visit["is_weekend"] is True
        assert visit["passes_used"] == 0
        assert visit["fee_charged_cents"] == 4800

        household = fx.read_household(api, arms["fee_first"]["household"]["id"])
        assert household["guest_pass_balance"] == 4
        assert household["guest_passes_consumed"] == 0
        assert household["guest_fee_owed_cents"] == 4800

    def test_the_two_variants_diverge_by_3200_cents_on_identical_inputs(self, api):
        """Identical parties of six diverge sharply on cash and on passes.

        PRD §3.5: "The two variants can diverge sharply on identical inputs —
        the same weekend party of six may consume four passes and be billed for
        two guests, or consume none and be billed for all six — and they leave
        different surviving pass balances behind."

        Design: Difficulty/dual_variant_calc/guest_visit_pass_first_vs_fee_first_on_weekend
        """
        arms = _two_policy_visit_setup(api)
        pass_first_visit = _record_six_guests(api, arms["pass_first"])
        fee_first_visit = _record_six_guests(api, arms["fee_first"])

        assert (
            fee_first_visit["fee_charged_cents"]
            - pass_first_visit["fee_charged_cents"] == 3200
        )
        surviving_pass_first = fx.read_household(
            api, arms["pass_first"]["household"]["id"]
        )["guest_pass_balance"]
        surviving_fee_first = fx.read_household(
            api, arms["fee_first"]["household"]["id"]
        )["guest_pass_balance"]
        assert surviving_pass_first == 0
        assert surviving_fee_first == 4
