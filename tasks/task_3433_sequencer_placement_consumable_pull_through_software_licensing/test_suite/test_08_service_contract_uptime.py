"""Service contracts: uptime credit tier/cap arithmetic, exact-threshold
boundary, half-open window adjacency, window validity, reconciliation
chaining, and the contract expiry sweep (PRD sections 2.4, 3.6).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_uptime_reconciliation_result,
    create_account,
    create_contract,
    create_active_contract,
    create_instrument,
    create_service_contract_payload,
    activate_contract,
    instrument_event_payload,
    record_service_window,
    setup_active_contract_scenario,
    uptime_reconciliation_payload,
    validate_error,
    validate_success,
)
from test_helpers import api_client

FSE = TEST_USERS["field_service_engineer_headers"]
FA = TEST_USERS["finance_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def _reconcile(contract_id: str, period_start: str, period_end: str):
    return api_client.post_uptime_reconciliation(
        contract_id,
        uptime_reconciliation_payload(period_start, period_end),
        FA,
    )


def _setup_first_period_with_20min_downtime() -> dict:
    """ACTIVE contract (committed 99.0, fee 500,000c, cap 120,000c, coverage
    [2026-09-01, 2027-09-01)); a 20-minute service window 00:00 -> 00:20;
    first reconciliation over the 1000-minute period [00:00, 16:40)."""
    bag = setup_active_contract_scenario()
    instrument_id = bag["instrument"]["id"]
    # Open the window at the default clock instant (2026-09-01T00:00:00Z) —
    # no clock advance is needed (or possible, monotonicity) for t == default.
    validate_success(
        api_client.post_instrument_event(
            instrument_id, instrument_event_payload("SERVICE_OPEN"), FSE
        )
    )
    advance_clock("2026-09-01T00:20:00Z")
    validate_success(
        api_client.post_instrument_event(
            instrument_id, instrument_event_payload("SERVICE_CLOSE"), FSE
        )
    )
    advance_clock("2026-09-01T16:40:00Z")
    first = validate_success(
        _reconcile(
            bag["contract"]["id"],
            "2026-09-01T00:00:00Z",
            "2026-09-01T16:40:00Z",
        ),
        201,
    )
    bag["first_reconciliation"] = first
    return bag


class TestUptimeCreditTieredCapMinMax:
    def test_deficit_exactly_1_lands_in_10pct_tier(self, api):
        """1000-minute period with 20 downtime minutes gives uptime 98.00;
        the deficit of exactly 1.00 takes the 10% tier (not 5%):
        10% of 500,000c = 50,000c.

        PRD §3.6: "Measured uptime is the percentage of the period that was not downtime, rounded half up to two decimals."
        PRD §3.6: "Below the commitment, the deficit — the commitment minus the measured uptime, at two decimals rounded half up — selects a rate: a deficit below 1.0 percentage point pays 5% of `monthly_fee_cents`; a deficit of at least 1.0 but below 3.0 pays 10%, so a deficit of exactly 1.0 lands in the 10% tier; a deficit of 3.0 or more pays 25%."

        Design: Difficulty/combinatorial_formula/uptime_credit_tiered_cap_minmax
        """
        bag = _setup_first_period_with_20min_downtime()
        first = bag["first_reconciliation"]
        assert_uptime_reconciliation_result(first)
        assert first["downtime_minutes"] == 20
        assert float(first["uptime_percent"]) == pytest.approx(98.00)
        assert first["credit_cents"] == 50_000

    def test_second_reconciliation_clamps_to_cap_remainder(self, api):
        """Second period (1000 minutes, 50 down -> uptime 95.00 -> deficit
        4.00 -> 25% tier) computes a raw 125,000c that the annual cap
        remainder (120,000 - 50,000) clamps to 70,000c, fully consuming the
        cap.

        PRD §3.6: "Below the commitment, the deficit — the commitment minus the measured uptime, at two decimals rounded half up — selects a rate: a deficit below 1.0 percentage point pays 5% of `monthly_fee_cents`; a deficit of at least 1.0 but below 3.0 pays 10%, so a deficit of exactly 1.0 lands in the 10% tier; a deficit of 3.0 or more pays 25%."
        PRD §3.6: "The raw credit rounds half up to whole cents and is then clamped to the remaining annual headroom — `annual_credit_cap_cents` minus `credits_issued_ytd_cents` — never below zero."

        Design: Difficulty/combinatorial_formula/uptime_credit_tiered_cap_minmax
        """
        bag = _setup_first_period_with_20min_downtime()
        assert bag["first_reconciliation"]["credit_cents"] == 50_000
        instrument_id = bag["instrument"]["id"]
        record_service_window(
            instrument_id, "2026-09-02T02:00:00Z", "2026-09-02T02:50:00Z"
        )
        advance_clock("2026-09-02T09:20:00Z")
        second = validate_success(
            _reconcile(
                bag["contract"]["id"],
                "2026-09-01T16:40:00Z",
                "2026-09-02T09:20:00Z",
            ),
            201,
        )
        assert second["downtime_minutes"] == 50
        assert float(second["uptime_percent"]) == pytest.approx(95.00)
        assert second["credit_cents"] == 70_000, (
            "raw 125,000c must clamp to the 70,000c cap remainder, got "
            f"{second['credit_cents']}"
        )
        assert second["credits_issued_ytd_cents"] == 120_000


class TestUptimeExactThreshold:
    def _run_threshold_case(self, downtime_minutes: int) -> dict:
        """Committed 99.90, fee 500,000c, cap 100,000c; one service window of
        `downtime_minutes` starting 01:00; reconcile the 1000-minute period
        [00:00, 16:40)."""
        bag = setup_active_contract_scenario(
            contract_overrides={
                "committed_uptime_percent": 99.90,
                "annual_credit_cap_cents": 100_000,
            }
        )
        record_service_window(
            bag["instrument"]["id"],
            "2026-09-01T01:00:00Z",
            f"2026-09-01T01:{downtime_minutes:02d}:00Z",
        )
        advance_clock("2026-09-01T16:40:00Z")
        return validate_success(
            _reconcile(
                bag["contract"]["id"],
                "2026-09-01T00:00:00Z",
                "2026-09-01T16:40:00Z",
            ),
            201,
        )

    def test_exact_threshold_yields_zero_credit(self, api):
        """999 of 1000 minutes up is exactly 99.90 — equal to the 99.90
        commitment, and the strictly-below rule pays nothing.

        PRD §3.6: "If the measured uptime meets or exceeds `committed_uptime_percent` the credit is zero — hitting the commitment exactly pays nothing."
        PRD §3.6: "Measured uptime is the percentage of the period that was not downtime, rounded half up to two decimals."

        Design: Difficulty/boundary_precision_check/uptime_exact_threshold_yields_zero_credit
        """
        result = self._run_threshold_case(downtime_minutes=1)
        assert result["downtime_minutes"] == 1
        assert float(result["uptime_percent"]) == pytest.approx(99.90)
        assert result["credit_cents"] == 0, (
            "99.90 >= 99.90: exact-threshold equality is not a breach"
        )

    def test_one_tick_below_threshold_pays_5pct(self, api):
        """998 of 1000 minutes up is 99.80: a 0.10 deficit, below 1.0, pays
        5% of 500,000c = 25,000c.

        PRD §3.6: "If the measured uptime meets or exceeds `committed_uptime_percent` the credit is zero — hitting the commitment exactly pays nothing."
        PRD §3.6: "Below the commitment, the deficit — the commitment minus the measured uptime, at two decimals rounded half up — selects a rate: a deficit below 1.0 percentage point pays 5% of `monthly_fee_cents`; a deficit of at least 1.0 but below 3.0 pays 10%, so a deficit of exactly 1.0 lands in the 10% tier; a deficit of 3.0 or more pays 25%."

        Design: Difficulty/boundary_precision_check/uptime_exact_threshold_yields_zero_credit
        """
        result = self._run_threshold_case(downtime_minutes=2)
        assert result["downtime_minutes"] == 2
        assert float(result["uptime_percent"]) == pytest.approx(99.80)
        assert result["credit_cents"] == 25_000


class TestContractWindowOverlap:
    def _active_contract_a(self):
        """Instrument with ACTIVE contract A covering [2026-01-01, 2027-01-01)."""
        account = create_account()
        instrument = create_instrument(account_id=account["id"])
        contract_a = create_active_contract(
            account_id=account["id"],
            instrument_id=instrument["id"],
            coverage_start="2026-01-01T00:00:00Z",
            coverage_end="2027-01-01T00:00:00Z",
        )
        return account, instrument, contract_a

    def test_adjacent_window_activates_cleanly(self, api):
        """A new contract whose coverage_start equals the existing contract's
        coverage_end is adjacency, not overlap, under half-open windows.

        PRD §3.6: "Activation re-checks the window, refuses a `DECOMMISSIONED` instrument with `ERR_INVALID_STATE`, and enforces single coverage: no other `ACTIVE` contract on the same instrument may have an overlapping half-open window, else `ERR_CONTRACT_WINDOW_OVERLAP` (HTTP 409) — adjacency is allowed, so a new contract whose `coverage_start` equals an existing contract's `coverage_end` activates cleanly."

        Design: Difficulty/resource_temporal_overlap/contract_window_half_open_adjacency
        """
        account, instrument, _ = self._active_contract_a()
        contract_b = create_contract(
            account_id=account["id"],
            instrument_id=instrument["id"],
            coverage_start="2027-01-01T00:00:00Z",
            coverage_end="2028-01-01T00:00:00Z",
            monthly_fee_cents=600_000,
        )
        activated = activate_contract(contract_b["id"])
        assert activated["contract_state"] == "ACTIVE"

    def test_one_day_overlap_rejected(self, api):
        """A new contract starting one day inside the existing window is
        rejected and stays DRAFT.

        PRD §3.6: "Activation re-checks the window, refuses a `DECOMMISSIONED` instrument with `ERR_INVALID_STATE`, and enforces single coverage: no other `ACTIVE` contract on the same instrument may have an overlapping half-open window, else `ERR_CONTRACT_WINDOW_OVERLAP` (HTTP 409) — adjacency is allowed, so a new contract whose `coverage_start` equals an existing contract's `coverage_end` activates cleanly."

        Design: Difficulty/resource_temporal_overlap/contract_window_half_open_adjacency
        """
        account, instrument, _ = self._active_contract_a()
        contract_c = create_contract(
            account_id=account["id"],
            instrument_id=instrument["id"],
            coverage_start="2026-12-31T00:00:00Z",
            coverage_end="2027-06-01T00:00:00Z",
            committed_uptime_percent=99.5,
            monthly_fee_cents=700_000,
        )
        resp = api_client.activate_service_contract(contract_c["id"], FA)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)
        after = validate_success(api_client.get_service_contract(contract_c["id"], FA))
        assert after["contract_state"] == "DRAFT"


class TestContractWindowAndReconciliationRules:
    def test_empty_window_rejected_at_creation(self, api):
        """coverage_end equal to coverage_start is not after it: the creation
        itself is rejected.

        PRD §3.6: "Creation itself rejects a window whose `coverage_end` is not after its `coverage_start` with `ERR_CONTRACT_WINDOW_INVALID` (HTTP 422), and the contract starts in `DRAFT` with `credits_issued_ytd_cents` at 0, `last_reconciliation_end` null, and `terminated_reason` null."

        Design: Corner/validations/contract_window_invalid_rejected
        """
        account = create_account()
        instrument = create_instrument(account_id=account["id"])
        resp = api_client.create_service_contract(
            create_service_contract_payload(
                account["id"],
                instrument["id"],
                coverage_start="2026-09-01T00:00:00Z",
                coverage_end="2026-09-01T00:00:00Z",
            ),
            FA,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_INVALID)

    def test_overlapping_reconciliation_period_rejected(self, api):
        """A clean-downtime-free first reconciliation posts zero credit; a
        second period starting before the first one's end is rejected —
        periods must chain without overlap.

        PRD §3.6: "The submitted `period_start` and `period_end` must describe a legitimate window: `period_start` strictly before `period_end`, `period_end` not after the current logical clock, and — once a first reconciliation has happened — `period_start` at or after `last_reconciliation_end` so windows never overlap or reach into the future; violations are `ERR_RECONCILIATION_PERIOD_INVALID` (HTTP 422)."
        PRD §3.6: "If the measured uptime meets or exceeds `committed_uptime_percent` the credit is zero — hitting the commitment exactly pays nothing."

        Design: Corner/validations/reconciliation_period_overlap_rejected
        """
        bag = setup_active_contract_scenario()
        advance_clock("2026-09-01T16:40:00Z")
        first = validate_success(
            _reconcile(
                bag["contract"]["id"],
                "2026-09-01T00:00:00Z",
                "2026-09-01T16:40:00Z",
            ),
            201,
        )
        assert first["credit_cents"] == 0  # no downtime -> uptime 100.00
        resp = _reconcile(
            bag["contract"]["id"], "2026-09-01T15:00:00Z", "2026-09-01T16:40:00Z"
        )
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_PERIOD_INVALID)

    def test_contract_expiry_sweep(self, api):
        """An ACTIVE contract whose coverage_end the clock reaches flips to
        EXPIRED via the sweep, with no direct call on the contract.

        PRD §2.4: "Service contracts still `ACTIVE` whose `coverage_end` has been reached become `EXPIRED`."

        Design: Corner/state_machines/contract_expiry_sweep
        """
        account = create_account()
        instrument = create_instrument(account_id=account["id"])
        contract = create_active_contract(
            account_id=account["id"],
            instrument_id=instrument["id"],
            coverage_start="2026-09-01T00:00:00Z",
            coverage_end="2026-09-10T00:00:00Z",
        )
        result = advance_clock("2026-09-10T00:00:00Z")
        assert result["contracts_expired"] == 1
        after = validate_success(
            api_client.get_service_contract(contract["id"], FA)
        )
        assert after["contract_state"] == "EXPIRED"
