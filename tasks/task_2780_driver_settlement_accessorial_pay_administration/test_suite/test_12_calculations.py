"""Arithmetic: which quantity drives which amount, and where the rounding lands.

Each case is chosen so that a plausible wrong formula produces a visibly different integer
number of cents rather than an off-by-one.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    CLERK_HEADERS,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)
from test_helpers.types import (
    AccessorialType,
    ClaimStatus,
    DriverType,
    LineType,
    MileageGuide,
    MovementStatus,
    PayStatus,
    PerDiemMethod,
    ReferenceType,
    RejectReasonCode,
)


def _leased_driver(name: str, legal_name: str, **package_overrides):
    """An ACTIVE leased operator on a PRACTICAL package with both linehaul legs."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name=name,
        **package_overrides,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name=legal_name,
        home_state="TX",
    )
    return package, driver


class TestAccessorialQuantities:
    """Two accessorials whose quantity does not come from the interval at all."""

    def test_stop_off_units_are_read_from_the_load_stop_count(self):
        """A four-stop load pays three extra stops however long the claimed interval is, and
        STOP_OFF needs no paperwork.

        PRD 3.5: "**`STOP_OFF`.** The quantity comes from the load, not from the request:
        `billable_units` is the load's `stop_count` less 1, floored at zero, because the final
        delivery stop is part of the linehaul. Any units the request's own interval might imply are
        ignored. `amount_cents` is `billable_units` multiplied by 5,000 cents per extra stop."
        PRD 3.5: "`documentation_required` is computed at submission as true when
        `accessorial_type` is `DETENTION`, `TARPING` or `BREAKDOWN`, and false for `LAYOVER` and
        `STOP_OFF`."

        Design: Corner/calculations/stop_off_units_come_from_the_load_stop_count_not_the_claim_interval
        """
        fixtures.reset_clock()
        _package, driver = _leased_driver("Leased Stop Off", "Stu Stopoff")
        load = fixtures.delivered_load(driver["id"], stop_count=4)
        assert load["stop_count"] == 4
        fixtures.set_clock("2026-08-05T09:00:00Z")
        claim = fixtures.submit_claim(
            load["id"],
            driver["id"],
            AccessorialType.STOP_OFF,
            "2026-08-04T08:00:00Z",
            "2026-08-04T14:00:00Z",
            None,
            CLERK_HEADERS,
        )
        assert claim["documentation_required"] is False
        assert claim["document_ref"] is None

        approved = validate_success(
            api_client.approve_accessorial_claim(claim["id"], CLERK_HEADERS)
        )

        assert approved["status"] == ClaimStatus.APPROVED
        assert approved["billable_units"] == 3, "stop_count 4 less the final delivery stop"
        assert approved["amount_cents"] == 15000
        assert approved["approved_by_user_id"] == CLERK_HEADERS["X-User-ID"]

    def test_layover_payable_days_are_capped_at_three(self):
        """A layover covering six calendar dates would pay five days after the unpaid first day,
        but the cap holds it to three, so 37500 rather than 62500 or 75000.

        PRD 3.5: "**`LAYOVER`.** Layover is counted in calendar days, not hours. Take the number
        of distinct UTC calendar dates covered by the interval, counting both the `start_at` date
        and the `end_at` date. The first of those days is unpaid, so `billable_units` is that count
        less 1, floored at zero, and then capped at 3 payable days."

        Design: Corner/calculations/layover_payable_days_are_capped_by_layover_max_payable_days
        """
        fixtures.reset_clock()
        _package, driver = _leased_driver("Leased Layover Cap", "Lou Layover")
        load = fixtures.delivered_load(
            driver["id"],
            dispatched_at="2026-08-03T04:00:00Z",
            delivered_at="2026-08-09T06:00:00Z",
            stop_count=1,
        )
        assert load["movement_status"] == MovementStatus.DELIVERED
        fixtures.set_clock("2026-08-09T08:00:00Z")
        claim = fixtures.submit_claim(
            load["id"],
            driver["id"],
            AccessorialType.LAYOVER,
            "2026-08-03T20:00:00Z",
            "2026-08-08T06:00:00Z",
            None,
            CLERK_HEADERS,
        )
        assert claim["documentation_required"] is False

        approved = validate_success(
            api_client.approve_accessorial_claim(claim["id"], CLERK_HEADERS)
        )

        assert approved["status"] == ClaimStatus.APPROVED
        assert approved["billable_units"] == 3, "six dates, minus the unpaid first day, capped at 3"
        assert approved["billable_units"] != 5
        assert approved["billable_units"] != 6
        assert approved["amount_cents"] == 37500
        assert approved["amount_cents"] != 62500, "the cap is applied"
        assert approved["amount_cents"] != 75000, "the first day is unpaid"


