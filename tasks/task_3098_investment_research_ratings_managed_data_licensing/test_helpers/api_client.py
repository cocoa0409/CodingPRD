"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Fund companies ---
    def create_fund_company(self, payload, headers):
        return self._request("POST", "/research/fund-companies", payload, headers)

    def get_fund_company(self, company_id, headers):
        return self._request("GET", f"/research/fund-companies/{company_id}", headers=headers)

    def list_fund_companies(self, headers, params=None):
        return self._request("GET", "/research/fund-companies", headers=headers, params=params)

    def list_company_funds(self, company_id, headers, params=None):
        return self._request("GET", f"/research/fund-companies/{company_id}/funds", headers=headers, params=params)

    def list_company_disputes(self, company_id, headers, params=None):
        return self._request("GET", f"/research/fund-companies/{company_id}/disputes", headers=headers, params=params)

    def suspend_fund_company(self, company_id, headers):
        return self._request("POST", f"/research/fund-companies/{company_id}/suspend", headers=headers)

    def reinstate_fund_company(self, company_id, headers):
        return self._request("POST", f"/research/fund-companies/{company_id}/reinstate", headers=headers)

    def offboard_fund_company(self, company_id, headers):
        return self._request("POST", f"/research/fund-companies/{company_id}/offboard", headers=headers)

    # --- Funds & holdings ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/research/funds", payload, headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/research/funds/{fund_id}", headers=headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/research/funds", headers=headers, params=params)

    def ingest_holdings(self, fund_id, payload, headers):
        return self._request("POST", f"/research/funds/{fund_id}/holdings", payload, headers)

    def list_holdings(self, fund_id, headers, params=None):
        return self._request("GET", f"/research/funds/{fund_id}/holdings", headers=headers, params=params)

    def assign_category(self, fund_id, headers):
        return self._request("POST", f"/research/funds/{fund_id}/assign-category", headers=headers)

    def liquidate_fund(self, fund_id, headers):
        return self._request("POST", f"/research/funds/{fund_id}/liquidate", headers=headers)

    def list_fund_ratings(self, fund_id, headers, params=None):
        return self._request("GET", f"/research/funds/{fund_id}/ratings", headers=headers, params=params)

    def list_fund_disputes(self, fund_id, headers, params=None):
        return self._request("GET", f"/research/funds/{fund_id}/disputes", headers=headers, params=params)

    def list_fund_conflict_flags(self, fund_id, headers, params=None):
        return self._request("GET", f"/research/funds/{fund_id}/conflict-flags", headers=headers, params=params)

    def raise_dispute(self, fund_id, payload, headers):
        return self._request("POST", f"/research/funds/{fund_id}/disputes", payload, headers)

    def list_fund_constituents(self, fund_id, headers, params=None):
        return self._request("GET", f"/research/funds/{fund_id}/constituents", headers=headers, params=params)

    # --- Categories ---
    def create_category(self, payload, headers):
        return self._request("POST", "/research/categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/research/categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/research/categories/{category_id}", headers=headers)

    # --- Methodologies & changes ---
    def create_methodology(self, payload, headers):
        return self._request("POST", "/research/methodologies", payload, headers)

    def get_methodology(self, methodology_id, headers):
        return self._request("GET", f"/research/methodologies/{methodology_id}", headers=headers)

    def list_methodologies(self, headers, params=None):
        return self._request("GET", "/research/methodologies", headers=headers, params=params)

    def list_methodology_changes(self, methodology_id, headers, params=None):
        return self._request("GET", f"/research/methodologies/{methodology_id}/changes", headers=headers, params=params)

    def activate_methodology(self, methodology_id, headers):
        return self._request("POST", f"/research/methodologies/{methodology_id}/activate", headers=headers)

    def retire_methodology(self, methodology_id, headers):
        return self._request("POST", f"/research/methodologies/{methodology_id}/retire", headers=headers)

    def propose_methodology_change(self, methodology_id, payload, headers):
        return self._request("POST", f"/research/methodologies/{methodology_id}/changes", payload, headers)

    def get_methodology_change(self, change_id, headers):
        return self._request("GET", f"/research/methodology-changes/{change_id}", headers=headers)

    def list_change_notices(self, change_id, headers, params=None):
        return self._request("GET", f"/research/methodology-changes/{change_id}/notices", headers=headers, params=params)

    def approve_change(self, change_id, headers):
        return self._request("POST", f"/research/methodology-changes/{change_id}/approve", headers=headers)

    def record_notice(self, change_id, payload, headers):
        return self._request("POST", f"/research/methodology-changes/{change_id}/notices", payload, headers)

    def effectuate_change(self, change_id, headers):
        return self._request("POST", f"/research/methodology-changes/{change_id}/effectuate", headers=headers)

    def withdraw_change(self, change_id, headers):
        return self._request("POST", f"/research/methodology-changes/{change_id}/withdraw", headers=headers)

    # --- Ratings & committee ---
    def compute_rating(self, payload, headers):
        return self._request("POST", "/research/ratings/compute", payload, headers)

    def initiate_analyst_rating(self, payload, headers):
        return self._request("POST", "/research/ratings", payload, headers)

    def get_rating(self, rating_id, headers):
        return self._request("GET", f"/research/ratings/{rating_id}", headers=headers)

    def list_ratings(self, headers, params=None):
        return self._request("GET", "/research/ratings", headers=headers, params=params)

    def publish_rating(self, rating_id, headers):
        return self._request("POST", f"/research/ratings/{rating_id}/publish", headers=headers)

    def withdraw_rating(self, rating_id, headers):
        return self._request("POST", f"/research/ratings/{rating_id}/withdraw", headers=headers)

    def open_proposal(self, rating_id, payload, headers):
        return self._request("POST", f"/research/ratings/{rating_id}/proposals", payload, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/research/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/research/proposals/{proposal_id}", headers=headers)

    def list_votes(self, proposal_id, headers, params=None):
        return self._request("GET", f"/research/proposals/{proposal_id}/votes", headers=headers, params=params)

    def cast_vote(self, proposal_id, payload, headers):
        return self._request("POST", f"/research/proposals/{proposal_id}/votes", payload, headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/research/proposals/{proposal_id}/withdraw", headers=headers)

    # --- Conflict flags ---
    def waive_conflict_flag(self, flag_id, headers):
        return self._request("POST", f"/research/conflict-flags/{flag_id}/waive", headers=headers)

    def get_conflict_flag(self, flag_id, headers):
        return self._request("GET", f"/research/conflict-flags/{flag_id}", headers=headers)

    # --- Licensees, agreements, seats, audits ---
    def create_licensee(self, payload, headers):
        return self._request("POST", "/research/licensees", payload, headers)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"/research/licensees/{licensee_id}", headers=headers)

    def list_licensee_agreements(self, licensee_id, headers, params=None):
        return self._request("GET", f"/research/licensees/{licensee_id}/agreements", headers=headers, params=params)

    def list_licensee_notices(self, licensee_id, headers, params=None):
        return self._request("GET", f"/research/licensees/{licensee_id}/notices", headers=headers, params=params)

    def reinstate_licensee(self, licensee_id, headers):
        return self._request("POST", f"/research/licensees/{licensee_id}/reinstate", headers=headers)

    def terminate_licensee(self, licensee_id, headers):
        return self._request("POST", f"/research/licensees/{licensee_id}/terminate", headers=headers)

    def create_license_agreement(self, payload, headers):
        return self._request("POST", "/research/license-agreements", payload, headers)

    def fee_quote(self, payload, headers):
        return self._request("POST", "/research/license-agreements/fee-quote", payload, headers)

    def get_license_agreement(self, agreement_id, headers):
        return self._request("GET", f"/research/license-agreements/{agreement_id}", headers=headers)

    def list_agreement_seats(self, agreement_id, headers, params=None):
        return self._request("GET", f"/research/license-agreements/{agreement_id}/seats", headers=headers, params=params)

    def list_agreement_audits(self, agreement_id, headers, params=None):
        return self._request("GET", f"/research/license-agreements/{agreement_id}/audits", headers=headers, params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/research/license-agreements/{agreement_id}/activate", headers=headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/research/license-agreements/{agreement_id}/suspend", headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/research/license-agreements/{agreement_id}/terminate", headers=headers)

    def grant_seat(self, agreement_id, payload, headers):
        return self._request("POST", f"/research/license-agreements/{agreement_id}/seats", payload, headers)

    def revoke_seat(self, seat_id, headers):
        return self._request("POST", f"/research/seat-entitlements/{seat_id}/revoke", headers=headers)

    def open_audit(self, payload, headers):
        return self._request("POST", "/research/license-audits", payload, headers)

    def file_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/research/license-audits/{audit_id}/file-findings", payload, headers)

    def close_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/research/license-audits/{audit_id}/close", payload, headers)

    # --- Indices ---
    def create_index(self, payload, headers):
        return self._request("POST", "/research/indices", payload, headers)

    def get_index(self, index_id, headers):
        return self._request("GET", f"/research/indices/{index_id}", headers=headers)

    def list_indices(self, headers, params=None):
        return self._request("GET", "/research/indices", headers=headers, params=params)

    def list_index_constituents(self, index_id, headers, params=None):
        return self._request("GET", f"/research/indices/{index_id}/constituents", headers=headers, params=params)

    def link_license(self, index_id, payload, headers):
        return self._request("POST", f"/research/indices/{index_id}/link-license", payload, headers)

    def add_constituent(self, index_id, payload, headers):
        return self._request("POST", f"/research/indices/{index_id}/constituents", payload, headers)

    def launch_index(self, index_id, headers):
        return self._request("POST", f"/research/indices/{index_id}/launch", headers=headers)

    def suspend_index(self, index_id, headers):
        return self._request("POST", f"/research/indices/{index_id}/suspend", headers=headers)

    def retire_index(self, index_id, headers):
        return self._request("POST", f"/research/indices/{index_id}/retire", headers=headers)

    def rebalance_index(self, index_id, headers):
        return self._request("POST", f"/research/indices/{index_id}/rebalance", headers=headers)

    # --- Data disputes (operator side) ---
    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/research/data-disputes/{dispute_id}", headers=headers)

    def investigate_dispute(self, dispute_id, headers):
        return self._request("POST", f"/research/data-disputes/{dispute_id}/investigate", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/research/data-disputes/{dispute_id}/resolve", payload, headers)


api_client = ApiClient()
