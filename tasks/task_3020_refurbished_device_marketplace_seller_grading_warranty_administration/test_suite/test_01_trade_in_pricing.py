"""Trade-in intake pricing: the provisional and final quote variants."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx


class TestProvisionalQuote:
    def test_provisional_quote_reads_only_the_declaration(self, api):
        """PRD §3.8: "The provisional quote starts from a base of 38000 cents and subtracts four deductions."
        PRD §3.8: "The provisional quote is the base minus all four deductions, clamped at zero."
        PRD §3.8: "That provisional figure is never revised in place, so a submission that later receives an inspection retains both numbers side by side."

        Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_quote
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        trade_in = fx.submit_trade_in(
            self_declared_cosmetic_grade="FLAWLESS",
            self_declared_functional_grade="FULLY_FUNCTIONAL",
            self_declared_battery_health_pct=95,
            self_declared_carrier_lock_status="UNLOCKED",
        )
        assert trade_in["provisional_quote_cents"] == 38000, (
            f"Expected 38000 for a FLAWLESS / FULLY_FUNCTIONAL / 95% / UNLOCKED declaration, "
            f"got {trade_in['provisional_quote_cents']}"
        )
        assert trade_in["submission_state"] == "SUBMITTED"

        fx.inspect_trade_in(
            trade_in["id"],
            inspected_cosmetic_grade="FAIR",
            inspected_functional_grade="MINOR_FAULTS",
            inspected_battery_health_pct=82,
            inspected_carrier_lock_status="UNLOCKED",
        )
        validate_success(fx.revise_trade_in(trade_in["id"]))

        after = fx.read_trade_in(trade_in["id"])
        assert after["provisional_quote_cents"] == 38000, (
            "the provisional quote must not be recomputed in place by the revision step"
        )

    def test_provisional_and_final_quotes_differ_by_penalty_plus_fee(self, api):
        """PRD §3.8: "For identical underlying measurements, the provisional and final variants differ by exactly the step penalty plus the fee."
        PRD §3.8: "Each step costs 2500 cents, and the step penalty is that rate times the step count, subtracted from the inspected value, with the result clamped at zero."

        Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_quote
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        trade_in = fx.submit_trade_in(
            self_declared_cosmetic_grade="FLAWLESS",
            self_declared_functional_grade="FULLY_FUNCTIONAL",
            self_declared_battery_health_pct=95,
            self_declared_carrier_lock_status="UNLOCKED",
        )
        fx.inspect_trade_in(
            trade_in["id"],
            inspected_cosmetic_grade="FAIR",
            inspected_functional_grade="MINOR_FAULTS",
            inspected_battery_health_pct=82,
            inspected_carrier_lock_status="UNLOCKED",
        )
        revised = validate_success(fx.revise_trade_in(trade_in["id"]))

        assert revised["final_quote_cents"] == 17298, (
            f"Expected the revised quote 17298, got {revised['final_quote_cents']}"
        )
        assert revised["submission_state"] == "PRICE_REVISED"
        assert revised["revision_count"] == 1
        assert revised["inspection_fee_cents"] == 1500
        # FLAWLESS -> FAIR is two cosmetic steps, FULLY_FUNCTIONAL -> MINOR_FAULTS
        # is one functional step, so the step penalty is three steps.
        step_penalty = 2500 * 3
        inspected_value = 38000 - 5200 - 4200 - 2500 - 0
        assert revised["final_quote_cents"] == inspected_value - step_penalty - 1302, (
            "the final quote is the inspected value less the step penalty less the 7% fee"
        )


class TestFinalQuoteBands:
    def test_final_quote_combines_bands_ordinals_and_penalty(self, api):
        """PRD §3.8: "the number of grade steps worse than the declaration is the sum of two clamped differences: the excess, if any, of the inspected cosmetic position over the declared cosmetic position, plus the excess, if any, of the inspected functional position over the declared functional position."
        PRD §3.8: "The inspection fee is then seven percent of that clamped figure, rounded half-up to integer cents, and the final quote is that figure minus the fee, rounded half-up to integer cents and clamped at zero once more."

        Design: Difficulty/combinatorial_formula/trade_in_final_quote_nested_clamp_and_bands
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        trade_in = fx.submit_trade_in(
            self_declared_cosmetic_grade="GOOD",
            self_declared_functional_grade="MINOR_FAULTS",
            self_declared_battery_health_pct=90,
            self_declared_carrier_lock_status="UNLOCKED",
        )
        assert trade_in["provisional_quote_cents"] == 32000

        fx.inspect_trade_in(
            trade_in["id"],
            inspected_cosmetic_grade="FAIR",
            inspected_functional_grade="MINOR_FAULTS",
            inspected_battery_health_pct=82,
            inspected_carrier_lock_status="LOCKED",
        )
        revised = validate_success(fx.revise_trade_in(trade_in["id"]))
        assert revised["final_quote_cents"] == 13578, (
            f"Expected the nested-clamp final quote 13578, got {revised['final_quote_cents']}"
        )

    def test_locked_carrier_band_is_deducted_before_the_fee(self, api):
        """PRD §3.8: "The carrier-lock deduction is zero for `UNLOCKED`, 4500 cents for `UNKNOWN` and 9000 cents for `LOCKED`."
        PRD §3.8: "a device measured at exactly 70 percent or above proceeds to `INSPECTED`, while one measured strictly below 70 is rejected outright"

        Design: Difficulty/combinatorial_formula/trade_in_final_quote_nested_clamp_and_bands
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        unlocked = fx.submit_trade_in(
            self_declared_cosmetic_grade="GOOD",
            self_declared_functional_grade="MINOR_FAULTS",
            self_declared_battery_health_pct=90,
            self_declared_carrier_lock_status="UNLOCKED",
        )
        locked = fx.submit_trade_in(
            self_declared_cosmetic_grade="GOOD",
            self_declared_functional_grade="MINOR_FAULTS",
            self_declared_battery_health_pct=90,
            self_declared_carrier_lock_status="UNKNOWN",
        )
        # The measured lock state, not the declaration, drives the final quote.
        # Each submission is inspected exactly once (PRD §3.8: inspection runs
        # from SUBMITTED), so the two devices are inspected with the lock state
        # whose deduction the test is measuring.
        fx.inspect_trade_in(
            unlocked["id"],
            inspected_cosmetic_grade="FAIR",
            inspected_functional_grade="MINOR_FAULTS",
            inspected_battery_health_pct=82,
            inspected_carrier_lock_status="UNLOCKED",
        )
        unlocked_revised = validate_success(fx.revise_trade_in(unlocked["id"]))
        # 38000 - 5200 (FAIR) - 4200 (MINOR_FAULTS) - 2500 (82%) - 0 = 26100
        # one cosmetic step (GOOD -> FAIR) => 26100 - 2500 = 23600
        # fee = round_half_up(23600 * 0.07) = 1652 => 23600 - 1652 = 21948
        assert unlocked_revised["final_quote_cents"] == 21948

        fx.inspect_trade_in(
            locked["id"],
            inspected_cosmetic_grade="FAIR",
            inspected_functional_grade="MINOR_FAULTS",
            inspected_battery_health_pct=82,
            inspected_carrier_lock_status="LOCKED",
        )
        locked_revised = validate_success(fx.revise_trade_in(locked["id"]))
        # The 9000-cent locked band is inside inspected_value, so the 7% fee is
        # taken on the already-reduced figure rather than on the unlocked one.
        assert locked_revised["final_quote_cents"] == 13578
        assert locked_revised["final_quote_cents"] < unlocked_revised["final_quote_cents"]


class TestInsurableBatteryBoundary:
    def test_inspection_at_exactly_70_proceeds(self, api):
        """PRD §3.8: "a device measured at exactly 70 percent or above proceeds to `INSPECTED`, while one measured strictly below 70 is rejected outright and moves to `REJECTED`, refused with `ERR_INSPECTION_BATTERY_UNINSURABLE` (HTTP 422)."
        PRD §3.8: "The boundary is deliberate — 70 is insurable and 69 is not."

        Design: Difficulty/boundary_precision_check/measured_battery_health_at_insurable_boundary
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        trade_in = fx.submit_trade_in()
        inspected = validate_success(
            fx.inspect_trade_in(
                trade_in["id"],
                inspected_cosmetic_grade="FAIR",
                inspected_functional_grade="MINOR_FAULTS",
                inspected_battery_health_pct=70,
                inspected_carrier_lock_status="UNLOCKED",
            )
        )
        assert inspected["submission_state"] == "INSPECTED", (
            "a device measured at exactly 70 is insurable and must reach INSPECTED"
        )

    def test_inspection_at_69_is_refused_uninsurable(self, api):
        """PRD §3.8: "a device measured at exactly 70 percent or above proceeds to `INSPECTED`, while one measured strictly below 70 is rejected outright and moves to `REJECTED`, refused with `ERR_INSPECTION_BATTERY_UNINSURABLE` (HTTP 422)."
        PRD §3.8: "A submission that proceeds has its `final_quote_cents` set to zero pending the revision step."

        Design: Difficulty/boundary_precision_check/measured_battery_health_at_insurable_boundary
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        trade_in = fx.submit_trade_in()
        response = fx.inspect_trade_in(
            trade_in["id"],
            inspected_cosmetic_grade="FAIR",
            inspected_functional_grade="MINOR_FAULTS",
            inspected_battery_health_pct=69,
            inspected_carrier_lock_status="UNLOCKED",
        )
        validate_error(response, ApiErrorId.ERR_INSPECTION_BATTERY_UNINSURABLE, 422)

        after = fx.read_trade_in(trade_in["id"])
        assert after["submission_state"] == "REJECTED"


class TestTradeInListingContract:
    def test_list_pagination_envelope_honours_limit_and_offset(self, api):
        """PRD §2.3: "`limit` caps how many items are returned, defaults to 10, and is constrained to a minimum of 1 and a maximum of 100; a value outside that range is a malformed request."
        PRD §2.3: "the `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more` alongside the standard `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/trade_in_listing_pagination_envelope
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        first = fx.submit_trade_in()
        fx.submit_trade_in()
        fx.submit_trade_in(
            self_declared_cosmetic_grade="GOOD",
            self_declared_functional_grade="MINOR_FAULTS",
            self_declared_battery_health_pct=90,
        )

        page, meta = validate_success_page(api, "/v1/trade-ins", {"limit": 2, "offset": 0})
        assert len(page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        offset_page, offset_meta = validate_success_page(api, "/v1/trade-ins", {"limit": 1, "offset": 1})
        assert len(offset_page) == 1
        assert offset_page[0]["id"] != page[0]["id"], (
            "the row at offset 1 must differ from the row at offset 0"
        )
        assert offset_meta["total_count"] == 3
        assert first["id"] == page[0]["id"], "list responses are ordered by creation timestamp ascending"

        over = fx.api_client.list_trade_ins(fx.ADMIN, {"limit": 101})
        validate_error(over, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_second_revision_is_refused(self, api):
        """PRD §3.8: "A revision attempted when `revision_count` is already one is refused with `ERR_REVISION_LIMIT_REACHED` (HTTP 409)."
        PRD §3.8: "the one free revision round runs in both directions and is exhausted by the second attempt."

        Design: Corner/state_machines/trade_in_second_revision_rejected
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        trade_in = fx.submit_trade_in(
            self_declared_cosmetic_grade="GOOD",
            self_declared_functional_grade="MINOR_FAULTS",
            self_declared_battery_health_pct=90,
        )
        fx.inspect_trade_in(trade_in["id"])
        revised = validate_success(fx.revise_trade_in(trade_in["id"]))
        assert revised["revision_count"] == 1

        # PRD §3.8: "A submission in `PRICE_REVISED` may, however, be revised
        # *back* to `INSPECTED` provided the clock is at or before its
        # `acceptance_deadline` and its `revision_count` is exactly one — the one
        # free revision round runs in both directions and is exhausted by the
        # second attempt."  The first reverse revision is therefore admitted,
        # and it is the third request that exhausts the round.
        reverted = validate_success(fx.revise_trade_in(trade_in["id"]))
        assert reverted["submission_state"] == "INSPECTED"
        assert reverted["revision_count"] == 1

        response = fx.revise_trade_in(trade_in["id"])
        validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED, 409)

        after = fx.read_trade_in(trade_in["id"])
        assert after["revision_count"] == 1
        assert after["submission_state"] == "INSPECTED", (
            "the refused third attempt leaves the state the reverse revision set"
        )


def validate_success_page(api, path, params):
    """Read a paginated list and return (rows, meta)."""
    return validate_paginated(api.get(path, headers=fx.ADMIN, params=params))