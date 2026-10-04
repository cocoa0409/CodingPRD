"""Hedge positions: volume cap, open/close conservation, realized PnL, and
lifecycle rules (PRD §3.7, §2.11).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    assert_hedge_position,
    create_hedge,
    create_hedge_position_payload,
    create_smelter,
    validate_error,
    validate_success,
)


class TestHedgeAggregateCapacity:
    def test_aggregate_volume_at_capacity_allowed(self, api, trading_analyst_headers):
        """PRD §3.7: "the aggregate `OPEN` volume for the same smelter and
        delivery month, plus the new volume, must not exceed the smelter's
        monthly capacity basis (`rated_capacity_tpd` multiplied by 30);
        equality is allowed, and an excess is rejected with
        `ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/hedge_delivery_month_aggregate_capacity
        """
        smelter = create_smelter()  # 1000 tpd -> monthly capacity 30000t
        h1 = create_hedge(smelter["id"], volume_tonnes=18000, delivery_month="2026-11")
        h2 = create_hedge(smelter["id"], volume_tonnes=12000, delivery_month="2026-11",
                          instrument="PREMIUM_SWAP", strike_price_usd=380.00)
        assert h1["status"] == "OPEN" and h2["status"] == "OPEN"

    def test_aggregate_volume_over_capacity_rejected(self, api, trading_analyst_headers):
        """PRD §3.7: "equality is allowed, and an excess is rejected with
        `ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE` (HTTP 422)."
        PRD §2.11: "The same read exposes `open_hedged_tonnes` (the summed
        `volume_tonnes` of the smelter's `OPEN` hedge positions)".

        Design: Difficulty/resource_temporal_overlap/hedge_delivery_month_aggregate_capacity
        """
        smelter = create_smelter()
        create_hedge(smelter["id"], volume_tonnes=18000, delivery_month="2026-11")
        create_hedge(smelter["id"], volume_tonnes=12000, delivery_month="2026-11",
                     instrument="PREMIUM_SWAP", strike_price_usd=380.00)
        resp = api.create_hedge_position(
            create_hedge_position_payload(smelter["id"], volume_tonnes=0.01,
                                          delivery_month="2026-11"),
            trading_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE)
        smelter_after = validate_success(api.get_smelter(smelter["id"], trading_analyst_headers))
        assert smelter_after["open_hedged_tonnes"] == pytest.approx(30000)


class TestOpenCloseConservation:
    def test_open_hedged_tonnes_conserved_across_open_and_close(self, api, trading_analyst_headers):
        """PRD §2.11: "The same read exposes `open_hedged_tonnes` (the summed
        `volume_tonnes` of the smelter's `OPEN` hedge positions)".
        PRD §3.7: "Closing drops the volume out of `open_hedged_tonnes` on the
        next smelter read and increments the hedge's `version`."

        Design: Difficulty/compensating_invariant/hedge_open_close_conserves_open_hedged_tonnes
        """
        smelter = create_smelter()
        baseline = validate_success(api.get_smelter(smelter["id"], trading_analyst_headers))
        assert baseline["open_hedged_tonnes"] == 0

        hedge = create_hedge(smelter["id"], volume_tonnes=15000, delivery_month="2026-10")
        after_open = validate_success(api.get_smelter(smelter["id"], trading_analyst_headers))
        assert after_open["open_hedged_tonnes"] == pytest.approx(15000)

        validate_success(
            api.close_hedge_position(hedge["id"], {"closed_price_usd": 2500.00},
                                     trading_analyst_headers)
        )
        after_close = validate_success(api.get_smelter(smelter["id"], trading_analyst_headers))
        assert after_close["open_hedged_tonnes"] == 0

    def test_close_records_realized_pnl(self, api, trading_analyst_headers):
        """PRD §3.7: "the position's `realized_pnl_usd` — null while `OPEN` —
        is computed as the closed price minus the strike, multiplied by the
        volume, rounded half-up to 2 decimal places."

        Design: Difficulty/compensating_invariant/hedge_open_close_conserves_open_hedged_tonnes
        """
        smelter = create_smelter()
        hedge = create_hedge(smelter["id"], volume_tonnes=15000, delivery_month="2026-10",
                             strike_price_usd=2400.00)
        data = validate_success(
            api.close_hedge_position(hedge["id"], {"closed_price_usd": 2500.00},
                                     trading_analyst_headers)
        )
        assert data["status"] == "CLOSED"
        # (2500.00 - 2400.00) * 15000
        assert data["realized_pnl_usd"] == pytest.approx(1500000.00, abs=0.01)


class TestDerivedTonnesReconciliation:
    def test_open_hedged_tonnes_reconciles_across_mixed_closes(self, api, trading_analyst_headers):
        """PRD §2.11: "The same read exposes `open_hedged_tonnes` (the summed
        `volume_tonnes` of the smelter's `OPEN` hedge positions)".
        PRD §3.7: "Closing drops the volume out of `open_hedged_tonnes` on the
        next smelter read and increments the hedge's `version`."

        Design: Corner/cross_cutting_layers/derived_open_hedged_tonnes_reconciles_on_open_and_close
        """
        smelter = create_smelter()
        h1 = create_hedge(smelter["id"], volume_tonnes=15000, delivery_month="2026-10")
        create_hedge(smelter["id"], volume_tonnes=11000, delivery_month="2026-11",
                     instrument="PREMIUM_SWAP", strike_price_usd=380.00)

        mid = validate_success(api.get_smelter(smelter["id"], trading_analyst_headers))
        assert mid["open_hedged_tonnes"] == pytest.approx(26000)

        closed = validate_success(
            api.close_hedge_position(h1["id"], {"closed_price_usd": 2450.00},
                                     trading_analyst_headers)
        )
        # (2450.00 - 2400.00) * 15000
        assert closed["realized_pnl_usd"] == pytest.approx(750000.00, abs=0.01)

        after = validate_success(api.get_smelter(smelter["id"], trading_analyst_headers))
        assert after["open_hedged_tonnes"] == pytest.approx(11000)


class TestHedgeLifecycleAndShape:
    def test_double_close_rejected_and_pnl_stable(self, api, trading_analyst_headers):
        """PRD §3.7: "Closing a hedge that is not `OPEN` is rejected with
        `ERR_INVALID_LIFECYCLE_STATE`."

        Design: Corner/state_machines/hedge_double_close_rejected
        """
        smelter = create_smelter()
        hedge = create_hedge(smelter["id"], volume_tonnes=5000, delivery_month="2026-10")
        first = validate_success(
            api.close_hedge_position(hedge["id"], {"closed_price_usd": 2500.00},
                                     trading_analyst_headers)
        )
        assert first["realized_pnl_usd"] == pytest.approx(500000.00, abs=0.01)

        resp = api.close_hedge_position(hedge["id"], {"closed_price_usd": 2600.00},
                                        trading_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_LIFECYCLE_STATE)

    def test_delivery_month_in_past_rejected(self, api, trading_analyst_headers):
        """PRD §3.7: "a `delivery_month` in `YYYY-MM` format that may not be
        earlier than the month containing the current logical clock."
        PRD §2.7: "15. Temporal field validity on creation payloads —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/hedge_delivery_month_in_past_returns_invalid_request
        """
        smelter = create_smelter()
        resp = api.create_hedge_position(
            create_hedge_position_payload(smelter["id"], volume_tonnes=1000,
                                          delivery_month="2026-08"),
            trading_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
