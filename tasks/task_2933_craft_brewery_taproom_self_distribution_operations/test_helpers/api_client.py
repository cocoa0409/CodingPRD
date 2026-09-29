"""One method per endpoint of PRD §4.

All fifty-eight endpoints are rooted at the service origin with no version or
namespace prefix. The base ``_request`` plumbing, session handling and
``API_BASE_URL`` resolution are inherited from the shared framework client.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP client covering every endpoint in the contract."""

    # -- Logical clock (§2.5) ----------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Brewery singleton (§3.1) ------------------------------------------
    def create_brewery(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/brewery", payload, headers)

    def get_brewery(self, headers: Dict[str, str]):
        return self._request("GET", "/brewery", None, headers)

    def drive_notice(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/brewery/notice", payload, headers)

    def set_brewery_ytd_adjustments(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/brewery/ytd-adjustments", payload, headers)

    # -- Beers (§3.1) -------------------------------------------------------
    def create_beer(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/beers", payload, headers)

    def get_beer(self, beer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/beers/{beer_id}", None, headers)

    def list_beers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/beers", params, headers)

    def create_beer_filing(self, beer_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/beers/{beer_id}/filings", payload, headers)

    def decide_beer_filing(
        self, beer_id: str, filing_type: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/beers/{beer_id}/filings/{filing_type}/decision",
            payload,
            headers,
        )

    # -- Tanks (§3.2) -------------------------------------------------------
    def create_tank(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/tanks", payload, headers)

    def get_tank(self, tank_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tanks/{tank_id}", None, headers)

    def list_tanks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/tanks", params, headers)

    def service_tank(self, tank_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/tanks/{tank_id}/service", payload, headers)

    # -- Batches (§3.2) -----------------------------------------------------
    def create_batch(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/batches", payload, headers)

    def get_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/batches/{batch_id}", None, headers)

    def list_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/batches", params, headers)

    def start_batch(self, batch_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/batches/{batch_id}/start", payload, headers)

    def condition_batch(self, batch_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/batches/{batch_id}/condition", payload, headers)

    def dump_batch(self, batch_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/batches/{batch_id}/dump", payload, headers)

    # -- Packaging runs (§3.3) ---------------------------------------------
    def create_packaging_run(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/packaging-runs", payload, headers)

    def get_packaging_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/packaging-runs/{run_id}", None, headers)

    def list_packaging_runs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/packaging-runs", params, headers)

    def complete_packaging_run(self, run_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/packaging-runs/{run_id}/complete", payload, headers
        )

    def void_packaging_run(
        self, run_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request("POST", f"/packaging-runs/{run_id}/void", payload, headers)

    # -- Keg assets (§3.4) --------------------------------------------------
    def create_keg_asset(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/keg-assets", payload, headers)

    def get_keg_asset(self, keg_asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/keg-assets/{keg_asset_id}", None, headers)

    def list_keg_assets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/keg-assets", params, headers)

    def clean_keg_asset(self, keg_asset_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/keg-assets/{keg_asset_id}/clean", payload, headers
        )

    def fill_keg_asset(self, keg_asset_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/keg-assets/{keg_asset_id}/fill", payload, headers
        )

    def move_keg_asset(self, keg_asset_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/keg-assets/{keg_asset_id}/movements", payload, headers
        )

    # -- Taproom pours (§3.5) ----------------------------------------------
    def create_taproom_pour(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/taproom-pours", payload, headers)

    def get_taproom_pour(self, pour_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/taproom-pours/{pour_id}", None, headers)

    def list_taproom_pours(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/taproom-pours", params, headers)

    # -- State licences (§3.6) ---------------------------------------------
    def create_state_license(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/state-licenses", payload, headers)

    def get_state_license(self, state_license_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/state-licenses/{state_license_id}", None, headers)

    def list_state_licenses(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/state-licenses", params, headers)

    def set_license_ytd_adjustments(
        self, state_license_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/state-licenses/{state_license_id}/ytd-adjustments",
            payload,
            headers,
        )

    # -- Distributor appointments (§3.6) -----------------------------------
    def create_distributor_appointment(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/distributor-appointments", payload, headers)

    def get_distributor_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/distributor-appointments/{appointment_id}", None, headers
        )

    def list_distributor_appointments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/distributor-appointments", params, headers)

    def approve_appointment(
        self, appointment_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST",
            f"/distributor-appointments/{appointment_id}/approve",
            payload,
            headers,
        )

    def terminate_appointment(
        self, appointment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/distributor-appointments/{appointment_id}/termination",
            payload,
            headers,
        )

    # -- Distribution orders (§3.7) ----------------------------------------
    def create_distribution_order(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/distribution-orders", payload, headers)

    def get_distribution_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/distribution-orders/{order_id}", None, headers)

    def list_distribution_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/distribution-orders", params, headers)

    def allocate_order(self, order_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/distribution-orders/{order_id}/allocate", payload, headers
        )

    def ship_order(self, order_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/distribution-orders/{order_id}/ship", payload, headers
        )

    def cancel_order(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/distribution-orders/{order_id}/cancel", payload, headers
        )

    # -- Excise reports (§3.8) ---------------------------------------------
    def create_excise_report(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/excise-reports", payload, headers)

    def get_excise_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/excise-reports/{report_id}", None, headers)

    def list_excise_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/excise-reports", params, headers)

    def file_excise_report(
        self, report_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/excise-reports/{report_id}/file", payload, headers
        )

    # -- Event permits (§3.9) ----------------------------------------------
    def create_event_permit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/event-permits", payload, headers)

    def get_event_permit(self, permit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/event-permits/{permit_id}", None, headers)

    def list_event_permits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/event-permits", params, headers)

    def submit_event_permit(
        self, permit_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/event-permits/{permit_id}/submit", payload, headers
        )

    def decide_event_permit(self, permit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/event-permits/{permit_id}/decision", payload, headers
        )
