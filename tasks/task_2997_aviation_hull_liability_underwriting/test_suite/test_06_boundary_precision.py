"""Boundary precision: the exact cent, the exact part per million, the exact day.

Two of this specification's thresholds are declared inclusive, and both are tested
here at the threshold itself and at one unit either side of it.  The constructive
total loss test turns over at exactly 750,000 parts per million of agreed value,
and a fleet declaration's reporting period includes both of its bounds, so a hull
whose cover began on the period's first day is inside the sweep while the same
hull one day earlier than the period is outside it and yields the empty aggregate.
"""

import pytest

from test_helpers import (
    AcquisitionSource,
    AdjustmentStatus,
    AssessmentVerdict,
    CoverageStatus,
    DeclarationStatus,
    LossType,
    TxnBasis,
    TxnType,
    UseClass,
    assert_damage_assessment_shape,
    assert_field_values,
    assert_ledger_row,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

POLICY_TERMS = f.policy_payload("operator")
HULL_TERMS = f.schedule_payload("policy", "aircraft", "pilot")
NAMED_PILOT = f.pilot_payload()
SENIOR_PILOT = f.senior_pilot_payload()
AGREED_VALUE_CENTS = HULL_TERMS["agreed_value_cents"]
TERM_DAYS = c.whole_days_between(
    POLICY_TERMS["effective_from"], POLICY_TERMS["effective_to"]
)


def band_of(pilot, clock_utc):
    """A pilot's rating band on the declared figures at a given instant (§3.2)."""
    return c.band_for_score(
        c.qualification_score(
            pilot["total_logged_hours"],
            pilot["hours_on_type"],
            pilot["instrument_rated"],
            pilot["license_type"],
            pilot["last_training_completed_at"],
            clock_utc,
        )
    )


def smallest_repair_cost_for_ratio(ratio_ppm):
    """The cheapest repair estimate whose floored repair-to-value ratio is `ratio_ppm`."""
    return c.ceil_div(ratio_ppm * AGREED_VALUE_CENTS, c.PPM)


def expected_verdict_for(ratio_ppm):
    """The verdict the inclusive total-loss threshold produces for a ratio."""
    if ratio_ppm >= c.CTL_THRESHOLD_PPM:
        return AssessmentVerdict.CONSTRUCTIVE_TOTAL_LOSS
    return AssessmentVerdict.REPAIRABLE


BELOW_THRESHOLD_PPM = c.CTL_THRESHOLD_PPM - 1
ABOVE_THRESHOLD_PPM = c.CTL_THRESHOLD_PPM + 1
FIRST_SURVEY_AT = "2026-09-10T00:00:00Z"
SECOND_SURVEY_AT = "2026-09-11T00:00:00Z"


def investigated_hull_claim(api):
    """An investigating hull claim on a live bound hull, ready for a survey."""
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_MID_TERM)
    return fx.investigated_claim(api, book)


