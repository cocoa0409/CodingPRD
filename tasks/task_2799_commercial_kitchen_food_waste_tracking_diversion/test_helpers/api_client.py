"""One method per endpoint of the food waste diversion API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, endpoint-per-method wrapper over the generic HTTP client."""

    # ---------------------------------------------------------------- sites
    def create_site(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/sites", payload=payload, headers=headers)

    def get_site(self, site_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/sites", headers=headers, params=params or None)

    # ----------------------------------------------------------- food types
    def create_food_type(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/food-types", payload=payload, headers=headers)

    def get_food_type(self, food_type_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/food-types/{food_type_id}", headers=headers)

    def list_food_types(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/food-types", headers=headers, params=params or None)

    # -------------------------------------------------------------- recipes
    def create_recipe(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/recipes", payload=payload, headers=headers)

    def publish_recipe(self, recipe_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/recipes/{recipe_id}/publish", payload={}, headers=headers)

    def get_recipe(self, recipe_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def list_recipes(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/recipes", headers=headers, params=params or None)

    # ---------------------------------------------------- tracking stations
    def create_tracking_station(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/tracking-stations", payload=payload, headers=headers)

    def set_station_status(
        self, station_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/tracking-stations/{station_id}/status", payload=payload, headers=headers)

    def get_tracking_station(self, station_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/tracking-stations/{station_id}", headers=headers)

    def list_tracking_stations(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/tracking-stations", headers=headers, params=params or None)

    # ------------------------------------------------------- service periods
    def create_shift(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/shifts", payload=payload, headers=headers)

    def close_shift(self, shift_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/shifts/{shift_id}/close", payload={}, headers=headers)

    def get_shift(self, shift_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/shifts", headers=headers, params=params or None)

    # --------------------------------------------------------- waste entries
    def create_waste_entry(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/waste-entries", payload=payload, headers=headers)

    def flag_waste_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/waste-entries/{entry_id}/flag", payload=payload, headers=headers)

    def clear_waste_entry_flag(self, entry_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/waste-entries/{entry_id}/clear-flag", payload={}, headers=headers)

    def void_waste_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/waste-entries/{entry_id}/void", payload=payload, headers=headers)

    def correct_waste_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/waste-entries/{entry_id}/corrections", payload=payload, headers=headers)

    def get_waste_entry(self, entry_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/waste-entries/{entry_id}", headers=headers)

    def list_waste_entries(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/waste-entries", headers=headers, params=params or None)

    # ------------------------------------------------------ baseline periods
    def create_baseline_period(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/baseline-periods", payload=payload, headers=headers)

    def submit_baseline_period(self, baseline_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/baseline-periods/{baseline_id}/submit", payload={}, headers=headers)

    def certify_baseline_period(self, baseline_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/baseline-periods/{baseline_id}/certify", payload={}, headers=headers)

    def reject_baseline_period(
        self, baseline_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/baseline-periods/{baseline_id}/reject", payload=payload, headers=headers)

    def get_baseline_period(self, baseline_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/baseline-periods/{baseline_id}", headers=headers)

    def list_baseline_periods(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/baseline-periods", headers=headers, params=params or None)

    # ----------------------------------------------------- reduction targets
    def create_reduction_target(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/reduction-targets", payload=payload, headers=headers)

    def activate_reduction_target(self, target_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/reduction-targets/{target_id}/activate", payload={}, headers=headers)

    def get_reduction_target(self, target_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/reduction-targets/{target_id}", headers=headers)

    def list_reduction_targets(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/reduction-targets", headers=headers, params=params or None)

    def get_target_attainment(self, target_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/reduction-targets/{target_id}/attainment", headers=headers)

    # -------------------------------------------------------------- haulers
    def create_hauler(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/haulers", payload=payload, headers=headers)

    def approve_hauler(self, hauler_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/haulers/{hauler_id}/approve", payload={}, headers=headers)

    def get_hauler(self, hauler_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/haulers/{hauler_id}", headers=headers)

    def list_haulers(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/haulers", headers=headers, params=params or None)

    # ------------------------------------------------ diversion consignments
    def create_consignment(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/diversion-consignments", payload=payload, headers=headers)

    def stage_consignment(self, consignment_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/diversion-consignments/{consignment_id}/stage", payload={}, headers=headers)

    def dispatch_consignment(self, consignment_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/diversion-consignments/{consignment_id}/dispatch", payload={}, headers=headers)

    def cancel_consignment(
        self, consignment_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/diversion-consignments/{consignment_id}/cancel", payload=payload, headers=headers
        )

    def get_consignment(self, consignment_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/diversion-consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/diversion-consignments", headers=headers, params=params or None)

    # ----------------------------------------------------- consignment lines
    def create_consignment_line(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/consignment-lines", payload=payload, headers=headers)

    def delete_consignment_line(self, line_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("DELETE", f"/consignment-lines/{line_id}", headers=headers)

    def get_consignment_line(self, line_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/consignment-lines/{line_id}", headers=headers)

    def list_consignment_lines(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/consignment-lines", headers=headers, params=params or None)

    # -------------------------------------------------------- hauler tickets
    def create_hauler_ticket(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/hauler-tickets", payload=payload, headers=headers)

    def accept_hauler_ticket(self, ticket_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/hauler-tickets/{ticket_id}/accept", payload={}, headers=headers)

    def dispute_hauler_ticket(
        self, ticket_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/hauler-tickets/{ticket_id}/dispute", payload=payload, headers=headers)

    def get_hauler_ticket(self, ticket_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/hauler-tickets/{ticket_id}", headers=headers)

    def list_hauler_tickets(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/hauler-tickets", headers=headers, params=params or None)

    # -------------------------------------------------------- coaching alerts
    def acknowledge_alert(self, alert_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/coaching-alerts/{alert_id}/acknowledge", payload={}, headers=headers)

    def resolve_alert(
        self, alert_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/coaching-alerts/{alert_id}/resolve", payload=payload, headers=headers)

    def get_alert(self, alert_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/coaching-alerts/{alert_id}", headers=headers)

    def list_alerts(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/coaching-alerts", headers=headers, params=params or None)

    # ---------------------------------------------------------- data quality
    def create_data_quality_scan(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/data-quality-scans", payload=payload, headers=headers)

    def resolve_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/data-quality-findings/{finding_id}/resolve", payload=payload, headers=headers)

    def get_finding(self, finding_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/data-quality-findings/{finding_id}", headers=headers)

    def list_findings(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/data-quality-findings", headers=headers, params=params or None)

    # ------------------------------------------------------ corporate rollups
    def create_rollup(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/corporate-rollups", payload=payload, headers=headers)

    def publish_rollup(self, rollup_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", f"/corporate-rollups/{rollup_id}/publish", payload={}, headers=headers)

    def get_rollup(self, rollup_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/corporate-rollups/{rollup_id}", headers=headers)

    def list_rollups(self, headers: Optional[Dict[str, str]] = None, **params: Any) -> requests.Response:
        return self._request("GET", "/corporate-rollups", headers=headers, params=params or None)

    # ---------------------------------------------------------- logical clock
    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        """Set the server's logical clock. Open to any caller; no identity headers required."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers or {"Content-Type": "application/json"},
        )

    def raw_post(
        self, path: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Escape hatch for deliberately malformed requests against a known path."""
        return self._request("POST", path, payload=payload, headers=headers)

    def raw_get(
        self, path: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """Escape hatch for reads whose path is assembled by the test itself."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
