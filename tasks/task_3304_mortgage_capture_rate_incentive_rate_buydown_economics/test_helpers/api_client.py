"""API client: one method per endpoint in the housing contract."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin wrapper over the HTTP surface mounted at /housing."""

    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/housing/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Community ---
    def create_community(self, payload, headers):
        return self._request("POST", "/housing/communities", payload, headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/housing/communities", None, headers, params)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/housing/communities/{community_id}", None, headers)

    def set_community_posture(self, community_id, target_status, headers):
        return self._request(
            "POST", f"/housing/communities/{community_id}/posture",
            {"target_status": target_status}, headers,
        )

    def list_community_forward_commitments(self, community_id, headers):
        return self._request(
            "GET", f"/housing/communities/{community_id}/forward-commitments", None, headers
        )

    def list_community_home_sites(self, community_id, headers):
        return self._request(
            "GET", f"/housing/communities/{community_id}/home-sites", None, headers
        )

    # --- ForwardCommitment ---
    def create_forward_commitment(self, community_id, payload, headers):
        return self._request(
            "POST", f"/housing/communities/{community_id}/forward-commitments", payload, headers
        )

    def get_forward_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"/housing/forward-commitments/{commitment_id}", None, headers
        )

    def close_forward_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"/housing/forward-commitments/{commitment_id}/close", {}, headers
        )

    def list_commitment_rate_locks(self, commitment_id, headers):
        return self._request(
            "GET", f"/housing/forward-commitments/{commitment_id}/rate-locks", None, headers
        )

    # --- HomeSite ---
    def create_home_site(self, community_id, payload, headers):
        return self._request(
            "POST", f"/housing/communities/{community_id}/home-sites", payload, headers
        )

    def get_home_site(self, home_site_id, headers):
        return self._request("GET", f"/housing/home-sites/{home_site_id}", None, headers)

    def reserve_home_site(self, community_id, home_site_id, headers):
        return self._request(
            "POST", f"/housing/communities/{community_id}/home-sites/{home_site_id}/reserve",
            {}, headers,
        )

    def list_home_site_contracts(self, home_site_id, headers):
        return self._request(
            "GET", f"/housing/home-sites/{home_site_id}/contracts", None, headers
        )

    # --- Buyer ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/housing/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/housing/buyers/{buyer_id}", None, headers)

    def list_buyer_contracts(self, buyer_id, headers):
        return self._request("GET", f"/housing/buyers/{buyer_id}/contracts", None, headers)

    def qualify_buyer(self, buyer_id, headers):
        return self._request("POST", f"/housing/buyers/{buyer_id}/qualify", {}, headers)

    def withdraw_buyer(self, buyer_id, headers):
        return self._request("POST", f"/housing/buyers/{buyer_id}/withdraw", {}, headers)

    # --- HomeSaleContract ---
    def create_contract(self, home_site_id, payload, headers):
        return self._request("POST", f"/housing/home-sites/{home_site_id}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/housing/contracts/{contract_id}", None, headers)

    def lock_contract(self, contract_id, headers):
        return self._request("POST", f"/housing/contracts/{contract_id}/lock", {}, headers)

    def approve_contract(self, contract_id, headers):
        return self._request("POST", f"/housing/contracts/{contract_id}/approve", {}, headers)

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/housing/contracts/{contract_id}/close", {}, headers)

    def cancel_contract(self, contract_id, cancellation_reason, headers):
        return self._request(
            "POST", f"/housing/contracts/{contract_id}/cancel",
            {"cancellation_reason": cancellation_reason}, headers,
        )

    def reinstate_contract(self, contract_id, headers):
        return self._request("POST", f"/housing/contracts/{contract_id}/reinstate", {}, headers)

    def list_contract_loan_applications(self, contract_id, headers):
        return self._request(
            "GET", f"/housing/contracts/{contract_id}/loan-applications", None, headers
        )

    def list_contract_incentive_allocations(self, contract_id, headers):
        return self._request(
            "GET", f"/housing/contracts/{contract_id}/incentive-allocations", None, headers
        )

    def list_contract_buydown_records(self, contract_id, headers):
        return self._request(
            "GET", f"/housing/contracts/{contract_id}/buydown-records", None, headers
        )

    def list_contract_disclosures(self, contract_id, headers):
        return self._request(
            "GET", f"/housing/contracts/{contract_id}/disclosures", None, headers
        )

    def list_contract_deposit_forfeitures(self, contract_id, headers):
        return self._request(
            "GET", f"/housing/contracts/{contract_id}/deposit-forfeitures", None, headers
        )

    # --- LoanApplication ---
    def create_loan_application(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/housing/contracts/{contract_id}/loan-applications", payload, headers
        )

    def get_loan_application(self, application_id, headers):
        return self._request(
            "GET", f"/housing/loan-applications/{application_id}", None, headers
        )

    def qualify_loan_application(self, application_id, headers):
        return self._request(
            "POST", f"/housing/loan-applications/{application_id}/qualify", {}, headers
        )

    def deny_loan_application(self, application_id, headers):
        return self._request(
            "POST", f"/housing/loan-applications/{application_id}/deny", {}, headers
        )

    def relock_loan_application(self, application_id, headers):
        return self._request(
            "POST", f"/housing/loan-applications/{application_id}/relock", {}, headers
        )

    def set_lock_waiver(self, application_id, target_waiver_status, headers):
        return self._request(
            "POST", f"/housing/loan-applications/{application_id}/lock-waiver",
            {"target_waiver_status": target_waiver_status}, headers,
        )

    def list_application_rate_locks(self, application_id, headers):
        return self._request(
            "GET", f"/housing/loan-applications/{application_id}/rate-locks", None, headers
        )

    # --- RateLock ---
    def create_rate_lock(self, application_id, payload, headers):
        return self._request(
            "POST", f"/housing/loan-applications/{application_id}/rate-locks", payload, headers
        )

    def get_rate_lock(self, rate_lock_id, headers):
        return self._request("GET", f"/housing/rate-locks/{rate_lock_id}", None, headers)

    def void_rate_lock(self, rate_lock_id, headers):
        return self._request("POST", f"/housing/rate-locks/{rate_lock_id}/void", {}, headers)

    def extend_rate_lock(self, rate_lock_id, new_lock_days, headers):
        return self._request(
            "POST", f"/housing/rate-locks/{rate_lock_id}/extend",
            {"new_lock_days": new_lock_days}, headers,
        )

    def relock_rate_lock(self, rate_lock_id, headers):
        return self._request("POST", f"/housing/rate-locks/{rate_lock_id}/relock", {}, headers)

    # --- IncentiveAllocation ---
    def create_incentive_allocation(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/housing/contracts/{contract_id}/incentive-allocations", payload, headers
        )

    def get_incentive_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/housing/incentive-allocations/{allocation_id}", None, headers
        )

    def list_allocation_buydown_records(self, allocation_id, headers):
        return self._request(
            "GET", f"/housing/incentive-allocations/{allocation_id}/buydown-records", None, headers
        )

    # --- BuydownCostRecord ---
    def create_buydown_record(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/housing/contracts/{contract_id}/buydown-records", payload, headers
        )

    def get_buydown_record(self, record_id, headers):
        return self._request("GET", f"/housing/buydown-records/{record_id}", None, headers)

    # --- ABADisclosure ---
    def create_disclosure(self, contract_id, disclosure_type, headers):
        return self._request(
            "POST", f"/housing/contracts/{contract_id}/disclosures",
            {"disclosure_type": disclosure_type}, headers,
        )

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/housing/disclosures/{disclosure_id}", None, headers)

    def acknowledge_disclosure(self, disclosure_id, headers):
        return self._request(
            "POST", f"/housing/disclosures/{disclosure_id}/acknowledge", {}, headers
        )

    def waive_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/housing/disclosures/{disclosure_id}/waive", {}, headers)

    # --- DepositForfeiture ---
    def create_deposit_forfeiture(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/housing/contracts/{contract_id}/deposit-forfeitures", payload, headers
        )

    def get_deposit_forfeiture(self, forfeiture_id, headers):
        return self._request(
            "GET", f"/housing/deposit-forfeitures/{forfeiture_id}", None, headers
        )

    def finalize_deposit_forfeiture(self, forfeiture_id, headers):
        return self._request(
            "POST", f"/housing/deposit-forfeitures/{forfeiture_id}/finalize", {}, headers
        )


api_client = ApiClient()