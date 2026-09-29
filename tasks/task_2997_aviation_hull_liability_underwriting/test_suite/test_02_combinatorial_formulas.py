"""Combinatorial premium formulas: the pinned rate chain and the pinned rounding order.

Two orderings decide the money here.  A hull's rate is three successive
multiplications each of which discards its own fraction before the next one runs,
and a fleet declaration rounds every reported line up on its own before the lines
are added together.  Every expected figure is rebuilt from those orderings with
the pure helpers of the toolkit, never read back from the response under test.
"""

from test_helpers import (
    AcquisitionSource,
    CoverageStatus,
    DeclarationStatus,
    LicenseType,
    PolicyType,
    TerritorialLimit,
    TxnType,
    UseClass,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# ----------------------------------------------------------------------
# The slip terms every policy in this module is written on.
# ----------------------------------------------------------------------
BASE_HULL_RATE_PPM = 18000

# The hulls and the values they are written at.
INSTRUCTIONAL_AGREED_VALUE_CENTS = 45000000
PRIVATE_AGREED_VALUE_CENTS = 30000000
PRIVATE_REGISTRATION_MARKS = ("N512NW", "N513NW", "N514NW", "N515NW")

# The three turboprops that are acquired automatically and reported later.
ACQUIRED_HULLS = (
    {
        "registration_mark": "N521NW",
        "hull_new_value_cents": 50000000,
        "seat_count": 8,
        "max_takeoff_weight_kg": 4200,
        "agreed_value_cents": 32500000,
        "effective_from": "2026-09-15T00:00:00Z",
    },
    {
        "registration_mark": "N522NW",
        "hull_new_value_cents": 70000000,
        "seat_count": 9,
        "max_takeoff_weight_kg": 4600,
        "agreed_value_cents": 45500000,
        "effective_from": "2026-09-20T00:00:00Z",
    },
    {
        "registration_mark": "N523NW",
        "hull_new_value_cents": 48000000,
        "seat_count": 8,
        "max_takeoff_weight_kg": 4200,
        "agreed_value_cents": 31250000,
        "effective_from": "2026-09-25T00:00:00Z",
    },
)
DECLARATION_PERIOD_FROM = f.POLICY_EFFECTIVE_FROM
DECLARATION_PERIOD_TO = "2026-09-30T00:00:00Z"

# The figures the broker declares for the two named pilots.
CPL_TOTAL_HOURS = 1200
CPL_HOURS_ON_TYPE = 80
CPL_LAST_TRAINING_AT = "2026-06-01T00:00:00Z"
ATPL_TOTAL_HOURS = 3000
ATPL_HOURS_ON_TYPE = 300
ATPL_LAST_TRAINING_AT = "2026-07-01T00:00:00Z"


def commercial_pilot_band() -> str:
    """The band the commercially licensed pilot's declared hours earn."""
    return c.band_for_score(
        c.qualification_score(
            CPL_TOTAL_HOURS,
            CPL_HOURS_ON_TYPE,
            False,
            LicenseType.CPL,
            CPL_LAST_TRAINING_AT,
            f.CLOCK_BEFORE_INCEPTION,
        )
    )


def airline_pilot_band() -> str:
    """The band the airline-licensed pilot's declared hours earn."""
    return c.band_for_score(
        c.qualification_score(
            ATPL_TOTAL_HOURS,
            ATPL_HOURS_ON_TYPE,
            True,
            LicenseType.ATPL,
            ATPL_LAST_TRAINING_AT,
            f.CLOCK_BEFORE_INCEPTION,
        )
    )


def worldwide_rate_ppm(use_class: str, band: str) -> int:
    """The rate a worldwide hull of a given use class carries on a given band."""
    return c.rate_ppm_for(
        BASE_HULL_RATE_PPM, use_class, TerritorialLimit.WORLDWIDE, band
    )


def worldwide_premium_cents(
    agreed_value_cents: int, use_class: str, band: str, live_schedule_count: int
) -> int:
    """The annual premium of one worldwide hull, credit included where it applies."""
    return c.annual_premium_cents(
        agreed_value_cents,
        worldwide_rate_ppm(use_class, band),
        PolicyType.FLEET,
        live_schedule_count,
    )


def draft_policy_one_hull_short_of_the_credit(api):
    """A draft fleet policy carrying four live hulls, one short of the credit.

    The first hull is instructional and flown by the commercially licensed pilot;
    the other three are private hulls of identical value flown by the airline
    pilot, so the fifth attachment is structurally identical to the fourth and
    the only thing that changes between them is the size of the fleet.
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    twin = fx.make_aircraft(api)
    singles = [
        fx.make_aircraft(api, f.single_piston_aircraft_payload(registration_mark=mark))
        for mark in PRIVATE_REGISTRATION_MARKS
    ]
    commercial_pilot = fx.make_pilot(api)
    airline_pilot = fx.make_pilot(api, f.senior_pilot_payload())
    policy = fx.make_policy(api, operator["id"])
    instructional = fx.make_schedule(
        api, policy["id"], twin["id"], commercial_pilot["id"]
    )
    private_ids = [
        fx.make_schedule(
            api,
            policy["id"],
            single["id"],
            airline_pilot["id"],
            use_class=UseClass.PRIVATE,
            agreed_value_cents=PRIVATE_AGREED_VALUE_CENTS,
        )["id"]
        for single in singles[:3]
    ]
    return {
        "policy_id": policy["id"],
        "instructional_schedule_id": instructional["id"],
        "private_schedule_ids": private_ids,
        "fifth_aircraft_id": singles[3]["id"],
        "airline_pilot_id": airline_pilot["id"],
    }


def attach_fifth_hull(api, book):
    """Attach the fifth hull, the one that takes the fleet over the threshold."""
    return validate_unpaginated(
        api.create_schedule(
            f.schedule_payload(
                book["policy_id"],
                book["fifth_aircraft_id"],
                book["airline_pilot_id"],
                use_class=UseClass.PRIVATE,
                agreed_value_cents=PRIVATE_AGREED_VALUE_CENTS,
            ),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )


class TestFourFactorRateChain:
    """The rate chain and the fleet-size credit that hangs off its result."""

    def test_instructional_worldwide_hull_prices_off_the_three_pinned_factors(self, api):
        """PRD §3.4: "Multiplying the three factors together before applying them, or
        rounding only once at the end, produces a different rate for many inputs and is not
        the specified behaviour: the fraction must be discarded after each of the three
        multiplications, in the stated order."

        Design: Difficulty/combinatorial_formula/four_factor_rate_chain_with_fleet_size_credit_branch
        """
        book = draft_policy_one_hull_short_of_the_credit(api)

        band = commercial_pilot_band()
        schedule = fx.fetch_schedule(api, book["instructional_schedule_id"])
        assert schedule["rated_pilot_band"] == band
        assert schedule["rate_ppm"] == worldwide_rate_ppm(UseClass.INSTRUCTIONAL, band)
        assert schedule["hull_premium_cents"] == worldwide_premium_cents(
            INSTRUCTIONAL_AGREED_VALUE_CENTS, UseClass.INSTRUCTIONAL, band, 1
        )

    def test_private_hulls_on_the_airline_band_carry_the_cheapest_rate(self, api):
        """PRD §3.4: "The gross annual premium is `agreed_value_cents` multiplied by
        `rate_ppm`, divided by 1,000,000, with the fraction discarded."

        Design: Difficulty/combinatorial_formula/four_factor_rate_chain_with_fleet_size_credit_branch
        """
        book = draft_policy_one_hull_short_of_the_credit(api)

        band = airline_pilot_band()
        expected_rate = worldwide_rate_ppm(UseClass.PRIVATE, band)
        expected_premium = worldwide_premium_cents(
            PRIVATE_AGREED_VALUE_CENTS, UseClass.PRIVATE, band, 2
        )
        first = fx.fetch_schedule(api, book["private_schedule_ids"][0])
        assert first["rated_pilot_band"] == band
        assert first["rate_ppm"] == expected_rate
        assert first["hull_premium_cents"] == expected_premium
        # The fourth hull on the policy is still priced without any credit.
        fourth = fx.fetch_schedule(api, book["private_schedule_ids"][2])
        assert fourth["rate_ppm"] == expected_rate
        assert fourth["hull_premium_cents"] == expected_premium
        # A private hull rates below the instructional hull on the same slip.
        assert expected_rate < worldwide_rate_ppm(
            UseClass.INSTRUCTIONAL, commercial_pilot_band()
        )

    def test_fifth_live_hull_earns_the_five_per_cent_fleet_credit(self, api):
        """PRD §3.4: "A policy's first four hulls are priced without the credit; the fifth
        and later hulls are priced with it; and the earlier four are not re-rated when the
        fleet later crosses the threshold."

        Design: Difficulty/combinatorial_formula/four_factor_rate_chain_with_fleet_size_credit_branch
        """
        book = draft_policy_one_hull_short_of_the_credit(api)

        fifth = attach_fifth_hull(api, book)

        band = airline_pilot_band()
        expected_rate = worldwide_rate_ppm(UseClass.PRIVATE, band)
        gross = worldwide_premium_cents(PRIVATE_AGREED_VALUE_CENTS, UseClass.PRIVATE, band, 4)
        credited = worldwide_premium_cents(
            PRIVATE_AGREED_VALUE_CENTS, UseClass.PRIVATE, band, 5
        )
        credit = c.floor_ppm(gross, c.FLEET_CREDIT_PPM)
        # The credit touches the premium alone: the rate chain is unchanged.
        assert fifth["rate_ppm"] == expected_rate
        assert fifth["hull_premium_cents"] == credited
        assert credited == gross - credit
        # The fourth hull keeps the premium it was priced at, retroactively untouched.
        fourth = fx.fetch_schedule(api, book["private_schedule_ids"][2])
        assert fourth["hull_premium_cents"] == gross
        assert fifth["hull_premium_cents"] == fourth["hull_premium_cents"] - credit

    def test_fifth_attachment_grows_the_sum_insured_population(self, api):
        """PRD §3.4: "Attaching a schedule closes by updating the policy's
        `total_hull_sum_insured_cents` and `live_schedule_count` and advancing the
        schedule's `version`."

        Design: Difficulty/combinatorial_formula/four_factor_rate_chain_with_fleet_size_credit_branch
        """
        book = draft_policy_one_hull_short_of_the_credit(api)
        before = fx.fetch_policy(api, book["policy_id"])
        assert before["live_schedule_count"] == 4

        attach_fifth_hull(api, book)

        policy = fx.fetch_policy(api, book["policy_id"])
        assert policy["live_schedule_count"] == 5
        assert policy["total_hull_sum_insured_cents"] == (
            INSTRUCTIONAL_AGREED_VALUE_CENTS + 4 * PRIVATE_AGREED_VALUE_CENTS
        )


def bound_policy_with_three_acquired_hulls(api):
    """A bound fleet account carrying three unreported automatic acquisitions.

    The three turboprops attach on three different dates inside September at
    three different values, so each one contributes a different unexpired
    fraction of its own annual premium to the reporting declaration.  The clock
    is left inside the reporting window that follows the period.
    """
    fx.advance_clock(api, f.CLOCK_BEFORE_INCEPTION)
    operator = fx.make_operator(api)
    twin = fx.make_aircraft(api)
    commercial_pilot = fx.make_pilot(api)
    airline_pilot = fx.make_pilot(api, f.senior_pilot_payload())
    policy = fx.make_policy(api, operator["id"], automatic_acquisition_enabled=True)
    scheduled = fx.make_schedule(api, policy["id"], twin["id"], commercial_pilot["id"])
    fx.bind_policy(api, policy["id"])
    acquired_ids = []
    for hull in ACQUIRED_HULLS:
        airframe = fx.make_aircraft(
            api,
            f.turboprop_aircraft_payload(
                registration_mark=hull["registration_mark"],
                hull_new_value_cents=hull["hull_new_value_cents"],
                seat_count=hull["seat_count"],
                max_takeoff_weight_kg=hull["max_takeoff_weight_kg"],
            ),
        )
        acquired = fx.make_schedule(
            api,
            policy["id"],
            airframe["id"],
            airline_pilot["id"],
            headers=users.BROKER,
            use_class=UseClass.BUSINESS,
            agreed_value_cents=hull["agreed_value_cents"],
            effective_from=hull["effective_from"],
            acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
        )
        acquired_ids.append(acquired["id"])
    fx.advance_clock(api, f.CLOCK_AFTER_LOSS)
    return {
        "policy_id": policy["id"],
        "scheduled_schedule_id": scheduled["id"],
        "acquired_schedule_ids": acquired_ids,
    }


def declare_the_september_acquisitions(api, book):
    """Report the three September acquisitions, priced once at creation."""
    return validate_unpaginated(
        api.create_fleet_declaration(
            f.fleet_declaration_payload(
                book["policy_id"],
                period_from=DECLARATION_PERIOD_FROM,
                period_to=DECLARATION_PERIOD_TO,
            ),
            headers=users.BROKER,
        ),
        expected_status=201,
    )


def expected_acquired_premium_cents(agreed_value_cents: int) -> int:
    """The annual premium an acquired business hull is priced at on attachment.

    Each acquisition joins a fleet of at most four live hulls, so none of them
    reaches the fleet-size credit threshold.
    """
    return worldwide_premium_cents(
        agreed_value_cents, UseClass.BUSINESS, airline_pilot_band(), 4
    )


def expected_declaration_lines() -> list:
    """The three individually rounded-up pro-rata lines, in reporting order."""
    return [
        c.pro_rata_charge_cents(
            expected_acquired_premium_cents(hull["agreed_value_cents"]),
            c.whole_days_between(hull["effective_from"], f.POLICY_EFFECTIVE_TO),
            f.POLICY_TERM_DAYS,
        )
        for hull in ACQUIRED_HULLS
    ]


class TestFleetDeclarationPricing:
    """The reporting declaration that regularises the automatic acquisitions."""

    def test_reportable_population_is_ordered_by_when_each_hull_attached(self, api):
        """PRD §3.8: "The population is ordered by `effective_from` ascending, with ties
        broken by `created_at` ascending, and their identifiers are recorded in that order
        into `reported_schedule_ids`; `declared_count` is the size of the population."

        Design: Difficulty/combinatorial_formula/fleet_declaration_round_per_line_then_sum
        """
        book = bound_policy_with_three_acquired_hulls(api)

        declaration = declare_the_september_acquisitions(api, book)

        assert declaration["reported_schedule_ids"] == book["acquired_schedule_ids"]
        assert declaration["declared_count"] == len(ACQUIRED_HULLS)
        assert declaration["status"] == DeclarationStatus.SUBMITTED
        # The hull attached as SCHEDULED is not reportable.
        assert book["scheduled_schedule_id"] not in declaration["reported_schedule_ids"]

    def test_each_line_is_rounded_up_on_its_own_before_the_lines_are_added(self, api):
        """PRD §3.8: "For each reportable schedule in turn, take its `hull_premium_cents`,
        multiply by the number of whole days from the calendar date of that schedule's own
        `effective_from` to the calendar date of the policy's `effective_to`, divide by the
        policy's `term_days`, and round **up** to the next whole cent; then add those
        individually-rounded lines together."

        Design: Difficulty/combinatorial_formula/fleet_declaration_round_per_line_then_sum
        """
        book = bound_policy_with_three_acquired_hulls(api)
        rate = worldwide_rate_ppm(UseClass.BUSINESS, airline_pilot_band())
        for schedule_id, hull in zip(book["acquired_schedule_ids"], ACQUIRED_HULLS):
            schedule = fx.fetch_schedule(api, schedule_id)
            assert schedule["rate_ppm"] == rate
            assert schedule["hull_premium_cents"] == expected_acquired_premium_cents(
                hull["agreed_value_cents"]
            )

        declaration = declare_the_september_acquisitions(api, book)

        assert declaration["declared_premium_cents"] == sum(expected_declaration_lines())
        # Summing the exact fractional lines and rounding once at the end under-charges.
        rounded_once = c.ceil_div(
            sum(
                expected_acquired_premium_cents(hull["agreed_value_cents"])
                * c.whole_days_between(hull["effective_from"], f.POLICY_EFFECTIVE_TO)
                for hull in ACQUIRED_HULLS
            ),
            f.POLICY_TERM_DAYS,
        )
        assert rounded_once < sum(expected_declaration_lines())
        assert declaration["declared_premium_cents"] != rounded_once

    def test_a_declaration_inside_the_reporting_window_carries_no_late_loading(self, api):
        """PRD §3.8: "`late_flag` becomes true when the number of whole days from the
        calendar date of `period_to` to the calendar date of the current logical clock is
        greater than the policy's `acquisition_reporting_days`; a declaration submitted
        exactly on the deadline is not late."

        Design: Difficulty/combinatorial_formula/fleet_declaration_round_per_line_then_sum
        """
        book = bound_policy_with_three_acquired_hulls(api)
        policy = fx.fetch_policy(api, book["policy_id"])
        elapsed = c.whole_days_between(DECLARATION_PERIOD_TO, f.CLOCK_AFTER_LOSS)
        assert elapsed <= policy["acquisition_reporting_days"]

        declaration = declare_the_september_acquisitions(api, book)

        assert declaration["late_flag"] is False
        assert declaration["late_loading_cents"] == 0
        # With no loading the declared premium is the line total exactly.
        assert declaration["declared_premium_cents"] == sum(expected_declaration_lines())

    def test_creating_a_declaration_mutates_no_schedule_and_writes_no_ledger_row(self, api):
        """PRD §3.8: "Creating a declaration mutates no schedule and writes no ledger row:
        it is purely a priced proposal."

        Design: Difficulty/combinatorial_formula/fleet_declaration_round_per_line_then_sum
        """
        book = bound_policy_with_three_acquired_hulls(api)
        before = fx.fetch_policy(api, book["policy_id"])

        declare_the_september_acquisitions(api, book)

        for schedule_id in book["acquired_schedule_ids"]:
            assert (
                fx.fetch_schedule(api, schedule_id)["coverage_status"]
                == CoverageStatus.PENDING
            )
        rows, meta = validate_list(
            api.list_premium_transactions(
                headers=users.UNDERWRITER,
                params={
                    "policy_id": book["policy_id"],
                    "txn_type": TxnType.DECLARATION_PREMIUM,
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
        after = fx.fetch_policy(api, book["policy_id"])
        assert after["written_premium_cents"] == before["written_premium_cents"]
