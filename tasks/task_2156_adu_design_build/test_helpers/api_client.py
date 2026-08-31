"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ---------------- jurisdictions ----------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers=headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # ---------------- inspectors ----------------
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers=headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    def get_inspector_availability(self, inspector_id, slot_date, headers):
        return self._request(
            "GET", f"/inspectors/{inspector_id}/availability",
            headers=headers, params={"slot_date": slot_date},
        )

    # ---------------- properties ----------------
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers=headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---------------- adu projects ----------------
    def create_adu_project(self, payload, headers):
        return self._request("POST", "/adu-projects", payload, headers=headers)

    def get_adu_project(self, project_id, headers):
        return self._request("GET", f"/adu-projects/{project_id}", headers=headers)

    def list_adu_projects(self, headers, params=None):
        return self._request("GET", "/adu-projects", headers=headers, params=params)

    # ---------------- feasibility ----------------
    def create_feasibility_screening(self, project_id, payload, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/feasibility-screenings", payload, headers=headers)

    def list_feasibility_screenings(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/adu-projects/{project_id}/feasibility-screenings",
            headers=headers, params=params)

    def select_pathway(self, project_id, payload, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/select-pathway", payload, headers=headers)

    # ---------------- utility connections ----------------
    def create_utility_connection(self, project_id, payload, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/utility-connections", payload, headers=headers)

    def list_utility_connections(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/adu-projects/{project_id}/utility-connections", headers=headers, params=params)

    def decide_utility_connection(self, utility_connection_id, payload, headers):
        return self._request(
            "POST", f"/utility-connections/{utility_connection_id}/decide", payload, headers=headers)

    def energize_utility_connection(self, utility_connection_id, headers):
        return self._request(
            "POST", f"/utility-connections/{utility_connection_id}/energize", {}, headers=headers)

    # ---------------- permit submittals ----------------
    def create_permit_submittal(self, project_id, payload, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/permit-submittals", payload, headers=headers)

    def list_permit_submittals(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/adu-projects/{project_id}/permit-submittals", headers=headers, params=params)

    def get_permit_submittal(self, submittal_id, headers):
        return self._request("GET", f"/permit-submittals/{submittal_id}", headers=headers)

    def submit_permit_submittal(self, submittal_id, headers):
        return self._request("POST", f"/permit-submittals/{submittal_id}/submit", {}, headers=headers)

    def record_plan_check_result(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/permit-submittals/{submittal_id}/plan-check-result", payload, headers=headers)

    def resubmit_permit_submittal(self, submittal_id, headers):
        return self._request("POST", f"/permit-submittals/{submittal_id}/resubmit", {}, headers=headers)

    def list_correction_items(self, submittal_id, headers, params=None):
        return self._request(
            "GET", f"/permit-submittals/{submittal_id}/correction-items", headers=headers, params=params)

    def resolve_correction_item(self, correction_item_id, headers):
        return self._request(
            "POST", f"/correction-items/{correction_item_id}/resolve", {}, headers=headers)

    # ---------------- financing ----------------
    def create_financing_scenario(self, project_id, payload, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/financing-scenarios", payload, headers=headers)

    def list_financing_scenarios(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/adu-projects/{project_id}/financing-scenarios", headers=headers, params=params)

    def get_financing_scenario(self, scenario_id, headers):
        return self._request("GET", f"/financing-scenarios/{scenario_id}", headers=headers)

    def commit_financing_scenario(self, scenario_id, headers):
        return self._request("POST", f"/financing-scenarios/{scenario_id}/commit", {}, headers=headers)

    # ---------------- change orders ----------------
    def create_change_order(self, project_id, payload, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/change-orders", payload, headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def submit_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/submit", {}, headers=headers)

    def decide_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/decide", payload, headers=headers)

    def void_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/void", {}, headers=headers)

    # ---------------- construction phases ----------------
    def create_construction_phase(self, project_id, payload, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/construction-phases", payload, headers=headers)

    def list_construction_phases(self, headers, params=None):
        return self._request("GET", "/construction-phases", headers=headers, params=params)

    def get_construction_phase(self, phase_id, headers):
        return self._request("GET", f"/construction-phases/{phase_id}", headers=headers)

    def schedule_construction_phase(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/construction-phases/{phase_id}/schedule", payload, headers=headers)

    def start_construction_phase(self, phase_id, headers):
        return self._request("POST", f"/construction-phases/{phase_id}/start", {}, headers=headers)

    def complete_construction_phase(self, phase_id, headers):
        return self._request("POST", f"/construction-phases/{phase_id}/complete", {}, headers=headers)

    # ---------------- inspections ----------------
    def create_inspection_appointment(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/construction-phases/{phase_id}/inspection-appointments", payload, headers=headers)

    def list_inspection_appointments(self, headers, params=None):
        return self._request("GET", "/inspection-appointments", headers=headers, params=params)

    def get_inspection_appointment(self, appointment_id, headers):
        return self._request("GET", f"/inspection-appointments/{appointment_id}", headers=headers)

    def record_inspection_result(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/inspection-appointments/{appointment_id}/result", payload, headers=headers)

    def cancel_inspection_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/inspection-appointments/{appointment_id}/cancel", {}, headers=headers)

    # ---------------- occupancy certificate ----------------
    def issue_occupancy_certificate(self, project_id, headers):
        return self._request(
            "POST", f"/adu-projects/{project_id}/occupancy-certificate", {}, headers=headers)

    def list_occupancy_certificates(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/adu-projects/{project_id}/occupancy-certificates", headers=headers, params=params)

    # ---------------- raw helper for header-level tests ----------------
    def raw_get(self, path, headers, params=None):
        """Issue a GET with an arbitrary (possibly header-less) request."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
