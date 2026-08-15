"""API client: one method per endpoint defined in the PRD (§4).

All paths carry the API's `/api` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/api/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/api/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/api/suppliers/{supplier_id}", headers=headers)

    def set_supplier_status(self, supplier_id, payload, headers):
        return self._request("PUT", f"/api/suppliers/{supplier_id}/status",
                             payload, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- Warehouses ---
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/api/warehouses", payload, headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", "/api/warehouses", headers=headers, params=params)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/api/warehouses/{warehouse_id}", headers=headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/api/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    # --- Yield specs ---
    def create_yield_spec(self, payload, headers):
        return self._request("POST", "/api/yield-specs", payload, headers)

    def list_yield_specs(self, headers, params=None):
        return self._request("GET", "/api/yield-specs", headers=headers, params=params)

    def get_yield_spec(self, yield_spec_id, headers):
        return self._request("GET", f"/api/yield-specs/{yield_spec_id}", headers=headers)

    # --- Price sheets and lines ---
    def create_price_sheet(self, payload, headers):
        return self._request("POST", "/api/price-sheets", payload, headers)

    def list_price_sheets(self, headers, params=None):
        return self._request("GET", "/api/price-sheets", headers=headers, params=params)

    def get_price_sheet(self, sheet_id, headers):
        return self._request("GET", f"/api/price-sheets/{sheet_id}", headers=headers)

    def add_sheet_line(self, sheet_id, payload, headers):
        return self._request("POST", f"/api/price-sheets/{sheet_id}/lines",
                             payload, headers)

    def list_sheet_lines(self, sheet_id, headers, params=None):
        return self._request("GET", f"/api/price-sheets/{sheet_id}/lines",
                             headers=headers, params=params)

    def list_price_sheet_lines(self, headers, params=None):
        return self._request("GET", "/api/price-sheet-lines",
                             headers=headers, params=params)

    def get_price_sheet_line(self, line_id, headers):
        return self._request("GET", f"/api/price-sheet-lines/{line_id}",
                             headers=headers)

    def publish_price_sheet(self, sheet_id, headers):
        return self._request("POST", f"/api/price-sheets/{sheet_id}/publish",
                             headers=headers)

    def close_price_sheet(self, sheet_id, headers):
        return self._request("POST", f"/api/price-sheets/{sheet_id}/close",
                             headers=headers)

    def run_allocation(self, sheet_id, headers):
        return self._request("POST", f"/api/price-sheets/{sheet_id}/run-allocation",
                             headers=headers)

    # --- Purchase orders ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/api/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/api/purchase-orders",
                             headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/api/purchase-orders/{po_id}", headers=headers)

    def receive_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/api/purchase-orders/{po_id}/receive",
                             payload, headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/api/purchase-orders/{po_id}/cancel",
                             headers=headers)

    # --- Inventory lots ---
    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/api/inventory-lots",
                             headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/api/inventory-lots/{lot_id}", headers=headers)

    def inspect_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/inventory-lots/{lot_id}/inspect",
                             payload, headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/api/inventory-lots/{lot_id}/quarantine",
                             headers=headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/api/inventory-lots/{lot_id}/release",
                             headers=headers)

    # --- Fabrication batches ---
    def create_fabrication_batch(self, payload, headers):
        return self._request("POST", "/api/fabrication-batches", payload, headers)

    def list_fabrication_batches(self, headers, params=None):
        return self._request("GET", "/api/fabrication-batches",
                             headers=headers, params=params)

    def get_fabrication_batch(self, batch_id, headers):
        return self._request("GET", f"/api/fabrication-batches/{batch_id}",
                             headers=headers)

    def post_fabrication_batch(self, batch_id, headers):
        return self._request("POST", f"/api/fabrication-batches/{batch_id}/post",
                             headers=headers)

    def void_fabrication_batch(self, batch_id, headers):
        return self._request("POST", f"/api/fabrication-batches/{batch_id}/void",
                             headers=headers)

    # --- Forward contracts ---
    def create_forward_contract(self, payload, headers):
        return self._request("POST", "/api/forward-contracts", payload, headers)

    def list_forward_contracts(self, headers, params=None):
        return self._request("GET", "/api/forward-contracts",
                             headers=headers, params=params)

    def get_forward_contract(self, contract_id, headers):
        return self._request("GET", f"/api/forward-contracts/{contract_id}",
                             headers=headers)

    def amend_forward_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/forward-contracts/{contract_id}/amend",
                             payload, headers)

    def cancel_forward_contract(self, contract_id, headers):
        return self._request("POST", f"/api/forward-contracts/{contract_id}/cancel",
                             headers=headers)

    # --- Allocations ---
    def create_allocation(self, payload, headers):
        return self._request("POST", "/api/allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/api/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/api/allocations/{allocation_id}",
                             headers=headers)

    def cancel_allocation(self, allocation_id, headers):
        return self._request("POST", f"/api/allocations/{allocation_id}/cancel",
                             headers=headers)

    # --- Shipments and temperature readings ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/api/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def add_temperature_reading(self, shipment_id, payload, headers):
        return self._request("POST",
                             f"/api/shipments/{shipment_id}/temperature-readings",
                             payload, headers)

    def list_temperature_readings(self, shipment_id, headers, params=None):
        return self._request("GET",
                             f"/api/shipments/{shipment_id}/temperature-readings",
                             headers=headers, params=params)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/depart",
                             headers=headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/deliver",
                             headers=headers)

    def reject_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/reject",
                             payload, headers)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def post_claim_offer(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/offers",
                             payload, headers)

    def counter_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/counter",
                             payload, headers)

    def accept_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/accept",
                             headers=headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/deny", headers=headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/withdraw",
                             headers=headers)

    # --- Inspection certificates ---
    def create_inspection_certificate(self, payload, headers):
        return self._request("POST", "/api/inspection-certificates", payload, headers)

    def list_inspection_certificates(self, headers, params=None):
        return self._request("GET", "/api/inspection-certificates",
                             headers=headers, params=params)

    def get_inspection_certificate(self, cert_id, headers):
        return self._request("GET", f"/api/inspection-certificates/{cert_id}",
                             headers=headers)

    def revoke_inspection_certificate(self, cert_id, headers):
        return self._request("POST",
                             f"/api/inspection-certificates/{cert_id}/revoke",
                             headers=headers)

    # --- Exposure report ---
    def get_exposure(self, headers, params=None):
        return self._request("GET", "/api/exposure", headers=headers, params=params)


api_client = ApiClient()
