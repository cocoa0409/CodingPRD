"""Reads taken at the same logical instant as the write that produced them.

The clock does not move during this test, so nothing here can be explained by time
passing: whatever the prepare derived is either visible to the very next read or it is
not visible at all.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    api_client,
    assert_timestamps_equal,
    fixtures,
    get_success_data,
    validate_success,
)
from test_helpers.types import (
    DriverType,
    LineType,
    MileageGuide,
    PayStatus,
    PerDiemMethod,
    ReferenceType,
    SettlementStatus,
)

LINEHAUL_780_CENTS = 46080


def _draft_settlement_at_the_settle_instant():
    """One delivered, still-ACCRUED load worth 46,080 cents and a DRAFT settlement over the
    period that contains it, with the clock parked on the preparation instant."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        name="Leased Immediate Read",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Imo Immediate",
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1, tarp_required=False)
    assert load["pay_status"] == PayStatus.ACCRUED
    assert load["settlement_id"] is None
    assert load["paid_miles"] == fixtures.REF_PRACTICAL_MILES
    assert load["linehaul_pay_cents"] == LINEHAUL_780_CENTS

    fixtures.set_clock(fixtures.TS_SETTLE)
    settlement = fixtures.open_settlement(driver["id"])
    assert settlement["status"] == SettlementStatus.DRAFT
    assert settlement["line_count"] == 0
    return {"driver": driver, "load": load, "settlement": settlement}


class TestPreparationIsVisibleToTheVeryNextRead:
    """Every field the preparation derives — on the settlement, on its lines and on the
    load — is readable at the same logical instant, with no retry and no polling."""

    def test_the_settlement_its_lines_and_the_load_all_read_back_prepared_immediately(self):
        """The prepare's own response already says PREPARED, and the reads that follow it at the
        identical clock value agree with it field for field: one linehaul line of 780 miles for
        46,080 cents, a net that equals the gross because nothing was deducted, and a load whose
        pay axis has already been closed against this statement.

        PRD 3.7: "A successful preparation advances the settlement `DRAFT` → `PREPARED`, records
        the acting `X-User-ID` as `prepared_by_user_id`, stamps `prepared_at` from the logical
        clock, writes `line_count`, `itemization_required` and every total from
        `linehaul_total_cents` through `net_pay_cents`, and increments the settlement's `version`
        by 1."
        PRD 3.7: "every swept load moves on the pay axis `ACCRUED` → `SETTLED` with its
        `settlement_id` set to this settlement"
        PRD 3.7: "one linehaul line typed with the load's own `linehaul_line_type`, whose
        `quantity` is the load's `paid_miles` when that type is `LINEHAUL_PER_MILE`"

        Design: Corner/consistency_model/prepare_side_effects_are_readable_at_the_same_logical_instant
        """
        env = _draft_settlement_at_the_settle_instant()
        settlement_id = env["settlement"]["id"]

        prepared = validate_success(
            api_client.prepare_settlement(settlement_id, None, CLERK_HEADERS)
        )

        assert prepared["status"] == SettlementStatus.PREPARED, (
            "the write's own response body already carries the derived status"
        )

        read_back = fixtures.read_settlement(settlement_id)
        assert read_back["status"] == SettlementStatus.PREPARED
        assert_timestamps_equal(read_back["prepared_at"], fixtures.TS_SETTLE, "prepared_at")
        assert read_back["line_count"] == 1
        assert read_back["linehaul_total_cents"] == LINEHAUL_780_CENTS
        assert read_back["gross_pay_cents"] == LINEHAUL_780_CENTS
        assert read_back["deduction_total_cents"] == 0
        assert read_back["net_pay_cents"] == LINEHAUL_780_CENTS
        assert read_back["version"] == env["settlement"]["version"] + 1

        lines = fixtures.read_settlement_lines(settlement_id)
        assert len(lines) == 1
        assert lines[0]["line_type"] == LineType.LINEHAUL_PER_MILE
        assert lines[0]["quantity"] == fixtures.REF_PRACTICAL_MILES
        assert lines[0]["amount_cents"] == LINEHAUL_780_CENTS
        assert lines[0]["reference_type"] == ReferenceType.LOAD
        assert lines[0]["reference_id"] == env["load"]["id"]

        load = fixtures.read_load(env["load"]["id"])
        assert load["pay_status"] == PayStatus.SETTLED, (
            "the load's own axis moved inside the prepare, not on a later pass"
        )
        assert load["settlement_id"] == settlement_id

    def test_the_ytd_accumulators_stay_at_zero_and_a_repeated_read_does_not_creep(self):
        """Immediate does not mean eventually-more: PREPARED contributes nothing to the
        year-to-date figures, so they read zero at this instant, and reading the statement twice
        at the same clock value returns the same record rather than a settling one.

        PRD 2.11: "The year-to-date accumulators `ytd_gross_pay_cents`, `ytd_taxable_wages_cents`
        and `ytd_per_diem_non_taxable_cents` are the sums of `gross_pay_cents`,
        `taxable_wages_cents` and `per_diem_non_taxable_cents` over that driver's settlements
        whose `status` is `APPROVED` or `PAID`; settlements in `DRAFT`, `PREPARED` or `VOIDED`
        contribute nothing."
        PRD 2.5: "It keeps a **logical clock** that begins at exactly `2026-08-01T00:00:00Z` when
        the server starts and moves only when an operator sets it."

        Design: Corner/consistency_model/prepare_side_effects_are_readable_at_the_same_logical_instant
        """
        env = _draft_settlement_at_the_settle_instant()
        settlement_id = env["settlement"]["id"]

        validate_success(api_client.prepare_settlement(settlement_id, None, CLERK_HEADERS))

        driver = fixtures.read_driver(env["driver"]["id"])
        assert driver["ytd_gross_pay_cents"] == 0
        assert driver["ytd_taxable_wages_cents"] == 0
        assert driver["ytd_per_diem_non_taxable_cents"] == 0

        first = get_success_data(api_client.get_settlement(settlement_id, ADMIN_HEADERS))
        second = get_success_data(api_client.get_settlement(settlement_id, ADMIN_HEADERS))

        assert second == first, "two reads at one logical instant return the identical record"
        assert second["gross_pay_cents"] == LINEHAUL_780_CENTS
        assert fixtures.read_driver(env["driver"]["id"])["ytd_gross_pay_cents"] == 0, (
            "a second driver read at the same clock value does not creep upward"
        )
