"""Effective power cost variants and monthly settlement (PRD §3.3, §3.1, §3.2).

Covers the FORWARD vs SETTLED dual-variant calculation, the pinned
round-per-hour-then-sum settlement order, the latest-observation selector
tie-break, null degradation without observations, contract component shape,
and the potline-create power gate.
"""
import pytest
from test_helpers import (
    ApiErrorId,
    BLENDED_COMPONENTS,
    create_active_contract,
    create_potline_payload,
    create_power_contract_payload,
    create_smelter,
    post_price_observation,
    set_clock,
    setup_site,
    validate_error,
    validate_success,
)


def _setup_blended_contract_with_curve():
    """Smelter + ACTIVE blended contract; clock advanced to 2026-09-11 with
    spot prints 48.00 (08-20), 40.00 (09-01), 60.00 (09-06)."""
    smelter = create_smelter()
    contract = create_active_contract(smelter["id"], components=BLENDED_COMPONENTS)
    set_clock("2026-09-11T00:00:00Z")
    post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-08-20T00:00:00Z", 48.00)
    post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-09-01T00:00:00Z", 40.00)
    post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-09-06T00:00:00Z", 60.00)
    return smelter, contract


class TestForwardVsSettledCost:
    def test_forward_cost_uses_single_latest_spot(self, api, energy_manager_headers):
        """PRD §3.3: "The FORWARD variant is projective: it feeds the
        `forward_cost_per_mwh` read field and the curtailment economics
        snapshot, and it prices the contract as `f` plus `m_mw` times the
        single latest spot plus `i_mw` times that same spot discounted by a
        quarter (interruptible energy prices at 75% of spot), all divided by
        `total_mw`."

        Design: Difficulty/dual_variant_calc/power_contract_forward_vs_settled_cost
        """
        _, contract = _setup_blended_contract_with_curve()
        data = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        # (150*32 + 100*60 + 50*60*0.75) / 300 = 13050/300
        assert data["forward_cost_per_mwh"] == pytest.approx(43.50, abs=0.01)

    def test_settled_cost_time_weighted_diverges_from_forward(self, api, energy_manager_headers):
        """PRD §3.3: "The SETTLED variant is the ex-post view exposed as
        `settled_cost_per_mwh`, and it replays the calendar month containing
        the current logical clock chronologically."
        PRD §3.3: "Identical contract inputs therefore produce different
        forward and settled numbers whenever the curve moved intra-month."

        Design: Difficulty/dual_variant_calc/power_contract_forward_vs_settled_cost
        """
        _, contract = _setup_blended_contract_with_curve()
        data = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        # tw_avg = (40*120h + 60*120h)/240h = 50.00 -> (4800+5000+1875)/300
        assert data["settled_cost_per_mwh"] == pytest.approx(38.92, abs=0.01)
        assert data["forward_cost_per_mwh"] != data["settled_cost_per_mwh"]


class TestMonthlySettlementRounding:
    def _setup_market_only_contract(self):
        smelter = create_smelter()
        contract = create_active_contract(
            smelter["id"], components=[{"component_type": "MARKET_INDEXED", "volume_mw": 100}]
        )
        set_clock("2026-09-02T00:00:00Z")
        post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-08-25T00:00:00Z", 53.57)
        return contract

    def test_month_to_date_settlement_value(self, api, energy_manager_headers):
        """PRD §3.3: "The settlement itself surfaces as
        `month_to_date_settlement_usd`, computed hour by hour for the calendar
        month containing the logical clock."

        Design: Difficulty/combinatorial_formula/monthly_settlement_round_per_hour_then_sum
        """
        contract = self._setup_market_only_contract()
        data = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        # 24 * round_half_up(100 * 53.57 * 1.037, 2) = 24 * 5555.21
        assert data["month_to_date_settlement_usd"] == pytest.approx(133325.04, abs=0.01)

    def test_settlement_rounds_per_hour_then_sums(self, api, energy_manager_headers):
        """PRD §3.3: "Each hour's raw total is rounded half-up to 2 decimal
        places before any summation; the rounded hourly amounts then sum into
        days and the days into the month-to-date figure. This pinned order —
        round per hour, then sum — is contractual."

        Design: Difficulty/combinatorial_formula/monthly_settlement_round_per_hour_then_sum
        """
        contract = self._setup_market_only_contract()
        data = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        # Forbidden sum-then-round order yields 24 * 5555.209 = 133325.02
        assert data["month_to_date_settlement_usd"] == pytest.approx(133325.04, abs=0.01)
        assert data["month_to_date_settlement_usd"] != pytest.approx(133325.02, abs=0.001)


