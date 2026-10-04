"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/work-number"


class ApiClient(GenericApiClient):
    # --- logical clock / directives ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def expire_batch(self, batch_id, headers):
        return self._request("POST", f"{BASE}/directives/expire-batch", {"payroll_feed_batch_id": batch_id}, headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", f"{BASE}/employers", payload, headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", f"{BASE}/employers", headers=headers, params=params)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"{BASE}/employers/{employer_id}", headers=headers)

    def freeze_employer(self, employer_id, reason_code, headers):
        return self._request("POST", f"{BASE}/employers/{employer_id}/freeze", {"reason_code": reason_code}, headers)

    def unfreeze_employer(self, employer_id, outcome, headers):
        return self._request("POST", f"{BASE}/employers/{employer_id}/unfreeze", {"outcome": outcome}, headers)

    # --- RecordLayout ---
    def create_layout(self, payload, headers):
        return self._request("POST", f"{BASE}/record-layouts", payload, headers)

    def list_layouts(self, headers, params=None):
        return self._request("GET", f"{BASE}/record-layouts", headers=headers, params=params)

    def get_layout(self, layout_id, headers):
        return self._request("GET", f"{BASE}/record-layouts/{layout_id}", headers=headers)

    def patch_layout(self, layout_id, payload, headers):
        return self._request("PATCH", f"{BASE}/record-layouts/{layout_id}", payload, headers)

    def verify_layout(self, layout_id, headers):
        return self._request("POST", f"{BASE}/record-layouts/{layout_id}/verify", {}, headers)

    # --- PayrollFeedBatch ---
    def create_batch(self, payload, headers):
        return self._request("POST", f"{BASE}/payroll-feed-batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", f"{BASE}/payroll-feed-batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"{BASE}/payroll-feed-batches/{batch_id}", headers=headers)

    def patch_batch_records(self, batch_id, rejected_entries, headers):
        return self._request("PATCH", f"{BASE}/payroll-feed-batches/{batch_id}/records", {"rejected_entries": rejected_entries}, headers)

    def reject_batch(self, batch_id, headers):
        return self._request("POST", f"{BASE}/payroll-feed-batches/{batch_id}/reject", {}, headers)

    def validate_batch(self, batch_id, headers):
        return self._request("POST", f"{BASE}/payroll-feed-batches/{batch_id}/validate", {}, headers)

    # --- EmploymentRecord ---
    def create_record(self, payload, headers):
        return self._request("POST", f"{BASE}/employment-records", payload, headers)

    def list_records(self, headers, params=None):
        return self._request("GET", f"{BASE}/employment-records", headers=headers, params=params)

    def get_record(self, record_id, headers):
        return self._request("GET", f"{BASE}/employment-records/{record_id}", headers=headers)

    def reconfirm_record(self, record_id, headers):
        return self._request("POST", f"{BASE}/employment-records/{record_id}/reconfirm", {}, headers)

    def retain_record(self, record_id, headers):
        return self._request("POST", f"{BASE}/employment-records/{record_id}/retain", {}, headers)

    # --- CoveredWorker ---
    def create_worker(self, payload, headers):
        return self._request("POST", f"{BASE}/covered-workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", f"{BASE}/covered-workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"{BASE}/covered-workers/{worker_id}", headers=headers)

    def opt_out_worker(self, worker_id, headers):
        return self._request("POST", f"{BASE}/covered-workers/{worker_id}/opt-out", {}, headers)

    def opt_in_worker(self, worker_id, headers):
        return self._request("POST", f"{BASE}/covered-workers/{worker_id}/opt-in", {}, headers)

    # --- Verifier ---
    def create_verifier(self, payload, headers):
        return self._request("POST", f"{BASE}/verifiers", payload, headers)

    def list_verifiers(self, headers, params=None):
        return self._request("GET", f"{BASE}/verifiers", headers=headers, params=params)

    def get_verifier(self, verifier_id, headers):
        return self._request("GET", f"{BASE}/verifiers/{verifier_id}", headers=headers)

    def accredit_verifier(self, verifier_id, headers):
        return self._request("POST", f"{BASE}/verifiers/{verifier_id}/accredit", {}, headers)

    def authorize_verifier(self, verifier_id, headers):
        return self._request("POST", f"{BASE}/verifiers/{verifier_id}/authorize", {}, headers)

    def escrow_adjustment(self, verifier_id, amount_cents, headers):
        return self._request("POST", f"{BASE}/verifiers/{verifier_id}/escrow-adjustments", {"amount_cents": amount_cents}, headers)

    # --- VerificationProduct ---
    def create_product(self, payload, headers):
        return self._request("POST", f"{BASE}/verification-products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{BASE}/verification-products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{BASE}/verification-products/{product_id}", headers=headers)

    # --- ConsumerAuthorization ---
    def create_authorization(self, payload, headers):
        return self._request("POST", f"{BASE}/consumer-authorizations", payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", f"{BASE}/consumer-authorizations", headers=headers, params=params)

    def get_authorization(self, auth_id, headers):
        return self._request("GET", f"{BASE}/consumer-authorizations/{auth_id}", headers=headers)

    # --- VerificationRequest ---
    def create_request(self, payload, headers):
        return self._request("POST", f"{BASE}/verification-requests", payload, headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", f"{BASE}/verification-requests", headers=headers, params=params)

    def get_request(self, request_id, headers):
        return self._request("GET", f"{BASE}/verification-requests/{request_id}", headers=headers)

    def permit_request(self, request_id, consumer_authorization_id, headers):
        return self._request("POST", f"{BASE}/verification-requests/{request_id}/permit", {"consumer_authorization_id": consumer_authorization_id}, headers)

    def validate_currency(self, request_id, headers):
        return self._request("POST", f"{BASE}/verification-requests/{request_id}/validate-currency", {}, headers)

    def reconsent_request(self, request_id, headers):
        return self._request("POST", f"{BASE}/verification-requests/{request_id}/reconsent", {}, headers)

    def decline_request(self, request_id, decline_reason, headers):
        return self._request("POST", f"{BASE}/verification-requests/{request_id}/decline", {"decline_reason": decline_reason}, headers)

    def reverse_request(self, request_id, headers):
        return self._request("POST", f"{BASE}/verification-requests/{request_id}/reverse", {}, headers)

    # --- VerificationResponse ---
    def create_response(self, verification_request_id, headers):
        return self._request("POST", f"{BASE}/verification-responses", {"verification_request_id": verification_request_id}, headers)

    def list_responses(self, headers, params=None):
        return self._request("GET", f"{BASE}/verification-responses", headers=headers, params=params)

    def get_response(self, response_id, headers):
        return self._request("GET", f"{BASE}/verification-responses/{response_id}", headers=headers)

    # --- ConsumerDisclosure ---
    def create_disclosure(self, covered_worker_id, headers):
        return self._request("POST", f"{BASE}/consumer-disclosures", {"covered_worker_id": covered_worker_id}, headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", f"{BASE}/consumer-disclosures", headers=headers, params=params)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"{BASE}/consumer-disclosures/{disclosure_id}", headers=headers)

    def generate_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"{BASE}/consumer-disclosures/{disclosure_id}/generate", {}, headers)

    # --- RecordDispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", f"{BASE}/record-disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", f"{BASE}/record-disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{BASE}/record-disputes/{dispute_id}", headers=headers)

    def notice_dispute(self, dispute_id, headers):
        return self._request("POST", f"{BASE}/record-disputes/{dispute_id}/notice", {}, headers)

    def respond_dispute(self, dispute_id, resolution, headers):
        return self._request("POST", f"{BASE}/record-disputes/{dispute_id}/respond", {"resolution": resolution}, headers)

    def reopen_dispute(self, dispute_id, resolution, headers):
        return self._request("POST", f"{BASE}/record-disputes/{dispute_id}/reopen", {"resolution": resolution}, headers)

    # --- Compensation ---
    def create_accrual(self, payload, headers):
        return self._request("POST", f"{BASE}/contributor-compensations", payload, headers)

    def list_accruals(self, headers, params=None):
        return self._request("GET", f"{BASE}/contributor-compensations", headers=headers, params=params)

    def get_accrual(self, accrual_id, headers):
        return self._request("GET", f"{BASE}/contributor-compensations/{accrual_id}", headers=headers)

    def create_settlement(self, payload, headers):
        return self._request("POST", f"{BASE}/compensation-settlements", payload, headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"{BASE}/compensation-settlements/{settlement_id}/void", {}, headers)

    # --- DataCurrencyReview ---
    def create_review(self, payload, headers):
        return self._request("POST", f"{BASE}/data-currency-reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", f"{BASE}/data-currency-reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"{BASE}/data-currency-reviews/{review_id}", headers=headers)

    def escalate_review(self, review_id, headers):
        return self._request("POST", f"{BASE}/data-currency-reviews/{review_id}/escalate", {}, headers)

    def rescore_review(self, review_id, headers):
        return self._request("POST", f"{BASE}/data-currency-reviews/{review_id}/rescore", {}, headers)

    # --- VerificationAttestation ---
    def create_attestation(self, payload, headers):
        return self._request("POST", f"{BASE}/verification-attestations", payload, headers)

    def list_attestations(self, headers, params=None):
        return self._request("GET", f"{BASE}/verification-attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"{BASE}/verification-attestations/{attestation_id}", headers=headers)


api_client = ApiClient()