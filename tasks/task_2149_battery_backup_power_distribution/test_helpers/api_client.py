"""API client: one method per endpoint published by the PRD.

Every path is mounted under the /distribution prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/distribution"


class ApiClient(GenericApiClient):
    # ---- Accounts -------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    # ---- Battery models -------------------------------------------------
    def create_battery_model(self, payload, headers):
        return self._request("POST", f"{PREFIX}/battery-models", payload, headers)

    def get_battery_model(self, battery_model_id, headers):
        return self._request(
            "GET", f"{PREFIX}/battery-models/{battery_model_id}", headers=headers
        )

    def list_battery_models(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/battery-models", headers=headers, params=params)

    def discontinue_battery_model(self, battery_model_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/battery-models/{battery_model_id}/discontinue",
            payload,
            headers,
        )

    # ---- Warehouses -----------------------------------------------------
    def create_warehouse(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"{PREFIX}/warehouses/{warehouse_id}", headers=headers)

    # ---- Carriers -------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{PREFIX}/carriers/{carrier_id}", headers=headers)

    # ---- Inventory lots -------------------------------------------------
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inventory-lots", payload, headers)

    def get_inventory_lot(self, inventory_lot_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inventory-lots/{inventory_lot_id}", headers=headers
        )

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inventory-lots", headers=headers, params=params)

    def refresh_charge_lot(self, inventory_lot_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/inventory-lots/{inventory_lot_id}/refresh-charge",
            payload,
            headers,
        )

    def scrap_lot(self, inventory_lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inventory-lots/{inventory_lot_id}/scrap", payload, headers
        )

    # ---- Orders ---------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"{PREFIX}/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/order-lines", headers=headers, params=params)

    def submit_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/submit", payload or {}, headers
        )

    def allocate_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/allocate", payload or {}, headers
        )

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/cancel", payload, headers)

    # ---- Shipments ------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shipments", headers=headers, params=params)

    def certify_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/certify", payload, headers
        )

    def dispatch_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/dispatch", payload or {}, headers
        )

    def deliver_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/deliver", payload or {}, headers
        )

    # ---- Core returns ---------------------------------------------------
    def create_core_return(self, payload, headers):
        return self._request("POST", f"{PREFIX}/core-returns", payload, headers)

    def get_core_return(self, core_return_id, headers):
        return self._request("GET", f"{PREFIX}/core-returns/{core_return_id}", headers=headers)

    def list_core_returns(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/core-returns", headers=headers, params=params)

    def inspect_core_return(self, core_return_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/core-returns/{core_return_id}/inspect", payload, headers
        )

    def dispute_core_return(self, core_return_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/core-returns/{core_return_id}/dispute", payload, headers
        )

    def credit_core_return(self, core_return_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/core-returns/{core_return_id}/credit", payload or {}, headers
        )

    # ---- Warranty claims ------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, warranty_claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims/{warranty_claim_id}", headers=headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-claims", headers=headers, params=params)

    def adjudicate_warranty_claim(self, warranty_claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/warranty-claims/{warranty_claim_id}/adjudicate",
            payload or {},
            headers,
        )

    def settle_warranty_claim(self, warranty_claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{warranty_claim_id}/settle", payload, headers
        )

    # ---- Service contracts ----------------------------------------------
    def create_service_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-contracts", payload, headers)

    def get_service_contract(self, service_contract_id, headers):
        return self._request(
            "GET", f"{PREFIX}/service-contracts/{service_contract_id}", headers=headers
        )

    def list_service_contracts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-contracts", headers=headers, params=params
        )

    def size_service_contract(self, service_contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/service-contracts/{service_contract_id}/size",
            payload or {},
            headers,
        )

    def attach_service_contract(self, service_contract_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/service-contracts/{service_contract_id}/attach",
            payload,
            headers,
        )

    # ---- Storm events ---------------------------------------------------
    def create_storm_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storm-events", payload, headers)

    def get_storm_event(self, storm_event_id, headers):
        return self._request("GET", f"{PREFIX}/storm-events/{storm_event_id}", headers=headers)

    def open_storm_allocation(self, storm_event_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/storm-events/{storm_event_id}/open-allocation",
            payload or {},
            headers,
        )

    def close_storm_event(self, storm_event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/storm-events/{storm_event_id}/close", payload or {}, headers
        )

    # ---- Disposal manifests ---------------------------------------------
    def create_disposal_manifest(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disposal-manifests", payload, headers)

    def get_disposal_manifest(self, disposal_manifest_id, headers):
        return self._request(
            "GET", f"{PREFIX}/disposal-manifests/{disposal_manifest_id}", headers=headers
        )

    def list_disposal_manifests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/disposal-manifests", headers=headers, params=params
        )

    def attach_core_return_to_manifest(self, disposal_manifest_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/disposal-manifests/{disposal_manifest_id}/attach-core-return",
            payload,
            headers,
        )

    def submit_disposal_manifest(self, disposal_manifest_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/disposal-manifests/{disposal_manifest_id}/submit",
            payload or {},
            headers,
        )

    def file_disposal_manifest(self, disposal_manifest_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/disposal-manifests/{disposal_manifest_id}/file",
            payload or {},
            headers,
        )

    def reject_disposal_manifest(self, disposal_manifest_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/disposal-manifests/{disposal_manifest_id}/reject",
            payload,
            headers,
        )

    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
