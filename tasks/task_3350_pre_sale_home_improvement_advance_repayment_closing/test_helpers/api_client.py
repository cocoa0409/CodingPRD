"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Agent ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/concierge/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/concierge/agents/{agent_id}", headers=headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/concierge/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/concierge/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/concierge/vendors", headers=headers, params=params)

    # --- VendorCapacityWindow ---
    def create_capacity_window(self, vendor_id, payload, headers):
        return self._request(
            "POST", f"/concierge/vendors/{vendor_id}/capacity-windows", payload, headers
        )

    def list_capacity_windows(self, vendor_id, headers):
        return self._request(
            "GET", f"/concierge/vendors/{vendor_id}/capacity-windows", headers=headers
        )

    def list_vendor_engagements(self, vendor_id, headers):
        return self._request(
            "GET", f"/concierge/vendors/{vendor_id}/engagements", headers=headers
        )

    # --- ConciergeCase ---
    def create_case(self, payload, headers):
        return self._request("POST", "/concierge/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/concierge/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/concierge/cases", headers=headers, params=params)

    def approve_eligibility(self, case_id, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/eligibility/approve", headers=headers
        )

    def reject_eligibility(self, case_id, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/eligibility/reject", headers=headers
        )

    def approve_plan(self, case_id, payload, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/plan/approve", payload, headers
        )

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/concierge/cases/{case_id}/cancel", headers=headers)

    # --- ImprovementProject ---
    def create_project(self, case_id, payload, headers):
        return self._request("POST", f"/concierge/cases/{case_id}/projects", payload, headers)

    def get_project(self, case_id, project_id, headers):
        return self._request(
            "GET", f"/concierge/cases/{case_id}/projects/{project_id}", headers=headers
        )

    def list_projects(self, case_id, headers):
        return self._request("GET", f"/concierge/cases/{case_id}/projects", headers=headers)

    def propose_project(self, case_id, project_id, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/projects/{project_id}/propose", headers=headers
        )

    def approve_project(self, case_id, project_id, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/projects/{project_id}/approve", headers=headers
        )

    def verify_project(self, case_id, project_id, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/projects/{project_id}/verify", headers=headers
        )

    def cancel_project(self, case_id, project_id, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/projects/{project_id}/cancel", headers=headers
        )

    # --- VendorEngagement ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/concierge/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/concierge/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/concierge/engagements", headers=headers, params=params)

    def start_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/concierge/engagements/{engagement_id}/start", headers=headers
        )

    def complete_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/concierge/engagements/{engagement_id}/complete", headers=headers
        )

    def cancel_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/concierge/engagements/{engagement_id}/cancel", headers=headers
        )

    def list_engagement_disputes(self, engagement_id, headers):
        return self._request(
            "GET", f"/concierge/engagements/{engagement_id}/disputes", headers=headers
        )

    # --- Disbursement ---
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/concierge/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/concierge/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/concierge/disbursements", headers=headers, params=params)

    def approve_disbursement(self, disbursement_id, payload, headers):
        return self._request(
            "POST", f"/concierge/disbursements/{disbursement_id}/approve", payload, headers
        )

    def release_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/concierge/disbursements/{disbursement_id}/release", headers=headers
        )

    def void_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/concierge/disbursements/{disbursement_id}/void", headers=headers
        )

    def list_case_disbursements(self, case_id, headers):
        return self._request(
            "GET", f"/concierge/cases/{case_id}/disbursements", headers=headers
        )

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/concierge/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/concierge/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/concierge/change-orders", headers=headers, params=params)

    def approve_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/concierge/change-orders/{change_order_id}/approve", headers=headers
        )

    def reject_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/concierge/change-orders/{change_order_id}/reject", headers=headers
        )

    def list_project_change_orders(self, project_id, headers):
        return self._request(
            "GET", f"/concierge/projects/{project_id}/change-orders", headers=headers
        )

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/concierge/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/concierge/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/concierge/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/concierge/disputes/{dispute_id}/review", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/concierge/disputes/{dispute_id}/resolve", payload, headers
        )

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/concierge/disputes/{dispute_id}/withdraw", headers=headers)

    def list_case_disputes(self, case_id, headers):
        return self._request("GET", f"/concierge/cases/{case_id}/disputes", headers=headers)

    def list_project_disputes(self, project_id, headers):
        return self._request("GET", f"/concierge/projects/{project_id}/disputes", headers=headers)

    # --- ListingEvent ---
    def create_listing_event(self, case_id, payload, headers):
        return self._request(
            "POST", f"/concierge/cases/{case_id}/listing-events", payload, headers
        )

    def list_listing_events(self, case_id, headers):
        return self._request(
            "GET", f"/concierge/cases/{case_id}/listing-events", headers=headers
        )

    # --- ClosingStatement ---
    def get_closing_statement(self, case_id, headers):
        return self._request(
            "GET", f"/concierge/cases/{case_id}/closing-statement", headers=headers
        )

    def finalize_closing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/concierge/closing-statements/{statement_id}/finalize", headers=headers
        )

    def pay_closing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/concierge/closing-statements/{statement_id}/pay", headers=headers
        )

    def waive_closing_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/concierge/closing-statements/{statement_id}/waive", headers=headers
        )

    # --- Project reverse-reachability ---
    def list_project_engagements(self, project_id, headers):
        return self._request(
            "GET", f"/concierge/projects/{project_id}/engagements", headers=headers
        )


api_client = ApiClient()