class TestConstructiveTotalLossThreshold:
    """750,000 parts per million of agreed value, inclusive."""

    @pytest.mark.parametrize(
        "ratio_ppm", [BELOW_THRESHOLD_PPM, c.CTL_THRESHOLD_PPM, ABOVE_THRESHOLD_PPM]
    )
    def test_the_verdict_turns_over_exactly_at_the_threshold(self, api, ratio_ppm):
        """PRD §3.9: "Its `verdict` is `CONSTRUCTIVE_TOTAL_LOSS` when that ratio has
        reached at least 750,000 parts per million — seventy-five per cent of agreed
        value — and `REPAIRABLE` otherwise."

        Design: Difficulty/boundary_precision_check/ctl_ratio_inclusive_threshold_at_exactly_750000_ppm
        """
        book = investigated_hull_claim(api)
        repair_cost_cents = smallest_repair_cost_for_ratio(ratio_ppm)

        assessment = validate_unpaginated(
            api.create_damage_assessment(
                f.damage_assessment_payload(
                    book["claim_id"],
                    repair_cost_estimate_cents=repair_cost_cents,
                    assessed_at=FIRST_SURVEY_AT,
                ),
                headers=users.CLAIMS_ADJUSTER,
            ),
            expected_status=201,
        )

        assert_field_values(
            assessment,
            repair_cost_estimate_cents=repair_cost_cents,
            ctl_ratio_ppm=ratio_ppm,
            verdict=expected_verdict_for(ratio_ppm),
        )
        assert c.ctl_ratio_ppm(repair_cost_cents, AGREED_VALUE_CENTS) == ratio_ppm

    def test_one_part_below_the_threshold_leaves_the_claim_a_repairable_hull_loss(
        self, api
    ):
        """PRD §3.9: "The threshold is inclusive: a ratio of exactly 750,000 is a
        constructive total loss and 749,999 is not."

        Design: Difficulty/boundary_precision_check/ctl_ratio_inclusive_threshold_at_exactly_750000_ppm
        """
        book = investigated_hull_claim(api)

        fx.make_damage_assessment(
            api,
            book["claim_id"],
            repair_cost_estimate_cents=smallest_repair_cost_for_ratio(
                BELOW_THRESHOLD_PPM
            ),
            assessed_at=FIRST_SURVEY_AT,
        )

        claim = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            claim,
            ctl_ratio_ppm=BELOW_THRESHOLD_PPM,
            ctl_flag=False,
            loss_type=LossType.HULL_DAMAGE,
            assessment_count=1,
            adjustment_status=AdjustmentStatus.INVESTIGATING,
        )

    def test_exactly_at_the_threshold_the_claim_becomes_a_total_loss(self, api):
        """PRD §3.9: "Where `ctl_flag` becomes true and the claim's `loss_type` is
        `HULL_DAMAGE`, the loss type is promoted to `TOTAL_LOSS`."

        Design: Difficulty/boundary_precision_check/ctl_ratio_inclusive_threshold_at_exactly_750000_ppm
        """
        book = investigated_hull_claim(api)
        fx.make_damage_assessment(
            api,
            book["claim_id"],
            repair_cost_estimate_cents=smallest_repair_cost_for_ratio(
                BELOW_THRESHOLD_PPM
            ),
            assessed_at=FIRST_SURVEY_AT,
        )
        before = fx.fetch_claim(api, book["claim_id"])

        fx.make_damage_assessment(
            api,
            book["claim_id"],
            repair_cost_estimate_cents=smallest_repair_cost_for_ratio(
                c.CTL_THRESHOLD_PPM
            ),
            assessed_at=SECOND_SURVEY_AT,
        )

        claim = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            claim,
            ctl_ratio_ppm=c.CTL_THRESHOLD_PPM,
            ctl_flag=True,
            loss_type=LossType.TOTAL_LOSS,
            assessment_count=2,
        )
        assert claim["version"] == before["version"] + 1

    def test_the_later_survey_does_not_rewrite_the_earlier_one(self, api):
        """PRD §2.4: "There is no operation anywhere in this API that alters an existing
        damage assessment or an existing ledger row; corrections are made by appending
        new rows, never by editing old ones."

        Design: Difficulty/boundary_precision_check/ctl_ratio_inclusive_threshold_at_exactly_750000_ppm
        """
        book = investigated_hull_claim(api)
        below_cost_cents = smallest_repair_cost_for_ratio(BELOW_THRESHOLD_PPM)
        first = fx.make_damage_assessment(
            api,
            book["claim_id"],
            repair_cost_estimate_cents=below_cost_cents,
            assessed_at=FIRST_SURVEY_AT,
        )

        fx.make_damage_assessment(
            api,
            book["claim_id"],
            repair_cost_estimate_cents=smallest_repair_cost_for_ratio(
                c.CTL_THRESHOLD_PPM
            ),
            assessed_at=SECOND_SURVEY_AT,
        )

        reread = fx.fetch_damage_assessment(api, first["id"])
        assert_damage_assessment_shape(reread)
        assert_field_values(
            reread,
            repair_cost_estimate_cents=below_cost_cents,
            ctl_ratio_ppm=BELOW_THRESHOLD_PPM,
            verdict=AssessmentVerdict.REPAIRABLE,
        )
        assert len(fx.assessments_of_claim(api, book["claim_id"])) == 2


# ----------------------------------------------------------------------
# The reporting period of a fleet declaration
# ----------------------------------------------------------------------
AUTO_COVER_FROM = "2026-09-25T00:00:00Z"
AUTO_AGREED_VALUE_CENTS = 31250000
AUTO_HULL_NEW_VALUE_CENTS = 48000000
AUTO_REGISTRATION_MARK = "N523NW"
DECLARATION_CLOCK = "2026-11-15T00:00:00Z"

