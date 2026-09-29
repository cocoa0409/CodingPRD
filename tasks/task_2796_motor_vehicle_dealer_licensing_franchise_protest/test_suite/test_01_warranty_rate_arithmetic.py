"""Warranty reimbursement rate disputes: the two rival rate computations,
the qualifying-sample boundary, and the order in which a rate dispute's
safety and fiscal checks fire.
"""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import BOARD_ADMIN, make_dealer_headers


def _mixed_weight_sample():
    """Seven repair orders: five qualify, one is a sub-half-hour customer-paid
    line and one is warranty work. Charge-per-hour differs sharply from
    hours-weighted pooling, so the two computations cannot coincide."""
    return [
        f.repair_order_line(12000, 1.0),
        f.repair_order_line(9000, 1.5),
        f.repair_order_line(10000, 2.0),
        f.repair_order_line(8000, 0.5),
        f.repair_order_line(6000, 2.0),
        f.repair_order_line(5000, 0.4),
        f.repair_order_line(7000, 1.0, "WARRANTY"),
    ]


def _four_qualifying_sample():
    """The same orders minus one qualifying line: four qualify."""
    return [
        f.repair_order_line(12000, 1.0),
        f.repair_order_line(9000, 1.5),
        f.repair_order_line(10000, 2.0),
        f.repair_order_line(8000, 0.5),
        f.repair_order_line(5000, 0.4),
    ]


