"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the /plan-admin prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/plan-admin"


class ApiClient(GenericApiClient):
    # ---------------- Employer ----------------
    def create_employer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"{PREFIX}/employers/{employer_id}", headers=headers)

    # ---------------- Plan ----------------
    def create_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/plans", payload=params, headers=headers)

    def set_plan_status(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/status", payload, headers)

    # ---------------- Vendor ----------------
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    # ---------------- InformationSharingAgreement ----------------
    def create_agreement(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/information-sharing-agreements", payload, headers
        )

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/information-sharing-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/information-sharing-agreements", payload=params, headers=headers
        )

    def set_agreement_status(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/information-sharing-agreements/{agreement_id}/status",
            payload,
            headers,
        )

    def post_data_feed(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/information-sharing-agreements/{agreement_id}/data-feed",
            payload,
            headers,
        )

    # ---------------- Participant ----------------
    def create_participant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"{PREFIX}/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/participants", payload=params, headers=headers)

    def update_participant(self, participant_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/participants/{participant_id}", payload, headers
        )

    # ---------------- UniversalAvailabilityNotice ----------------
    def create_notice(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plans/{plan_id}/universal-availability-notices", payload, headers
        )

    def list_notices(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/plans/{plan_id}/universal-availability-notices",
            payload=params,
            headers=headers,
        )

    # ---------------- EligibilityDetermination ----------------
    def create_eligibility_determination(self, payload, headers):
        return self._request("POST", f"{PREFIX}/eligibility-determinations", payload, headers)

    def get_eligibility_determination(self, determination_id, headers):
        return self._request(
            "GET", f"{PREFIX}/eligibility-determinations/{determination_id}", headers=headers
        )

    def list_eligibility_determinations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/eligibility-determinations", payload=params, headers=headers
        )

    # ---------------- VendorAccount ----------------
    def create_vendor_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vendor-accounts", payload, headers)

    def get_vendor_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/vendor-accounts/{account_id}", headers=headers)

    def list_vendor_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vendor-accounts", payload=params, headers=headers)

    def report_balance(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vendor-accounts/{account_id}/balance-report", payload, headers
        )

    # ---------------- ContributionElection ----------------
    def create_election(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contribution-elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request(
            "GET", f"{PREFIX}/contribution-elections/{election_id}", headers=headers
        )

    def list_elections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contribution-elections", payload=params, headers=headers
        )

    def decide_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contribution-elections/{election_id}/decision", payload, headers
        )

    def revoke_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contribution-elections/{election_id}/revoke", payload, headers
        )

    # ---------------- RemittanceBatch ----------------
    def create_remittance_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/remittance-batches", payload, headers)

    def get_remittance_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/remittance-batches/{batch_id}", headers=headers)

    def list_remittance_batches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/remittance-batches", payload=params, headers=headers
        )

    def deposit_remittance_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/remittance-batches/{batch_id}/deposit", payload, headers
        )

    def reverse_remittance_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/remittance-batches/{batch_id}/reverse", payload, headers
        )

    def list_corrections(self, batch_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/remittance-batches/{batch_id}/corrections",
            payload=params,
            headers=headers,
        )

    def settle_correction(self, batch_id, correction_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/remittance-batches/{batch_id}/corrections/{correction_id}/settle",
            payload,
            headers,
        )

    # ---------------- ParticipantRequest ----------------
    def create_participant_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/participant-requests", payload, headers)

    def get_participant_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/participant-requests/{request_id}", headers=headers
        )

    def list_participant_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/participant-requests", payload=params, headers=headers
        )

    def decide_participant_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participant-requests/{request_id}/decision", payload, headers
        )

    def resubmit_participant_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participant-requests/{request_id}/resubmit", payload, headers
        )

    def fulfill_participant_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participant-requests/{request_id}/fulfill", payload, headers
        )

    # ---------------- TransferExchangeRequest ----------------
    def create_movement_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfer-exchange-requests", payload, headers)

    def get_movement_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transfer-exchange-requests/{request_id}", headers=headers
        )

    def list_movement_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transfer-exchange-requests", payload=params, headers=headers
        )

    def respond_to_movement_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-exchange-requests/{request_id}/vendor-response",
            payload,
            headers,
        )

    def decide_movement_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-exchange-requests/{request_id}/decision",
            payload,
            headers,
        )

    def execute_movement_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transfer-exchange-requests/{request_id}/execute", payload, headers
        )

    def reverse_movement_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transfer-exchange-requests/{request_id}/reverse", payload, headers
        )

    # ---------------- Computed reads ----------------
    def get_contribution_limit_summary(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/participants/{participant_id}/contribution-limit-summary",
            payload=params,
            headers=headers,
        )

    def get_loan_capacity(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/participants/{participant_id}/loan-capacity",
            payload=params,
            headers=headers,
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
