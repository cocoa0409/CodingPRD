"""API client: one method per endpoint defined in the PRD.

Every path is root-relative; there is no shared collection prefix.
Endpoints that declare no request payload are sent with an empty JSON object so
that a body is always present on a POST.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- material specifications ----------------
    def create_material_specification(self, payload, headers):
        return self._request("POST", "/material-specifications", payload, headers)

    def get_material_specification(self, spec_id, headers):
        return self._request("GET", f"/material-specifications/{spec_id}",
                             headers=headers)

    def list_material_specifications(self, headers, params=None):
        return self._request("GET", "/material-specifications",
                             headers=headers, params=params)

    # ---------------- material lots ----------------
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/material-lots", payload, headers)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/material-lots/{lot_id}", headers=headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/material-lots", headers=headers, params=params)

    def disposition_material_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/material-lots/{lot_id}/disposition",
                             payload, headers)

    def list_material_lot_components(self, lot_id, headers, params=None):
        return self._request("GET", f"/material-lots/{lot_id}/lot-components",
                             headers=headers, params=params)

    # ---------------- product specifications ----------------
    def create_product_specification(self, payload, headers):
        return self._request("POST", "/product-specifications", payload, headers)

    def get_product_specification(self, spec_id, headers):
        return self._request("GET", f"/product-specifications/{spec_id}",
                             headers=headers)

    def list_product_specifications(self, headers, params=None):
        return self._request("GET", "/product-specifications",
                             headers=headers, params=params)

    def record_product_clearance(self, spec_id, payload, headers):
        return self._request("POST", f"/product-specifications/{spec_id}/clearance",
                             payload, headers)

    # ---------------- design control records ----------------
    def create_design_control_record(self, payload, headers):
        return self._request("POST", "/design-control-records", payload, headers)

    def get_design_control_record(self, record_id, headers):
        return self._request("GET", f"/design-control-records/{record_id}",
                             headers=headers)

    def list_design_control_records(self, headers, params=None):
        return self._request("GET", "/design-control-records",
                             headers=headers, params=params)

    def approve_design_control_record(self, record_id, headers):
        return self._request("POST", f"/design-control-records/{record_id}/approve",
                             {}, headers)

    # ---------------- reagent lots ----------------
    def create_reagent_lot(self, payload, headers):
        return self._request("POST", "/reagent-lots", payload, headers)

    def get_reagent_lot(self, lot_id, headers):
        return self._request("GET", f"/reagent-lots/{lot_id}", headers=headers)

    def list_reagent_lots(self, headers, params=None):
        return self._request("GET", "/reagent-lots", headers=headers, params=params)

    def add_reagent_lot_component(self, lot_id, payload, headers):
        return self._request("POST", f"/reagent-lots/{lot_id}/components",
                             payload, headers)

    def list_reagent_lot_components(self, lot_id, headers, params=None):
        return self._request("GET", f"/reagent-lots/{lot_id}/components",
                             headers=headers, params=params)

    def disposition_reagent_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/reagent-lots/{lot_id}/disposition",
                             payload, headers)

    def set_reagent_lot_distribution_status(self, lot_id, payload, headers):
        return self._request("POST", f"/reagent-lots/{lot_id}/distribution-status",
                             payload, headers)

    def list_reagent_lot_allocations(self, lot_id, headers, params=None):
        return self._request("GET", f"/reagent-lots/{lot_id}/allocations",
                             headers=headers, params=params)

    # ---------------- fill runs and monitoring samples ----------------
    def create_fill_run(self, payload, headers):
        return self._request("POST", "/fill-runs", payload, headers)

    def get_fill_run(self, run_id, headers):
        return self._request("GET", f"/fill-runs/{run_id}", headers=headers)

    def list_fill_runs(self, headers, params=None):
        return self._request("GET", "/fill-runs", headers=headers, params=params)

    def start_fill_run(self, run_id, headers):
        return self._request("POST", f"/fill-runs/{run_id}/start", {}, headers)

    def complete_fill_run(self, run_id, payload, headers):
        return self._request("POST", f"/fill-runs/{run_id}/complete", payload, headers)

    def abort_fill_run(self, run_id, payload, headers):
        return self._request("POST", f"/fill-runs/{run_id}/abort", payload, headers)

    def create_monitoring_sample(self, run_id, payload, headers):
        return self._request("POST", f"/fill-runs/{run_id}/samples", payload, headers)

    def list_monitoring_samples(self, run_id, headers, params=None):
        return self._request("GET", f"/fill-runs/{run_id}/samples",
                             headers=headers, params=params)

    # ---------------- test results ----------------
    def create_test_result(self, payload, headers):
        return self._request("POST", "/test-results", payload, headers)

    def get_test_result(self, result_id, headers):
        return self._request("GET", f"/test-results/{result_id}", headers=headers)

    def list_test_results(self, headers, params=None):
        return self._request("GET", "/test-results", headers=headers, params=params)

    # ---------------- stability studies ----------------
    def create_stability_study(self, payload, headers):
        return self._request("POST", "/stability-studies", payload, headers)

    def get_stability_study(self, study_id, headers):
        return self._request("GET", f"/stability-studies/{study_id}", headers=headers)

    def list_stability_studies(self, headers, params=None):
        return self._request("GET", "/stability-studies", headers=headers, params=params)

    def approve_stability_protocol(self, study_id, headers):
        return self._request("POST",
                             f"/stability-studies/{study_id}/approve-protocol",
                             {}, headers)

    def conclude_stability_study(self, study_id, headers):
        return self._request("POST", f"/stability-studies/{study_id}/conclude",
                             {}, headers)

    # ---------------- bridging studies ----------------
    def create_bridging_study(self, payload, headers):
        return self._request("POST", "/bridging-studies", payload, headers)

    def get_bridging_study(self, study_id, headers):
        return self._request("GET", f"/bridging-studies/{study_id}", headers=headers)

    def list_bridging_studies(self, headers, params=None):
        return self._request("GET", "/bridging-studies", headers=headers, params=params)

    def decide_bridging_study(self, study_id, payload, headers):
        return self._request("POST", f"/bridging-studies/{study_id}/decision",
                             payload, headers)

    # ---------------- complaints ----------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def triage_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/triage",
                             payload, headers)

    def file_malfunction_report(self, complaint_id, payload, headers):
        return self._request("POST",
                             f"/complaints/{complaint_id}/malfunction-report",
                             payload, headers)

    def decide_field_action(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/field-action",
                             payload, headers)

    def close_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/close", {}, headers)

    # ---------------- distribution orders ----------------
    def create_distribution_order(self, payload, headers):
        return self._request("POST", "/distribution-orders", payload, headers)

    def get_distribution_order(self, order_id, headers):
        return self._request("GET", f"/distribution-orders/{order_id}",
                             headers=headers)

    def list_distribution_orders(self, headers, params=None):
        return self._request("GET", "/distribution-orders",
                             headers=headers, params=params)

    def allocate_distribution_order(self, order_id, headers):
        return self._request("POST", f"/distribution-orders/{order_id}/allocate",
                             {}, headers)

    def list_distribution_order_allocations(self, order_id, headers, params=None):
        return self._request("GET", f"/distribution-orders/{order_id}/allocations",
                             headers=headers, params=params)

    # ---------------- allocations ----------------
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def ship_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/ship", {}, headers)

    def cancel_allocation(self, allocation_id, headers, payload=None):
        return self._request("POST", f"/allocations/{allocation_id}/cancel",
                             payload if payload is not None else {}, headers)

    def create_cold_chain_event(self, allocation_id, payload, headers):
        return self._request("POST",
                             f"/allocations/{allocation_id}/cold-chain-event",
                             payload, headers)

    # ---------------- raw escape hatches ----------------
    def post_raw(self, path, payload, headers):
        """POST an arbitrary body to an arbitrary path (for malformed-payload and
        missing-header cases)."""
        return self._request("POST", path, payload, headers)

    def get_raw(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
