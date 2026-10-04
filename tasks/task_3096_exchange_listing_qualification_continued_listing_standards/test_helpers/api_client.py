"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- Issuer ---
    def create_issuer(self, payload, headers):
        return self._request("POST", "/issuers", payload, headers)

    def list_issuers(self, headers, params=None):
        return self._request("GET", "/issuers", headers=headers, params=params)

    def get_issuer(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}", headers=headers)

    # --- ListingApplication ---
    def create_listing_application(self, issuer_id, payload, headers):
        return self._request("POST", f"/issuers/{issuer_id}/listing-applications",
                             payload, headers)

    def list_listing_applications(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/listing-applications",
                             headers=headers, params=params)

    def list_listing_applications_index(self, headers, params=None):
        return self._request("GET", "/listing-applications",
                             headers=headers, params=params)

    def get_listing_application_index(self, application_id, headers):
        return self._request("GET", f"/listing-applications/{application_id}",
                             headers=headers)

    def get_listing_application(self, issuer_id, application_id, headers):
        return self._request("GET",
                             f"/issuers/{issuer_id}/listing-applications/{application_id}",
                             headers=headers)

    def submit_application(self, issuer_id, application_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/listing-applications/{application_id}/submit",
                             {}, headers)

    def approve_application(self, issuer_id, application_id, expected_issuer_version, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/listing-applications/{application_id}/approve",
                             {"expected_issuer_version": expected_issuer_version}, headers)

    def reject_application(self, issuer_id, application_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/listing-applications/{application_id}/reject",
                             {}, headers)

    # --- Listing ---
    def list_listings(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/listings",
                             headers=headers, params=params)

    def list_listings_index(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_listing_index(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def get_listing(self, issuer_id, listing_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}/listings/{listing_id}",
                             headers=headers)

    def execute_delisting(self, issuer_id, listing_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/listings/{listing_id}/execute-delisting",
                             {}, headers)

    # --- MarketDataSnapshot ---
    def create_snapshot(self, issuer_id, payload, headers):
        return self._request("POST", f"/issuers/{issuer_id}/market-data-snapshots",
                             payload, headers)

    def list_snapshots(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/market-data-snapshots",
                             headers=headers, params=params)

    def get_snapshot(self, issuer_id, snapshot_id, headers):
        return self._request("GET",
                             f"/issuers/{issuer_id}/market-data-snapshots/{snapshot_id}",
                             headers=headers)

    def list_snapshots_index(self, headers, params=None):
        return self._request("GET", "/market-data-snapshots",
                             headers=headers, params=params)

    def get_snapshot_index(self, snapshot_id, headers):
        return self._request("GET", f"/market-data-snapshots/{snapshot_id}",
                             headers=headers)

    # --- Deficiency monitoring ---
    def run_deficiency_monitor(self, issuer_id, headers):
        return self._request("POST", f"/issuers/{issuer_id}/deficiency-monitor/run",
                             {}, headers)

    def list_deficiencies(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/deficiencies",
                             headers=headers, params=params)

    def list_deficiencies_index(self, headers, params=None):
        return self._request("GET", "/deficiencies", headers=headers, params=params)

    def get_deficiency_index(self, deficiency_id, headers):
        return self._request("GET", f"/deficiencies/{deficiency_id}", headers=headers)

    def list_compliance_records_for_deficiency(self, deficiency_id, headers, params=None):
        return self._request("GET",
                             f"/deficiencies/{deficiency_id}/compliance-records",
                             headers=headers, params=params)

    def list_compliance_plans_for_deficiency(self, deficiency_id, headers, params=None):
        return self._request("GET", f"/deficiencies/{deficiency_id}/compliance-plans",
                             headers=headers, params=params)

    def list_appeals_for_deficiency(self, deficiency_id, headers, params=None):
        return self._request("GET", f"/deficiencies/{deficiency_id}/appeals",
                             headers=headers, params=params)

    def get_deficiency(self, issuer_id, deficiency_id, headers):
        return self._request("GET",
                             f"/issuers/{issuer_id}/deficiencies/{deficiency_id}",
                             headers=headers)

    def staff_determine_delisting(self, issuer_id, deficiency_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/deficiencies/{deficiency_id}/staff-determine-delisting",
                             {}, headers)

    # --- ComplianceRecord ---
    def list_compliance_records(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/compliance-records",
                             headers=headers, params=params)

    def get_compliance_record(self, issuer_id, record_id, headers):
        return self._request("GET",
                             f"/issuers/{issuer_id}/compliance-records/{record_id}",
                             headers=headers)

    def list_compliance_records_index(self, headers, params=None):
        return self._request("GET", "/compliance-records", headers=headers, params=params)

    def get_compliance_record_index(self, record_id, headers):
        return self._request("GET", f"/compliance-records/{record_id}", headers=headers)

    # --- CompliancePlan ---
    def create_compliance_plan(self, issuer_id, payload, headers):
        return self._request("POST", f"/issuers/{issuer_id}/compliance-plans",
                             payload, headers)

    def list_compliance_plans(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/compliance-plans",
                             headers=headers, params=params)

    def get_compliance_plan(self, issuer_id, plan_id, headers):
        return self._request("GET",
                             f"/issuers/{issuer_id}/compliance-plans/{plan_id}",
                             headers=headers)

    def list_compliance_plans_index(self, headers, params=None):
        return self._request("GET", "/compliance-plans", headers=headers, params=params)

    def get_compliance_plan_index(self, plan_id, headers):
        return self._request("GET", f"/compliance-plans/{plan_id}", headers=headers)

    def review_compliance_plan(self, issuer_id, plan_id, payload, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/compliance-plans/{plan_id}/review",
                             payload, headers)

    # --- HearingsReview ---
    def create_hearings_review(self, payload, headers):
        return self._request("POST", "/hearings-reviews", payload, headers)

    def list_hearings_reviews(self, headers, params=None):
        return self._request("GET", "/hearings-reviews", headers=headers, params=params)

    def get_hearings_review(self, review_id, headers):
        return self._request("GET", f"/hearings-reviews/{review_id}", headers=headers)

    def close_hearings_review(self, review_id, headers):
        return self._request("POST", f"/hearings-reviews/{review_id}/close",
                             {}, headers)

    def list_hearings_reviews_for_issuer(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/hearings-reviews",
                             headers=headers, params=params)

    # --- Appeal ---
    def create_appeal(self, issuer_id, payload, headers):
        return self._request("POST", f"/issuers/{issuer_id}/appeals", payload, headers)

    def list_appeals(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/appeals",
                             headers=headers, params=params)

    def get_appeal(self, issuer_id, appeal_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}/appeals/{appeal_id}",
                             headers=headers)

    def list_appeals_index(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def get_appeal_index(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals_for_review(self, review_id, headers, params=None):
        return self._request("GET", f"/hearings-reviews/{review_id}/appeals",
                             headers=headers, params=params)

    def appeal_panel_review(self, issuer_id, appeal_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/appeals/{appeal_id}/panel-review",
                             {}, headers)

    def appeal_panel_decision(self, issuer_id, appeal_id, payload, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/appeals/{appeal_id}/panel-decision",
                             payload, headers)

    def appeal_council_review(self, issuer_id, appeal_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/appeals/{appeal_id}/council-review",
                             {}, headers)

    def appeal_council_decision(self, issuer_id, appeal_id, payload, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/appeals/{appeal_id}/council-decision",
                             payload, headers)

    # --- FeeAssessment ---
    def run_annual_fees(self, issuer_id, payload, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/fee-assessments/run-annual-fees",
                             payload, headers)

    def list_fee_assessments(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/fee-assessments",
                             headers=headers, params=params)

    def get_fee_assessment(self, issuer_id, fee_id, headers):
        return self._request("GET",
                             f"/issuers/{issuer_id}/fee-assessments/{fee_id}",
                             headers=headers)

    def list_fee_assessments_index(self, headers, params=None):
        return self._request("GET", "/fee-assessments", headers=headers, params=params)

    def get_fee_assessment_index(self, fee_id, headers):
        return self._request("GET", f"/fee-assessments/{fee_id}", headers=headers)

    def mark_fee_paid(self, issuer_id, fee_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/fee-assessments/{fee_id}/mark-paid",
                             {}, headers)

    def waive_fee(self, issuer_id, fee_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/fee-assessments/{fee_id}/waive",
                             {}, headers)

    # --- CorporateAction ---
    def create_corporate_action(self, issuer_id, payload, headers):
        return self._request("POST", f"/issuers/{issuer_id}/corporate-actions",
                             payload, headers)

    def list_corporate_actions(self, issuer_id, headers, params=None):
        return self._request("GET", f"/issuers/{issuer_id}/corporate-actions",
                             headers=headers, params=params)

    def get_corporate_action(self, issuer_id, action_id, headers):
        return self._request("GET",
                             f"/issuers/{issuer_id}/corporate-actions/{action_id}",
                             headers=headers)

    def list_corporate_actions_index(self, headers, params=None):
        return self._request("GET", "/corporate-actions", headers=headers, params=params)

    def get_corporate_action_index(self, action_id, headers):
        return self._request("GET", f"/corporate-actions/{action_id}", headers=headers)

    def effect_corporate_action(self, issuer_id, action_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/corporate-actions/{action_id}/effect",
                             {}, headers)

    def reject_corporate_action(self, issuer_id, action_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/corporate-actions/{action_id}/reject",
                             {}, headers)

    def cancel_corporate_action(self, issuer_id, action_id, headers):
        return self._request("POST",
                             f"/issuers/{issuer_id}/corporate-actions/{action_id}/cancel",
                             {}, headers)


api_client = ApiClient()
