"""HTTP client for the Frozen Potato Processing API.

One method per endpoint declared in PRD §4. Every method returns the raw
response so tests can assert on status codes as well as bodies. Query filters
and pagination go through ``params``; request bodies through ``payload``.

The logical-clock endpoint is a platform operation that lives OUTSIDE the
/potato-ops business prefix (PRD §2.5): its path is /_clock/set_current_utc
verbatim.
"""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock (unprefixed platform endpoint, PRD §2.5) ─────────────
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Growers ────────────────────────────────────────────────────────────
    def create_grower(self, payload, headers):
        return self._request("POST", "/potato-ops/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/potato-ops/growers/{grower_id}", None, headers)

    # ── Crop contracts ─────────────────────────────────────────────────────
    def create_crop_contract(self, payload, headers):
        return self._request("POST", "/potato-ops/crop-contracts", payload, headers)

    def list_crop_contracts(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/potato-ops/crop-contracts", params, headers)

    def get_crop_contract(self, contract_id, headers):
        return self._request("GET", f"/potato-ops/crop-contracts/{contract_id}", None, headers)

    def activate_crop_contract(self, contract_id, headers):
        return self._request("POST", f"/potato-ops/crop-contracts/{contract_id}/activate", {}, headers)

    def propose_amendment(self, contract_id, payload, headers):
        return self._request("POST", f"/potato-ops/crop-contracts/{contract_id}/propose-amendment", payload, headers)

    def accept_amendment(self, contract_id, payload, headers):
        return self._request("POST", f"/potato-ops/crop-contracts/{contract_id}/accept-amendment", payload, headers)

    def declare_shortfall(self, contract_id, headers):
        return self._request("POST", f"/potato-ops/crop-contracts/{contract_id}/declare-shortfall", {}, headers)

    # ── Potato lots ────────────────────────────────────────────────────────
    def create_potato_lot(self, payload, headers):
        return self._request("POST", "/potato-ops/potato-lots", payload, headers)

    def list_potato_lots(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/potato-ops/potato-lots", params, headers)

    def get_potato_lot(self, lot_id, headers):
        return self._request("GET", f"/potato-ops/potato-lots/{lot_id}", None, headers)

    def dispose_potato_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/potato-ops/potato-lots/{lot_id}/dispose", payload, headers)

    # ── Storage facilities ─────────────────────────────────────────────────
    def create_storage_facility(self, payload, headers):
        return self._request("POST", "/potato-ops/storage-facilities", payload, headers)

    def get_storage_facility(self, facility_id, headers):
        return self._request("GET", f"/potato-ops/storage-facilities/{facility_id}", None, headers)

    def record_reading(self, facility_id, payload, headers):
        return self._request("POST", f"/potato-ops/storage-facilities/{facility_id}/readings", payload, headers)

    # ── Processing lines ───────────────────────────────────────────────────
    def create_processing_line(self, payload, headers):
        return self._request("POST", "/potato-ops/processing-lines", payload, headers)

    # ── Cut specifications ─────────────────────────────────────────────────
    def create_cut_specification(self, payload, headers):
        return self._request("POST", "/potato-ops/cut-specifications", payload, headers)

    def list_cut_specifications(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/potato-ops/cut-specifications", params, headers)

    def get_cut_specification(self, spec_id, headers):
        return self._request("GET", f"/potato-ops/cut-specifications/{spec_id}", None, headers)

    def validate_cut_specification(self, spec_id, payload, headers):
        return self._request("POST", f"/potato-ops/cut-specifications/{spec_id}/validate", payload, headers)

    def request_spec_revision(self, spec_id, headers):
        return self._request("POST", f"/potato-ops/cut-specifications/{spec_id}/request-revision", {}, headers)

    # ── Customer chains ────────────────────────────────────────────────────
    def create_customer_chain(self, payload, headers):
        return self._request("POST", "/potato-ops/customer-chains", payload, headers)

    def get_customer_chain(self, chain_id, headers):
        return self._request("GET", f"/potato-ops/customer-chains/{chain_id}", None, headers)

    def set_credit_status(self, chain_id, payload, headers):
        return self._request("POST", f"/potato-ops/customer-chains/{chain_id}/set-credit-status", payload, headers)

    # ── Supply agreements ──────────────────────────────────────────────────
    def create_supply_agreement(self, payload, headers):
        return self._request("POST", "/potato-ops/supply-agreements", payload, headers)

    def list_supply_agreements(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/potato-ops/supply-agreements", params, headers)

    def get_supply_agreement(self, agreement_id, headers):
        return self._request("GET", f"/potato-ops/supply-agreements/{agreement_id}", None, headers)

    def activate_supply_agreement(self, agreement_id, headers):
        return self._request("POST", f"/potato-ops/supply-agreements/{agreement_id}/activate", {}, headers)

    # ── Production runs ────────────────────────────────────────────────────
    def create_production_run(self, payload, headers):
        return self._request("POST", "/potato-ops/production-runs", payload, headers)

    def list_production_runs(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/potato-ops/production-runs", params, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/potato-ops/production-runs/{run_id}", None, headers)

    def advance_run(self, run_id, headers):
        return self._request("POST", f"/potato-ops/production-runs/{run_id}/advance", {}, headers)

    def qa_release_run(self, run_id, payload, headers):
        return self._request("POST", f"/potato-ops/production-runs/{run_id}/qa-release", payload, headers)

    def rework_run(self, run_id, headers):
        return self._request("POST", f"/potato-ops/production-runs/{run_id}/rework", {}, headers)

    def reject_run(self, run_id, payload, headers):
        return self._request("POST", f"/potato-ops/production-runs/{run_id}/reject", payload, headers)

    # ── Byproduct batches (system-created, read-only) ──────────────────────
    def list_byproduct_batches(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/potato-ops/byproduct-batches", params, headers)

    def get_byproduct_batch(self, batch_id, headers):
        return self._request("GET", f"/potato-ops/byproduct-batches/{batch_id}", None, headers)

    # ── Shipments ──────────────────────────────────────────────────────────
    def create_shipment(self, payload, headers):
        return self._request("POST", "/potato-ops/shipments", payload, headers)

    def list_shipments(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/potato-ops/shipments", params, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/potato-ops/shipments/{shipment_id}", None, headers)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/potato-ops/shipments/{shipment_id}/deliver", payload, headers)

    def reject_shipment_on_arrival(self, shipment_id, headers):
        return self._request("POST", f"/potato-ops/shipments/{shipment_id}/reject-on-arrival", {}, headers)

    # ── Shortage events ────────────────────────────────────────────────────
    def create_shortage_event(self, payload, headers):
        return self._request("POST", "/potato-ops/shortage-events", payload, headers)

    def execute_allocation(self, event_id, headers):
        return self._request("POST", f"/potato-ops/shortage-events/{event_id}/execute-allocation", {}, headers)


api_client = ApiClient()
