"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Channel partner program endpoints."""

    # ------------------------------------------------------------ logical clock
    def set_current_utc(self, current_utc: str, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc - moves the server's logical clock."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers or {}
        )

    # ------------------------------------------------------------ Partner
    def create_partner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/partners", payload, headers)

    def list_partners(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/partners", headers=headers, params=params)

    def get_partner(self, partner_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/partners/{partner_id}", headers=headers)

    def update_partner(self, partner_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/partners/{partner_id}", payload, headers)

    # ------------------------------------------------------------ CertificationRecord
    def create_certification(self, partner_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/partners/{partner_id}/certifications", payload, headers)

    def list_partner_certifications(
        self, partner_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/partners/{partner_id}/certifications", headers=headers, params=params
        )

    def list_certifications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def get_certification(self, certification_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/certifications/{certification_id}", headers=headers)

    # ------------------------------------------------------------ Account
    def create_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/accounts", payload, headers)

    def list_accounts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def declare_direct_pursuit(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/accounts/{account_id}/direct-pursuit", payload, headers)

    def list_account_deal_registrations(
        self, account_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/accounts/{account_id}/deal-registrations", headers=headers, params=params
        )

    def list_account_conflict_cases(
        self, account_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/accounts/{account_id}/conflict-cases", headers=headers, params=params
        )

    # ------------------------------------------------------------ AccountMapping
    def create_account_mapping(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/account-mappings", payload, headers)

    def list_account_mappings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/account-mappings", headers=headers, params=params)

    def get_account_mapping(self, mapping_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/account-mappings/{mapping_id}", headers=headers)

    def respond_account_mapping(
        self, mapping_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/account-mappings/{mapping_id}/respond", payload, headers)

    # ------------------------------------------------------------ DealRegistration
    def create_deal_registration(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/deal-registrations", payload, headers)

    def list_deal_registrations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/deal-registrations", headers=headers, params=params)

    def get_deal_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/deal-registrations/{registration_id}", headers=headers)

    def submit_deal_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/deal-registrations/{registration_id}/submit", {}, headers)

    def review_deal_registration(
        self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/deal-registrations/{registration_id}/review", payload, headers
        )

    def decide_deal_registration(
        self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/deal-registrations/{registration_id}/decision", payload, headers
        )

    def convert_deal_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/deal-registrations/{registration_id}/convert", {}, headers)

    def list_registration_special_pricing_requests(
        self, registration_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/deal-registrations/{registration_id}/special-pricing-requests",
            headers=headers,
            params=params,
        )

    def list_registration_order_invoices(
        self, registration_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/deal-registrations/{registration_id}/order-invoices",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ ConflictCase
    def list_conflict_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conflict-cases", headers=headers, params=params)

    def get_conflict_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conflict-cases/{case_id}", headers=headers)

    def escalate_conflict_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/conflict-cases/{case_id}/escalate", payload, headers)

    def resolve_conflict_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/conflict-cases/{case_id}/resolve", payload, headers)

    # ------------------------------------------------------------ SpecialPricingRequest
    def create_special_pricing_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/special-pricing-requests", payload, headers)

    def list_special_pricing_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/special-pricing-requests", headers=headers, params=params)

    def get_special_pricing_request(self, spr_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/special-pricing-requests/{spr_id}", headers=headers)

    def decide_special_pricing_request(
        self, spr_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/special-pricing-requests/{spr_id}/decision", payload, headers
        )

    # ------------------------------------------------------------ MdfAllocation
    def create_mdf_allocation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdf-allocations", payload, headers)

    def list_mdf_allocations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdf-allocations", headers=headers, params=params)

    def get_mdf_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdf-allocations/{allocation_id}", headers=headers)

    def close_mdf_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/mdf-allocations/{allocation_id}/close", {}, headers)

    def list_allocation_mdf_claims(
        self, allocation_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/mdf-allocations/{allocation_id}/mdf-claims", headers=headers, params=params
        )

    # ------------------------------------------------------------ MdfClaim / ProofOfPerformance
    def create_mdf_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mdf-claims", payload, headers)

    def list_mdf_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mdf-claims", headers=headers, params=params)

    def get_mdf_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mdf-claims/{claim_id}", headers=headers)

    def create_proof(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/mdf-claims/{claim_id}/proofs", payload, headers)

    def list_claim_proofs(
        self, claim_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/mdf-claims/{claim_id}/proofs", headers=headers, params=params
        )

    def get_proof(self, proof_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/proofs/{proof_id}", headers=headers)

    def verify_proof(self, claim_id: str, proof_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/mdf-claims/{claim_id}/proofs/{proof_id}/verify", {}, headers
        )

    def validate_mdf_claim(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/mdf-claims/{claim_id}/validate", payload, headers)

    def settle_mdf_claim(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/mdf-claims/{claim_id}/settlement", payload, headers)

    # ------------------------------------------------------------ OrderInvoice
    def create_order_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/order-invoices", payload, headers)

    def list_order_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/order-invoices", headers=headers, params=params)

    def get_order_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/order-invoices/{invoice_id}", headers=headers)

    def invoice_order(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/order-invoices/{invoice_id}/invoice", {}, headers)

    def issue_credit_memo(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/order-invoices/{invoice_id}/credit-memo", payload, headers)

    # ------------------------------------------------------------ PerformanceReview
    def create_performance_review(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/performance-reviews", payload, headers)

    def list_performance_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/performance-reviews", headers=headers, params=params)

    def get_performance_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/performance-reviews/{review_id}", headers=headers)

    def remediate_performance_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/performance-reviews/{review_id}/remediate", payload, headers
        )

    def decide_performance_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/performance-reviews/{review_id}/decision", payload, headers)


api_client = ApiClient()
