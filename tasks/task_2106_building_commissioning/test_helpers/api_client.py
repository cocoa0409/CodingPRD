"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- CxProject
    def create_cx_project(self, payload, headers):
        return self._request("POST", "/cx-projects", payload, headers)

    def get_cx_project(self, project_id, headers):
        return self._request("GET", f"/cx-projects/{project_id}", headers=headers)

    def list_cx_projects(self, headers, params=None):
        return self._request("GET", "/cx-projects", headers=headers, params=params)

    def advance_phase(self, project_id, payload, headers):
        return self._request(
            "POST", f"/cx-projects/{project_id}/advance-phase", payload, headers
        )

    def issue_acceptance(self, project_id, payload, headers):
        return self._request(
            "POST", f"/cx-projects/{project_id}/issue-acceptance", payload, headers
        )

    def get_readiness(self, project_id, headers):
        return self._request(
            "GET", f"/cx-projects/{project_id}/readiness", headers=headers
        )

    def run_seasonal_sweep(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/cx-projects/{project_id}/run-seasonal-sweep", payload or {}, headers
        )

    # --------------------------------------------------------- OwnerRequirement
    def create_owner_requirement(self, payload, headers):
        return self._request("POST", "/owner-requirements", payload, headers)

    def list_owner_requirements(self, headers, params=None):
        return self._request(
            "GET", "/owner-requirements", headers=headers, params=params
        )

    def get_owner_requirement(self, requirement_id, headers):
        return self._request(
            "GET", f"/owner-requirements/{requirement_id}", headers=headers
        )

    def approve_owner_requirement(self, requirement_id, headers, payload=None):
        return self._request(
            "POST", f"/owner-requirements/{requirement_id}/approve", payload or {}, headers
        )

    def revise_owner_requirement(self, requirement_id, payload, headers):
        return self._request(
            "POST", f"/owner-requirements/{requirement_id}/revise", payload, headers
        )

    # ------------------------------------------------------------------- CxPlan
    def create_cx_plan(self, payload, headers):
        return self._request("POST", "/cx-plans", payload, headers)

    def list_cx_plans(self, headers, params=None):
        return self._request("GET", "/cx-plans", headers=headers, params=params)

    def get_cx_plan(self, plan_id, headers):
        return self._request("GET", f"/cx-plans/{plan_id}", headers=headers)

    def approve_cx_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/cx-plans/{plan_id}/approve", payload or {}, headers
        )

    # ---------------------------------------------------------------- Submittal
    def create_submittal(self, payload, headers):
        return self._request("POST", "/submittals", payload, headers)

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/submittals", headers=headers, params=params)

    def get_submittal(self, submittal_id, headers):
        return self._request("GET", f"/submittals/{submittal_id}", headers=headers)

    def review_submittal(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/submittals/{submittal_id}/review", payload, headers
        )

    def resubmit_submittal(self, submittal_id, headers, payload=None):
        return self._request(
            "POST", f"/submittals/{submittal_id}/resubmit", payload or {}, headers
        )

    # ------------------------------------------------------------ EquipmentUnit
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, equipment_id, headers):
        return self._request("GET", f"/equipment-units/{equipment_id}", headers=headers)

    def set_install_status(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/equipment-units/{equipment_id}/install-status", payload, headers
        )

    # --------------------------------------------------- PrefunctionalChecklist
    def create_prefunctional_checklist(self, payload, headers):
        return self._request("POST", "/prefunctional-checklists", payload, headers)

    def list_prefunctional_checklists(self, headers, params=None):
        return self._request(
            "GET", "/prefunctional-checklists", headers=headers, params=params
        )

    def get_prefunctional_checklist(self, checklist_id, headers):
        return self._request(
            "GET", f"/prefunctional-checklists/{checklist_id}", headers=headers
        )

    def add_checklist_item(self, checklist_id, payload, headers):
        return self._request(
            "POST", f"/prefunctional-checklists/{checklist_id}/items", payload, headers
        )

    def record_checklist_item(self, checklist_id, payload, headers):
        return self._request(
            "POST",
            f"/prefunctional-checklists/{checklist_id}/record-item",
            payload,
            headers,
        )

    def execute_checklist(self, checklist_id, headers, payload=None):
        return self._request(
            "POST",
            f"/prefunctional-checklists/{checklist_id}/execute",
            payload or {},
            headers,
        )

    def verify_checklist(self, checklist_id, headers, payload=None):
        return self._request(
            "POST",
            f"/prefunctional-checklists/{checklist_id}/verify",
            payload or {},
            headers,
        )

    def reject_checklist(self, checklist_id, payload, headers):
        return self._request(
            "POST", f"/prefunctional-checklists/{checklist_id}/reject", payload, headers
        )

    # ----------------------------------------------------------- FunctionalTest
    def create_functional_test(self, payload, headers):
        return self._request("POST", "/functional-tests", payload, headers)

    def list_functional_tests(self, headers, params=None):
        return self._request("GET", "/functional-tests", headers=headers, params=params)

    def get_functional_test(self, test_id, headers):
        return self._request("GET", f"/functional-tests/{test_id}", headers=headers)

    def start_functional_test(self, test_id, headers, payload=None):
        return self._request(
            "POST", f"/functional-tests/{test_id}/start", payload or {}, headers
        )

    def record_functional_test_result(self, test_id, payload, headers):
        return self._request(
            "POST", f"/functional-tests/{test_id}/record-result", payload, headers
        )

    def schedule_retest(self, test_id, payload, headers):
        return self._request(
            "POST", f"/functional-tests/{test_id}/schedule-retest", payload, headers
        )

    # -------------------------------------------------------------------- Issue
    def create_issue(self, payload, headers):
        return self._request("POST", "/issues", payload, headers)

    def list_issues(self, headers, params=None):
        return self._request("GET", "/issues", headers=headers, params=params)

    def get_issue(self, issue_id, headers):
        return self._request("GET", f"/issues/{issue_id}", headers=headers)

    def propose_resolution(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/issues/{issue_id}/propose-resolution", payload, headers
        )

    def verify_closure(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/issues/{issue_id}/verify-closure", payload, headers
        )

    def reopen_issue(self, issue_id, payload, headers):
        return self._request("POST", f"/issues/{issue_id}/reopen", payload, headers)

    def defer_issue(self, issue_id, payload, headers):
        return self._request("POST", f"/issues/{issue_id}/defer", payload, headers)

    def void_issue(self, issue_id, payload, headers):
        return self._request("POST", f"/issues/{issue_id}/void", payload, headers)

    # ------------------------------------------------------------- DeferredTest
    def create_deferred_test(self, payload, headers):
        return self._request("POST", "/deferred-tests", payload, headers)

    def list_deferred_tests(self, headers, params=None):
        return self._request("GET", "/deferred-tests", headers=headers, params=params)

    def get_deferred_test(self, deferred_test_id, headers):
        return self._request(
            "GET", f"/deferred-tests/{deferred_test_id}", headers=headers
        )

    def execute_deferred_test(self, deferred_test_id, payload, headers):
        return self._request(
            "POST", f"/deferred-tests/{deferred_test_id}/execute", payload, headers
        )

    # ------------------------------------------------------ CloseoutDeliverable
    def create_closeout_deliverable(self, payload, headers):
        return self._request("POST", "/closeout-deliverables", payload, headers)

    def list_closeout_deliverables(self, headers, params=None):
        return self._request(
            "GET", "/closeout-deliverables", headers=headers, params=params
        )

    def get_closeout_deliverable(self, deliverable_id, headers):
        return self._request(
            "GET", f"/closeout-deliverables/{deliverable_id}", headers=headers
        )

    def deliver_closeout_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/closeout-deliverables/{deliverable_id}/deliver", payload, headers
        )

    def accept_closeout_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/closeout-deliverables/{deliverable_id}/accept", payload, headers
        )

    def return_closeout_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/closeout-deliverables/{deliverable_id}/return", payload, headers
        )

    # ----------------------------------------------------- CertificationCredit
    def create_certification_credit(self, payload, headers):
        return self._request("POST", "/certification-credits", payload, headers)

    def list_certification_credits(self, headers, params=None):
        return self._request(
            "GET", "/certification-credits", headers=headers, params=params
        )

    def get_certification_credit(self, credit_id, headers):
        return self._request(
            "GET", f"/certification-credits/{credit_id}", headers=headers
        )

    def attach_credit_evidence(self, credit_id, payload, headers):
        return self._request(
            "POST", f"/certification-credits/{credit_id}/evidence", payload, headers
        )

    def list_credit_evidence(self, credit_id, headers, params=None):
        return self._request(
            "GET",
            f"/certification-credits/{credit_id}/evidence",
            headers=headers,
            params=params,
        )

    def submit_certification_credit(self, credit_id, payload, headers):
        return self._request(
            "POST", f"/certification-credits/{credit_id}/submit", payload, headers
        )

    def adjudicate_certification_credit(self, credit_id, payload, headers):
        return self._request(
            "POST", f"/certification-credits/{credit_id}/adjudicate", payload, headers
        )

    # ----------------------------------------------------------- EnergyBaseline
    def create_energy_baseline(self, payload, headers):
        return self._request("POST", "/energy-baselines", payload, headers)

    def list_energy_baselines(self, headers, params=None):
        return self._request("GET", "/energy-baselines", headers=headers, params=params)

    def get_energy_baseline(self, baseline_id, headers):
        return self._request("GET", f"/energy-baselines/{baseline_id}", headers=headers)

    def record_post_period(self, baseline_id, payload, headers):
        return self._request(
            "POST", f"/energy-baselines/{baseline_id}/post-period", payload, headers
        )

    def certify_savings(self, baseline_id, payload, headers):
        return self._request(
            "POST", f"/energy-baselines/{baseline_id}/certify-savings", payload, headers
        )

    # --------------------------------------------------------------- Logical clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
