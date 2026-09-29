"""Typed HTTP surface for the milk bank API.

One method per documented operation, each returning the raw response so the
caller decides whether it expects a success envelope or an error envelope. Every
path is rooted at the `/milk-bank` prefix.

Money and volume arguments are passed through untouched, so callers must supply
integers for cent and millilitre fields — the API never accepts a monetary value
as a string.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/milk-bank"

Headers = Dict[str, str]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint methods for the Human Milk Bank Screening Pasteurization API."""

    # -- Donors ------------------------------------------------------------
    def create_donor(self, payload: Payload, headers: Headers):
        return self._request("POST", f"{BASE}/donors", payload=payload, headers=headers)

    def list_donors(self, headers: Headers, params: Params = None):
        return self._request("GET", f"{BASE}/donors", headers=headers, params=params)

    def get_donor(self, donor_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/donors/{donor_id}", headers=headers)

    def submit_health_history(self, donor_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/health-history", payload=payload, headers=headers
        )

    def list_health_history(self, donor_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"{BASE}/donors/{donor_id}/health-history", headers=headers, params=params
        )

    def record_serology_panel(self, donor_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/serology-panels", payload=payload, headers=headers
        )

    def list_serology_panels(self, donor_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"{BASE}/donors/{donor_id}/serology-panels", headers=headers, params=params
        )

    def record_physician_approval(self, donor_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST",
            f"{BASE}/donors/{donor_id}/physician-approvals",
            payload=payload,
            headers=headers,
        )

    def list_physician_approvals(self, donor_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"{BASE}/donors/{donor_id}/physician-approvals", headers=headers, params=params
        )

    def qualify_donor(self, donor_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/qualify", payload=payload or {}, headers=headers
        )

    def requalify_donor(self, donor_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/requalify", payload=payload or {}, headers=headers
        )

    def record_deferral(self, donor_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/donors/{donor_id}/deferrals", payload=payload, headers=headers
        )

    def list_deferrals(self, donor_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"{BASE}/donors/{donor_id}/deferrals", headers=headers, params=params
        )

    # -- Shipments ---------------------------------------------------------
    def create_shipment(self, payload: Payload, headers: Headers):
        return self._request("POST", f"{BASE}/shipments", payload=payload, headers=headers)

    def list_shipments(self, headers: Headers, params: Params = None):
        return self._request("GET", f"{BASE}/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/shipments/{shipment_id}", headers=headers)

    def receive_shipment(self, shipment_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/shipments/{shipment_id}/receive", payload=payload, headers=headers
        )

    def disposition_shipment(self, shipment_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/shipments/{shipment_id}/disposition", payload=payload, headers=headers
        )

    def log_donation(self, shipment_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/shipments/{shipment_id}/donations", payload=payload, headers=headers
        )

    # -- Donations ---------------------------------------------------------
    def list_donations(self, headers: Headers, params: Params = None):
        return self._request("GET", f"{BASE}/donations", headers=headers, params=params)

    def get_donation(self, donation_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/donations/{donation_id}", headers=headers)

    def list_donation_components(self, donation_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET",
            f"{BASE}/donations/{donation_id}/pool-components",
            headers=headers,
            params=params,
        )

    # -- Pools -------------------------------------------------------------
    def create_pool(self, payload: Payload, headers: Headers):
        return self._request("POST", f"{BASE}/pools", payload=payload, headers=headers)

    def list_pools(self, headers: Headers, params: Params = None):
        return self._request("GET", f"{BASE}/pools", headers=headers, params=params)

    def get_pool(self, pool_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/pools/{pool_id}", headers=headers)

    def add_pool_component(self, pool_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/pools/{pool_id}/components", payload=payload, headers=headers
        )

    def list_pool_components(self, pool_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"{BASE}/pools/{pool_id}/components", headers=headers, params=params
        )

    def commit_pool(self, pool_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST", f"{BASE}/pools/{pool_id}/commit", payload=payload or {}, headers=headers
        )

    def scrap_pool(self, pool_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST", f"{BASE}/pools/{pool_id}/scrap", payload=payload or {}, headers=headers
        )

    # -- Pasteurization runs ----------------------------------------------
    def create_run(self, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/pasteurization-runs", payload=payload, headers=headers
        )

    def list_runs(self, headers: Headers, params: Params = None):
        return self._request("GET", f"{BASE}/pasteurization-runs", headers=headers, params=params)

    def get_run(self, run_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/pasteurization-runs/{run_id}", headers=headers)

    def append_reading(self, run_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST",
            f"{BASE}/pasteurization-runs/{run_id}/readings",
            payload=payload,
            headers=headers,
        )

    def list_readings(self, run_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"{BASE}/pasteurization-runs/{run_id}/readings", headers=headers, params=params
        )

    def complete_run(self, run_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST",
            f"{BASE}/pasteurization-runs/{run_id}/complete",
            payload=payload or {},
            headers=headers,
        )

    def record_culture(self, run_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST",
            f"{BASE}/pasteurization-runs/{run_id}/culture",
            payload=payload,
            headers=headers,
        )

    def bottle_lot(self, run_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"{BASE}/pasteurization-runs/{run_id}/lots", payload=payload, headers=headers
        )

    # -- Milk lots ---------------------------------------------------------
    def list_milk_lots(self, headers: Headers, params: Params = None):
        return self._request("GET", f"{BASE}/milk-lots", headers=headers, params=params)

    def get_milk_lot(self, lot_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/milk-lots/{lot_id}", headers=headers)

    def list_lot_dispenses(self, lot_id: str, headers: Headers, params: Params = None):
        return self._request(
            "GET", f"{BASE}/milk-lots/{lot_id}/dispenses", headers=headers, params=params
        )

    def release_milk_lot(self, lot_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST", f"{BASE}/milk-lots/{lot_id}/release", payload=payload or {}, headers=headers
        )

    # -- Subsidy programs --------------------------------------------------
    def create_subsidy_program(self, payload: Payload, headers: Headers):
        return self._request("POST", f"{BASE}/subsidy-programs", payload=payload, headers=headers)

    def get_subsidy_program(self, program_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/subsidy-programs/{program_id}", headers=headers)

    # -- Prescriptions -----------------------------------------------------
    def create_prescription(self, payload: Payload, headers: Headers):
        return self._request("POST", f"{BASE}/prescriptions", payload=payload, headers=headers)

    def list_prescriptions(self, headers: Headers, params: Params = None):
        return self._request("GET", f"{BASE}/prescriptions", headers=headers, params=params)

    def get_prescription(self, prescription_id: str, headers: Headers):
        return self._request("GET", f"{BASE}/prescriptions/{prescription_id}", headers=headers)

    def list_prescription_dispenses(
        self, prescription_id: str, headers: Headers, params: Params = None
    ):
        return self._request(
            "GET",
            f"{BASE}/prescriptions/{prescription_id}/dispenses",
            headers=headers,
            params=params,
        )

    def create_dispense(self, prescription_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST",
            f"{BASE}/prescriptions/{prescription_id}/dispenses",
            payload=payload,
            headers=headers,
        )

    def cancel_prescription(self, prescription_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST",
            f"{BASE}/prescriptions/{prescription_id}/cancel",
            payload=payload or {},
            headers=headers,
        )

    # -- Dispenses ---------------------------------------------------------
    def void_dispense(self, dispense_id: str, headers: Headers, payload: Payload = None):
        return self._request(
            "POST", f"{BASE}/dispenses/{dispense_id}/void", payload=payload or {}, headers=headers
        )

    # -- Allocation cycles and the logical clock --------------------------
    def run_allocation_cycle(self, headers: Headers, payload: Payload = None):
        return self._request(
            "POST", f"{BASE}/allocation-cycles", payload=payload or {}, headers=headers
        )

    def set_clock(self, current_utc: str, headers: Headers):
        return self._request(
            "POST",
            f"{BASE}/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    # -- Raw escape hatch --------------------------------------------------
    def post_raw(self, path: str, payload: Payload, headers: Headers):
        """POST an arbitrary body to an arbitrary sub-path, for shape probes."""
        return self._request("POST", f"{BASE}{path}", payload=payload, headers=headers)

    def get_raw(self, path: str, headers: Headers, params: Params = None):
        """GET an arbitrary sub-path, for existence and scope probes."""
        return self._request("GET", f"{BASE}{path}", headers=headers, params=params)


api_client = ApiClient()
