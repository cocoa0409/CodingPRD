"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- Laboratories ---
    def create_laboratory(self, payload, headers):
        return self._request("POST", "/laboratories", payload, headers)

    def list_laboratories(self, headers, params=None):
        return self._request("GET", "/laboratories", headers=headers, params=params)

    def get_laboratory(self, lab_id, headers):
        return self._request("GET", f"/laboratories/{lab_id}", headers=headers)

    def reinstate_laboratory(self, lab_id, headers):
        return self._request("POST", f"/laboratories/{lab_id}/reinstate", {}, headers)

    def revoke_laboratory(self, lab_id, headers):
        return self._request("POST", f"/laboratories/{lab_id}/revoke", {}, headers)

    def list_laboratory_enrollments(self, lab_id, headers, params=None):
        return self._request("GET", f"/laboratories/{lab_id}/enrollments",
                             headers=headers, params=params)

    # --- Inspector profiles ---
    def create_inspector_profile(self, payload, headers):
        return self._request("POST", "/inspector-profiles", payload, headers)

    def list_inspector_profiles(self, headers, params=None):
        return self._request("GET", "/inspector-profiles", headers=headers, params=params)

    def get_inspector_profile(self, inspector_id, headers):
        return self._request("GET", f"/inspector-profiles/{inspector_id}", headers=headers)

    # --- Discipline enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollment_sections(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/sections",
                             headers=headers, params=params)

    # --- Testing sections ---
    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def assign_checklist(self, section_id, payload, headers):
        return self._request("POST", f"/sections/{section_id}/assign-checklist",
                             payload, headers)

    # --- Checklist editions ---
    def create_checklist_edition(self, payload, headers):
        return self._request("POST", "/checklist-editions", payload, headers)

    def list_checklist_editions(self, headers, params=None):
        return self._request("GET", "/checklist-editions", headers=headers, params=params)

    # --- PT subscriptions ---
    def create_pt_subscription(self, payload, headers):
        return self._request("POST", "/pt-subscriptions", payload, headers)

    def list_pt_subscriptions(self, headers, params=None):
        return self._request("GET", "/pt-subscriptions", headers=headers, params=params)

    def get_pt_subscription(self, subscription_id, headers):
        return self._request("GET", f"/pt-subscriptions/{subscription_id}", headers=headers)

    # --- PT shipments ---
    def create_pt_shipment(self, payload, headers):
        return self._request("POST", "/pt-shipments", payload, headers)

    def list_pt_shipments(self, headers, params=None):
        return self._request("GET", "/pt-shipments", headers=headers, params=params)

    def get_pt_shipment(self, shipment_id, headers):
        return self._request("GET", f"/pt-shipments/{shipment_id}", headers=headers)

    def close_pt_shipment(self, shipment_id, headers):
        return self._request("POST", f"/pt-shipments/{shipment_id}/close", {}, headers)

    # --- PT results ---
    def create_pt_result(self, payload, headers):
        return self._request("POST", "/pt-results", payload, headers)

    def list_pt_results(self, headers, params=None):
        return self._request("GET", "/pt-results", headers=headers, params=params)

    def get_pt_result(self, result_id, headers):
        return self._request("GET", f"/pt-results/{result_id}", headers=headers)

    def void_pt_result(self, result_id, headers):
        return self._request("POST", f"/pt-results/{result_id}/void", {}, headers)

    # --- PT investigations ---
    def list_pt_investigations(self, headers, params=None):
        return self._request("GET", "/pt-investigations", headers=headers, params=params)

    def get_pt_investigation(self, investigation_id, headers):
        return self._request("GET", f"/pt-investigations/{investigation_id}", headers=headers)

    def begin_review(self, investigation_id, headers):
        return self._request("POST", f"/pt-investigations/{investigation_id}/begin-review",
                             {}, headers)

    def require_corrective_action(self, investigation_id, payload, headers):
        return self._request("POST",
                             f"/pt-investigations/{investigation_id}/require-corrective-action",
                             payload, headers)

    def resolve_investigation(self, investigation_id, headers):
        return self._request("POST", f"/pt-investigations/{investigation_id}/resolve",
                             {}, headers)

    def cease_testing(self, investigation_id, headers):
        return self._request("POST", f"/pt-investigations/{investigation_id}/cease-testing",
                             {}, headers)

    # --- Inspection cycles ---
    def create_inspection_cycle(self, payload, headers):
        return self._request("POST", "/inspection-cycles", payload, headers)

    def list_inspection_cycles(self, headers, params=None):
        return self._request("GET", "/inspection-cycles", headers=headers, params=params)

    def get_inspection_cycle(self, cycle_id, headers):
        return self._request("GET", f"/inspection-cycles/{cycle_id}", headers=headers)

    def screen_team(self, cycle_id, headers):
        return self._request("POST", f"/inspection-cycles/{cycle_id}/screen-team",
                             {}, headers)

    def conduct_cycle(self, cycle_id, headers):
        return self._request("POST", f"/inspection-cycles/{cycle_id}/conduct", {}, headers)

    def issue_findings(self, cycle_id, headers):
        return self._request("POST", f"/inspection-cycles/{cycle_id}/issue-findings",
                             {}, headers)

    def decide_cycle(self, cycle_id, decision, headers):
        return self._request("POST", f"/inspection-cycles/{cycle_id}/decide",
                             {"decision": decision}, headers)

    def appeal_cycle(self, cycle_id, headers):
        return self._request("POST", f"/inspection-cycles/{cycle_id}/appeal", {}, headers)

    def self_inspect_cycle(self, cycle_id, headers):
        return self._request("POST", f"/inspection-cycles/{cycle_id}/self-inspect",
                             {}, headers)

    def re_decide_cycle(self, cycle_id, decision, headers):
        return self._request("POST", f"/inspection-cycles/{cycle_id}/re-decide",
                             {"decision": decision}, headers)

    # --- Team assignments ---
    def create_team_assignment(self, payload, headers):
        return self._request("POST", "/team-assignments", payload, headers)

    def list_team_assignments(self, headers, params=None):
        return self._request("GET", "/team-assignments", headers=headers, params=params)

    def get_team_assignment(self, assignment_id, headers):
        return self._request("GET", f"/team-assignments/{assignment_id}", headers=headers)

    def clear_assignment(self, assignment_id, headers):
        return self._request("POST", f"/team-assignments/{assignment_id}/clear",
                             {}, headers)

    def flag_conflict(self, assignment_id, headers):
        return self._request("POST", f"/team-assignments/{assignment_id}/flag-conflict",
                             {}, headers)

    def replace_assignment(self, assignment_id, replacement_inspector_id, headers):
        return self._request("POST", f"/team-assignments/{assignment_id}/replace",
                             {"replacement_inspector_id": replacement_inspector_id}, headers)

    # --- Inspection findings ---
    def create_finding(self, payload, headers):
        return self._request("POST", "/inspection-findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/inspection-findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/inspection-findings/{finding_id}", headers=headers)

    def respond_to_finding(self, finding_id, response_text, headers):
        return self._request("POST", f"/inspection-findings/{finding_id}/respond",
                             {"response_text": response_text}, headers)

    def accept_finding(self, finding_id, headers):
        return self._request("POST", f"/inspection-findings/{finding_id}/accept",
                             {}, headers)

    def withdraw_finding(self, finding_id, headers):
        return self._request("POST", f"/inspection-findings/{finding_id}/withdraw",
                             {}, headers)

    # --- Personnel records ---
    def create_personnel_record(self, payload, headers):
        return self._request("POST", "/personnel-records", payload, headers)

    def list_personnel_records(self, headers, params=None):
        return self._request("GET", "/personnel-records", headers=headers, params=params)

    def get_personnel_record(self, personnel_id, headers):
        return self._request("GET", f"/personnel-records/{personnel_id}", headers=headers)

    def verify_qualification(self, personnel_id, headers):
        return self._request("POST",
                             f"/personnel-records/{personnel_id}/verify-qualification",
                             {}, headers)

    # --- Competency assessments ---
    def create_competency_assessment(self, payload, headers):
        return self._request("POST", "/competency-assessments", payload, headers)

    def list_competency_assessments(self, headers, params=None):
        return self._request("GET", "/competency-assessments", headers=headers, params=params)

    def get_competency_assessment(self, assessment_id, headers):
        return self._request("GET", f"/competency-assessments/{assessment_id}",
                             headers=headers)

    # --- Method validations ---
    def create_method_validation(self, payload, headers):
        return self._request("POST", "/method-validations", payload, headers)

    def list_method_validations(self, headers, params=None):
        return self._request("GET", "/method-validations", headers=headers, params=params)

    def get_method_validation(self, mv_id, headers):
        return self._request("GET", f"/method-validations/{mv_id}", headers=headers)

    def submit_method_validation(self, mv_id, headers):
        return self._request("POST", f"/method-validations/{mv_id}/submit", {}, headers)

    def approve_method_validation(self, mv_id, headers):
        return self._request("POST", f"/method-validations/{mv_id}/approve", {}, headers)

    def reject_method_validation(self, mv_id, headers):
        return self._request("POST", f"/method-validations/{mv_id}/reject", {}, headers)


api_client = ApiClient()
