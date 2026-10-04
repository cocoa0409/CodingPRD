"""HTTP client for the Healthcare Claims Clearinghouse API.

One method per endpoint the contract declares. Every method returns the raw
response so tests can assert on status codes as well as bodies. Query filters
and pagination go in ``params``; request bodies in ``payload``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with none or with trailing zeroes.
    Comparisons run on the canonical form ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Test-driving capabilities ─────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/clearinghouse/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    def advance_enrollment_to_review(self, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/_enrollments/{enrollment_id}/advance-to-review", {}, headers)

    # ── Providers ─────────────────────────────────────────────────────────

    def create_provider(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/clearinghouse/providers", payload, headers)

    def list_providers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/providers", params, headers)

    def get_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}", None, headers)

    def activate_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/activate", {}, headers)

    def suspend_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/suspend", {}, headers)

    def reinstate_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/reinstate", {}, headers)

    def terminate_provider(self, provider_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/terminate", {}, headers)

    # ── Submitter credentials ─────────────────────────────────────────────

    def create_credential(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/credentials", payload, headers)

    def list_credentials(self, provider_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}/credentials", params, headers)

    def get_credential(self, provider_id: str, credential_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}/credentials/{credential_id}", None, headers)

    def submit_credential(self, provider_id: str, credential_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/credentials/{credential_id}/submit", {}, headers)

    def revoke_credential(self, provider_id: str, credential_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/credentials/{credential_id}/revoke", {}, headers)

    def list_all_credentials(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/credentials", params, headers)

    # ── Payers ────────────────────────────────────────────────────────────

    def create_payer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/clearinghouse/payers", payload, headers)

    def list_payers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/payers", params, headers)

    def get_payer(self, payer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/payers/{payer_id}", None, headers)

    # ── Pricing tiers ─────────────────────────────────────────────────────

    def create_pricing_tier(self, payer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/payers/{payer_id}/pricing-tiers", payload, headers)

    def list_pricing_tiers(self, payer_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/payers/{payer_id}/pricing-tiers", params, headers)

    def list_all_pricing_tiers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/pricing-tiers", params, headers)

    # ── Edit rules ────────────────────────────────────────────────────────

    def create_edit_rule(self, payer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/payers/{payer_id}/edit-rules", payload, headers)

    def list_edit_rules(self, payer_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/payers/{payer_id}/edit-rules", params, headers)

    def list_all_edit_rules(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/edit-rules", params, headers)

    # ── Enrollments ───────────────────────────────────────────────────────

    def create_enrollment(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/enrollments", payload, headers)

    def list_enrollments(self, provider_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}/enrollments", params, headers)

    def get_enrollment(self, provider_id: str, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}/enrollments/{enrollment_id}", None, headers)

    def get_enrollment_by_id(self, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/enrollments/{enrollment_id}", None, headers)

    def submit_enrollment(self, provider_id: str, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/enrollments/{enrollment_id}/submit", {}, headers)

    def resubmit_enrollment(self, provider_id: str, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/enrollments/{enrollment_id}/resubmit", {}, headers)

    def cancel_enrollment(self, provider_id: str, enrollment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/enrollments/{enrollment_id}/cancel", {}, headers)

    def record_payer_decision(self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/enrollments/{enrollment_id}/payer-decision", payload, headers)

    def list_all_enrollments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/enrollments", params, headers)

    # ── Claims ────────────────────────────────────────────────────────────

    def create_claim(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/claims", payload, headers)

    def list_claims(self, provider_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}/claims", params, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/claims/{claim_id}", None, headers)

    def forward_claim(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/claims/{claim_id}/forward", payload, headers)

    def ack_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/claims/{claim_id}/payer-ack", {}, headers)

    def reject_claim(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/claims/{claim_id}/payer-reject", payload, headers)

    def list_all_claims(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/claims", params, headers)

    # ── Remittance advices ────────────────────────────────────────────────

    def create_remittance(self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/claims/{claim_id}/remittances", payload, headers)

    def list_remittances_for_claim(self, claim_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/claims/{claim_id}/remittances", params, headers)

    def get_remittance(self, remittance_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/remittances/{remittance_id}", None, headers)

    def post_remittance(self, remittance_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/remittances/{remittance_id}/post", {}, headers)

    def void_remittance(self, remittance_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/remittances/{remittance_id}/void", {}, headers)

    def list_all_remittances(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/remittances", params, headers)

    # ── Posting files ─────────────────────────────────────────────────────

    def list_posting_files(self, remittance_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/remittances/{remittance_id}/posting-files", params, headers)

    def get_posting_file(self, posting_file_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/posting-files/{posting_file_id}", None, headers)

    def deliver_posting_file(self, posting_file_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/posting-files/{posting_file_id}/deliver", {}, headers)

    def list_all_posting_files(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/posting-files", params, headers)

    # ── Eligibility inquiries ─────────────────────────────────────────────

    def create_eligibility_inquiry(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/eligibility", payload, headers)

    def list_eligibility_inquiries(self, provider_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}/eligibility", params, headers)

    def get_eligibility_inquiry(self, inquiry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/eligibility/{inquiry_id}", None, headers)

    def respond_to_inquiry(self, inquiry_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/eligibility/{inquiry_id}/respond", payload, headers)

    def list_all_eligibility_inquiries(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/eligibility", params, headers)

    # ── Connectivity outages ──────────────────────────────────────────────

    def create_outage(self, payer_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/payers/{payer_id}/outages", payload, headers)

    def list_outages(self, payer_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/payers/{payer_id}/outages", params, headers)

    def get_outage(self, outage_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/outages/{outage_id}", None, headers)

    def resolve_outage(self, outage_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/outages/{outage_id}/resolve", {}, headers)

    def list_outage_notifications(self, outage_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/outages/{outage_id}/notifications", params, headers)

    def list_all_outages(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/outages", params, headers)

    # ── Outage notifications ──────────────────────────────────────────────

    def get_notification(self, notification_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/notifications/{notification_id}", None, headers)

    def list_all_notifications(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/notifications", params, headers)

    # ── Usage invoices ────────────────────────────────────────────────────

    def create_usage_invoice(self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/providers/{provider_id}/usage-invoices", payload, headers)

    def list_usage_invoices(self, provider_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/clearinghouse/providers/{provider_id}/usage-invoices", params, headers)

    def get_usage_invoice(self, invoice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clearinghouse/usage-invoices/{invoice_id}", None, headers)

    def finalize_usage_invoice(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/usage-invoices/{invoice_id}/finalize", payload, headers)

    def record_payment(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/usage-invoices/{invoice_id}/record-payment", payload, headers)

    def void_usage_invoice(self, invoice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/clearinghouse/usage-invoices/{invoice_id}/void", {}, headers)

    def list_all_usage_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/clearinghouse/usage-invoices", params, headers)


api_client = ApiClient()
