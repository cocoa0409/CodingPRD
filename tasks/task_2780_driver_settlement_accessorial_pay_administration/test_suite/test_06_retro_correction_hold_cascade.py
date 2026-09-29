"""The depth-four cascade rooted at one dispute resolution.

Upholding a mileage dispute on a paid load walks from the dispute to a correction, from
the correction to the driver's pending total, and from that total to a hold that refuses a
completely different settlement.
"""

from test_helpers import (
    APPROVER_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    fixtures,
    make_driver_headers,
    validate_error,
    validate_success,
)
from test_helpers.constants import RETRO_HOLD_THRESHOLD_CENTS
from test_helpers.types import (
    CorrectionStatus,
    CorrectionType,
    DisputeStatus,
    DriverType,
    MileageGuide,
    MovementStatus,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
)

CLAIMED_MILES = 1600
REGRADE_DELTA_CENTS = 50020
SECOND_PERIOD_START = "2026-08-11T00:00:00Z"
SECOND_PERIOD_END = "2026-08-18T00:00:00Z"


def _cascade_environment():
    """One paid load under an UNDER_REVIEW mileage dispute claiming 1600 practical miles, a
    second delivered-and-accrued load, and a DRAFT settlement waiting to sweep it."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Cascade",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Ida Interline",
        home_state="TX",
    )
    first_load = fixtures.delivered_load(driver["id"], stop_count=1)
    assert first_load["linehaul_pay_cents"] == 46080

    fixtures.set_clock(fixtures.TS_SETTLE)
    first_settlement = fixtures.open_settlement(driver["id"])
    fixtures.prepare(first_settlement["id"])
    fixtures.approve(first_settlement["id"])
    fixtures.pay(first_settlement["id"], "ACH-2026-08-10-0002")

    second_load = fixtures.delivered_load(
        driver["id"],
        dispatched_at="2026-08-12T08:00:00Z",
        delivered_at="2026-08-12T18:00:00Z",
        stop_count=1,
        linehaul_revenue_cents=92800,
        practical_miles=400,
        hhg_miles=400,
    )
    assert second_load["linehaul_pay_cents"] == 23200
    assert second_load["pay_status"] == PayStatus.ACCRUED

    dispute = fixtures.file_mileage_dispute(
        driver["id"],
        first_load["id"],
        MileageGuide.PRACTICAL,
        CLAIMED_MILES,
        headers=make_driver_headers(driver["id"]),
        # PRD 3.9: on a MILEAGE dispute `settlement_id`, `claimed_amount_cents` and
        # `disputed_line_type` must all be null; the correction's origin settlement is
        # taken from the load's own `settlement_id` instead.
        narrative="Load was rerouted around a closure; practical mileage should be 1600.",
    )
    fixtures.review(dispute["id"], CLERK_HEADERS)

    fixtures.set_clock("2026-08-18T09:00:00Z")
    second_settlement = fixtures.open_settlement(
        driver["id"], SECOND_PERIOD_START, SECOND_PERIOD_END
    )
    return {
        "driver": driver,
        "first_load": first_load,
        "first_settlement": first_settlement,
        "second_load": second_load,
        "second_settlement": second_settlement,
        "dispute": dispute,
    }


class TestUpheldMileageDisputeCascadesIntoASettlementHold:
    """One call, four hops, and a failure that surfaces three entities away."""

    def test_resolution_flips_the_dispute_and_mints_the_correction_and_adjusts_the_load(self):
        """Hops one and two: the dispute becomes UPHELD, a PENDING correction of +50020 is
        created, and the paid load's money axis moves to ADJUSTED.

        PRD 3.9: "Hop 1: the load's pay fields are rewritten exactly as in branch A and its pay
        axis moves `SETTLED` → `ADJUSTED`, while `movement_status` stays `DELIVERED` and is not
        touched."
        PRD 3.9: "`delta_gross_cents` is the new figure less the old one, and it is negative on
        a down-grade."

        Design: Difficulty/transitive_cascade/mileage_uphold_depth4_settlement_hold_cascade
        """
        env = _cascade_environment()

        upheld = validate_success(
            api_client.resolve_dispute(
                env["dispute"]["id"],
                {"outcome": "UPHOLD", "resolution_note": "Detour confirmed by dispatch log."},
                APPROVER_HEADERS,
            )
        )

        assert upheld["status"] == DisputeStatus.UPHELD
        correction = fixtures.read_correction(upheld["resolution_correction_id"])
        assert correction["status"] == CorrectionStatus.PENDING
        assert correction["correction_type"] == CorrectionType.MILEAGE_REGRADE
        assert correction["delta_gross_cents"] == REGRADE_DELTA_CENTS
        assert correction["origin_settlement_id"] == env["first_settlement"]["id"]

        load = fixtures.read_load(env["first_load"]["id"])
        assert load["pay_status"] == PayStatus.ADJUSTED
        assert load["movement_status"] == MovementStatus.DELIVERED

    def test_the_correction_accumulates_onto_the_driver_and_trips_the_hold(self):
        """Hops three and four: the insert recomputes the driver's pending total, and that
        total, being above 50000 cents, recomputes the hold flag to true.

        PRD 3.9: "Hop 3: that insert itself recomputes the driver's
        `pending_retro_correction_cents`."
        PRD 3.9: "Hop 4: the new `pending_retro_correction_cents` itself recomputes the driver's
        `settlement_hold`, which is true whenever the absolute value of
        `pending_retro_correction_cents` exceeds 50,000 cents and false otherwise".

        Design: Difficulty/transitive_cascade/mileage_uphold_depth4_settlement_hold_cascade
        """
        env = _cascade_environment()
        before = fixtures.read_driver(env["driver"]["id"])
        assert before["pending_retro_correction_cents"] == 0
        assert before["settlement_hold"] is False

        fixtures.resolve(
            env["dispute"]["id"],
            "UPHOLD",
            APPROVER_HEADERS,
            resolution_note="Detour confirmed by dispatch log.",
        )

        after = fixtures.read_driver(env["driver"]["id"])
        assert after["pending_retro_correction_cents"] == REGRADE_DELTA_CENTS
        assert after["pending_retro_correction_cents"] > RETRO_HOLD_THRESHOLD_CENTS
        assert after["settlement_hold"] is True
        assert after["version"] > before["version"]

    def test_the_hold_refuses_a_different_settlement_three_entities_away(self):
        """The final hop lands on an unrelated operation: preparing the next period's
        settlement, which has its own eligible load, is refused while the hold stands.

        PRD 3.7: "only while that driver's `settlement_hold` is false — a held driver is refused
        with `ERR_SETTLEMENT_HOLD_ACTIVE` (HTTP 409)".
        PRD 3.9: "and once it is true, no new settlement for that driver can be prepared."

        Design: Difficulty/transitive_cascade/mileage_uphold_depth4_settlement_hold_cascade
        """
        env = _cascade_environment()
        fixtures.resolve(
            env["dispute"]["id"],
            "UPHOLD",
            APPROVER_HEADERS,
            resolution_note="Detour confirmed by dispatch log.",
        )

        response = api_client.prepare_settlement(
            env["second_settlement"]["id"], {}, CLERK_HEADERS
        )

        validate_error(response, ApiErrorId.SETTLEMENT_HOLD_ACTIVE, 409)
        blocked = fixtures.read_settlement(env["second_settlement"]["id"])
        assert blocked["status"] == SettlementStatus.DRAFT
        assert blocked["line_count"] == 0
        assert blocked["gross_pay_cents"] == 0
        second_load = fixtures.read_load(env["second_load"]["id"])
        assert second_load["pay_status"] == PayStatus.ACCRUED
        assert second_load["settlement_id"] is None
