"""API client: one method per endpoint defined in PRD §4."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- tier configs ----
    def create_tier(self, payload, headers):
        return self._request("POST", "/tiers", payload, headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/tiers", headers=headers, params=params)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/tiers/{tier_id}", headers=headers)

    # ---- orgs ----
    def create_org(self, payload, headers):
        return self._request("POST", "/orgs", payload, headers)

    def get_org(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}", headers=headers)

    def get_org_ledger(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/ledger", headers=headers)

    def get_tier_assessment(self, org_id, headers):
        return self._request("GET", f"/orgs/{org_id}/tier-assessment", headers=headers)

    # ---- revenue declarations ----
    def create_revenue_declaration(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/revenue-declarations", payload, headers)

    def list_revenue_declarations(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/revenue-declarations", headers=headers, params=params)

    # ---- seat subscriptions ----
    def create_seat_subscription(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/seat-subscriptions", payload, headers)

    def list_seat_subscriptions(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/seat-subscriptions", headers=headers, params=params)

    def assign_seat(self, sub_id, payload, headers):
        return self._request("POST", f"/seat-subscriptions/{sub_id}/assign", payload, headers)

    def release_seat(self, sub_id, headers):
        return self._request("POST", f"/seat-subscriptions/{sub_id}/release", {}, headers)

    # ---- projects ----
    def create_project(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/projects", payload, headers)

    def list_org_projects(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/projects", headers=headers, params=params)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def ship_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/ship", {}, headers)

    # ---- editor versions ----
    def create_editor_version(self, payload, headers):
        return self._request("POST", "/editor-versions", payload, headers)

    def list_editor_versions(self, headers, params=None):
        return self._request("GET", "/editor-versions", headers=headers, params=params)

    def get_editor_version(self, version_id, headers):
        return self._request("GET", f"/editor-versions/{version_id}", headers=headers)

    def transition_editor_version(self, version_id, payload, headers):
        return self._request("POST", f"/editor-versions/{version_id}/transition", payload, headers)

    # ---- install reports ----
    def create_install_report(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/install-reports", payload, headers)

    def list_project_install_reports(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/install-reports", headers=headers, params=params)

    def get_install_report(self, report_id, headers):
        return self._request("GET", f"/install-reports/{report_id}", headers=headers)

    def list_install_reports(self, headers, params=None):
        return self._request("GET", "/install-reports", headers=headers, params=params)

    def submit_install_report(self, report_id, headers):
        return self._request("POST", f"/install-reports/{report_id}/submit", {}, headers)

    def review_install_report(self, report_id, payload, headers):
        return self._request("POST", f"/install-reports/{report_id}/review", payload, headers)

    def revise_install_report(self, report_id, payload, headers):
        return self._request("POST", f"/install-reports/{report_id}/revise", payload, headers)

    # ---- invoices ----
    def list_project_invoices(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/invoices", headers=headers, params=params)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def waive_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/waive", payload, headers)

    # ---- policy changes & grandfathering ----
    def create_policy_change(self, payload, headers):
        return self._request("POST", "/policy-changes", payload, headers)

    def get_policy_change(self, policy_id, headers):
        return self._request("GET", f"/policy-changes/{policy_id}", headers=headers)

    def activate_policy_change(self, policy_id, headers):
        return self._request("POST", f"/policy-changes/{policy_id}/activate", {}, headers)

    def rescind_policy_change(self, policy_id, headers):
        return self._request("POST", f"/policy-changes/{policy_id}/rescind", {}, headers)

    def list_grandfather_commitments(self, headers, params=None):
        return self._request("GET", "/grandfather-commitments", headers=headers, params=params)

    def get_grandfather_commitment(self, commitment_id, headers):
        return self._request("GET", f"/grandfather-commitments/{commitment_id}", headers=headers)

    def attest_grandfather_commitment(self, commitment_id, headers):
        return self._request("POST", f"/grandfather-commitments/{commitment_id}/attest", {}, headers)

    # ---- asset marketplace ----
    def create_asset_listing(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/asset-listings", payload, headers)

    def list_asset_listings(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/asset-listings", headers=headers, params=params)

    def get_asset_listing(self, listing_id, headers):
        return self._request("GET", f"/asset-listings/{listing_id}", headers=headers)

    def submit_listing_review(self, listing_id, headers):
        return self._request("POST", f"/asset-listings/{listing_id}/submit-review", {}, headers)

    def review_asset_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/asset-listings/{listing_id}/review", payload, headers)

    def revise_asset_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/asset-listings/{listing_id}/revise", payload, headers)

    def delist_asset_listing(self, listing_id, headers):
        return self._request("POST", f"/asset-listings/{listing_id}/delist", {}, headers)

    def purchase_asset_listing(self, listing_id, headers):
        return self._request("POST", f"/asset-listings/{listing_id}/purchase", {}, headers)

    def list_asset_purchases(self, headers, params=None):
        return self._request("GET", "/asset-purchases", headers=headers, params=params)

    def get_asset_purchase(self, purchase_id, headers):
        return self._request("GET", f"/asset-purchases/{purchase_id}", headers=headers)

    def refund_asset_purchase(self, purchase_id, headers):
        return self._request("POST", f"/asset-purchases/{purchase_id}/refund", {}, headers)

    # ---- export agreements & builds ----
    def create_export_agreement(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/export-agreements", payload, headers)

    def list_export_agreements(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/export-agreements", headers=headers, params=params)

    def get_export_agreement(self, agreement_id, headers):
        return self._request("GET", f"/export-agreements/{agreement_id}", headers=headers)

    def activate_export_agreement(self, agreement_id, headers):
        return self._request("POST", f"/export-agreements/{agreement_id}/activate", {}, headers)

    def revoke_export_agreement(self, agreement_id, headers):
        return self._request("POST", f"/export-agreements/{agreement_id}/revoke", {}, headers)

    def create_export_build(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/export-builds", payload, headers)

    def list_project_export_builds(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/export-builds", headers=headers, params=params)

    def list_export_builds(self, headers, params=None):
        return self._request("GET", "/export-builds", headers=headers, params=params)

    def get_export_build(self, build_id, headers):
        return self._request("GET", f"/export-builds/{build_id}", headers=headers)

    # ---- audit cases ----
    def create_audit_case(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/audit-cases", payload, headers)

    def list_audit_cases(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/audit-cases", headers=headers, params=params)

    def request_audit_evidence(self, case_id, headers):
        return self._request("POST", f"/audit-cases/{case_id}/request-evidence", {}, headers)

    def resolve_audit_case(self, case_id, payload, headers):
        return self._request("POST", f"/audit-cases/{case_id}/resolve", payload, headers)

    def appeal_audit_case(self, case_id, headers):
        return self._request("POST", f"/audit-cases/{case_id}/appeal", {}, headers)

    # ---- migration assessments ----
    def create_migration_assessment(self, org_id, payload, headers):
        return self._request("POST", f"/orgs/{org_id}/migration-assessments", payload, headers)

    def list_migration_assessments(self, org_id, headers, params=None):
        return self._request("GET", f"/orgs/{org_id}/migration-assessments", headers=headers, params=params)

    def advance_migration_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/migration-assessments/{assessment_id}/advance", payload, headers)


api_client = ApiClient()
