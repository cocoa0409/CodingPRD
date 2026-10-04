"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- MedicalGroup ---
    def create_medical_group(self, payload, headers):
        return self._request("POST", "/api/medical-groups", payload, headers)

    def list_medical_groups(self, headers, params=None):
        return self._request("GET", "/api/medical-groups", headers=headers, params=params)

    def get_medical_group(self, group_id, headers):
        return self._request("GET", f"/api/medical-groups/{group_id}", headers=headers)

    def activate_medical_group(self, group_id, headers):
        return self._request("POST", f"/api/medical-groups/{group_id}/activate", {}, headers)

    # --- Market ---
    def create_market(self, payload, headers):
        return self._request("POST", "/api/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/api/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/api/markets/{market_id}", headers=headers)

    # --- Practice ---
    def create_practice(self, payload, headers):
        return self._request("POST", "/api/practices", payload, headers)

    def list_practices(self, headers, params=None):
        return self._request("GET", "/api/practices", headers=headers, params=params)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/api/practices/{practice_id}", headers=headers)

    def suspend_practice(self, practice_id, headers):
        return self._request("POST", f"/api/practices/{practice_id}/suspend", {}, headers)

    def reinstate_practice(self, practice_id, headers):
        return self._request("POST", f"/api/practices/{practice_id}/reinstate", {}, headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/api/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/api/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/api/providers/{provider_id}", headers=headers)

    # --- AffiliationAgreement ---
    def create_affiliation_agreement(self, payload, headers):
        return self._request("POST", "/api/affiliation-agreements", payload, headers)

    def list_affiliation_agreements(self, headers, params=None):
        return self._request("GET", "/api/affiliation-agreements", headers=headers, params=params)

    def get_affiliation_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/affiliation-agreements/{agreement_id}", headers=headers)

    def execute_affiliation_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/affiliation-agreements/{agreement_id}/execute", {}, headers)

    # --- ImplementationWave ---
    def create_implementation_wave(self, payload, headers):
        return self._request("POST", "/api/implementation-waves", payload, headers)

    def list_implementation_waves(self, headers, params=None):
        return self._request("GET", "/api/implementation-waves", headers=headers, params=params)

    def get_implementation_wave(self, wave_id, headers):
        return self._request("GET", f"/api/implementation-waves/{wave_id}", headers=headers)

    def lock_implementation_wave(self, wave_id, payload, headers):
        return self._request("POST", f"/api/implementation-waves/{wave_id}/lock", payload, headers)

    def start_cutover_implementation_wave(self, wave_id, headers):
        return self._request("POST", f"/api/implementation-waves/{wave_id}/start-cutover", {}, headers)

    def complete_implementation_wave(self, wave_id, headers):
        return self._request("POST", f"/api/implementation-waves/{wave_id}/complete", {}, headers)

    def rollback_implementation_wave(self, wave_id, headers):
        return self._request("POST", f"/api/implementation-waves/{wave_id}/rollback", {}, headers)

    # --- PayerContract ---
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/api/payer-contracts", payload, headers)

    def list_payer_contracts(self, headers, params=None):
        return self._request("GET", "/api/payer-contracts", headers=headers, params=params)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/api/payer-contracts/{contract_id}", headers=headers)

    def activate_payer_contract(self, contract_id, headers):
        return self._request("POST", f"/api/payer-contracts/{contract_id}/activate", {}, headers)

    def terminate_payer_contract(self, contract_id, headers):
        return self._request("POST", f"/api/payer-contracts/{contract_id}/terminate", {}, headers)

    # --- FeeScheduleRate ---
    def create_fee_schedule_rate(self, payload, headers):
        return self._request("POST", "/api/fee-schedule-rates", payload, headers)

    def list_fee_schedule_rates(self, headers, params=None):
        return self._request("GET", "/api/fee-schedule-rates", headers=headers, params=params)

    def get_fee_schedule_rate(self, rate_id, headers):
        return self._request("GET", f"/api/fee-schedule-rates/{rate_id}", headers=headers)

    # --- CredentialingEnrollment ---
    def create_credentialing_enrollment(self, payload, headers):
        return self._request("POST", "/api/credentialing-enrollments", payload, headers)

    def list_credentialing_enrollments(self, headers, params=None):
        return self._request("GET", "/api/credentialing-enrollments", headers=headers, params=params)

    def get_credentialing_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/api/credentialing-enrollments/{enrollment_id}", headers=headers)

    def approve_credentialing_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/api/credentialing-enrollments/{enrollment_id}/approve", {}, headers)

    def terminate_credentialing_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/api/credentialing-enrollments/{enrollment_id}/terminate", payload, headers)

    # --- CollectionBatch ---
    def create_collection_batch(self, payload, headers):
        return self._request("POST", "/api/collection-batches", payload, headers)

    def list_collection_batches(self, headers, params=None):
        return self._request("GET", "/api/collection-batches", headers=headers, params=params)

    def get_collection_batch(self, batch_id, headers):
        return self._request("GET", f"/api/collection-batches/{batch_id}", headers=headers)

    def settle_collection_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/collection-batches/{batch_id}/settle", payload, headers)

    def adjust_collection_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/collection-batches/{batch_id}/adjust", payload, headers)

    # --- DistributionStatement ---
    def create_distribution_statement(self, payload, headers):
        return self._request("POST", "/api/distribution-statements", payload, headers)

    def list_distribution_statements(self, headers, params=None):
        return self._request("GET", "/api/distribution-statements", headers=headers, params=params)

    def get_distribution_statement(self, statement_id, headers):
        return self._request("GET", f"/api/distribution-statements/{statement_id}", headers=headers)

    def finalize_distribution_statement(self, statement_id, headers):
        return self._request("POST", f"/api/distribution-statements/{statement_id}/finalize", {}, headers)

    def amend_distribution_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/api/distribution-statements/{statement_id}/amend", payload, headers)

    def reissue_distribution_statement(self, statement_id, headers):
        return self._request("POST", f"/api/distribution-statements/{statement_id}/reissue", {}, headers)

    # --- ValueBasedIncentivePool ---
    def create_incentive_pool(self, payload, headers):
        return self._request("POST", "/api/incentive-pools", payload, headers)

    def list_incentive_pools(self, headers, params=None):
        return self._request("GET", "/api/incentive-pools", headers=headers, params=params)

    def get_incentive_pool(self, pool_id, headers):
        return self._request("GET", f"/api/incentive-pools/{pool_id}", headers=headers)

    def close_entries_incentive_pool(self, pool_id, headers):
        return self._request("POST", f"/api/incentive-pools/{pool_id}/close-entries", {}, headers)

    def allocate_incentive_pool(self, pool_id, headers):
        return self._request("POST", f"/api/incentive-pools/{pool_id}/allocate", {}, headers)

    def distribute_incentive_pool(self, pool_id, headers):
        return self._request("POST", f"/api/incentive-pools/{pool_id}/distribute", {}, headers)

    def void_incentive_pool(self, pool_id, headers):
        return self._request("POST", f"/api/incentive-pools/{pool_id}/void", {}, headers)

    # --- IncentiveAllocation ---
    def create_incentive_allocation(self, payload, headers):
        return self._request("POST", "/api/incentive-allocations", payload, headers)

    def list_incentive_allocations(self, headers, params=None):
        return self._request("GET", "/api/incentive-allocations", headers=headers, params=params)

    def get_incentive_allocation(self, allocation_id, headers):
        return self._request("GET", f"/api/incentive-allocations/{allocation_id}", headers=headers)

    def pay_incentive_allocation(self, allocation_id, headers):
        return self._request("POST", f"/api/incentive-allocations/{allocation_id}/pay", {}, headers)

    # --- DepartureCase ---
    def create_departure_case(self, payload, headers):
        return self._request("POST", "/api/departure-cases", payload, headers)

    def list_departure_cases(self, headers, params=None):
        return self._request("GET", "/api/departure-cases", headers=headers, params=params)

    def get_departure_case(self, case_id, headers):
        return self._request("GET", f"/api/departure-cases/{case_id}", headers=headers)

    def complete_review_departure_case(self, case_id, headers):
        return self._request("POST", f"/api/departure-cases/{case_id}/complete-review", {}, headers)

    def dispute_departure_case(self, case_id, headers):
        return self._request("POST", f"/api/departure-cases/{case_id}/dispute", {}, headers)

    def resettle_departure_case(self, case_id, headers):
        return self._request("POST", f"/api/departure-cases/{case_id}/resettle", {}, headers)

    def settle_departure_case(self, case_id, headers):
        return self._request("POST", f"/api/departure-cases/{case_id}/settle", {}, headers)

    def rescind_departure_case(self, case_id, headers):
        return self._request("POST", f"/api/departure-cases/{case_id}/rescind", {}, headers)

    # --- CommitteeVote ---
    def create_committee_vote(self, payload, headers):
        return self._request("POST", "/api/committee-votes", payload, headers)

    def list_committee_votes(self, headers, params=None):
        return self._request("GET", "/api/committee-votes", headers=headers, params=params)

    def get_committee_vote(self, vote_id, headers):
        return self._request("GET", f"/api/committee-votes/{vote_id}", headers=headers)

    def cast_committee_vote(self, vote_id, payload, headers):
        return self._request("POST", f"/api/committee-votes/{vote_id}/cast", payload, headers)


api_client = ApiClient()
