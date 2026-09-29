"""API client: one method per endpoint defined in the PRD (§4).

Every business endpoint is mounted under the /perks prefix; the two
test-harness control-plane endpoints are not.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ── Control plane (PRD §2.4) ────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_epoch(self, headers):
        return self._request("POST", "/_ops/run-epoch", {}, headers)

    # ── Merchants (PRD §3.1, §3.8) ──────────────────────────────────────────

    def create_merchant(self, payload, headers):
        return self._request("POST", "/perks/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/perks/merchants/{merchant_id}", headers=headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/perks/merchants", headers=headers, params=params)

    def update_merchant(self, merchant_id, payload, headers):
        return self._request("PATCH", f"/perks/merchants/{merchant_id}", payload, headers)

    def reinstate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/perks/merchants/{merchant_id}/reinstate", {}, headers)

    def terminate_merchant(self, merchant_id, payload, headers):
        return self._request("POST", f"/perks/merchants/{merchant_id}/terminate", payload, headers)

    # ── Partner agreements and negotiation (PRD §3.1, §3.2) ─────────────────

    def create_agreement(self, payload, headers):
        return self._request("POST", "/perks/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/perks/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/perks/agreements", headers=headers, params=params)

    def list_negotiation_rounds(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/perks/agreements/{agreement_id}/negotiation-rounds",
            headers=headers, params=params,
        )

    def propose_round(self, agreement_id, payload, headers):
        return self._request("POST", f"/perks/agreements/{agreement_id}/propose", payload, headers)

    def counter_round(self, agreement_id, payload, headers):
        return self._request("POST", f"/perks/agreements/{agreement_id}/counter", payload, headers)

    def decide_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/perks/agreements/{agreement_id}/decide", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/perks/agreements/{agreement_id}/activate", {}, headers)

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/perks/agreements/{agreement_id}/terminate", payload, headers)

    # ── Employers, storefronts and eligibility (PRD §3.3, §3.4) ─────────────

    def create_employer(self, payload, headers):
        return self._request("POST", "/perks/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/perks/employers/{employer_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/perks/employers", headers=headers, params=params)

    def update_employer(self, employer_id, payload, headers):
        return self._request("PATCH", f"/perks/employers/{employer_id}", payload, headers)

    def brand_storefront(self, employer_id, payload, headers):
        return self._request("POST", f"/perks/employers/{employer_id}/storefront", payload, headers)

    def publish_storefront(self, employer_id, headers):
        return self._request("POST", f"/perks/employers/{employer_id}/storefront/publish", {}, headers)

    def suspend_storefront(self, employer_id, payload, headers):
        return self._request("POST", f"/perks/employers/{employer_id}/storefront/suspend", payload, headers)

    def create_eligibility_file(self, employer_id, payload, headers):
        return self._request("POST", f"/perks/employers/{employer_id}/eligibility-files", payload, headers)

    def list_eligibility_files(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/perks/employers/{employer_id}/eligibility-files",
            headers=headers, params=params,
        )

    def get_engagement_report(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/perks/employers/{employer_id}/engagement-report",
            headers=headers, params=params,
        )

    def get_category_demand(self, headers, params=None):
        return self._request("GET", "/perks/category-demand", headers=headers, params=params)

    def get_eligibility_file(self, file_id, headers):
        return self._request("GET", f"/perks/eligibility-files/{file_id}", headers=headers)

    def validate_eligibility_file(self, file_id, headers):
        return self._request("POST", f"/perks/eligibility-files/{file_id}/validate", {}, headers)

    def apply_eligibility_file(self, file_id, headers):
        return self._request("POST", f"/perks/eligibility-files/{file_id}/apply", {}, headers)

    # ── Memberships (PRD §3.3) ──────────────────────────────────────────────

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/perks/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/perks/memberships", headers=headers, params=params)

    def set_employment_status(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/perks/memberships/{membership_id}/employment-status", payload, headers
        )

    # ── Offers (PRD §3.5) ───────────────────────────────────────────────────

    def create_offer(self, payload, headers):
        return self._request("POST", "/perks/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/perks/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/perks/offers", headers=headers, params=params)

    def submit_offer(self, offer_id, headers):
        return self._request("POST", f"/perks/offers/{offer_id}/submit", {}, headers)

    def review_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/perks/offers/{offer_id}/review", payload, headers)

    def pause_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/perks/offers/{offer_id}/pause", payload, headers)

    def resume_offer(self, offer_id, headers):
        return self._request("POST", f"/perks/offers/{offer_id}/resume", {}, headers)

    # ── Placement slots (PRD §3.6) ──────────────────────────────────────────

    def reserve_placement_slot(self, offer_id, payload, headers):
        return self._request("POST", f"/perks/offers/{offer_id}/placement-slots", payload, headers)

    def get_placement_slot(self, slot_id, headers):
        return self._request("GET", f"/perks/placement-slots/{slot_id}", headers=headers)

    def list_placement_slots(self, headers, params=None):
        return self._request("GET", "/perks/placement-slots", headers=headers, params=params)

    def confirm_placement_slot(self, slot_id, headers):
        return self._request("POST", f"/perks/placement-slots/{slot_id}/confirm", {}, headers)

    def release_placement_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/perks/placement-slots/{slot_id}/release", payload, headers)

    # ── Redemptions (PRD §3.7, §3.8) ────────────────────────────────────────

    def create_redemption(self, payload, headers):
        return self._request("POST", "/perks/redemptions", payload, headers)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/perks/redemptions/{redemption_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/perks/redemptions", headers=headers, params=params)

    def verify_redemption(self, redemption_id, payload, headers):
        return self._request("POST", f"/perks/redemptions/{redemption_id}/verify", payload, headers)

    def fulfill_redemption(self, redemption_id, headers):
        return self._request("POST", f"/perks/redemptions/{redemption_id}/fulfill", {}, headers)

    def void_redemption(self, redemption_id, headers):
        return self._request("POST", f"/perks/redemptions/{redemption_id}/void", {}, headers)

    def create_dispute(self, redemption_id, payload, headers):
        return self._request("POST", f"/perks/redemptions/{redemption_id}/disputes", payload, headers)

    def list_redemption_ledger_entries(self, redemption_id, headers, params=None):
        return self._request(
            "GET", f"/perks/redemptions/{redemption_id}/ledger-entries",
            headers=headers, params=params,
        )

    # ── Disputes (PRD §3.8) ─────────────────────────────────────────────────

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/perks/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/perks/disputes", headers=headers, params=params)

    def respond_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/perks/disputes/{dispute_id}/respond", payload, headers)

    def request_dispute_info(self, dispute_id, headers):
        return self._request("POST", f"/perks/disputes/{dispute_id}/request-info", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/perks/disputes/{dispute_id}/resolve", payload, headers)

    # ── Revenue share statements and ledger (PRD §3.9) ──────────────────────

    def create_statement(self, payload, headers):
        return self._request("POST", "/perks/revenue-share-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/perks/revenue-share-statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/perks/revenue-share-statements", headers=headers, params=params)

    def finalize_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/perks/revenue-share-statements/{statement_id}/finalize", {}, headers
        )

    def pay_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/perks/revenue-share-statements/{statement_id}/pay", payload, headers
        )

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/perks/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/perks/ledger-entries", headers=headers, params=params)

    # ── Raw helpers for negative tests that must omit or mangle a header ─────

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
