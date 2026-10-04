"""API client: one method per endpoint family in PRD §4.

All routes are mounted under the /confection prefix. List endpoints pass their
filter/pagination parameters as query params (the framework forwards `params`
on GET). Action endpoints with no input fields send an empty JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/confection"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.5)
    # ------------------------------------------------------------------
    def set_logical_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # SeasonalProgram (PRD §3.1, §3.5, §3.9)
    # ------------------------------------------------------------------
    def create_seasonal_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seasonal-programs", payload, headers)

    def get_seasonal_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/seasonal-programs/{program_id}", headers=headers)

    def get_supply_summary(self, program_id, headers):
        return self._request(
            "GET", f"{PREFIX}/seasonal-programs/{program_id}/supply-summary",
            headers=headers,
        )

    def advance_program(self, program_id, payload, headers):
        """payload: {"to_state": ..., "expected_program_version": ...} (OCC, PRD §2.7)."""
        return self._request(
            "POST", f"{PREFIX}/seasonal-programs/{program_id}/advance", payload, headers,
        )

    # ------------------------------------------------------------------
    # Product (PRD §3.1)
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    # ------------------------------------------------------------------
    # ProductionRun (PRD §3.2, §2.10)
    # ------------------------------------------------------------------
    def create_production_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/production-runs", headers=headers, params=params)

    def start_production_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/production-runs/{run_id}/start", {}, headers)

    def complete_production_run(self, run_id, payload, headers):
        """payload: {"produced_units": int, "warehouse_id": str}."""
        return self._request(
            "POST", f"{PREFIX}/production-runs/{run_id}/complete", payload, headers,
        )

    def cancel_production_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/production-runs/{run_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # RetailerAccount (PRD §3.1)
    # ------------------------------------------------------------------
    def create_retailer_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retailer-accounts", payload, headers)

    def get_retailer_account(self, retailer_id, headers):
        return self._request("GET", f"{PREFIX}/retailer-accounts/{retailer_id}", headers=headers)

    # ------------------------------------------------------------------
    # RetailerCommitment (PRD §3.4, §3.6)
    # ------------------------------------------------------------------
    def create_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retailer-commitments", payload, headers)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"{PREFIX}/retailer-commitments/{commitment_id}", headers=headers)

    def list_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/retailer-commitments", headers=headers, params=params,
        )

    def submit_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/retailer-commitments/{commitment_id}/submit", {}, headers,
        )

    def confirm_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/retailer-commitments/{commitment_id}/confirm", {}, headers,
        )

    def revise_commitment(self, commitment_id, payload, headers):
        """payload: {"committed_units": int, "expected_commitment_version": int,
        optional ship-window bounds}. Returns 201 with the successor row."""
        return self._request(
            "POST", f"{PREFIX}/retailer-commitments/{commitment_id}/revise", payload, headers,
        )

    def reorder_commitment(self, commitment_id, payload, headers):
        """payload: {"units": int}."""
        return self._request(
            "POST", f"{PREFIX}/retailer-commitments/{commitment_id}/reorder", payload, headers,
        )

    def cancel_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/retailer-commitments/{commitment_id}/cancel", {}, headers,
        )

    # ------------------------------------------------------------------
    # Shipment (PRD §3.6)
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shipments", headers=headers, params=params)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"{PREFIX}/shipments/{shipment_id}/deliver", {}, headers)

    # ------------------------------------------------------------------
    # HeatClaim (PRD §3.8)
    # ------------------------------------------------------------------
    def create_heat_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/heat-claims", payload, headers)

    def get_heat_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/heat-claims/{claim_id}", headers=headers)

    def list_heat_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/heat-claims", headers=headers, params=params)

    def decide_heat_claim(self, claim_id, payload, headers):
        """payload: {"decision": "APPROVE" | "REJECT" | "REQUEST_MORE_INFO"}."""
        return self._request(
            "POST", f"{PREFIX}/heat-claims/{claim_id}/decide", payload, headers,
        )

    def provide_heat_claim_info(self, claim_id, payload, headers):
        """payload: {"evidence_note": str}."""
        return self._request(
            "POST", f"{PREFIX}/heat-claims/{claim_id}/provide-info", payload, headers,
        )

    # ------------------------------------------------------------------
    # Warehouse (PRD §2.9)
    # ------------------------------------------------------------------
    def create_warehouse(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"{PREFIX}/warehouses/{warehouse_id}", headers=headers)

    # ------------------------------------------------------------------
    # InventoryLot (PRD §3.9)
    # ------------------------------------------------------------------
    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inventory-lots", headers=headers, params=params)

    def quarantine_inventory_lot(self, lot_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inventory-lots/{lot_id}/quarantine", {}, headers,
        )

    def release_inventory_lot_quarantine(self, lot_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inventory-lots/{lot_id}/release-quarantine", {}, headers,
        )

    # ------------------------------------------------------------------
    # DispositionOrder (PRD §3.9)
    # ------------------------------------------------------------------
    def create_disposition_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disposition-orders", payload, headers)

    def get_disposition_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/disposition-orders/{order_id}", headers=headers)

    def list_disposition_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/disposition-orders", headers=headers, params=params,
        )

    def approve_disposition_order(self, order_id, payload, headers):
        """payload: {"decision": "APPROVE" | "REJECT"}."""
        return self._request(
            "POST", f"{PREFIX}/disposition-orders/{order_id}/approve", payload, headers,
        )

    def execute_disposition_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/disposition-orders/{order_id}/execute", {}, headers,
        )

    # ------------------------------------------------------------------
    # CommodityContract (PRD §3.3)
    # ------------------------------------------------------------------
    def create_commodity_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/commodity-contracts", payload, headers)

    def get_commodity_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/commodity-contracts/{contract_id}", headers=headers)

    def list_commodity_contracts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/commodity-contracts", headers=headers, params=params,
        )

    def settle_commodity_contract(self, contract_id, payload, headers):
        """payload: {"spot_price_cents_per_unit": int}."""
        return self._request(
            "POST", f"{PREFIX}/commodity-contracts/{contract_id}/settle", payload, headers,
        )

    # ------------------------------------------------------------------
    # SellThroughReport (PRD §3.7)
    # ------------------------------------------------------------------
    def create_sell_through_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sell-through-reports", payload, headers)

    def get_sell_through_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/sell-through-reports/{report_id}", headers=headers)

    def list_sell_through_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sell-through-reports", headers=headers, params=params,
        )


api_client = ApiClient()
