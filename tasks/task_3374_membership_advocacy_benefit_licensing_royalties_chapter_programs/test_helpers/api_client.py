"""API client: one method per endpoint defined in the PRD (all under /api)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock / batch ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_renewal_batch(self, headers):
        return self._request("POST", "/api/_batch/renewal_run", {}, headers)

    # --- households / members / terms ---
    def create_household(self, payload, headers):
        return self._request("POST", "/api/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/api/households/{household_id}", headers=headers)

    def list_household_members(self, household_id, headers, params=None):
        return self._request("GET", f"/api/households/{household_id}/members",
                             headers=headers, params=params)

    def list_household_terms(self, household_id, headers, params=None):
        return self._request("GET", f"/api/households/{household_id}/terms",
                             headers=headers, params=params)

    def cancel_term(self, term_id, payload, headers):
        return self._request("POST", f"/api/membership-terms/{term_id}/cancel",
                             payload, headers)

    # --- providers / agreements / royalty statements ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/api/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/api/providers/{provider_id}", headers=headers)

    def admit_provider(self, provider_id, headers):
        return self._request("POST", f"/api/providers/{provider_id}/admit", {}, headers)

    def create_license_agreement(self, provider_id, payload, headers):
        return self._request("POST", f"/api/providers/{provider_id}/license-agreements",
                             payload, headers)

    def list_provider_agreements(self, provider_id, headers, params=None):
        return self._request("GET", f"/api/providers/{provider_id}/license-agreements",
                             headers=headers, params=params)

    def get_license_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/license-agreements/{agreement_id}",
                             headers=headers)

    def transition_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/license-agreements/{agreement_id}/transitions",
                             payload, headers)

    def submit_royalty_statement(self, agreement_id, payload, headers):
        return self._request("POST",
                             f"/api/license-agreements/{agreement_id}/royalty-statements",
                             payload, headers)

    def list_agreement_statements(self, agreement_id, headers, params=None):
        return self._request("GET",
                             f"/api/license-agreements/{agreement_id}/royalty-statements",
                             headers=headers, params=params)

    def finalize_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/api/royalty-statements/{statement_id}/finalize",
                             payload, headers)

    # --- complaints / oversight ---
    def file_complaint(self, payload, headers):
        return self._request("POST", "/api/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/api/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/api/complaints", headers=headers, params=params)

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/adjudicate",
                             payload, headers)

    # --- legal entities / fund transfers ---
    def create_legal_entity(self, payload, headers):
        return self._request("POST", "/api/legal-entities", payload, headers)

    def get_legal_entity(self, entity_id, headers):
        return self._request("GET", f"/api/legal-entities/{entity_id}", headers=headers)

    def create_fund_transfer(self, payload, headers):
        return self._request("POST", "/api/fund-transfers", payload, headers)

    def list_entity_fund_transfers(self, entity_id, headers, params=None):
        return self._request("GET", f"/api/legal-entities/{entity_id}/fund-transfers",
                             headers=headers, params=params)

    def decide_fund_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/fund-transfers/{transfer_id}/approve",
                             payload, headers)

    # --- publications / advertising ---
    def create_publication(self, payload, headers):
        return self._request("POST", "/api/publications", payload, headers)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"/api/publications/{publication_id}", headers=headers)

    def create_ad_booking(self, publication_id, payload, headers):
        return self._request("POST", f"/api/publications/{publication_id}/ad-bookings",
                             payload, headers)

    def list_ad_bookings(self, publication_id, headers, params=None):
        return self._request("GET", f"/api/publications/{publication_id}/ad-bookings",
                             headers=headers, params=params)

    # --- chapters / course sessions ---
    def create_chapter(self, payload, headers):
        return self._request("POST", "/api/chapters", payload, headers)

    def get_chapter(self, chapter_id, headers):
        return self._request("GET", f"/api/chapters/{chapter_id}", headers=headers)

    def create_course_session(self, chapter_id, payload, headers):
        return self._request("POST", f"/api/chapters/{chapter_id}/course-sessions",
                             payload, headers)

    def list_chapter_sessions(self, chapter_id, headers, params=None):
        return self._request("GET", f"/api/chapters/{chapter_id}/course-sessions",
                             headers=headers, params=params)

    def enroll_member(self, session_id, payload, headers):
        return self._request("POST", f"/api/course-sessions/{session_id}/enroll",
                             payload, headers)

    # --- advocacy campaigns / mobilization ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/api/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/api/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/api/campaigns", headers=headers, params=params)

    def create_mobilization(self, campaign_id, payload, headers):
        return self._request("POST", f"/api/campaigns/{campaign_id}/mobilizations",
                             payload, headers)

    def list_mobilizations(self, campaign_id, headers, params=None):
        return self._request("GET", f"/api/campaigns/{campaign_id}/mobilizations",
                             headers=headers, params=params)


api_client = ApiClient()
