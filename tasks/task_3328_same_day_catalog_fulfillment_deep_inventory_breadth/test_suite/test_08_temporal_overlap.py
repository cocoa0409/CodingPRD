"""Temporal overlap: the same-day window when the center is already past its cutoff."""

from test_helpers import (
    MONDAY_AFTER_CUTOFF_UTC,
    MONDAY_EARLY_BEFORE_CUTOFF_UTC,
    setup_released_order,
    validate_success,
)


class TestSameDayWindowAlreadyCutOffInverseOverlap:
    """A center past its cutoff can no longer commit the order to today's dispatch."""

    def _allocated(self, api, utc):
        scenario = setup_released_order(
            api,
            lines_spec=[{"price": 4500, "qty": 1, "bundle": 8, "on_hand": 10,
                         "sku": "SKU-8101"}],
            utc=utc,
        )
        order = validate_success(api.allocate_order(
            scenario["order"]["id"],
            {"expected_order_version": scenario["order"]["version"]},
            scenario["acct_headers"]))
        return scenario, order

    def test_an_allocation_after_the_cutoff_is_not_same_day_committed(self, api):
        """PRD §3.4: "The order's own `same_day_committed` flag is then set: it is true
        when at least one eligible candidate center still had `cutoff_passed` false at the
        moment of selection — that is, at least one center was still ahead of its local
        cutoff — and false otherwise".
        PRD §3.7: "The `commit_minutes_before_cutoff` value on the order is the number of
        minutes between the allocated center's `local_current_time` at the moment of
        allocation and that center's `local_cutoff_time`, saturated at 0 — an order
        committed at or after the cutoff records 0 rather than a negative figure."

        Design: Difficulty/resource_temporal_overlap/same_day_window_already_cut_off_inverse_overlap
        """
        scenario, order = self._allocated(api, MONDAY_AFTER_CUTOFF_UTC)

        assert order["fulfillment_status"] == "ALLOCATED"
        assert order["allocated_dc_id"] == scenario["dc"]["id"]
        assert order["same_day_committed"] is False, (
            "the BOS center was already past its local cutoff, so no candidate was still "
            "ahead of it"
        )
        assert order["commit_minutes_before_cutoff"] == 0, (
            "a commitment at or after the cutoff saturates the figure at 0"
        )

    def test_the_same_allocation_ahead_of_the_cutoff_is_same_day_committed(self, api):
        """PRD §2.5: "A center's `cutoff_passed` is true once its local weekday is a
        business day and its `local_current_time` is at or after its `local_cutoff_time`".
        PRD §3.7: "It is the urgency input to the freight calculation, and it is ignored
        entirely when `same_day_committed` is false."

        Design: Difficulty/resource_temporal_overlap/same_day_window_already_cut_off_inverse_overlap
        """
        scenario, order = self._allocated(api, MONDAY_EARLY_BEFORE_CUTOFF_UTC)

        assert order["allocated_dc_id"] == scenario["dc"]["id"]
        assert order["same_day_committed"] is True, (
            "the center was still one hour ahead of its local cutoff at allocation"
        )
        assert order["commit_minutes_before_cutoff"] == 60, (
            "BOS local 05:00 against its 06:00 cutoff is exactly 60 minutes"
        )