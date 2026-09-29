"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- administrative logical clock ------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- market requirement registry -------------------------------------
    def create_market_requirement(self, payload, headers):
        return self._request("POST", "/labeling/market-requirements", payload, headers)

    def list_market_requirements(self, headers, params=None):
        return self._request("GET", "/labeling/market-requirements",
                             headers=headers, params=params)

    # --- brands -----------------------------------------------------------
    def create_brand(self, payload, headers):
        return self._request("POST", "/labeling/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/labeling/brands/{brand_id}", headers=headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", "/labeling/brands", headers=headers, params=params)

    def list_brand_styles(self, brand_id, headers, params=None):
        return self._request("GET", f"/labeling/brands/{brand_id}/styles",
                             headers=headers, params=params)

    # --- styles -----------------------------------------------------------
    def create_style(self, payload, headers):
        return self._request("POST", "/labeling/styles", payload, headers)

    def get_style(self, style_id, headers):
        return self._request("GET", f"/labeling/styles/{style_id}", headers=headers)

    def replace_fiber_declaration(self, style_id, payload, headers):
        return self._request("PUT", f"/labeling/styles/{style_id}/fiber-declaration",
                             payload, headers)

    def get_compliance_summary(self, style_id, headers):
        return self._request("GET", f"/labeling/styles/{style_id}/compliance-summary",
                             headers=headers)

    # --- supply graph -----------------------------------------------------
    def create_material_input(self, style_id, payload, headers):
        return self._request("POST", f"/labeling/styles/{style_id}/material-inputs",
                             payload, headers)

    def get_material_input(self, material_input_id, headers):
        return self._request("GET", f"/labeling/material-inputs/{material_input_id}",
                             headers=headers)

    def list_material_inputs(self, headers, params=None):
        return self._request("GET", "/labeling/material-inputs",
                             headers=headers, params=params)

    # --- laboratory evidence ---------------------------------------------
    def create_lab_test(self, payload, headers):
        return self._request("POST", "/labeling/lab-tests", payload, headers)

    def post_lab_test_results(self, lab_test_id, payload, headers):
        return self._request("POST", f"/labeling/lab-tests/{lab_test_id}/results",
                             payload, headers)

    def retest_lab_test(self, lab_test_id, payload, headers):
        return self._request("POST", f"/labeling/lab-tests/{lab_test_id}/retest",
                             payload, headers)

    def get_lab_test(self, lab_test_id, headers):
        return self._request("GET", f"/labeling/lab-tests/{lab_test_id}", headers=headers)

    def list_style_lab_tests(self, style_id, headers, params=None):
        return self._request("GET", f"/labeling/styles/{style_id}/lab-tests",
                             headers=headers, params=params)

    # --- origin determinations -------------------------------------------
    def create_origin_determination(self, payload, headers):
        return self._request("POST", "/labeling/origin-determinations", payload, headers)

    def issue_origin_determination(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/labeling/origin-determinations/{determination_id}/issue",
            payload, headers)

    def get_origin_determination(self, determination_id, headers):
        return self._request("GET", f"/labeling/origin-determinations/{determination_id}",
                             headers=headers)

    def list_style_origin_determinations(self, style_id, headers, params=None):
        return self._request("GET", f"/labeling/styles/{style_id}/origin-determinations",
                             headers=headers, params=params)

    # --- label artifacts --------------------------------------------------
    def create_label_spec(self, payload, headers):
        return self._request("POST", "/labeling/label-specs", payload, headers)

    def update_label_spec(self, label_spec_id, payload, headers):
        return self._request("PATCH", f"/labeling/label-specs/{label_spec_id}",
                             payload, headers)

    def submit_label_spec(self, label_spec_id, headers):
        return self._request("POST", f"/labeling/label-specs/{label_spec_id}/submit",
                             None, headers)

    def approve_label_spec(self, label_spec_id, headers):
        return self._request("POST", f"/labeling/label-specs/{label_spec_id}/approve",
                             None, headers)

    def request_revision_label_spec(self, label_spec_id, revision_note, headers):
        return self._request(
            "POST", f"/labeling/label-specs/{label_spec_id}/request-revision",
            {"revision_note": revision_note}, headers)

    def publish_label_spec(self, label_spec_id, effective_from, effective_to, headers):
        return self._request("POST", f"/labeling/label-specs/{label_spec_id}/publish",
                             {"effective_from": effective_from,
                              "effective_to": effective_to}, headers)

    def publish_label_spec_raw(self, label_spec_id, payload, headers):
        return self._request("POST", f"/labeling/label-specs/{label_spec_id}/publish",
                             payload, headers)

    def withdraw_label_spec(self, label_spec_id, withdrawn_reason, headers):
        return self._request("POST", f"/labeling/label-specs/{label_spec_id}/withdraw",
                             {"withdrawn_reason": withdrawn_reason}, headers)

    def create_hangtag(self, parent_label_spec_id, payload, headers):
        return self._request(
            "POST", f"/labeling/label-specs/{parent_label_spec_id}/hangtags",
            payload, headers)

    def get_label_spec(self, label_spec_id, headers):
        return self._request("GET", f"/labeling/label-specs/{label_spec_id}",
                             headers=headers)

    def list_label_specs(self, headers, params=None):
        return self._request("GET", "/labeling/label-specs", headers=headers, params=params)

    # --- imported goods ---------------------------------------------------
    def create_import_shipment(self, payload, headers):
        return self._request("POST", "/labeling/import-shipments", payload, headers)

    def marking_review(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/labeling/import-shipments/{shipment_id}/marking-review",
            payload, headers)

    def correct_import_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/labeling/import-shipments/{shipment_id}/correct",
                             payload, headers)

    def get_import_shipment(self, shipment_id, headers):
        return self._request("GET", f"/labeling/import-shipments/{shipment_id}",
                             headers=headers)

    def list_import_shipments(self, headers, params=None):
        return self._request("GET", "/labeling/import-shipments",
                             headers=headers, params=params)

    # --- compliance audits and findings ----------------------------------
    def create_compliance_audit(self, payload, headers):
        return self._request("POST", "/labeling/compliance-audits", payload, headers)

    def close_compliance_audit(self, audit_id, headers):
        return self._request("POST", f"/labeling/compliance-audits/{audit_id}/close",
                             None, headers)

    def get_compliance_audit(self, audit_id, headers):
        return self._request("GET", f"/labeling/compliance-audits/{audit_id}",
                             headers=headers)

    def list_compliance_audits(self, headers, params=None):
        return self._request("GET", "/labeling/compliance-audits",
                             headers=headers, params=params)

    def create_audit_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/labeling/compliance-audits/{audit_id}/findings",
                             payload, headers)

    def record_finding_disposition(self, finding_id, payload, headers):
        return self._request("POST", f"/labeling/audit-findings/{finding_id}/disposition",
                             payload, headers)

    def verify_finding(self, finding_id, headers):
        return self._request("POST", f"/labeling/audit-findings/{finding_id}/verify",
                             None, headers)

    def reopen_finding(self, finding_id, reopen_reason, headers):
        return self._request("POST", f"/labeling/audit-findings/{finding_id}/reopen",
                             {"reopen_reason": reopen_reason}, headers)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"/labeling/audit-findings/{finding_id}",
                             headers=headers)

    def list_audit_findings(self, headers, params=None):
        return self._request("GET", "/labeling/audit-findings",
                             headers=headers, params=params)


api_client = ApiClient()
