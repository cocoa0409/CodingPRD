"""Contract window overlap semantics and interruptible-cap boundary
(PRD §3.2).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    assert_interrupt_event,
    create_active_contract,
    create_interrupt_event_payload,
    create_power_contract_payload,
    create_smelter,
    setup_site,
    validate_error,
    validate_success,
)

INTERRUPTIBLE_50_CAP500 = [
    {"component_type": "INTERRUPTIBLE", "volume_mw": 50, "interruptible_cap_hours_per_year": 500},
]


class TestContractWindowAdjacency:
    def _setup_three_contracts(self, api, energy_manager_headers):
        smelter = create_smelter()
        c1 = create_active_contract(smelter["id"])  # [2026-01-01, 2027-01-01)
        c2 = validate_success(
            api.create_power_contract(
                create_power_contract_payload(
                    smelter["id"], supplier_name="Chelan",
                    window_start="2027-01-01T00:00:00Z", window_end="2028-01-01T00:00:00Z",
                    components=[{"component_type": "FIXED", "volume_mw": 200,
                                 "fixed_price_per_mwh": 35.00}],
                ),
                energy_manager_headers,
            ),
            201,
        )
        c3 = validate_success(
            api.create_power_contract(
                create_power_contract_payload(
                    smelter["id"], supplier_name="Grant",
                    window_start="2026-12-31T00:00:00Z", window_end="2027-07-01T00:00:00Z",
                    components=[{"component_type": "FIXED", "volume_mw": 100,
                                 "fixed_price_per_mwh": 30.00}],
                ),
                energy_manager_headers,
            ),
            201,
        )
        return smelter, c1, c2, c3

    def test_touching_windows_do_not_overlap(self, api, energy_manager_headers):
        """PRD §3.2: "touching windows, where one contract's `window_end`
        equals the other's `window_start`, do not overlap and are allowed."

        Design: Difficulty/resource_temporal_overlap/power_contract_half_open_adjacency
        """
        _, _, c2, _ = self._setup_three_contracts(api, energy_manager_headers)
        data = validate_success(api.activate_power_contract(c2["id"], energy_manager_headers))
        assert data["status"] == "ACTIVE"

    def test_overlapping_window_rejected(self, api, energy_manager_headers):
        """PRD §3.2: "An overlapping activation is rejected with
        `ERR_CONTRACT_WINDOW_OVERLAP` (HTTP 409), while activating a contract
        that is not `DRAFT` is rejected with `ERR_INVALID_LIFECYCLE_STATE`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/power_contract_half_open_adjacency
        """
        _, _, _, c3 = self._setup_three_contracts(api, energy_manager_headers)
        resp = api.activate_power_contract(c3["id"], energy_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)
        data = validate_success(api.get_power_contract(c3["id"], energy_manager_headers))
        assert data["status"] == "DRAFT"

    def test_activate_twice_rejected(self, api, energy_manager_headers):
        """PRD §3.2: "activating a contract that is not `DRAFT` is rejected
        with `ERR_INVALID_LIFECYCLE_STATE` (HTTP 409)."

        Design: Corner/state_machines/contract_activate_twice_rejected
        """
        smelter = create_smelter()
        contract = create_active_contract(smelter["id"])
        resp = api.activate_power_contract(contract["id"], energy_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_LIFECYCLE_STATE)
        data = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        assert data["status"] == "ACTIVE"
        assert data["version"] == 2


class TestInterruptibleCap:
    def _setup_interruptible_contract(self):
        smelter = create_smelter()
        return create_active_contract(smelter["id"], components=INTERRUPTIBLE_50_CAP500)

    def test_cumulative_hours_reaching_cap_accepted(self, api, energy_manager_headers):
        """PRD §3.2: "the cumulative hours of all events whose `start_at`
        falls inside the current contract year — the 365-day window beginning
        on the anniversary of `window_start` that contains the current logical
        clock — must not exceed `interruptible_cap_hours_per_year`."
        PRD §3.2: "Landing exactly on the cap is allowed; exceeding it is
        rejected with `ERR_INTERRUPTIBLE_CAP_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/interruptible_hours_exactly_at_cap
        """
        contract = self._setup_interruptible_contract()
        ev1 = validate_success(
            api.create_interrupt_event(
                create_interrupt_event_payload(
                    contract["id"], start_at="2026-03-01T00:00:00Z",
                    end_at="2026-03-13T12:00:00Z", mw_reduced=50,
                ),
                energy_manager_headers,
            ),
            201,
        )
        assert_interrupt_event(ev1)
        assert ev1["hours"] == pytest.approx(300.0)

        ev2 = validate_success(
            api.create_interrupt_event(
                create_interrupt_event_payload(
                    contract["id"], start_at="2026-05-01T00:00:00Z",
                    end_at="2026-05-09T08:00:00Z", mw_reduced=50,
                ),
                energy_manager_headers,
            ),
            201,
        )
        assert ev2["hours"] == pytest.approx(200.0)

        data = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        assert data["interruptible_hours_used"] == pytest.approx(500.0)

    def test_hours_beyond_cap_rejected_and_not_accrued(self, api, energy_manager_headers):
        """PRD §3.2: "Landing exactly on the cap is allowed; exceeding it is
        rejected with `ERR_INTERRUPTIBLE_CAP_EXCEEDED` (HTTP 422)."
        PRD §3.2: "The contract's computed `interruptible_hours_used` exposes
        this running contract-year total on read."

        Design: Difficulty/boundary_precision_check/interruptible_hours_exactly_at_cap
        """
        contract = self._setup_interruptible_contract()
        for start, end in (("2026-03-01T00:00:00Z", "2026-03-13T12:00:00Z"),
                           ("2026-05-01T00:00:00Z", "2026-05-09T08:00:00Z")):
            resp = api.create_interrupt_event(
                create_interrupt_event_payload(contract["id"], start_at=start, end_at=end,
                                               mw_reduced=50),
                energy_manager_headers,
            )
            assert resp.status_code == 201, f"Setup failed: {resp.text}"

        resp = api.create_interrupt_event(
            create_interrupt_event_payload(
                contract["id"], start_at="2026-06-01T00:00:00Z",
                end_at="2026-06-01T00:30:00Z", mw_reduced=50,
            ),
            energy_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INTERRUPTIBLE_CAP_EXCEEDED)

        data = validate_success(api.get_power_contract(contract["id"], energy_manager_headers))
        assert data["interruptible_hours_used"] == pytest.approx(500.0)
