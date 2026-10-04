"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- payer clients ---
    def create_payer_client(self, payload, headers):
        return self._request("POST", "/payer-clients", payload, headers)

    def get_payer_client(self, payer_id, headers):
        return self._request("GET", f"/payer-clients/{payer_id}", headers=headers)

    def list_payer_clients(self, headers, params=None):
        return self._request("GET", "/payer-clients", headers=headers, params=params)

    def suspend_payer_client(self, payer_id, headers):
        return self._request("POST", f"/payer-clients/{payer_id}/suspend", {}, headers)

    def reinstate_payer_client(self, payer_id, headers):
        return self._request("POST", f"/payer-clients/{payer_id}/reinstate", {}, headers)

    # --- repricing policies ---
    def create_repricing_policy(self, payload, headers):
        return self._request("POST", "/repricing-policies", payload, headers)

    def get_repricing_policy(self, policy_id, headers):
        return self._request("GET", f"/repricing-policies/{policy_id}", headers=headers)

    def list_repricing_policies(self, headers, params=None):
        return self._request("GET", "/repricing-policies", headers=headers, params=params)

    def retire_repricing_policy(self, policy_id, headers):
        return self._request("POST", f"/repricing-policies/{policy_id}/retire", {}, headers)

    # --- determinations ---
    def get_determination(self, determination_id, headers):
        return self._request("GET", f"/repricing-determinations/{determination_id}",
                             headers=headers)

    def list_determinations(self, headers, params=None):
        return self._request("GET", "/repricing-determinations", headers=headers,
                             params=params)

    # --- providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    # --- network agreements ---
    def create_network_agreement(self, payload, headers):
        return self._request("POST", "/network-agreements", payload, headers)

    def get_network_agreement(self, agreement_id, headers):
        return self._request("GET", f"/network-agreements/{agreement_id}", headers=headers)

    def list_network_agreements(self, headers, params=None):
        return self._request("GET", "/network-agreements", headers=headers, params=params)

    def suspend_network_agreement(self, agreement_id, headers):
        return self._request("POST", f"/network-agreements/{agreement_id}/suspend",
                             {}, headers)

    def reinstate_network_agreement(self, agreement_id, headers):
        return self._request("POST", f"/network-agreements/{agreement_id}/reinstate",
                             {}, headers)

    def terminate_network_agreement(self, agreement_id, headers):
        return self._request("POST", f"/network-agreements/{agreement_id}/terminate",
                             {}, headers)

    # --- rate tables ---
    def create_medicare_entry(self, payload, headers):
        return self._request("POST", "/medicare-fee-schedule", payload, headers)

    def list_medicare_entries(self, headers, params=None):
        return self._request("GET", "/medicare-fee-schedule", headers=headers, params=params)

    def create_ucr_rate(self, payload, headers):
        return self._request("POST", "/ucr-rates", payload, headers)

    def list_ucr_rates(self, headers, params=None):
        return self._request("GET", "/ucr-rates", headers=headers, params=params)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def add_claim_line(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/lines", payload, headers)

    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/lines", headers=headers,
                             params=params)

    def reprice_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reprice", payload, headers)

    def list_claim_determinations(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/determinations", headers=headers,
                             params=params)

    def finalize_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/finalize", {}, headers)

    # --- negotiation cases ---
    def create_negotiation_case(self, payload, headers):
        return self._request("POST", "/negotiation-cases", payload, headers)

    def get_negotiation_case(self, case_id, headers):
        return self._request("GET", f"/negotiation-cases/{case_id}", headers=headers)

    def list_negotiation_cases(self, headers, params=None):
        return self._request("GET", "/negotiation-cases", headers=headers, params=params)

    def offer_negotiation_case(self, case_id, payload, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/offer", payload, headers)

    def counter_negotiation_case(self, case_id, payload, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/counter", payload, headers)

    def accept_negotiation_case(self, case_id, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/accept", {}, headers)

    def withdraw_negotiation_case(self, case_id, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/withdraw", {}, headers)

    # --- settlement agreements ---
    def get_settlement_agreement(self, agreement_id, headers):
        return self._request("GET", f"/settlement-agreements/{agreement_id}", headers=headers)

    def list_settlement_agreements(self, headers, params=None):
        return self._request("GET", "/settlement-agreements", headers=headers, params=params)

    def sign_settlement_agreement(self, agreement_id, headers):
        return self._request("POST", f"/settlement-agreements/{agreement_id}/sign",
                             {}, headers)

    def void_settlement_agreement(self, agreement_id, headers):
        return self._request("POST", f"/settlement-agreements/{agreement_id}/void",
                             {}, headers)

    # --- open negotiations (NSA) ---
    def create_open_negotiation(self, payload, headers):
        return self._request("POST", "/open-negotiations", payload, headers)

    def get_open_negotiation(self, on_id, headers):
        return self._request("GET", f"/open-negotiations/{on_id}", headers=headers)

    def list_open_negotiations(self, headers, params=None):
        return self._request("GET", "/open-negotiations", headers=headers, params=params)

    def agree_open_negotiation(self, on_id, payload, headers):
        return self._request("POST", f"/open-negotiations/{on_id}/agree", payload, headers)

    # --- IDR ---
    def create_idr_submission(self, payload, headers):
        return self._request("POST", "/idr-submissions", payload, headers)

    def get_idr_submission(self, idr_id, headers):
        return self._request("GET", f"/idr-submissions/{idr_id}", headers=headers)

    def list_idr_submissions(self, headers, params=None):
        return self._request("GET", "/idr-submissions", headers=headers, params=params)

    def decide_idr_submission(self, idr_id, payload, headers):
        return self._request("POST", f"/idr-submissions/{idr_id}/decide", payload, headers)

    def dismiss_idr_submission(self, idr_id, headers):
        return self._request("POST", f"/idr-submissions/{idr_id}/dismiss", {}, headers)

    # --- appeals ---
    def create_appeal(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def start_review_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/start-review", {}, headers)

    def resolve_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/resolve", payload, headers)

    # --- feed batches ---
    def create_feed_batch(self, payload, headers):
        return self._request("POST", "/feed-batches", payload, headers)

    def get_feed_batch(self, batch_id, headers):
        return self._request("GET", f"/feed-batches/{batch_id}", headers=headers)

    def list_feed_batches(self, headers, params=None):
        return self._request("GET", "/feed-batches", headers=headers, params=params)

    def process_feed_batch(self, batch_id, headers):
        return self._request("POST", f"/feed-batches/{batch_id}/process", {}, headers)

    def fail_feed_batch(self, batch_id, headers):
        return self._request("POST", f"/feed-batches/{batch_id}/fail", {}, headers)

    # --- fee invoices / transparency reports ---
    def create_fee_invoice(self, payload, headers):
        return self._request("POST", "/fee-invoices", payload, headers)

    def get_fee_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{invoice_id}", headers=headers)

    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def issue_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/issue", {}, headers)

    def void_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/void", {}, headers)

    def publish_transparency_report(self, invoice_id, headers):
        return self._request("POST",
                             f"/fee-invoices/{invoice_id}/publish-transparency-report",
                             {}, headers)

    def get_transparency_report(self, report_id, headers):
        return self._request("GET", f"/transparency-reports/{report_id}", headers=headers)

    def list_transparency_reports(self, headers, params=None):
        return self._request("GET", "/transparency-reports", headers=headers, params=params)


api_client = ApiClient()