# A period whose inclusive lower bound is the day the hull came on risk captures it.
CAPTURING_PERIOD_FROM = AUTO_COVER_FROM
CAPTURING_PERIOD_TO = "2026-09-26T00:00:00Z"
# A period beginning one day later misses it, and misses it by that single day.
EMPTY_PERIOD_FROM = "2026-09-26T00:00:00Z"
EMPTY_PERIOD_TO = "2026-10-31T00:00:00Z"

AUTO_PILOT_BAND = band_of(SENIOR_PILOT, f.CLOCK_BEFORE_INCEPTION)
AUTO_RATE_PPM = c.rate_ppm_for(
    POLICY_TERMS["base_hull_rate_ppm"],
    UseClass.BUSINESS,
    POLICY_TERMS["territorial_limit_code"],
    AUTO_PILOT_BAND,
)
# Two live hulls is short of the five the fleet credit demands, so the gross stands.
AUTO_HULL_PREMIUM_CENTS = c.annual_premium_cents(
    AUTO_AGREED_VALUE_CENTS, AUTO_RATE_PPM, POLICY_TERMS["policy_type"], 2
)
AUTO_UNEXPIRED_DAYS = c.whole_days_between(
    AUTO_COVER_FROM, POLICY_TERMS["effective_to"]
)
AUTO_LINE_CENTS = c.pro_rata_charge_cents(
    AUTO_HULL_PREMIUM_CENTS, AUTO_UNEXPIRED_DAYS, TERM_DAYS
)
AUTO_LATE_LOADING_CENTS = c.ceil_ppm(AUTO_LINE_CENTS, c.LATE_LOADING_PPM)
AUTO_DECLARED_PREMIUM_CENTS = AUTO_LINE_CENTS + AUTO_LATE_LOADING_CENTS

SCHEDULED_HULL_PREMIUM_CENTS = c.annual_premium_cents(
    AGREED_VALUE_CENTS,
    c.rate_ppm_for(
        POLICY_TERMS["base_hull_rate_ppm"],
        HULL_TERMS["use_class"],
        POLICY_TERMS["territorial_limit_code"],
        band_of(NAMED_PILOT, f.CLOCK_BEFORE_INCEPTION),
    ),
    POLICY_TERMS["policy_type"],
    1,
)


def policy_with_an_unreported_hull(api):
    """A bound fleet account carrying one automatically acquired, unreported hull.

    The hull comes on risk on 25 September and is still `PENDING`; the clock is
    then parked in mid-November, which is past the thirty-day reporting deadline
    for a period closing in September but not for one closing at the end of
    October.
    """
    book = fx.bound_policy_with_hull(
        api, clock=f.CLOCK_BEFORE_INCEPTION, automatic_acquisition_enabled=True
    )
    turboprop = fx.make_aircraft(
        api,
        f.turboprop_aircraft_payload(
            registration_mark=AUTO_REGISTRATION_MARK,
            hull_new_value_cents=AUTO_HULL_NEW_VALUE_CENTS,
        ),
    )
    auto_hull = fx.make_schedule(
        api,
        book["policy_id"],
        turboprop["id"],
        book["senior_pilot_id"],
        headers=users.BROKER,
        use_class=UseClass.BUSINESS,
        agreed_value_cents=AUTO_AGREED_VALUE_CENTS,
        effective_from=AUTO_COVER_FROM,
        acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
    )
    assert_field_values(
        auto_hull,
        coverage_status=CoverageStatus.PENDING,
        acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
        rated_pilot_band=AUTO_PILOT_BAND,
        rate_ppm=AUTO_RATE_PPM,
        hull_premium_cents=AUTO_HULL_PREMIUM_CENTS,
        reported_declaration_id=None,
    )
    fx.advance_clock(api, DECLARATION_CLOCK)
    book.update(
        {
            "turboprop": turboprop,
            "auto_hull": auto_hull,
            "auto_hull_id": auto_hull["id"],
        }
    )
    return book


def declare(api, policy_id, period_from, period_to):
    """Report a period as the broker, checking the 201 the PRD promises."""
    return validate_unpaginated(
        api.create_fleet_declaration(
            f.fleet_declaration_payload(
                policy_id, period_from=period_from, period_to=period_to
            ),
            headers=users.BROKER,
        ),
        expected_status=201,
    )


