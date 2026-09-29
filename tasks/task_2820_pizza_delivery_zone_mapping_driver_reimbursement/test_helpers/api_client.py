"""API client: one method per endpoint of the Store Operations API.

Every path is mounted beneath the ``/store-ops`` prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/store-ops"


class ApiClient(GenericApiClient):
    """Endpoint methods. Every method returns the raw ``requests.Response``."""

    # --- Logical clock --------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # --- Stores ---------------------------------------------------------------
    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/stores", payload, headers)

    def update_store(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"{BASE}/stores/{store_id}", payload, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/stores/{store_id}", headers=headers)

    def get_cash_reconciliation(self, store_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/stores/{store_id}/cash-reconciliation", headers=headers
        )

    # --- Delivery-area versions ----------------------------------------------
    def create_zone_version(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/zone-versions", payload, headers)

    def activate_zone_version(self, zone_version_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/zone-versions/{zone_version_id}/activate", None, headers
        )

    def get_zone_version(self, zone_version_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/zone-versions/{zone_version_id}", headers=headers)

    def list_zone_versions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/zone-versions", headers=headers, params=params)

    # --- Service addresses ----------------------------------------------------
    def create_service_address(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/service-addresses", payload, headers)

    def get_service_address(self, service_address_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/service-addresses/{service_address_id}", headers=headers
        )

    def list_service_addresses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/service-addresses", headers=headers, params=params)

    # --- Address disputes -----------------------------------------------------
    def create_address_dispute(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/address-disputes", payload, headers)

    def review_address_dispute(
        self, address_dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/address-disputes/{address_dispute_id}/review", payload, headers
        )

    def get_address_dispute(self, address_dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/address-disputes/{address_dispute_id}", headers=headers
        )

    def list_address_disputes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/address-disputes", headers=headers, params=params)

    # --- Drivers --------------------------------------------------------------
    def create_driver(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/drivers", payload, headers)

    def create_mvr_check(self, driver_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/drivers/{driver_id}/mvr-checks", payload, headers)

    def create_insurance_verification(
        self, driver_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/drivers/{driver_id}/insurance-verifications", payload, headers
        )

    def create_qualification_decision(
        self, driver_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/drivers/{driver_id}/qualification-decisions", payload, headers
        )

    def get_driver(self, driver_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/drivers", headers=headers, params=params)

    def get_mvr_check(self, mvr_check_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/mvr-checks/{mvr_check_id}", headers=headers)

    def list_mvr_checks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/mvr-checks", headers=headers, params=params)

    def get_insurance_verification(self, insurance_verification_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/insurance-verifications/{insurance_verification_id}", headers=headers
        )

    def list_insurance_verifications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{BASE}/insurance-verifications", headers=headers, params=params
        )

    # --- Vehicle cost models --------------------------------------------------
    def create_vehicle_cost_model(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/vehicle-cost-models", payload, headers)

    def get_vehicle_cost_model(self, vehicle_cost_model_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/vehicle-cost-models/{vehicle_cost_model_id}", headers=headers
        )

    def list_vehicle_cost_models(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/vehicle-cost-models", headers=headers, params=params)

    # --- Safe drops -----------------------------------------------------------
    def create_safe_drop(self, driver_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/drivers/{driver_id}/safe-drops", payload, headers)

    def void_safe_drop(self, safe_drop_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/safe-drops/{safe_drop_id}/void", payload, headers)

    def get_safe_drop(self, safe_drop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/safe-drops/{safe_drop_id}", headers=headers)

    def list_safe_drops(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/safe-drops", headers=headers, params=params)

    # --- Orders ---------------------------------------------------------------
    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/orders", payload, headers)

    def zone_decision(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/orders/{order_id}/zone-decision", payload, headers)

    def disclose_fee(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/orders/{order_id}/disclose-fee", payload, headers)

    def production(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/orders/{order_id}/production", payload, headers)

    def remake_order(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/orders/{order_id}/remake", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/orders/{order_id}", headers=headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/orders", headers=headers, params=params)

    # --- Routes (dispatches) --------------------------------------------------
    def create_dispatch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dispatches", payload, headers)

    def create_dispatch_stop(
        self, dispatch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/dispatches/{dispatch_id}/stops", payload, headers)

    def delete_dispatch_stop(
        self, dispatch_id: str, dispatch_stop_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "DELETE", f"{BASE}/dispatches/{dispatch_id}/stops/{dispatch_stop_id}", headers=headers
        )

    def lock_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dispatches/{dispatch_id}/lock", None, headers)

    def unlock_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dispatches/{dispatch_id}/unlock", None, headers)

    def depart_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dispatches/{dispatch_id}/depart", None, headers)

    def door_arrival(
        self,
        dispatch_id: str,
        dispatch_stop_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/dispatches/{dispatch_id}/stops/{dispatch_stop_id}/door-arrival",
            payload,
            headers,
        )

    def return_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dispatches/{dispatch_id}/return", None, headers)

    def settle_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dispatches/{dispatch_id}/settle", None, headers)

    def recall_dispatch(self, dispatch_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/dispatches/{dispatch_id}/recall", payload, headers)

    def get_dispatch(self, dispatch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/dispatches", headers=headers, params=params)

    def get_dispatch_stop(self, dispatch_stop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/dispatch-stops/{dispatch_stop_id}", headers=headers)

    def list_dispatch_stops(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/dispatch-stops", headers=headers, params=params)

    # --- Reimbursement ledger -------------------------------------------------
    def get_reimbursement_line(self, reimbursement_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/reimbursement-lines/{reimbursement_line_id}", headers=headers
        )

    def list_reimbursement_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/reimbursement-lines", headers=headers, params=params)

    # --- Complaints -----------------------------------------------------------
    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/complaints", payload, headers)

    def propose_remedy(
        self, complaint_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "POST", f"{BASE}/complaints/{complaint_id}/propose-remedy", payload or {}, headers
        )

    def resolve_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/complaints/{complaint_id}/resolve", payload, headers
        )

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/complaints", headers=headers, params=params)


api_client = ApiClient()
