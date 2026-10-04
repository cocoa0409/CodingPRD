"""One method per endpoint of the Worksite Indemnity API.

All paths are mounted at the service root (no path prefix). Methods return the raw
response so a test can assert on the status code as well as the body.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import Filters, Headers, JsonObject, ResourceId

BASE = ""


class ApiClient(GenericApiClient):
    """Typed wrapper over the worksite indemnity service's HTTP surface."""

    # ------------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601: str, headers: Headers):
        return self._request(
            "POST", BASE + "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------ employer groups
    def create_employer_group(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/employer-groups", payload, headers)

    def get_employer_group(self, group_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/employer-groups/" + str(group_id), None, headers
        )

    def list_employer_groups(self, headers: Headers, filters: Filters = None):
        return self._request("GET", BASE + "/employer-groups", None, headers, params=filters)

    def activate_employer_group(self, group_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/employer-groups/" + str(group_id) + "/activate", {}, headers
        )

    def suspend_employer_group(self, group_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/employer-groups/" + str(group_id) + "/suspend", {}, headers
        )

    def terminate_employer_group(self, group_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/employer-groups/" + str(group_id) + "/terminate", {}, headers
        )

    def list_group_employees(self, group_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/employer-groups/" + str(group_id) + "/employees",
            None, headers, params=filters,
        )

    def list_group_campaigns(self, group_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/employer-groups/" + str(group_id) + "/enrollment-campaigns",
            None, headers, params=filters,
        )

    def list_group_payroll_cycles(self, group_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/employer-groups/" + str(group_id) + "/payroll-cycles",
            None, headers, params=filters,
        )

    # --------------------------------------------------------- benefit counselors
    def create_benefit_counselor(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/benefit-counselors", payload, headers)

    def get_benefit_counselor(self, counselor_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/benefit-counselors/" + str(counselor_id), None, headers
        )

    def suspend_benefit_counselor(self, counselor_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/benefit-counselors/" + str(counselor_id) + "/suspend", {}, headers
        )

    def activate_benefit_counselor(self, counselor_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/benefit-counselors/" + str(counselor_id) + "/activate", {}, headers
        )

    def terminate_benefit_counselor(self, counselor_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/benefit-counselors/" + str(counselor_id) + "/terminate", {}, headers
        )

    def list_counselor_campaigns(self, counselor_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/benefit-counselors/" + str(counselor_id) + "/enrollment-campaigns",
            None, headers, params=filters,
        )

    # -------------------------------------------------------- enrollment campaigns
    def create_enrollment_campaign(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/enrollment-campaigns", payload, headers)

    def get_enrollment_campaign(self, campaign_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/enrollment-campaigns/" + str(campaign_id), None, headers
        )

    def list_enrollment_campaigns(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/enrollment-campaigns", None, headers, params=filters
        )

    def open_enrollment_campaign(self, campaign_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/enrollment-campaigns/" + str(campaign_id) + "/open", {}, headers
        )

    def lock_enrollment_campaign(self, campaign_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/enrollment-campaigns/" + str(campaign_id) + "/lock", {}, headers
        )

    def close_enrollment_campaign(self, campaign_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/enrollment-campaigns/" + str(campaign_id) + "/close",
            payload, headers,
        )

    def reopen_enrollment_campaign(self, campaign_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/enrollment-campaigns/" + str(campaign_id) + "/reopen",
            payload, headers,
        )

    def list_campaign_policies(self, campaign_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/enrollment-campaigns/" + str(campaign_id) + "/policies",
            None, headers, params=filters,
        )

    # -------------------------------------------------------------- policy series
    def create_policy_series(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/policy-series", payload, headers)

    def get_policy_series(self, series_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/policy-series/" + str(series_id), None, headers
        )

    def list_series_schedules(self, series_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/policy-series/" + str(series_id) + "/benefit-schedules",
            None, headers, params=filters,
        )

    def activate_policy_series(self, series_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/policy-series/" + str(series_id) + "/activate", {}, headers
        )

    def retire_policy_series(self, series_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/policy-series/" + str(series_id) + "/retire", {}, headers
        )

    def list_series_policies(self, series_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/policy-series/" + str(series_id) + "/policies",
            None, headers, params=filters,
        )

    # ---------------------------------------------------------- benefit schedules
    def create_benefit_schedule(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/benefit-schedules", payload, headers)

    def get_benefit_schedule(self, schedule_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/benefit-schedules/" + str(schedule_id), None, headers
        )

    def publish_benefit_schedule(self, schedule_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/benefit-schedules/" + str(schedule_id) + "/publish",
            payload, headers,
        )

    # ------------------------------------------------------------------ employees
    def create_employee(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/employees", payload, headers)

    def get_employee(self, employee_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/employees/" + str(employee_id), None, headers)

    def terminate_employee(self, employee_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/employees/" + str(employee_id) + "/terminate", {}, headers
        )

    def reinstate_employee(self, employee_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/employees/" + str(employee_id) + "/reinstate", {}, headers
        )

    def list_employee_policies(self, employee_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/employees/" + str(employee_id) + "/policies",
            None, headers, params=filters,
        )

    # ------------------------------------------------------------------- policies
    def create_policy(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/policies", payload, headers)

    def get_policy(self, policy_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/policies/" + str(policy_id), None, headers)

    def list_policies(self, headers: Headers, filters: Filters = None):
        return self._request("GET", BASE + "/policies", None, headers, params=filters)

    def issue_policy(self, policy_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/policies/" + str(policy_id) + "/issue", {}, headers
        )

    def activate_policy(self, policy_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/policies/" + str(policy_id) + "/activate", {}, headers
        )

    def lapse_policy(self, policy_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/policies/" + str(policy_id) + "/lapse", {}, headers
        )

    def reinstate_policy(self, policy_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/policies/" + str(policy_id) + "/reinstate", {}, headers
        )

    def port_policy(self, policy_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/policies/" + str(policy_id) + "/port", payload, headers
        )

    def cancel_policy(self, policy_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/policies/" + str(policy_id) + "/cancel", {}, headers
        )

    # --------------------------------------------------------------------- claims
    def create_claim(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/claims", payload, headers)

    def get_claim(self, claim_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/claims/" + str(claim_id), None, headers)

    def list_claims(self, headers: Headers, filters: Filters = None):
        return self._request("GET", BASE + "/claims", None, headers, params=filters)

    def review_claim(self, claim_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/claims/" + str(claim_id) + "/review", {}, headers
        )

    def adjudicate_claim(self, claim_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/claims/" + str(claim_id) + "/adjudicate", payload, headers
        )

    def pay_claim(self, claim_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/claims/" + str(claim_id) + "/pay", {}, headers
        )

    def appeal_claim(self, claim_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/claims/" + str(claim_id) + "/appeal", {}, headers
        )

    def void_claim(self, claim_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/claims/" + str(claim_id) + "/void", {}, headers
        )

    def list_claim_documents(self, claim_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/claims/" + str(claim_id) + "/documents",
            None, headers, params=filters,
        )

    # ---------------------------------------------------------- claim documents
    def create_claim_document(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/claim-documents", payload, headers)

    def get_claim_document(self, document_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/claim-documents/" + str(document_id), None, headers
        )

    def accept_claim_document(self, document_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/claim-documents/" + str(document_id) + "/accept", {}, headers
        )

    def reject_claim_document(self, document_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/claim-documents/" + str(document_id) + "/reject", {}, headers
        )

    # ----------------------------------------------------------- wellness benefits
    def create_wellness_benefit(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/wellness-benefits", payload, headers)

    def get_wellness_benefit(self, wellness_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/wellness-benefits/" + str(wellness_id), None, headers
        )

    def list_wellness_benefits(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/wellness-benefits", None, headers, params=filters
        )

    def approve_wellness_benefit(self, wellness_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/wellness-benefits/" + str(wellness_id) + "/approve", {}, headers
        )

    def deny_wellness_benefit(self, wellness_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/wellness-benefits/" + str(wellness_id) + "/deny", {}, headers
        )

    def pay_wellness_benefit(self, wellness_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/wellness-benefits/" + str(wellness_id) + "/pay", {}, headers
        )

    # ------------------------------------------- payroll cycles and deduction lines
    def create_payroll_cycle(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/payroll-cycles", payload, headers)

    def get_payroll_cycle(self, cycle_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/payroll-cycles/" + str(cycle_id), None, headers
        )

    def finalize_payroll_cycle(self, cycle_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/payroll-cycles/" + str(cycle_id) + "/finalize", {}, headers
        )

    def reconcile_payroll_cycle(self, cycle_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/payroll-cycles/" + str(cycle_id) + "/reconcile", {}, headers
        )

    def close_payroll_cycle(self, cycle_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/payroll-cycles/" + str(cycle_id) + "/close", {}, headers
        )

    def list_cycle_deduction_lines(self, cycle_id: ResourceId, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/payroll-cycles/" + str(cycle_id) + "/deduction-lines",
            None, headers, params=filters,
        )

    def list_deduction_lines(self, headers: Headers, filters: Filters = None):
        return self._request("GET", BASE + "/deduction-lines", None, headers, params=filters)

    def get_deduction_line(self, line_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/deduction-lines/" + str(line_id), None, headers
        )

    def reverse_deduction_line(self, line_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/deduction-lines/" + str(line_id) + "/reverse", {}, headers
        )


api_client = ApiClient()
