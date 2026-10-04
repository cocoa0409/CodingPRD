"""API client: one method per route in the PRD's routing table (§4).

The shared request plumbing lives in the framework's `GenericApiClient`; this
class only names the domain's endpoints.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------- configuration
    def create_branch(self, payload, headers):
        return self._request("POST", "/api/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/api/branches/{branch_id}", headers=headers)

    def hire_technician(self, branch_id, payload, headers):
        return self._request(
            "POST", f"/api/branches/{branch_id}/technicians", payload, headers
        )

    def list_branch_technicians(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"/api/branches/{branch_id}/technicians", headers=headers, params=params
        )

    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/api/membership-plans", payload, headers)

    def create_campaign(self, payload, headers):
        return self._request("POST", "/api/campaigns", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ pricebook
    def create_pricebook_task(self, payload, headers):
        return self._request("POST", "/api/pricebook/tasks", payload, headers)

    # -------------------------------------------------------------- intake
    def create_call_record(self, payload, headers):
        return self._request("POST", "/api/call-records", payload, headers)

    def assign_coaching(self, call_id, payload, headers):
        return self._request(
            "POST", f"/api/call-records/{call_id}/coaching", payload, headers
        )

    # ------------------------------------------------------------ bookings
    def create_appointment(self, payload, headers):
        return self._request("POST", "/api/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/api/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/api/appointments/{appointment_id}", headers=headers)

    def add_line(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/lines", payload, headers
        )

    def list_lines(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/api/appointments/{appointment_id}/lines", headers=headers, params=params
        )

    def reprice_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/reprice", payload, headers
        )

    # ------------------------------------------------------------ dispatch
    def dispatch_order(self, payload, headers):
        return self._request("POST", "/api/dispatch/orders", payload, headers)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/complete", payload, headers
        )

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/cancel", payload, headers
        )

    # ------------------------------------------------------ price overrides
    def file_override_request(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/api/appointments/{appointment_id}/override-requests", payload, headers
        )

    def list_override_requests(self, appointment_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/appointments/{appointment_id}/override-requests",
            headers=headers,
            params=params,
        )

    def decide_override(self, override_id, payload, headers):
        return self._request(
            "POST", f"/api/override-requests/{override_id}/decide", payload, headers
        )

    # ------------------------------------------------------------ membership
    def sell_membership(self, payload, headers):
        return self._request("POST", "/api/membership-agreements", payload, headers)

    def list_membership_agreements(self, headers, params=None):
        return self._request(
            "GET", "/api/membership-agreements", headers=headers, params=params
        )

    def get_membership_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/membership-agreements/{agreement_id}", headers=headers
        )

    def record_payment(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/membership-agreements/{agreement_id}/payments", payload, headers
        )

    def schedule_visit(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/api/membership-agreements/{agreement_id}/membership-visits",
            payload,
            headers,
        )

    def list_visits(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/membership-agreements/{agreement_id}/membership-visits",
            headers=headers,
            params=params,
        )

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/api/membership-visits/{visit_id}/reschedule", payload, headers
        )

    def cancel_membership(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/membership-agreements/{agreement_id}/cancel", payload, headers
        )

    # ------------------------------------------------------- performance pay
    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    def get_incentive_statement(self, technician_id, params, headers):
        return self._request(
            "GET",
            f"/api/technicians/{technician_id}/incentive-statement",
            headers=headers,
            params=params,
        )

    def get_performance_review(self, technician_id, headers):
        return self._request(
            "GET", f"/api/technicians/{technician_id}/performance", headers=headers
        )

    # ------------------------------------------------------------ marketing
    def get_campaign(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/api/campaigns/{campaign_id}", headers=headers, params=params
        )

    def list_campaign_calls(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/api/campaigns/{campaign_id}/call-records", headers=headers, params=params
        )


api_client = ApiClient()