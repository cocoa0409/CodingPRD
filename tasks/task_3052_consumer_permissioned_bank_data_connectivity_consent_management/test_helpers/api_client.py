"""HTTP client for the Bank Data Connectivity Consent API.

One method per endpoint the PRD declares. Every method returns the raw
response so tests can assert on the status code as well as the body.
Query filters and pagination go through ``params``; request bodies through
``payload``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but an equal
    instant may legitimately arrive with fewer digits or trailing zeroes.
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
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock ─────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Institutions ──────────────────────────────────────────────────────

    def create_institution(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/institutions", payload, headers)

    def list_institutions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/institutions", params, headers)

    def get_institution(self, institution_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/institutions/{institution_id}", None, headers)

    def recover_institution(self, institution_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/institutions/{institution_id}/recover", {}, headers)

    def start_migration(self, institution_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/institutions/{institution_id}/migration/start", {}, headers)

    def complete_migration(self, institution_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/institutions/{institution_id}/migration/complete", {}, headers)

    # ── Institution agreements ────────────────────────────────────────────

    def create_agreement(self, institution_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/institutions/{institution_id}/agreements", payload, headers)

    def list_agreements(self, institution_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/institutions/{institution_id}/agreements", params, headers)

    def list_institution_breakage_events(
        self, institution_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/institutions/{institution_id}/breakage_events", params, headers)

    def list_institution_connections(
        self, institution_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/institutions/{institution_id}/connections", params, headers)

    # ── Recipients ────────────────────────────────────────────────────────

    def create_recipient(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/recipients", payload, headers)

    def list_recipients(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/recipients", params, headers)

    def get_recipient(self, recipient_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/recipients/{recipient_id}", None, headers)

    def review_recipient(self, recipient_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/recipients/{recipient_id}/review", payload, headers)

    def suspend_recipient(self, recipient_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/recipients/{recipient_id}/suspend", {}, headers)

    def list_recipient_consents(
        self, recipient_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/recipients/{recipient_id}/consents", params, headers)

    def list_recipient_webhook_events(
        self, recipient_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/recipients/{recipient_id}/webhook_events", params, headers)

    # ── Data product tiers and enrollment ─────────────────────────────────

    def create_tier(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/tiers", payload, headers)

    def list_tiers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/tiers", params, headers)

    def get_tier(self, tier_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/tiers/{tier_id}", None, headers)

    def create_tier_assignment(self, recipient_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/recipients/{recipient_id}/tier_assignments", payload, headers)

    def list_tier_assignments(
        self, recipient_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/recipients/{recipient_id}/tier_assignments", params, headers)

    def list_tier_enrollments(
        self, tier_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/tiers/{tier_id}/tier_assignments", params, headers)

    # ── Consents ──────────────────────────────────────────────────────────

    def create_consent(self, recipient_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/recipients/{recipient_id}/consents", payload, headers)

    def list_consents(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/consents", params, headers)

    def get_consent(self, consent_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/consents/{consent_id}", None, headers)

    def revoke_consent(self, consent_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/consents/{consent_id}/revoke", {}, headers)

    def list_consent_connections(
        self, consent_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/consents/{consent_id}/connections", params, headers)

    def list_consent_grants(
        self, consent_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/consents/{consent_id}/grants", params, headers)

    # ── Connections ───────────────────────────────────────────────────────

    def create_connection(self, institution_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/institutions/{institution_id}/connections", payload, headers)

    def list_connections(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/connections", params, headers)

    def get_connection(self, connection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/connections/{connection_id}", None, headers)

    def complete_auth(self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/complete_auth", payload, headers)

    def reauth_connection(self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/reauth", payload, headers)

    def migrate_connection(self, connection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/migrate", {}, headers)

    def refresh_connection(self, connection_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/connections/{connection_id}/refresh", payload, headers)

    def list_refresh_jobs(
        self, connection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/connections/{connection_id}/refresh_jobs", params, headers)

    def get_cost_summary(
        self, connection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/connections/{connection_id}/cost_summary", params, headers)

    def list_connection_webhook_events(
        self, connection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/connections/{connection_id}/webhook_events", params, headers)

    def list_connection_breakage_events(
        self, connection_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/connections/{connection_id}/breakage_events", params, headers)

    # ── Webhook delivery ──────────────────────────────────────────────────

    def deliver_webhook_event(self, webhook_event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/webhook_events/{webhook_event_id}/deliver", {}, headers)

    # ── Data deletion ─────────────────────────────────────────────────────

    def create_deletion_request(self, consent_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/consents/{consent_id}/deletion_requests", {}, headers)

    def list_deletion_requests(
        self, consent_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/consents/{consent_id}/deletion_requests", params, headers)

    def get_deletion_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/deletion_requests/{request_id}", None, headers)

    def ack_deletion_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/deletion_requests/{request_id}/ack", {}, headers)

    # ── Audit ─────────────────────────────────────────────────────────────

    def list_audit_logs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit_logs", params, headers)


api_client = ApiClient()
