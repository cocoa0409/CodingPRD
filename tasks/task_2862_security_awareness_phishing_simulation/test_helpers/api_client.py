"""Typed HTTP client: one method per endpoint of the awareness program API."""

from __future__ import annotations

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/awareness"


class ApiClient(GenericApiClient):
    """One method per routing-table row; every method returns the raw response."""

    # ---------------------------------------------------------------- clock --
    def set_clock(self, to_iso8601: str, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------ employees --
    def create_employee(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/employees/{employee_id}", None, headers)

    def list_employees(self, params: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/employees", params or {}, headers)

    def change_employee_role(self, employee_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"{BASE}/employees/{employee_id}/role", payload, headers)

    def offboard_employee(self, employee_id: str, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/employees/{employee_id}/offboard", {}, headers)

    # -------------------------------------------------- access consequences --
    def apply_access_consequence(
        self, employee_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{BASE}/employees/{employee_id}/access-consequences", payload, headers
        )

    def get_access_consequence(self, consequence_id: str, headers: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/access-consequences/{consequence_id}", None, headers
        )

    def list_access_consequences(
        self, params: Optional[dict] = None, headers: Optional[dict] = None
    ):
        return self._request("GET", f"{BASE}/access-consequences", params or {}, headers)

    def lift_access_consequence(
        self, consequence_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{BASE}/access-consequences/{consequence_id}/lift", payload, headers
        )

    # ------------------------------------------------------ training modules --
    def create_module(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/training-modules", payload, headers)

    def get_module(self, module_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/training-modules/{module_id}", None, headers)

    def publish_module(self, module_id: str, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/training-modules/{module_id}/publish", {}, headers)

    def retire_module(self, module_id: str, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/training-modules/{module_id}/retire", {}, headers)

    # ------------------------------------------------ curriculum assignments --
    def create_assignment(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/curriculum-assignments", payload, headers)

    def get_assignment(self, assignment_id: str, headers: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/curriculum-assignments/{assignment_id}", None, headers
        )

    def list_assignments(self, params: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/curriculum-assignments", params or {}, headers)

    def start_assignment(self, assignment_id: str, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/curriculum-assignments/{assignment_id}/start", {}, headers
        )

    def submit_assignment(self, assignment_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/curriculum-assignments/{assignment_id}/submit", payload, headers
        )

    def retake_assignment(self, assignment_id: str, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/curriculum-assignments/{assignment_id}/retake", {}, headers
        )

    def extend_assignment(self, assignment_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/curriculum-assignments/{assignment_id}/extension", payload, headers
        )

    def void_assignment(self, assignment_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/curriculum-assignments/{assignment_id}/void", payload, headers
        )

    # ---------------------------------------------------- compliance sweeps --
    def run_compliance_sweep(self, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/compliance-sweeps", {}, headers)

    # --------------------------------------------------- escalation notices --
    def get_notice(self, notice_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/escalation-notices/{notice_id}", None, headers)

    def list_notices(self, params: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/escalation-notices", params or {}, headers)

    def acknowledge_notice(self, notice_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/escalation-notices/{notice_id}/acknowledge", payload, headers
        )

    # --------------------------------------------------- phishing templates --
    def create_template(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/phishing-templates", payload, headers)

    def get_template(self, template_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/phishing-templates/{template_id}", None, headers)

    def approve_template_for_use(self, template_id: str, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/phishing-templates/{template_id}/approve-for-use", {}, headers
        )

    def block_template(self, template_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/phishing-templates/{template_id}/block", payload, headers
        )

    # ----------------------------------------------------------- campaigns --
    def create_campaign(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/campaigns", payload, headers)

    def get_campaign(self, campaign_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/campaigns/{campaign_id}", None, headers)

    def list_campaigns(self, params: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/campaigns", params or {}, headers)

    def submit_campaign_for_review(self, campaign_id: str, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/campaigns/{campaign_id}/submit-for-review", {}, headers
        )

    def approve_campaign(self, campaign_id: str, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/campaigns/{campaign_id}/approve", {}, headers)

    def reject_campaign(self, campaign_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/campaigns/{campaign_id}/reject", payload, headers)

    def schedule_campaign(self, campaign_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/campaigns/{campaign_id}/schedule", payload, headers)

    def launch_campaign(self, campaign_id: str, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/campaigns/{campaign_id}/launch", {}, headers)

    def close_campaign(self, campaign_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/campaigns/{campaign_id}/close", payload, headers)

    def cancel_campaign(self, campaign_id: str, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/campaigns/{campaign_id}/cancel", {}, headers)

    def get_scorecard(self, campaign_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/campaigns/{campaign_id}/scorecard", None, headers)

    # ------------------------------------------------- simulation deliveries --
    def get_delivery(self, delivery_id: str, headers: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/simulation-deliveries/{delivery_id}", None, headers
        )

    def list_deliveries(self, params: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/simulation-deliveries", params or {}, headers)

    def append_interaction(self, delivery_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/simulation-deliveries/{delivery_id}/interactions", payload, headers
        )

    def list_interaction_events(self, delivery_id: str, params: Optional[dict] = None,
                                headers: Optional[dict] = None):
        return self._request(
            "GET",
            f"{BASE}/simulation-deliveries/{delivery_id}/interaction-events",
            params or {},
            headers,
        )

    # -------------------------------------------------------- interventions --
    def get_intervention(self, intervention_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/interventions/{intervention_id}", None, headers)

    def list_interventions(self, params: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/interventions", params or {}, headers)

    def assign_coaching(self, intervention_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/interventions/{intervention_id}/assign-coaching", payload, headers
        )

    def close_intervention(self, intervention_id: str, payload: dict,
                           headers: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/interventions/{intervention_id}/close", payload, headers
        )

    # ------------------------------------------------------------ incidents --
    def create_incident(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/incidents", payload, headers)

    def get_incident(self, incident_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/incidents/{incident_id}", None, headers)

    def list_incidents(self, params: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/incidents", params or {}, headers)

    # -------------------------------------------------- communication windows --
    def create_communication_window(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{BASE}/communication-windows", payload, headers)

    def list_communication_windows(self, params: Optional[dict] = None,
                                   headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/communication-windows", params or {}, headers)

    # --------------------------------------------------- effectiveness report --
    def get_effectiveness_report(self, params: dict, headers: Optional[dict] = None):
        return self._request("GET", f"{BASE}/effectiveness-report", params, headers)


api_client = ApiClient()
