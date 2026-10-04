"""API client: one method per endpoint defined in the PRD (mounted under /licensing)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/licensing/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- organizations ---
    def create_organization(self, payload, headers):
        return self._request("POST", "/licensing/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/licensing/organizations/{org_id}", headers=headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", "/licensing/organizations", headers=headers, params=params)

    def update_organization(self, org_id, payload, headers):
        return self._request("PATCH", f"/licensing/organizations/{org_id}", payload, headers)

    # --- agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/licensing/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/licensing/agreements/{agreement_id}", headers=headers)

    def list_agreements_of_organization(self, org_id, headers, params=None):
        return self._request("GET", f"/licensing/organizations/{org_id}/agreements", headers=headers, params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/activate", {}, headers)

    def open_renewal_review(self, agreement_id, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/renewal-review", {}, headers)

    def renew_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/renew", payload, headers)

    def decline_renewal(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/decline-renewal", payload, headers)

    def expire_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/expire", {}, headers)

    # --- anniversaries ---
    def register_anniversary(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/anniversaries", payload, headers)

    def list_anniversaries(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/anniversaries", headers=headers, params=params)

    def get_anniversary(self, anniversary_id, headers):
        return self._request("GET", f"/licensing/anniversaries/{anniversary_id}", headers=headers)

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/licensing/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/licensing/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/licensing/products", headers=headers, params=params)

    # --- entitlements ---
    def create_entitlement(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/entitlements", payload, headers)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/licensing/entitlements/{entitlement_id}", headers=headers)

    def list_entitlements_of_agreement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/entitlements", headers=headers, params=params)

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/licensing/entitlements", headers=headers, params=params)

    def adjust_entitlement(self, entitlement_id, payload, headers):
        return self._request("PATCH", f"/licensing/entitlements/{entitlement_id}", payload, headers)

    # --- step-up conversions ---
    def create_step_up(self, entitlement_id, payload, headers):
        return self._request("POST", f"/licensing/entitlements/{entitlement_id}/step-up", payload, headers)

    def get_step_up(self, conversion_id, headers):
        return self._request("GET", f"/licensing/step-up-conversions/{conversion_id}", headers=headers)

    def list_step_ups_of_entitlement(self, entitlement_id, headers, params=None):
        return self._request("GET", f"/licensing/entitlements/{entitlement_id}/step-up-conversions", headers=headers, params=params)

    def list_step_ups(self, headers, params=None):
        return self._request("GET", "/licensing/step-up-conversions", headers=headers, params=params)

    def execute_step_up(self, conversion_id, headers):
        return self._request("POST", f"/licensing/step-up-conversions/{conversion_id}/execute", {}, headers)

    def reject_step_up(self, conversion_id, headers):
        return self._request("POST", f"/licensing/step-up-conversions/{conversion_id}/reject", {}, headers)

    # --- deployments ---
    def create_deployment(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/deployments", payload, headers)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"/licensing/deployments/{deployment_id}", headers=headers)

    def list_deployments_of_agreement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/deployments", headers=headers, params=params)

    def list_deployments(self, headers, params=None):
        return self._request("GET", "/licensing/deployments", headers=headers, params=params)

    def retire_deployment(self, deployment_id, headers):
        return self._request("DELETE", f"/licensing/deployments/{deployment_id}", headers=headers)

    # --- position snapshots ---
    def create_snapshot(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/position-snapshots", payload, headers)

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/licensing/position-snapshots/{snapshot_id}", headers=headers)

    def list_snapshots_of_agreement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/position-snapshots", headers=headers, params=params)

    def list_snapshots(self, headers, params=None):
        return self._request("GET", "/licensing/position-snapshots", headers=headers, params=params)

    # --- true-up reports & lines ---
    def create_true_up_report(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/true-up-reports", payload, headers)

    def get_true_up_report(self, report_id, headers):
        return self._request("GET", f"/licensing/true-up-reports/{report_id}", headers=headers)

    def list_true_up_reports_of_agreement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/true-up-reports", headers=headers, params=params)

    def list_true_up_reports(self, headers, params=None):
        return self._request("GET", "/licensing/true-up-reports", headers=headers, params=params)

    def add_true_up_line(self, report_id, payload, headers):
        return self._request("POST", f"/licensing/true-up-reports/{report_id}/lines", payload, headers)

    def get_true_up_line(self, line_id, headers):
        return self._request("GET", f"/licensing/true-up-lines/{line_id}", headers=headers)

    def list_lines_of_report(self, report_id, headers, params=None):
        return self._request("GET", f"/licensing/true-up-reports/{report_id}/lines", headers=headers, params=params)

    def list_true_up_lines(self, headers, params=None):
        return self._request("GET", "/licensing/true-up-lines", headers=headers, params=params)

    def submit_true_up_report(self, report_id, headers):
        return self._request("POST", f"/licensing/true-up-reports/{report_id}/submit", {}, headers)

    def accept_true_up_report(self, report_id, headers):
        return self._request("POST", f"/licensing/true-up-reports/{report_id}/accept", {}, headers)

    def reject_true_up_report(self, report_id, headers):
        return self._request("POST", f"/licensing/true-up-reports/{report_id}/reject", {}, headers)

    def revise_true_up_report(self, report_id, headers):
        return self._request("POST", f"/licensing/true-up-reports/{report_id}/revise", {}, headers)

    def invoice_true_up_report(self, report_id, headers):
        return self._request("POST", f"/licensing/true-up-reports/{report_id}/invoice", {}, headers)

    def settle_true_up_report(self, report_id, headers):
        return self._request("POST", f"/licensing/true-up-reports/{report_id}/settle", {}, headers)

    # --- benefit grants & redemptions ---
    def create_benefit_grant(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/benefit-grants", payload, headers)

    def get_benefit_grant(self, grant_id, headers):
        return self._request("GET", f"/licensing/benefit-grants/{grant_id}", headers=headers)

    def list_benefit_grants_of_agreement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/benefit-grants", headers=headers, params=params)

    def redeem_benefit(self, grant_id, payload, headers):
        return self._request("POST", f"/licensing/benefit-grants/{grant_id}/redemptions", payload, headers)

    def list_redemptions_of_grant(self, grant_id, headers, params=None):
        return self._request("GET", f"/licensing/benefit-grants/{grant_id}/redemptions", headers=headers, params=params)

    # --- cloud commitments & consumption events ---
    def create_cloud_commitment(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/cloud-commitments", payload, headers)

    def get_cloud_commitment(self, commitment_id, headers):
        return self._request("GET", f"/licensing/cloud-commitments/{commitment_id}", headers=headers)

    def list_cloud_commitments_of_agreement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/cloud-commitments", headers=headers, params=params)

    def consume_commitment(self, commitment_id, payload, headers):
        return self._request("POST", f"/licensing/cloud-commitments/{commitment_id}/consumption-events", payload, headers)

    def list_consumption_events_of_commitment(self, commitment_id, headers, params=None):
        return self._request("GET", f"/licensing/cloud-commitments/{commitment_id}/consumption-events", headers=headers, params=params)

    # --- hosting authorizations ---
    def create_hosting_authorization(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/hosting-authorizations", payload, headers)

    def get_hosting_authorization(self, auth_id, headers):
        return self._request("GET", f"/licensing/hosting-authorizations/{auth_id}", headers=headers)

    def list_hosting_authorizations_of_agreement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/hosting-authorizations", headers=headers, params=params)

    def list_hosting_authorizations(self, headers, params=None):
        return self._request("GET", "/licensing/hosting-authorizations", headers=headers, params=params)

    def review_hosting_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"/licensing/hosting-authorizations/{auth_id}/review", payload, headers)

    def suspend_hosting_authorization(self, auth_id, headers):
        return self._request("POST", f"/licensing/hosting-authorizations/{auth_id}/suspend", {}, headers)

    def reinstate_hosting_authorization(self, auth_id, headers):
        return self._request("POST", f"/licensing/hosting-authorizations/{auth_id}/reinstate", {}, headers)

    def revoke_hosting_authorization(self, auth_id, headers):
        return self._request("POST", f"/licensing/hosting-authorizations/{auth_id}/revoke", {}, headers)

    # --- shortfall assessments ---
    def assess_shortfall(self, agreement_id, headers):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/shortfall-assessment", headers=headers)

    def get_shortfall_assessment(self, assessment_id, headers):
        return self._request("GET", f"/licensing/shortfall-assessments/{assessment_id}", headers=headers)

    def list_shortfall_assessments(self, headers, params=None):
        return self._request("GET", "/licensing/shortfall-assessments", headers=headers, params=params)


api_client = ApiClient()
