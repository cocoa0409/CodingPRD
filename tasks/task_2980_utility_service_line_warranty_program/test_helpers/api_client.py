"""One method per endpoint of PRD §4.

Every collection is mounted flat at the API root (PRD §2.11) and a sub-resource
action is a verb segment beneath the single resource it acts on, so the paths
below are the complete paths with no version prefix.

Methods return the raw ``requests.Response`` so that tests can assert status
codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Endpoint surface of the Utility Service Line Warranty Program API."""

    # ── Partners (PRD §3.1) ──

    def list_partners(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/partners", headers=headers, params=params)

    def get_partner(self, partner_id: str, headers: Headers):
        return self._request("GET", f"/partners/{partner_id}", headers=headers)

    def create_partner(self, payload: Payload, headers: Headers):
        return self._request("POST", "/partners", payload, headers)

    def change_partner_status(self, partner_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/partners/{partner_id}/status-changes", payload, headers)

    # ── Service line products (PRD §3.1) ──

    def list_products(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/service-line-products", headers=headers, params=params)

    def get_product(self, product_id: str, headers: Headers):
        return self._request("GET", f"/service-line-products/{product_id}", headers=headers)

    def create_product(self, payload: Payload, headers: Headers):
        return self._request("POST", "/service-line-products", payload, headers)

    # ── Premises (PRD §3.1) ──

    def list_premises(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/premises", headers=headers, params=params)

    def get_premises(self, premises_id: str, headers: Headers):
        return self._request("GET", f"/premises/{premises_id}", headers=headers)

    def create_premises(self, payload: Payload, headers: Headers):
        return self._request("POST", "/premises", payload, headers)

    # ── Marketing campaigns (PRD §3.2) ──

    def list_campaigns(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id: str, headers: Headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def create_campaign(self, payload: Payload, headers: Headers):
        return self._request("POST", "/campaigns", payload, headers)

    def submit_campaign(self, campaign_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/campaigns/{campaign_id}/submission", payload, headers)

    def decide_campaign(self, campaign_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/campaigns/{campaign_id}/decision", payload, headers)

    def mail_drop(self, campaign_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/mail-drop", payload if payload is not None else {}, headers
        )

    # ── Enrollments (PRD §3.3, §3.4) ──

    def list_enrollments(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id: str, headers: Headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def create_enrollment(self, payload: Payload, headers: Headers):
        return self._request("POST", "/enrollments", payload, headers)

    def cancel_enrollment(self, enrollment_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancellation", payload, headers)

    def create_billing_event(self, enrollment_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/billing-events", payload, headers)

    def create_renewal_notice(self, enrollment_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/renewal-notices", payload, headers)

    # ── Claims (PRD §3.5, §3.8) ──

    def list_claims(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id: str, headers: Headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def create_claim(self, payload: Payload, headers: Headers):
        return self._request("POST", "/claims", payload, headers)

    def triage_claim(self, claim_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/claims/{claim_id}/triage-decision", payload, headers)

    def create_appeal(self, claim_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/claims/{claim_id}/appeals", payload, headers)

    def decide_appeal(self, claim_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/claims/{claim_id}/appeal-decision", payload, headers)

    # ── Contractors and dispatches (PRD §3.6, §3.7) ──

    def list_contractors(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id: str, headers: Headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def create_contractor(self, payload: Payload, headers: Headers):
        return self._request("POST", "/contractors", payload, headers)

    def list_dispatches(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/dispatches", headers=headers, params=params)

    def get_dispatch(self, dispatch_id: str, headers: Headers):
        return self._request("GET", f"/dispatches/{dispatch_id}", headers=headers)

    def create_dispatch(self, claim_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/claims/{claim_id}/dispatches", payload, headers)

    def create_dispatch_event(self, dispatch_id: str, payload: Payload, headers: Headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/events", payload, headers)

    # ── Ledger (PRD §2.10) ──

    def list_ledger_entries(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, ledger_entry_id: str, headers: Headers):
        return self._request("GET", f"/ledger-entries/{ledger_entry_id}", headers=headers)

    # ── Regulator complaints (PRD §3.8) ──

    def list_complaints(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/regulator-complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id: str, headers: Headers):
        return self._request("GET", f"/regulator-complaints/{complaint_id}", headers=headers)

    def create_complaint(self, payload: Payload, headers: Headers):
        return self._request("POST", "/regulator-complaints", payload, headers)

    def respond_to_complaint(self, complaint_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/regulator-complaints/{complaint_id}/response", payload, headers
        )

    def escalate_complaint(self, complaint_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/regulator-complaints/{complaint_id}/escalation", payload, headers
        )

    # ── Operational capabilities (PRD §3.9, §2.5) ──

    def run_nightly(self, headers: Headers, payload: Optional[Payload] = None):
        """POST /operations/nightly-run — "The run takes no inputs." (PRD §3.9)"""
        return self._request(
            "POST", "/operations/nightly-run", payload if payload is not None else {}, headers
        )

    def set_clock(self, to_iso8601: str, headers: Headers):
        """POST /_clock/set_current_utc — supplies ``to_iso8601`` (PRD §2.5)."""
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload: Payload, headers: Headers):
        """Same endpoint, with the body under the caller's full control."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    PRD §2.5 requires instants "rendered with exactly three fractional-second
    digits". Assertions that only care about the *moment* compare canonical
    forms so that a trailing-zero difference is not mistaken for a wrong value;
    the literal three-digit rendering itself is asserted separately.
    """
    if not isinstance(value, str) or not value.endswith("Z"):
        return value
    body = value[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


__all__ = ["ApiClient", "canonical_instant", "requests"]
