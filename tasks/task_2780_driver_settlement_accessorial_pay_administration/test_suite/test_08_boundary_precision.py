"""Exact boundaries, both on a quantity threshold and on a temporal window.

The interesting values are the ones that land precisely on a limit: 120 minutes of
detention, and a delivery stamped exactly on a period edge.
"""

from test_helpers import (
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    assert_timestamps_equal,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    DETENTION_FREE_MINUTES,
    DETENTION_INCREMENT_CENTS,
    DETENTION_INCREMENT_MINUTES,
)
from test_helpers.types import (
    ClaimStatus,
    DriverType,
    LineType,
    MileageGuide,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
)


def _detention_environment():
    """One delivered load carrying three documented detention tickets of exactly 120, 134 and
    135 minutes, spaced so the 15-minute buffer never makes them collide."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Detention Boundary",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Mona Meter",
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    fixtures.set_clock("2026-08-06T09:00:00Z")
    exactly_free = fixtures.submit_claim(
        load["id"],
        driver["id"],
        "DETENTION",
        "2026-08-05T00:00:00Z",
        "2026-08-05T02:00:00Z",
        "doc://det-120",
        CLERK_HEADERS,
    )
    one_short = fixtures.submit_claim(
        load["id"],
        driver["id"],
        "DETENTION",
        "2026-08-05T04:00:00Z",
        "2026-08-05T06:14:00Z",
        "doc://det-134",
        CLERK_HEADERS,
    )
    first_payable = fixtures.submit_claim(
        load["id"],
        driver["id"],
        "DETENTION",
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:15:00Z",
        "doc://det-135",
        CLERK_HEADERS,
    )
    return {
        "driver": driver,
        "load": load,
        "exactly_free": exactly_free,
        "one_short": one_short,
        "first_payable": first_payable,
    }


class TestDetentionFreeAllowanceBoundary:
    """The first payable minute is the 135th, not the 121st."""

    def test_exactly_the_free_allowance_earns_nothing_and_cannot_be_approved(self):
        """A ticket of exactly 120 minutes sits on the allowance, so billable minutes are zero
        and the approval is refused rather than paying zero.

        PRD 3.5: "The first 120 minutes at the dock are free. Billable minutes are the total
        minutes less 120, or zero when the total does not exceed the free allowance."
        PRD 3.5: "A claim whose computed `amount_cents` is exactly zero is not an approvable
        accessorial".

        Design: Difficulty/boundary_precision_check/detention_free_allowance_exact_boundary
        """
        env = _detention_environment()

        response = api_client.approve_accessorial_claim(
            env["exactly_free"]["id"], CLERK_HEADERS
        )

        validate_error(response, ApiErrorId.ZERO_VALUE_ACCESSORIAL, 422)
        claim = fixtures.read_claim(env["exactly_free"]["id"])
        assert claim["status"] == ClaimStatus.SUBMITTED
        assert claim["billable_units"] == 0
        assert claim["amount_cents"] == 0

    def test_fourteen_billable_minutes_truncate_to_zero_increments(self):
        """134 minutes leaves 14 billable minutes, which is one minute short of a whole
        increment, and truncation toward zero means it pays nothing at all.

        PRD 3.5: "`billable_units` is the count of whole completed 15-minute increments in those
        billable minutes, truncated toward zero and never rounded up."

        Design: Difficulty/boundary_precision_check/detention_free_allowance_exact_boundary
        """
        env = _detention_environment()

        response = api_client.approve_accessorial_claim(env["one_short"]["id"], CLERK_HEADERS)

        validate_error(response, ApiErrorId.ZERO_VALUE_ACCESSORIAL, 422)
        claim = fixtures.read_claim(env["one_short"]["id"])
        assert claim["status"] == ClaimStatus.SUBMITTED
        assert claim["billable_units"] == 0
        assert claim["amount_cents"] == 0
        assert 134 - DETENTION_FREE_MINUTES < DETENTION_INCREMENT_MINUTES

    def test_one_hundred_and_thirty_five_minutes_is_the_first_payable_ticket(self):
        """One more minute completes the first increment, so the claim is approvable and worth
        exactly one increment.

        PRD 3.5: "`amount_cents` is `billable_units` multiplied by 500 cents per increment, and
        the whole detention charge is capped at 20,000 cents — the lesser of the computed amount
        and the cap."
        PRD 3.5: "Approval computes `billable_units` and `amount_cents`, advances the claim
        `SUBMITTED` → `APPROVED`, records the acting `X-User-ID` as `approved_by_user_id`, and
        increments the claim's `version` by 1."

        Design: Difficulty/boundary_precision_check/detention_free_allowance_exact_boundary
        """
        env = _detention_environment()

        approved = validate_success(
            api_client.approve_accessorial_claim(env["first_payable"]["id"], CLERK_HEADERS)
        )

        assert approved["status"] == ClaimStatus.APPROVED
        assert approved["billable_units"] == 1
        assert approved["amount_cents"] == DETENTION_INCREMENT_CENTS
        assert approved["amount_cents"] == 500
        assert approved["version"] == env["first_payable"]["version"] + 1


EDGE_INSTANT = "2026-08-18T00:00:00Z"
EARLY_PERIOD = ("2026-08-11T00:00:00Z", EDGE_INSTANT)
LATE_PERIOD = (EDGE_INSTANT, "2026-08-25T00:00:00Z")


def _edge_delivery_environment():
    """A load delivered at exactly 2026-08-18T00:00:00Z with two adjacent DRAFT settlements,
    one ending at that instant and one starting at it."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Period Edge",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Ned Nightline",
        home_state="TX",
    )
    load = fixtures.delivered_load(
        driver["id"],
        dispatched_at="2026-08-17T08:00:00Z",
        delivered_at=EDGE_INSTANT,
        stop_count=1,
        linehaul_revenue_cents=92800,
        practical_miles=400,
        hhg_miles=400,
    )
    assert_timestamps_equal(load["delivered_at"], EDGE_INSTANT, "load.delivered_at")
    assert load["linehaul_pay_cents"] == 23200

    fixtures.set_clock("2026-08-25T09:00:00Z")
    early = fixtures.open_settlement(driver["id"], EARLY_PERIOD[0], EARLY_PERIOD[1])
    late = fixtures.open_settlement(driver["id"], LATE_PERIOD[0], LATE_PERIOD[1])
    return {"driver": driver, "load": load, "early": early, "late": late}


