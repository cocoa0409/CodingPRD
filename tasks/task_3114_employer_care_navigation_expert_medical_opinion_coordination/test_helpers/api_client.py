"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/care/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/care/employers/{employer_id}", headers=headers)

    def list_employer_members(self, employer_id, headers, params=None):
        return self._request("GET", f"/care/employers/{employer_id}/members",
                             headers=headers, params=params)

    def get_utilization_report(self, employer_id, headers):
        return self._request("GET", f"/care/employers/{employer_id}/utilization-report",
                             headers=headers)

    # --- Member ---
    def create_member(self, employer_id, payload, headers):
        return self._request("POST", f"/care/employers/{employer_id}/members",
                             payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/care/members/{member_id}", headers=headers)

    def list_dependents(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/dependents",
                             headers=headers, params=params)

    def deactivate_member(self, member_id, headers):
        return self._request("POST", f"/care/members/{member_id}/deactivate",
                             {}, headers)

    def reactivate_member(self, member_id, headers):
        return self._request("POST", f"/care/members/{member_id}/reactivate",
                             {}, headers)

    # --- CoverageWindow ---
    def create_coverage_window(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/coverage-windows",
                             payload, headers)

    def list_coverage_windows(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/coverage-windows",
                             headers=headers, params=params)

    def terminate_coverage_window(self, window_id, payload, headers):
        return self._request("POST", f"/care/coverage-windows/{window_id}/terminate",
                             payload, headers)

    # --- Provider / QualitySnapshot ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/care/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/care/providers/{provider_id}", headers=headers)

    def create_quality_snapshot(self, provider_id, payload, headers):
        return self._request("POST", f"/care/providers/{provider_id}/quality-snapshots",
                             payload, headers)

    def list_quality_snapshots(self, provider_id, headers, params=None):
        return self._request("GET", f"/care/providers/{provider_id}/quality-snapshots",
                             headers=headers, params=params)

    def list_provider_matches(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/provider-matches",
                             headers=headers, params=params)

    # --- ConsentGrant ---
    def create_consent(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/consents",
                             payload, headers)

    def list_consents(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/consents",
                             headers=headers, params=params)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/care/consents/{consent_id}/revoke",
                             {}, headers)

    # --- NavigationCase ---
    def create_navigation_case(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/navigation-cases",
                             payload, headers)

    def get_navigation_case(self, case_id, headers):
        return self._request("GET", f"/care/navigation-cases/{case_id}",
                             headers=headers)

    def list_member_navigation_cases(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/navigation-cases",
                             headers=headers, params=params)

    def start_navigation_case(self, case_id, headers):
        return self._request("POST", f"/care/navigation-cases/{case_id}/start",
                             {}, headers)

    def escalate_navigation_case(self, case_id, headers):
        return self._request("POST", f"/care/navigation-cases/{case_id}/escalate",
                             {}, headers)

    def resolve_navigation_case(self, case_id, headers):
        return self._request("POST", f"/care/navigation-cases/{case_id}/resolve",
                             {}, headers)

    def close_navigation_case(self, case_id, headers):
        return self._request("POST", f"/care/navigation-cases/{case_id}/close",
                             {}, headers)

    def list_navigation_case_appointments(self, case_id, headers, params=None):
        return self._request("GET", f"/care/navigation-cases/{case_id}/appointments",
                             headers=headers, params=params)

    def list_navigation_case_expert_opinions(self, case_id, headers, params=None):
        return self._request("GET", f"/care/navigation-cases/{case_id}/expert-opinions",
                             headers=headers, params=params)

    # --- Appointment ---
    def create_appointment(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/appointments",
                             payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/care/appointments/{appointment_id}",
                             headers=headers)

    def list_member_appointments(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/appointments",
                             headers=headers, params=params)

    def list_provider_appointments(self, provider_id, headers, params=None):
        return self._request("GET", f"/care/providers/{provider_id}/appointments",
                             headers=headers, params=params)

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/care/appointments/{appointment_id}/reschedule",
                             payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/care/appointments/{appointment_id}/cancel",
                             {}, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/care/appointments/{appointment_id}/complete",
                             {}, headers)

    def mark_no_show_appointment(self, appointment_id, headers):
        return self._request("POST",
                             f"/care/appointments/{appointment_id}/mark-no-show",
                             {}, headers)

    # --- RecordRequest ---
    def create_record_request(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/record-requests",
                             payload, headers)

    def get_record_request(self, request_id, headers):
        return self._request("GET", f"/care/record-requests/{request_id}",
                             headers=headers)

    def list_record_requests(self, headers, params=None):
        return self._request("GET", "/care/record-requests",
                             headers=headers, params=params)

    def list_member_record_requests(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/record-requests",
                             headers=headers, params=params)

    def receive_record_request(self, request_id, payload, headers):
        return self._request("POST", f"/care/record-requests/{request_id}/receive",
                             payload, headers)

    def fail_record_request(self, request_id, headers):
        return self._request("POST", f"/care/record-requests/{request_id}/fail",
                             {}, headers)

    def retry_record_request(self, request_id, headers):
        return self._request("POST", f"/care/record-requests/{request_id}/retry",
                             {}, headers)

    def cancel_record_request(self, request_id, headers):
        return self._request("POST", f"/care/record-requests/{request_id}/cancel",
                             {}, headers)

    # --- ExpertOpinionCase ---
    def create_expert_opinion(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/expert-opinions",
                             payload, headers)

    def get_expert_opinion(self, opinion_id, headers):
        return self._request("GET", f"/care/expert-opinions/{opinion_id}",
                             headers=headers)

    def list_member_expert_opinions(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/expert-opinions",
                             headers=headers, params=params)

    def attach_records(self, opinion_id, payload, headers):
        return self._request("POST", f"/care/expert-opinions/{opinion_id}/attach-records",
                             payload, headers)

    def list_opinion_record_items(self, opinion_id, headers, params=None):
        return self._request("GET", f"/care/expert-opinions/{opinion_id}/record-items",
                             headers=headers, params=params)

    def list_record_request_opinion_items(self, request_id, headers, params=None):
        return self._request("GET", f"/care/record-requests/{request_id}/opinion-items",
                             headers=headers, params=params)

    def compile_expert_opinion(self, opinion_id, headers):
        return self._request("POST", f"/care/expert-opinions/{opinion_id}/compile",
                             {}, headers)

    def submit_for_review(self, opinion_id, headers):
        return self._request("POST",
                             f"/care/expert-opinions/{opinion_id}/submit-for-review",
                             {}, headers)

    def claim_review(self, opinion_id, headers):
        return self._request("POST", f"/care/expert-opinions/{opinion_id}/claim-review",
                             {}, headers)

    def request_changes(self, opinion_id, headers):
        return self._request("POST",
                             f"/care/expert-opinions/{opinion_id}/request-changes",
                             {}, headers)

    def submit_recommendation(self, opinion_id, payload, headers):
        return self._request("POST",
                             f"/care/expert-opinions/{opinion_id}/submit-recommendation",
                             payload, headers)

    def deliver_expert_opinion(self, opinion_id, headers):
        return self._request("POST", f"/care/expert-opinions/{opinion_id}/deliver",
                             {}, headers)

    def withdraw_expert_opinion(self, opinion_id, headers):
        return self._request("POST", f"/care/expert-opinions/{opinion_id}/withdraw",
                             {}, headers)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/care/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/care/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/care/claims", headers=headers, params=params)

    def list_member_claims(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/claims",
                             headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/care/claims/{claim_id}/adjudicate",
                             {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/care/claims/{claim_id}/void", {}, headers)

    # --- BillingCase ---
    def create_billing_case(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/billing-cases",
                             payload, headers)

    def get_billing_case(self, case_id, headers):
        return self._request("GET", f"/care/billing-cases/{case_id}", headers=headers)

    def list_member_billing_cases(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/billing-cases",
                             headers=headers, params=params)

    def list_claim_billing_cases(self, claim_id, headers, params=None):
        return self._request("GET", f"/care/claims/{claim_id}/billing-cases",
                             headers=headers, params=params)

    def identify_errors(self, case_id, headers):
        return self._request("POST", f"/care/billing-cases/{case_id}/identify-errors",
                             {}, headers)

    def propose_settlement(self, case_id, payload, headers):
        return self._request("POST",
                             f"/care/billing-cases/{case_id}/propose-settlement",
                             payload, headers)

    def accept_settlement(self, case_id, headers):
        return self._request("POST",
                             f"/care/billing-cases/{case_id}/accept-settlement",
                             {}, headers)

    def reject_settlement(self, case_id, headers):
        return self._request("POST",
                             f"/care/billing-cases/{case_id}/reject-settlement",
                             {}, headers)

    def abandon_billing_case(self, case_id, headers):
        return self._request("POST", f"/care/billing-cases/{case_id}/abandon",
                             {}, headers)

    def close_billing_case(self, case_id, headers):
        return self._request("POST", f"/care/billing-cases/{case_id}/close",
                             {}, headers)

    # --- PlanAuthorization ---
    def create_authorization(self, member_id, payload, headers):
        return self._request("POST", f"/care/members/{member_id}/authorizations",
                             payload, headers)

    def get_authorization(self, auth_id, headers):
        return self._request("GET", f"/care/authorizations/{auth_id}", headers=headers)

    def list_member_authorizations(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/authorizations",
                             headers=headers, params=params)

    def approve_authorization(self, auth_id, headers):
        return self._request("POST", f"/care/authorizations/{auth_id}/approve",
                             {}, headers)

    def deny_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"/care/authorizations/{auth_id}/deny",
                             payload, headers)

    def appeal_authorization(self, auth_id, headers):
        return self._request("POST", f"/care/authorizations/{auth_id}/appeal",
                             {}, headers)

    # --- computed reads ---
    def get_cost_share_estimate(self, member_id, headers, params=None):
        return self._request("GET", f"/care/members/{member_id}/cost-share-estimate",
                             headers=headers, params=params)


api_client = ApiClient()