class TestHourlyPayIsAdditive:
    """The max() ranges over the two linehaul legs only."""

    def test_the_hourly_leg_is_added_to_the_linehaul_winner_not_compared_against_it(self):
        """300 miles at 58 cents earns 17400 and 470 minutes at 2200 cents an hour earns 17233;
        the statement's gross is their sum, not the larger of the two.

        PRD 3.4: "Two further legs are additive and never enter the comparison. When the
        snapshotted package holds an `HOURLY` component and the load's `hours_worked_minutes` is
        greater than zero, hourly pay is `hours_worked_minutes` multiplied by that component's
        `rate_value` — cents per hour — divided by 60 and rounded half up to whole cents".
        PRD 3.7: "one `HOURLY` line whose `quantity` is the load's `hours_worked_minutes` divided
        by 60 and rounded to two decimal places".

        Design: Corner/calculations/hourly_pay_is_additive_and_never_competes_with_the_linehaul_max
        """
        fixtures.reset_clock()
        package = fixtures.create_package(
            components=[
                factories.per_mile_component(rate_value=58, sequence=1),
                factories.hourly_component(rate_value=2200, sequence=2),
            ],
            activate=True,
            driver_type=DriverType.COMPANY_SOLO,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Company Hourly Additive",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.COMPANY_SOLO,
            per_diem_elected=False,
            legal_name="Hank Hourly",
            home_state="TX",
        )
        load = fixtures.delivered_load(
            driver["id"],
            hours_worked_minutes=470,
            practical_miles=300,
            hhg_miles=290,
            linehaul_revenue_cents=100000,
            stop_count=1,
        )
        assert load["linehaul_pay_cents"] == 17400
        assert load["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert load["hours_worked_minutes"] == 470

        settlement = fixtures.prepared_settlement(driver["id"])

        assert settlement["gross_pay_cents"] == 34633, "17400 plus 17233, not either alone"
        assert settlement["gross_pay_cents"] != 17400
        assert settlement["gross_pay_cents"] != 17233
        assert settlement["line_count"] == 2
        assert settlement["net_pay_cents"] == 34633
        assert settlement["deduction_total_cents"] == 0
        assert settlement["itemization_required"] is False, "a company driver gets no itemization"

        lines = fixtures.read_settlement_lines(settlement["id"])
        by_type = {line["line_type"]: line for line in lines}
        linehaul = by_type[LineType.LINEHAUL_PER_MILE]
        hourly = by_type[LineType.HOURLY]
        assert linehaul["quantity"] == 300
        assert linehaul["rate_value"] == 58
        assert linehaul["amount_cents"] == 17400
        assert round(float(hourly["quantity"]), 2) == 7.83
        assert hourly["rate_value"] == 2200
        assert hourly["amount_cents"] == 17233


class TestPreparationInputSet:
    """The accrual filter is a conjunction, not a date window."""

    def test_only_delivered_accrued_loads_and_approved_claims_reach_the_statement(self):
        """A tendered load and a rejected claim both sit inside the period and both must be
        invisible, so gross is 53580 rather than anything that counts them.

        PRD 3.7: "An eligible load is one whose `driver_id` is the settlement's driver, whose
        `movement_status` is `DELIVERED`, whose `pay_status` is `ACCRUED` — loads that are
        `UNPAID`, `SETTLED` or `ADJUSTED` are all excluded — whose `settlement_id` is null, and
        whose `delivered_at` is at or after `period_start` and strictly before `period_end`."
        PRD 3.7: "An eligible claim is one whose `driver_id` is the settlement's driver, whose
        `status` is `APPROVED` — `SUBMITTED`, `REJECTED` and `PAID` claims are excluded".

        Design: Corner/calculations/prepare_sweeps_only_delivered_accrued_loads_and_approved_claims
        """
        fixtures.reset_clock()
        _package, driver = _leased_driver("Leased Accrual Filter", "Flo Filter")
        settled_load = fixtures.delivered_load(
            driver["id"], stop_count=1, tarp_required=True
        )
        assert settled_load["linehaul_pay_cents"] == 46080
        untouched_load = fixtures.tender_load(driver["id"], stop_count=1)

        fixtures.set_clock("2026-08-05T09:00:00Z")
        paid_claim = fixtures.submit_claim(
            settled_load["id"],
            driver["id"],
            AccessorialType.TARPING,
            "2026-08-04T09:00:00Z",
            "2026-08-04T10:00:00Z",
            "doc://tarp-flo",
            CLERK_HEADERS,
        )
        validate_success(
            api_client.approve_accessorial_claim(paid_claim["id"], CLERK_HEADERS)
        )
        rejected_claim = fixtures.submit_claim(
            settled_load["id"],
            driver["id"],
            AccessorialType.DETENTION,
            "2026-08-04T12:00:00Z",
            "2026-08-04T15:00:00Z",
            "doc://det-flo",
            CLERK_HEADERS,
        )
        validate_success(
            api_client.reject_accessorial_claim(
                rejected_claim["id"],
                factories.claim_reject_payload(RejectReasonCode.SHIPPER_NOT_LIABLE),
                CLERK_HEADERS,
            )
        )

        settlement = fixtures.prepared_settlement(driver["id"])

        assert settlement["line_count"] == 2
        assert settlement["gross_pay_cents"] == 53580
        assert settlement["linehaul_total_cents"] == 46080
        assert settlement["accessorial_total_cents"] == 7500
        lines = fixtures.read_settlement_lines(settlement["id"])
        references = {line["reference_id"] for line in lines}
        assert untouched_load["id"] not in references
        assert rejected_claim["id"] not in references

        skipped = fixtures.read_load(untouched_load["id"])
        assert skipped["movement_status"] == MovementStatus.TENDERED
        assert skipped["pay_status"] == PayStatus.UNPAID
        assert skipped["settlement_id"] is None
        stale = fixtures.read_claim(rejected_claim["id"])
        assert stale["status"] == ClaimStatus.REJECTED
        assert stale["settlement_id"] is None
        swept_load = fixtures.read_load(settled_load["id"])
        assert swept_load["settlement_id"] == settlement["id"]
        assert swept_load["pay_status"] == PayStatus.SETTLED
        swept_claim = fixtures.read_claim(paid_claim["id"])
        assert swept_claim["settlement_id"] == settlement["id"]
        assert swept_claim["status"] == ClaimStatus.PAID


class TestLinehaulPrecisionAndThresholds:
    """Half-up rounding and a strict inequality, each pinned by a pair of loads."""

    def test_the_revenue_percentage_leg_rounds_half_up_at_the_exact_half_cent(self):
        """2500 basis points of 100002 is exactly 25000.5 and must round up to 25001, while
        25000.25 must stay 25000 — a pair that separates half-up from bankers and truncation.

        PRD 3.4: "The **revenue-percentage leg** is the load's `linehaul_revenue_cents` multiplied
        by the `REVENUE_PERCENT` component's `rate_value` in basis points, divided by 10,000 and
        rounded half up to whole cents."
        PRD 3.7: "whose `quantity` is the load's `paid_miles` when that type is
        `LINEHAUL_PER_MILE` or exactly 1 when it is `LINEHAUL_PERCENT`".

        Design: Corner/calculations/revenue_percent_leg_is_round_half_up_at_the_exact_half_cent
        """
        fixtures.reset_clock()
        _package, driver = _leased_driver("Leased Half Cent", "Rita Rounding")
        half_cent = fixtures.delivered_load(
            driver["id"],
            practical_miles=300,
            hhg_miles=290,
            linehaul_revenue_cents=100002,
            stop_count=1,
        )
        quarter_cent = fixtures.delivered_load(
            driver["id"],
            dispatched_at="2026-08-04T08:00:00Z",
            delivered_at="2026-08-04T20:00:00Z",
            practical_miles=300,
            hhg_miles=290,
            linehaul_revenue_cents=100001,
            stop_count=1,
        )

        assert half_cent["linehaul_pay_cents"] == 25001
        assert half_cent["linehaul_pay_cents"] != 25000, "25000.5 rounds half up, not to even"
        assert quarter_cent["linehaul_pay_cents"] == 25000
        assert quarter_cent["linehaul_pay_cents"] != 25001
        for load in (half_cent, quarter_cent):
            assert load["linehaul_line_type"] == LineType.LINEHAUL_PERCENT, (
                "25000-odd beats the 17400 per-mile leg"
            )
            assert load["paid_miles"] == 300
            assert load["short_haul_floor_applied"] is False

    def test_the_short_haul_floor_is_a_strict_inequality_at_250_miles(self):
        """180 guide miles are lifted to the 250-mile floor with the flag set; exactly 250 miles
        pay the identical 14500 with the flag clear.

        PRD 3.4: "A **short-haul floor** then applies: `short_haul_floor_applied` is true only
        when `base_guide_miles` is strictly below 250 miles, and false at exactly 250; when it is
        true, `paid_miles` is raised to 250, and otherwise `paid_miles` equals `base_guide_miles`."

        Design: Corner/calculations/short_haul_floor_is_strict_less_than_min_paid_miles
        """
        fixtures.reset_clock()
        _package, driver = _leased_driver("Leased Short Haul", "Shea Shorthaul")
        below = fixtures.delivered_load(
            driver["id"],
            practical_miles=180,
            hhg_miles=175,
            linehaul_revenue_cents=40000,
            stop_count=1,
        )
        exactly_at = fixtures.delivered_load(
            driver["id"],
            dispatched_at="2026-08-04T08:00:00Z",
            delivered_at="2026-08-04T20:00:00Z",
            practical_miles=250,
            hhg_miles=240,
            linehaul_revenue_cents=40000,
            stop_count=1,
        )

        assert below["base_guide_miles"] == 180
        assert below["paid_miles"] == 250
        assert below["short_haul_floor_applied"] is True
        assert exactly_at["base_guide_miles"] == 250
        assert exactly_at["paid_miles"] == 250
        assert exactly_at["short_haul_floor_applied"] is False, "250 is not strictly below 250"
        assert below["linehaul_pay_cents"] == 14500
        assert exactly_at["linehaul_pay_cents"] == 14500
        for load in (below, exactly_at):
            assert load["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE, (
                "14500 beats the 10000 percentage leg"
            )


class TestPerDiemAllocation:
    """Days on the road are counted once, and the statutory ceiling is rounded first."""

    def test_days_out_count_is_the_union_of_calendar_dates_and_not_the_per_load_sum(self):
        """Two loads of three dates each share 5 August, so the driver was out five days and not
        six, and the 40 percent ceiling then keeps 32960 of the 34500 out of taxable wages.

        PRD 3.7: "`days_out_count` is, in both methods, the number of distinct UTC calendar dates
        in the union — across every load swept into this settlement — of the dates covered by that
        load's `dispatched_at` through `delivered_at`, counting both endpoint dates; a driver who
        was out on the same date under two loads is out one day, not two."
        PRD 3.7: "`per_diem_non_taxable_cents` is the lesser of the gross per diem and that cap,
        and `per_diem_excess_taxable_cents` is whatever the gross per diem exceeded the cap by,
        which stays in taxable wages."

        Design: Corner/calculations/days_out_count_is_the_union_of_calendar_dates_not_the_sum_per_load
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.DAY_BASED,
            escrow_required=False,
            name="Leased Per Diem Union",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=True,
            legal_name="Pam Perdiem",
            home_state="TX",
        )
        first = fixtures.delivered_load(
            driver["id"],
            dispatched_at="2026-08-03T08:00:00Z",
            delivered_at="2026-08-05T18:00:00Z",
            stop_count=1,
        )
        second = fixtures.delivered_load(
            driver["id"],
            dispatched_at="2026-08-05T20:00:00Z",
            delivered_at="2026-08-07T10:00:00Z",
            practical_miles=620,
            hhg_miles=600,
            linehaul_revenue_cents=100000,
            stop_count=1,
        )
        assert first["linehaul_pay_cents"] == 46080
        assert second["linehaul_pay_cents"] == 36320

        settlement = fixtures.prepared_settlement(driver["id"])

        assert settlement["days_out_count"] == 5, "5 August is shared, so it counts once"
        assert settlement["days_out_count"] != 6, "a per-load sum would give 3 + 3"
        assert settlement["gross_pay_cents"] == 82400
        assert settlement["linehaul_total_cents"] == 82400
        assert settlement["per_diem_non_taxable_cents"] == 32960, "the 4000 bps ceiling binds"
        assert settlement["per_diem_non_taxable_cents"] != 34500, (
            "5 days at 6900 exceeds 40 percent of 82400"
        )
        assert settlement["per_diem_excess_taxable_cents"] == 1540
        assert settlement["taxable_wages_cents"] == 49440
        assert (
            settlement["taxable_wages_cents"] + settlement["per_diem_non_taxable_cents"]
            == settlement["gross_pay_cents"]
        )
        assert settlement["line_count"] == 3
        assert settlement["net_pay_cents"] == 82400, "per diem reclassifies, it does not pay"

        per_diem_lines = get_success_data(
            api_client.list_settlement_lines(
                settlement["id"], AUDITOR_HEADERS, {"line_type": LineType.PER_DIEM}
            )
        )
        assert len(per_diem_lines) == 1
        assert per_diem_lines[0]["amount_cents"] == 32960
        assert per_diem_lines[0]["taxable"] is False
        assert per_diem_lines[0]["reference_type"] == ReferenceType.DRIVER
        assert per_diem_lines[0]["reference_id"] == driver["id"]


class TestAccrualOrdering:
    """Print order follows the road, not the keyboard."""

    def test_lines_are_sequenced_by_delivered_at_rather_than_by_creation_order(self):
        """The load tendered second is delivered first, so it takes sequence 1; iterating rows in
        insertion order would put the 620-mile load at the top of the statement.

        PRD 3.7: "Eligible loads are taken in `delivered_at` ascending order, with `created_at`
        ascending as the tie-break."
        PRD 3.7: "Sequence numbers are assigned ascending from 1 and continue from the highest
        sequence already present on the settlement".

        Design: Corner/calculations/settlement_lines_are_sequenced_by_delivered_at_not_by_creation_order
        """
        fixtures.reset_clock()
        _package, driver = _leased_driver("Leased Sequence", "Seb Sequence")
        created_first = fixtures.tender_load(
            driver["id"],
            practical_miles=620,
            hhg_miles=600,
            linehaul_revenue_cents=100000,
            stop_count=1,
        )
        created_second = fixtures.tender_load(driver["id"], stop_count=1)

        fixtures.set_clock("2026-08-03T08:00:00Z")
        fixtures.dispatch(created_second["id"])
        fixtures.set_clock("2026-08-04T18:00:00Z")
        fixtures.deliver(created_second["id"])
        fixtures.set_clock("2026-08-05T08:00:00Z")
        fixtures.dispatch(created_first["id"])
        fixtures.set_clock("2026-08-06T18:00:00Z")
        fixtures.deliver(created_first["id"])

        settlement = fixtures.prepared_settlement(driver["id"])

        assert settlement["line_count"] == 2
        assert settlement["gross_pay_cents"] == 82400
        lines = get_success_data(
            api_client.list_settlement_lines(settlement["id"], AUDITOR_HEADERS)
        )
        by_sequence = {line["sequence"]: line for line in lines}
        assert sorted(by_sequence) == [1, 2]
        assert by_sequence[1]["reference_id"] == created_second["id"], (
            "delivered 4 August, tendered second"
        )
        assert by_sequence[1]["reference_type"] == ReferenceType.LOAD
        assert by_sequence[1]["quantity"] == 780
        assert by_sequence[1]["amount_cents"] == 46080
        assert by_sequence[2]["reference_id"] == created_first["id"]
        assert by_sequence[2]["quantity"] == 620
        assert by_sequence[2]["amount_cents"] == 36320
        assert by_sequence[1]["reference_id"] != created_first["id"], (
            "creation order is not print order"
        )
