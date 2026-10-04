"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/bureau/_clock/set_current_utc", payload, headers)

    # --- MemberInsurer ---
    def create_insurer(self, payload, headers):
        return self._request("POST", "/bureau/insurers", payload, headers)

    def get_insurer(self, insurer_id, headers):
        return self._request("GET", f"/bureau/insurers/{insurer_id}", headers=headers)

    def list_insurers(self, headers, params=None):
        return self._request("GET", "/bureau/insurers", headers=headers, params=params)

    def suspend_insurer(self, insurer_id, headers):
        return self._request("POST", f"/bureau/insurers/{insurer_id}/suspend", {}, headers)

    def reinstate_insurer(self, insurer_id, headers):
        return self._request("POST", f"/bureau/insurers/{insurer_id}/reinstate", {}, headers)

    def withdraw_membership(self, insurer_id, headers):
        return self._request("POST", f"/bureau/insurers/{insurer_id}/withdraw-membership", {}, headers)

    def list_insurer_agreements(self, insurer_id, headers):
        return self._request("GET", f"/bureau/insurers/{insurer_id}/agreements", headers=headers)

    # --- StatisticalPlan ---
    def create_statistical_plan(self, payload, headers):
        return self._request("POST", "/bureau/statistical-plans", payload, headers)

    def get_statistical_plan(self, plan_id, headers):
        return self._request("GET", f"/bureau/statistical-plans/{plan_id}", headers=headers)

    def activate_statistical_plan(self, plan_id, headers):
        return self._request("POST", f"/bureau/statistical-plans/{plan_id}/activate", {}, headers)

    # --- StatisticalSubmission ---
    def create_submission(self, payload, headers):
        return self._request("POST", "/bureau/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/bureau/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/bureau/submissions", headers=headers, params=params)

    def begin_edit(self, submission_id, headers):
        return self._request("POST", f"/bureau/submissions/{submission_id}/begin-edit", {}, headers)

    def create_finding(self, submission_id, payload, headers):
        return self._request("POST", f"/bureau/submissions/{submission_id}/findings", payload, headers)

    def list_findings(self, submission_id, headers):
        return self._request("GET", f"/bureau/submissions/{submission_id}/findings", headers=headers)

    def dispose_submission(self, submission_id, headers, payload=None):
        return self._request("POST", f"/bureau/submissions/{submission_id}/dispose", payload or {}, headers)

    # --- StateDepartment ---
    def create_department(self, payload, headers):
        return self._request("POST", "/bureau/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/bureau/departments/{department_id}", headers=headers)

    def list_department_objections(self, department_id, headers):
        return self._request("GET", f"/bureau/departments/{department_id}/objections", headers=headers)

    # --- LossCostFiling ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/bureau/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/bureau/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/bureau/filings", headers=headers, params=params)

    def create_cell(self, filing_id, payload, headers):
        return self._request("POST", f"/bureau/filings/{filing_id}/cells", payload, headers)

    def list_cells(self, filing_id, headers):
        return self._request("GET", f"/bureau/filings/{filing_id}/cells", headers=headers)

    def submit_filing_review(self, filing_id, headers):
        return self._request("POST", f"/bureau/filings/{filing_id}/submit-review", {}, headers)

    def complete_filing_review(self, filing_id, headers):
        return self._request("POST", f"/bureau/filings/{filing_id}/complete-review", {}, headers)

    def file_filing(self, filing_id, headers):
        return self._request("POST", f"/bureau/filings/{filing_id}/file", {}, headers)

    def raise_objection(self, filing_id, payload, headers):
        return self._request("POST", f"/bureau/filings/{filing_id}/objections", payload, headers)

    def list_filing_objections(self, filing_id, headers):
        return self._request("GET", f"/bureau/filings/{filing_id}/objections", headers=headers)

    def finalize_filing(self, filing_id, headers):
        return self._request("POST", f"/bureau/filings/{filing_id}/finalize", {}, headers)

    def withdraw_filing(self, filing_id, headers):
        return self._request("POST", f"/bureau/filings/{filing_id}/withdraw", {}, headers)

    # --- LossCostMultiplierAdoption ---
    def create_adoption(self, payload, headers):
        return self._request("POST", "/bureau/adoptions", payload, headers)

    def get_adoption(self, adoption_id, headers):
        return self._request("GET", f"/bureau/adoptions/{adoption_id}", headers=headers)

    def list_adoptions(self, headers, params=None):
        return self._request("GET", "/bureau/adoptions", headers=headers, params=params)

    def authorize_adoption(self, adoption_id, headers):
        return self._request("POST", f"/bureau/adoptions/{adoption_id}/authorize", {}, headers)

    def withdraw_adoption(self, adoption_id, headers):
        return self._request("POST", f"/bureau/adoptions/{adoption_id}/withdraw", {}, headers)

    # --- PolicyForm / FormVariant ---
    def create_form(self, payload, headers):
        return self._request("POST", "/bureau/forms", payload, headers)

    def get_form(self, form_id, headers):
        return self._request("GET", f"/bureau/forms/{form_id}", headers=headers)

    def create_variant(self, form_id, payload, headers):
        return self._request("POST", f"/bureau/forms/{form_id}/variants", payload, headers)

    def list_variants(self, form_id, headers, params=None):
        return self._request("GET", f"/bureau/forms/{form_id}/variants", headers=headers, params=params)

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/bureau/variants/{variant_id}", headers=headers)

    def clear_variant(self, variant_id, headers):
        return self._request("POST", f"/bureau/variants/{variant_id}/clear", {}, headers)

    def block_variant(self, variant_id, headers):
        return self._request("POST", f"/bureau/variants/{variant_id}/block", {}, headers)

    def unblock_variant(self, variant_id, headers):
        return self._request("POST", f"/bureau/variants/{variant_id}/unblock", {}, headers)

    def retire_variant(self, variant_id, headers):
        return self._request("POST", f"/bureau/variants/{variant_id}/retire", {}, headers)

    def submit_form_review(self, form_id, headers):
        return self._request("POST", f"/bureau/forms/{form_id}/submit-review", {}, headers)

    def approve_form(self, form_id, headers):
        return self._request("POST", f"/bureau/forms/{form_id}/approve", {}, headers)

    def return_form_to_drafting(self, form_id, headers):
        return self._request("POST", f"/bureau/forms/{form_id}/return-to-drafting", {}, headers)

    def withdraw_form(self, form_id, headers):
        return self._request("POST", f"/bureau/forms/{form_id}/withdraw", {}, headers)

    # --- Circular ---
    def create_circular(self, payload, headers):
        return self._request("POST", "/bureau/circulars", payload, headers)

    def get_circular(self, circular_id, headers):
        return self._request("GET", f"/bureau/circulars/{circular_id}", headers=headers)

    def list_circulars(self, headers, params=None):
        return self._request("GET", "/bureau/circulars", headers=headers, params=params)

    def publish_circular(self, circular_id, headers):
        return self._request("POST", f"/bureau/circulars/{circular_id}/publish", {}, headers)

    # --- LicenseAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/bureau/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/bureau/agreements/{agreement_id}", headers=headers)

    def get_royalty(self, agreement_id, headers):
        return self._request("GET", f"/bureau/agreements/{agreement_id}/royalty", headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/bureau/agreements/{agreement_id}/terminate", {}, headers)

    # --- ClassPlan / ClassPlanRevision ---
    def create_class_plan(self, payload, headers):
        return self._request("POST", "/bureau/class-plans", payload, headers)

    def get_class_plan(self, plan_id, headers):
        return self._request("GET", f"/bureau/class-plans/{plan_id}", headers=headers)

    def list_class_plans(self, headers, params=None):
        return self._request("GET", "/bureau/class-plans", headers=headers, params=params)

    def create_revision(self, plan_id, payload, headers):
        return self._request("POST", f"/bureau/class-plans/{plan_id}/revisions", payload, headers)

    def list_revisions(self, plan_id, headers):
        return self._request("GET", f"/bureau/class-plans/{plan_id}/revisions", headers=headers)

    def get_revision(self, revision_id, headers):
        return self._request("GET", f"/bureau/class-plan-revisions/{revision_id}", headers=headers)

    def list_in_force_for(self, revision_id, headers):
        return self._request("GET", f"/bureau/class-plan-revisions/{revision_id}/in-force-for", headers=headers)

    def activate_revision(self, revision_id, headers):
        return self._request("POST", f"/bureau/class-plan-revisions/{revision_id}/activate", {}, headers)

    def lock_class_plan(self, plan_id, headers):
        return self._request("POST", f"/bureau/class-plans/{plan_id}/lock", {}, headers)


api_client = ApiClient()
