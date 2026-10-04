"""Settlement: gross/refunds/net readings, and the settlement read endpoint."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_booking_payload,
    set_clock,
    setup_show_in_rehearsal,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
VS = TEST_USERS["venue_scheduler_headers"]
GU = TEST_USERS["guest_headers"]


def _confirm_show(api, show_id, production_id):
    prod = validate_success(api.get_production(production_id, PD))
    return validate_success(
        api.confirm_show(show_id, {"expected_production_version": prod["version"]}, VS)
    )


class TestSettlementVariants:

    def test_gross_net_and_refunds_diverge_on_same_bookings(self, api):
        """PRD: "`gross_cents` is the sum of `line_total_cents` over the show's
        `CONFIRMED` bookings. `refunds_cents` is the sum of `refund_cents` over
        the show's `CANCELLED` bookings. `net_cents` is `gross_cents` minus
        `refunds_cents`."

        Design: Difficulty/dual_variant_calc/settlement_payout_gross_vs_net_variant
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=12000,
            show_overrides={"show_format": "CONCERT", "start_time": "2026-09-01T10:00:00Z", "length_minutes": 90},
        )
        _confirm_show(api, show["id"], prod["id"])
        bk_a = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="MAIN", seats=2), GU),
            expected_status=201,
        )
        validate_success(api.confirm_booking(bk_a["id"], GU))
        bk_b = validate_success(
            api.create_booking(show["id"], create_booking_payload(zone="MAIN", seats=1), GU),
            expected_status=201,
        )
        validate_success(api.confirm_booking(bk_b["id"], GU))
        validate_success(api.cancel_booking(bk_b["id"], GU))

        # The §3.8 clock sweep completes the CONFIRMED show once the clock
        # passes start_time + length_minutes (11:30); settlement runs there.
        set_clock("2026-09-01T12:00:00Z")
        assert validate_success(api.get_show(show["id"], VS))["status"] == "COMPLETED"

        resp = api.get_settlement(show["id"], VS)
        data = validate_success(resp)
        settlement = data[0] if isinstance(data, list) else data
        # B0_MAIN = round_half_up(12000 x (1 + 12000 x 1.0 / 760), 4) = 201473.6842
        # booking A line = round(2 x 201473.6842 x 1.06, 2) = 427124.21
        # booking B refund = round(1 x 201473.6842 x 1.06, 2) = 213562.11
        assert settlement["gross_cents"] == pytest.approx(427124.21, abs=0.005)
        assert settlement["refunds_cents"] == pytest.approx(213562.11, abs=0.005)
        assert settlement["net_cents"] == pytest.approx(213562.10, abs=0.005)
        assert settlement["gross_cents"] != settlement["net_cents"], (
            "gross (CONFIRMED only) and net (gross minus CANCELLED refunds) must diverge"
        )

    def test_settlement_recorded_as_final_on_completion(self, api):
        """PRD: "Settlement runs automatically when a show completes. The
        platform computes a `Settlement` record under the show, in `FINAL`
        status, with the following fields."
        PRD: "At completion, the platform runs settlement (see §3.5), creates a
        `Settlement` record whose `status` is `FINAL`, stores the settlement's
        `id` on the show's `settlement_snapshot_id`, and accrues impressions to
        every `ACTIVE` campaign whose flight window overlaps the show window
        (see §3.7)."

        Design: Difficulty/dual_variant_calc/settlement_payout_gross_vs_net_variant
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=12000,
            show_overrides={"show_format": "CONCERT", "start_time": "2026-09-01T10:00:00Z", "length_minutes": 90},
        )
        _confirm_show(api, show["id"], prod["id"])
        # The §3.8 clock sweep completes the CONFIRMED show once the clock
        # passes start_time + length_minutes (11:30); settlement runs there.
        set_clock("2026-09-01T12:00:00Z")
        completed = validate_success(api.get_show(show["id"], VS))
        assert completed["status"] == "COMPLETED"

        resp = api.get_settlement(show["id"], VS)
        data = validate_success(resp)
        settlement = data[0] if isinstance(data, list) else data
        assert settlement["status"] == "FINAL"
        assert completed["settlement_snapshot_id"] == settlement["id"], (
            "the show must pin the settlement's id at completion"
        )


class TestSettlementReadGate:

    def test_settlement_available_after_completion(self, api):
        """PRD: "At completion, the platform runs settlement (see §3.5), creates
        a `Settlement` record whose `status` is `FINAL`, stores the settlement's
        `id` on the show's `settlement_snapshot_id`, and accrues impressions to
        every `ACTIVE` campaign whose flight window overlaps the show window
        (see §3.7)."

        Design: Corner/endpoints/settlement_not_available_for_incomplete_show
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-01T10:00:00Z", "length_minutes": 90},
        )
        _confirm_show(api, show["id"], prod["id"])
        # The §3.8 clock sweep completes the CONFIRMED show once the clock
        # passes start_time + length_minutes (11:30); settlement runs there.
        set_clock("2026-09-01T12:00:00Z")
        assert validate_success(api.get_show(show["id"], VS))["status"] == "COMPLETED"
        resp = api.get_settlement(show["id"], VS)
        data = validate_success(resp)
        settlement = data[0] if isinstance(data, list) else data
        assert settlement["status"] == "FINAL"