class TestLatestObservationSelector:
    def test_latest_observation_tiebreak_by_created_at(self, api, energy_manager_headers):
        """PRD §2.10: ""Latest observation" selectors used throughout the
        pricing engine pick the qualifying record with the greatest
        `observed_at` at or before the logical clock, breaking ties by
        `created_at` descending (the most recently recorded observation wins)."

        Design: Corner/calculations/latest_price_observation_selector_tiebreak
        """
        smelter = create_smelter()
        contract = create_active_contract(smelter["id"], components=BLENDED_COMPONENTS)
        post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-08-20T00:00:00Z", 40.00)
        post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-08-25T00:00:00Z", 44.00)

        first = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        # (150*32 + 100*44 + 50*44*0.75)/300 = 10850/300
        assert first["forward_cost_per_mwh"] == pytest.approx(36.17, abs=0.01)

        # Same observed_at, posted later: wins the created_at tie-break.
        post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-08-25T00:00:00Z", 46.00)
        second = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        # (150*32 + 100*46 + 50*46*0.75)/300 = 11125/300
        assert second["forward_cost_per_mwh"] == pytest.approx(37.08, abs=0.01)


class TestMissingPriceData:
    def test_computed_costs_null_without_observations(self, api, energy_manager_headers):
        """PRD §3.3: "when `m_mw` and `i_mw` together exceed zero and no
        qualifying observation exists, both variant outputs read null — this
        is not an error condition."
        PRD §2.11: "Computed reads that depend on market data degrade to null
        rather than raising when their inputs are missing".

        Design: Corner/calculations/forward_cost_null_without_price_observation
        """
        smelter = create_smelter()
        contract = create_active_contract(
            smelter["id"], components=[{"component_type": "MARKET_INDEXED", "volume_mw": 100}]
        )
        resp = api.get_power_contract(contract["id"], energy_manager_headers)
        data = validate_success(resp, 200)
        assert data["forward_cost_per_mwh"] is None
        assert data["settled_cost_per_mwh"] is None
        assert data["month_to_date_settlement_usd"] is None


class TestContractShapeAndPowerGate:
    def test_component_invalid_enum_rejected(self, api, energy_manager_headers):
        """PRD §3.2: "Each component declares a `component_type` of `FIXED`,
        `MARKET_INDEXED`, or `INTERRUPTIBLE`, plus a strictly positive
        `volume_mw`."
        PRD §3.2: "Composition violations — a missing component list, a second
        interruptible tranche, a fixed tranche without its price, an
        interruptible tranche without its cap — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/contract_component_invalid_enum_returns_invalid_request
        """
        smelter = create_smelter()
        payload = create_power_contract_payload(
            smelter["id"], components=[{"component_type": "SPOT_ONLY", "volume_mw": 100}]
        )
        resp = api.create_power_contract(payload, energy_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_potline_create_without_active_contract_rejected(self, api, smelter_manager_headers,
                                                             energy_manager_headers):
        """PRD §3.1: "Creation is gated on power: the smelter must have an
        `ACTIVE` power contract whose delivery window covers the current
        logical clock, or the request is rejected with
        `ERR_NO_ACTIVE_POWER_CONTRACT` (HTTP 422)."

        Design: Corner/entities/potline_create_without_active_contract_rejected
        """
        smelter = create_smelter()
        # Contract stays DRAFT: no ACTIVE window covers the default clock.
        create_active_contract(smelter["id"], activate=False)
        resp = api.create_potline(create_potline_payload(smelter["id"]), smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POWER_CONTRACT)
