"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    # --- bureaus ---
    def create_bureau(self, payload, headers):
        return self._request("POST", "/bureaus", payload, headers)

    def get_bureau(self, bureau_id, headers):
        return self._request("GET", f"/bureaus/{bureau_id}", headers=headers)

    # --- carriers ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    # --- employers ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    # --- class codes ---
    def create_class_code(self, payload, headers):
        return self._request("POST", "/class-codes", payload, headers)

    def get_class_code(self, class_code_id, headers):
        return self._request("GET", f"/class-codes/{class_code_id}", headers=headers)

    # --- rating tables ---
    def create_rating_table(self, payload, headers):
        return self._request("POST", "/rating-tables", payload, headers)

    def get_rating_table(self, rating_table_id, headers):
        return self._request("GET", f"/rating-tables/{rating_table_id}", headers=headers)

    def promulgate_rating_table(self, rating_table_id, headers):
        return self._request(
            "POST", f"/rating-tables/{rating_table_id}/promulgate", headers=headers
        )

    # --- policies ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def list_employer_policies(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/employers/{employer_id}/policies", headers=headers, params=params
        )

    # --- unit statistical reports ---
    def create_unit_stat_report(self, payload, headers):
        return self._request("POST", "/unit-stat-reports", payload, headers)

    def get_unit_stat_report(self, report_id, headers):
        return self._request("GET", f"/unit-stat-reports/{report_id}", headers=headers)

    def list_unit_stat_reports(self, headers, params=None):
        return self._request("GET", "/unit-stat-reports", headers=headers, params=params)

    def list_policy_unit_stat_reports(self, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/policies/{policy_id}/unit-stat-reports",
            headers=headers,
            params=params,
        )

    def validate_unit_stat_report(self, report_id, headers):
        return self._request(
            "POST", f"/unit-stat-reports/{report_id}/validate", headers=headers
        )

    # --- class assignments ---
    def create_class_assignment(self, payload, headers):
        return self._request("POST", "/class-assignments", payload, headers)

    def get_class_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/class-assignments/{assignment_id}", headers=headers
        )

    def list_class_assignments(self, headers, params=None):
        return self._request("GET", "/class-assignments", headers=headers, params=params)

    def list_employer_class_assignments(self, employer_id, headers, params=None):
        return self._request(
            "GET",
            f"/employers/{employer_id}/class-assignments",
            headers=headers,
            params=params,
        )

    def assign_class_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/class-assignments/{assignment_id}/assign", headers=headers
        )

    def confirm_class_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/class-assignments/{assignment_id}/confirm", headers=headers
        )

    def withdraw_class_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/class-assignments/{assignment_id}/withdraw", headers=headers
        )

    # --- inspections ---
    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def list_assignment_inspections(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/class-assignments/{assignment_id}/inspections",
            headers=headers,
            params=params,
        )

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/complete", payload, headers
        )

    def waive_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/waive", headers=headers
        )

    # --- class assignment disputes ---
    def create_class_assignment_dispute(self, payload, headers):
        return self._request("POST", "/class-assignment-disputes", payload, headers)

    def get_class_assignment_dispute(self, dispute_id, headers):
        return self._request(
            "GET", f"/class-assignment-disputes/{dispute_id}", headers=headers
        )

    def list_class_assignment_disputes(self, headers, params=None):
        return self._request(
            "GET", "/class-assignment-disputes", headers=headers, params=params
        )

    def list_assignment_disputes(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/class-assignments/{assignment_id}/disputes",
            headers=headers,
            params=params,
        )

    def review_class_assignment_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/class-assignment-disputes/{dispute_id}/review", headers=headers
        )

    def resolve_class_assignment_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/class-assignment-disputes/{dispute_id}/resolve", payload, headers
        )

    def withdraw_class_assignment_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/class-assignment-disputes/{dispute_id}/withdraw", headers=headers
        )

    # --- experience modification sheets ---
    def create_experience_mod_sheet(self, payload, headers):
        return self._request("POST", "/experience-mod-sheets", payload, headers)

    def get_experience_mod_sheet(self, sheet_id, headers):
        return self._request(
            "GET", f"/experience-mod-sheets/{sheet_id}", headers=headers
        )

    def list_experience_mod_sheets(self, headers, params=None):
        return self._request(
            "GET", "/experience-mod-sheets", headers=headers, params=params
        )

    def list_employer_experience_mod_sheets(self, employer_id, headers, params=None):
        return self._request(
            "GET",
            f"/employers/{employer_id}/experience-mod-sheets",
            headers=headers,
            params=params,
        )

    def promulgate_experience_mod_sheet(self, sheet_id, headers):
        return self._request(
            "POST", f"/experience-mod-sheets/{sheet_id}/promulgate", headers=headers
        )

    def finalize_experience_mod_sheet(self, sheet_id, headers):
        return self._request(
            "POST", f"/experience-mod-sheets/{sheet_id}/finalize", headers=headers
        )

    # --- modification appeals ---
    def create_mod_appeal(self, payload, headers):
        return self._request("POST", "/mod-appeals", payload, headers)

    def get_mod_appeal(self, appeal_id, headers):
        return self._request("GET", f"/mod-appeals/{appeal_id}", headers=headers)

    def list_mod_appeals(self, headers, params=None):
        return self._request("GET", "/mod-appeals", headers=headers, params=params)

    def list_sheet_appeals(self, sheet_id, headers, params=None):
        return self._request(
            "GET",
            f"/experience-mod-sheets/{sheet_id}/appeals",
            headers=headers,
            params=params,
        )

    def review_mod_appeal(self, appeal_id, headers):
        return self._request(
            "POST", f"/mod-appeals/{appeal_id}/review", headers=headers
        )

    def decide_mod_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/mod-appeals/{appeal_id}/decide", payload, headers
        )

    def withdraw_mod_appeal(self, appeal_id, headers):
        return self._request(
            "POST", f"/mod-appeals/{appeal_id}/withdraw", headers=headers
        )

    # --- ownership changes ---
    def create_ownership_change(self, payload, headers):
        return self._request("POST", "/ownership-changes", payload, headers)

    def get_ownership_change(self, change_id, headers):
        return self._request("GET", f"/ownership-changes/{change_id}", headers=headers)

    def list_ownership_changes(self, headers, params=None):
        return self._request("GET", "/ownership-changes", headers=headers, params=params)

    def list_employer_ownership_changes(self, employer_id, headers, params=None):
        return self._request(
            "GET",
            f"/employers/{employer_id}/ownership-changes",
            headers=headers,
            params=params,
        )

    def combine_ownership_change(self, change_id, payload, headers):
        return self._request(
            "POST", f"/ownership-changes/{change_id}/combine", payload, headers
        )

    def not_combined_ownership_change(self, change_id, headers):
        return self._request(
            "POST", f"/ownership-changes/{change_id}/not_combined", headers=headers
        )

    def reverse_ownership_change(self, change_id, headers):
        return self._request(
            "POST", f"/ownership-changes/{change_id}/reverse", headers=headers
        )

    # --- combinability groups ---
    def get_combinability_group(self, group_id, headers):
        return self._request(
            "GET", f"/combinability-groups/{group_id}", headers=headers
        )

    def list_combinability_groups(self, headers, params=None):
        return self._request(
            "GET", "/combinability-groups", headers=headers, params=params
        )

    # --- assigned risk enrollments ---
    def create_assigned_risk_enrollment(self, payload, headers):
        return self._request("POST", "/assigned-risk-enrollments", payload, headers)

    def get_assigned_risk_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/assigned-risk-enrollments/{enrollment_id}", headers=headers
        )

    def list_assigned_risk_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/assigned-risk-enrollments", headers=headers, params=params
        )

    def list_employer_assigned_risk_enrollments(self, employer_id, headers, params=None):
        return self._request(
            "GET",
            f"/employers/{employer_id}/assigned-risk-enrollments",
            headers=headers,
            params=params,
        )

    def list_carrier_assigned_risk_enrollments(self, carrier_id, headers, params=None):
        return self._request(
            "GET",
            f"/carriers/{carrier_id}/assigned-risk-enrollments",
            headers=headers,
            params=params,
        )

    def assign_assigned_risk_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/assigned-risk-enrollments/{enrollment_id}/assign",
            payload,
            headers,
        )

    def cancel_assigned_risk_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/assigned-risk-enrollments/{enrollment_id}/cancel", headers=headers
        )

    # --- assigned risk take-outs ---
    def create_assigned_risk_take_out(self, payload, headers):
        return self._request("POST", "/assigned-risk-take-outs", payload, headers)

    def get_assigned_risk_take_out(self, take_out_id, headers):
        return self._request(
            "GET", f"/assigned-risk-take-outs/{take_out_id}", headers=headers
        )

    def list_assigned_risk_take_outs(self, headers, params=None):
        return self._request(
            "GET", "/assigned-risk-take-outs", headers=headers, params=params
        )

    def list_enrollment_take_outs(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/assigned-risk-enrollments/{enrollment_id}/take-outs",
            headers=headers,
            params=params,
        )

    def approve_assigned_risk_take_out(self, take_out_id, headers):
        return self._request(
            "POST", f"/assigned-risk-take-outs/{take_out_id}/approve", headers=headers
        )

    def reject_assigned_risk_take_out(self, take_out_id, headers):
        return self._request(
            "POST", f"/assigned-risk-take-outs/{take_out_id}/reject", headers=headers
        )

    # --- underwriting reviews ---
    def get_underwriting_review(self, review_id, headers):
        return self._request(
            "GET", f"/underwriting-reviews/{review_id}", headers=headers
        )

    def approve_underwriting_review(self, review_id, headers):
        return self._request(
            "POST", f"/underwriting-reviews/{review_id}/approve", headers=headers
        )

    def reject_underwriting_review(self, review_id, headers):
        return self._request(
            "POST", f"/underwriting-reviews/{review_id}/reject", headers=headers
        )


api_client = ApiClient()
