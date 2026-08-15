"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.10)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/robotics/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------
    # Integrator orgs & users (PRD §3.1)
    # ------------------------------------------------------------------
    def create_integrator_org(self, payload, headers):
        return self._request("POST", "/robotics/integrator-orgs", payload, headers)

    def get_integrator_org(self, org_id, headers):
        return self._request("GET", f"/robotics/integrator-orgs/{org_id}", headers=headers)

    def list_integrator_orgs(self, headers, params=None):
        return self._request("GET", "/robotics/integrator-orgs", headers=headers, params=params)

    def create_integrator_user(self, org_id, payload, headers):
        return self._request(
            "POST", f"/robotics/integrator-orgs/{org_id}/users", payload, headers
        )

    def list_integrator_users(self, org_id, headers, params=None):
        return self._request(
            "GET", f"/robotics/integrator-orgs/{org_id}/users", headers=headers, params=params
        )

    def get_user(self, user_id, headers):
        return self._request("GET", f"/robotics/users/{user_id}", headers=headers)

    def list_user_approved_safety_assessments(self, user_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/users/{user_id}/approved-safety-assessments",
            headers=headers,
            params=params,
        )

    def list_user_recorded_acceptance_tests(self, user_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/users/{user_id}/recorded-acceptance-tests",
            headers=headers,
            params=params,
        )

    def list_user_training_sessions(self, user_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/users/{user_id}/training-sessions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Customer sites (PRD §3.1)
    # ------------------------------------------------------------------
    def create_customer_site(self, org_id, payload, headers):
        return self._request(
            "POST", f"/robotics/integrator-orgs/{org_id}/customer-sites", payload, headers
        )

    def list_customer_sites(self, org_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/integrator-orgs/{org_id}/customer-sites",
            headers=headers,
            params=params,
        )

    def get_customer_site(self, site_id, headers):
        return self._request("GET", f"/robotics/customer-sites/{site_id}", headers=headers)

    def update_customer_site(self, site_id, payload, headers):
        return self._request(
            "PATCH", f"/robotics/customer-sites/{site_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Cell projects (PRD §3.1, §3.6, §3.9)
    # ------------------------------------------------------------------
    def create_cell_project(self, site_id, payload, headers):
        return self._request(
            "POST", f"/robotics/customer-sites/{site_id}/cell-projects", payload, headers
        )

    def list_cell_projects(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/customer-sites/{site_id}/cell-projects",
            headers=headers,
            params=params,
        )

    def get_cell_project(self, project_id, headers):
        return self._request("GET", f"/robotics/cell-projects/{project_id}", headers=headers)

    def advance_cell_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/advance", payload, headers
        )

    def hold_cell_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/hold", payload, headers
        )

    def resume_cell_project(self, project_id, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/resume", {}, headers
        )

    def terminate_cell_project(self, project_id, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/terminate", {}, headers
        )

    # ------------------------------------------------------------------
    # Application studies (PRD §3.2)
    # ------------------------------------------------------------------
    def create_application_study(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/robotics/cell-projects/{project_id}/application-studies",
            payload,
            headers,
        )

    def list_application_studies(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/application-studies",
            headers=headers,
            params=params,
        )

    def get_application_study(self, study_id, headers):
        return self._request(
            "GET", f"/robotics/application-studies/{study_id}", headers=headers
        )

    def list_superseded_by(self, study_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/application-studies/{study_id}/superseded-by",
            headers=headers,
            params=params,
        )

    def submit_application_study(self, study_id, headers):
        return self._request(
            "POST", f"/robotics/application-studies/{study_id}/submit", {}, headers
        )

    def approve_application_study(self, study_id, headers):
        return self._request(
            "POST", f"/robotics/application-studies/{study_id}/approve", {}, headers
        )

    def reject_application_study(self, study_id, headers):
        return self._request(
            "POST", f"/robotics/application-studies/{study_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Safety risk assessments (PRD §3.3)
    # ------------------------------------------------------------------
    def create_safety_risk_assessment(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/robotics/cell-projects/{project_id}/safety-risk-assessments",
            payload,
            headers,
        )

    def list_safety_risk_assessments(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/safety-risk-assessments",
            headers=headers,
            params=params,
        )

    def get_safety_risk_assessment(self, sra_id, headers):
        return self._request(
            "GET", f"/robotics/safety-risk-assessments/{sra_id}", headers=headers
        )

    def submit_safety_risk_assessment(self, sra_id, headers):
        return self._request(
            "POST", f"/robotics/safety-risk-assessments/{sra_id}/submit", {}, headers
        )

    def approve_safety_risk_assessment(self, sra_id, headers):
        return self._request(
            "POST", f"/robotics/safety-risk-assessments/{sra_id}/approve", {}, headers
        )

    def reject_safety_risk_assessment(self, sra_id, headers):
        return self._request(
            "POST", f"/robotics/safety-risk-assessments/{sra_id}/reject", {}, headers
        )

    def revise_safety_risk_assessment(self, sra_id, headers):
        return self._request(
            "POST", f"/robotics/safety-risk-assessments/{sra_id}/revise", {}, headers
        )

    # ------------------------------------------------------------------
    # Robot selections (PRD §3.4)
    # ------------------------------------------------------------------
    def create_robot_selection(self, project_id, payload, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/robot-selections", payload, headers
        )

    def list_robot_selections(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/robot-selections",
            headers=headers,
            params=params,
        )

    def get_robot_selection(self, rs_id, headers):
        return self._request("GET", f"/robotics/robot-selections/{rs_id}", headers=headers)

    def validate_robot_selection(self, rs_id, headers):
        return self._request(
            "POST", f"/robotics/robot-selections/{rs_id}/validate", {}, headers
        )

    def lock_robot_selection(self, rs_id, headers):
        return self._request(
            "POST", f"/robotics/robot-selections/{rs_id}/lock", {}, headers
        )

    def reject_robot_selection(self, rs_id, headers):
        return self._request(
            "POST", f"/robotics/robot-selections/{rs_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Robot programs (PRD §3.5)
    # ------------------------------------------------------------------
    def create_robot_program(self, project_id, payload, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/robot-programs", payload, headers
        )

    def list_robot_programs(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/robot-programs",
            headers=headers,
            params=params,
        )

    def get_robot_program(self, rp_id, headers):
        return self._request("GET", f"/robotics/robot-programs/{rp_id}", headers=headers)

    def code_complete_robot_program(self, rp_id, headers):
        return self._request(
            "POST", f"/robotics/robot-programs/{rp_id}/code-complete", {}, headers
        )

    def peer_review_robot_program(self, rp_id, headers):
        return self._request(
            "POST", f"/robotics/robot-programs/{rp_id}/peer-review", {}, headers
        )

    def simulate_robot_program(self, rp_id, headers):
        return self._request(
            "POST", f"/robotics/robot-programs/{rp_id}/simulate", {}, headers
        )

    def record_simulation(self, rp_id, payload, headers):
        return self._request(
            "POST", f"/robotics/robot-programs/{rp_id}/simulate/record", payload, headers
        )

    def release_robot_program(self, rp_id, headers):
        return self._request(
            "POST", f"/robotics/robot-programs/{rp_id}/release", {}, headers
        )

    # ------------------------------------------------------------------
    # Acceptance tests (PRD §3.6)
    # ------------------------------------------------------------------
    def create_acceptance_test(self, project_id, payload, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/acceptance-tests", payload, headers
        )

    def list_acceptance_tests(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/acceptance-tests",
            headers=headers,
            params=params,
        )

    def get_acceptance_test(self, at_id, headers):
        return self._request("GET", f"/robotics/acceptance-tests/{at_id}", headers=headers)

    def record_acceptance_test(self, at_id, headers):
        return self._request(
            "POST", f"/robotics/acceptance-tests/{at_id}/record", {}, headers
        )

    def fail_acceptance_test(self, at_id, headers):
        return self._request("POST", f"/robotics/acceptance-tests/{at_id}/fail", {}, headers)

    # ------------------------------------------------------------------
    # Spare parts packages (PRD §3.7)
    # ------------------------------------------------------------------
    def create_spare_parts_package(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/robotics/cell-projects/{project_id}/spare-parts-packages",
            payload,
            headers,
        )

    def list_spare_parts_packages(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/spare-parts-packages",
            headers=headers,
            params=params,
        )

    def get_spare_parts_package(self, pkg_id, headers):
        return self._request(
            "GET", f"/robotics/spare-parts-packages/{pkg_id}", headers=headers
        )

    def order_spare_parts_package(self, pkg_id, headers):
        return self._request(
            "POST", f"/robotics/spare-parts-packages/{pkg_id}/order", {}, headers
        )

    def deliver_spare_parts_package(self, pkg_id, headers):
        return self._request(
            "POST", f"/robotics/spare-parts-packages/{pkg_id}/deliver", {}, headers
        )

    # ------------------------------------------------------------------
    # Maintenance plans (PRD §3.7)
    # ------------------------------------------------------------------
    def create_maintenance_plan(self, project_id, payload, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/maintenance-plans", payload, headers
        )

    def list_maintenance_plans(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/maintenance-plans",
            headers=headers,
            params=params,
        )

    def get_maintenance_plan(self, mp_id, headers):
        return self._request("GET", f"/robotics/maintenance-plans/{mp_id}", headers=headers)

    def activate_maintenance_plan(self, mp_id, headers):
        return self._request(
            "POST", f"/robotics/maintenance-plans/{mp_id}/activate", {}, headers
        )

    def suspend_maintenance_plan(self, mp_id, headers):
        return self._request(
            "POST", f"/robotics/maintenance-plans/{mp_id}/suspend", {}, headers
        )

    def report_meter_reading(self, mp_id, payload, headers):
        return self._request(
            "POST", f"/robotics/maintenance-plans/{mp_id}/meter-reading", payload, headers
        )

    # ------------------------------------------------------------------
    # Training sessions (PRD §3.8)
    # ------------------------------------------------------------------
    def create_training_session(self, project_id, payload, headers):
        return self._request(
            "POST", f"/robotics/cell-projects/{project_id}/training-sessions", payload, headers
        )

    def list_training_sessions(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/training-sessions",
            headers=headers,
            params=params,
        )

    def get_training_session(self, sess_id, headers):
        return self._request("GET", f"/robotics/training-sessions/{sess_id}", headers=headers)

    def start_training_session(self, sess_id, headers):
        return self._request(
            "POST", f"/robotics/training-sessions/{sess_id}/start", {}, headers
        )

    def complete_training_session(self, sess_id, payload, headers):
        return self._request(
            "POST", f"/robotics/training-sessions/{sess_id}/complete", payload, headers
        )

    def cancel_training_session(self, sess_id, headers):
        return self._request(
            "POST", f"/robotics/training-sessions/{sess_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Throughput guarantees (PRD §3.9)
    # ------------------------------------------------------------------
    def get_throughput_guarantee(self, guar_id, headers):
        return self._request(
            "GET", f"/robotics/throughput-guarantees/{guar_id}", headers=headers
        )

    def get_project_throughput_guarantee(self, project_id, headers):
        return self._request(
            "GET", f"/robotics/cell-projects/{project_id}/throughput-guarantee", headers=headers
        )

    def close_throughput_guarantee(self, guar_id, payload, headers):
        return self._request(
            "POST", f"/robotics/throughput-guarantees/{guar_id}/close", payload, headers
        )

    def waive_throughput_guarantee(self, guar_id, payload, headers):
        return self._request(
            "POST", f"/robotics/throughput-guarantees/{guar_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------
    # Retention ledger (PRD §2.8, §3.9)
    # ------------------------------------------------------------------
    def list_retention_ledger_entries(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/robotics/cell-projects/{project_id}/retention-ledger-entries",
            headers=headers,
            params=params,
        )

    def post_retention_ledger_entry(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/robotics/cell-projects/{project_id}/retention-ledger-entries",
            payload,
            headers,
        )


api_client = ApiClient()
