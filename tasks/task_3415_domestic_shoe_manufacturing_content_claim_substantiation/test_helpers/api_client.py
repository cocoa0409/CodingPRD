"""API client: one method per endpoint defined in the PRD (section 4 table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- factories ----
    def create_factory(self, payload, headers):
        return self._request("POST", "/footwear/factories", payload, headers)

    def list_factories(self, headers, params=None):
        return self._request("GET", "/footwear/factories", headers=headers, params=params)

    def get_factory(self, factory_id, headers):
        return self._request("GET", f"/footwear/factories/{factory_id}", headers=headers)

    def suspend_factory(self, factory_id, headers):
        return self._request("POST", f"/footwear/factories/{factory_id}/suspend", {}, headers)

    def reactivate_factory(self, factory_id, headers):
        return self._request("POST", f"/footwear/factories/{factory_id}/reactivate", {}, headers)

    # ---- models ----
    def create_model(self, payload, headers):
        return self._request("POST", "/footwear/models", payload, headers)

    def list_models(self, headers, params=None):
        return self._request("GET", "/footwear/models", headers=headers, params=params)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/footwear/models/{model_id}", headers=headers)

    def discontinue_model(self, model_id, headers):
        return self._request("POST", f"/footwear/models/{model_id}/discontinue", {}, headers)

    # ---- components ----
    def create_component(self, payload, headers):
        return self._request("POST", "/footwear/components", payload, headers)

    # ---- material lots ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/footwear/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/footwear/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/footwear/lots/{lot_id}", headers=headers)

    # ---- production runs ----
    def create_run(self, payload, headers):
        return self._request("POST", "/footwear/production-runs", payload, headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/footwear/production-runs", headers=headers, params=params)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/footwear/production-runs/{run_id}", headers=headers)

    def reserve_materials(self, run_id, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/reserve-materials", {}, headers)

    def release_materials(self, run_id, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/release-materials", {}, headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/start", {}, headers)

    def hold_run(self, run_id, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/hold", {}, headers)

    def resume_run(self, run_id, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/resume", {}, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/complete", payload, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/cancel", {}, headers)

    def create_content_report(self, run_id, payload, headers):
        return self._request("POST", f"/footwear/production-runs/{run_id}/content-reports", payload, headers)

    def list_content_reports(self, run_id, headers, params=None):
        return self._request("GET", f"/footwear/production-runs/{run_id}/content-reports", headers=headers, params=params)

    # ---- custom orders ----
    def create_custom_order(self, payload, headers):
        return self._request("POST", "/footwear/custom-orders", payload, headers)

    def list_custom_orders(self, headers, params=None):
        return self._request("GET", "/footwear/custom-orders", headers=headers, params=params)

    def get_custom_order(self, order_id, headers):
        return self._request("GET", f"/footwear/custom-orders/{order_id}", headers=headers)

    def accept_order(self, order_id, headers):
        return self._request("POST", f"/footwear/custom-orders/{order_id}/accept", {}, headers)

    def schedule_order(self, order_id, payload, headers):
        return self._request("POST", f"/footwear/custom-orders/{order_id}/schedule", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/footwear/custom-orders/{order_id}/cancel", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/footwear/custom-orders/{order_id}/fulfill", {}, headers)

    # ---- label claims ----
    def create_label_claim(self, payload, headers):
        return self._request("POST", "/footwear/label-claims", payload, headers)

    def list_label_claims(self, headers, params=None):
        return self._request("GET", "/footwear/label-claims", headers=headers, params=params)

    def get_label_claim(self, claim_id, headers):
        return self._request("GET", f"/footwear/label-claims/{claim_id}", headers=headers)

    def substantiate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/footwear/label-claims/{claim_id}/substantiate", payload, headers)

    def publish_claim(self, claim_id, headers):
        return self._request("POST", f"/footwear/label-claims/{claim_id}/publish", {}, headers)

    def revoke_claim(self, claim_id, headers):
        return self._request("POST", f"/footwear/label-claims/{claim_id}/revoke", {}, headers)

    # ---- evidence documents ----
    def create_evidence_document(self, payload, headers):
        return self._request("POST", "/footwear/evidence-documents", payload, headers)

    def list_evidence_documents(self, headers, params=None):
        return self._request("GET", "/footwear/evidence-documents", headers=headers, params=params)

    def get_evidence_document(self, doc_id, headers):
        return self._request("GET", f"/footwear/evidence-documents/{doc_id}", headers=headers)

    def verify_document(self, doc_id, headers):
        return self._request("POST", f"/footwear/evidence-documents/{doc_id}/verify", {}, headers)

    def reject_document(self, doc_id, headers):
        return self._request("POST", f"/footwear/evidence-documents/{doc_id}/reject", {}, headers)

    # ---- workers / certifications / training ----
    def create_worker(self, payload, headers):
        return self._request("POST", "/footwear/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/footwear/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/footwear/workers/{worker_id}", headers=headers)

    def suspend_worker(self, worker_id, headers):
        return self._request("POST", f"/footwear/workers/{worker_id}/suspend", {}, headers)

    def reinstate_worker(self, worker_id, headers):
        return self._request("POST", f"/footwear/workers/{worker_id}/reinstate", {}, headers)

    def suspend_certification(self, worker_id, operation, headers):
        return self._request(
            "POST", f"/footwear/workers/{worker_id}/certifications/{operation}/suspend", {}, headers
        )

    def reinstate_certification(self, worker_id, operation, headers):
        return self._request(
            "POST", f"/footwear/workers/{worker_id}/certifications/{operation}/reinstate", {}, headers
        )

    def create_enrollment(self, payload, headers):
        return self._request("POST", "/footwear/training-enrollments", payload, headers)

    def list_worker_enrollments(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/footwear/workers/{worker_id}/training-enrollments", headers=headers, params=params
        )

    def record_assessment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/footwear/training-enrollments/{enrollment_id}/record-assessment", payload, headers
        )

    # ---- capacity allocations ----
    def create_allocation(self, payload, headers):
        return self._request("POST", "/footwear/capacity-allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/footwear/capacity-allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/footwear/capacity-allocations/{allocation_id}", headers=headers)

    def lock_allocation(self, allocation_id, headers):
        return self._request("POST", f"/footwear/capacity-allocations/{allocation_id}/lock", {}, headers)

    def shift_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/footwear/capacity-allocations/{allocation_id}/shift", payload, headers)

    def reconcile_allocation(self, allocation_id, headers):
        return self._request("POST", f"/footwear/capacity-allocations/{allocation_id}/reconcile", {}, headers)

    # ---- government contracts ----
    def create_gov_contract(self, payload, headers):
        return self._request("POST", "/footwear/gov-contracts", payload, headers)

    def list_gov_contracts(self, headers, params=None):
        return self._request("GET", "/footwear/gov-contracts", headers=headers, params=params)

    def get_gov_contract(self, contract_id, headers):
        return self._request("GET", f"/footwear/gov-contracts/{contract_id}", headers=headers)

    def start_fulfillment(self, contract_id, headers):
        return self._request("POST", f"/footwear/gov-contracts/{contract_id}/start-fulfillment", {}, headers)

    def initiate_audit(self, contract_id, headers):
        return self._request("POST", f"/footwear/gov-contracts/{contract_id}/initiate-audit", {}, headers)

    def complete_audit(self, contract_id, headers):
        return self._request("POST", f"/footwear/gov-contracts/{contract_id}/complete-audit", {}, headers)


api_client = ApiClient()
