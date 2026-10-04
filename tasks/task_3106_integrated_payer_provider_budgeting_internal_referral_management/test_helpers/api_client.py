"""API client: one method per endpoint declared in the PRD."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Region ────────────────────────────────────────
    def create_region(self, payload, headers):
        return self._request("POST", "/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/regions/{region_id}", headers=headers)

    # ─── Member ────────────────────────────────────────
    def create_member(self, region_id, payload, headers):
        return self._request("POST", f"/regions/{region_id}/members", payload, headers)

    def list_region_members(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/members", headers=headers, params=params
        )

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def terminate_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/terminate", payload, headers)

    def correct_member_risk_score(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers)

    # ─── CareSite ──────────────────────────────────────
    def create_care_site(self, region_id, payload, headers):
        return self._request("POST", f"/regions/{region_id}/care-sites", payload, headers)

    def list_region_care_sites(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/care-sites", headers=headers, params=params
        )

    def list_care_sites(self, headers, params=None):
        return self._request("GET", "/care-sites", headers=headers, params=params)

    def get_care_site(self, care_site_id, headers):
        return self._request("GET", f"/care-sites/{care_site_id}", headers=headers)

    def set_staffing(self, care_site_id, payload, headers):
        return self._request("POST", f"/care-sites/{care_site_id}/staffing", payload, headers)

    # ─── Department ────────────────────────────────────
    def create_department(self, care_site_id, payload, headers):
        return self._request(
            "POST", f"/care-sites/{care_site_id}/departments", payload, headers
        )

    def list_care_site_departments(self, care_site_id, headers, params=None):
        return self._request(
            "GET", f"/care-sites/{care_site_id}/departments", headers=headers, params=params
        )

    def list_departments(self, headers, params=None):
        return self._request("GET", "/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def adjust_department(self, department_id, payload, headers):
        return self._request("PATCH", f"/departments/{department_id}", payload, headers)

    # ─── Provider ──────────────────────────────────────
    def create_provider(self, care_site_id, payload, headers):
        return self._request(
            "POST", f"/care-sites/{care_site_id}/providers", payload, headers
        )

    def list_care_site_providers(self, care_site_id, headers, params=None):
        return self._request(
            "GET", f"/care-sites/{care_site_id}/providers", headers=headers, params=params
        )

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def change_compensation_model(self, provider_id, payload, headers):
        return self._request(
            "PATCH", f"/providers/{provider_id}/compensation-model", payload, headers
        )

    def draft_compensation_plan(self, payload, headers):
        return self._request("POST", "/provider-compensation-plans", payload, headers)

    # ─── NetworkService ────────────────────────────────
    def declare_network_service(self, region_id, payload, headers):
        return self._request(
            "POST", f"/regions/{region_id}/network-services", payload, headers
        )

    def list_region_network_services(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/network-services", headers=headers, params=params
        )

    def get_network_service(self, network_service_id, headers):
        return self._request(
            "GET", f"/network-services/{network_service_id}", headers=headers
        )

    # ─── Appointment ───────────────────────────────────
    def book_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/cancel", payload, headers
        )

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/appointments/{appointment_id}/complete", payload, headers
        )

    # ─── Referral ──────────────────────────────────────
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def authorize_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/authorize", payload, headers)

    def deny_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/deny", payload, headers)

    def appeal_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/appeal", payload, headers)

    def create_referral_capacity_plan(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/capacity-plans", payload, headers
        )

    # ─── OutsideServiceClaim ───────────────────────────
    def submit_outside_service_claim(self, region_id, payload, headers):
        return self._request(
            "POST", f"/regions/{region_id}/outside-service-claims", payload, headers
        )

    def list_region_outside_service_claims(self, region_id, headers, params=None):
        return self._request(
            "GET",
            f"/regions/{region_id}/outside-service-claims",
            headers=headers,
            params=params,
        )

    def list_outside_service_claims(self, headers, params=None):
        return self._request(
            "GET", "/outside-service-claims", headers=headers, params=params
        )

    def get_outside_service_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/outside-service-claims/{claim_id}", headers=headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/outside-service-claims/{claim_id}/adjudicate", payload, headers
        )

    def pay_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/outside-service-claims/{claim_id}/pay", payload, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/outside-service-claims/{claim_id}/deny", payload, headers
        )

    def appeal_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/outside-service-claims/{claim_id}/appeal", payload, headers
        )

    def bulk_adjudicate_referral_claims(self, payload, headers):
        return self._request("POST", "/referral-claims/bulk-adjudicate", payload, headers)

    def get_referral_claim_batch(self, referral_id, headers):
        return self._request("GET", f"/referral-claims/{referral_id}", headers=headers)

    # ─── RegionalBudget ────────────────────────────────
    def create_regional_budget(self, region_id, payload, headers):
        return self._request(
            "POST", f"/regions/{region_id}/regional-budgets", payload, headers
        )

    def list_region_regional_budgets(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/regional-budgets", headers=headers, params=params
        )

    def list_regional_budgets(self, headers, params=None):
        return self._request("GET", "/regional-budgets", headers=headers, params=params)

    def get_regional_budget(self, budget_id, headers):
        return self._request("GET", f"/regional-budgets/{budget_id}", headers=headers)

    def submit_budget(self, budget_id, payload, headers):
        return self._request("POST", f"/regional-budgets/{budget_id}/submit", payload, headers)

    def approve_budget(self, budget_id, payload, headers):
        return self._request("POST", f"/regional-budgets/{budget_id}/approve", payload, headers)

    def return_budget(self, budget_id, payload, headers):
        return self._request("POST", f"/regional-budgets/{budget_id}/return", payload, headers)

    def close_budget(self, budget_id, payload, headers):
        return self._request("POST", f"/regional-budgets/{budget_id}/close", payload, headers)

    def reopen_budget(self, budget_id, payload, headers):
        return self._request("POST", f"/regional-budgets/{budget_id}/reopen", payload, headers)

    # ─── CapacityPlan ──────────────────────────────────
    def create_capacity_plan(self, region_id, payload, headers):
        return self._request(
            "POST", f"/regions/{region_id}/capacity-plans", payload, headers
        )

    def list_region_capacity_plans(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/capacity-plans", headers=headers, params=params
        )

    def list_capacity_plans(self, headers, params=None):
        return self._request("GET", "/capacity-plans", headers=headers, params=params)

    def get_capacity_plan(self, plan_id, headers):
        return self._request("GET", f"/capacity-plans/{plan_id}", headers=headers)

    def review_capacity_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/capacity-plans/{plan_id}/review", payload, headers)

    def activate_capacity_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/capacity-plans/{plan_id}/activate", payload, headers)

    def adjust_capacity_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/capacity-plans/{plan_id}/adjust", payload, headers)

    def return_capacity_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/capacity-plans/{plan_id}/return", payload, headers)

    # ─── MemberTransfer ────────────────────────────────
    def create_member_transfer(self, payload, headers):
        return self._request("POST", "/member-transfers", payload, headers)

    def list_member_transfers(self, headers, params=None):
        return self._request("GET", "/member-transfers", headers=headers, params=params)

    def get_member_transfer(self, transfer_id, headers):
        return self._request("GET", f"/member-transfers/{transfer_id}", headers=headers)

    def accept_member_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/member-transfers/{transfer_id}/accept", payload, headers
        )

    def reject_member_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/member-transfers/{transfer_id}/reject", payload, headers
        )

    def complete_member_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/member-transfers/{transfer_id}/complete", payload, headers
        )

    def cancel_member_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/member-transfers/{transfer_id}/cancel", payload, headers
        )

    # ─── QualityMetric ─────────────────────────────────
    def create_quality_metric(self, region_id, payload, headers):
        return self._request(
            "POST", f"/regions/{region_id}/quality-metrics", payload, headers
        )

    def list_region_quality_metrics(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/quality-metrics", headers=headers, params=params
        )

    def list_quality_metrics(self, headers, params=None):
        return self._request("GET", "/quality-metrics", headers=headers, params=params)

    def get_quality_metric(self, metric_id, headers):
        return self._request("GET", f"/quality-metrics/{metric_id}", headers=headers)

    def finalize_quality_metric(self, metric_id, payload, headers):
        return self._request(
            "POST", f"/quality-metrics/{metric_id}/finalize", payload, headers
        )

    def reopen_quality_metric(self, metric_id, payload, headers):
        return self._request(
            "POST", f"/quality-metrics/{metric_id}/reopen", payload, headers
        )

    # ─── ReferentialIntegration ────────────────────────
    def create_referential_integration(self, region_id, payload, headers):
        return self._request(
            "POST", f"/regions/{region_id}/referential-integrations", payload, headers
        )

    def list_region_referential_integrations(self, region_id, headers, params=None):
        return self._request(
            "GET",
            f"/regions/{region_id}/referential-integrations",
            headers=headers,
            params=params,
        )

    def get_referential_integration(self, integration_id, headers):
        return self._request(
            "GET", f"/referential-integrations/{integration_id}", headers=headers
        )

    def bind_referential_integration(self, integration_id, payload, headers):
        return self._request(
            "POST", f"/referential-integrations/{integration_id}/bind", payload, headers
        )

    def enroll_referential_integration(self, integration_id, payload, headers):
        return self._request(
            "POST", f"/referential-integrations/{integration_id}/enroll", payload, headers
        )

    def contract_referential_integration(self, integration_id, payload, headers):
        return self._request(
            "POST", f"/referential-integrations/{integration_id}/contract", payload, headers
        )

    def terminate_referential_integration(self, integration_id, payload, headers):
        return self._request(
            "POST", f"/referential-integrations/{integration_id}/terminate", payload, headers
        )

    # ─── AlertNotification ─────────────────────────────
    def list_region_alerts(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/alerts", headers=headers, params=params
        )

    def acknowledge_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/alerts/{alert_id}/acknowledge", payload, headers)

    # ─── Platform controls ─────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_outcome_targets(self, metric_id, payload, headers):
        return self._request("PATCH", f"/_outcome-targets/{metric_id}", payload, headers)

    def inject_member_risk_score(self, payload, headers):
        return self._request("POST", "/_inject/member-risk-score", payload, headers)


api_client = ApiClient()