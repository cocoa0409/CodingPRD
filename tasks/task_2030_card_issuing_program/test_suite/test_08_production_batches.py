"""Production batch temporal-overlap rules (difficulty: resource_temporal_overlap
and priority_pair_validation_conflict)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_production_batch,
    create_program_with_bin_and_publish,
    create_submitted_batch,
    create_vendor,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)

OA = TEST_USERS["operations_analyst_headers"]


class TestVendorBatchOverlap:
    def test_vendor_batch_same_date_overlap_rejected(self, api):
        """PRD §3.3: "no other batch for the same vendor on the same UTC date
        may already be `SUBMITTED` or `IN_PRODUCTION`
        (`ERR_VENDOR_BATCH_OVERLAP`)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_velocity
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-10", bin_prefix="499999")
        vendor = create_vendor("VEND-X", daily_capacity_cards=100)
        create_submitted_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=50,
            unit_cost_cents=100,
        )
        batch_new = create_production_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=50,
            unit_cost_cents=100,
        )
        resp = api.submit_batch(batch_new["id"], OA)
        validate_error(resp, ApiErrorId.ERR_VENDOR_BATCH_OVERLAP.value)

    def test_vendor_batch_overlap_also_rejected_when_existing_in_production(self, api):
        """PRD §3.3: "no other batch for the same vendor on the same UTC date
        may already be `SUBMITTED` or `IN_PRODUCTION`
        (`ERR_VENDOR_BATCH_OVERLAP`)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_velocity
        """
        from test_helpers import create_in_production_batch
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-10B", bin_prefix="499998")
        vendor = create_vendor("VEND-X2", daily_capacity_cards=100)
        create_in_production_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=50,
            unit_cost_cents=100,
        )
        batch_new = create_production_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=50,
            unit_cost_cents=100,
        )
        resp = api.submit_batch(batch_new["id"], OA)
        validate_error(resp, ApiErrorId.ERR_VENDOR_BATCH_OVERLAP.value)

    def test_vendor_batch_different_date_no_overlap(self, api):
        """PRD §3.3: "no other batch for the same vendor on the same UTC date
        may already be `SUBMITTED` or `IN_PRODUCTION`
        (`ERR_VENDOR_BATCH_OVERLAP`)."

        Batches on different UTC dates never collide.

        Design: Difficulty/resource_temporal_overlap/vendor_batch_same_date_overlap
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-15", bin_prefix="455500")
        vendor = create_vendor("VEND-Y", daily_capacity_cards=1000)
        create_submitted_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=100,
            unit_cost_cents=50,
        )
        batch2 = create_production_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-16",
            requested_card_count=100,
            unit_cost_cents=50,
        )
        resp = api.submit_batch(batch2["id"], OA)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED", (
            f"Different UTC date must not collide; expected SUBMITTED, got "
            f"{data['status']}"
        )

    def test_vendor_batch_same_date_after_cancel_no_overlap(self, api):
        """PRD §3.3: "no other batch for the same vendor on the same UTC date
        may already be `SUBMITTED` or `IN_PRODUCTION`
        (`ERR_VENDOR_BATCH_OVERLAP`)."

        A CANCELLED batch is outside the colliding status set, so a same-date
        submit must succeed once the earlier batch is cancelled.

        Design: Difficulty/resource_temporal_overlap/vendor_batch_same_date_overlap
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-VISA-15B", bin_prefix="455501")
        vendor = create_vendor("VEND-Y2", daily_capacity_cards=1000)
        first = create_submitted_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=100,
            unit_cost_cents=50,
        )
        get_success_data(api.cancel_batch(first["id"], OA))
        second = create_production_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=100,
            unit_cost_cents=50,
        )
        resp = api.submit_batch(second["id"], OA)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED", (
            f"Cancelled batch must not collide on the same date; expected "
            f"SUBMITTED, got {data['status']}"
        )