class TestDeclarationPeriodBounds:
    """The reporting period includes both of its bounds, and may report nothing."""

    def test_a_period_starting_one_day_late_reports_the_empty_aggregate(self, api):
        """PRD §3.8: "An empty population is perfectly legal and yields a
        `declared_count` of 0, a `declared_premium_cents` of 0 and a
        `late_loading_cents` of 0."

        Design: Difficulty/boundary_precision_check/declaration_period_inclusive_lower_bound_and_zero_count_aggregate
        """
        book = policy_with_an_unreported_hull(api)

        declaration = declare(
            api, book["policy_id"], EMPTY_PERIOD_FROM, EMPTY_PERIOD_TO
        )

        assert_field_values(
            declaration,
            status=DeclarationStatus.SUBMITTED,
            declared_count=0,
            declared_premium_cents=0,
            late_loading_cents=0,
            late_flag=False,
            reported_schedule_ids=[],
        )

    def test_a_period_starting_exactly_on_the_day_cover_began_reports_the_hull(
        self, api
    ):
        """PRD §3.8: "The reportable population is gathered first: aircraft schedules on
        the declaration's policy whose `acquisition_source` is `AUTOMATIC_ACQUISITION`,
        whose `reported_declaration_id` is still null, whose `coverage_status` is
        `PENDING`, and whose `effective_from` falls at or after `period_from` and at or
        before `period_to`."

        Design: Difficulty/boundary_precision_check/declaration_period_inclusive_lower_bound_and_zero_count_aggregate
        """
        book = policy_with_an_unreported_hull(api)

        declaration = declare(
            api, book["policy_id"], CAPTURING_PERIOD_FROM, CAPTURING_PERIOD_TO
        )

        assert_field_values(
            declaration,
            status=DeclarationStatus.SUBMITTED,
            declared_count=1,
            reported_schedule_ids=[book["auto_hull_id"]],
        )

    def test_the_captured_hull_is_priced_pro_rata_with_the_late_loading_on_top(
        self, api
    ):
        """PRD §3.8: "The `declared_premium_cents` is the line total plus
        `late_loading_cents`."

        Design: Difficulty/boundary_precision_check/declaration_period_inclusive_lower_bound_and_zero_count_aggregate
        """
        book = policy_with_an_unreported_hull(api)
        days_after_the_period = c.whole_days_between(
            CAPTURING_PERIOD_TO, DECLARATION_CLOCK
        )
        assert days_after_the_period > POLICY_TERMS["acquisition_reporting_days"], (
            "the report is filed past the deadline, so the loading applies"
        )

        declaration = declare(
            api, book["policy_id"], CAPTURING_PERIOD_FROM, CAPTURING_PERIOD_TO
        )

        assert_field_values(
            declaration,
            late_flag=True,
            late_loading_cents=AUTO_LATE_LOADING_CENTS,
            declared_premium_cents=AUTO_DECLARED_PREMIUM_CENTS,
        )
        assert declaration["declared_premium_cents"] == (
            AUTO_LINE_CENTS + AUTO_LATE_LOADING_CENTS
        )

    def test_pricing_a_period_mutates_no_hull_and_writes_no_ledger_row(self, api):
        """PRD §3.8: "Creating a declaration mutates no schedule and writes no ledger
        row: it is purely a priced proposal."

        Design: Difficulty/boundary_precision_check/declaration_period_inclusive_lower_bound_and_zero_count_aggregate
        """
        book = policy_with_an_unreported_hull(api)
        rows_before = fx.ledger_rows(api, book["policy_id"])

        declare(api, book["policy_id"], CAPTURING_PERIOD_FROM, CAPTURING_PERIOD_TO)

        hull = fx.fetch_schedule(api, book["auto_hull_id"])
        assert_field_values(
            hull,
            coverage_status=CoverageStatus.PENDING,
            reported_declaration_id=None,
        )
        assert hull["version"] == book["auto_hull"]["version"]
        rows_after = fx.ledger_rows(api, book["policy_id"])
        assert len(rows_after) == len(rows_before) == 1
        assert_ledger_row(
            rows_after[0],
            txn_type=TxnType.INITIAL_PREMIUM,
            amount_cents=SCHEDULED_HULL_PREMIUM_CENTS,
            basis=TxnBasis.ANNUAL,
        )