class TestDeclaredVersusCounterRate:
    def test_declared_rate_rounds_each_order_before_averaging(self, api):
        """PRD 3.8: "divide each qualifying line's `labor_charge_cents` by its
        `labor_hours`, round each of those per-order rates half up to a whole
        cent *first*, then average the rounded per-order rates by summing them
        and dividing by how many there are, rounding that average half up to a
        whole cent." The five qualifying orders yield 12000, 6000, 5000, 16000
        and 3000 cents per hour, whose mean is 8400 — the short high-charge
        order carries the same weight as the long cheap one.

        Design: Difficulty/dual_variant_calc/warranty_rate_per_order_mean_vs_aggregate_weighted
        """
        env = fx.setup_licensed_dealer()
        dealer, manufacturer = env["dealer"], env["manufacturer"]

        response = api.create_warranty_rate_dispute(
            f.rate_dispute_payload(dealer["id"], manufacturer["id"], _mixed_weight_sample()),
            make_dealer_headers(dealer["id"]),
        )
        dispute = get_success_data(response, expected_status=201)

        assert dispute["qualifying_line_count"] == 5
        assert dispute["declared_rate_cents"] == 8400
        assert dispute["status"] == "FILED"
        assert dispute["filed_on"] == "2026-09-01"
        assert dispute["counter_rate_cents"] is None
        assert dispute["spread_pct"] is None
        assert dispute["excluded_line_indexes"] == []

    def test_counter_rate_pools_once_and_the_board_splits_the_wide_spread(self, api):
        """PRD 3.8: "sum all the `labor_charge_cents` and sum all the
        `labor_hours`, divide the first sum by the second *once*, and round half
        up to a whole cent only at the very end." Pooling 45000 cents over 7.0
        hours gives 6429, against a declared 8400 — a spread of 30.66 percent.
        PRD 3.8: "otherwise the board splits the difference, and
        `approved_rate_cents` is the sum of `declared_rate_cents` and
        `counter_rate_cents` divided by two, rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/warranty_rate_per_order_mean_vs_aggregate_weighted
        """
        env = fx.setup_licensed_dealer()
        dealer, manufacturer = env["dealer"], env["manufacturer"]
        dispute = fx.file_rate_dispute(
            dealer["id"], manufacturer["id"], _mixed_weight_sample())

        answered = fx.answer_rate_dispute(
            dispute["id"], manufacturer["id"], "REBUT", excluded_line_indexes=[])
        assert answered["status"] == "UNDER_REVIEW"
        assert answered["counter_rate_cents"] == 6429
        assert answered["declared_rate_cents"] != answered["counter_rate_cents"]
        assert answered["spread_pct"] == pytest.approx(30.66, abs=0.01)

        decided = fx.decide_rate_dispute(dispute["id"], "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["approved_rate_cents"] == 7415
        assert decided["decided_on"] == "2026-09-01"
        assert decided["effective_on"] == "2026-10-01"

        after = fx.read_dealer(dealer["id"])
        assert after["approved_warranty_labor_rate_cents"] == 7415
        assert after["version"] == dealer["version"] + 1


class TestQualifyingSampleBoundary:
    def test_four_qualifying_lines_are_refused_and_leave_no_dispute(self, api):
        """PRD 3.8: "A sample carrying fewer than 5 qualifying lines is refused
        with `ERR_INSUFFICIENT_RO_SAMPLE`." The sub-half-hour order is excluded
        by PRD 3.8: "warranty work, internal work and sub-half-hour lines are
        excluded from every computation in this section, whether or not the
        franchisor ever names them." Five submitted orders, four qualifying.

        Design: Difficulty/boundary_precision_check/warranty_sample_exactly_five_qualifying_lines_accepted
        """
        env = fx.setup_licensed_dealer()
        dealer, manufacturer = env["dealer"], env["manufacturer"]

        response = api.create_warranty_rate_dispute(
            f.rate_dispute_payload(dealer["id"], manufacturer["id"], _four_qualifying_sample()),
            make_dealer_headers(dealer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_RO_SAMPLE.value)

        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 0
        _, meta = validate_paginated(api.list_warranty_rate_disputes(BOARD_ADMIN))
        assert meta["total_count"] == 0

    def test_exactly_five_qualifying_lines_are_accepted(self, api):
        """PRD 3.8: "`qualifying_line_count` is the number of qualifying lines
        across the whole sample and is frozen at filing". Adding a fifth
        qualifying order to the refused sample — plus a warranty order that
        never counts — carries the sample over the statutory floor of five.

        Design: Difficulty/boundary_precision_check/warranty_sample_exactly_five_qualifying_lines_accepted
        """
        env = fx.setup_licensed_dealer()
        dealer, manufacturer = env["dealer"], env["manufacturer"]

        response = api.create_warranty_rate_dispute(
            f.rate_dispute_payload(dealer["id"], manufacturer["id"], _mixed_weight_sample()),
            make_dealer_headers(dealer["id"]),
        )
        dispute = get_success_data(response, expected_status=201)

        assert dispute["qualifying_line_count"] == 5
        assert dispute["declared_rate_cents"] == 8400
        assert dispute["status"] == "FILED"
        assert dispute["filed_on"] == "2026-09-01"
        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 1


class TestRateDisputeCheckOrder:
    def test_lapsed_franchisor_pre_empts_the_rate_sufficiency_check(self, api):
        """PRD 3.8: "The dealership must be `LICENSED`
        (`ERR_DEALER_LICENSE_NOT_ACTIVE`), the franchisor must be `REGISTERED`
        (`ERR_MANUFACTURER_REGISTRATION_LAPSED`)". PRD 2.10 places party
        standing ahead of fiscal sufficiency: "Fiscal and evidentiary
        sufficiency**, last of all, in this order: repair-order sample size
        (`ERR_INSUFFICIENT_RO_SAMPLE`), the declared rate exceeding the posted
        rate (`ERR_RATE_NOT_ABOVE_POSTED`)". The sample here also fails the
        rate test, so only the ordering can decide the response.

        Design: Difficulty/priority_pair_validation_conflict/warranty_dispute_lapsed_manufacturer_safety_beats_rate_fiscal
        """
        env = fx.setup_licensed_dealer(
            manufacturer_overrides={"state_registration_status": "LAPSED"})
        dealer, manufacturer = env["dealer"], env["manufacturer"]
        assert manufacturer["posted_warranty_labor_rate_cents"] == 6000

        response = api.create_warranty_rate_dispute(
            f.rate_dispute_payload(
                dealer["id"], manufacturer["id"],
                f.qualifying_lines(count=5, labor_charge_cents=4200, labor_hours=1.0)),
            make_dealer_headers(dealer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_MANUFACTURER_REGISTRATION_LAPSED.value)

        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 0
        _, meta = validate_paginated(api.list_warranty_rate_disputes(BOARD_ADMIN))
        assert meta["total_count"] == 0

    def test_registered_franchisor_reaches_the_posted_rate_check(self, api):
        """PRD 3.8: "a declared rate at or below the posted rate is refused with
        `ERR_RATE_NOT_ABOVE_POSTED`." With the franchisor's standing intact the
        very same sample — five orders at 4200 cents for one hour against a
        posted 6000 — falls through to the fiscal test instead.

        Design: Difficulty/priority_pair_validation_conflict/warranty_dispute_lapsed_manufacturer_safety_beats_rate_fiscal
        """
        env = fx.setup_licensed_dealer()
        dealer, manufacturer = env["dealer"], env["manufacturer"]
        assert manufacturer["state_registration_status"] == "REGISTERED"

        response = api.create_warranty_rate_dispute(
            f.rate_dispute_payload(
                dealer["id"], manufacturer["id"],
                f.qualifying_lines(count=5, labor_charge_cents=4200, labor_hours=1.0)),
            make_dealer_headers(dealer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RATE_NOT_ABOVE_POSTED.value)

        assert fx.read_manufacturer(manufacturer["id"])["open_dispute_count"] == 0
        _, meta = validate_paginated(api.list_warranty_rate_disputes(BOARD_ADMIN))
        assert meta["total_count"] == 0