class TestSettlementPeriodHalfOpenBoundary:
    """A delivery exactly on the edge belongs to the later period, never to both."""

    def test_the_period_ending_at_the_delivery_instant_finds_nothing_to_settle(self):
        """period_end is exclusive, so the load stamped exactly at it is not eligible and the
        sweep has nothing at all to settle.

        PRD 3.7: "The window is half-open in both senses that matter: a load delivered exactly at
        `period_start` belongs to this period, and a load delivered exactly at `period_end`
        belongs to the next one."
        PRD 3.7: "If there is no eligible load, no eligible claim, and no `RETRO_CORRECTION` line
        already swept onto the settlement, there is nothing to settle and the prepare is rejected
        with `ERR_NO_SETTLEABLE_ACTIVITY` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/settlement_period_half_open_boundary
        """
        env = _edge_delivery_environment()

        response = api_client.prepare_settlement(env["early"]["id"], {}, CLERK_HEADERS)

        validate_error(response, ApiErrorId.NO_SETTLEABLE_ACTIVITY, 422)
        early = fixtures.read_settlement(env["early"]["id"])
        assert early["status"] == SettlementStatus.DRAFT
        assert early["line_count"] == 0
        assert early["gross_pay_cents"] == 0
        load = fixtures.read_load(env["load"]["id"])
        assert load["pay_status"] == PayStatus.ACCRUED
        assert load["settlement_id"] is None

    def test_the_period_starting_at_the_delivery_instant_sweeps_the_load(self):
        """period_start is inclusive, so the same load falls into the later period and is priced
        there in full.

        PRD 3.7: "whose `delivered_at` is at or after `period_start` and strictly before
        `period_end`."

        Design: Difficulty/boundary_precision_check/settlement_period_half_open_boundary
        """
        env = _edge_delivery_environment()

        prepared = validate_success(
            api_client.prepare_settlement(env["late"]["id"], {}, CLERK_HEADERS)
        )

        assert prepared["status"] == SettlementStatus.PREPARED
        assert prepared["line_count"] == 1
        assert prepared["gross_pay_cents"] == 23200
        assert prepared["net_pay_cents"] == 23200
        lines = fixtures.read_settlement_lines(env["late"]["id"])
        assert [line["line_type"] for line in lines] == [LineType.LINEHAUL_PER_MILE]
        load = fixtures.read_load(env["load"]["id"])
        assert load["pay_status"] == PayStatus.SETTLED
        assert load["settlement_id"] == env["late"]["id"]
        assert_timestamps_equal(load["delivered_at"], EDGE_INSTANT, "load.delivered_at")

    def test_the_edge_delivery_is_claimed_by_exactly_one_of_the_two_periods(self):
        """Sweeping the later period first does not make the load eligible again for the earlier
        one; the boundary assigns it to exactly one statement.

        PRD 3.7: "An eligible load is one whose `driver_id` is the settlement's driver, whose
        `movement_status` is `DELIVERED`, whose `pay_status` is `ACCRUED` — loads that are
        `UNPAID`, `SETTLED` or `ADJUSTED` are all excluded — whose `settlement_id` is null".

        Design: Difficulty/boundary_precision_check/settlement_period_half_open_boundary
        """
        env = _edge_delivery_environment()
        fixtures.prepare(env["late"]["id"])

        response = api_client.prepare_settlement(env["early"]["id"], {}, CLERK_HEADERS)

        validate_error(response, ApiErrorId.NO_SETTLEABLE_ACTIVITY, 422)
        assert fixtures.read_settlement(env["early"]["id"])["line_count"] == 0
        assert fixtures.read_settlement(env["late"]["id"])["line_count"] == 1
