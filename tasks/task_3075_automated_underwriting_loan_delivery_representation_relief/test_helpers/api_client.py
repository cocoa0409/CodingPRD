"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/gse/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- sellers ---
    def create_seller(self, payload, headers):
        return self._request("POST", "/gse/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/gse/sellers/{seller_id}", headers=headers)

    def approve_seller(self, seller_id, headers):
        return self._request("POST", f"/gse/sellers/{seller_id}/approve", {}, headers)

    def suspend_seller(self, seller_id, headers):
        return self._request("POST", f"/gse/sellers/{seller_id}/suspend", {}, headers)

    def terminate_seller(self, seller_id, headers):
        return self._request("POST", f"/gse/sellers/{seller_id}/terminate", {}, headers)

    # --- servicers ---
    def create_servicer(self, payload, headers):
        return self._request("POST", "/gse/servicers", payload, headers)

    def get_servicer(self, servicer_id, headers):
        return self._request("GET", f"/gse/servicers/{servicer_id}", headers=headers)

    def approve_servicer(self, servicer_id, headers):
        return self._request("POST", f"/gse/servicers/{servicer_id}/approve", {}, headers)

    def suspend_servicer(self, servicer_id, headers):
        return self._request("POST", f"/gse/servicers/{servicer_id}/suspend", {}, headers)

    def terminate_servicer(self, servicer_id, headers):
        return self._request("POST", f"/gse/servicers/{servicer_id}/terminate", {}, headers)

    # --- master agreements ---
    def create_master_agreement(self, payload, headers):
        return self._request("POST", "/gse/master-agreements", payload, headers)

    def get_master_agreement(self, agreement_id, headers):
        return self._request("GET", f"/gse/master-agreements/{agreement_id}", headers=headers)

    def list_master_agreements(self, headers, params=None):
        return self._request("GET", "/gse/master-agreements", headers=headers, params=params)

    def activate_master_agreement(self, agreement_id, headers):
        return self._request("POST", f"/gse/master-agreements/{agreement_id}/activate", {}, headers)

    def terminate_master_agreement(self, agreement_id, headers):
        return self._request("POST", f"/gse/master-agreements/{agreement_id}/terminate", {}, headers)

    # --- LLPA matrices ---
    def create_llpa_matrix(self, payload, headers):
        return self._request("POST", "/gse/llpa-matrices", payload, headers)

    def get_llpa_matrix(self, matrix_id, headers):
        return self._request("GET", f"/gse/llpa-matrices/{matrix_id}", headers=headers)

    def list_llpa_matrices(self, headers, params=None):
        return self._request("GET", "/gse/llpa-matrices", headers=headers, params=params)

    # --- loans ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/gse/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/gse/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/gse/loans", headers=headers, params=params)

    def deliver_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/gse/loans/{loan_id}/deliver", payload, headers)

    # --- underwriting cases / validation reports ---
    def create_underwriting_case(self, payload, headers):
        return self._request("POST", "/gse/underwriting-cases", payload, headers)

    def get_underwriting_case(self, case_id, headers):
        return self._request("GET", f"/gse/underwriting-cases/{case_id}", headers=headers)

    def list_underwriting_cases(self, headers, params=None):
        return self._request("GET", "/gse/underwriting-cases", headers=headers, params=params)

    def create_validation_report(self, case_id, payload, headers):
        return self._request("POST", f"/gse/underwriting-cases/{case_id}/reports", payload, headers)

    def list_validation_reports(self, headers, params=None):
        return self._request("GET", "/gse/validation-reports", headers=headers, params=params)

    def complete_validation_report(self, report_id, payload, headers):
        return self._request("POST", f"/gse/validation-reports/{report_id}/complete", payload, headers)

    def finalize_underwriting_case(self, case_id, payload, headers):
        return self._request("POST", f"/gse/underwriting-cases/{case_id}/finalize", payload, headers)

    # --- pools ---
    def create_pool(self, payload, headers):
        return self._request("POST", "/gse/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/gse/pools/{pool_id}", headers=headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/gse/pools", headers=headers, params=params)

    def lock_pool(self, pool_id, headers):
        return self._request("POST", f"/gse/pools/{pool_id}/lock", {}, headers)

    def unlock_pool(self, pool_id, headers):
        return self._request("POST", f"/gse/pools/{pool_id}/unlock", {}, headers)

    def issue_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/gse/pools/{pool_id}/issue", payload, headers)

    def cancel_pool(self, pool_id, headers):
        return self._request("POST", f"/gse/pools/{pool_id}/cancel", {}, headers)

    # --- payment events ---
    def create_payment_event(self, payload, headers):
        return self._request("POST", "/gse/payment-events", payload, headers)

    def list_payment_events(self, headers, params=None):
        return self._request("GET", "/gse/payment-events", headers=headers, params=params)

    # --- QC audits / findings / repurchase demands ---
    def create_qc_audit(self, payload, headers):
        return self._request("POST", "/gse/qc-audits", payload, headers)

    def get_qc_audit(self, audit_id, headers):
        return self._request("GET", f"/gse/qc-audits/{audit_id}", headers=headers)

    def list_qc_audits(self, headers, params=None):
        return self._request("GET", "/gse/qc-audits", headers=headers, params=params)

    def create_qc_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/gse/qc-audits/{audit_id}/findings", payload, headers)

    def list_qc_findings(self, headers, params=None):
        return self._request("GET", "/gse/qc-findings", headers=headers, params=params)

    def get_qc_finding(self, finding_id, headers):
        return self._request("GET", f"/gse/qc-findings/{finding_id}", headers=headers)

    def issue_findings(self, audit_id, headers):
        return self._request("POST", f"/gse/qc-audits/{audit_id}/issue-findings", {}, headers)

    def close_qc_audit(self, audit_id, headers):
        return self._request("POST", f"/gse/qc-audits/{audit_id}/close", {}, headers)

    def issue_repurchase_demand(self, finding_id, headers):
        return self._request("POST", f"/gse/qc-findings/{finding_id}/issue-demand", {}, headers)

    def get_repurchase_demand(self, demand_id, headers):
        return self._request("GET", f"/gse/repurchase-demands/{demand_id}", headers=headers)

    def list_repurchase_demands(self, headers, params=None):
        return self._request("GET", "/gse/repurchase-demands", headers=headers, params=params)

    def appeal_repurchase_demand(self, demand_id, payload, headers):
        return self._request("POST", f"/gse/repurchase-demands/{demand_id}/appeal", payload, headers)

    def resolve_appeal(self, demand_id, payload, headers):
        return self._request("POST", f"/gse/repurchase-demands/{demand_id}/resolve-appeal", payload, headers)

    def settle_repurchase_demand(self, demand_id, headers):
        return self._request("POST", f"/gse/repurchase-demands/{demand_id}/settle", {}, headers)

    # --- servicing transfers ---
    def create_servicing_transfer(self, payload, headers):
        return self._request("POST", "/gse/servicing-transfers", payload, headers)

    def get_servicing_transfer(self, transfer_id, headers):
        return self._request("GET", f"/gse/servicing-transfers/{transfer_id}", headers=headers)

    def list_servicing_transfers(self, headers, params=None):
        return self._request("GET", "/gse/servicing-transfers", headers=headers, params=params)

    def approve_servicing_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/gse/servicing-transfers/{transfer_id}/approve", payload, headers)

    def reject_servicing_transfer(self, transfer_id, headers):
        return self._request("POST", f"/gse/servicing-transfers/{transfer_id}/reject", {}, headers)

    def cancel_servicing_transfer(self, transfer_id, headers):
        return self._request("POST", f"/gse/servicing-transfers/{transfer_id}/cancel", {}, headers)

    # --- subservicer oversight ---
    def create_subservicer_oversight(self, payload, headers):
        return self._request("POST", "/gse/subservicer-oversight", payload, headers)

    def get_subservicer_oversight(self, record_id, headers):
        return self._request("GET", f"/gse/subservicer-oversight/{record_id}", headers=headers)

    def list_subservicer_oversight(self, headers, params=None):
        return self._request("GET", "/gse/subservicer-oversight", headers=headers, params=params)

    def close_subservicer_oversight(self, record_id, headers):
        return self._request("POST", f"/gse/subservicer-oversight/{record_id}/close", {}, headers)

    # --- pipelines / llpa update events ---
    def create_pipeline(self, payload, headers):
        return self._request("POST", "/gse/pipelines", payload, headers)

    def get_pipeline(self, pipeline_id, headers):
        return self._request("GET", f"/gse/pipelines/{pipeline_id}", headers=headers)

    def list_pipelines(self, headers, params=None):
        return self._request("GET", "/gse/pipelines", headers=headers, params=params)

    def list_llpa_update_events(self, headers, params=None):
        return self._request("GET", "/gse/llpa-update-events", headers=headers, params=params)


api_client = ApiClient()
